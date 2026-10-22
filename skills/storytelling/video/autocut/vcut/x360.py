"""Raw Insta360 .insv → 2:1 equirect (emergency stitch with ffmpeg v360 dual-fisheye).

Honest scope (see README「360° 素材」):
  * X5/X4 (≥5.7K) store BOTH lenses as two square HEVC video tracks in one .insv  → `two_track`
  * some modes/older models store one side-by-side ~2:1 dual-fisheye frame         → `side_by_side`
  * older ≥5.7K captures split lenses into VID_..._00_xxx.insv + VID_..._10_xxx.insv → `dual_file`
This is a plain geometric dewarp: NO FlowState/IMU stabilisation, NO horizon lock, NO optical-flow seam
blending, NO per-lens calibration (lens FOV/centre are guesses → visible seam/parallax).
Lens order and roll were NOT verified on a real X5 capture → `--swap` / `--back-rot180` / `--roll` exist
so you can fix a mirrored/upside-down result after looking at the preview JPG.
For delivery quality use Insta360 Studio (export 2:1 panorama) or the Insta360 Media SDK.
"""
from __future__ import annotations

import re
from pathlib import Path

from .media import ffmpeg, ffprobe_json, pick_encoder, video_encode_args

DEFAULT_FOV = 193.0  # X-series fisheyes are ~190–200°; v360 dfisheye ih_fov/iv_fov


def insv_layout(path: Path) -> dict:
    """Inspect a raw 360 file → {layout, streams:[{w,h}], partner, has_audio, duration}."""
    path = Path(path)
    j = ffprobe_json(path)
    vs = [s for s in j.get("streams", []) if s.get("codec_type") == "video"
          and not (s.get("disposition") or {}).get("attached_pic")]
    has_audio = any(s.get("codec_type") == "audio" for s in j.get("streams", []))
    dur = float((j.get("format") or {}).get("duration") or 0)
    streams = [{"w": int(s.get("width") or 0), "h": int(s.get("height") or 0), "codec": s.get("codec_name")} for s in vs]
    partner = None
    m = re.search(r"_(00|10)_(\d{3})", path.name)
    if m:
        other = "10" if m.group(1) == "00" else "00"
        cand = path.with_name(path.name[:m.start()] + f"_{other}_{m.group(2)}" + path.name[m.end():])
        if cand.exists():
            partner = cand
    if len(streams) >= 2 and all(abs(s["w"] - s["h"]) <= 16 for s in streams[:2]):
        layout = "two_track"
    elif len(streams) == 1 and streams[0]["h"] and abs(streams[0]["w"] / streams[0]["h"] - 2.0) < 0.05:
        layout = "side_by_side"
    elif len(streams) == 1 and partner is not None:
        layout = "dual_file"
    else:
        layout = "unknown"
    return {"layout": layout, "streams": streams, "partner": str(partner) if partner else None,
            "has_audio": has_audio, "duration": dur}


def stitch_filter(layout: str, *, fov: float = DEFAULT_FOV, swap: bool = False, back_rot180: bool = False,
                  yaw: float = 0.0, pitch: float = 0.0, roll: float = 0.0, width: int = 5760) -> tuple[str, list[str]]:
    """Return (filter_complex, extra input args) producing [v] equirect width×width/2."""
    w = int(width) // 2 * 2
    h = w // 2
    rot = f":yaw={yaw:g}:pitch={pitch:g}:roll={roll:g}" if (yaw or pitch or roll) else ""
    v360 = f"v360=input=dfisheye:output=e:ih_fov={fov:g}:iv_fov={fov:g}:w={w}:h={h}:interp=lanczos{rot}"
    if layout in ("two_track", "dual_file"):
        a, b = ("[0:v:0]", "[0:v:1]") if layout == "two_track" else ("[0:v:0]", "[1:v:0]")
        if swap:
            a, b = b, a
        pre = ""
        if back_rot180:
            pre = f"{b}hflip,vflip[bk];"
            b = "[bk]"
        return f"{pre}{a}{b}hstack=inputs=2:shortest=1,{v360},format=yuv420p[v]", []
    if layout == "side_by_side":
        if swap or back_rot180:
            fc = "[0:v:0]split[l0][r0];[l0]crop=iw/2:ih:0:0[l];[r0]crop=iw/2:ih:iw/2:0[r];"
            r = "[r]"
            if back_rot180:
                fc += "[r]hflip,vflip[rr];"
                r = "[rr]"
            pair = f"{r}[l]" if swap else f"[l]{r}"
            return f"{fc}{pair}hstack=inputs=2,{v360},format=yuv420p[v]", []
        return f"[0:v:0]{v360},format=yuv420p[v]", []
    raise ValueError(f"不认识的 .insv 布局：{layout}")


def stitch_insv(src: Path, out: Path, *, fov: float = DEFAULT_FOV, swap: bool = False, back_rot180: bool = False,
                yaw: float = 0.0, pitch: float = 0.0, roll: float = 0.0, width: int = 5760,
                start: float = 0.0, duration: float | None = None, encoder: str = "auto",
                preview: Path | None = None) -> dict:
    src, out = Path(src), Path(out)
    lay = insv_layout(src)
    if lay["layout"] == "unknown":
        raise ValueError(f"无法识别 {src.name} 的镜头布局：{lay['streams']}（只支持 X5/X4 双轨、单帧双鱼眼、_00_/_10_ 双文件）")
    fc, _ = stitch_filter(lay["layout"], fov=fov, swap=swap, back_rot180=back_rot180, yaw=yaw, pitch=pitch,
                          roll=roll, width=width)
    inputs = ["-ss", f"{start:.3f}", "-i", str(src)]
    if lay["layout"] == "dual_file":
        inputs += ["-ss", f"{start:.3f}", "-i", lay["partner"]]
    tl = ["-t", f"{duration:.3f}"] if duration else []
    out.parent.mkdir(parents=True, exist_ok=True)
    if preview is not None:
        preview.parent.mkdir(parents=True, exist_ok=True)
        pfc = fc[:-3] + ",scale=2048:1024[v]"
        ffmpeg([*inputs, "-filter_complex", pfc, "-map", "[v]", "-frames:v", "1", "-q:v", "3", str(preview)])
    enc = pick_encoder(encoder)
    if enc == "h264_nvenc" and width > 4096:  # NVENC H.264 tops out at 4096 wide
        enc = "hevc_nvenc"
    amap = ["-map", "0:a:0?", "-c:a", "aac", "-b:a", "192k"]
    args = [*inputs, *tl, "-filter_complex", fc, "-map", "[v]", *amap,
            *video_encode_args(enc),
            "-metadata:s:v:0", "spherical=equirectangular", "-movflags", "+faststart", str(out)]
    ffmpeg(args)
    return {"out": str(out), "layout": lay["layout"], "preview": str(preview) if preview else None, "encoder": enc}


def make_fake_insv(equirect: Path, out: Path, *, fov: float = DEFAULT_FOV, size: int = 512,
                   duration: float = 2.0) -> Path:
    """Test helper: equirect → two square fisheye tracks in one container (mimics the X5 layout)."""
    fc = (f"[0:v]v360=input=e:output=dfisheye:h_fov={fov:g}:v_fov={fov:g}:w={size * 2}:h={size},"
          f"split[a][b];[a]crop={size}:{size}:0:0[f];[b]crop={size}:{size}:{size}:0[r]")
    ffmpeg(["-t", f"{duration:.3f}", "-i", str(equirect), "-filter_complex", fc, "-map", "[f]", "-map", "[r]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-f", "mp4", str(out)])
    return out
