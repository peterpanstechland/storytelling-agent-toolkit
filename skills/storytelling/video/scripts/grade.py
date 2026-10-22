#!/usr/bin/env python3
"""Color-only revisions of a zero-origin CFR SDR master; copy audio unchanged."""
import argparse
from fractions import Fraction
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from voice_clone import VoiceError, command, digest, number, read_json, save_json


def probe(path):
    return json.loads(command(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', path]))


def audio_hash(path):
    return command(['ffmpeg', '-v', 'error', '-i', path, '-map', '0:a:0', '-c:a', 'copy',
                    '-f', 'hash', '-hash', 'sha256', '-']).strip()


def frame_clock(path):
    lines = command(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                     '-show_entries', 'frame=best_effort_timestamp_time', '-of', 'csv=p=0', path])
    # H.264 side-data can add empty columns/lines; the first field remains PTS.
    return [float(line.split(',')[0]) for line in lines.splitlines() if line.split(',')[0].strip()]


def build_filter(shots, width, height, duration):
    if not isinstance(shots, list) or not shots:
        raise VoiceError('shots must be a nonempty array')
    graph, previous, last = [], '0:v:0', 0
    normalized = []
    for i, shot in enumerate(shots):
        start = number(shot.get('start'), 'start', 0, duration)
        end = number(shot.get('end'), 'end', 0, duration + .00001)
        if end <= start or start < last:
            raise VoiceError('Grade shots must be ordered and nonoverlapping, with end > start')
        last = end
        region = shot.get('region', [0, 0, width, height])
        if not isinstance(region, list) or len(region) != 4 or any(type(v) is not int or v % 2 for v in region):
            raise VoiceError('region must be four even integers [x, y, width, height] for yuv420p')
        x, y, w, h = region
        if min(x, y) < 0 or min(w, h) < 2 or x+w > width or y+h > height:
            raise VoiceError('region outside frame')
        lift = number(shot.get('lift', .12), 'lift', -.2, .3)
        saturation = number(shot.get('saturation', 1.05), 'saturation', .5, 1.5)
        curve = ' '.join(f'{v/8:.6f}/{v/8+lift*math.sin(math.pi*v/8)*math.exp(-1.1*v/8):.6f}' for v in range(9))
        graph += [f'[{previous}]split=2[base{i}][area{i}]',
                  f"[area{i}]crop={w}:{h}:{x}:{y},curves=all='{curve}',eq=saturation={saturation}[grade{i}]",
                  f"[base{i}][grade{i}]overlay=x={x}:y={y}:enable='gte(t,{start})*lt(t,{end})':eof_action=pass[v{i}]"]
        previous = f'v{i}'
        normalized.append(dict(start=start, end=end, region=region, lift=lift, saturation=saturation))
    return ';'.join(graph), previous, normalized


def render(plan_path, out):
    plan_path, out = Path(plan_path).resolve(), Path(out).absolute()
    plan = read_json(plan_path)
    if type(plan.get('version')) is not int or plan['version'] != 1:
        raise VoiceError('Expected plan version: 1')
    if out.exists():
        raise VoiceError('Choose a new output directory; the baseline is never overwritten')
    source = (plan_path.parent / Path(plan['source']).expanduser()).resolve(strict=True)
    metadata = probe(source)
    videos = [s for s in metadata['streams'] if s['codec_type'] == 'video']
    audios = [s for s in metadata['streams'] if s['codec_type'] == 'audio']
    if len(videos) != 1 or len(audios) > 1:
        raise VoiceError('Use a master with one video stream and at most one audio stream')
    video = videos[0]
    if video.get('color_transfer') in ('smpte2084', 'arib-std-b67') or video.get('color_primaries') == 'bt2020':
        raise VoiceError('Convert HDR to an approved SDR master before this editorial brightness pass')
    if video.get('pix_fmt') != 'yuv420p' or video['width'] % 2 or video['height'] % 2:
        raise VoiceError('Use an 8-bit yuv420p SDR delivery master with even dimensions')
    fps = float(Fraction(video['avg_frame_rate']))
    number(fps, 'fps', 1, 240)
    pts = frame_clock(source)
    if not pts or abs(pts[0]) > .0001 or any(abs((b-a)-1/fps) > .00002 for a, b in zip(pts, pts[1:])):
        raise VoiceError('Use a zero-origin constant-frame-rate master; do not silently change timing')
    for audio in audios:
        if abs(float(audio.get('start_time', 0))) > .001:
            raise VoiceError('Use zero-origin audio before a color-only revision')
    seconds = len(pts) / fps
    graph, label, shots = build_filter(plan.get('shots'), video['width'], video['height'], seconds)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.grade-', dir=out.parent) as tmp:
        temp = Path(tmp)
        movie = temp / 'graded.mp4'
        args = ['ffmpeg', '-v', 'error', '-xerror', '-nostdin', '-y', '-filter_complex_threads', '1',
                '-i', source, '-filter_complex', graph, '-map', f'[{label}]', '-map', '0:a:0?',
                '-c:v', 'libx264', '-crf', '18', '-preset', 'fast', '-threads', '4', '-pix_fmt', 'yuv420p',
                '-c:a', 'copy', '-map_metadata', '0', '-movflags', '+faststart', movie]
        command(args)
        command(['ffmpeg', '-v', 'error', '-xerror', '-i', movie, '-f', 'null', '-'])
        after_pts = frame_clock(movie)
        if len(after_pts) != len(pts) or any(abs(a-b) > .00002 for a, b in zip(pts, after_pts)):
            raise VoiceError('Frame count or timing changed; no deliverable promoted')
        before_audio = audio_hash(source) if audios else None
        after_audio = audio_hash(movie) if audios else None
        if before_audio != after_audio:
            raise VoiceError('Audio packet hash changed; no deliverable promoted')
        report = dict(version=1, operation='grade', source=str(source), source_sha256=digest(source),
                      output_sha256=digest(movie), frames=len(pts), fps=fps, duration=seconds, shots=shots,
                      audio_hash_before=before_audio, audio_hash_after=after_audio,
                      checks=['full decode', 'all frame timestamps', 'encoded audio packet hash'],
                      limitations='A creative SDR brightness pass, not a camera Log/technical LUT transform. '
                                  'Outside regions bypass grading but video compression can change their pixels. '
                                  'Check skin tones, highlights and before/after frames visually.')
        save_json(temp / 'manifest.json', report)
        for subtitle in plan.get('subtitles', []):
            path = (plan_path.parent / subtitle).resolve(strict=True)
            if path.suffix.lower() not in ('.srt', '.ass', '.vtt') or (temp / path.name).exists():
                raise VoiceError('Sidecar subtitles need unique .srt/.ass/.vtt names')
            shutil.copy2(path, temp / path.name)
        # Atomic promotion only after all media checks pass.
        temp.rename(out)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan', type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    try:
        report = render(args.plan, args.out)
        print(json.dumps(dict(output=str(args.out / 'graded.mp4'), frames=report['frames'], duration=report['duration'])))
        return 0
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as exc:
        print('Color revision failed: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
