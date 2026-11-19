"""Working-space checks on made-up Finder backups, with a stand-in for iLEAPP's executable."""
import io
import plistlib
import sys
import tempfile
import textwrap
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ileapp
import iphone_backup


class IleappSpaceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.base = self.root / 'app-data'
        self.mirror = self.root / 'mirror/files'
        phone_file = self.mirror / 'HomeDomain/Library/Notes/notes.db'
        phone_file.parent.mkdir(parents=True)
        phone_file.write_bytes(b'made-up notes database')
        self.python = self.root / 'fake-ileapp'
        self.python.write_text(textwrap.dedent(f'''\
            #!{sys.executable}
            import sys
            from pathlib import Path
            args = sys.argv[1:]
            run = Path(args[args.index('-o') + 1]) / args[args.index('--custom_output_folder') + 1]
            run.mkdir(parents=True, exist_ok=True)
            (run / '_lava_artifacts.db').write_bytes(b'fake database')
            (run / '_lava_data.lava').write_text('{{}}')
            print('Processes completed.')
            '''))
        self.python.chmod(0o755)
        self.backup = self.make_backup('small', 1024)
        for name, value in [('BASE', self.base), ('OUT', self.base / 'ileapp'), ('IPHONE', self.mirror), ('VENV_PY', self.python)]:
            p = patch.object(ileapp, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(ileapp, 'write_profile', return_value=1)
        p.start()
        self.addCleanup(p.stop)

    def make_backup(self, name, size):
        folder = self.root / 'backups' / name
        folder.mkdir(parents=True)
        (folder / 'Info.plist').write_bytes(plistlib.dumps({'Device Name': 'Fixture iPhone', 'Product Type': 'iPhone99,1'}))
        (folder / 'Manifest.db').write_bytes(b'fake index')
        (folder / 'ab').mkdir()
        with (folder / 'ab/payload').open('wb') as f:
            f.truncate(size)  # sparse: a large logical backup without using a large disk
        return iphone_backup.Backup(folder)

    def run_with_space(self, backup, free, force=False):
        with patch.object(ileapp.shutil, 'disk_usage', return_value=types.SimpleNamespace(free=free)), redirect_stdout(io.StringIO()):
            return ileapp.run(backup, force=force)

    def test_small_backup_runs_with_less_than_fifteen_gb_free(self):
        latest = self.run_with_space(self.backup, 3_000_000_000)
        self.assertEqual((latest / '_lava_artifacts.db').read_bytes(), b'fake database')
        self.assertTrue((latest / 'run.json').is_file())
        self.assertFalse((self.mirror.parent / 'ileapp_view').exists())

    def test_selected_large_backup_reports_its_space_before_touching_old_results(self):
        large = self.make_backup('large', 4_000_000_000)
        old = ileapp.OUT / large.dir.name / 'latest/previous'
        old.parent.mkdir(parents=True)
        old.write_text('previous results')
        work = old.parent.parent / 'run/unfinished'
        work.parent.mkdir()
        work.write_text('previous work')
        with patch.object(ileapp, 'VENV_PY', self.root / 'not-installed'), patch.object(ileapp, 'install') as install:
            with self.assertRaises(SystemExit) as stopped:
                self.run_with_space(large, 2_000_000_000)
            install.assert_not_called()
        message = str(stopped.exception)
        self.assertIn('only 2.0 GB free', message)
        self.assertIn('needs about 5.0 GB free', message)
        self.assertIn("three quarters of the backup's size plus 2 GB", message)
        self.assertEqual(old.read_text(), 'previous results')
        self.assertEqual(work.read_text(), 'previous work')

    def test_exact_estimate_fits_and_force_can_bypass_a_shortage(self):
        size = sum(p.stat().st_size for p in self.backup.dir.rglob('*') if p.is_file())
        need = size * 3 // 4 + 2_000_000_000
        self.assertEqual(ileapp.working_space(self.backup.dir), need)
        self.assertTrue(self.run_with_space(self.backup, need).is_dir())
        with self.assertRaises(SystemExit):
            self.run_with_space(self.backup, need - 1)
        self.assertTrue(self.run_with_space(self.backup, need - 1, force=True).is_dir())

    def test_unreadable_backup_size_is_not_treated_as_an_empty_backup(self):
        scandir = ileapp.os.scandir

        def blocked(folder):
            if isinstance(folder, (str, Path)) and Path(folder) == self.backup.dir / 'ab':
                raise PermissionError('fixture backup is unreadable')
            return scandir(folder)

        with patch.object(ileapp.os, 'scandir', side_effect=blocked):
            with self.assertRaisesRegex(SystemExit, "couldn't measure this backup's size.*fixture backup is unreadable"):
                self.run_with_space(self.backup, 2_000_000_000)
        self.assertFalse(ileapp.OUT.exists())

    def test_a_child_directory_link_does_not_count_another_backup(self):
        before = ileapp.working_space(self.backup.dir)
        other = self.make_backup('other', 4_000_000_000)
        (self.backup.dir / 'other-backup').symlink_to(other.dir, target_is_directory=True)
        self.assertEqual(ileapp.working_space(self.backup.dir), before)


if __name__ == '__main__':
    unittest.main()
