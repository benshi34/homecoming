"""Several devices backed up on one Mac: the decrypted copy starts over when it's another device's backup, so one
phone's files never stay mixed in with another's; and with no backup picked, an iPhone's is read before an iPad's.

Run: python3 -m unittest discover -s connectors/tests -p 'test_*.py'
"""
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CONNECTORS = Path(__file__).resolve().parents[1]

# A stand-in for a backup: its device, and the files it holds (domain, path, contents). extract() just writes them.
STAND_IN = """
import json, sys
from pathlib import Path
import iphone_backup
spec = json.loads(sys.argv[1])
class Fake:
    def __init__(self, path=None):
        self.dir = Path(spec["dir"]); self.info = spec["info"]; self.encrypted = False; self.unreadable = []
    def describe(self): return self.info["Device Name"]
    def open(self, password): pass
    def files(self):
        for i, (domain, rel, text) in enumerate(spec["files"]):
            yield (f"id{i}", domain, rel, len(text), 1700000000 + i, None)
    def extract(self, file_id, key, n, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(spec["files"][int(file_id[2:])][2])
iphone_backup.Backup = Fake
iphone_backup.main([])
"""


class SwitchTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.corpus = self.root / "corpus"
        (self.corpus / "raw/iphone").mkdir(parents=True)

    def read(self, udid, device, files):
        d = self.root / "Backup" / udid
        d.mkdir(parents=True, exist_ok=True)
        info = {"Device Name": device, "Product Type": "iPhone17,1", "Target Identifier": udid}
        (d / "Info.plist").write_bytes(plistlib.dumps(info))
        env = {**os.environ, "HOME": str(self.root / "home"), "CORPUS_DIR": str(self.corpus)}
        r = subprocess.run([sys.executable, "-c", STAND_IN, json.dumps({"dir": str(d), "info": info, "files": files})],
                           cwd=CONNECTORS, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def mirror(self):
        base = self.corpus / "raw/iphone/files"
        return sorted(str(p.relative_to(base)) for p in base.rglob("*") if p.is_file())

    def test_another_devices_backup_starts_the_copy_over(self):
        self.read("UDID-ADA", "Ada's iPhone", [("HomeDomain", "Library/SMS/sms.db", "ada"), ("AppDomain-x", "Documents/only-ada", "a")])
        self.assertEqual(self.mirror(), ["AppDomain-x/Documents/only-ada", "HomeDomain/Library/SMS/sms.db"])
        # The same device again: incremental, nothing starts over.
        self.assertNotIn("from the start", self.read("UDID-ADA", "Ada's iPhone", [("HomeDomain", "Library/SMS/sms.db", "ada")]))
        self.assertIn("AppDomain-x/Documents/only-ada", self.mirror())
        # Another device: Ada's files go, and the record says whose it is now.
        out = self.read("UDID-SAM", "Sam's iPhone", [("HomeDomain", "Library/SMS/sms.db", "sam")])
        self.assertIn("A different device from last time (Ada's iPhone)", out)
        self.assertEqual(self.mirror(), ["HomeDomain/Library/SMS/sms.db"])
        self.assertEqual((self.corpus / "raw/iphone/files/HomeDomain/Library/SMS/sms.db").read_text(), "sam")
        self.assertEqual(json.loads((self.corpus / "raw/iphone/backup.json").read_text())["udid"], "UDID-SAM")

    def test_an_iphones_backup_before_a_newer_ipads(self):
        home = self.root / "home"
        root = home / "Library/Application Support/MobileSync/Backup"
        for name, product, mtime in (("PHONE", "iPhone17,1", 1000), ("TABLET", "iPad16,3", 2000)):
            d = root / name
            d.mkdir(parents=True)
            (d / "Info.plist").write_bytes(plistlib.dumps({"Product Type": product}))
            (d / "Manifest.db").write_bytes(b"")
            os.utime(d / "Info.plist", (mtime, mtime))
        env = {**os.environ, "HOME": str(home), "CORPUS_DIR": str(self.corpus)}
        r = subprocess.run([sys.executable, "-c", "import iphone_backup; print(iphone_backup.latest_backup().name)"], cwd=CONNECTORS,
                           env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.stdout.strip(), "PHONE", r.stderr)


if __name__ == "__main__":
    unittest.main()
