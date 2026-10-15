"""EDL v2 → 剪映 (pyJianYingDraft 0.3.x) effect/animation mapping.

Every name below was checked against the installed pyJianYingDraft enums (see `autocut jy-effects`); at runtime
each lookup goes through `resolve()` which (1) checks the name exists in the installed version, (2) swaps VIP
items for a free fallback when one is given and (3) records what was used so vcut_说明.txt can list it.
"""
from __future__ import annotations

import math

# fx type → 场景特效 (VideoSceneEffectType) — all free in pyJianYingDraft 0.3.0
SCENE_FX = {
    "glitch": "故障", "rgb_split": "色差", "light_leak": "胶片漏光", "flare": "光晕", "flash": "闪白",
    "speed_lines": "冲刺", "grain": "胶片", "vhs": "录像带", "motion_blur": "动感模糊", "vignette": "暗角",
    "bw": "老电影", "glow": "发光", "shake": "抖动", "scanlines": "隔行扫描",
}
FLASH_FX = "闪白"
# text anim preset → (TextIntro, TextOutro, TextLoopAnim)
TEXT_ANIM = {
    "fade": ("渐显", "渐隐", None), "pop": ("弹入", "弹出", None), "slide_up": ("向上滑动", "向下滑动", None),
    "typewriter": ("打字机_I", "渐隐", None), "glitch": ("故障打字机", "渐隐", "色差故障"),
    "stamp": ("放大", "渐隐", None), "kinetic": ("逐字显影", "渐隐", None), "highlight_box": ("羽化向右擦开", "渐隐", None),
}
FALLBACK = {"transition": "叠化", "scene": None, "filter": None, "intro": "渐显", "outro": "渐隐",
            "text_intro": "渐显", "text_outro": "渐隐", "text_loop": None}


class Resolver:
    def __init__(self):
        import pyJianYingDraft as jy
        self.enums = {"transition": jy.TransitionType, "scene": jy.VideoSceneEffectType, "filter": jy.FilterType,
                      "intro": jy.IntroType, "outro": jy.OutroType, "group": jy.GroupAnimationType,
                      "text_intro": jy.TextIntro, "text_outro": jy.TextOutro, "text_loop": jy.TextLoopAnim,
                      "mask": jy.MaskType}
        self.used: dict[tuple[str, str], int] = {}
        self.notes: list[str] = []

    def resolve(self, kind: str, name: str | None):
        if not name:
            return None
        enum = self.enums[kind]
        m = enum.__members__.get(name)
        if m is None:
            self.notes.append(f"剪映 {kind}「{name}」在当前 pyJianYingDraft 版本里不存在，已跳过/替换。")
            fb = FALLBACK.get(kind)
            m = enum.__members__.get(fb) if fb else None
            if m is None:
                return None
            name = fb
        if getattr(m.value, "is_vip", False):
            fb = FALLBACK.get(kind)
            if fb and fb != name and fb in enum.__members__:
                self.notes.append(f"剪映 {kind}「{name}」是 VIP 素材，已替换为「{fb}」。")
                m, name = enum.__members__[fb], fb
            else:
                self.notes.append(f"剪映 {kind}「{name}」是 VIP 素材（保留，导出成片时可能要求会员）。")
        self.used[(kind, name)] = self.used.get((kind, name), 0) + 1
        return m

    def summary(self) -> list[str]:
        if not self.used:
            return []
        out = ["", "## 草稿里用到的剪映素材（类型 / 名称 / 次数 / 是否 VIP）"]
        for (kind, name), n in sorted(self.used.items()):
            m = self.enums[kind].__members__[name]
            out.append(f"- {kind} / {name} × {n} / {'VIP' if getattr(m.value, 'is_vip', False) else '免费'}")
        return out


def catalog(kind: str | None = None, keyword: str = "", include_vip: bool = True) -> dict[str, list[tuple[str, bool]]]:
    import pyJianYingDraft as jy
    enums = {"transition": jy.TransitionType, "scene": jy.VideoSceneEffectType, "character": jy.VideoCharacterEffectType,
             "filter": jy.FilterType, "intro": jy.IntroType, "outro": jy.OutroType, "group": jy.GroupAnimationType,
             "text_intro": jy.TextIntro, "text_outro": jy.TextOutro, "text_loop": jy.TextLoopAnim, "mask": jy.MaskType}
    out = {}
    for k, e in enums.items():
        if kind and k != kind:
            continue
        items = [(n, bool(getattr(v.value, "is_vip", False))) for n, v in e.__members__.items()]
        items = [(n, vip) for n, vip in items if (not keyword or keyword in n) and (include_vip or not vip)]
        out[k] = items
    return out


