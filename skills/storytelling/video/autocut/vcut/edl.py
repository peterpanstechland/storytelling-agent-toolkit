"""Edit Decision List (EDL) schema — the contract between planner, renderer and exporters."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# our transition names -> ffmpeg xfade names (None = hard cut)
XFADE = {
    "cut": None, "fade": "fade", "dissolve": "dissolve", "fadeblack": "fadeblack", "fadewhite": "fadewhite",
    "slideleft": "slideleft", "slideright": "slideright", "slideup": "slideup", "slidedown": "slidedown",
    "wipeleft": "wipeleft", "wiperight": "wiperight", "wipeup": "wipeup", "smoothleft": "smoothleft",
    "smoothright": "smoothright", "circleopen": "circleopen", "zoomin": "zoomin", "hblur": "hblur",
    "pixelize": "pixelize", "radial": "radial",
}
# our transition names -> 剪映 (non-VIP where possible)
JIANYING_TRANSITION = {
    "fade": "叠化", "dissolve": "叠化", "fadeblack": "闪黑", "fadewhite": "闪白", "slideleft": "向左",
    "slideright": "向右", "slideup": "向上擦除", "slidedown": "向下擦除", "wipeleft": "向右擦除", "wiperight": "向右擦除",
    "wipeup": "向上擦除", "smoothleft": "向左", "smoothright": "向右", "circleopen": "叠化", "zoomin": "推近",
    "hblur": "横向模糊", "pixelize": "模糊", "radial": "叠化",
}
# v2 custom transitions rendered frame-by-frame by vcut.fx.transitions (not xfade)
CUSTOM_TRANSITIONS = {
    "whip_left": "甩镜（向左，方向性运动模糊）", "whip_right": "甩镜（向右）", "whip_up": "甩镜（向上）",
    "whip_down": "甩镜（向下）", "spin": "旋转（顺时针 + 旋转模糊）", "spin_ccw": "旋转（逆时针）",
    "zoom_through": "3D 推镜穿越（径向模糊）", "glitch": "故障切换", "flash": "白闪曝光", "light_leak": "漏光叠化",
}
JIANYING_TRANSITION.update({
    "whip_left": "横向模糊", "whip_right": "横向模糊", "whip_up": "竖向模糊", "whip_down": "竖向模糊",
    "spin": "顺时针旋转", "spin_ccw": "逆时针旋转", "zoom_through": "推近", "glitch": "故障", "flash": "闪白",
    "light_leak": "泛光",
})
ALL_TRANSITIONS = set(XFADE) | set(CUSTOM_TRANSITIONS)

EFFECTS = {"zoom_in", "zoom_out", "speed_ramp", "bw", "vignette", "freeze_end"}  # v1 legacy flags
RAMP_SPLIT, RAMP_FACTOR = 0.6, 2.5

# ---- v2 vocabularies (validated; unknown names are dropped by planners) ----
MOVES_360 = {
    "fixed360": "固定朝向（默认朝向主体）", "follow": "自动跟随主体", "orbit": "环绕 360° 摇镜",
    "hero": "隐形自拍杆第三人称英雄镜头", "whip360": "360 甩镜换方向（旋转运动模糊）",
    "tiny_planet": "小行星", "planet_intro": "小行星 → 正常视角 开场", "rabbit_hole": "兔子洞（仰视反向小行星）",
    "crystal_ball": "水晶球",
}
MOVES_2D = {
    "push_in": "缓推（缓动）", "pull_out": "缓拉（缓动）", "pan": "横摇（裁切窗口移动）", "tilt": "竖摇",
    "punch": "卡点放大（跟随音乐节拍）", "shake": "手持晃动模拟", "roll": "滚转（荷兰角）", "subject": "主体跟随构图",
    "none": "不动",
}
FX_TYPES = {
    "glitch": "故障（RGB 分离 + 块位移 + 扫描线）", "rgb_split": "色差（镜头色散）", "light_leak": "漏光",
    "flare": "镜头光晕", "flash": "白闪", "speed_lines": "速度线", "grain": "胶片颗粒 + 片门抖动",
    "vhs": "VHS 录像带", "motion_blur": "运动模糊 / 拖影", "vignette": "暗角", "bw": "黑白", "glow": "辉光",
    "shake": "震动（同 shake 运镜，可按节拍）", "scanlines": "扫描线",
    "punch": "卡点放大（params.on=beats 跟节拍；否则在窗口内放大一次）",
}
TEXT_ANIMS = {
    "fade": "淡入淡出", "pop": "弹出放大", "slide_up": "上滑进入", "typewriter": "打字机", "glitch": "故障抖动",
    "stamp": "盖章砸入", "kinetic": "逐词弹出", "highlight_box": "色块擦出",
}


class Transition(BaseModel):
    type: str = "cut"
    duration: float = 0.0

    @field_validator("type")
    @classmethod
    def _known(cls, v: str) -> str:
        return v if v in ALL_TRANSITIONS else "fade"

    @property
    def is_custom(self) -> bool:
        return self.type in CUSTOM_TRANSITIONS


class Move(BaseModel):
    """Camera move. 360 moves need projection=equirect; 2D moves work on any flat clip."""
    type: str = "none"
    params: dict = Field(default_factory=dict)


class FX(BaseModel):
    """Per-clip effect window (clip-local OUTPUT seconds). dur=None → until the clip ends.
    params.on = "beats" makes the effect pulse on music beats (EDL.beats)."""
    type: str
    start: float = 0.0
    dur: float | None = None
    intensity: float = Field(0.6, ge=0, le=1.5)
    params: dict = Field(default_factory=dict)


class Ramp(BaseModel):
    """Smooth speed ramp: profile = [[x(0..1 of the output), speed], ...] multiplied with Clip.speed;
    curve is smoothstep-eased between points. interp: blend (frame blending) | flow (ffmpeg minterpolate) | nearest."""
    profile: list[list[float]] = Field(default_factory=lambda: [[0, 1.0], [0.35, 1.0], [0.5, 0.3], [0.7, 0.3], [1, 2.0]])
    interp: Literal["blend", "flow", "nearest"] = "blend"

    def mean_speed(self) -> float:
        import numpy as np
        xs = np.linspace(0, 1, 401)
        return float(np.mean([_profile_speed(self.profile, x) for x in xs]))


def _profile_speed(profile: list[list[float]], x: float) -> float:
    pts = sorted((float(p[0]), max(0.05, float(p[1]))) for p in profile) or [(0.0, 1.0), (1.0, 1.0)]
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, s0), (x1, s1) in zip(pts, pts[1:]):
        if x <= x1:
            u = 0.0 if x1 <= x0 else (x - x0) / (x1 - x0)
            u = u * u * (3 - 2 * u)
            return s0 + (s1 - s0) * u
    return pts[-1][1]


class Freeze(BaseModel):
    """Freeze-frame with pop card. at = clip-local output seconds (before the hold)."""
    at: float = 0.0
    hold: float = Field(1.2, ge=0.2, le=5)
    text: str = ""
    style: Literal["pop", "plain"] = "pop"


class PIP(BaseModel):
    """Second source composited over the clip: picture-in-picture or split screen."""
    model_config = ConfigDict(populate_by_name=True)
    src: str
    media_id: str = ""
    in_: float = Field(0.0, alias="in", ge=0)
    layout: Literal["pip_br", "pip_bl", "pip_tr", "pip_tl", "split_lr", "split_tb"] = "pip_br"
    scale: float = Field(0.34, ge=0.15, le=0.6)
    projection: Literal["flat", "equirect"] = "flat"


class Clip(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    media_id: str
    src: str
    in_: float = Field(alias="in", ge=0)
    out: float
    role: str = "broll"
    section: str = ""
    speed: float = Field(1.0, gt=0.1, le=8)
    effects: list[str] = Field(default_factory=list)
    transition_in: Transition = Field(default_factory=Transition)
    volume: float = 1.0
    focus_x: float = 0.5
    note: str = ""
    # ---- v2 ----
    projection: Literal["flat", "equirect"] = "flat"
    move: Move | None = None
    fx: list[FX] = Field(default_factory=list)
    ramp: Ramp | None = None
    freeze: Freeze | None = None
    pip: PIP | None = None
    focus_track: list[list[float]] = Field(default_factory=list)   # [[t_local, x, y]] normalized subject centre
    yaw_track: list[list[float]] = Field(default_factory=list)     # [[t_local, yaw, pitch]] 360 subject heading

    @property
    def src_duration(self) -> float:
        return max(0.0, self.out - self.in_)

    @property
    def base_duration(self) -> float:
        """Output length before a freeze hold is inserted."""
        d = self.src_duration
        if self.ramp is not None:
            return d / (self.speed * self.ramp.mean_speed())
        if "speed_ramp" in self.effects:
            return d * RAMP_SPLIT / self.speed + d * (1 - RAMP_SPLIT) / (self.speed * RAMP_FACTOR)
        return d / self.speed

    @property
    def duration(self) -> float:
        return self.base_duration + (self.freeze.hold if self.freeze else 0.0)

    def uses_engine(self) -> bool:
        """True when the clip needs the frame-level v2 engine (else the fast pure-ffmpeg path)."""
        return bool(self.projection == "equirect" or (self.move and self.move.type not in ("", "none")) or self.fx
                    or self.ramp or self.freeze or self.pip or self.focus_track)

    def out_to_src(self, t_out: float) -> float:
        """Clip-local output time → source time (absolute, seconds)."""
        if self.freeze:
            if t_out >= self.freeze.at + self.freeze.hold:
                t_out -= self.freeze.hold
            elif t_out >= self.freeze.at:
                t_out = self.freeze.at
        bd = self.base_duration
        x = min(1.0, max(0.0, t_out / bd)) if bd > 0 else 0.0
        if self.ramp is not None:
            n = 200
            acc, tot = [0.0], 0.0
            for k in range(n):
                tot += _profile_speed(self.ramp.profile, (k + 0.5) / n)
                acc.append(tot)
            pos = x * n
            k = min(n - 1, int(pos))
            frac = acc[k] + (acc[k + 1] - acc[k]) * (pos - k)
            return self.in_ + self.src_duration * frac / tot
        if "speed_ramp" in self.effects:
            split_out = self.src_duration * RAMP_SPLIT / self.speed
            if t_out <= split_out:
                return self.in_ + t_out * self.speed
            return self.in_ + self.src_duration * RAMP_SPLIT + (t_out - split_out) * self.speed * RAMP_FACTOR
        return self.in_ + t_out * self.speed

    def src_to_timeline(self, t_src: float, clip_start: float) -> float:
        rel = t_src - self.in_
        if self.ramp is not None or self.freeze is not None:
            lo, hi = 0.0, self.duration
            for _ in range(40):  # out_to_src is monotonic → bisection
                mid = (lo + hi) / 2
                if self.out_to_src(mid) < t_src:
                    lo = mid
                else:
                    hi = mid
            return clip_start + (lo + hi) / 2
        if "speed_ramp" in self.effects:
            split = self.src_duration * RAMP_SPLIT
            if rel <= split:
                return clip_start + rel / self.speed
            return clip_start + split / self.speed + (rel - split) / (self.speed * RAMP_FACTOR)
        return clip_start + rel / self.speed


class TextOverlay(BaseModel):
    start: float
    end: float
    text: str
    kind: Literal["title", "section", "lower_third", "caption", "cta", "callout"] = "caption"
    anim: str = ""                       # TEXT_ANIMS key ("" = style default)
    x: float | None = None               # normalized anchor (callouts / custom placement)
    y: float | None = None
    target: list[float] | None = None    # callout arrow target [x, y] normalized


class SubtitleCue(BaseModel):
    start: float
    end: float
    text: str


class AudioItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    kind: Literal["music", "voiceover", "sfx"] = "music"
    tag: str = ""               # sfx: whoosh / hit / riser / glitch / shutter / pop
    src: str
    start: float = 0.0          # timeline position
    in_: float = Field(0.0, alias="in")   # source offset
    duration: float = 0.0       # timeline length
    volume: float = 1.0
    fade_in: float = 0.0
    fade_out: float = 0.0
    duck: bool = False
    loop: bool = False


class Logo(BaseModel):
    src: str
    position: Literal["top_right", "top_left", "bottom_right", "bottom_left"] = "top_right"
    start: float = 0.0
    end: float | None = None
    scale: float = 0.12
    opacity: float = 0.9


class EDL(BaseModel):
    version: int = 2
    project: str = ""
    title: str = ""
    type: str = ""
    width: int = 1920
    height: int = 1080
    fps: int = 30
    aspect: str = "16:9"
    style: str = ""
    color_filter: str = ""
    lut: str = ""
    letterbox: bool = False
    reframe: str = "auto"
    subtitle_style: dict = Field(default_factory=dict)
    title_style: dict = Field(default_factory=dict)
    clips: list[Clip] = Field(default_factory=list)
    overlays: list[TextOverlay] = Field(default_factory=list)
    subtitles: list[SubtitleCue] = Field(default_factory=list)
    audio: list[AudioItem] = Field(default_factory=list)
    logo: Logo | None = None
    planner: str = "heuristic"
    notes: list[str] = Field(default_factory=list)
    # ---- v2 timeline-level ----
    beats: list[float] = Field(default_factory=list)       # music beats on the render timeline
    downbeats: list[float] = Field(default_factory=list)
    flashes: list[list[float]] = Field(default_factory=list)   # [[t, strength 0..1]] white flashes
    look: list[FX] = Field(default_factory=list)            # applied to every engine clip (grain / vhs / glow …)
    progress: dict | None = None                            # {color, height, position, chapters: [[t, label]]}
    text_anims: dict = Field(default_factory=dict)          # kind → default TEXT_ANIMS preset
    jianying: dict = Field(default_factory=dict)            # style hints for the 剪映 export (filter, effects …)

    # ---------- timing ----------
    def normalize_transitions(self) -> None:
        """Clamp transition durations so that overlaps never exceed half of either neighbour."""
        for i, c in enumerate(self.clips):
            if i == 0 or (XFADE.get(c.transition_in.type) is None and not c.transition_in.is_custom):
                c.transition_in = Transition(type="cut", duration=0.0)
                continue
            prev = self.clips[i - 1]
            limit = 0.45 * min(prev.duration, c.duration)
            d = min(max(c.transition_in.duration, 0.1), limit)
            if d < 0.1:
                c.transition_in = Transition(type="cut", duration=0.0)
            else:
                c.transition_in.duration = round(d, 3)

    def timeline(self) -> list[tuple[float, float]]:
        out, t = [], 0.0
        for i, c in enumerate(self.clips):
            if i > 0:
                t -= c.transition_in.duration
            out.append((round(t, 3), round(t + c.duration, 3)))
            t += c.duration
        return out

    @property
    def total_duration(self) -> float:
        tl = self.timeline()
        return tl[-1][1] if tl else 0.0

    # ---------- io ----------
    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2, by_alias=True), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "EDL":
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))
