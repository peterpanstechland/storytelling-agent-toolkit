#!/usr/bin/env python3
"""Local speech recognition adapter. No network/model download unless --download."""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--model', default='small')
    p.add_argument('--language', default=None, help='e.g. zh or en; omitted = detect')
    p.add_argument('--cache-dir', type=Path, default=Path('work/models'))
    p.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    p.add_argument('--compute-type', default='int8')
    p.add_argument('--terms', default='', help='Vocabulary spellings, not an invented transcript')
    p.add_argument('--download', action='store_true')
    args = p.parse_args()
    source = args.source.expanduser().resolve(strict=True)
    if not source.is_file():
        raise ValueError('Source must be a local file')
    hasher = hashlib.sha256()
    with source.open('rb') as audio:
        for block in iter(lambda: audio.read(8 * 1024 * 1024), b''):
            hasher.update(block)
    source_sha256 = hasher.hexdigest()
    stat = source.stat()
    signature = hashlib.sha256(json.dumps({
        'source': str(source), 'source_sha256': source_sha256, 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns,
        'model': args.model, 'language': args.language, 'terms': args.terms,
        'device': args.device, 'compute_type': args.compute_type,
    }, sort_keys=True).encode()).hexdigest()
    if args.out.exists():
        old = json.loads(args.out.read_text(encoding='utf-8'))
        if old.get('signature') == signature:
            print(json.dumps({'cached': True, 'transcript': str(args.out.resolve())}))
            return
        raise ValueError('Output exists with different input/settings; use a new file')
    probe = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(source)],
                           check=True, capture_output=True, text=True)
    streams = json.loads(probe.stdout).get('streams', [])
    if not any(x.get('codec_type') == 'audio' for x in streams):
        result = {'source': str(source), 'signature': signature, 'status': 'no_audio', 'segments': []}
    else:
        if importlib.util.find_spec('faster_whisper') is None:
            raise RuntimeError('faster-whisper is not installed in this Python environment. Install requirements-asr.txt in your chosen environment; no speech has been transcribed.')
        from faster_whisper import WhisperModel
        model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type,
                             download_root=str(args.cache_dir.resolve()), local_files_only=not args.download)
        segments, info = model.transcribe(str(source), language=args.language, beam_size=5,
                                         vad_filter=True, word_timestamps=True,
                                         initial_prompt=args.terms or None)
        rows = []
        for s in segments:
            if not (math.isfinite(s.start) and math.isfinite(s.end) and s.end > s.start):
                continue
            rows.append({'start': s.start, 'end': s.end, 'text': s.text.strip(),
                         'avg_logprob': s.avg_logprob, 'no_speech_prob': s.no_speech_prob,
                         'words': [{'start': w.start, 'end': w.end, 'word': w.word,
                                    'probability': w.probability} for w in (s.words or [])]})
        result = {'source': str(source), 'signature': signature, 'status': 'transcribed',
                  'model': args.model, 'language': info.language,
                  'language_probability': info.language_probability, 'segments': rows,
                  'review_note': 'Machine transcript; verify technical terms, numbers and speech presence.'}
    result['source_sha256'] = source_sha256
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps({'transcript': str(args.out.resolve()), 'status': result['status'],
                      'segments': len(result['segments'])}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
