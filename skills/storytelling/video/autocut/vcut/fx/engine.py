"""Per-clip frame engine: ffmpeg decode → NumPy/OpenCV (360 reprojection, camera, looks, freeze, PIP) → ffmpeg encode.

Used for every clip that has v2 features (Clip.uses_engine()); plain clips keep the pure-ffmpeg fast path.
Frames travel as raw BGR over pipes; the encoder also muxes the clip's audio and applies the style's colour
filter / LUT, so the output is a normal cached mezzanine for pass 2.
"""
from __future__ import annotations

import math
import os
import subprocess
import threading
from collections import deque
from pathlib import Path

import cv2
import numpy as np

from .. import config
from ..edl import EDL, FX, Clip
from ..media import FFmpegError, ffmpeg_bin, kind_of, probe, video_encode_args
from .camera2d import Camera2D, pulse_env
from .ease import ease
from .effects import HUD_ORDER, make_effect, window_env
from .moves360 import Shot360
from .sphere import Reprojector, View

CAMERA_FX = {"punch", "shake"}
CTX_KEYS = {"mode", "points", "max_boxes", "detect_every", "locks", "lock_count", "lock_hold", "collapse_at",
            "collapse_dur", "cuts"}
_NOWIN = {"creationflags": 0x08000000} if os.name == "nt" else {}


class _Drain(threading.Thread):
    def __init__(self, stream):
        super().__init__(daemon=True)
        self.stream, self.lines = stream, deque(maxlen=40)

    def run(self):
        for raw in iter(self.stream.readline, b""):
            self.lines.append(raw.decode("utf-8", "replace"))


class FrameReader:
    """Sequential raw-frame reader with random forward access by index (keeps a few frames)."""

    def __init__(self, cmd: list[str], w: int, h: int):
        self.w, self.h, self.size = w, h, w * h * 3
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **_NOWIN)
        self.drain = _Drain(self.proc.stderr)
        self.drain.start()
        self.buf: dict[int, np.ndarray] = {}
        self.next = 0
        self.eof = False
        self.last: np.ndarray | None = None

    def get(self, k: int) -> np.ndarray:
        k = max(0, k)
        while not self.eof and self.next <= k:
            raw = self.proc.stdout.read(self.size)  # type: ignore[union-attr]
            if not raw or len(raw) < self.size:
                self.eof = True
                break
            f = np.frombuffer(raw, np.uint8).reshape(self.h, self.w, 3)
            self.buf[self.next] = f
            self.last = f
            self.next += 1
            for old in [i for i in self.buf if i < self.next - 8]:
                del self.buf[old]
        if k in self.buf:
            return self.buf[k]
        if self.last is None:
            raise FFmpegError("解码失败：" + "".join(self.drain.lines))
        return self.last if k >= self.next else self.buf[min(self.buf)]

    def close(self):
        try:
            self.proc.stdout.close()  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass
        try:
            self.proc.kill()
        except Exception:  # noqa: BLE001
            pass
        self.proc.wait()


def _even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def _local_beats(edl: EDL, start: float, dur: float, every: int = 1, down: bool = False) -> list[float]:
    src = edl.downbeats if down and edl.downbeats else edl.beats
    bs = [round(b - start, 4) for b in src if start - 0.05 <= b <= start + dur]
    return bs[::max(1, every)]


def _fx_env(spec: FX, t: float, dur: float, beats: list[float]) -> float:
    if spec.params.get("on") == "beats":
        if t < spec.start or (spec.dur is not None and t > spec.start + spec.dur):
            return 0.0
        return pulse_env(t, beats, decay=float(spec.params.get("decay", 0.12)))
    if spec.type == "flash":
        return pulse_env(t, [spec.start], decay=float(spec.params.get("decay", 0.14)))
    return window_env(t, spec.start, spec.dur, dur)


