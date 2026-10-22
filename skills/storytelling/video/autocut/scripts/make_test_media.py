"""Generate synthetic test footage with FFmpeg (no real camera files needed).

python scripts/make_test_media.py <out_dir> [--small]

Creates clips whose *filenames and metadata* mimic common cameras so device detection,
scene detection, ASR (ffmpeg flite TTS, English) and rendering can be exercised end to end.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

FF = shutil.which("ffmpeg") or "ffmpeg"


def ff(*args: str) -> None:
    cmd = [FF, "-hide_banner", "-loglevel", "error", "-y", *args]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"ffmpeg failed: {' '.join(cmd)}\n{r.stderr}")


def has_filter(name: str) -> bool:
    out = subprocess.run([FF, "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    return f" {name} " in out


def make(out: Path, small: bool = False) -> dict[str, Path]:
    out.mkdir(parents=True, exist_ok=True)
    W, H = (960, 540) if small else (1920, 1080)
    enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k"]
    files: dict[str, Path] = {}

    # 1) "Ace Pro 2" action clip: 3 hard scene changes, ambient tone
    p = out / "PRO_VID_20260301_101500_00_001.mp4"
    ff("-f", "lavfi", "-i", f"testsrc2=s={W}x{H}:r=30:d=4",
       "-f", "lavfi", "-i", f"mandelbrot=s={W}x{H}:r=30,trim=duration=4",
       "-f", "lavfi", "-i", f"smptehdbars=s={W}x{H}:r=30:d=4",
       "-f", "lavfi", "-i", "sine=f=180:d=12,volume=0.08",
       "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0,format=yuv420p[v]",
       "-map", "[v]", "-map", "3:a", *enc, "-metadata", "comment=Insta360 Ace Pro 2", str(p))
    files["ace"] = p

    # 2) "GO Ultra" POV clip: moving pattern + noise ambience
    p = out / "VID_20260301_102000_00_002.mp4"
    ff("-f", "lavfi", "-i", f"cellauto=s={W}x{H}:rule=110:r=30,trim=duration=5",
       "-f", "lavfi", "-i", f"rgbtestsrc=s={W}x{H}:r=30:d=5",
       "-f", "lavfi", "-i", "anoisesrc=d=10:c=pink:a=0.03",
       "-filter_complex", "[0:v]format=yuv420p,hue=h=t*40[a];[1:v]format=yuv420p,rotate=0.02*sin(2*PI*t)[b];[a][b]concat=n=2:v=1:a=0[v]",
       "-map", "[v]", "-map", "2:a", *enc, str(p))
    files["go"] = p

    # 3) "OnePlus 12" talking head with TTS speech (Android metadata tags)
    p = out / "VID20260301103000.mp4"
    lines = ["Hello everyone, welcome back to my channel.",
             "Today I will show you my new maker project, a smart desk lamp.",
             "It uses an ESP32 and a light sensor to adjust brightness automatically.",
             "Let me show you how I built it and how it works."]
    if has_filter("flite"):
        parts, labels = [], []
        for i, t in enumerate(lines):
            parts += ["-f", "lavfi", "-i", f"flite=text='{t}':voice=slt"]
            labels.append(f"[{i}:a]aresample=48000,apad=pad_dur=0.8[s{i}]")
        concat = ";".join(labels) + ";" + "".join(f"[s{i}]" for i in range(len(lines))) + f"concat=n={len(lines)}:v=0:a=1[a]"
        ff(*parts, "-filter_complex", concat, "-map", "[a]", str(out / "_speech.wav"))
    else:  # fallback: beeps standing in for speech
        ff("-f", "lavfi", "-i", "sine=f=300:d=16,volume=0.5", str(out / "_speech.wav"))
    ff("-f", "lavfi", "-i", f"color=c=0x2b3a4a:s={W}x{H}:r=30",
       "-i", str(out / "_speech.wav"),
       "-filter_complex",
       f"[0:v]drawbox=x=iw/2-{W // 10}+20*sin(t):y=ih/2-{H // 4}:w={W // 5}:h={H // 2}:color=0xe0b090@1:t=fill,"
       f"drawbox=x=iw/2-{W // 6}:y=ih*0.78:w={W // 3}:h={H // 6}:color=0x445566@1:t=fill,format=yuv420p[v]",
       "-map", "[v]", "-map", "1:a", "-shortest", *enc,
       "-movflags", "use_metadata_tags", "-metadata", "com.android.manufacturer=OnePlus",
       "-metadata", "com.android.model=PJD110", str(p))
    (out / "_speech.wav").unlink(missing_ok=True)
    files["talk"] = p

    # 4) portrait phone detail clip (tests 9:16 → 16:9 blur-pad)
    p = out / "VID20260301104000.mp4"
    ff("-f", "lavfi", "-i", f"testsrc=s={H}x{W}:r=30:d=6", "-f", "lavfi", "-i", "sine=f=440:d=6,volume=0.05",
       "-map", "0:v", "-map", "1:a", *enc, "-movflags", "use_metadata_tags",
       "-metadata", "com.android.manufacturer=OnePlus", "-metadata", "com.android.model=PJD110", str(p))
    files["portrait"] = p

    # 5) fake 360 raw + proxy (should be flagged, not ingested)
    (out / "VID_20260301_105000_00_003.insv").write_bytes(b"\x00" * 1024)
    (out / "LRV_20260301_105000_11_003.lrv").write_bytes(b"\x00" * 512)

    # 6) music bed: 120 BPM pulse (beat every 0.5 s) with a chord
    mdir = out / "music" / "电子_科技"
    mdir.mkdir(parents=True, exist_ok=True)
    p = mdir / "test_beat_120bpm.wav"
    ff("-f", "lavfi", "-i",
       "aevalsrc='0.5*sin(2*PI*60*t)*exp(-12*mod(t,0.5))+0.12*sin(2*PI*220*t)+0.08*sin(2*PI*277*t)+0.06*sin(2*PI*330*t)'"
       ":s=44100:d=40", "-ac", "2", str(p))
    files["music"] = p

    # 7) logo PNG with alpha
    p = out / "logo.png"
    ff("-f", "lavfi", "-i", "color=c=0xff6a00@1:s=400x160,format=rgba,"
       "drawbox=x=20:y=20:w=360:h=120:color=white@0.9:t=8", "-frames:v", "1", str(p))
    files["logo"] = p
    return files


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--small", action="store_true", help="960x540 for fast unit tests")
    a = ap.parse_args()
    for k, v in make(a.out, a.small).items():
        print(f"{k}: {v}")
    sys.exit(0)
