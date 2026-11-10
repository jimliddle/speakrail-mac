"""Exercise patch installation without downloading dependencies or loading models."""
import subprocess
import tempfile
from pathlib import Path
import unittest

from patch_audio import apply_patch

PATCH = '''diff --git a/source.cpp b/source.cpp
--- a/source.cpp
+++ b/source.cpp
@@ -1 +1 @@
-original
+guarded
diff --git a/guard.h b/guard.h
new file mode 100644
--- /dev/null
+++ b/guard.h
@@ -0,0 +1 @@
+boundary
'''


class PatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'source'
        self.repo.mkdir()
        self.git('init', '-q')
        (self.repo / 'source.cpp').write_text('original\n')
        (self.repo / 'other.cpp').write_text('untouched\n')
        self.git('add', '.')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                 '-c', 'commit.gpgsign=false', 'commit', '-qm', 'Fixture')
        self.revision = self.git('rev-parse', 'HEAD').decode().strip()
        self.patch = self.root / 'boundary.patch'
        self.patch.write_text(PATCH)

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args])

    def apply(self, **kwargs):
        return apply_patch(self.repo, self.revision, self.patch, **kwargs)

    def test_fresh_check_apply_repeat(self):
        self.assertEqual(self.apply(check_only=True), 'patch applicable')
        self.assertFalse((self.repo / 'guard.h').exists())
        self.assertEqual(self.apply(), 'patched')
        self.assertEqual((self.repo / 'source.cpp').read_text(), 'guarded\n')
        self.assertEqual(self.apply(), 'already patched')
        self.assertEqual(self.git('diff', '--cached', '--name-only'), b'')

    def test_unrelated_tracked_edits_rejected(self):
        (self.repo / 'other.cpp').write_text('personal edit\n')
        with self.assertRaisesRegex(RuntimeError, 'unrelated'):
            self.apply()
        self.assertEqual((self.repo / 'other.cpp').read_text(), 'personal edit\n')

    def test_new_file_collision_rejected(self):
        (self.repo / 'guard.h').write_text('personal header\n')
        with self.assertRaisesRegex(RuntimeError, 'unrecognized'):
            self.apply()

    def test_tampered_patch_rejected(self):
        self.apply()
        (self.repo / 'source.cpp').write_text('disabled guard\n')
        with self.assertRaisesRegex(RuntimeError, 'unrecognized'):
            self.apply()

    def test_staged_changes_rejected(self):
        (self.repo / 'other.cpp').write_text('staged\n')
        self.git('add', 'other.cpp')
        with self.assertRaisesRegex(RuntimeError, 'staged'):
            self.apply()

    def test_wrong_pin_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'pinned'):
            apply_patch(self.repo, '0' * 40, self.patch)

    def test_symlink_rejected(self):
        target = self.root / 'private'
        target.write_text('boundary\n')
        (self.repo / 'guard.h').symlink_to(target)
        with self.assertRaisesRegex(RuntimeError, 'symlink'):
            self.apply()


if __name__ == '__main__':
    unittest.main()
