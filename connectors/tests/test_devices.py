"""devices.py: the iPhones backed up here, the phone lines they've had, and this Mac, without the SIM's identifiers.

Run: python3 -m unittest discover -s connectors/tests -p 'test_devices.py'
"""
import datetime
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CONNECTORS = Path(__file__).resolve().parents[1]
# Made up, and shaped like the real thing, so a leak would show as an exact string.
ICCID, IMSI, IMEI, MEID, SERIAL = "8901260000000000017", "310260000000017", "350000000000017", "A0000000000017", "XQ17SERIAL"


class DevicesTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.home, self.corpus = Path(t.name) / "home", Path(t.name) / "corpus"
        backup = self.home / "Library/Application Support/MobileSync/Backup/00008101-TEST"
        backup.mkdir(parents=True)
        (backup / "Info.plist").write_bytes(plistlib.dumps({
            "Device Name": "Ada's iPhone", "Product Type": "iPhone13,2", "Product Version": "18.7",
            "Phone Number": "+1 (415) 555-0100", "Last Backup Date": datetime.datetime(2026, 11, 1, 18, 30),
            "ICCID": ICCID, "IMEI": IMEI, "MEID": MEID, "Serial Number": SERIAL, "Target Identifier": "00008101-TEST"}))
        (backup / "Info.plist.bak").write_text("not a plist")
        (self.home / "Library/Application Support/MobileSync/Backup/broken").mkdir()
        (self.home / "Library/Application Support/MobileSync/Backup/broken/Info.plist").write_text("garbage")
        lines = self.corpus / "raw/iphone/WirelessDomain/Library/Preferences/com.apple.commcenter.data.plist"
        lines.parent.mkdir(parents=True)
        lines.write_bytes(plistlib.dumps({
            "PersonalWallet": {"sim-a": {
                "z1": {"mdn": "4155550100", "esim": False, "cb_id": "com.apple.Verizon_US", "label-id": "L1",
                       "ts": 1700000000, "iccid": ICCID, "imsi": IMSI, "eap_aka": IMSI},
                "z2": {"mdn": "+81 90-0000-0017", "esim": True, "cb_id": "com.apple.Docomo_JP", "label-id": "L2",
                       "ts": 1760000000},
                "z3": {"esim": True},  # nothing about it: no number, label or carrier
            }},
            "unique-sim-label-store": {"L1": {"tag": 1, "text": "Personal"}, "L2": {"tag": 2, "text": "Travel"}},
        }))

    def run_devices(self):
        env = {**os.environ, "HOME": str(self.home), "CORPUS_DIR": str(self.corpus), "UMP_PHONE_REGION": "US"}
        subprocess.run([sys.executable, "devices.py"], cwd=CONNECTORS, env=env, check=True, capture_output=True)
        out = self.corpus / "normalized/devices.jsonl"
        return out.read_text(), {r["id"]: r for r in map(json.loads, out.read_text().splitlines())}

    def test_phone_lines_and_mac(self):
        raw, recs = self.run_devices()
        phone = recs["phone:00008101-TEST"]
        self.assertEqual(phone["kind"], "device")
        self.assertEqual(phone["meta"]["number"], "+14155550100")
        self.assertEqual(phone["ts"], "2026-11-01T18:30:00Z")
        self.assertIn("iPhone13,2, iOS 18.7", phone["text"])
        home = recs["line:+14155550100"]
        self.assertEqual((home["meta"]["label"], home["meta"]["carrier"], home["meta"]["esim"]), ("Personal", "Verizon", False))
        self.assertEqual(home["ts"], "2023-11-14T22:13:20Z")
        self.assertIn("SIM card", home["text"])
        travel = recs["line:+819000000017"]
        self.assertEqual((travel["meta"]["label"], travel["meta"]["carrier"], travel["meta"]["esim"]), ("Travel", "Docomo", True))
        self.assertEqual(sum(r["kind"] == "phone_line" for r in recs.values()), 2)
        if sys.platform == "darwin":
            self.assertTrue(any(r["meta"].get("this_mac") for r in recs.values()))
        self.assertNotIn("broken", raw)

    def test_sim_identifiers_never_written(self):
        raw, _ = self.run_devices()
        for value in (ICCID, IMSI, IMEI, MEID, SERIAL):
            self.assertNotIn(value, raw)
        self.assertNotIn("iccid", raw.lower())

    def test_no_backup_no_phone_records(self):
        import shutil
        shutil.rmtree(self.home / "Library")
        shutil.rmtree(self.corpus / "raw")
        _, recs = self.run_devices()
        self.assertFalse([r for r in recs.values() if r["kind"] == "phone_line" or r["id"].startswith("phone:")])


if __name__ == "__main__":
    unittest.main()
