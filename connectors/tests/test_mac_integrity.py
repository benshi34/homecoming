"""What has to stay the same from one read to the next, on a made-up home folder: the manifest a crash can't cut short,
a call in both copies counted once for good, ids an iPhone module can't switch, Mail's Sent copy kept, the stream
rebuilt for a relabel, downloads and tabs as they really are, documents that aren't yours left out, and the iPhone
read again with its backup gone. Every name, message and file here is invented.

Run: python3 -m unittest discover -s connectors/tests -p 'test_*.py'
"""
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

CONNECTORS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONNECTORS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common
from test_mac_sources import APPLE, chat_storage, maps_sync

PHONE_WA = "AppDomainGroup-group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite"


class Home(unittest.TestCase):
    """A made-up home folder and library; connectors run in their own process, reading only those."""

    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.home, self.corpus = Path(t.name) / "home", Path(t.name) / "corpus"
        self.home.mkdir()
        self.corpus.mkdir()
        (self.corpus / "identity.json").write_text(json.dumps({"names": ["Ada Lovelace"], "emails": ["ada@example.test"],
                                                               "usernames": [], "phones": []}))

    def run_py(self, code, **env):
        e = {**os.environ, "HOME": str(self.home), "CORPUS_DIR": str(self.corpus), "TZ": "UTC", **env}
        r = subprocess.run([sys.executable, "-c", code], cwd=CONNECTORS, env=e, capture_output=True, text=True, timeout=180)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return r.stdout

    def records(self, source):
        f = self.corpus / f"normalized/{source}.jsonl"
        return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []

    def manifest(self):
        return json.loads((self.corpus / "manifest.json").read_text())


class WriterTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        for name, value in (("NORM", self.root / "normalized"), ("MANIFEST", self.root / "manifest.json")):
            p = patch.object(common, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(common, "code_version", return_value="fixture")
        p.start()
        self.addCleanup(p.stop)

    def write(self, recs, **kw):
        with redirect_stdout(io.StringIO()), common.Writer("notes", "fixture", parser="fixture", **kw) as w:
            for r in recs:
                w.add(**r)

    def test_a_manifest_cut_short_is_read_as_empty_and_written_whole(self):
        common.MANIFEST.write_text('{"mail": {"count": 3, "kin')  # a crash in the middle of writing it
        self.write([{"id": "1", "kind": "note", "text": "hello"}])
        m = json.loads(common.MANIFEST.read_text())
        self.assertEqual((sorted(m), m["notes"]["count"]), (["notes"], 1), "every later read goes on")
        self.assertEqual([p.name for p in self.root.iterdir() if p.name.endswith(".tmp")], [], "no temp file left")

    def test_half_an_emoji_is_replaced_not_the_source_lost(self):
        self.write([{"id": "1", "kind": "post", "text": json.loads('"cut emoji \\ud83d here"')},
                    {"id": "2", "kind": "post", "text": "fine 😀"}])
        recs = [json.loads(x) for x in (common.NORM / "notes.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["text"] for r in recs], ["cut emoji � here", "fine 😀"])

    def test_what_an_earlier_run_kept_can_be_let_go(self):
        self.write([{"id": "tab1", "kind": "open_tab", "text": "a"}, {"id": "bm1", "kind": "bookmark", "text": "b"}])
        self.write([{"id": "tab2", "kind": "open_tab", "text": "c"}], forget=lambda r: r.get("kind") == "open_tab")
        ids = sorted(json.loads(x)["id"] for x in (common.NORM / "notes.jsonl").read_text().splitlines())
        self.assertEqual(ids, ["bm1", "tab2"], "the bookmark stays; yesterday's tab doesn't")


def call_db(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    con = sqlite3.connect(path)
    con.execute("create table ZCALLRECORD (ZUNIQUE_ID text, ZDATE real, ZDURATION real, ZADDRESS text, ZNAME text, ZORIGINATED int, "
                "ZANSWERED int, ZCALLTYPE int, ZLOCATION text)")
    con.executemany("insert into ZCALLRECORD values (?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()


class CallsTests(Home):
    def test_a_call_the_mac_pruned_is_still_the_phones_copy(self):
        mac = self.home / "Library/Application Support/CallHistoryDB/CallHistory.storedata"
        phone = self.corpus / "raw/iphone/files/HomeDomain/Library/CallHistoryDB/CallHistory.storedata"
        call = lambda uid, t=700000000.0: (uid, t, 60, "+14155550100", None, 1, 1, 1, None)  # noqa: E731
        call_db(mac, [call("MAC-1")])
        self.run_py("import calls; calls.main()")  # January: the Mac's daily read
        call_db(mac, [])
        self.run_py("import calls; calls.main()")  # months later the Mac has pruned it: kept from the first read
        call_db(phone, [call("PHONE-1", 700000002.0), call("PHONE-2", 700100000.0)])
        self.run_py("import calls; calls.main()")  # the iPhone's backup, read for the first time
        self.assertEqual(sorted(r["id"] for r in self.records("calls")), ["PHONE-1", "PHONE-2"], "one call, not two")
        self.assertEqual(self.manifest()["calls"]["notes"], {"same_call_in_both_copies": 1})
        # And the other way: the phone's copy kept, the Mac reading a call it has too.
        call_db(phone, [])
        call_db(mac, [call("MAC-2", 700100003.0)])
        self.run_py("import calls; calls.main()")
        self.assertEqual(sorted(r["id"] for r in self.records("calls")), ["PHONE-1", "PHONE-2"])


class IleappIdTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        for name, value in (("NORM", self.root / "normalized"), ("MANIFEST", self.root / "manifest.json")):
            p = patch.object(common, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(common, "code_version", return_value="fixture")
        p.start()
        self.addCleanup(p.stop)

    def read(self, rows):
        import ileapp
        con = sqlite3.connect(":memory:")
        con.execute('create table t ("order_id" text, "item" text, "when" text)')
        con.executemany("insert into t values (?,?,?)", rows)
        a = {"column_map": [["order_id", "Order ID"], ["item", "Item"], ["when", "When"]], "object_columns": [{"name": "when", "type": "datetime"}],
             "artifact_key": "shopOrders", "name": "Shop - Orders", "tablename": "t"}
        with redirect_stdout(io.StringIO()):
            ileapp.write_module("shop", [("Shopping", a)], con, {}, "fixture", {}, {})
        con.close()
        return sorted(json.loads(x)["id"] for x in (common.NORM / "phone_shop.jsonl").read_text().splitlines())

    def test_the_id_column_stays_when_a_backup_repeats_a_row(self):
        rows = [("o1", "socks", 1700000000), ("o2", "hat", 1700100000), ("o3", "mug", 1700200000)]
        self.assertEqual(self.read(rows), ["shopOrders:o1", "shopOrders:o2", "shopOrders:o3"])
        # The next backup: the module's join repeats o3, and o2 comes back with something else under its id.
        again = self.read(rows + [("o3", "mug", 1700200000), ("o2", "scarf", 1700300000)])
        self.assertEqual(len(again), 4, "the repeat dropped, the other row kept, nothing twice")
        self.assertEqual([i for i in again if "#" not in i], ["shopOrders:o1", "shopOrders:o2", "shopOrders:o3"], "the same ids as before")
        self.assertTrue([i for i in again if "#" in i][0].startswith("shopOrders:o2#"))
        self.assertEqual(json.loads(common.MANIFEST.read_text())["phone_shop"]["notes"]["id_columns"], {"shopOrders": "order_id"})

    def test_an_import_from_before_the_choice_was_kept_keeps_its_ids(self):
        common.NORM.mkdir()
        (common.NORM / "phone_shop.jsonl").write_text(json.dumps({"id": "shopOrders:0123456789abcdef", "source": "phone_shop",
                                                                   "kind": "record"}) + "\n")  # hashed, no manifest note
        ids = self.read([("o1", "socks", 1700000000), ("o2", "hat", 1700100000)])
        self.assertFalse({"shopOrders:o1", "shopOrders:o2"} & set(ids), "still hashes, as that import wrote them")
        self.assertEqual(json.loads(common.MANIFEST.read_text())["phone_shop"]["notes"]["id_columns"], {"shopOrders": None})


class WhatsAppSenderTests(Home):
    def test_a_phone_group_message_has_who_wrote_it(self):
        chats = [(1, "120363000000000001@g.us", "Allotment crew", 1), (2, "15550001111@s.whatsapp.net", "Bea Quill", 0)]
        members = [(1, 1, "15550002222@s.whatsapp.net", "Cal Rowan")]
        t = 780000000
        rows = [(1, 1, 0, t, "Who has the shed key?", "S1", 0, 1, None, "120363000000000001@g.us", None, 0),
                (2, 2, 0, t + 60, "Leeks?", "S2", 0, None, None, "15550001111@s.whatsapp.net", None, 0)]
        chat_storage(self.corpus / "raw/iphone/files" / PHONE_WA, rows, chats, members)
        # What iLEAPP's module makes of them (its LAVA table): the group's name as the sender.
        lava = self.corpus / "lava.db"
        con = sqlite3.connect(lava)
        con.execute("create table m (timestamp, direction, sender_name, chat_name, message, chat_id)")
        con.executemany("insert into m values (?,?,?,?,?,?)", [
            (t + APPLE, "Incoming", "Allotment crew", "Allotment crew", "Who has the shed key?", "120363000000000001@g.us"),
            (t + APPLE + 30, "Incoming", "Allotment crew", "Allotment crew", "A message the database doesn't have", "120363000000000001@g.us"),
            (t + 60 + APPLE, "Incoming", "Bea Quill", "Bea Quill", "Leeks?", "15550001111@s.whatsapp.net")])
        con.commit()
        con.close()
        self.run_py(f"""import sqlite3, ileapp
conv = {{"conversationDiscriminatorColumn": "chat_id", "conversationLabelColumn": "chat_name", "textColumn": "message",
        "directionColumn": "direction", "directionSentValue": "Outgoing", "timeColumn": "timestamp", "senderColumn": "sender_name"}}
a = {{"name": "WhatsApp - Messages", "tablename": "m", "artifact_key": "whatsAppMessages", "column_map": [],
      "object_columns": [{{"name": "timestamp", "type": "datetime"}}], "data_views": {{"conversation": conv}}}}
ileapp.write_module("whatsApp", [("WhatsApp", a)], sqlite3.connect({str(lava)!r}), {{}}, "fixture", {{}}, {{}})""")
        by = {r["text"]: r["author"] for r in self.records("phone_whatsapp")}
        self.assertEqual(by, {"Who has the shed key?": "Cal Rowan", "A message the database doesn't have": "someone in the group",
                              "Leeks?": "Bea Quill"}, "never the group's own name")


def emlx(mid, frm="Me <ada.alias@work.example>"):
    raw = (f"Message-ID: <{mid}@example.test>\nFrom: {frm}\nTo: bob@example.test\nSubject: Report\n"
           "Date: Mon, 1 Jan 2024 10:00:00 +0000\n\nhere it is\n").encode()
    return str(len(raw)).encode() + b"\n" + raw + b"<?xml version=\"1.0\"?><plist><dict/></plist>"


class MailTests(Home):
    def test_the_sent_copy_stays_and_what_mail_says_comes_through(self):
        acct = self.home / "Library/Mail/V10/ACCT-1"
        for box, n in (("Sent Messages.mbox", 1), ("INBOX.mbox", 2)):  # a reply-all to yourself: in Sent and in the Inbox
            p = acct / box / "Messages" / f"{n}.emlx"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(emlx("x1"))
        env = self.home / "Library/Mail/V10/MailData/Envelope Index"
        env.parent.mkdir(parents=True)
        con = sqlite3.connect(env)
        con.executescript("create table messages (ROWID integer primary key, global_message_id int, read int, flagged int, date_last_viewed int);"
                          "create table message_global_data (ROWID integer primary key, model_category int);"
                          "insert into message_global_data values (1, 0); insert into messages values (1, 1, 0, 0, null);")
        con.commit()
        con.close()
        self.run_py("import mail_app; mail_app.main()")
        r = self.records("mail")[0]
        self.assertEqual((r["meta"]["folder"], r["is_me"]), ("Sent Messages", True))
        inbox = acct / "INBOX.mbox/Messages/2.emlx"
        os.utime(inbox, (time.time() + 5, time.time() + 5))  # Mail rewrote the Inbox copy (its flags)
        con = sqlite3.connect(env)
        con.execute("update messages set read = 1, flagged = 1")  # and you read and flagged the Sent one
        con.commit()
        con.close()
        self.run_py("import mail_app; mail_app.main()")
        r = self.records("mail")
        self.assertEqual(len(r), 1)
        self.assertEqual((r[0]["meta"]["folder"], r[0]["is_me"], r[0]["author"]), ("Sent Messages", True, "me"), "still yours")
        self.assertEqual((r[0]["meta"]["read"], r[0]["meta"]["flagged"]), (True, True), "read and flagged since, though its file didn't change")


class StreamTests(Home):
    def test_a_relabel_rebuilds_the_month(self):
        norm = self.corpus / "normalized"
        norm.mkdir()

        def write(author, is_me):
            r = {"id": "<m1@x>", "source": "gmail", "kind": "email", "ts": "2024-03-05T18:00:00Z", "author": author, "is_me": is_me,
                 "title": "Lunch", "text": "Lunch\nsee you", "thread": "lunch", "participants": ["bob@example.test"],
                 "meta": {"from": "ada@example.test", "to": ["bob@example.test"]}}
            (norm / "gmail.jsonl").write_text(json.dumps(r) + "\n")
            self.run_py("import build_index; build_index.main()")
            return [json.loads(x) for x in (self.corpus / "stream/2024-03.jsonl").read_text().splitlines()]
        before = write("Ada Lovelace <ada@example.test>", False)
        after = write("me", True)  # the same counts and lengths, relabeled as yours
        self.assertEqual((before[0]["mine"], after[0]["mine"]), (0, 1))


def chrome_history(path, downloads):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    con = sqlite3.connect(path)
    con.executescript("""create table urls (id integer primary key, url text, title text, visit_count int);
        create table visits (id integer primary key, url int, visit_time int, transition int, visit_duration int);
        create table downloads (id integer primary key, guid text, target_path text, start_time int, total_bytes int, state int,
            mime_type text, referrer text, tab_url text);
        create table downloads_url_chains (id int, chain_index int, url text);""")
    for i, (guid, file, start) in enumerate(downloads, 1):
        con.execute("insert into downloads values (?, ?, ?, ?, 2048, 1, 'application/pdf', null, null)", (i, guid, f"/Users/ada/Downloads/{file}", start))
        con.execute("insert into downloads_url_chains values (?, 0, ?)", (i, f"https://files.example/{file}"))
    con.commit()
    con.close()


class BrowserTests(Home):
    def saved(self):
        return sorted((r["id"].split(":")[-1], r["kind"], r.get("title")) for r in self.records("browser_saved"))

    def test_downloads_by_guid_tags_and_tabs(self):
        history = self.home / "Library/Application Support/Google/Chrome/Default/History"
        chrome_history(history, [("G-LEASE", "lease.pdf", 13370000000000000)])
        ff = self.home / "Library/Application Support/Firefox/Profiles/ab12.default-release/places.sqlite"
        ff.parent.mkdir(parents=True)
        con = sqlite3.connect(ff)
        con.executescript("""create table moz_places (id integer primary key, url text, title text, visit_count int);
            create table moz_historyvisits (id integer primary key, place_id int, visit_date int, visit_type int);
            create table moz_bookmarks (id integer primary key, type int, fk int, parent int, title text, dateAdded int, guid text);
            insert into moz_places values (1, 'https://bread.example', 'Bread', 1);
            insert into moz_bookmarks values (1, 2, null, 0, '', 1700000000000000, 'root________'),
                (3, 2, null, 1, 'toolbar', 1700000000000000, 'toolbar_____'), (4, 2, null, 1, 'tags', 1700000000000000, 'tags________');
            insert into moz_bookmarks values (10, 1, 1, 3, 'Bread', 1700000000000000, 'bm1');
            insert into moz_bookmarks values (11, 2, null, 4, 'baking', 1700000001000000, 't1'), (12, 1, 1, 11, null, 1700000001000000, 't1e');""")
        con.commit()
        con.close()
        tabs = self.home / "Library/Containers/com.apple.Safari/Data/Library/Safari/CloudTabs.db"
        tabs.parent.mkdir(parents=True)
        con = sqlite3.connect(tabs)
        con.executescript("""create table cloud_tab_devices (device_uuid text, device_name text);
            create table cloud_tabs (tab_uuid text, device_uuid text, title text, url text, is_pinned int, last_viewed_time real);
            insert into cloud_tab_devices values ('D1', 'iPhone');
            insert into cloud_tabs values ('T1', 'D1', 'Train times', 'https://trains.example', 0, 780000000);""")
        con.commit()
        con.close()
        self.run_py("import browser_history; browser_history.main()")
        self.assertEqual(self.saved(), [("10", "bookmark", "Bread"), ("G-LEASE", "download", "lease.pdf"), ("T1", "open_tab", "Train times")],
                         "a tag is no bookmark")
        # Download history cleared, a new download (Chrome numbers it 1 again); the tab closed and another opened.
        chrome_history(history, [("G-PHOTO", "photo.jpg", 13380000000000000)])
        con = sqlite3.connect(tabs)
        con.executescript("delete from cloud_tabs; insert into cloud_tabs values ('T2', 'D1', 'Weather', 'https://wx.example', 0, 780100000);")
        con.commit()
        con.close()
        self.run_py("import browser_history; browser_history.main()")
        self.assertEqual(self.saved(), [("10", "bookmark", "Bread"), ("G-LEASE", "download", "lease.pdf"), ("G-PHOTO", "download", "photo.jpg"),
                                        ("T2", "open_tab", "Weather")], "both downloads; only the tab open now")

    def test_downloads_kept_by_row_number_become_one_by_guid(self):
        history = self.home / "Library/Application Support/Google/Chrome/Default/History"
        chrome_history(history, [("G-LEASE", "lease.pdf", 13370000000000000)])
        norm = self.corpus / "normalized"
        norm.mkdir()
        # What an earlier version wrote: the download by Chrome's row number.
        (norm / "browser_saved.jsonl").write_text(json.dumps({"id": "chrome:Default:download:1", "source": "browser_saved", "kind": "download",
                                                              "ts": common.from_webkit(13370000000000000), "title": "lease.pdf"}) + "\n")
        self.run_py("import browser_history; browser_history.main()")
        self.assertEqual([r["id"] for r in self.records("browser_saved")], ["chrome:Default:download:G-LEASE"])


class PhotosAndMapsTests(Home):
    def test_memories_are_as_photos_has_them_now(self):
        from test_photos import library
        library(self.home)
        db = self.home / "Pictures/Photos Library.photoslibrary/database/Photos.sqlite"
        con = sqlite3.connect(db)
        con.executescript("""create table ZMEMORY (ZUUID text, ZTITLE text, ZSUBTITLE text, ZSTARTDATE real, ZENDDATE real, ZCREATIONDATE real,
            ZFAVORITE int, ZPLAYCOUNT int, ZSHARECOUNT int, ZREJECTED int);
            insert into ZMEMORY values ('M1', 'Summer', null, 700000000, 700500000, 701000000, 0, 0, 0, 0);""")  # an older library: no ZVIEWCOUNT
        con.commit()
        con.close()
        self.run_py("import photos; photos.main()")
        self.assertEqual([r["id"] for r in self.records("photos_memories")], ["memory:M1"], "one column missing loses nothing")
        con = sqlite3.connect(db)
        con.execute("update ZMEMORY set ZREJECTED = 1")  # you turned it down
        con.commit()
        con.close()
        self.run_py("import photos; photos.main()")
        self.assertEqual(self.records("photos_memories"), [])

    def test_maps_visits_with_a_column_missing(self):
        db = self.home / "Library/Containers/com.apple.Maps/Data/Maps/MapsSync_0.0.1"
        maps_sync(db)
        con = sqlite3.connect(db)
        con.executescript("drop table ZVISIT; create table ZVISIT (Z_PK integer primary key, ZSTARTDATE real, ZLOCATION int);"
                          "insert into ZVISITEDLOCATION (Z_PK, ZMAPITEMNAME) values (90, 'Corner Bakery');"
                          "insert into ZVISIT values (1, 780000000, 90);")
        con.commit()
        con.close()
        self.run_py("import apple_maps; apple_maps.main()")
        visits = [r for r in self.records("apple_maps") if r["kind"] == "place_visit"]
        self.assertEqual([(r["id"], r["title"]) for r in visits], [("visit:1", "Corner Bakery")])


class DocumentsTests(Home):
    def test_what_isnt_yours_and_what_hasnt_changed(self):
        docs, dl = self.home / "Documents", self.home / "Downloads"
        docs.mkdir()
        (docs / "plan.md").write_text("The plan")
        (docs / "Passwords.csv").write_text("name,url,username,password\nBank,https://bank.example,ada,hunter2\n")
        (docs / "codes.csv").write_text("issuer,link\nMail,otpauth://totp/Mail:ada?secret=ABC\n")
        fb = dl / "facebook-ada-2026-10-01-abc"  # Safari unzipped it here
        (fb / "your_facebook_activity/messages/inbox/grace_1").mkdir(parents=True)
        (fb / "your_facebook_activity/messages/inbox/grace_1/message_1.html").write_text("<p>Grace: hi</p>")
        (dl / "loose_messages/inbox/alan_2").mkdir(parents=True)
        (dl / "loose_messages/inbox/alan_2/message_1.html").write_text("<p>Alan: hello</p>")
        (dl / "flight.txt").write_text("Flight at nine")
        cloud = self.home / "Library/CloudStorage"
        (cloud / "OneDrive-SharedLibraries-Contoso/Team").mkdir(parents=True)
        (cloud / "OneDrive-SharedLibraries-Contoso/Team/minutes.md").write_text("Someone else's minutes")
        drive = cloud / "GoogleDrive-ada@example.test"
        for d in ("My Drive", "Shared drives/Club", "Other computers/Old laptop", "My Drive/Archive"):
            (drive / d).mkdir(parents=True)
        (drive / "My Drive/essay.md").write_text("My essay")
        (drive / "Shared drives/Club/rota.md").write_text("The club's rota")
        (drive / "Other computers/Old laptop/old.md").write_text("A backup")
        (drive / "My Drive/Archive/far.md").write_text("in the cloud only")
        (self.home / "Library/Mail").mkdir(parents=True)
        (self.home / "Library/Mail/note.txt").write_text("Mail's own file")
        (self.home / ".obsidian").mkdir()
        obsidian = self.home / "Library/Application Support/obsidian"
        obsidian.mkdir(parents=True)
        (obsidian / "obsidian.json").write_text(json.dumps({"vaults": {"a1": {"path": str(self.home)}}}))  # a vault set at the home folder
        (self.home / "Notes").mkdir()
        (self.home / "Notes/garden.md").write_text("Beans in May")
        patch = "import common, pathlib; common.cloud_only = lambda p: pathlib.Path(p).name == 'Archive'; "
        self.run_py(patch + "import documents; documents.main()")
        recs = {Path(r["meta"]["path"]).name: r for r in self.records("documents")}
        self.assertEqual(sorted(recs), ["Passwords.csv", "codes.csv", "essay.md", "flight.txt", "garden.md", "plan.md"])
        for name in ("Passwords.csv", "codes.csv"):
            self.assertEqual(recs[name]["text"], name, "a password manager's export: only its name")
            self.assertNotIn("hunter2", json.dumps(recs[name]))
        notes = self.manifest()["documents"]["notes"]
        self.assertEqual((notes["unzipped_exports"], notes["folders_in_the_cloud_only"], notes["password_files"]), (2, 1, 2))
        # Changed without its size or time changing (as a file that wasn't touched): not read again, its record carries over.
        st = (docs / "plan.md").stat()
        (docs / "plan.md").write_text("The PLAN")
        os.utime(docs / "plan.md", ns=(st.st_atime_ns, st.st_mtime_ns))
        self.run_py(patch + "import documents; documents.main()")
        recs = {Path(r["meta"]["path"]).name: r for r in self.records("documents")}
        self.assertEqual(recs["plan.md"]["text"], "The plan")
        (docs / "plan.md").write_text("The new plan")
        self.run_py(patch + "import documents; documents.main()")
        self.assertEqual({Path(r["meta"]["path"]).name: r for r in self.records("documents")}["plan.md"]["text"], "The new plan")

    def test_an_earlier_runs_records_of_what_isnt_yours_go(self):
        dl = self.home / "Downloads"
        (dl / "Takeout-export/Takeout/Drive").mkdir(parents=True)
        (dl / "Takeout-export/Takeout/Drive/report.md").write_text("A report")
        norm = self.corpus / "normalized"
        norm.mkdir()
        old = str(dl / "Takeout-export/Takeout/Drive/report.md")
        (norm / "documents.jsonl").write_text(json.dumps({"id": old, "source": "documents", "kind": "document", "text": "A report",
                                                          "meta": {"root": "Downloads", "path": old}}) + "\n")
        self.run_py("import documents; documents.main()")
        self.assertEqual(self.records("documents"), [])


class AiCodingTests(Home):
    def test_do_it_for_mes_sessions_arent_your_prompts(self):
        def session(folder, uuid, text):
            p = self.home / ".claude/projects" / folder / "s.jsonl"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"type": "user", "uuid": uuid, "sessionId": "s", "timestamp": "2026-09-01T10:00:00Z",
                                     "cwd": "/" + folder.strip("-").replace("-", "/"), "message": {"role": "user", "content": text}}) + "\n")
        session("-Users-ada-Developer-garden", "u1", "Add a watering schedule")
        session("-private-var-folders-xy-T-homecoming-agent-Ab12Cd", "u2", "Open the export page and request the data")
        norm = self.corpus / "normalized"
        norm.mkdir()
        # An earlier version read it as yours.
        (norm / "ai_coding.jsonl").write_text(json.dumps({"id": "u0", "source": "ai_coding", "kind": "ai_turn", "text": "Request the export",
                                                          "meta": {"tool": "claude-code", "cwd": "/private/var/folders/xy/T/homecoming-agent-Zz99"}}) + "\n")
        self.run_py("import ai_coding; ai_coding.main()")
        self.assertEqual([r["text"] for r in self.records("ai_coding")], ["Add a watering schedule"])
        self.assertEqual(self.manifest()["ai_coding"]["notes"], {"homecoming_agent_sessions": 1})


class IphoneAgainTests(Home):
    def test_read_again_with_the_backup_gone(self):
        """The app reads the copy already decrypted again after an update: no Finder backup needed."""
        out = self.run_py("import iphone; iphone.main(['--skip-decrypt', '--skip-ileapp'])")
        self.assertNotIn("No finished backup", out)


if __name__ == "__main__":
    unittest.main()
