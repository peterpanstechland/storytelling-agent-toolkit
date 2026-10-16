"""terminal_hud — a generated "terminal / agent screen" insert card, filmed through the lens look.

Port of the ff-tracking idea (mrsarac/ff-tracking, MIT; hud/src/lib.rs + flat/src/lib.rs): a flat black screen with
typed lines, hatched tracker boxes on the newest characters, then a camera (perspective tilt, depth of field
focused on the newest character, palette, bloom, LED grid) that moves per line, a lock moment, and a final
collapse → "Done" pill. Everything is generated from the text you supply — the lines come from the project brief /
EDL (`Clip.generated`), nothing from ff-tracking's own copy is reused.

Clip.generated = {"type": "terminal_hud", "lines": ["…", …], "title": "agent", "status": "ready", "log": [...],
                  "palettes": ["paper", "thermal", …], "done": "Done", "line_dur": null, "lens": {…}, "sfx": true}
"""
from __future__ import annotations

import math
import os
import subprocess
from collections import deque
from pathlib import Path

import cv2
import numpy as np

from .. import config
from ..media import FFmpegError, ffmpeg_bin, video_encode_args
from . import fonts
from .hud import TrackerHUD, draw_done_pill, draw_quad_box
from .lens import FOCAL, LH, LensLook
from .trackctx import Box, TrackCtx

_NOWIN = {"creationflags": 0x08000000} if os.name == "nt" else {}

# Camera presets per line (tilt_x, tilt_y, roll rad; zoom start/end; pan logical px; blur). Same family of values as
# ff-tracking's scene list, re-tuned by eye for 16:9 and 9:16 — they are not copied one for one.
CAMS = [
    (0.18, 0.55, -0.05, 2.6, 3.0, 10.0, 0.0, 1.0),
    (0.34, -0.25, 0.04, 2.2, 2.5, 50.0, 0.0, 1.2),
    (-0.22, 0.30, 0.03, 2.0, 2.4, -30.0, 10.0, 1.0),
    (0.12, -0.45, -0.04, 2.8, 3.1, 20.0, 0.0, 1.3),
    (0.28, 0.12, 0.06, 1.8, 2.1, 0.0, -20.0, 0.9),
]
DONE_CAM = (0.10, -0.10, 0.0, 1.9, 1.6, 0.0, 0.0, 0.8)
PALETTE_CYCLE = ["paper", "thermal", "mono", "phosphor", "amber", "navy", "neon"]
DEFAULT_LOG = ["scanning project files", "resolved 14 dependencies", "indexed 2,381 files", "plan ready · 6 steps",
               "applying changes 1/6", "checks passed · 128/128", "build ok"]
CHAIN = 5          # newest characters that carry a tracker box (ff-tracking: CHAIN = 5)
COLLAPSE_DUR = 0.5
DONE_HOLD = 0.9


def ease_out(x: float) -> float:
    return 1 - (1 - min(1.0, max(0.0, x))) ** 3


