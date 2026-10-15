"""vcut shotlist: 拍摄清单 tailored to type + brief + available devices (LLM optional)."""
from __future__ import annotations

import datetime as _dt

from . import config
from .backends import BackendError, backend_name_for, get_backend
from .devices import available_devices, device_labels_for
from .project import Project
from .util import info, ok, warn

PREP = {
    "common": ["所有设备电池充满、存储卡留够空间（4K 每分钟约 0.5~1GB）", "统一帧率（建议 30fps；要慢动作的镜头单独用 60/120fps）",
               "口播一定要用外接/领夹麦，环境安静；开拍前拍手打板方便对齐", "每个镜头开头和结尾多录 2 秒，方便剪辑和转场"],
    "360": ["X5：擦干净镜头/装镜头保护镜，隐形自拍杆拧紧；导出时在 Insta360 Studio 选 2:1 全景 MP4（开防抖/水平校正），之后可自动运镜"],
    "glasses": ["智能眼镜：确认电量和存储，镜头保持干净；第一视角竖屏，头别晃太快，说话时留意收音"],
    "pocket": ["GO Ultra：带磁吸挂绳/帽夹，第一视角时镜头略朝下（对准手）"],
    "action": ["Ace Pro 2：夜景/低光开 PureVideo，运动镜头开 FlowState 防抖"],
    "phone": ["手机：锁定曝光对焦（AE/AF Lock），关美颜；口播用后置主摄"],
}


def _resolve_devices(kinds: list[str]) -> str:
    labels = device_labels_for([str(k) for k in kinds])
    return " / ".join(labels) if labels else "任意可用设备"


def base_items(pdata: dict) -> list[dict]:
    tmpl = config.get_type(pdata.get("type", "vlog"))
    items = [dict(s) for s in tmpl.get("shots") or []]
    sp = pdata.get("sponsor") or {}
    for i, m in enumerate(sp.get("must_show") or []):
        items.append({"id": f"must_{i + 1}", "section": "experience", "name": f"必拍：{m}", "category": "product",
                      "devices": ["phone", "pocket"], "min_seconds": 6, "required": True, "keywords": [str(m)],
                      "desc": f"品牌要求必须出现：{m}。至少 2 个角度，干净清晰，留足时长。", "source": "brief"})
    for i, m in enumerate(sp.get("key_messages") or []):
        items.append({"id": f"msg_{i + 1}", "section": "messages", "name": f"口播卖点：{m}", "category": "talking_head",
                      "devices": ["phone"], "min_seconds": 4, "required": True, "keywords": [str(m)],
                      "desc": f"用自己的话说出：“{m}”，单独一句，说完停 2 秒；再拍一个对应的画面特写。", "source": "brief"})
    for i, f in enumerate((pdata.get("maker") or {}).get("features") or []):
        items.append({"id": f"feat_{i + 1}", "section": "features", "name": f"功能演示：{f}", "category": "demo",
                      "devices": ["phone", "pocket"], "min_seconds": 8, "required": True, "keywords": [str(f)],
                      "desc": f"完整演示“{f}”：先拍全景再拍特写，口播一句它解决什么问题。", "source": "brief"})
    return items


def llm_items(pdata: dict, items: list[dict], backend) -> tuple[list[dict], list[str]]:
    devs = [{"label": d.get("label"), "kind": d.get("kind"), "strengths": d.get("strengths"), "tips": d.get("tips")}
            for d in available_devices()]
    prompt = (f"项目 brief：{pdata}\n可用设备：{devs}\n已有拍摄清单（不要重复）：{[i['name'] for i in items]}\n"
              f"镜头类别：{list(config.CATEGORIES)}；设备 kind：360/action/pocket/glasses/phone\n"
              "请根据这个具体项目补充 3~8 个最有价值的额外镜头，并给 3~5 条拍摄建议。输出 JSON："
              "{\"extra_shots\":[{\"name\":..,\"section\":段落id,\"category\":类别,\"devices\":[kind],\"min_seconds\":数字,"
              "\"required\":false,\"keywords\":[..],\"desc\":..}],\"tips\":[..]}")
    data = backend.chat_json(prompt, system="你是经验丰富的视频编导，为创作者规划拍摄清单。简体中文，具体可执行。")
    extra = []
    for i, s in enumerate((data or {}).get("extra_shots") or []):
        if not isinstance(s, dict) or not s.get("name"):
            continue
        cat = s.get("category") if s.get("category") in config.CATEGORIES else "broll"
        extra.append({"id": f"ai_{i + 1}", "section": str(s.get("section") or ""), "name": str(s["name"]), "category": cat,
                      "devices": [str(d) for d in (s.get("devices") or ["phone"])], "min_seconds": float(s.get("min_seconds") or 5),
                      "required": bool(s.get("required", False)), "keywords": [str(k) for k in s.get("keywords") or []],
                      "desc": str(s.get("desc") or ""), "source": "ai"})
    return extra, [str(t) for t in (data or {}).get("tips") or []]


