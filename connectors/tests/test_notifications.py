"""Notification Center fixtures for the retained Mac notification source."""

import json
import os
import plistlib
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path


CONNECTORS = Path(__file__).resolve().parents[1]
APPLE = 978307200


def payload(title, subtitle, body, thread=None, category=None):
    req = {"titl": title, "subt": subtitle, "body": body}
    if thread:
        req["thread-id"] = thread
    if category:
        req["cate"] = category
    return plistlib.dumps({"req": req})


class NotificationsTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        root = Path(t.name)
        self.home, self.corpus, self.db = root / "home", root / "corpus", root / "notifications" / "db"
        self.home.mkdir()
        self.corpus.mkdir()
        self.db.parent.mkdir()
        self._create_db()

    def _create_db(self):
        con = sqlite3.connect(self.db)
        con.executescript("""
            create table app (app_id integer primary key, identifier text, badge integer);
            create table record (rec_id integer primary key, app_id integer, uuid blob, data blob,
                request_date real, request_last_date real, delivered_date real, presented integer,
                style integer, snooze_fire_date real);
        """)
        con.executemany("insert into app values (?, ?, 0)", [(1, "com.example.macapp"), (2, "com.example.iphoneapp"),
                                                                 (3, "_system_center_:com.apple.diskarbitration"), (4, "com.example.systemapp")])
        con.commit()
        con.close()

    def add(self, rec_id, app_id, ident, title, subtitle, body, delivered, presented, style, thread=None, category=None):
        con = sqlite3.connect(self.db)
        con.execute("insert into record values (?, ?, ?, ?, null, null, ?, ?, ?, null)",
                    (rec_id, app_id, uuid.UUID(ident).bytes, payload(title, subtitle, body, thread, category), delivered, presented, style))
        con.commit()
        con.close()

    def run_connector(self, extra=None):
        env = {**os.environ, "HOME": str(self.home), "CORPUS_DIR": str(self.corpus), "UMP_NOTIFICATIONS_DB": str(self.db),
               "UMP_APPLICATIONS": str(self.home / "Applications"), **(extra or {})}
        r = subprocess.run([sys.executable, "-c", "import notifications; notifications.main()"], cwd=CONNECTORS,
                           env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)

    def records(self):
        path = self.corpus / "normalized/notifications.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def manifest(self):
        return json.loads((self.corpus / "manifest.json").read_text())["notifications"]

    def test_fields_shown_style_app_name_and_code_redaction(self):
        app = self.home / "Applications/Example.app/Contents"
        app.mkdir(parents=True)
        # As a real Mac keeps them: the bundle id as the app has it (MacApp), lowercased in the database
        (app / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "com.example.MacApp", "CFBundleDisplayName": "Example App"}))
        ext = app / "PlugIns/ServiceExtension.appex/Contents"
        ext.mkdir(parents=True)
        (ext / "Info.plist").write_bytes(plistlib.dumps({"CFBundleName": "ServiceExtension"}))
        sysapp = self.home / "System/Applications/Clock.app/Contents"
        sysapp.mkdir(parents=True)
        (sysapp / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "com.example.SystemApp", "CFBundleName": "\u200eClock"}))
        prefs = self.home / "usernoted.plist"
        prefs.write_bytes(plistlib.dumps({"apps": [
            {"bundle-id": "com.example.MacApp", "path": str(app.parent), "flags": 0,
             "src": [{"path": str(app / "PlugIns/ServiceExtension.appex")}]},  # named for the app, not its extension
            {"bundle-id": "com.example.SystemApp", "path": str(sysapp.parent), "flags": 0},  # on this Mac, outside /Applications
            {"bundle-id": "com.example.iPhoneApp", "path": "/Applications/Only On The Phone.app", "flags": 0},  # not on this Mac
            {"bundle-id": "_SYSTEM_CENTER_:com.apple.diskarbitration", "flags": 0}]}))
        # presented is 0 on every row of a real database; style says how it was delivered
        self.add(1, 1, "12345678-1234-5678-1234-567812345678", "Verify", "Security code 482913", "Use it now", APPLE + 800000000, 0, 1, "thread-1", "category-1")
        self.add(2, 2, "22345678-1234-5678-1234-567812345678", "Order", "Total 1234", "At 2:30", APPLE + 800000001, 0, 2)
        self.add(3, 3, "42345678-1234-5678-1234-567812345678", "Disk Not Ejected Properly", "", "", APPLE + 800000002, 0, 0)
        self.add(4, 4, "52345678-1234-5678-1234-567812345678", "Alarm", "", "7:00", APPLE + 800000003, 0, 2)
        self.run_connector({"UMP_NOTIFICATION_PREFS": str(prefs)})
        clock = next(r for r in self.records() if r["id"] == "52345678-1234-5678-1234-567812345678")
        self.assertEqual((clock["author"], clock["meta"].get("from_iphone")), ("Clock", None))
        rows = {r["id"]: r for r in self.records()}
        mac = rows["12345678-1234-5678-1234-567812345678"]
        self.assertEqual(mac["author"], "Example App")
        self.assertEqual(mac["text"], "Verify\nSecurity code [code]\nUse it now")
        self.assertEqual(mac["meta"], {"bundle": "com.example.macapp", "shown": True, "style": "banner",
                                         "thread_id": "thread-1", "category_id": "category-1"})
        phone = rows["22345678-1234-5678-1234-567812345678"]
        self.assertEqual(phone["text"], "Order\nTotal 1234\nAt 2:30")
        self.assertEqual(phone["meta"], {"bundle": "com.example.iphoneapp", "shown": True, "style": "alert", "from_iphone": True})
        system = rows["42345678-1234-5678-1234-567812345678"]
        self.assertEqual((system["author"], system["meta"]), ("macOS", {"bundle": "_system_center_:com.apple.diskarbitration",
                                                                          "shown": False, "style": "none"}))

    def test_accumulates_cleared_records_and_deduplicates_uuid(self):
        ident = "32345678-1234-5678-1234-567812345678"
        self.add(1, 1, ident, "First", "", "one", APPLE + 800000000, 1, 0)
        self.add(2, 1, ident, "First duplicate", "", "two", APPLE + 800000001, 1, 0)
        self.run_connector()
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(self.manifest()["notes"], {"duplicates": 1})
        con = sqlite3.connect(self.db)
        con.execute("delete from record")
        con.commit()
        con.close()
        self.run_connector()
        self.assertEqual(len(self.records()), 1, "a notification cleared before the next read stays in the corpus")

    def test_no_full_disk_access_is_reported(self):
        self.db.chmod(0)
        try:
            self.run_connector()
        finally:
            self.db.chmod(0o600)
        self.assertEqual(self.manifest()["notes"]["not_read"],
                         "macOS keeps notifications behind Full Disk Access: turn it on for this app, then try again.")

    def test_old_path_fixture_uses_the_same_schema(self):
        old = self.db.parent / "old" / "db"
        old.parent.mkdir()
        self.db.rename(old)
        self.db = old
        self.add(1, 1, "42345678-1234-5678-1234-567812345678", "Old", "", "path", APPLE + 800000000, 1, 1)
        self.run_connector()
        self.assertEqual(len(self.records()), 1)


if __name__ == "__main__":
    unittest.main()
