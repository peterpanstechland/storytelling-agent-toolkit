"""v2 效果展示片：360 运镜 + 平面运镜/卡点 + 特效 + 自定义转场 + 文字动画 + 画中画 + 自动音效。

    python scripts/make_showcase.py [输出目录]        # 默认 ./showcase_out
输出：showcase_16x9.mp4（≤60s）、showcase_9x16.mp4（竖屏验证）、showcase_contact.jpg（关键帧联系表）。
素材全部程序生成（合成的 2:1 全景场景 + 由它投影出的平面镜头 + mandelbrot + 合成鼓点），不需要真实素材。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from vcut.edl import EDL, FX, PIP, AudioItem, Clip, Freeze, Move, Ramp, TextOverlay, Transition  # noqa: E402
from vcut.fx.sfx import get_sfx  # noqa: E402
from vcut.fx.track import track_360, track_flat  # noqa: E402
from vcut.media import ffmpeg  # noqa: E402
from vcut.project import Project  # noqa: E402
from vcut.render import render  # noqa: E402

BPM = 120
BEAT = 60 / BPM


def make_media(md: Path) -> dict[str, Path]:
    md.mkdir(parents=True, exist_ok=True)
    eq = md / "VID_20260301_110000_00_010_equirect.mp4"
    if not eq.exists():
        from make_equirect import make_equirect
        make_equirect(eq, W=2880, dur=12, fps=30)
    out = {"eq": eq}
    for name, yaw, fov in (("flatA", 70, 78), ("flatB", -165, 70)):
        p = md / f"{name}.mp4"
        if not p.exists():
            ffmpeg(["-i", str(eq), "-vf", f"v360=e:flat:yaw={yaw}:pitch=-4:h_fov={fov}:v_fov={fov * 9 / 16 * 1.12:.1f}:w=1920:h=1080",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-an", str(p)])
        out[name] = p
    p = md / "mandel.mp4"
    if not p.exists():
        ffmpeg(["-f", "lavfi", "-i", "mandelbrot=size=1920x1080:rate=30:start_scale=2.5:end_scale=0.6", "-t", "9",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(p)])
    out["mandel"] = p
    p = md / "beat_120.wav"
    if not p.exists():  # kick on every beat, snare on 2/4, hats on 8ths
        expr = ("0.9*sin(2*PI*(45+90*exp(-mod(t,0.5)*30))*t)*exp(-mod(t,0.5)*9)"
                "+0.35*(random(0)-0.5)*exp(-mod(t-0.5,1)*25)*gte(mod(t,1),0.5)"
                "+0.12*(random(1)-0.5)*exp(-mod(t,0.25)*60)")
        ffmpeg(["-f", "lavfi", "-i", f"aevalsrc='{expr}':s=48000:d=70", "-ac", "2", str(p)])
    out["music"] = p
    return out


def lab(t0, t1, text, anim, kind="lower_third"):
    return TextOverlay(start=round(t0, 3), end=round(t1, 3), text=text, kind=kind, anim=anim)


def build_16x9(m: dict[str, Path], proj: Project) -> EDL:
    eq, A, B, MD = str(m["eq"]), str(m["flatA"]), str(m["flatB"]), str(m["mandel"])
    tr = track_360(m["eq"], 0, 12)["track"]

    def ytr(a, b):  # slice the full-clip yaw track to [a,b] clip-local
        pts = [[round(t - a, 3), y, p] for t, y, p in tr if a - 0.6 <= t <= b + 0.6]
        return pts

    def E(cid, a, b, move, params=None, t="cut", d=0.0, fx=None):
        return Clip(id=cid, media_id="eq", src=eq, **{"in": a}, out=b, projection="equirect",
                    move=Move(type=move, params=params or {}), yaw_track=ytr(a, b), fx=fx or [],
                    transition_in=Transition(type=t, duration=d), role="establishing", section="s360")

    def F(cid, src, a, b, t="cut", d=0.0, sec="s2d", **kw):
        return Clip(id=cid, media_id=Path(src).stem, src=src, **{"in": a}, out=b, transition_in=Transition(type=t, duration=d),
                    role="action", section=sec, volume=0.0, **kw)

    clips = [
        E("c01", 0.0, 4.5, "planet_intro"),
        E("c02", 4.5, 8.5, "follow"),
        E("c03", 0.0, 4.0, "orbit", {"turns": 0.6}, "whip_left", 0.35),
        E("c04", 8.5, 11.0, "whip360", {"delta": 150}),
        E("c05", 2.0, 6.0, "hero", t="light_leak", d=0.5),
        E("c06", 6.0, 9.0, "rabbit_hole", t="zoom_through", d=0.4),
        E("c07", 9.0, 12.0, "crystal_ball", t="spin", d=0.4),
        E("c08", 3.0, 5.5, "tiny_planet", t="flash", d=0.3),
        # ---- camera moves & beat sync
        F("c09", A, 0.0, 3.5, "glitch", 0.3, move=Move(type="push_in", params={"amount": 0.12}),
          fx=[FX(type="punch", intensity=0.9, params={"every": 1})]),
        F("c10", B, 0.0, 3.0, "whip_right", 0.35, move=Move(type="pan", params={"direction": "right", "amount": 0.18}),
          fx=[FX(type="speed_lines", start=1.6, dur=1.2, intensity=0.8)]),
        F("c11", MD, 0.5, 2.5, "spin_ccw", 0.35, move=Move(type="roll", params={"degrees": 6})),
        F("c12", A, 4.0, 6.5, fx=[FX(type="shake", intensity=0.8, params={"on": "beats"}), FX(type="rgb_split", intensity=0.7)]),
        F("c13", A, 6.0, 9.0, "zoom_through", 0.4,
          ramp=Ramp(profile=[[0, 1.0], [0.25, 1.0], [0.4, 0.3], [0.65, 0.3], [0.8, 1.8], [1, 2.0]], interp="blend")),
        F("c14", B, 4.0, 6.5, freeze=Freeze(at=1.1, hold=1.1, text="定格！", style="pop")),
        # ---- effects
        F("c15", B, 6.5, 9.5, "glitch", 0.3, sec="sfx",
          fx=[FX(type="glitch", start=0.4, dur=1.4, intensity=1.0), FX(type="scanlines", intensity=0.5)]),
        F("c16", MD, 3.0, 5.5, "light_leak", 0.5, sec="sfx",
          fx=[FX(type="light_leak", intensity=0.9), FX(type="flare", start=0.8, dur=1.6, intensity=0.9)]),
        F("c17", A, 9.0, 11.5, sec="sfx", fx=[FX(type="vhs", intensity=0.9)]),
        F("c18", B, 0.5, 3.0, "fade", 0.4, sec="sfx", fx=[FX(type="bw", intensity=1.0), FX(type="grain", intensity=0.9),
                                                         FX(type="vignette", intensity=0.8)]),
        F("c19", MD, 6.0, 8.0, "flash", 0.3, sec="sfx", fx=[FX(type="glow", intensity=0.9), FX(type="motion_blur", intensity=0.8)],
          move=Move(type="push_in", params={"amount": 0.2})),
        # ---- PIP / split
        F("c20", A, 0.0, 3.0, "slideleft", 0.3, sec="pip", pip=PIP(src=B, **{"in": 3.0}, layout="split_lr")),
        F("c21", B, 3.0, 6.5, sec="pip", pip=PIP(src=eq, **{"in": 1.0}, layout="pip_br", projection="equirect", scale=0.36)),
    ]
    edl = EDL(project="showcase", title="vcut v2 showcase", type="maker", width=1920, height=1080, fps=30, style="cyber_glitch",
              clips=clips, color_filter="eq=contrast=1.05:saturation=1.1")
    edl.normalize_transitions()
    tl = edl.timeline()
    total = edl.total_duration
    edl.beats = [round(k * BEAT, 3) for k in range(1, int(total / BEAT))]
    edl.downbeats = edl.beats[3::4]
    s2d0, s2d1 = tl[8][0], tl[13][1]
    edl.flashes = [[b, 0.45] for b in edl.downbeats if s2d0 + 0.3 < b < s2d1 - 0.3][::2]
    names = {"c01": "planet_intro 小行星开场", "c02": "follow 自动跟随", "c03": "orbit 环绕", "c04": "whip360 甩镜",
             "c05": "hero 隐形自拍杆", "c06": "rabbit_hole 兔子洞", "c07": "crystal_ball 水晶球", "c08": "tiny_planet 小行星",
             "c09": "push_in + 卡点放大", "c10": "pan 横摇 + 速度线", "c11": "roll 滚转", "c12": "手持晃动 + 色差",
             "c13": "speed ramp 慢动作", "c14": "freeze 定格", "c15": "glitch 故障 + 扫描线", "c16": "漏光 + 镜头光晕",
             "c17": "VHS 录像带", "c18": "黑白胶片颗粒", "c19": "辉光 + 运动拖影", "c20": "分屏", "c21": "画中画（360 小窗）"}
    anims = ["slide_up", "pop", "typewriter", "highlight_box", "fade", "glitch", "kinetic", "stamp"]
    for k, (c, (s, e)) in enumerate(zip(clips, tl)):
        if c.id == "c01":
            continue
        a = anims[k % len(anims)]
        edl.overlays.append(lab(s + 0.15, min(e - 0.1, s + 2.4), names[c.id], a))
    edl.overlays += [
        TextOverlay(start=0.4, end=3.8, text="X5 360° 自动运镜", kind="title", anim="stamp"),
        TextOverlay(start=s2d0 + 0.1, end=s2d0 + 2.0, text="运镜 · 卡点", kind="section", anim="glitch"),
        TextOverlay(start=tl[14][0] + 0.1, end=tl[14][0] + 2.0, text="特效", kind="section", anim="pop"),
        TextOverlay(start=tl[19][0] + 0.1, end=tl[19][0] + 2.0, text="分屏 / 画中画", kind="section", anim="slide_up"),
        TextOverlay(start=tl[13][0] + 1.15, end=tl[13][0] + 2.2, text="看这里", kind="callout", anim="pop",
                    x=0.24, y=0.22, target=[0.47, 0.55]),
        TextOverlay(start=total - 3.0, end=total - 0.1, text="关注我 看更多 Maker 作品", kind="cta", anim="kinetic"),
    ]
    edl.text_anims = {"subtitle": ""}
    edl.progress = {"color": "#3DF5F0", "height": 8, "position": "bottom",
                    "chapters": [[0.0, "360 运镜"], [s2d0, "运镜卡点"], [tl[14][0], "特效"], [tl[19][0], "分屏"]]}
    edl.audio.append(AudioItem(kind="music", src=str(m["music"]), start=0.0, duration=round(total, 3), volume=0.35,
                               fade_in=0.5, fade_out=1.5))
    cache = proj.root / "cache" / "sfx"
    n = 0
    for i, c in enumerate(clips):
        if i == 0:
            continue
        t0, d = tl[i][0], c.transition_in.duration
        kind = {"glitch": "glitch", "flash": "hit", "fade": "", "slideleft": "swish"}.get(c.transition_in.type, "whoosh")
        if c.transition_in.type != "cut" and kind:
            st = t0 + d / 2 - (0.3 if kind == "whoosh" else 0.02)
            edl.audio.append(AudioItem(kind="sfx", tag=kind, src=str(get_sfx(kind, cache, n)), start=round(max(0, st), 3),
                                       duration=0.7, volume=0.5))
            n += 1
        if c.freeze:
            edl.audio.append(AudioItem(kind="sfx", tag="shutter", src=str(get_sfx("shutter", cache, n)),
                                       start=round(t0 + c.freeze.at, 3), duration=0.4, volume=0.6))
    for s0 in (s2d0, tl[14][0], tl[19][0]):
        edl.audio.append(AudioItem(kind="sfx", tag="riser", src=str(get_sfx("riser", cache, 1, 1.2)), start=round(s0 - 1.2, 3),
                                   duration=1.2, volume=0.35))
        edl.audio.append(AudioItem(kind="sfx", tag="hit", src=str(get_sfx("hit", cache, 2)), start=round(s0, 3), duration=0.8,
                                   volume=0.55))
    return edl


def build_9x16(m: dict[str, Path]) -> EDL:
    eq, A = str(m["eq"]), str(m["flatA"])
    tr = track_360(m["eq"], 0, 12)["track"]
    ft = track_flat(m["flatA"], 0.0, 4.0, 1920, 1080)["track"]
    clips = [
        Clip(id="v1", media_id="eq", src=eq, **{"in": 0.0}, out=4.0, projection="equirect", move=Move(type="planet_intro"),
             yaw_track=tr),
        Clip(id="v2", media_id="eq", src=eq, **{"in": 4.0}, out=8.0, projection="equirect", move=Move(type="follow"),
             yaw_track=[[round(t - 4.0, 3), y, p] for t, y, p in tr if t >= 3.4], transition_in=Transition(type="whip_left", duration=0.35)),
        Clip(id="v3", media_id="flatA", src=A, **{"in": 0.0}, out=4.0, move=Move(type="subject"), focus_track=ft,
             transition_in=Transition(type="zoom_through", duration=0.4), volume=0.0),
    ]
    edl = EDL(project="showcase", width=1080, height=1920, fps=30, clips=clips, reframe="crop")
    edl.normalize_transitions()
    edl.overlays = [TextOverlay(start=0.3, end=3.5, text="竖屏 9:16 重构图", kind="title", anim="pop"),
                    TextOverlay(start=8.0, end=11.0, text="横转竖：主体跟随构图", kind="lower_third", anim="slide_up")]
    return edl


def contact_sheet(video: Path, edl: EDL, out: Path, cols: int = 6) -> Path:
    tl = edl.timeline()
    times = []
    for c, (s, e) in zip(edl.clips, tl):
        times.append((c.id + " " + (c.move.type if c.move else ",".join(f.type for f in c.fx) or c.transition_in.type), (s + e) / 2))
        if c.transition_in.type != "cut" and c.transition_in.duration > 0:
            times.append((c.id + " tr:" + c.transition_in.type, s + c.transition_in.duration / 2))
    times.sort(key=lambda x: x[1])
    tiles = []
    for label, t in times:
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", "-vf", "scale=480:-2",
                            "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True)
        img = cv2.imdecode(np.frombuffer(r.stdout, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            continue
        cv2.rectangle(img, (0, 0), (img.shape[1], 26), (0, 0, 0), -1)
        cv2.putText(img, f"{t:5.1f}s {label}", (6, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
        tiles.append(img)
    h, w = tiles[0].shape[:2]
    rows = (len(tiles) + cols - 1) // cols
    sheet = np.zeros((rows * h, cols * w, 3), np.uint8)
    for k, im in enumerate(tiles):
        r, c = divmod(k, cols)
        sheet[r * h:(r + 1) * h, c * w:c * w + im.shape[1]] = im[:h]
    cv2.imwrite(str(out), sheet, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return out


def main() -> None:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "showcase_out").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    m = make_media(out_dir / "media")
    proj_root = out_dir / "showcase"
    proj = Project.open(proj_root) if (proj_root / "project.yaml").exists() else Project.create("showcase", "maker", parent=out_dir)
    edl = build_16x9(m, proj)
    edl.save(out_dir / "showcase_edl.json")
    v = render(proj, edl, out=out_dir / "showcase_16x9.mp4")
    contact_sheet(v, edl, out_dir / "showcase_contact.jpg")
    if "--no-portrait" not in sys.argv:
        e2 = build_9x16(m)
        v2 = render(proj, e2, out=out_dir / "showcase_9x16.mp4")
        contact_sheet(v2, e2, out_dir / "showcase_9x16_contact.jpg", cols=4)
    print(f"完成：{out_dir}")


if __name__ == "__main__":
    main()