def generate_shotlist(project: Project, backend_name: str | None = None) -> tuple[str, list[dict]]:
    pdata = project.load()
    tmpl = project.type_template()
    items = base_items(pdata)
    tips: list[str] = []
    bname = backend_name_for(pdata, backend_name)
    if bname not in ("none", ""):
        try:
            backend = get_backend(bname)
            info(f"用 {backend.name} 补充个性化镜头…")
            extra, tips = llm_items(pdata, items, backend)
            items += extra
        except (BackendError, ValueError) as e:
            warn(f"AI 补充失败，使用模板清单：{e}")
    target = float((pdata.get("sponsor") or {}).get("duration") or pdata.get("target_duration") or 60)
    aspect = pdata.get("aspect", "16:9")
    md = [f"# 拍摄清单：{pdata.get('title')}",
          f"> 类型：{tmpl.get('name')}｜目标时长：约 {target:.0f} 秒｜画幅：{aspect}｜平台：{'、'.join(pdata.get('platforms') or [])}"
          f"｜风格：{project.style().get('name')}｜生成于 {_dt.datetime.now():%Y-%m-%d %H:%M}", ""]
    if pdata.get("theme"):
        md += [f"**主题**：{pdata['theme']}", ""]
    md += ["## 拍摄前准备"]
    kinds = {str(d.get("kind")) for d in available_devices()}
    for line in PREP["common"] + [x for k in ("360", "pocket", "glasses", "action", "phone") if k in kinds for x in PREP[k]]:
        md.append(f"- [ ] {line}")
    if aspect == "9:16":
        md.append("- [ ] 成片是竖屏：手机口播直接竖拍；其它相机横拍时主体放画面中间（后期裁成 9:16）")
    elif set(pdata.get("platforms") or []) & {"抖音", "小红书", "视频号"}:
        md.append("- [ ] 还要发竖屏平台：横拍时主体尽量居中，方便后期再裁一版 9:16")
    md.append("")
    secs = {s["id"]: s for s in tmpl.get("sections") or []}
    order = list(secs) + sorted({i.get("section", "") for i in items} - set(secs))
    n = 0
    for sid in order:
        group = [i for i in items if i.get("section", "") == sid]
        if not group:
            continue
        sec = secs.get(sid, {"name": sid or "其它", "ratio": 0})
        n += 1
        md.append(f"## {n}. {sec.get('name')}（成片约 {target * float(sec.get('ratio', 0)):.0f} 秒）")
        for it in group:
            req = "必拍" if it.get("required") else "可选"
            src = {"brief": "（来自 brief）", "ai": "（AI 建议）"}.get(it.get("source", ""), "")
            md.append(f"- [ ] **{it['name']}**{src}｜{req}｜≥{it.get('min_seconds', 5):.0f}s｜📷 {_resolve_devices(it.get('devices') or [])}")
            if it.get("desc"):
                md.append(f"  - {it['desc']}")
            if it.get("tips"):
                md.append(f"  - 💡 {it['tips']}")
        md.append("")
    sp = pdata.get("sponsor") or {}
    if pdata.get("type") == "sponsored":
        md += ["## 商单 brief 核对",
               f"- 品牌：{sp.get('brand') or '（未填写）'}｜产品：{sp.get('product') or '（未填写）'}｜时长：{sp.get('duration') or target}s"
               f"｜平台：{'、'.join(sp.get('platform') or pdata.get('platforms') or [])}｜截止：{sp.get('deadline') or '未填写'}"]
        for m in sp.get("must_show") or []:
            md.append(f"- [ ] 必须出现：{m}")
        for m in sp.get("key_messages") or []:
            md.append(f"- [ ] 必须讲到：{m}")
        for m in sp.get("forbidden") or []:
            md.append(f"- [ ] ⛔ 禁止：{m}")
        if sp.get("logo"):
            md.append(f"- [ ] Logo 文件已放入：{sp['logo']}")
        else:
            md.append("- [ ] ⚠️ 还没有 Logo 文件：向品牌方要 PNG（透明底），放到 assets/ 并填 sponsor.logo")
        md.append("")
    if (pdata.get("voiceover") or {}).get("enabled"):
        md += ["## 口播提纲（建议）"]
        script = (pdata.get("voiceover") or {}).get("script")
        if script:
            md.append(script)
        else:
            md += ["1. 一句话钩子：这是什么 / 最大亮点", "2. 我是谁、为什么做/为什么来",
                   "3. 每个重点 1~2 句（每句之间停顿 1 秒，方便剪）", "4. 结尾：总结 + 引导（关注/评论/链接）"]
        md.append("")
    if tips:
        md += ["## AI 拍摄建议"] + [f"- {t}" for t in tips] + [""]
    md += ["---", "拍完后：`autocut ingest` 导入 → `autocut analyze` 分析 → `autocut gaps` 看还缺什么。"]
    text = "\n".join(md)
    (project.root / "shotlist.md").write_text(text, encoding="utf-8")
    config.dump_yaml({"items": items}, project.root / "shotlist.yaml")
    ok(f"拍摄清单：{project.root / 'shotlist.md'}（{len(items)} 项）")
    return text, items