# ---------------------------------------------------------------- keyframes for 2D moves
def move_keyframes(c, seg_dur: float, beats_local: list[float], W: int, H: int, src_ar: float | None) -> list[tuple[str, float, float]]:
    """Return [(property, t_seconds, value)] approximating Move/punch/shake/focus with 剪映 keyframes.
    position_x/y are in 剪映 units (half canvas); uniform_scale relative to the 'fit' size."""
    kf: list[tuple[str, float, float]] = []
    base = 1.0
    # portrait canvas with landscape source → fill height and pan to the subject
    canvas_ar = W / H
    if src_ar and src_ar > canvas_ar * 1.05 and c.projection != "equirect":
        base = src_ar / canvas_ar
        track = c.focus_track or [[0.0, c.focus_x, 0.5]]
        for t, fx, _fy in track[:: max(1, len(track) // 12)] + ([track[-1]] if len(track) > 1 else []):
            off = max(-(base - 1), min(base - 1, (0.5 - fx) * 2 * base))
            kf.append(("position_x", min(max(0.0, t), seg_dur - 0.01), round(off, 4)))
    mv = c.move.type if c.move else "none"
    amt = float((c.move.params or {}).get("amount", 0.12)) if c.move else 0.12
    if mv == "push_in":
        kf += [("uniform_scale", 0.0, base), ("uniform_scale", seg_dur - 0.01, base * (1 + amt))]
    elif mv == "pull_out":
        kf += [("uniform_scale", 0.0, base * (1 + amt)), ("uniform_scale", seg_dur - 0.01, base)]
    elif mv in ("pan", "tilt"):
        z = 1.0 + max(amt, 0.15)
        d = -1.0 if (c.move.params or {}).get("direction") in ("left", "up") else 1.0
        prop = "position_x" if mv == "pan" else "position_y"
        r = (z - 1.0) * 0.9 * (1 if mv == "pan" else -1)
        kf += [("uniform_scale", 0.0, base * z), (prop, 0.0, round(d * r, 4)), (prop, seg_dur - 0.01, round(-d * r, 4))]
    elif mv == "roll":
        deg = float((c.move.params or {}).get("degrees", 5.0))
        th = math.radians(abs(deg))
        z = math.cos(th) + max(canvas_ar, 1 / canvas_ar) * math.sin(th) + 0.01
        kf += [("rotation", 0.0, 0.0), ("rotation", seg_dur - 0.01, deg), ("uniform_scale", 0.0, base),
               ("uniform_scale", seg_dur - 0.01, base * z)]
    punch = next((f for f in c.fx if f.type == "punch"), None)
    if punch and beats_local and not any(p == "uniform_scale" for p, _, _ in kf):
        s = 1.0 + 0.05 + 0.13 * punch.intensity
        for b in beats_local:
            if 0.02 < b < seg_dur - 0.2:
                kf += [("uniform_scale", max(0.0, b - 0.01), base), ("uniform_scale", b + 0.04, base * s),
                       ("uniform_scale", min(seg_dur - 0.01, b + 0.22), base)]
    shake = next((f for f in c.fx if f.type == "shake"), None)
    if shake and not any(p == "position_x" for p, _, _ in kf):
        k = 0.0
        amp = 0.01 + 0.02 * shake.intensity
        if base == 1.0 and not any(p == "uniform_scale" for p, _, _ in kf):
            kf.append(("uniform_scale", 0.0, 1.0 + amp * 2.5))
        n = 0
        while k < seg_dur - 0.05:
            kf += [("position_x", k, round(amp * math.sin(n * 2.3), 4)), ("position_y", k, round(amp * math.cos(n * 1.7), 4))]
            k += 0.12
            n += 1
    if base != 1.0 and not any(p == "uniform_scale" for p, _, _ in kf):
        kf.append(("uniform_scale", 0.0, base))
    return kf
