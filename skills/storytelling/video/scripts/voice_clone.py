#!/usr/bin/env python3
"""Local IndexTTS-2.5 adapter. No engine, model, voice or download is bundled."""
from __future__ import annotations

import argparse
import array
from contextlib import contextmanager
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import time

ORDER = ['happy', 'angry', 'sad', 'afraid', 'disgusted', 'melancholic', 'surprised', 'calm']
MOODS = {
    'curious': [.16, 0, 0, 0, 0, 0, .07, .18],
    'clear': [.07, 0, 0, 0, 0, 0, .02, .27],
    'engaged': [.22, 0, 0, 0, 0, 0, .05, .14],
    'warm': [.12, 0, 0, 0, 0, 0, 0, .28],
}
# Layout of the upstream 2.5 runtime exercised in production. Pre-stage ancillary
# models too: upstream may otherwise try to download them at construction time.
MODEL_FILES = (
    'config.yaml', 'gpt.pth', 'codec.pth', 's2mel.pth', 'feat1.pt', 'feat2.pt',
    'wav2vec2bert_stats.pt', 'multilingual_zh_ja_yue_char_del.tiktoken',
    'hf_cache/w2v-bert-2.0/config.json', 'hf_cache/w2v-bert-2.0/preprocessor_config.json',
    'hf_cache/w2v-bert-2.0/model.safetensors', 'hf_cache/bigvgan/config.json',
    'hf_cache/bigvgan/bigvgan_generator.pt', 'hf_cache/campplus_cn_common.bin',
)
GENERATION = dict(emo_alpha=1.0, use_random=False, interval_silence=130,
                  max_text_tokens_per_segment=160, do_sample=True, top_p=.80,
                  top_k=30, temperature=.68, num_beams=1,
                  repetition_penalty=10.0, max_mel_tokens=1100, verbose=False)


class VoiceError(ValueError):
    pass


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def signature(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     allow_nan=False).encode()).hexdigest()


def save_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    temporary.replace(path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'),
                      parse_constant=lambda x: (_ for _ in ()).throw(VoiceError('Non-finite JSON: ' + x)))


def number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise VoiceError(f'{name} must be a finite number in [{low}, {high}]')
    return value


def string(value, name):
    if not isinstance(value, str) or not value.strip():
        raise VoiceError(name + ' must be nonempty text')
    return value


def object_value(value, name):
    if not isinstance(value, dict):
        raise VoiceError(name + ' must be an object')
    return value


def local_path(base, value, name, directory=False):
    path = (base / Path(string(value, name)).expanduser()).resolve()
    if not (path.is_dir() if directory else path.is_file()):
        raise VoiceError(f'{name} does not exist: {path}')
    return path


def command(args, binary=False):
    result = subprocess.run([str(x) for x in args], capture_output=True, check=False)
    if result.returncode:
        raise VoiceError(result.stderr.decode(errors='replace')[-4000:])
    return result.stdout if binary else result.stdout.decode()


