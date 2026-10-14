#!/usr/bin/env python3
"""Report video capabilities without installing packages or downloading models."""
import argparse
import importlib.metadata
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys


def command_output(arguments):
    try:
        result = subprocess.run(arguments, capture_output=True, text=True, timeout=15)
        return result.returncode == 0, result.stdout + result.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require", choices=("render", "inspect", "audio", "transcribe"),
                        default="render", help="capability that determines the exit status")
    parser.add_argument("--model", type=Path, help="optional existing local faster-whisper directory")
    args = parser.parse_args()
    checks = {}
    for package in ("Pillow", "faster-whisper"):
        try:
            checks[package] = {"ok": True, "version": importlib.metadata.version(package)}
        except importlib.metadata.PackageNotFoundError:
            checks[package] = {"ok": False, "optional": True}
    for name in ("ffmpeg", "ffprobe"):
        executable = shutil.which(name)
        ok, output = command_output([executable, "-version"]) if executable else (False, "Not on PATH")
        checks[name] = {"ok": ok, "path": executable, "version": output.splitlines()[0] if output else ""}
    filters, encoders = "", ""
    if checks["ffmpeg"]["ok"]:
        _, filters = command_output([checks["ffmpeg"]["path"], "-hide_banner", "-filters"])
        _, encoders = command_output([checks["ffmpeg"]["path"], "-hide_banner", "-encoders"])
    for name in ("subtitles", "alimiter", "sidechaincompress"):
        checks[name] = {"ok": bool(re.search(r"\b" + name + r"\s+", filters))}
    checks["libx264"] = {"ok": bool(re.search(r"\blibx264\b", encoders))}
    checks["aac"] = {"ok": bool(re.search(r"\baac\b", encoders))}
    if args.model:
        model = args.model.expanduser().resolve()
        missing = [name for name in ("model.bin", "config.json", "tokenizer.json")
                   if not (model / name).is_file()]
        checks["local_asr_model"] = {"ok": not missing, "path": str(model), "missing": missing}
    else:
        checks["local_asr_model"] = {"ok": False, "note": "Supply --model to verify a local directory; no model is bundled."}
    font_match = shutil.which("fc-match")
    if font_match:
        _, family = command_output([font_match, "-f", "%{family}", "Noto Sans CJK SC:lang=zh-cn"])
        checks["cjk_font"] = {"ok": "CJK" in family or "SC" in family, "family": family.strip()}
    else:
        checks["cjk_font"] = {"ok": False, "note": "Verify CJK glyph coverage in rendered frames."}
    base = checks["ffmpeg"]["ok"] and checks["ffprobe"]["ok"]
    capabilities = {
        "render": base and checks["libx264"]["ok"] and checks["aac"]["ok"],
        "inspect": base and checks["Pillow"]["ok"],
        "audio": base and checks["aac"]["ok"] and checks["alimiter"]["ok"] and checks["sidechaincompress"]["ok"],
        "transcribe": base and checks["faster-whisper"]["ok"] and checks["local_asr_model"]["ok"],
    }
    ready = capabilities[args.require]
    print(json.dumps({"status": "ready" if ready else "incomplete", "requested": args.require,
                      "python": sys.executable, "capabilities": capabilities, "checks": checks,
                      "notes": ["Caption burn-in additionally requires subtitles/libass and suitable fonts.",
                                "A present ASR directory is a structural check, not an inference test.",
                                "Voice generation providers and models are not bundled or checked here."]},
                     ensure_ascii=False, indent=2))
    return 0 if ready else 1


if __name__ == "__main__":
    sys.exit(main())
