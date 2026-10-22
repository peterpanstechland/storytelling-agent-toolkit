"""Color-only export must preserve clocks/audio and affect only requested regions."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/storytelling/video/scripts'
sys.path.insert(0, str(SCRIPTS))
import grade


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class GradeTests(unittest.TestCase):
    def test_real_color_revision_preserves_audio_clock_and_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'master.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=0x303030:s=128x96:r=25:d=1',
                            '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1', '-c:v', 'libx264',
                            '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(source)], check=True)
            (root / 'zh.srt').write_text('1\n00:00:00,100 --> 00:00:00,800\n字幕\n')
            plan = dict(version=1, source='master.mp4', subtitles=['zh.srt'],
                        shots=[dict(start=.2, end=.8, region=[32, 24, 64, 48], lift=.2)])
            (root / 'grade.json').write_text(json.dumps(plan))
            report = grade.render(root / 'grade.json', root / 'graded')
            self.assertEqual(report['frames'], 25)
            self.assertEqual(report['audio_hash_before'], report['audio_hash_after'])
            self.assertEqual((root / 'zh.srt').read_bytes(), (root / 'graded/zh.srt').read_bytes())
            def pixels(path, t):
                return grade.command(['ffmpeg', '-v', 'error', '-ss', t, '-i', path, '-frames:v', '1',
                                      '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'], binary=True)
            before = pixels(source, .4)
            after = pixels(root / 'graded/graded.mp4', .4)
            center = (48 * 128 + 64) * 3
            self.assertGreater(after[center] - before[center], 10)
            self.assertLess(abs(after[0] - before[0]), 4)
            untouched = pixels(root / 'graded/graded.mp4', .0)
            self.assertLess(abs(untouched[center] - before[center]), 4)
            with self.assertRaisesRegex(ValueError, 'new output'):
                grade.render(root / 'grade.json', root / 'graded')

    def test_rejects_overlapping_or_out_of_frame_regions(self):
        for shots in ([dict(start=0, end=1, region=[2, 0, 128, 96])],
                      [dict(start=0, end=.8), dict(start=.7, end=1)]):
            with self.assertRaises(ValueError):
                grade.build_filter(shots, 128, 96, 1)


if __name__ == '__main__':
    unittest.main()