def ease_in_out(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def spec_of(g: dict) -> dict:
    s = dict(g)
    s["lines"] = [str(x) for x in (s.get("lines") or ["Hello"]) if str(x).strip()] or ["Hello"]
    return s


def line_durations(spec: dict) -> list[float]:
    ld = spec.get("line_dur")
    return [float(ld) if ld else min(1.6, max(0.55, 0.35 + 0.045 * len(t))) for t in spec["lines"]]


def schedule(spec: dict) -> dict:
    """Timeline of the card (clip-local seconds): per-line windows, key times, lock times, collapse and done."""
    spec = spec_of(spec)
    durs = line_durations(spec)
    t = 0.0
    lines, keys, locks, cuts = [], [], [], []
    for text, d in zip(spec["lines"], durs):
        n = len(text)
        lines.append((t, t + d))
        cuts.append(round(t, 4))
        for k in range(n):
            if text[k] != " ":
                keys.append(round(t + d * (0.10 + 0.62 * (k + 1) / max(n, 1)), 4))
        locks.append(round(t + d * 0.78, 4))
        t += d
    done = spec.get("done", "Done")
    collapse_at = t if done is not False else None
    total = t + ((COLLAPSE_DUR + DONE_HOLD) if done is not False else 0.0)
    return {"lines": lines, "keys": keys, "locks": locks, "cuts": cuts, "collapse_at": collapse_at,
            "done_at": (t + COLLAPSE_DUR) if collapse_at is not None else None, "duration": round(total, 3)}


def card_duration(spec: dict) -> float:
    return schedule(spec)["duration"]


def layout_hero(text: str, LW: float, portrait: bool):
    """→ (size, [(ch, x, y_off_from_first_baseline, advance)], block_w, n_rows). Logical px, wraps on words."""
    size = 80.0 if portrait else 104.0
    maxw = LW * (0.84 if portrait else 0.80)

    def adv(ch: str, sz: float) -> float:
        return fonts.glyph(ch, max(6, int(round(sz))))[3] if fonts.have_pillow() else sz * 0.6

    for _ in range(14):
        words = text.split(" ")
        rows: list[str] = []
        cur = ""
        for w in words:
            cand = (cur + " " + w).strip() if cur else w
            if sum(adv(c, size) for c in cand) <= maxw or not cur:
                cur = cand
            else:
                rows.append(cur)
                cur = w
        rows.append(cur)
        widest = max(sum(adv(c, size) for c in r) for r in rows)
        if (widest <= maxw and len(rows) <= 3) or size <= 44:
            break
        size *= 0.88
    out = []
    blockw = max(sum(adv(c, size) for c in r) for r in rows)
    for ri, r in enumerate(rows):
        x = (LW - blockw) / 2
        for ch in r:
            a = adv(ch, size)
            out.append((ch, x, ri * size * 1.22, a))
            x += a
    return size, out, blockw, len(rows)


class Card:
    def __init__(self, spec: dict, W: int, H: int, fps: int, seed: int = 0):
        self.spec = spec_of(spec)
        self.W, self.H, self.fps = W, H, fps
        self.portrait = H > W
        self.LW = LH * W / H
        self.sched = schedule(self.spec)
        self.fs = 1.5 * H / LH                      # flat px per logical px
        self.FW, self.FH = int(round(self.LW * self.fs)), int(round(LH * self.fs))
        self.k = W / self.LW                        # logical → ctx/output-nominal px
        self.pal = list(self.spec.get("palettes") or PALETTE_CYCLE)
        self.log = [str(x) for x in (self.spec.get("log") or DEFAULT_LOG)]
        self.title = str(self.spec.get("title") or "agent")
        self.status = str(self.spec.get("status") or "ready")
        self.done_text = self.spec.get("done", "Done")
        self.layouts = [layout_hero(t, self.LW, self.portrait) for t in self.spec["lines"]]
        self.base_cache: dict[int, np.ndarray] = {}
        lens_p = {"palette": self.pal[0], "dof": 1.1, "dof_mode": "plane", "fit": "black", "bloom": 1.0, "bloom_threshold": 0.0,
                  "led": 1.0, "grain": 0.06, "keep_red": True, "lum": "g", "palette_mix": 1.0, "ca": 1.0, "tear": 1.0,
                  "cuts": self.sched["cuts"]}
        lens_p.update(self.spec.get("lens") or {})
        lens_p["cuts"] = self.sched["cuts"]
        self.lens = LensLook(W, H, fps, 1.0, lens_p, seed)
        self.cell = float(lens_p.get("cell", 3.0))
        hp = {"draw": ["links", "labels", "brackets"], "lock_fx": False, "flash": 0.0}
        hp.update(self.spec.get("hud") or {})
        self.hud = TrackerHUD(W, H, fps, 1.0, hp, seed)
        cp = {"mode": "provided", "locks": self.sched["locks"], "cuts": self.sched["cuts"], "lock_hold": 0.3}
        if self.sched["collapse_at"] is not None:
            cp["collapse_at"] = self.sched["collapse_at"]
            cp["collapse_dur"] = COLLAPSE_DUR
        self.ctx = TrackCtx(W, H, fps, self.sched["duration"], cp, seed=seed)
        self.lens.bind(self.ctx)
        self.hud.bind(self.ctx)
        self.lens.shot_dur = 1.0
        self.hud.label = str(self.done_text or "Done")
        self._targets: deque = deque(maxlen=4)
        self._last_line = -1

    # ---------------------------------------------------------------- flat pass
    def _text(self, img, text, x, y, size, color, bold=False, opacity=1.0):
        fs = self.fs
        return fonts.draw_text(img, text, x * fs, y * fs, max(6, int(round(size * fs))), color, bold=bold, opacity=opacity)

    def _base(self, j: int) -> np.ndarray:
        """Chrome + dim log (older lines scroll into it) for line j."""
        if j in self.base_cache:
            return self.base_cache[j]
        fs, LW = self.fs, self.LW
        img = np.zeros((self.FH, self.FW, 3), np.uint8)
        # title bar
        for k, c in enumerate(((80, 80, 255), (60, 190, 255), (90, 210, 90))):
            cv2.circle(img, (int((54 + 34 * k) * fs), int(46 * fs)), int(8 * fs), tuple(int(v * 0.45) for v in c), -1, cv2.LINE_AA)
        fonts.draw_text(img, self.title, LW / 2 * fs, 54 * fs, int(24 * fs), (120, 120, 120), anchor="c")
        cv2.line(img, (0, int(86 * fs)), (self.FW, int(86 * fs)), (44, 44, 44), max(1, int(2 * fs)))
        # log
        prev = self.spec["lines"][:j]
        lines = (self.log + prev)[-(6 if not self.portrait else 5):]
        y0 = 150
        for k, t in enumerate(lines):
            fade = 0.45 + 0.4 * (k + 1) / max(1, len(lines))
            col = tuple(int(v * fade) for v in (150, 150, 150))
            mark = "›" if t in prev else "✓"
            self._text(img, mark, 70, y0 + 46 * k, 26, (110, 110, 110))
            self._text(img, t[: int(LW / 15)], 110, y0 + 46 * k, 26, col)
        # status bar
        cv2.line(img, (0, int((LH - 70) * fs)), (self.FW, int((LH - 70) * fs)), (44, 44, 44), max(1, int(2 * fs)))
        self._text(img, f"● {self.status}", 60, LH - 26, 22, (110, 110, 110))
        self._text(img, f"ln {j + 1}/{len(self.spec['lines'])}", LW - 190, LH - 26, 22, (110, 110, 110))
        self.base_cache = {j: img} if len(self.base_cache) > 2 else {**self.base_cache, j: img}
        return img

    def _cells(self, j: int, vis: int):
        size, glyphs, blockw, nrows = self.layouts[j]
        y_base = 540 + 0.30 * size - (nrows - 1) * size * 0.61
        out = []
        for ch, x, yo, a in glyphs[:vis]:
            out.append((ch, x, y_base + yo, a))
        return size, y_base, out

    def frame(self, i: int) -> np.ndarray:
        t = i / self.fps
        sc, fs, k = self.sched, self.fs, self.k
        ctx = self.ctx
        # which phase?
        j = len(sc["lines"]) - 1
        for n, (a, b) in enumerate(sc["lines"]):
            if t < b:
                j = n
                break
        in_collapse = sc["collapse_at"] is not None and t >= sc["collapse_at"]
        a, b = sc["lines"][j]
        x = 0.0 if in_collapse else min(1.0, max(0.0, (t - a) / max(b - a, 1e-3)))
        if in_collapse:
            x = 1.0
        text = self.spec["lines"][j]
        n = len(text)
        vis = n if in_collapse else min(n, int(math.ceil(n * min(1.0, max(0.0, (x - 0.10) / 0.62)))))
        flat = self._base(j).copy()
        size, y_base, cells = self._cells(j, vis)
        sz_flat = max(6, int(round(size * fs)))
        c_collapse = ease_in_out((t - sc["collapse_at"]) / COLLAPSE_DUR) if in_collapse else 0.0
        centre = (self.LW / 2, 540.0)
        # hero text
        txt_alpha = 1.0 - c_collapse
        if txt_alpha > 0.02:
            for ch, cx, cy, adv in cells:
                if ch != " ":
                    fonts.draw_text(flat, ch, cx * fs, cy * fs, sz_flat, (255, 255, 255), bold=True, opacity=txt_alpha)
        # cursor
        typing = x < 0.80 and not in_collapse
        if (typing or (i // 4) % 2 == 0) and txt_alpha > 0.5:
            nxt = self._cells(j, vis + 1)[2]
            if len(nxt) > vis:
                cx = nxt[-1][1]
            elif cells:
                cx = cells[-1][1] + cells[-1][3]
            else:
                cx = self.layouts[j][1][0][1]
            cy = cells[-1][2] if cells else y_base
            cv2.rectangle(flat, (int(cx * fs), int((cy - size * 0.78) * fs)), (int((cx + size * 0.5) * fs), int((cy + size * 0.12) * fs)),
                          (255, 255, 255), -1)
        # tracker boxes on the newest characters
        locked = ctx.locked if hasattr(ctx, "locked") else False
        boxes_l: list[Box] = []
        newest = [c for c in cells if c[0] != " "][-CHAIN:]
        r = np.random.default_rng(i * 977 + 13)
        for q, (ch, cx, cy, adv) in enumerate(newest):
            pad = 6.0
            jx, jy = (r.random() - 0.5) * 3.2, (r.random() - 0.5) * 3.2
            bx0, by0 = cx - pad + jx, cy - size * 0.80 - pad + jy
            bw, bh = adv + 2 * pad, size * 0.98 + 2 * pad
            ccx, ccy = bx0 + bw / 2, by0 + bh / 2
            if c_collapse > 0:
                ccx, ccy = ccx + (centre[0] - ccx) * c_collapse, ccy + (centre[1] - ccy) * c_collapse
                bw, bh = bw * (1 - 0.6 * c_collapse), bh * (1 - 0.6 * c_collapse)
            boxes_l.append(Box(q, ccx, ccy, bw, bh, 1.0, "glyph", age=99))
        tgt = boxes_l[-1] if boxes_l else None
        for b in boxes_l if (c_collapse < 0.98) else []:
            quad = np.array([[b.cx - b.w / 2, b.cy - b.h / 2], [b.cx + b.w / 2, b.cy - b.h / 2], [b.cx + b.w / 2, b.cy + b.h / 2],
                             [b.cx - b.w / 2, b.cy + b.h / 2]]) * fs
            draw_quad_box(flat, quad, locked=bool(locked and b is tgt), hatch=True, outline=True, ink=(255, 255, 255), sc=fs)
        # done pill (in the flat pass, like ff-tracking)
        if in_collapse and t >= sc["done_at"]:
            draw_done_pill(flat, centre[0] * fs, centre[1] * fs, str(self.done_text), fs * 1.35, ease_out((t - sc["done_at"]) / 0.25))
        # camera for this moment
        cam = DONE_CAM if in_collapse else CAMS[j % len(CAMS)]
        tx, ty, roll, z0, z1, px, py, blur = cam
        if self.portrait:
            z0, z1 = z0 * 0.62, z1 * 0.62
        xt = x if not in_collapse else min(1.0, (t - sc["collapse_at"]) / (COLLAPSE_DUR + DONE_HOLD))
        zoom = z0 + (z1 - z0) * ease_out(xt)
        sway = math.sin(j * 1.7 + xt * 1.3) * 0.015
        focus = (tgt.cx, tgt.cy) if tgt else centre
        self._targets.append(focus)
        lag = (sum(q[0] for q in self._targets) / len(self._targets), sum(q[1] for q in self._targets) / len(self._targets))
        hero_mid = (cells[-1][1] + cells[-1][3] / 2, cells[-1][2] - size * 0.3) if cells else centre
        if in_collapse:
            lag, hero_mid = centre, centre
        aim = (lag[0] * 0.72 + hero_mid[0] * 0.28 + px * (xt - 0.5), lag[1] * 0.72 + hero_mid[1] * 0.28 + py * (xt - 0.5))
        self.lens.forced = ([tx + sway, ty - sway * 0.7, roll + sway * 0.4], zoom, aim)
        pal = self.pal[j % len(self.pal)] if not in_collapse else self.pal[-1 % len(self.pal)]
        if pal != self.lens.palette:
            from .lens import palette_lut
            self.lens.palette, self.lens.lut = pal, palette_lut(pal)
        self.lens.dof = blur
        # tracker context in output-nominal px (logical * W/LW)
        kb = [Box(b.id, b.cx * k, b.cy * k, b.w * k, b.h * k, 1.0, "glyph", age=99) for b in boxes_l]
        kt = kb[-1] if kb else None
        ctx.set_boxes(kb, focus=(focus[0] * k, focus[1] * k), target=kt)
        ctx.update(flat, i, t)
        out = self.lens(flat, t, 1.0)
        out = self.hud(out, t, 1.0)
        # fade to black on the very last frames of the card
        tail = self.sched["duration"] - t
        if tail < 0.12:
            out = (out.astype(np.float32) * max(0.0, tail / 0.12)).astype(np.uint8)
        return out


def render_terminal(project, edl, c, clip_start: float, out: Path, W: int, H: int, fps: int, *, quick: bool, encoder: str,
                    lut_name: str, color_filter: str, cwd: Path) -> Path:
    from .effects import HUD_ORDER, make_effect, window_env  # noqa: F401
    from .engine import _fx_env, _local_beats

    spec = spec_of(c.generated or {})
    card = Card(spec, W, H, fps, seed=int(abs(hash(c.id)) % 100000))
    N = max(1, int(round(c.duration * fps)))
    dur_out = c.duration
    beats = _local_beats(edl, clip_start, dur_out)
    extra = [(f, make_effect(f.type, W, H, fps, f.intensity, f.params, 7 + k)) for k, f in enumerate(c.fx)
             if f.type not in ("lens_look", "tracker_hud", "punch", "shake")]
    extra += [(f, make_effect(f.type, W, H, fps, f.intensity, f.params, 70 + k)) for k, f in enumerate(edl.look)]
    extra = [(f, e) for f, e in extra if e is not None]
    venc = (video_encode_args(encoder, {"crf": 16, "nvenc_cq": 17}, fast=True) if not quick
            else video_encode_args("libx264" if "nvenc" not in encoder else encoder, {"crf": 23}, fast=True))
    post = [x for x in (color_filter, f"lut3d=file={lut_name}" if lut_name else "") if x]
    vpost = ",".join([*post, "setsar=1", "format=yuv420p"])
    ecmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
            "-r", str(fps), "-i", "pipe:0", "-f", "lavfi", "-t", f"{dur_out:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
            "-filter_complex", f"[0:v]{vpost}[v];[1:a]aformat=sample_fmts=fltp:channel_layouts=stereo[a]", "-map", "[v]", "-map", "[a]",
            "-t", f"{dur_out:.3f}", *venc, "-g", str(fps), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-r", str(fps),
            "-video_track_timescale", str(fps * 1000), str(out)]
    enc = subprocess.Popen(ecmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(cwd), **_NOWIN)
    try:
        for i in range(N):
            frame = card.frame(i)
            t = i / fps
            for spec_fx, eff in extra:
                frame = eff(frame, t, _fx_env(spec_fx, t, dur_out, beats))
            enc.stdin.write(np.ascontiguousarray(frame).tobytes())  # type: ignore[union-attr]
        enc.stdin.close()  # type: ignore[union-attr]
    except BrokenPipeError:
        pass
    err = enc.stderr.read().decode("utf-8", "replace")  # type: ignore[union-attr]
    enc.stderr.close()  # type: ignore[union-attr]
    if enc.wait() != 0:
        out.unlink(missing_ok=True)
        raise FFmpegError(f"终端卡 {c.id} 编码失败：{err[-800:]}")
    return out
