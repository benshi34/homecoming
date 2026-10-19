"""The bridge doing less for the same answers: Mail's index (and Notification Center's database) copied only when
it has changed, and kept no longer than it can be read; the quick look between looks in Mail; the readers' re-read.

Run: python3 -m unittest discover -s test/py -p 'test_*.py'
"""

import datetime as dt
import json
import os
import sqlite3
import time

from test_bridge import Sandbox, bridge, jsonout, mail_index

ASKED = [{"id": "discord", "names": ["Discord"], "domains": ["discord.com"], "since": "2026-10-05T00:00:00Z"}]
t = lambda d, h=12: dt.datetime(2026, 10, d, h, tzinfo=dt.timezone.utc)


class MailCopyTests(Sandbox):
    def look(self, db, *args):
        env = {"UMP_MAIL_DB": str(db), "UMP_NOTIFICATIONS_DB": str(self.tmp / "missing/db")}
        return jsonout(bridge(["export-signals", *args], self.home, self.corpus, stdin=json.dumps(ASKED), extra_env=env))

    def test_the_copy_is_made_again_only_once_mail_has_changed(self):
        db = mail_index(self.tmp / "Mail/V10", [(t(6), "noreply@discord.com", "Discord", "Hello from Discord", "Welcome", "<p>hi</p>")])
        copy = self.home / "Library/Caches/Homecoming/copies/mail/db"
        self.assertEqual(self.look(db)["matches"], [])
        made = copy.stat().st_ino
        self.assertEqual(oct(copy.parent.parent.stat().st_mode & 0o777), "0o700", "only you can read it")
        self.look(db)
        self.assertEqual(copy.stat().st_ino, made, "unchanged: not copied again")

        time.sleep(0.01)
        con = sqlite3.connect(db)
        con.execute("insert into addresses values (9, 'noreply@discord.com', 'Discord')")
        con.execute("insert into subjects values (9, 'Your Discord data package is ready')")
        con.execute("insert into summaries values (9, 'Download it below')")
        con.execute("insert into messages (ROWID, sender, subject, summary, date_received, mailbox) values (9, 9, 9, 9, ?, 1)", (int(t(8).timestamp()),))
        con.commit()
        con.close()
        d = self.look(db)
        self.assertEqual([m["source"] for m in d["matches"]], ["discord"], "the new email is seen at once")
        self.assertNotEqual(copy.stat().st_ino, made)

        self.assertEqual(self.look(db, "--no-mail"), {"readable": False, "mail": False, "matches": []}, "the quick look leaves Mail out")

        os.chmod(db, 0)  # as without Full Disk Access
        try:
            self.assertFalse(self.look(db)["mail"])
            self.assertFalse(copy.exists(), "what can't be read there isn't kept here")
        finally:
            os.chmod(db, 0o644)

    def test_a_wal_that_went_away_is_not_read_with_the_new_copy(self):
        db = mail_index(self.tmp / "Mail/V10", [(t(8), "noreply@discord.com", "Discord", "Your Discord data package is ready", "Download it below", "<p>x</p>")])
        con = sqlite3.connect(db)
        con.execute("pragma journal_mode = wal")
        con.execute("pragma wal_autocheckpoint = 0")
        con.execute("update subjects set subject = 'Hello' where ROWID = 1")  # only in the -wal
        con.execute("update summaries set summary = 'Welcome' where ROWID = 1")
        con.commit()
        self.assertEqual(self.look(db)["matches"], [], "read with its -wal")
        con.execute("pragma wal_checkpoint(truncate)")
        con.execute("pragma journal_mode = delete")  # the -wal is gone
        con.execute("update subjects set subject = 'Your Discord data package is ready' where ROWID = 1")
        con.execute("update summaries set summary = 'Download it below' where ROWID = 1")
        con.commit()
        con.close()
        self.assertFalse(os.path.exists(f"{db}-wal"))
        self.assertEqual([m["source"] for m in self.look(db)["matches"]], ["discord"])


class ProbeTests(Sandbox):
    def test_python_packages_are_taken_as_the_app_last_found_them(self):
        known = lambda path, v: {"UMP_PYTHON_MODULES": json.dumps({"path": path, "cryptography": v, "pypdf": v})}
        probe = lambda env: jsonout(bridge(["probe"], self.home, self.corpus, extra_env=env))["python"]
        real = probe({})
        said = not real["cryptography"]
        got = probe(known(real["path"], said))
        self.assertEqual((got["cryptography"], got["pypdf"]), (said, said), "not looked up again")
        other = probe(known("/some/other/python3", said))
        self.assertEqual(other["cryptography"], real["cryptography"], "another Python: looked up")


class RereadTests(Sandbox):
    def test_reread_reads_every_mailbox_again(self):
        box = self.corpus / "imports/hotmail/Inbox.mbox"
        box.parent.mkdir(parents=True)
        box.write_text("From x@example.test Mon Jan 01 00:00:00 2024\nFrom: G <g@example.test>\nMessage-ID: <1@x>\nSubject: hi\n\nhello\n")
        run = lambda *a: bridge(["run", *a, "imports", "--no-index"], self.home, self.corpus).stdout
        run()
        self.assertIn("kept as read", run())
        self.assertNotIn("kept as read", run("--reread"))
