from __future__ import annotations

from ..backends import BackendError, backend_name_for, get_backend
from ..edl import EDL
from ..project import Project
from ..util import info, ok, warn
from .common import PlanError
from .heuristic import plan_heuristic
from .llm import plan_llm

__all__ = ["make_plan", "PlanError", "describe_edl"]


def make_plan(project: Project, backend_name: str | None = None, save: bool = True) -> EDL:
    bname = backend_name_for(project.load(), backend_name)
    edl: EDL | None = None
    if bname not in ("none", "", "heuristic"):
        try:
            backend = get_backend(bname)
            info(f"用 {backend.name}/{backend.text_model} 生成剪辑方案…")
            edl = plan_llm(project, backend)
        except (BackendError, PlanError, ValueError) as e:
            warn(f"AI 方案失败，改用规则方案：{e}")
    if edl is None:
        edl = plan_heuristic(project)
    if save:
        # keep previous versions for comparison/undo
        if project.edl_path.exists():
            hist = project.root / "analysis" / "edl_history"
            hist.mkdir(parents=True, exist_ok=True)
            n = len(list(hist.glob("edl_*.json"))) + 1
            project.edl_path.replace(hist / f"edl_{n:03d}.json")
        edl.save(project.edl_path)
        ok(f"剪辑方案已保存：{project.edl_path}（{len(edl.clips)} 个片段，{edl.total_duration:.1f}s，规划器 {edl.planner}）")
    return edl


def describe_edl(edl: EDL) -> str:
    from ..util import fmt_time

    lines = [f"# 剪辑方案：{edl.title}（{edl.aspect}，{edl.total_duration:.1f}s，风格 {edl.style}，{edl.planner}）", ""]
    lines.append("| # | 时间线 | 段落 | 类型 | 素材 | 源 in-out | 转场 | 特效 | 说明 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for i, (c, (s, e)) in enumerate(zip(edl.clips, edl.timeline()), 1):
        lines.append(f"| {i} | {fmt_time(s)}-{fmt_time(e)} | {c.section} | {c.role} | {c.src.split('/')[-1]} | "
                     f"{c.in_:.1f}-{c.out:.1f} | {c.transition_in.type} | {','.join(c.effects)} | {c.note} |")
    if edl.overlays:
        lines += ["", "## 屏幕文字"] + [f"- {fmt_time(o.start)} [{o.kind}] {o.text}" for o in edl.overlays]
    if edl.subtitles:
        lines += ["", f"## 字幕：{len(edl.subtitles)} 条"]
    if edl.audio:
        lines += ["", "## 音频"] + [f"- {a.kind}: {a.src.split('#')[0].replace(chr(92), '/').split('/')[-1]} @ {fmt_time(a.start)} "
                                    f"时长 {a.duration:.1f}s 音量 {a.volume}" for a in edl.audio]
    if edl.notes:
        lines += ["", "## 提醒"] + [f"- {n}" for n in edl.notes]
    return "\n".join(lines)