# --------------------------------------------------------------------------- freeze / pip / crystal ball
def freeze_card(frozen: np.ndarray, t: float, hold: float, style: str = "pop") -> np.ndarray:
    H, W = frozen.shape[:2]
    if style == "plain":
        return frozen
    small = cv2.resize(frozen, (W // 6, H // 6), interpolation=cv2.INTER_AREA)
    bg = cv2.resize(cv2.GaussianBlur(small, (0, 0), 6), (W, H), interpolation=cv2.INTER_LINEAR)
    gray = cv2.cvtColor(cv2.cvtColor(bg, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    bg = cv2.addWeighted(bg, 0.35, gray, 0.25, 0)
    k = ease("out_back", min(1.0, t / 0.32))
    scale = 1.0 - 0.2 * k + 0.012 * (t / max(hold, 0.1))
    ang = -2.6 * k
    border = max(4, int(min(W, H) * 0.012))
    card = cv2.copyMakeBorder(frozen, border, border, border, border, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    ch, cw = card.shape[:2]
    M = cv2.getRotationMatrix2D((cw / 2, ch / 2), ang, scale * W / cw)
    M[0, 2] += W / 2 - cw / 2
    M[1, 2] += H / 2 - ch / 2
    alpha = cv2.warpAffine(np.full((ch, cw), 255, np.uint8), M, (W, H))
    warped = cv2.warpAffine(card, M, (W, H))
    shadow = cv2.GaussianBlur(alpha, (0, 0), max(3, W / 120))
    shadow = np.roll(shadow, (int(H * 0.015), int(W * 0.012)), axis=(0, 1)).astype(np.float32)[..., None] / 255.0
    out = bg.astype(np.float32) * (1 - 0.6 * shadow)
    a = alpha.astype(np.float32)[..., None] / 255.0
    out = out * (1 - a) + warped.astype(np.float32) * a
    flash = max(0.0, 1.0 - t / 0.16) * 0.7
    out = out + (255 - out) * flash
    return np.clip(out, 0, 255).astype(np.uint8)


def _rounded_mask(w: int, h: int, r: int) -> np.ndarray:
    m = np.zeros((h, w), np.uint8)
    cv2.rectangle(m, (r, 0), (w - r, h), 255, -1)
    cv2.rectangle(m, (0, r), (w, h - r), 255, -1)
    for cx, cy in ((r, r), (w - r, r), (r, h - r), (w - r, h - r)):
        cv2.circle(m, (cx, cy), r, 255, -1, cv2.LINE_AA)
    return m


def compose_pip(main: np.ndarray, sec: np.ndarray, layout: str, t: float) -> np.ndarray:
    H, W = main.shape[:2]
    if layout in ("split_lr", "split_tb"):
        out = main.copy()
        k = ease("out_cubic", min(1.0, t / 0.45))
        if layout == "split_lr":
            half = W // 2
            left = main[:, (W - half) // 2:(W - half) // 2 + half]
            out[:, :half] = left
            sh, sw = sec.shape[:2]
            off = int((1 - k) * half)
            region = out[:, half:]
            region[:, off:] = sec[:, : half - off] if off < half else region[:, off:]
            cv2.rectangle(out, (half - max(2, W // 400), 0), (half + max(2, W // 400), H), (255, 255, 255), -1)
        else:
            half = H // 2
            top = main[(H - half) // 2:(H - half) // 2 + half]
            out[:half] = top
            off = int((1 - k) * half)
            region = out[half:]
            region[off:] = sec[: half - off] if off < half else region[off:]
            cv2.rectangle(out, (0, half - max(2, H // 400)), (W, half + max(2, H // 400)), (255, 255, 255), -1)
        return out
    ph, pw = sec.shape[:2]
    m = int(min(W, H) * 0.04)
    k = ease("out_back", min(1.0, t / 0.4))
    x_end = W - pw - m if layout in ("pip_br", "pip_tr") else m
    y = H - ph - m if layout in ("pip_br", "pip_bl") else m
    x_start = W + 10 if layout in ("pip_br", "pip_tr") else -pw - 10
    x = int(x_start + (x_end - x_start) * k)
    out = main.copy()
    r = max(6, int(min(pw, ph) * 0.08))
    mask = _rounded_mask(pw, ph, r)
    bw = max(3, int(min(W, H) * 0.005))
    # shadow + border
    sh = np.zeros((H, W), np.float32)
    x0, x1 = max(0, x + 8), min(W, x + pw + 8)
    if x1 > x0:
        sh[max(0, y + 10):min(H, y + ph + 10), x0:x1] = 1.0
    sh = cv2.GaussianBlur(sh, (0, 0), W / 150)[..., None]
    out = (out.astype(np.float32) * (1 - 0.55 * sh)).astype(np.uint8)
    framed = cv2.copyMakeBorder(sec, bw, bw, bw, bw, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    fmask = _rounded_mask(pw + 2 * bw, ph + 2 * bw, r + bw)
    fx0, fy0 = x - bw, y - bw
    xs0, xs1 = max(0, fx0), min(W, fx0 + framed.shape[1])
    if xs1 <= xs0:
        return out
    ys0, ys1 = max(0, fy0), min(H, fy0 + framed.shape[0])
    if ys1 <= ys0:
        return out
    sub = framed[ys0 - fy0:ys1 - fy0, xs0 - fx0:xs1 - fx0]
    sm = fmask[ys0 - fy0:ys1 - fy0, xs0 - fx0:xs1 - fx0].astype(np.float32)[..., None] / 255.0
    roi = out[ys0:ys1, xs0:xs1].astype(np.float32)
    out[ys0:ys1, xs0:xs1] = (roi * (1 - sm) + sub.astype(np.float32) * sm).astype(np.uint8)
    del mask
    return out


def crystal_ball(R: Reprojector, Rb: Reprojector, equi: np.ndarray, bg_view: View, inner: View, pop: float) -> np.ndarray:
    W, H = R.W, R.H
    bg = R.render(equi, bg_view)
    small = cv2.resize(bg, (W // 5, H // 5), interpolation=cv2.INTER_AREA)
    bg = cv2.resize(cv2.GaussianBlur(small, (0, 0), 5), (W, H), interpolation=cv2.INTER_LINEAR)
    bg = (bg.astype(np.float32) * 0.6).astype(np.uint8)
    D = Rb.W
    ball = Rb.render(equi, inner)
    rad = D / 2 * max(0.05, pop)
    yy, xx = np.mgrid[0:D, 0:D].astype(np.float32)
    rr = np.sqrt((xx - D / 2) ** 2 + (yy - D / 2) ** 2) / max(rad, 1)
    # refraction-ish edge darkening + rim + specular highlight
    mask = np.clip((1.0 - rr) * D * 0.02, 0, 1)
    shade = (1.0 - 0.45 * np.clip(rr, 0, 1) ** 3)[..., None]
    lit = ball.astype(np.float32) * shade
    rim = np.exp(-((rr - 0.97) / 0.025) ** 2)[..., None] * 140
    spec = np.exp(-(((xx - D * 0.36) / (D * 0.09)) ** 2 + ((yy - D * 0.3) / (D * 0.05)) ** 2))[..., None] * 170
    lit = np.clip(lit + rim + spec, 0, 255)
    out = bg.astype(np.float32)
    x0, y0 = (W - D) // 2, (H - D) // 2
    roi = out[y0:y0 + D, x0:x0 + D]
    m = mask[..., None]
    # contact shadow under the ball
    out[y0:y0 + D, x0:x0 + D] = roi * (1 - m) + lit * m
    return np.clip(out, 0, 255).astype(np.uint8)


# --------------------------------------------------------------------------- main
def render_clip(project, edl: EDL, c: Clip, clip_start: float, out: Path, W: int, H: int, fps: int, *, quick: bool,
                encoder: str, lut_name: str, color_filter: str, cwd: Path) -> Path:
    from ..render import atempo_chain, reframe_filter  # local import (render imports this module lazily)

    if c.generated:   # bake_clip / preview paths come here too
        from .terminal import render_terminal
        return render_terminal(project, edl, c, clip_start, out, W, H, fps, quick=quick, encoder=encoder,
                               lut_name=lut_name, color_filter=color_filter, cwd=cwd)

    rcfg = config.settings().get("render") or {}
    src = Path(c.src)
    src = src if src.is_absolute() else project.root / src
    if not src.exists():
        raise FileNotFoundError(f"素材不存在：{src}")
    pi = probe(src)
    is_img = kind_of(src) == "image"
    dur_out = c.duration
    N = max(1, int(round(dur_out * fps)))
    src_t = np.array([c.out_to_src(k / fps) for k in range(N + 1)])
    sfps = float(pi.fps or fps) if not is_img else float(fps)
    min_speed = float(np.min(np.diff(src_t)) * fps) if N > 1 else c.speed
    interp = c.ramp.interp if c.ramp else "blend"
    if interp == "blend" and rcfg.get("minterpolate"):
        interp = "flow"
    if int(rcfg.get("fx_threads", 0) or 0) > 0:
        cv2.setNumThreads(int(rcfg["fx_threads"]))
    F = float(fps)
    pre = []
    if not is_img and min_speed < 0.95:
        F = float(min(max(fps, round(sfps)), 120))  # use real high-fps frames for slow motion
        if interp == "flow" and F < fps / max(min_speed, 0.05) * 0.9:
            Fm = min(120, int(math.ceil(fps / max(min_speed, 0.1))))
            pre.append(f"minterpolate=fps={Fm}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1")
            F = float(Fm)
    seek = max(0.0, c.in_)
    span = float(src_t.max() - c.in_) + 3.0 / F
    seed = int(abs(hash((c.id, c.media_id))) % 100000)

    # ---- decoder geometry
    dw, dh = (pi.width, pi.height) if is_img else pi.display_size
    equirect = c.projection == "equirect"
    if equirect:
        cap = int(rcfg.get("equirect_width", 5760)) if not quick else 2880
        bw = _even(min(dw, cap))
        bh = bw // 2
        geo = f"scale={bw}:{bh}:flags=bicubic"
    from .. import reframe as RF
    rmode = c.reframe_mode() if (not equirect and H > W and dw and dh) else ""
    rmode = rmode if rmode in ("follow", "fit_blur", "fit_bars") else ""
    rcf = RF.cfg() if rmode else {}
    OW, OH = W, H                      # size of the picture the camera/effects work on (content band for fit/follow)
    if rmode:
        loose, fz_ = float(rcf["loose"]), float(rcf["fit_zoom"])
        OW, OH = RF.content_size(rmode, dw, dh, W, H, loose, fz_)
        if rmode == "follow":
            wn = float((c.reframe or {}).get("width") or RF.window_frac(dw, dh, W, H, loose))
            bw0, bh0 = _even(OW / wn), OH
        else:
            bw0, bh0 = _even(OW * (fz_ if rmode == "fit_blur" else 1.0)), OH
        extra = 1.0
        mv0 = c.move.type if c.move else "none"
        if mv0 not in ("none", "subject") or any(f.type in CAMERA_FX for f in c.fx):
            extra = 1.3
        bw, bh = _even(bw0 * extra), _even(bh0 * extra)
        geo = f"scale={bw}:{bh}:flags=bicubic"
    else:
        mode = edl.reframe
        sa, ta = (dw / dh if dh else 16 / 9), W / H
        if mode == "auto":
            mode = "blur_pad" if sa < ta * 0.97 and ta >= 1 else "crop"
        if abs(sa - ta) / ta < 0.03 or mode == "crop" or c.focus_track:
            cover = max(W / dw, H / dh) if dw and dh else 1.0
            extra = 1.0
            mv = c.move.type if c.move else "none"
            if mv not in ("none", "subject") or any(f.type in CAMERA_FX for f in c.fx):
                extra = max(1.0, min(1.5, 1.0 / cover))  # keep up to 1.5× resolution for zooms
            bw, bh = _even(dw * cover * extra), _even(dh * cover * extra)
            bw, bh = max(bw, W), max(bh, H)
            geo = f"scale={bw}:{bh}:flags=bicubic"
        else:
            bw, bh = W, H
            geo = reframe_filter(mode, dw, dh, W, H, c.focus_x)
    vf = ",".join([*pre, f"fps={F}", geo, "format=bgr24"]) if not is_img else f"{geo},format=bgr24"
    if is_img:
        dcmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-loop", "1", "-framerate", str(F),
                "-t", f"{span:.3f}", "-i", str(src), "-filter_complex", f"[0:v]{vf}", "-f", "rawvideo", "pipe:1"]
    else:
        dcmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-ss", f"{seek:.3f}", "-t", f"{span:.3f}",
                "-i", str(src), "-an", "-filter_complex", f"[0:v]{vf}", "-f", "rawvideo", "pipe:1"]
    reader = FrameReader(dcmd, bw, bh)

    # ---- secondary (PIP) reader
    pip_reader = None
    pip_size = (0, 0)
    if c.pip:
        p2 = Path(c.pip.src)
        p2 = p2 if p2.is_absolute() else project.root / p2
        pi2 = probe(p2)
        d2w, d2h = pi2.display_size
        if c.pip.layout == "split_lr":
            pw, ph = OW - OW // 2, OH
        elif c.pip.layout == "split_tb":
            pw, ph = OW, OH - OH // 2
        else:
            ar2 = (d2h / d2w if d2w else 9 / 16) if c.pip.projection != "equirect" else 9 / 16
            pw = _even(OW * c.pip.scale) if OW >= OH else _even(OW * c.pip.scale * 1.6)
            ph = _even(pw * ar2)
            if ph > OH * 0.5:  # portrait source in a landscape frame → limit by height
                ph = _even(OH * 0.5)
                pw = _even(ph / ar2)
        pip_size = (pw, ph)
        cover2 = f"scale={pw}:{ph}:force_original_aspect_ratio=increase,crop={pw}:{ph}"
        if c.pip.projection == "equirect":
            cover2 = f"v360=e:flat:h_fov=100:v_fov=62:pitch=-5:w={pw}:h={ph}"
        pcmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-ss", f"{c.pip.in_:.3f}", "-t", f"{dur_out + 0.2:.3f}",
                "-i", str(p2), "-an", "-vf", f"fps={fps},{cover2},format=bgr24", "-f", "rawvideo", "pipe:1"]
        pip_reader = FrameReader(pcmd, pw, ph)

    # ---- encoder (+ audio)
    from ..render import _audio_chain_for  # noqa: PLC0415
    venc = (video_encode_args(encoder, {"crf": 16, "nvenc_cq": 17}, fast=True) if not quick
            else video_encode_args("libx264" if "nvenc" not in encoder else encoder, {"crf": 23}, fast=True))
    post = [x for x in (color_filter, f"lut3d=file={lut_name}" if lut_name else "") if x]
    vpost = ",".join([*post, "setsar=1", "format=yuv420p"])
    has_audio = pi.has_audio and not is_img and c.volume > 0.001
    ecmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-v", "error",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "pipe:0"]
    if has_audio:
        ecmd += ["-ss", f"{c.in_:.3f}", "-t", f"{c.src_duration + 0.1:.3f}", "-i", str(src)]
        afc = _audio_chain_for(c, "[1:a]", dur_out)
    else:
        ecmd += ["-f", "lavfi", "-t", f"{dur_out:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        afc = "[1:a]aformat=sample_fmts=fltp:channel_layouts=stereo[a]"
    ecmd += ["-filter_complex", f"[0:v]{vpost}[v];{afc}", "-map", "[v]", "-map", "[a]", "-t", f"{dur_out:.3f}",
             *venc, "-g", str(fps), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-r", str(fps),
             "-video_track_timescale", str(fps * 1000), str(out)]
    enc = subprocess.Popen(ecmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(cwd), **_NOWIN)
    edrain = _Drain(enc.stderr)
    edrain.start()

    # ---- per-clip state
    beats = _local_beats(edl, clip_start, dur_out)
    fx_img = [(f, make_effect(f.type, OW, OH, fps, f.intensity, f.params, seed + i)) for i, f in enumerate(c.fx)
              if f.type not in CAMERA_FX]
    fx_img += [(f, make_effect(f.type, OW, OH, fps, f.intensity, f.params, seed + 50 + i)) for i, f in enumerate(edl.look)]
    fx_img = [(f, e) for f, e in fx_img if e is not None]
    fx_img.sort(key=lambda fe: HUD_ORDER.get(fe[0].type, 0))   # stable: lens_look, then tracker_hud last
    ctx = None
    ctx_specs = [(f, e) for f, e in fx_img if getattr(e, "needs_ctx", False)]
    if ctx_specs:
        from .trackctx import TrackCtx
        merged: dict = {}
        for f, _ in ctx_specs:
            merged.update({k: v for k, v in f.params.items() if k in CTX_KEYS})
        merged.setdefault("cuts", [])
        ctx = TrackCtx(OW, OH, fps, dur_out, merged, beats=beats, seed=seed)
        for _, e in ctx_specs:
            e.bind(ctx)
    punch = next((f for f in c.fx if f.type == "punch"), None)
    shake = next((f for f in c.fx if f.type == "shake"), None)
    punch_beats = beats if not punch or not punch.params.get("times") else list(punch.params["times"])
    if punch and punch.params.get("every"):
        punch_beats = _local_beats(edl, clip_start, dur_out, int(punch.params["every"]), bool(punch.params.get("down")))
    mv = c.move.type if c.move else ("follow" if equirect else "none")
    mparams = dict(c.move.params) if c.move else {}
    if equirect:
        shot = Shot360(mv, mparams, c.base_duration, portrait=H > W, yaw_track=c.yaw_track)
        R = Reprojector(W, H, bw, bh)
        Rb = Reprojector(_even(min(W, H) * 0.84), _even(min(W, H) * 0.84), bw, bh) if shot.special == "crystal_ball" else None
        cam = None
    else:
        shot = R = Rb = None
        ftrack = c.focus_track
        if rmode == "follow":
            ftrack = [[t_, x_, 0.5] for t_, x_ in (c.reframe or {}).get("track") or []] or [[0.0, 0.5, 0.5]]
        elif rmode:
            ftrack = None
        cam = Camera2D(mv, mparams, c.base_duration, OW, OH, bw, bh, focus_track=ftrack, focus_x=c.focus_x if not rmode else 0.5,
                       beats=punch_beats if punch else beats,
                       shake=(0.25 + 0.6 * shake.intensity) if shake else 0.0,
                       shake_beats=bool(shake and shake.params.get("on") == "beats"),
                       punch=(0.05 + 0.13 * punch.intensity) if punch else 0.0, seed=seed)

    def view_at(t: float) -> View:
        v = shot.view(t)  # type: ignore[union-attr]
        if punch:
            v = v.with_(fov=v.fov * (1.0 - (0.08 + 0.14 * punch.intensity) * pulse_env(t, punch_beats, 0.16)))
        if shake:
            from .camera2d import _noise
            a = 0.6 + 2.0 * shake.intensity
            v = v.with_(yaw=v.yaw + a * _noise(t, seed + 1, (1.3, 2.9, 5.1)), pitch=v.pitch + 0.7 * a * _noise(t, seed + 2, (1.1, 3.3, 4.9)),
                        roll=v.roll + 0.5 * a * _noise(t, seed + 3))
        return v

    shutter = 0.5 / fps
    frozen: np.ndarray | None = None
    fz = c.freeze
    try:
        for i in range(N):
            t = i / fps
            in_hold = fz is not None and fz.at <= t < fz.at + fz.hold
            t_cam = t if fz is None or t < fz.at else (fz.at if in_hold else t - fz.hold)
            if in_hold and frozen is not None:
                frame = freeze_card(frozen, t - fz.at, fz.hold, fz.style)  # type: ignore[union-attr]
            else:
                # --- source frame(s) for this output time (blend for slow-mo, average for fast)
                ts0, ts1 = src_t[i], src_t[i + 1]
                pos = (ts0 - seek) * F
                k0 = int(math.floor(pos))
                frac = pos - k0
                step = (ts1 - ts0) * F
                if step > 1.6:
                    n = int(min(6, math.ceil(step)))
                    acc = None
                    for j in range(n):
                        f = reader.get(k0 + j).astype(np.float32)
                        acc = f if acc is None else acc + f
                    base = (acc / n).astype(np.uint8)  # type: ignore[operator]
                elif interp != "nearest" and 0.08 < frac < 0.92 and step < 0.95:
                    base = cv2.addWeighted(reader.get(k0), 1 - frac, reader.get(k0 + 1), frac, 0)
                else:
                    base = reader.get(int(round(pos)))
                # --- camera
                if equirect:
                    if shot.special == "crystal_ball":  # type: ignore[union-attr]
                        bgv, inner, pop = shot.ball(t_cam)  # type: ignore[union-attr]
                        frame = crystal_ball(R, Rb, base, bgv, inner, pop)  # type: ignore[arg-type]
                    else:
                        v0, v1 = view_at(t_cam), view_at(t_cam + shutter)
                        dyaw = abs((v1.yaw - v0.yaw + 180) % 360 - 180)
                        disp = (dyaw + abs(v1.pitch - v0.pitch) + abs(v1.roll - v0.roll)) * W / max(v0.fov, 30) \
                            + abs(v1.fov - v0.fov) * W / 200
                        ns = int(min(9, max(1, math.ceil(disp / 5))))
                        if ns > 1:
                            views = [View(v0.yaw + (((v1.yaw - v0.yaw + 180) % 360) - 180) * k / (ns - 1),
                                          v0.pitch + (v1.pitch - v0.pitch) * k / (ns - 1), v0.roll + (v1.roll - v0.roll) * k / (ns - 1),
                                          v0.fov + (v1.fov - v0.fov) * k / (ns - 1), v0.d + (v1.d - v0.d) * k / (ns - 1))
                                     for k in range(ns)]
                            frame = R.render_blur(base, views)  # type: ignore[union-attr]
                        else:
                            frame = R.render(base, v0)  # type: ignore[union-attr]
                else:
                    s0, s1 = cam.state(t_cam), cam.state(t_cam + shutter)  # type: ignore[union-attr]
                    disp = cam.displacement_px(s0, s1)  # type: ignore[union-attr]
                    ns = int(min(8, max(1, math.ceil(disp / 6))))
                    flags = cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP
                    if ns > 1:
                        acc = None
                        for k in range(ns):
                            u = k / (ns - 1)
                            from .camera2d import Cam
                            st = Cam(s0.cx + (s1.cx - s0.cx) * u, s0.cy + (s1.cy - s0.cy) * u,
                                     s0.zoom + (s1.zoom - s0.zoom) * u, s0.angle + (s1.angle - s0.angle) * u)
                            f = cv2.warpAffine(base, cam.matrix(st), (OW, OH), flags=flags, borderMode=cv2.BORDER_REFLECT101).astype(np.float32)  # type: ignore[union-attr]
                            acc = f if acc is None else acc + f
                        frame = (acc / ns).astype(np.uint8)  # type: ignore[operator]
                    else:
                        frame = cv2.warpAffine(base, cam.matrix(s0), (OW, OH), flags=flags, borderMode=cv2.BORDER_REFLECT101)  # type: ignore[union-attr]
                if fz is not None and frozen is None and t + 1.0 / fps > fz.at:
                    frozen = frame.copy()
                    if in_hold:
                        frame = freeze_card(frozen, t - fz.at, fz.hold, fz.style)
            # --- picture in picture
            if pip_reader is not None:
                frame = compose_pip(frame, pip_reader.get(i), c.pip.layout, t)  # type: ignore[union-attr]
            # --- looks / effects
            if ctx is not None:
                ctx.update(frame, i, t)
            bg_src = None
            for spec, eff in fx_img:
                if rmode and bg_src is None and spec.type == "tracker_hud":
                    bg_src = frame          # padding is built from the picture *before* the HUD → no blurred boxes
                env = _fx_env(spec, t, dur_out, beats)
                frame = eff(frame, t, env)
            if rmode:
                frame = RF.compose(frame, W, H, rmode, frame if bg_src is None else bg_src,
                                   float(rcf["bg_blur"]), float(rcf["bg_dim"]))
            enc.stdin.write(np.ascontiguousarray(frame).tobytes())  # type: ignore[union-attr]
        enc.stdin.close()  # type: ignore[union-attr]
    except BrokenPipeError:
        pass
    finally:
        reader.close()
        if pip_reader is not None:
            pip_reader.close()
    rc = enc.wait()
    edrain.join(timeout=5)
    if rc != 0:
        out.unlink(missing_ok=True)
        raise FFmpegError(f"片段 {c.id} 编码失败：" + "".join(edrain.lines))
    _ = pip_size
    return out
