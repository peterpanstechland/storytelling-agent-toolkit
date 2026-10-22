#!/usr/bin/env python3
"""Compare generated speech with its script using hash-bound local ASR results."""
import argparse
import difflib
from pathlib import Path
import re
import sys
import unicodedata

from voice_clone import VoiceError, audio_metrics, digest, number, read_json, save_json


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text).casefold() if c.isalnum())


def distance(a, b):
    previous = list(range(len(b) + 1))
    for i, char in enumerate(a, 1):
        current = [i]
        for j, other in enumerate(b, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j-1] + (char != other)))
        previous = current
    return previous[-1]


def phrase_candidates(expected, words):
    """Keep measured word spans; unmatched script text never gets invented timing."""
    observed, spans = '', []
    for word in words:
        text = normalize(word['word'])
        observed += text
        spans.extend([(word['start'], word['end'])] * len(text))
    target = normalize(expected)
    mapping = [None] * len(target)
    for tag, i, j, k, end in difflib.SequenceMatcher(None, target, observed, autojunk=False).get_opcodes():
        if tag == 'equal':
            mapping[i:j] = spans[k:end]
    result, offset = [], 0
    for part in re.split(r'(?<=[，。！？；：,!?;:])', expected):
        count = len(normalize(part))
        if not count:
            continue
        matched = mapping[offset:offset+count]
        complete = all(x is not None for x in matched)
        result.append(dict(text=part.strip(), start=min(x[0] for x in matched) if complete else None,
                           end=max(x[1] for x in matched) if complete else None,
                           complete_word_coverage=complete, review_required=True))
        offset += count
    return result


def check(manifest_path, transcripts, selected=None, threshold=.18):
    manifest_path, transcripts = Path(manifest_path).resolve(), Path(transcripts).resolve()
    manifest = read_json(manifest_path)
    if manifest.get('operation') != 'clone':
        raise VoiceError('Expected a clone manifest')
    sections = manifest['sections']
    if selected:
        if not set(selected) <= {r['id'] for r in sections}:
            raise VoiceError('Requested section has not been generated')
        sections = [r for r in sections if r['id'] in selected]
    if not sections:
        raise VoiceError('No generated sections to check')
    reports = []
    for row in sections:
        source = (manifest_path.parent / row['source']).resolve()
        sha = digest(source)
        if sha != row['sha256']:
            raise VoiceError('Generated audio changed: ' + row['id'])
        asr = read_json(transcripts / (row['id'] + '.json'))
        if asr.get('source_sha256') != sha or asr.get('status') != 'transcribed':
            raise VoiceError('ASR must be transcribed from this exact audio hash: ' + row['id'])
        metrics = audio_metrics(source)
        actual = ' '.join(s['text'] for s in asr['segments'])
        words = [w for s in asr['segments'] for w in s.get('words', [])]
        last_start = -1
        for word in words:
            start = number(word.get('start'), 'word.start', 0, metrics['duration'] + .05)
            end = number(word.get('end'), 'word.end', 0, metrics['duration'] + .05)
            if end < start or start < last_start or not isinstance(word.get('word'), str):
                raise VoiceError('Invalid or unordered ASR word spans')
            last_start = start
        expected, recognized = normalize(row['text']), normalize(actual)
        cer = distance(expected, recognized) / max(1, len(expected))
        changes = [dict(operation=tag, expected=expected[i:j], recognized=recognized[k:end])
                   for tag, i, j, k, end in difflib.SequenceMatcher(None, expected, recognized, autojunk=False).get_opcodes()
                   if tag != 'equal']
        repeats = [m.group(1) for m in re.finditer(r'(.{5,24})\1\1', recognized)]
        flagged = not words or cer > threshold or bool(repeats) or metrics['clipped_fraction'] >= .001 or metrics['rms'] < .0001
        reports.append(dict(id=row['id'], source_sha256=sha, expected=row['text'], recognized=actual,
                            character_error_rate=cer, differences=changes, repeated_phrases=repeats,
                            acoustic_metrics=metrics, automated_flags=flagged,
                            phrase_candidates=phrase_candidates(row['text'], words),
                            transcript_sha256=digest(transcripts / (row['id'] + '.json'))))
    return dict(version=1, operation='voice-check', sections=reports, cer_threshold=threshold,
                flagged_sections=[r['id'] for r in reports if r['automated_flags']],
                listening_status='pending',
                timing_basis='ASR estimates on actual audio; candidates require editorial review',
                limitations='ASR can misrecognize numbers and names. CER is not a voice-similarity or naturalness score. '
                            'Listen for identity, delivery, pronunciation, missing speech and unintended emotion.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--transcripts', required=True, type=Path, help='one <section-id>.json from transcribe per section')
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--section', action='append')
    parser.add_argument('--cer-threshold', type=float, default=.18)
    args = parser.parse_args()
    try:
        number(args.cer_threshold, 'cer-threshold', 0, 1)
        if args.out.exists():
            raise VoiceError('Choose a new report path')
        report = check(args.manifest, args.transcripts, args.section, args.cer_threshold)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        save_json(args.out, report)
        print('Saved review report: ' + str(args.out))
        return 2 if report['flagged_sections'] else 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print('Voice check failed: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
