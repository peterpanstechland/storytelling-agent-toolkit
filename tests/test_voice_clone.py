"""Real FFmpeg audio with a fake synthesizer; no personal voice/model or network."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/storytelling/video/scripts'
sys.path.insert(0, str(SCRIPTS))
import voice_clone as vc
import voice_check as qc


def tone(path, hz=440, duration=.4):
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                    f'sine=frequency={hz}:sample_rate=24000:duration={duration}',
                    '-c:a', 'pcm_s16le', str(path)], check=True)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class VoiceCloneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='voice-adapter-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        model = self.root / 'model'
        for name in vc.MODEL_FILES:
            path = model / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('local fixture, not a model')
        repo = self.root / 'engine/indextts'
        repo.mkdir(parents=True)
        (repo / 'infer_v2_5.py').write_text('# fake engine; never imported\n')
        tone(self.root / 'speaker.wav', duration=2)
        self.raw = dict(version=1, engine='index-tts-2.5',
                        authorization=dict(speaker='synthetic fixture', statement='Generated test tone, no person'),
                        runtime=dict(repository='engine', model_dir='model', device='cpu', threads=1),
                        reference=dict(source='speaker.wav', **{'in': .1, 'out': 1.4}), gap=.2,
                        sections=[dict(id='a', text='你好，世界。'), dict(id='b', text='第二句。', mood='warm')])
        self.path = self.root / 'plan.json'
        self.output = self.root / 'generated'
        self.calls = []
        calls = self.calls

        class Fake:
            def generate(self, row, reference, output):
                calls.append(row['id'])
                tone(output, hz=440 if row['id'] == 'a' else 880)
                return row['emotion_vector']
        self.factory = lambda plan: Fake()

    def plan(self):
        self.path.write_text(json.dumps(self.raw, ensure_ascii=False))
        return vc.load_plan(self.path)

    def run_clone(self, selected=None, resume=False, factory=None):
        return vc.synthesize(self.plan(), self.output, selected, resume, factory or self.factory)

    def test_sample_resume_and_real_narration_handoff(self):
        report = self.run_clone(['a'])
        self.assertEqual(report['status'], 'partial')
        self.assertFalse((self.output / 'narration-plan.json').exists())
        self.run_clone(resume=True)
        self.assertEqual(self.calls, ['a', 'b'])
        def must_not_load(plan):
            self.fail('Cached run must not load a model')
        self.run_clone(resume=True, factory=must_not_load)
        plan = vc.read_json(self.output / 'narration-plan.json')
        self.assertAlmostEqual(plan['duration'], 1.0)
        self.assertAlmostEqual(plan['segments'][1]['start'], .6)
        result = subprocess.run([sys.executable, str(SCRIPTS / 'narration.py'), 'narrate',
                                 str(self.output / 'narration-plan.json'), '--out', str(self.root / 'assembled')],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertAlmostEqual(vc.audio_metrics(self.root / 'assembled/narration.wav')['duration'], 1.0)

    def test_edits_invalidate_only_affected_sections_and_revoke_stale_handoff(self):
        self.run_clone()
        self.raw['sections'][1]['text'] = '更新的第二句。'
        report = self.run_clone(['a'], True)
        self.assertEqual(report['missing'], ['b'])
        self.assertFalse((self.output / 'narration-plan.json').exists())
        self.run_clone(resume=True)
        self.assertEqual(self.calls, ['a', 'b', 'b'])

    def test_reference_model_and_output_changes_invalidate_cache(self):
        self.run_clone()
        tone(self.root / 'speaker.wav', hz=550, duration=2)
        self.run_clone(resume=True)
        self.assertEqual(len(self.calls), 4)
        (self.root / 'model/gpt.pth').write_text('changed weights')
        self.run_clone(resume=True)
        self.assertEqual(len(self.calls), 6)
        (self.output / 'segments/a.wav').write_bytes(b'corrupt')
        self.run_clone(resume=True)
        self.assertEqual(self.calls[-1], 'a')
        self.assertEqual(len(self.calls), 7)

    def test_failure_keeps_completed_sections_and_cleans_partial(self):
        class Failing:
            def generate(self, row, reference, output):
                if row['id'] == 'b':
                    output.write_bytes(b'partial')
                    raise RuntimeError('inference failure')
                tone(output)
                return row['emotion_vector']
        with self.assertRaisesRegex(RuntimeError, 'inference failure'):
            self.run_clone(factory=lambda plan: Failing())
        report = vc.read_json(self.output / 'manifest.json')
        self.assertEqual(report['status'], 'failed')
        self.assertEqual([r['id'] for r in report['sections']], ['a'])
        self.assertFalse((self.output / 'segments/b.partial.wav').exists())
        self.assertFalse((self.output / 'narration-plan.json').exists())
        self.run_clone(resume=True)
        self.assertEqual(self.calls, ['b'])

    def test_existing_directory_and_active_lock_are_protected(self):
        self.run_clone()
        with self.assertRaisesRegex(vc.VoiceError, 'new/empty'):
            self.run_clone()
        lock = self.output / '.clone.lock'
        lock.write_text('test writer\n')
        with self.assertRaisesRegex(vc.VoiceError, 'locked'):
            self.run_clone(resume=True)
        self.assertEqual(lock.read_text(), 'test writer\n')

    def test_bounds_ids_authorization_and_nonfinite_values(self):
        cases = [lambda p: p['sections'][0].update(id='../escape'),
                 lambda p: p['sections'][0].update(duration_factor=float('nan')),
                 lambda p: p['sections'][0].update(seed=True),
                 lambda p: p['sections'][0].update(emotion_vector=[0] * 7),
                 lambda p: p.update(authorization={}),
                 lambda p: p['reference'].update(out=.2)]
        original = json.dumps(self.raw)
        for change in cases:
            with self.subTest(change=change):
                self.raw = json.loads(original)
                change(self.raw)
                with self.assertRaises(vc.VoiceError):
                    self.plan()

    def test_missing_weights_and_reference_overrun_fail_before_inference(self):
        (self.root / 'model/codec.pth').unlink()
        with self.assertRaisesRegex(vc.VoiceError, 'missing'):
            self.run_clone()
        self.assertEqual(self.calls, [])
        (self.root / 'model/codec.pth').write_text('fixture')
        self.raw['reference']['out'] = 5
        with self.assertRaisesRegex(vc.VoiceError, 'beyond'):
            self.run_clone()

    def test_voice_check_binds_exact_audio_and_flags_missing_words(self):
        self.run_clone(['a'])
        transcript_dir = self.root / 'transcripts'
        transcript_dir.mkdir()
        source = self.output / 'segments/a.wav'
        asr = dict(status='transcribed', source_sha256=vc.digest(source), segments=[
            dict(text='你好世界', words=[dict(start=0, end=.2, word='你好'), dict(start=.2, end=.4, word='世界')])])
        (transcript_dir / 'a.json').write_text(json.dumps(asr))
        result = qc.check(self.output / 'manifest.json', transcript_dir)
        self.assertEqual(result['flagged_sections'], [])
        self.assertEqual(result['listening_status'], 'pending')
        self.assertEqual(result['sections'][0]['character_error_rate'], 0)
        asr['segments'][0]['text'] = '错误内容'
        (transcript_dir / 'a.json').write_text(json.dumps(asr))
        self.assertEqual(qc.check(self.output / 'manifest.json', transcript_dir)['flagged_sections'], ['a'])
        asr['source_sha256'] = 'stale'
        (transcript_dir / 'a.json').write_text(json.dumps(asr))
        with self.assertRaisesRegex(vc.VoiceError, 'exact audio hash'):
            qc.check(self.output / 'manifest.json', transcript_dir)

    def test_unmatched_script_does_not_get_invented_timestamps(self):
        candidates = qc.phrase_candidates('你好。另一个句子。', [dict(word='你好', start=.2, end=.7)])
        self.assertEqual(candidates[0]['start'], .2)
        self.assertIsNone(candidates[1]['start'])
        self.assertIsNone(candidates[1]['end'])
        self.assertTrue(candidates[0]['review_required'])


if __name__ == '__main__':
    unittest.main()
