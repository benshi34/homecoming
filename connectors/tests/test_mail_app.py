"""Apple Mail read where Mail keeps it, on a synthetic home folder; and one email, once, in the index.

Run: python3 -m unittest discover -s connectors/tests -p 'test_*.py'
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CONNECTORS = Path(__file__).resolve().parents[1]
ACCOUNT = "D7391124-79D9-4D47-9F11-429968914C73"


def message(mid, frm="Sender <sender@example.test>", subject="Hello"):
    raw = (f"From: {frm}\nTo: Ada <ada@example.test>\nMessage-ID: <{mid}@example.test>\nSubject: {subject}\n"
           f"Date: Mon, 01 Jan 2024 00:00:00 +0000\n\nHi there.\n").encode()
    return str(len(raw)).encode() + b"\n" + raw + b"<?xml version=\"1.0\"?><plist><dict/></plist>"


class MailAppTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.home, self.corpus = Path(t.name) / "home", Path(t.name) / "corpus"
        (self.corpus).mkdir(parents=True)
        (self.corpus / "identity.json").write_text(json.dumps({"names": ["Ada"], "emails": ["ada@example.test"], "usernames": [], "phones": []}))
        self.mail = self.home / "Library/Mail/V10" / ACCOUNT
        accounts = self.home / "Library/Accounts/Accounts4.sqlite"
        accounts.parent.mkdir(parents=True)
        con = sqlite3.connect(accounts)
        con.execute("create table ZACCOUNT (Z_PK integer primary key, ZIDENTIFIER text, ZUSERNAME text, ZACCOUNTDESCRIPTION text, ZPARENTACCOUNT int)")
        con.execute("insert into ZACCOUNT values (1, 'parent', 'ada@outlook.test', 'Exchange', null)")
        con.execute("insert into ZACCOUNT values (2, ?, null, null, 1)", (ACCOUNT,))
        con.commit()
        con.close()

    def put(self, mailbox, n, data):
        d = self.mail / mailbox / "AAAA/Data/1/Messages"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{n}.emlx").write_bytes(data)
        return d / f"{n}.emlx"

    def run_py(self, code):
        env = {**os.environ, "HOME": str(self.home), "CORPUS_DIR": str(self.corpus)}
        r = subprocess.run([sys.executable, "-c", code], cwd=CONNECTORS, env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)

    def records(self, source="mail"):
        return {r["id"]: r for r in map(json.loads, (self.corpus / f"normalized/{source}.jsonl").read_text().splitlines())}

    def test_folders_accounts_and_sent_mail(self):
        # The same message in All Mail and in Sent: it's the user's.
        self.put("[Gmail].mbox/All Mail.mbox", 1, message("mine", frm="Someone Else <x@example.test>"))
        self.put("[Gmail].mbox/Sent Mail.mbox", 2, message("mine", frm="Someone Else <x@example.test>"))
        self.put("Junk Email.mbox", 3, message("junk"))
        self.put("Inbox.mbox", 4, message("hello"))
        self.run_py("import mail_app; mail_app.main()")
        recs = self.records()
        self.assertEqual(len(recs), 3)
        mine = recs["<mine@example.test>"]
        self.assertEqual((mine["is_me"], mine["author"], mine["meta"]["folder"]), (True, "me", "[Gmail]/Sent Mail"))
        self.assertEqual(recs["<junk@example.test>"]["meta"]["tier"], "spam")
        self.assertEqual(recs["<hello@example.test>"]["meta"]["account"], "ada@outlook.test")
        self.assertFalse(recs["<hello@example.test>"]["is_me"])

    def test_read_flagged_and_mails_own_category(self):
        self.put("Inbox.mbox", 5, message("deal", frm="Shop <deals@shop.test>"))
        self.put("Inbox.mbox", 6, message("note", frm="Grace <grace@example.test>"))
        env = self.home / "Library/Mail/V10/MailData/Envelope Index"
        env.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(env)
        con.executescript("""create table messages (ROWID integer primary key, global_message_id int, read int, flagged int, date_last_viewed int);
            create table message_global_data (ROWID integer primary key, model_category int);
            insert into message_global_data values (1, 3), (2, 0);
            insert into messages values (5, 1, 0, 0, null), (6, 2, 1, 1, 1704067200);""")
        con.commit()
        con.close()
        self.run_py("import mail_app; mail_app.main()")
        recs = self.records()
        deal, note = recs["<deal@example.test>"]["meta"], recs["<note@example.test>"]["meta"]
        self.assertEqual((deal["read"], deal["category"], deal.get("flagged")), (False, "promotions", None))
        self.assertEqual((note["read"], note["flagged"], note["category"], note["viewed"]), (True, True, "primary", "2024-01-01T00:00:00Z"))

    def test_unchanged_messages_arent_read_again(self):
        self.put("Inbox.mbox", 1, message("one"))
        self.run_py("import mail_app; mail_app.main()")
        self.put("Inbox.mbox", 2, message("two"))
        self.run_py("import mail_app; mail_app.main()")
        manifest = json.loads((self.corpus / "manifest.json").read_text())["mail"]
        self.assertEqual(manifest["notes"]["read_again"], 1)
        self.assertEqual(set(self.records()), {"<one@example.test>", "<two@example.test>"}, "the unread one carried over")
        # New addresses can change what's the user's, so everything is read again.
        (self.corpus / "identity.json").write_text(json.dumps({"names": [], "emails": ["sender@example.test"], "usernames": [], "phones": []}))
        self.run_py("import mail_app; mail_app.main()")
        self.assertEqual(json.loads((self.corpus / "manifest.json").read_text())["mail"]["notes"]["read_again"], 2)
        self.assertTrue(self.records()["<one@example.test>"]["is_me"])

    def test_an_email_in_mail_and_an_export_is_indexed_once(self):
        norm = self.corpus / "normalized"
        norm.mkdir()
        rec = lambda source, mid: json.dumps({"id": f"<{mid}@example.test>", "source": source, "kind": "email", "ts": "2024-01-01T00:00:00Z", "text": mid})
        (norm / "hotmail.jsonl").write_text(rec("hotmail", "both") + "\n")
        (norm / "mail.jsonl").write_text(rec("mail", "both") + "\n" + rec("mail", "only_in_mail") + "\n")
        (self.corpus / "manifest.json").write_text(json.dumps({"mail": {"count": 2}, "hotmail": {"count": 1}}))
        self.run_py("import build_index; build_index.main()")
        con = sqlite3.connect(self.corpus / "corpus.db")
        rows = sorted(con.execute("select source, id from records where kind = 'email'").fetchall())
        self.assertEqual(rows, [("hotmail", "<both@example.test>"), ("mail", "<only_in_mail@example.test>")])
        self.assertEqual(json.loads((self.corpus / "manifest.json").read_text())["mail"]["notes"], {"in_an_export": 1})


if __name__ == "__main__":
    unittest.main()