def audio_metrics(path):
    data = json.loads(command(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', path]))
    streams = [s for s in data['streams'] if s['codec_type'] == 'audio']
    if len(streams) != 1:
        raise VoiceError('Expected exactly one audio stream: ' + str(path))
    # Fully decode to catch corrupt/truncated output, measuring all samples.
    raw = command(['ffmpeg', '-v', 'error', '-xerror', '-i', path, '-map', '0:a:0',
                   '-ac', '1', '-ar', '24000', '-f', 's16le', '-'], binary=True)
    values = array.array('h', raw)
    if sys.byteorder != 'little':
        values.byteswap()
    if not values:
        raise VoiceError('Empty audio: ' + str(path))
    rms = math.sqrt(sum(v * v for v in values) / len(values)) / 32768
    return dict(duration=len(values) / 24000, sample_rate=int(streams[0]['sample_rate']),
                channels=streams[0]['channels'], peak=max(abs(v) for v in values) / 32768,
                rms=rms, clipped_fraction=sum(abs(v) >= 32760 for v in values) / len(values))


def load_plan(path):
    path = Path(path).resolve()
    data = object_value(read_json(path), 'plan')
    if type(data.get('version')) is not int or data['version'] != 1 or data.get('engine') != 'index-tts-2.5':
        raise VoiceError('Expected version: 1 and engine: index-tts-2.5')
    authorization = object_value(data.get('authorization'), 'authorization')
    for key in ('speaker', 'statement'):
        value = string(authorization.get(key), 'authorization.' + key)
        if value.startswith('REPLACE_WITH_'):
            raise VoiceError('Record actual speaker authorization before synthesis')
    runtime = object_value(data.get('runtime'), 'runtime').copy()
    runtime['repository'] = str(local_path(path.parent, runtime.get('repository'), 'runtime.repository', True))
    runtime['model_dir'] = str(local_path(path.parent, runtime.get('model_dir'), 'runtime.model_dir', True))
    runtime.setdefault('device', 'cpu')
    if runtime['device'] not in ('cpu', 'cuda'):
        raise VoiceError('runtime.device must be cpu or cuda; no silent device fallback')
    runtime['threads'] = number(runtime.get('threads', 4), 'threads', 1, 128)
    if type(runtime['threads']) is not int:
        raise VoiceError('threads must be an integer')
    reference = object_value(data.get('reference'), 'reference').copy()
    reference['source'] = str(local_path(path.parent, reference.get('source'), 'reference.source'))
    reference['in'] = number(reference.get('in', 0), 'reference.in', 0, 86400)
    reference['out'] = number(reference.get('out'), 'reference.out', 0, 86400)
    if not 1 <= reference['out'] - reference['in'] <= 60:
        raise VoiceError('Use a contiguous reference excerpt between 1 and 60 seconds')
    sections = data.get('sections')
    if not isinstance(sections, list) or not sections:
        raise VoiceError('sections must be a nonempty array')
    normalized, seen = [], set()
    for row in sections:
        row = object_value(row, 'section').copy()
        sid = row.get('id')
        if not isinstance(sid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', sid) or sid in seen:
            raise VoiceError('Section ids must be unique, safe ASCII names')
        seen.add(sid)
        string(row.get('text'), sid + '.text')
        mood = row.get('mood', 'clear')
        if mood not in MOODS:
            raise VoiceError('Unknown mood: ' + str(mood))
        vector = row.get('emotion_vector', MOODS[mood])
        if not isinstance(vector, list) or len(vector) != 8:
            raise VoiceError('emotion_vector needs exactly eight values in the documented order')
        for value in vector:
            number(value, 'emotion_vector', 0, 1)
        seed = row.get('seed', 1014 + len(normalized))
        if type(seed) is not int or not 0 <= seed < 2 ** 32:
            raise VoiceError('seed must be an integer in [0, 2**32)')
        language = row.get('language', 'zhen')
        if language not in ('zhen', 'ja', 'es', 'ar'):
            raise VoiceError('Supported language codes: zhen, ja, es, ar')
        normalized.append(dict(id=sid, text=row['text'], en=row.get('en', ''), seed=seed,
                               mood=mood, emotion_vector=vector, language=language,
                               duration_factor=number(row.get('duration_factor', .95), 'duration_factor', .5, 2),
                               max_duration=number(row.get('max_duration', 90), 'max_duration', 1, 600)))
        if not isinstance(normalized[-1]['en'], str):
            raise VoiceError('en must be text')
    return dict(version=1, engine=data['engine'], authorization=authorization,
                runtime=runtime, reference=reference, sections=normalized,
                gap=number(data.get('gap', .18), 'gap', 0, 10))


def preflight(plan):
    runtime = plan['runtime']
    repo, model = Path(runtime['repository']), Path(runtime['model_dir'])
    missing = [name for name in MODEL_FILES if not (model / name).is_file()]
    if not (repo / 'indextts/infer_v2_5.py').is_file():
        missing.append('repository/indextts/infer_v2_5.py')
    if missing:
        raise VoiceError('Pre-stage the local IndexTTS-2.5 runtime; missing: ' + ', '.join(missing))
    metrics = audio_metrics(plan['reference']['source'])
    if plan['reference']['out'] > metrics['duration'] + 1 / 24000:
        raise VoiceError('Reference excerpt extends beyond the actual recording')
    return metrics


def provenance(plan):
    runtime = plan['runtime']
    repo, model = Path(runtime['repository']), Path(runtime['model_dir'])
    # Hash weights rather than mtimes: replacing a model must invalidate cached speech.
    files = {name: digest(model / name) for name in MODEL_FILES}
    code = {str(p.relative_to(repo)): digest(p) for p in sorted((repo / 'indextts').rglob('*.py'))}
    versions = {}
    for name in ('torch', 'numpy', 'transformers', 'torchaudio', 'tokenizers', 'safetensors'):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    try:
        revision = command(['git', '-C', repo, 'rev-parse', 'HEAD']).strip()
    except (OSError, VoiceError):
        revision = 'unversioned-local-source'
    return dict(adapter_sha256=digest(__file__), model_files=files, engine_code=code,
                engine_revision=revision, packages=versions, runtime=runtime,
                reference_sha256=digest(plan['reference']['source']), reference=plan['reference'],
                generation=GENERATION, authorization=plan['authorization'])


def prepare_reference(plan, output):
    ref = plan['reference']
    length = ref['out'] - ref['in']
    command(['ffmpeg', '-v', 'error', '-y', '-i', ref['source'], '-ss', ref['in'], '-t', length,
             '-map', '0:a:0', '-ac', '1', '-ar', '24000', '-c:a', 'pcm_s16le',
             '-af', f'highpass=f=65,afade=t=in:d=0.012,afade=t=out:st={length-.02}:d=0.02', output])
    metrics = audio_metrics(output)
    if abs(metrics['duration'] - length) > .05 or metrics['rms'] < .0001:
        raise VoiceError('Reference is truncated or effectively silent; choose a voiced excerpt')
    return metrics


class IndexBackend:
    def __init__(self, plan):
        runtime = plan['runtime']
        for key in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
            os.environ[key] = str(runtime['threads'])
        os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                          HF_HUB_DISABLE_TELEMETRY='1', TOKENIZERS_PARALLELISM='false')
        sys.path.insert(0, runtime['repository'])
        import numpy as np
        import torch
        self.np, self.torch = np, torch
        torch.set_num_threads(runtime['threads'])
        if runtime['device'] == 'cuda' and not torch.cuda.is_available():
            raise VoiceError('CUDA requested but unavailable in this interpreter')
        from indextts.infer_v2_5 import IndexTTS2
        self.repo = runtime['repository']
        with in_directory(self.repo):
            self.model = IndexTTS2(cfg_path=str(Path(runtime['model_dir']) / 'config.yaml'),
                                   model_dir=runtime['model_dir'], device=runtime['device'],
                                   use_bf16=False, use_cuda_kernel=False, use_deepspeed=False,
                                   use_accel=False, use_torch_compile=False, use_qwen_emo=False)

    def generate(self, row, reference, output):
        random.seed(row['seed'])
        self.np.random.seed(row['seed'])
        self.torch.manual_seed(row['seed'])
        if self.torch.cuda.is_available():
            self.torch.cuda.manual_seed_all(row['seed'])
        vector = self.model.normalize_emo_vec(row['emotion_vector'], apply_bias=True)
        with in_directory(self.repo):
            self.model.infer(spk_audio_prompt=str(reference), text=row['text'], output_path=str(output),
                             lang=row['language'], emo_vector=vector,
                             duration_factor=row['duration_factor'], **GENERATION)
        return list(vector)


@contextmanager
def in_directory(path):
    previous = Path.cwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(previous)


def synthesize(plan, output, selected=None, resume=False, backend_factory=IndexBackend):
    if Path(output).is_symlink():
        raise VoiceError('Output must not be a symlink')
    output = Path(output).resolve()
    selected = set(selected or [row['id'] for row in plan['sections']])
    if not selected <= {r['id'] for r in plan['sections']}:
        raise VoiceError('Unknown --section id')
    preflight(plan)
    output.mkdir(parents=True, exist_ok=True)
    if output.is_symlink() or any(p.is_symlink() for p in output.rglob('*')):
        raise VoiceError('Output must not contain symlinks')
    manifest_path = output / 'manifest.json'
    if any(output.iterdir()) and not (resume and manifest_path.is_file()):
        raise VoiceError('Use a new/empty output directory, or --resume an existing clone manifest')
    try:
        lock = (output / '.clone.lock').open('x')
    except FileExistsError as exc:
        raise VoiceError('Output is locked; verify its recorded PID before removing a stale .clone.lock') from exc
    try:
        lock.write(str(os.getpid()) + '\n')
        lock.close()
        old = read_json(manifest_path) if resume and manifest_path.exists() else {}
        if old and (old.get('operation') != 'clone' or old.get('version') != 1):
            raise VoiceError('Not a supported clone manifest')
        print('Hashing local model, engine and reference inputs…', flush=True)
        inputs = provenance(plan)
        keys = {r['id']: signature(dict(inputs=inputs, section=r)) for r in plan['sections']}
        valid = {}
        for row in plan['sections']:
            sid = row['id']
            prior = next((x for x in old.get('sections', []) if x['id'] == sid), None)
            path = output / 'segments' / (sid + '.wav')
            if prior and prior.get('signature') == keys[sid] and path.is_file() and digest(path) == prior.get('sha256'):
                valid[sid] = prior
        (output / 'narration-plan.json').unlink(missing_ok=True)
        manifest = dict(version=1, operation='clone', engine=plan['engine'], inputs=inputs,
                        emotion_order=ORDER, status='generating', sections=list(valid.values()),
                        review_status='awaiting-asr-and-listening')
        save_json(manifest_path, manifest)
        (output / 'segments').mkdir(exist_ok=True)
        reference = output / 'reference.wav'
        manifest['prepared_reference'] = prepare_reference(plan, reference)
        manifest['prepared_reference']['sha256'] = digest(reference)
        engine = None
        for row in plan['sections']:
            sid = row['id']
            if sid not in selected or sid in valid:
                continue
            if engine is None:
                engine = backend_factory(plan)
            temporary = output / 'segments' / (sid + '.partial.wav')
            temporary.unlink(missing_ok=True)
            started = time.monotonic()
            print('Generating ' + sid, flush=True)
            try:
                applied_vector = engine.generate(row, reference, temporary)
                metrics = audio_metrics(temporary)
                if not .1 <= metrics['duration'] <= row['max_duration'] or metrics['rms'] < .0001:
                    raise VoiceError('Empty, silent or overlong generated speech: ' + sid)
                final = output / 'segments' / (sid + '.wav')
                temporary.replace(final)
            finally:
                temporary.unlink(missing_ok=True)
            valid[sid] = dict(row, source='segments/' + sid + '.wav', signature=keys[sid],
                              sha256=digest(final), applied_emotion_vector=applied_vector,
                              generation_seconds=time.monotonic() - started, **metrics)
            manifest['sections'] = [valid[r['id']] for r in plan['sections'] if r['id'] in valid]
            save_json(manifest_path, manifest)
        missing = [r['id'] for r in plan['sections'] if r['id'] not in valid]
        manifest.update(status='partial' if missing else 'generated-awaiting-review', missing=missing)
        if not missing:
            clock, segments = 0.0, []
            for row in plan['sections']:
                result = valid[row['id']]
                segments.append(dict(id=row['id'], source=result['source'], start=round(clock, 6),
                                     text=row['text'], en=row['en']))
                clock += result['duration'] + plan['gap']
            save_json(output / 'narration-plan.json', dict(version=1, duration=round(clock-plan['gap'], 6),
                      backend=dict(engine=plan['engine'], provenance_file='manifest.json'), segments=segments))
        save_json(manifest_path, manifest)
        return manifest
    except BaseException as exc:
        if 'manifest' in locals():
            manifest.update(status='interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed', error=str(exc))
            save_json(manifest_path, manifest)
        raise
    finally:
        (output / '.clone.lock').unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan', type=Path)
    parser.add_argument('--out', type=Path, help='private working directory; never commit its contents')
    parser.add_argument('--section', action='append', help='sample/regenerate selected paragraph(s) by id')
    parser.add_argument('--resume', action='store_true', help='reuse only matching verified output hashes')
    parser.add_argument('--check', action='store_true', help='check local files/reference; no inference or downloads')
    args = parser.parse_args()
    try:
        plan = load_plan(args.plan)
        if args.check:
            print(json.dumps(dict(status='local-files-ready', reference=preflight(plan),
                                 note='Does not load the engine or prove inference compatibility.'), indent=2))
        else:
            if not args.out:
                parser.error('--out is required unless --check is used')
            result = synthesize(plan, args.out, args.section, args.resume)
            print(json.dumps(dict(status=result['status'], missing=result['missing'])))
        return 0
    except (VoiceError, OSError, ImportError, RuntimeError, KeyError, TypeError) as exc:
        print('Voice clone failed: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
