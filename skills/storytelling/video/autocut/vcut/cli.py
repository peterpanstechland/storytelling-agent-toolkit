"""vcut 命令行入口。"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional

import typer

if sys.platform == "win32":  # piped output on Windows defaults to GBK → emoji/符号 crash; force UTF-8
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass

from . import __version__, config  # noqa: E402
from .util import console, info, ok, warn  # noqa: E402

app = typer.Typer(help="autocut（vcut）：storytelling 视频工具包里的项目制自动剪辑（活动 / 商单 / Maker 项目 / Vlog）；用法见 references/auto-edit.md",
                  no_args_is_help=True, add_completion=False, rich_markup_mode="rich",
                  pretty_exceptions_show_locals=False)
music_app = typer.Typer(help="本地曲库（配乐）管理", no_args_is_help=True)
app.add_typer(music_app, name="music")

P = typer.Argument(..., help="项目名或项目文件夹路径")
BACKEND = typer.Option(None, "--backend", "-b", help="AI 后端：none / dashscope / gemini / ollama（默认读项目或全局设置）")


def _open(project: str):
    from .project import Project

    try:
        return Project.open(project)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


@app.command()
def new(name: str = typer.Argument(..., help="项目名（中文可以）"),
        type: str = typer.Option(..., "--type", "-t", help="event（活动）| sponsored（商单）| maker（Maker 项目）| vlog"),
        title: Optional[str] = typer.Option(None, help="视频标题（默认同项目名）"),
        aspect: Optional[str] = typer.Option(None, help="画幅 16:9 / 9:16 / 1:1（默认按类型）"),
        style: Optional[str] = typer.Option(None, help="风格：极致卡点/赛博科技/电影感360/胶片复古/温暖日常/科技感/活力快剪/电影感 或 id（autocut styles）"),
        duration: Optional[float] = typer.Option(None, help="目标时长（秒）"),
        platform: Optional[List[str]] = typer.Option(None, "--platform", "-p", help="发布平台，可多次：B站/抖音/小红书/YouTube"),
        dir: Optional[Path] = typer.Option(None, "--dir", help="项目放在哪个目录（默认 projects_root）")):
    """新建项目：生成 project.yaml 和素材/分析/输出文件夹。"""
    from .project import Project

    if style:
        style = config.get_style(style)["id"]
    try:
        p = Project.create(name, type, parent=dir, title=title, aspect=aspect, style=style, duration=duration, platforms=platform)
    except (FileExistsError, KeyError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    ok(f"项目已创建：{p.root}")
    info("下一步：编辑 project.yaml（主题、brief、功能点等），然后 `autocut shotlist " + str(p.root) + "`")


@app.command()
def shotlist(project: str = P, backend: Optional[str] = BACKEND,
             show: bool = typer.Option(True, help="在终端显示")):
    """生成拍摄清单 shotlist.md（按类型 + brief + 你的设备）。"""
    from .shotlist import generate_shotlist

    p = _open(project)
    text, _ = generate_shotlist(p, backend)
    if show:
        from rich.markdown import Markdown
        console.print(Markdown(text))


@app.command()
def ingest(project: str = P, paths: List[Path] = typer.Argument(..., help="文件或文件夹（可多个）"),
           mode: str = typer.Option("copy", help="copy 复制 | link 硬链接(同盘不占空间) | ref 只登记原路径"),
           as_: str = typer.Option("auto", "--as", help="auto | voiceover（旁白音频）| music（项目配乐）"),
           include_raw360: bool = typer.Option(False, "--include-raw360", help="也把 .insv 原始文件放进项目（不参与剪辑）")):
    """导入素材：读取元数据、识别设备、提示 .insv 需要先导出。"""
    from .ingest import ingest as do_ingest

    p = _open(project)
    do_ingest(p, paths, mode=mode, as_kind=as_, include_raw360=include_raw360)


@app.command()
def analyze(project: str = P, backend: Optional[str] = BACKEND,
            force: bool = typer.Option(False, help="全部重新分析"),
            redo_vision: bool = typer.Option(False, "--redo-vision", help="只重做画面理解"),
            no_asr: bool = typer.Option(False, "--no-asr", help="跳过语音转写"),
            only: Optional[List[str]] = typer.Option(None, help="只分析指定媒体 ID/文件名")):
    """分析素材：镜头切分、关键帧、画质、语音转写、画面理解（增量缓存）。"""
    from .analyze import analyze_project

    p = _open(project)
    analyze_project(p, backend_name=backend, force=force, redo_vision=redo_vision, only=only, do_asr=not no_asr)


@app.command()
def gaps(project: str = P):
    """对照拍摄清单，列出缺少的镜头（补拍提醒）。"""
    from .gaps import print_gaps

    print_gaps(_open(project))


@app.command()
def plan(project: str = P, backend: Optional[str] = BACKEND,
         show: bool = typer.Option(True, help="显示方案表")):
    """生成剪辑方案 edl.json（AI 或规则）。"""
    from .plan import PlanError, describe_edl, make_plan

    p = _open(project)
    try:
        edl = make_plan(p, backend)
    except PlanError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    md = describe_edl(edl)
    (p.root / "edl.md").write_text(md, encoding="utf-8")
    if show:
        from rich.markdown import Markdown
        console.print(Markdown(md))


@app.command()
def render(project: str = P, quick: bool = typer.Option(False, "--quick", help="半分辨率快速预览"),
           encoder: Optional[str] = typer.Option(None, help="auto / h264_nvenc / hevc_nvenc / libx264"),
           subs: Optional[str] = typer.Option(None, help="字幕：burn 烧录 / sidecar 只出 srt / both"),
           out: Optional[Path] = typer.Option(None, help="输出文件路径"),
           no_fx: bool = typer.Option(False, "--no-fx", help="关闭 v2 特效引擎（运镜/特效/自定义转场/360 重构图/音效），只做 v1 快速渲染")):
    """按 edl.json 渲染 MP4 预览（转场、运镜、特效、字幕、配乐闪避、调色）。"""
    from .render import render as do_render

    p = _open(project)
    if not p.edl_path.exists():
        console.print("[red]还没有 edl.json，先运行 autocut plan[/red]")
        raise typer.Exit(1)
    do_render(p, out=out, quick=quick, encoder_pref=encoder, subtitles_mode=subs, use_fx=not no_fx)


@app.command()
def draft(project: str = P, drafts_dir: Optional[Path] = typer.Option(None, help="剪映草稿目录（默认自动）"),
          name: Optional[str] = typer.Option(None, help="草稿名"),
          fcpxml: bool = typer.Option(True, help="同时导出 FCPXML（达芬奇/FCP）")):
    """导出剪映草稿（pyJianYingDraft）+ FCPXML + SRT。"""
    from .edl import EDL
    from .export import export_fcpxml, export_jianying, jianying_available
    from .render import write_srt

    p = _open(project)
    if not p.edl_path.exists():
        console.print("[red]还没有 edl.json，先运行 autocut plan[/red]")
        raise typer.Exit(1)
    edl = EDL.load(p.edl_path)
    p.drafts_dir.mkdir(parents=True, exist_ok=True)
    if edl.subtitles:
        write_srt(edl, p.drafts_dir / f"{edl.project or p.root.name}.srt")
    if jianying_available():
        export_jianying(p, edl, drafts_dir=drafts_dir, name=name)
    else:
        warn("未安装 pyJianYingDraft（pip install -r video/requirements-autocut-optional.txt），跳过剪映草稿。")
    if fcpxml:
        export_fcpxml(p, edl)


@app.command()
def run(project: str = P, backend: Optional[str] = BACKEND,
        quick: bool = typer.Option(False, "--quick", help="快速预览渲染"),
        no_draft: bool = typer.Option(False, "--no-draft", help="不导出草稿"),
        no_asr: bool = typer.Option(False, "--no-asr", help="跳过语音转写")):
    """一条龙：analyze → gaps → plan → render → draft。"""
    from .analyze import analyze_project
    from .gaps import find_gaps

    p = _open(project)
    analyze_project(p, backend_name=backend, do_asr=not no_asr)
    r = find_gaps(p)
    miss = [i["name"] for i in r["items"] if i["required"] and i["status"] != "ok"]
    if miss:
        warn(f"还缺 {len(miss)} 个必拍镜头（详见 analysis/gaps.md）：{'、'.join(miss[:6])}{'…' if len(miss) > 6 else ''}")
    plan(project=str(p.root), backend=backend, show=False)
    render(project=str(p.root), quick=quick, encoder=None, subs=None, out=None)
    if not no_draft:
        draft(project=str(p.root), drafts_dir=None, name=None, fcpxml=True)


@app.command("export-edit")
def export_edit_cmd(project: str = P, out: Optional[Path] = typer.Option(None, help="输出 edit.json（默认 <项目>/edit.json）"),
                    fit: str = typer.Option("cover", help="cover 裁切铺满 / contain 留黑边")):
    """把 edl.json 导出成 toolkit 的 edit.json v1，可交给 `video/run render`（有损，会列出丢掉的内容）。"""
    from .bridge import export_edit
    from .edl import EDL

    p = _open(project)
    if not p.edl_path.exists():
        console.print("[red]还没有 edl.json，先运行 plan[/red]")
        raise typer.Exit(1)
    plan_, warns = export_edit(p, EDL.load(p.edl_path), out or (p.root / "edit.json"), fit=fit)
    ok(f"edit.json：{out or p.root / 'edit.json'}（{len(plan_['clips'])} 个片段，{len(plan_['captions'])} 条字幕）")
    for w in warns:
        warn(w)


@app.command("import-edit")
def import_edit_cmd(project: str = P, plan_file: Path = typer.Argument(..., help="toolkit edit.json（version 1）"),
                    mode: str = typer.Option("ref", help="素材入库方式：ref 只引用原路径 / copy / link"),
                    style: Optional[str] = typer.Option(None, help="套用的风格（默认项目风格）")):
    """把 toolkit 的 edit.json 导入项目 edl.json（素材入库、字幕与配乐一并带入）。旧 edl.json 会存进 analysis/edl_history。"""
    from .bridge import import_edit, save_edl

    p = _open(project)
    edl, notes = import_edit(p, plan_file, mode=mode, style=style)
    path = save_edl(p, edl)
    ok(f"已导入 {len(edl.clips)} 个片段 → {path}（{edl.total_duration:.1f}s）")
    for n in notes:
        warn(n)


@app.command("import-index")
def import_index_cmd(project: str = P, manifest: Path = typer.Argument(..., help="`video/run inspect` 输出的 manifest.json"),
                     mode: str = typer.Option("ref", help="ref 只引用原路径 / copy / link")):
    """把 toolkit inspect 索引过的视频入库（之后 analyze 做镜头切分与画面理解）。"""
    from .bridge import import_index

    import_index(_open(project), manifest, mode=mode)


@app.command("import-transcript")
def import_transcript_cmd(project: str = P, media: str = typer.Argument(..., help="媒体ID 或文件名"),
                          transcript: Path = typer.Argument(..., help="`video/run transcribe` 输出的 transcript.json")):
    """导入 toolkit 的转写结果；analyze 会复用它而不再重复转写（需要重新分析：analyze --force）。"""
    from .bridge import import_transcript

    ok(f"已导入：{import_transcript(_open(project), media, transcript)}")


@app.command("import-narration")
def import_narration_cmd(project: str = P, narration_dir: Path = typer.Argument(..., help="`video/run narrate` 输出目录")):
    """把 toolkit narrate 的 narration.wav + 字幕加进 edl.json 的旁白轨（配乐自动开启闪避）。"""
    from .bridge import import_narration
    from .edl import EDL

    p = _open(project)
    edl = EDL.load(p.edl_path)
    for n in import_narration(p, edl, narration_dir):
        info(n)
    edl.save(p.edl_path)
    ok("旁白已加入 edl.json")


@app.command()
def status(project: str = P):
    """项目概况：素材、分析进度、方案、输出。"""
    from .util import read_json

    p = _open(project)
    d = p.load()
    media = p.media()
    vids = [m for m in media if m["kind"] == "video"]
    analyzed = [m for m in vids if (p.analysis_dir / f"{m['id']}.json").exists()]
    info(f"[bold]{d.get('title')}[/bold]（{d.get('type_name')}，{d.get('aspect')}，目标 {d.get('target_duration')}s，风格 {d.get('style')}）")
    info(f"  素材：视频 {len(vids)}（已分析 {len(analyzed)}），音频 {sum(m['kind'] == 'audio' for m in media)}，"
         f"图片 {sum(m['kind'] == 'image' for m in media)}，待导出 .insv {sum(bool(m.get('needs_export')) for m in media)}")
    by_dev: dict[str, float] = {}
    for m in vids:
        k = (m.get("device") or {}).get("label", "未知")
        by_dev[k] = by_dev.get(k, 0) + float((m.get("probe") or {}).get("duration") or 0)
    for k, v in by_dev.items():
        info(f"    {k}: {v / 60:.1f} 分钟")
    if p.edl_path.exists():
        e = read_json(p.edl_path, {})
        info(f"  方案：{len(e.get('clips', []))} 个片段（{e.get('planner')}）")
    renders = sorted(p.renders_dir.glob("*.mp4"))
    if renders:
        info(f"  最新渲染：{renders[-1]}")


@app.command()
def tag(project: str = P, ref: str = typer.Argument(..., help="媒体ID / 文件名 / 媒体ID#镜头序号"),
        cat: Optional[str] = typer.Option(None, "--cat", help=f"类别：{', '.join(config.CATEGORIES)}"),
        desc: Optional[str] = typer.Option(None, help="描述"),
        tags: Optional[List[str]] = typer.Option(None, "--tag", help="标签，可多次"),
        highlight: Optional[float] = typer.Option(None, help="精彩度 0~1"),
        skip: bool = typer.Option(False, help="不要用这段"),
        keep: bool = typer.Option(False, help="一定要用这段")):
    """手动标注素材（写入 analysis/labels.yaml，优先级最高）。"""
    p = _open(project)
    path = p.analysis_dir / "labels.yaml"
    labels = p.labels()
    entry = dict(labels.get(ref) or {})
    if cat:
        if cat not in config.CATEGORIES:
            console.print(f"[red]未知类别 {cat}[/red]")
            raise typer.Exit(1)
        entry["category"] = cat
    if desc:
        entry["desc"] = desc
    if tags:
        entry["tags"] = list(tags)
    if highlight is not None:
        entry["highlight"] = highlight
    if skip:
        entry["skip"] = True
    if keep:
        entry["keep"] = True
    labels[ref] = entry
    config.dump_yaml(labels, path)
    ok(f"已标注 {ref}: {entry}")


@app.command("contact-sheet")
def contact_sheet(project: str = P):
    """生成关键帧拼图（analysis/contact_XX.jpg），方便人或 Agent 快速浏览素材。"""
    from .contact import contact_sheets

    for pth in contact_sheets(_open(project)):
        ok(str(pth))


@app.command()
def probe(file: Path = typer.Argument(..., help="媒体文件")):
    """查看文件元数据和设备识别结果（用于完善 config/devices.yaml）。"""
    from .devices import detect_device
    from .media import probe as do_probe

    pi = do_probe(file)
    d = detect_device(file, pi)
    info(f"[bold]{file.name}[/bold]  {pi.kind}  {pi.display_size[0]}x{pi.display_size[1]}  {pi.fps}fps  {pi.duration:.2f}s  "
         f"{pi.vcodec}/{pi.acodec}  旋转 {pi.rotation}°  {pi.bit_depth}bit {pi.color_transfer}")
    info(f"设备：{d['label']}（{d['id']}，置信度 {d['confidence']}，依据：{'、'.join(d['reasons']) or '无'}）")
    for k, v in sorted(pi.tags.items()):
        info(f"  {k} = {v}")


@app.command()
def devices():
    """列出设备配置（config/devices.yaml）。"""
    for d in config.devices():
        flag = "✓" if d.get("available", True) else "✗（不可用）"
        info(f"{flag} {d['id']:<12} {d.get('label')}  [{d.get('kind')}]  擅长：{', '.join(d.get('strengths') or [])}")
    info(f"配置文件：{config.config_dir() / 'devices.yaml'}")


@app.command()
def styles():
    """列出风格预设和视频类型模板。"""
    info("[bold]风格[/bold]")
    for s in config.styles().values():
        m = s.get("motion") or {}
        info(f"  {s['id']:<14} {s.get('name')}（力度 {m.get('intensity', '-')}）：{s.get('description', '')}")
    info("[bold]类型[/bold]")
    for t in config.type_templates().values():
        info(f"  {t['id']:<10} {t.get('name')}：{t.get('description', '')}")


@music_app.command("scan")
def music_scan(folder: Optional[Path] = typer.Argument(None, help="曲库目录（默认 settings 里的 music.library）"),
               no_beats: bool = typer.Option(False, "--no-beats", help="不做节拍检测")):
    """扫描曲库：时长、BPM/节拍（卡点用）、按文件夹名/文件名打情绪标签。"""
    from .music import scan_library

    scan_library(folder, with_beats=not no_beats)


@app.command()
def doctor():
    """检查运行环境（FFmpeg、编码器、Whisper/CUDA、剪映、API Key）。"""
    from .analyze.audio import asr_available
    from .export import jianying_available
    from .media import ffmpeg_bin, has_encoder, run as run_cmd

    info(f"autocut（vcut）{__version__}  Python {sys.version.split()[0]}  {sys.platform}")
    info(f"配置目录：{config.config_dir()}")
    try:
        v = run_cmd([ffmpeg_bin(), "-version"]).stdout.decode("utf-8", "replace").splitlines()[0]
        ok(v)
    except Exception as e:  # noqa: BLE001
        warn(f"找不到 FFmpeg：{e}")
    for enc in ("h264_nvenc", "hevc_nvenc", "libx264"):
        (ok if has_encoder(enc) else warn)(f"编码器 {enc}: {'可用' if has_encoder(enc) else '不可用'}")
    if asr_available():
        try:
            import ctranslate2
            n = ctranslate2.get_cuda_device_count()
            ok(f"faster-whisper 已安装，CUDA 设备数：{n}")
        except Exception as e:  # noqa: BLE001
            warn(f"faster-whisper 已安装，但 ctranslate2 检测失败：{e}")
    else:
        warn("未安装 faster-whisper（pip install -r video/requirements-asr.txt）")
    (ok if jianying_available() else warn)(f"pyJianYingDraft：{'已安装' if jianying_available() else '未安装（pip install -r video/requirements-autocut-optional.txt）'}")
    jd = config.jianying_drafts_dir()
    info(f"剪映草稿目录：{jd}（{'存在' if jd and jd.exists() else '不存在/未配置'}）")
    for k in ("DASHSCOPE_API_KEY", "GEMINI_API_KEY"):
        info(f"{k}: {'已设置' if os.environ.get(k) else '未设置'}")
    info(f"默认后端：{config.settings().get('backend')}；项目目录：{config.projects_root()}")
    # v2
    try:
        import cv2

        from .fx.track import Detector, yunet_path
        info(f"OpenCV {cv2.__version__}；主体检测器：{Detector().kind}；YuNet：{'有' if yunet_path() else '无（autocut models fetch yunet）'}")
    except Exception as e:  # noqa: BLE001
        warn(f"主体检测器初始化失败：{e}")
    try:
        filt = run_cmd([ffmpeg_bin(), "-hide_banner", "-filters"]).stdout.decode("utf-8", "replace")
        (ok if " v360 " in filt else warn)(f"ffmpeg v360 滤镜：{'可用（x5-stitch）' if ' v360 ' in filt else '不可用'}")
        (ok if " ass " in filt else warn)(f"ffmpeg ass 字幕滤镜：{'可用' if ' ass ' in filt else '不可用（标题/字幕无法烧录）'}")
    except Exception:  # noqa: BLE001
        pass
    lib = (config.settings().get("sfx") or {}).get("library") or os.environ.get("VCUT_SFX_LIBRARY") or ""
    info(f"音效库：{lib or '未配置（自动合成 whoosh/hit/riser 等）'}")


models_app = typer.Typer(help="本地小模型（主体跟踪用）", no_args_is_help=True)
app.add_typer(models_app, name="models")


@models_app.command("fetch")
def models_fetch(name: str = typer.Argument("yunet", help="目前支持：yunet（OpenCV 人脸检测，约 230KB）")):
    """下载跟踪模型到本地模型目录（国内网络可设 VCUT_YUNET_URL 指向镜像）。"""
    from .fx.track import fetch_yunet

    if name != "yunet":
        warn("只支持 yunet。YOLO 请自行准备 ONNX（如 yolov8n.onnx / yolo11n.onnx）并在 settings.yaml 的 track.yolo_model 填路径。")
        raise typer.Exit(1)
    ok(f"已下载：{fetch_yunet()}")


@models_app.command("list")
def models_list():
    """显示检测器状态（YOLO / YuNet / Haar / 运动检测）。"""
    import cv2

    from .fx.track import Detector, models_dir, yunet_path

    info(f"模型目录：{models_dir()}（环境变量 VCUT_MODELS_DIR 可改）  OpenCV {cv2.__version__}")
    info(f"YuNet：{yunet_path() or '未下载（autocut models fetch yunet）'}")
    yolo = (config.settings().get("track") or {}).get("yolo_model") or ""
    info(f"YOLO：{yolo or '未配置（settings.yaml track.yolo_model）'}")
    try:
        import onnxruntime  # noqa: F401
        ok("onnxruntime 已安装")
    except Exception:  # noqa: BLE001
        info("onnxruntime 未安装（可选：pip install onnxruntime；也可用 OpenCV DNN 跑 YOLO）")
    info(f"Haar/HOG：{'可用' if hasattr(cv2, 'CascadeClassifier') else '不可用（OpenCV 5 已移除）'}")
    ok(f"当前自动选择的检测器：{Detector().kind}")


@app.command("fx")
def fx_list():
    """列出 v2 运镜 / 特效 / 转场 / 文字动画词表（EDL 和 AI 规划都用这些名字）。"""
    from .edl import CUSTOM_TRANSITIONS, FX_TYPES, MOVES_2D, MOVES_360, TEXT_ANIMS, XFADE

    for title, d in (("360 运镜（move，仅 360 全景素材）", MOVES_360), ("平面运镜（move）", MOVES_2D),
                     ("特效（fx 窗口 / look 全片质感）", FX_TYPES), ("自定义转场（帧级渲染）", CUSTOM_TRANSITIONS),
                     ("文字动画（overlay.anim / 风格 text_anims）", TEXT_ANIMS)):
        info(f"[bold]{title}[/bold]")
        for k, v in d.items():
            info(f"  {k:<14} {v}")
    info("[bold]xfade 转场[/bold]")
    info("  " + " ".join(k for k in XFADE if k != "cut"))


@app.command("jy-effects")
def jy_effects(kind: Optional[str] = typer.Option(None, help="transition / scene / character / filter / intro / outro / group / text_intro / text_outro / text_loop / mask"),
               search: str = typer.Option("", "--search", "-s", help="名称关键字"),
               free: bool = typer.Option(False, "--free", help="只看免费（非 VIP）")):
    """查看已安装 pyJianYingDraft 里的剪映素材名（风格 jianying 段可用的名字），标出 VIP。"""
    from .export import jianying_available

    if not jianying_available():
        warn("未安装 pyJianYingDraft（pip install -r video/requirements-autocut-optional.txt）")
        raise typer.Exit(1)
    from .export.jianying_fx import catalog

    for k, items in catalog(kind, search, include_vip=not free).items():
        nf = sum(1 for _, v in items if not v)
        info(f"[bold]{k}[/bold]  {len(items)} 个（免费 {nf}）")
        if kind or search:
            info("  " + "  ".join(f"{n}{'[VIP]' if v else ''}" for n, v in items))


@app.command("x5-stitch")
def x5_stitch(file: Path = typer.Argument(..., help="Insta360 原始 .insv（X5/X4 双轨，或 _00_ 文件）"),
              out: Optional[Path] = typer.Option(None, help="输出 2:1 全景 MP4（默认同目录 *_equirect.mp4）"),
              fov: float = typer.Option(193.0, help="鱼眼视场角（度），接缝错位时在 190~200 之间微调"),
              swap: bool = typer.Option(False, "--swap", help="交换前后镜头（画面左右/前后颠倒时用）"),
              back_rot180: bool = typer.Option(False, "--back-rot180", help="后镜头旋转 180°（后半球上下颠倒时用）"),
              roll: float = typer.Option(0.0, help="整体滚转校正（度）"),
              yaw: float = typer.Option(0.0, help="整体水平旋转（度），把主体转到画面中央"),
              width: int = typer.Option(5760, help="输出宽度（高度 = 宽/2）"),
              start: float = typer.Option(0.0, help="从第几秒开始"),
              duration: Optional[float] = typer.Option(None, help="只拼接这么长（秒）"),
              preview_only: bool = typer.Option(False, "--preview-only", help="只输出一张预览 JPG 用来检查镜头顺序/方向")):
    """应急：用 ffmpeg v360 把 .insv 双鱼眼粗拼成 2:1 全景（无防抖/无水平校正/无接缝融合，正式片请用 Insta360 Studio）。"""
    from .x360 import insv_layout, stitch_insv

    lay = insv_layout(file)
    info(f"布局：{lay['layout']}  视频流：{lay['streams']}  音频：{'有' if lay['has_audio'] else '无'}")
    out = out or file.with_name(file.stem + "_equirect.mp4")
    prev = out.with_suffix(".preview.jpg")
    if preview_only:
        stitch_insv(file, out.with_suffix(".tmp.mp4"), fov=fov, swap=swap, back_rot180=back_rot180, roll=roll, yaw=yaw,
                    width=1024, start=start, duration=0.2, preview=prev)
        out.with_suffix(".tmp.mp4").unlink(missing_ok=True)
        ok(f"预览：{prev}（地平线应水平、前方在中央；不对就加 --swap / --back-rot180 / --roll）")
        return
    r = stitch_insv(file, out, fov=fov, swap=swap, back_rot180=back_rot180, roll=roll, yaw=yaw, width=width,
                    start=start, duration=duration, preview=prev)
    ok(f"全景：{r['out']}（编码 {r['encoder']}）  预览：{prev}")
    warn("这是纯几何拼接：没有 FlowState 防抖、没有陀螺仪水平校正、没有光流接缝融合，近处物体在接缝处会错位。")


@app.command()
def preview(file: Path = typer.Argument(..., help="视频文件（360 全景 2:1 或普通视频）"),
            move: str = typer.Option("", help="运镜名，见 autocut fx（360 默认 follow，普通视频默认 push_in）"),
            fx: str = typer.Option("", help="特效，逗号分隔，如 glitch,light_leak,grain"),
            aspect: str = typer.Option("16:9", help="16:9 或 9:16"),
            start: float = typer.Option(0.0, help="源开始秒"),
            dur: float = typer.Option(6.0, help="时长（秒）"),
            track: bool = typer.Option(True, help="360 跟随/英雄镜头先跑主体跟踪"),
            out: Optional[Path] = typer.Option(None, help="输出 MP4（默认同目录 *_preview.mp4）")):
    """单独预览一个运镜/特效（不需要项目），用来挑参数。"""
    import tempfile

    from .edl import EDL, FX, Clip, Move
    from .fx.engine import render_clip
    from .media import is_equirect_size, pick_encoder, probe
    from .project import Project

    pi = probe(file)
    eq = is_equirect_size(*pi.display_size)
    W, H = (1920, 1080) if aspect == "16:9" else (1080, 1920)
    mv = move or ("follow" if eq else "push_in")
    dur = min(dur, max(0.5, float(pi.duration or dur) - start))
    c = Clip(id="p1", media_id="preview", src=str(file.resolve()), **{"in": start}, out=start + dur,
             projection="equirect" if eq else "flat", move=Move(type=mv),
             fx=[FX(type=x.strip()) for x in fx.split(",") if x.strip()])
    if eq and track and mv in ("follow", "hero", "whip360", "planet_intro", "fixed360", "crystal_ball"):
        from .fx.track import track_360
        r = track_360(file, start, dur)
        c.yaw_track = r["track"]
        info(f"主体跟踪：{r['method']}（{len(r['track'])} 个关键点）")
    edl = EDL(width=W, height=H, fps=30, clips=[c])
    out = out or file.with_name(f"{file.stem}_{mv}_{aspect.replace(':', 'x')}_preview.mp4")
    with tempfile.TemporaryDirectory() as td:
        proj = Project(Path(td))
        render_clip(proj, edl, c, 0.0, out, W, H, 30, quick=False, encoder=pick_encoder("auto"), lut_name="",
                    color_filter="", cwd=Path(td))
    ok(f"预览：{out}")


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
