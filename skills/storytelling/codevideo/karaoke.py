#!/usr/bin/env python3
"""Write karaoke cues and an ASS subtitle file from a word-timed lyric JSON.

The lyric text has to be supplied by the caller. This tool does not fetch songs.
"""
import argparse
import json
from pathlib import Path

from lyrics import LyricError, Lyrics, frame_cue, to_ass


def export(payload, output, width=1920, height=1080, samples=0):
    lyrics = Lyrics(payload)
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise LyricError("output directory is not empty; use a new revision folder")
    ass_path = output / "lyrics.ass"
    ass_path.write_text(to_ass(lyrics, width, height), encoding="utf-8")
    end = lyrics.lines[-1].end
    step = 0 if samples <= 0 else end / samples
    cues = []
    if samples > 0:
        for index in range(samples + 1):
            cues.append(frame_cue(lyrics, min(end, index * step)))
    manifest = {
        "title": lyrics.title,
        "line_count": len(lyrics.lines),
        "word_count": len(lyrics.words),
        "duration": end,
        "ass": "lyrics.ass",
        "lines": [
            {"i": line.i, "text": line.text, "start": line.start, "end": line.end,
             "words": [{"w": word.w, "start": word.start, "end": word.end} for word in line.words]}
            for line in lyrics.lines
        ],
        "cues": cues,
    }
    (output / "cues.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lyrics", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--samples", type=int, default=0, help="optional cue samples from 0 to the last line")
    args = parser.parse_args()
    payload = json.loads(args.lyrics.expanduser().read_text(encoding="utf-8"))
    manifest = export(payload, args.output.expanduser(), args.width, args.height, args.samples)
    print(f"{manifest['line_count']} lines, {manifest['word_count']} words, {args.output}")


if __name__ == "__main__":
    main()
