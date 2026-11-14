"""Cloud drives, spreadsheets and Obsidian vaults in Documents; WhatsApp, Apple Maps and Books on this Mac. All on a
made-up home folder: every name, message and place here is invented.

Run: python3 -m unittest discover -s connectors/tests -p 'test_*.py'
"""
import json
import os
import plistlib
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

CONNECTORS = Path(__file__).resolve().parents[1]
APPLE = 978307200  # 2001-01-01 in Unix seconds


def run(home, corpus, module, patch=""):
    env = {**os.environ, "HOME": str(home), "CORPUS_DIR": str(corpus)}
    r = subprocess.run([sys.executable, "-c", f"{patch}import {module}; {module}.main()"], cwd=CONNECTORS, env=env,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr


def records(corpus, source):
    f = corpus / "normalized" / f"{source}.jsonl"
    return [json.loads(line) for line in f.read_text().splitlines()] if f.exists() else []


def manifest(corpus, source):
    return json.loads((corpus / "manifest.json").read_text())[source]


def varint(n):
    out = bytearray()
    while True:
        b, n = n & 0x7F, n >> 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def pb(*fields):
    """A protobuf message from (field, value) pairs: bytes/str/messages as length-delimited, ints as varints."""
    out = b""
    for f, v in fields:
        if isinstance(v, int):
            out += varint(f << 3) + varint(v)
        else:
            v = v.encode() if isinstance(v, str) else v
            out += varint(f << 3 | 2) + varint(len(v)) + v
    return out


def place_blob(name, *address):
    """A place as Maps stores it: a component whose entity has the name, and the address lines under 101."""
    component = pb((1, 1), (8, pb((1, pb((10, pb((1, pb((12, "en"))), (3, name)))),)),))
    return pb((1, pb((1, 7), (4, component))), (101, pb((2, pb(*((11, line) for line in address))),)))


def xlsx(path, sheets, shared):
    """A minimal .xlsx: the workbook, its relationships, shared strings and one part per sheet."""
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook {ns} {rel}><sheets>' + "".join(
            f'<sheet name="{n}" sheetId="{i}" r:id="rId{i}"/>' for i, (n, _) in enumerate(sheets, 1)) + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(
            f'<Relationship Id="rId{i}" Target="{"/xl/" if i == 2 else ""}worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1)) + "</Relationships>")
        z.writestr("xl/sharedStrings.xml", f"<sst {ns}>" + "".join(f"<si><t>{s}</t></si>" for s in shared) + "</sst>")
        for i, (_, rows) in enumerate(sheets, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", f"<worksheet {ns}><sheetData>" + "".join(
                "<row>" + "".join(c for c in row) + "</row>" for row in rows) + "</sheetData></worksheet>")


class Base(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.home, self.corpus = Path(t.name) / "home", Path(t.name) / "corpus"
        self.home.mkdir()
        self.corpus.mkdir()


class CloudDriveTests(Base):
    def test_cloud_drives_spreadsheets_pages_and_vaults(self):
        (self.home / "Documents/Vault Inside/.obsidian").mkdir(parents=True)
        (self.home / "Documents/Vault Inside/plan.md").write_text("A vault already in Documents")
        cloud = self.home / "Library/CloudStorage"
        one = cloud / "OneDrive-Personal/Budget"
        one.mkdir(parents=True)
        xlsx(one / "budget.xlsx", [("Spring", [['<c t="s"><v>0</v></c>', '<c><v>42.5</v></c>'], ['<c t="inlineStr"><is><t>Bread</t></is></c>', '<c t="b"><v>1</v></c>']]),
                                   ("Summer", [['<c t="s"><v>1</v></c>']])], ["Rent", "Ferry tickets"])
        (one / "trips.csv").write_text("when,where\n2025-05-01,Lisbon\n")
        (one / "page.html").write_text("<html><head><title>x</title><style>p{}</style></head><body><p>Tide tables</p>"
                                       "<script>var a=1</script><p>for Oban &amp; Mull</p></body></html>")
        (one / "page_files").mkdir()
        (one / "page_files/inner.html").write_text("<p>part of the saved page</p>")
        data = one / "data"
        data.mkdir()
        for i in range(6):  # a folder of CSVs is a dataset
            (data / f"part{i}.csv").write_text("a,b\n1,2\n")
        (one / "saved.webarchive").write_bytes(plistlib.dumps({"WebMainResource": {
            "WebResourceData": "<html><body><h1>Lighthouse keepers</h1></body></html>".encode(),
            "WebResourceTextEncodingName": "UTF-8", "WebResourceURL": "https://example.com/lights"}}, fmt=plistlib.FMT_BINARY))
        drive = cloud / "GoogleDrive-ada@example.com/My Drive"
        drive.mkdir(parents=True)
        (drive / "Thesis outline.gdoc").write_text('{"url": "https://docs.google.com/document/d/x"}')
        (drive / "away.docx").write_text("only in the cloud")
        (cloud / "Dropbox").mkdir()
        (cloud / "Dropbox/recipes.md").write_text("Soda bread")
        (self.home / "Dropbox").symlink_to(cloud / "Dropbox")  # Dropbox's old folder, now a link
        vault = self.home / "Notes/Garden"
        (vault / "Library").mkdir(parents=True)
        (vault / "README.md").write_text("What grows where")
        (vault / "Library/seeds.md").write_text("Runner beans in May")
        (vault / ".obsidian").mkdir()
        (vault / ".obsidian/workspace.json").write_text("{}")
        obsidian = self.home / "Library/Application Support/obsidian"
        obsidian.mkdir(parents=True)
        (obsidian / "obsidian.json").write_text(json.dumps({"vaults": {
            "a1": {"path": str(vault), "ts": 1700000000000}, "a2": {"path": str(self.home / "Documents/Vault Inside")},
            "a3": {"path": "/Volumes/Stick/Vault"}}}))
        run(self.home, self.corpus, "documents",
            patch="import common, pathlib; common.cloud_only = lambda p: pathlib.Path(p).name == 'away.docx'; ")
        recs = {Path(r["meta"]["path"]).name: r for r in records(self.corpus, "documents")}
        book = recs["budget.xlsx"]["text"]
        self.assertIn("Sheet: Spring\nRent | 42.5\nBread | TRUE\nSheet: Summer\nFerry tickets", book)
        self.assertEqual(recs["budget.xlsx"]["meta"]["root"], "OneDrive")
        self.assertIn("2025-05-01,Lisbon", recs["trips.csv"]["text"])
        self.assertEqual(recs["page.html"]["text"], "Tide tables\n for Oban & Mull")
        self.assertNotIn("inner.html", recs, "a saved page's own files aren't documents")
        self.assertFalse(any(n.startswith("part") for n in recs), "a folder of CSVs is a dataset")
        self.assertEqual(recs["saved.webarchive"]["text"], "Lighthouse keepers")
        self.assertEqual(recs["Thesis outline.gdoc"]["text"], "Google Docs document: Thesis outline\nFolder: My Drive")
        self.assertEqual(recs["Thesis outline.gdoc"]["meta"]["root"], "Google Drive")
        self.assertEqual(recs["away.docx"]["text"], "away.docx (in Google Drive, not downloaded)")
        dropbox = [r for r in records(self.corpus, "documents") if r["title"] == "recipes.md"]
        self.assertEqual(len(dropbox), 1, "~/Dropbox links to the same folder: read once")
        self.assertEqual(dropbox[0]["meta"]["root"], "Dropbox")
        self.assertEqual(recs["README.md"]["meta"], {**recs["README.md"]["meta"], "root": "Obsidian", "vault": "Garden"},
                         "a vault's README is a note")
        self.assertEqual(recs["seeds.md"]["text"], "Runner beans in May", "a vault's Library folder is notes")
        self.assertNotIn("workspace.json", recs)
        self.assertEqual(recs["plan.md"]["meta"]["root"], "Documents", "a vault in Documents is read there, once")
        self.assertEqual([r["title"] for r in records(self.corpus, "documents")].count("plan.md"), 1)
        notes = manifest(self.corpus, "documents")["notes"]
        self.assertEqual(notes, {"in_cloud_drive_only": 1, "vaults_on_other_disks": 1})


def pb(*fields):
    """A protobuf message: (number, int) as a varint, (number, bytes or str) length-delimited."""
    def varint(n):
        out = b""
        while True:
            out += bytes([(n & 0x7F) | (0x80 if n > 0x7F else 0)])
            n >>= 7
            if not n:
                return out
    out = b""
    for f, v in fields:
        if isinstance(v, int):
            out += varint(f << 3) + varint(v)
        else:
            v = v.encode() if isinstance(v, str) else v
            out += varint(f << 3 | 2) + varint(len(v)) + v
    return out


def chat_storage(path, rows, chats, members=(), push=(), media=(), info=()):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript("""
        create table ZWACHATSESSION (Z_PK integer primary key, ZCONTACTJID text, ZPARTNERNAME text, ZSESSIONTYPE int);
        create table ZWAGROUPMEMBER (Z_PK integer primary key, ZCHATSESSION int, ZMEMBERJID text, ZCONTACTNAME text);
        create table ZWAPROFILEPUSHNAME (Z_PK integer primary key, ZJID text, ZPUSHNAME text);
        create table ZWAMEDIAITEM (Z_PK integer primary key, ZMESSAGE int, ZMEDIALOCALPATH text, ZTITLE text,
            ZFILESIZE int, ZLATITUDE real, ZLONGITUDE real, ZVCARDNAME text, ZMETADATA blob);
        create table ZWAMESSAGEINFO (Z_PK integer primary key, ZMESSAGE int, ZRECEIPTINFO blob);
        create table ZWAMESSAGE (Z_PK integer primary key, ZCHATSESSION int, ZISFROMME int, ZMESSAGEDATE real, ZTEXT text,
            ZSTANZAID text, ZMESSAGETYPE int, ZGROUPMEMBER int, ZGROUPEVENTTYPE int, ZFROMJID text, ZTOJID text, ZSTARRED int);
    """)
    con.executemany("insert into ZWACHATSESSION values (?,?,?,?)", chats)
    con.executemany("insert into ZWAGROUPMEMBER values (?,?,?,?)", members)
    con.executemany("insert into ZWAPROFILEPUSHNAME values (?,?,?)", push)
    con.executemany("insert into ZWAMEDIAITEM values (?,?,?,?,?,?,?,?,?)", [tuple(m) + (None,) * (9 - len(m)) for m in media])
    con.executemany("insert into ZWAMESSAGEINFO (ZMESSAGE, ZRECEIPTINFO) values (?,?)", info)
    con.executemany("insert into ZWAMESSAGE values (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()


class WhatsAppTests(Base):
    CHATS = [(1, "15550001111@s.whatsapp.net", "Bea Quill", 0), (2, "120363000000000001@g.us", "Allotment crew", 1),
             (3, "status@broadcast", None, 0)]
    MEMBERS = [(1, 2, "15550002222@s.whatsapp.net", "Cal Rowan"), (2, 2, "15550003333@s.whatsapp.net", None)]
    T = 780000000  # 2025-09-19 in Apple time

    def mac(self, rows):
        chat_storage(self.home / "Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite", rows,
                     self.CHATS, self.MEMBERS, push=[(1, "15550003333@s.whatsapp.net", "Dee")],
                     media=[(1, 4, "Media/120363000000000001@g.us/a/b/leeks.jpg", None, 2048, None, None, None)])

    ROWS = [(1, 1, 0, T, "Are the leeks up yet?", "S1", 0, None, None, "15550001111@s.whatsapp.net", None, 0),
            (2, 1, 1, T + 60, "Not yet, maybe Friday", "S2", 0, None, None, None, "15550001111@s.whatsapp.net", 1),
            (3, 2, 0, T + 120, "Who has the shed key?", "S3", 0, 2, 2, "120363000000000001@g.us", None, 0),  # the app's 2: a message
            (4, 2, 0, T + 180, "Look at these", "S4", 1, 1, None, "120363000000000001@g.us", None, 0),
            (5, 2, 0, T + 240, None, "S5", 6, 1, 2, "120363000000000001@g.us", None, 0),
            (6, 3, 0, T + 300, "my holiday", "S6", 0, None, None, "15550002222@s.whatsapp.net", None, 0),
            (7, 1, 0, T + 360, None, "S7", 14, None, None, "15550001111@s.whatsapp.net", None, 0),
            (8, 3, 1, T + 420, "Garden at dusk", "S8", 0, None, None, None, "status@broadcast", 0)]

    def test_chats_groups_and_who_wrote_what(self):
        self.mac(self.ROWS)
        run(self.home, self.corpus, "whatsapp")
        recs = {r["id"]: r for r in records(self.corpus, "whatsapp")}
        self.assertEqual(sorted(recs), ["S1", "S2", "S3", "S4", "S5", "S7", "S8"], "others' status updates aren't chats")
        self.assertEqual((recs["S8"]["kind"], recs["S8"]["thread_name"], recs["S8"].get("participants")), ("post", "Status updates", None))
        self.assertEqual((recs["S1"]["author"], recs["S1"]["thread_name"], recs["S1"]["participants"]),
                         ("Bea Quill", "Bea Quill", ["Bea Quill"]))
        self.assertTrue(recs["S2"]["is_me"])
        self.assertEqual(recs["S2"]["author"], "me")
        self.assertTrue(recs["S2"]["meta"]["starred"])
        self.assertEqual(recs["S1"]["ts"], "2025-09-19T18:40:00Z")
        self.assertEqual(recs["S3"]["author"], "Dee", "a member without a contact name: the name they gave WhatsApp")
        self.assertEqual(recs["S3"]["participants"], ["Cal Rowan", "Dee"])
        self.assertEqual(recs["S3"]["thread"], "120363000000000001@g.us")
        self.assertTrue(recs["S3"]["meta"]["group"])
        self.assertEqual((recs["S4"]["author"], recs["S4"]["text"]), ("Cal Rowan", "[photo] Look at these"))
        self.assertEqual(recs["S4"]["meta"]["attachment"], "Media/120363000000000001@g.us/a/b/leeks.jpg")
        self.assertEqual(recs["S5"]["kind"], "event")
        self.assertEqual(recs["S3"]["kind"], "message", "ZGROUPEVENTTYPE alone isn't an event")
        self.assertEqual((recs["S7"]["text"], recs["S7"]["meta"]["tier"]), ("[deleted message]", "deleted"))
        self.assertEqual(manifest(self.corpus, "whatsapp")["notes"], {"others_status_updates": 1})

    def test_replies_and_reactions_and_ones_taken_back(self):
        T = self.T
        rows = [(1, 2, 0, T, "Who has the shed key?", "S1", 0, 1, 2, "120363000000000001@g.us", None, 0),
                (2, 2, 1, T + 60, "I do", "S2", 0, None, 2, None, "120363000000000001@g.us", 0),
                (3, 2, 0, T + 120, "Thanks!", "S3", 0, 2, 2, "120363000000000001@g.us", None, 0)]
        reaction = lambda rid, jid, emoji, ms: (1, pb((1, rid), *([(2, jid)] if jid else [(6, 1)]), *([(3, emoji)] if emoji else []), (4, ms)))
        info = [(1, pb((7, pb(reaction("R1", "15550002222@s.whatsapp.net", "👍", 1758307300000),
                               reaction("R2", None, "❤️", 1758307310000),
                               # Dee's ❤️, then taken back (an entry with no emoji, newer)
                               reaction("R3", "77000000000003@lid", "❤️", 1758307320000),
                               reaction("R4", "77000000000003@lid", None, 1758307330000)))))]
        # S2 quotes S1 (its stanza id, and what it said); S3 quotes a message this copy doesn't have
        link = pb((6, pb((1, "see https://allotment.example"))))  # a link's message: its text in 6.1
        media = [(1, 2, None, None, None, None, None, None, pb((5, "S1"), (6, "15550002222@s.whatsapp.net"), (19, pb((1, "Who has the shed key?"))))),
                 (2, 3, None, None, None, None, None, None, pb((5, "GONE"), (19, link)))]
        chat_storage(self.home / "Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite", rows,
                     self.CHATS, self.MEMBERS, push=[(1, "77000000000003@lid", "Dee")], media=media, info=info)
        recs = {r["id"]: r for r in (run(self.home, self.corpus, "whatsapp") or records(self.corpus, "whatsapp"))}
        self.assertEqual(recs["S1"]["meta"]["reactions"], [{"who": "Cal Rowan", "reaction": "👍", "ts": "2025-09-19T18:41:40Z"},
                                                           {"who": "me", "reaction": "❤️", "ts": "2025-09-19T18:41:50Z"}])
        self.assertEqual(recs["S1"]["meta"]["reactions_taken_back"], [{"who": "Dee", "ts": "2025-09-19T18:42:10Z"}],
                         "a reaction taken back isn't one, and who took it back is kept")
        self.assertEqual((recs["S2"]["meta"]["reply_to"], recs["S2"]["meta"]["reply_text"]), ("S1", "Who has the shed key?"))
        self.assertEqual((recs["S3"]["meta"]["reply_to"], recs["S3"]["meta"]["reply_text"]), ("GONE", "see https://allotment.example"),
                         "a quote of a message not here: what it said, from the quote")

    def test_the_iphone_backups_reactions_and_replies_for_phone_whatsapp(self):
        T = self.T
        rows = [(1, 2, 0, T, "Who has the shed key?", "S1", 0, 1, 2, "120363000000000001@g.us", None, 0),
                (2, 2, 1, T + 60, "I do", "S2", 0, None, 2, None, "120363000000000001@g.us", 0)]
        info = [(1, pb((7, pb((1, pb((1, "R1"), (6, 1), (3, "🙏"), (4, 1758307300000)))))))]
        media = [(1, 2, None, None, None, None, None, None, pb((5, "S1"), (19, pb((1, "Who has the shed key?")))))]
        chat_storage(self.corpus / "raw/iphone/files/AppDomainGroup-group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite",
                     rows, self.CHATS, self.MEMBERS, media=media, info=info)
        r = subprocess.run([sys.executable, "-c", "import json, whatsapp; print(json.dumps({'|'.join(k): v for k, v in whatsapp.phone_extras().items()}))"],
                           cwd=CONNECTORS, env={**os.environ, "HOME": str(self.home), "CORPUS_DIR": str(self.corpus)},
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        jid = "120363000000000001@g.us"
        self.assertEqual(got[f"{jid}|Who has the shed key?"], [[T + 978307200, {"reactions": [{"who": "me", "reaction": "🙏", "ts": "2025-09-19T18:41:40Z"}]}]])
        self.assertEqual(got[f"{jid}|I do"], [[T + 60 + 978307200, {"reply_text": "Who has the shed key?"}]])

    def test_messages_the_iphone_backup_has_are_counted_there(self):
        self.mac(self.ROWS[:3])
        phone = self.corpus / "raw/iphone/files/AppDomainGroup-group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite"
        chat_storage(phone, self.ROWS[:3], self.CHATS[:2])
        # Before the backup's WhatsApp is brought in, the Mac keeps all three.
        run(self.home, self.corpus, "whatsapp")
        self.assertEqual(len(records(self.corpus, "whatsapp")), 3)
        (self.corpus / "manifest.json").write_text(json.dumps({**json.loads((self.corpus / "manifest.json").read_text()),
                                                               "phone_whatsapp": {"count": 2, "kinds": {"message": 2},
                                                                                  "last": "2025-09-19T18:41:00Z"}}))
        run(self.home, self.corpus, "whatsapp")
        # S3 is in a backup decrypted since, newer than anything phone_whatsapp has: kept here until it is.
        self.assertEqual([r["id"] for r in records(self.corpus, "whatsapp")], ["S3"], "and an earlier run's copies go too")
        self.assertEqual(manifest(self.corpus, "whatsapp")["notes"], {"in_the_iphone_backup": 2})


def maps_sync(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript("""
        create table Z_PRIMARYKEY (Z_ENT int, Z_NAME text, Z_SUPER int, Z_MAX int);
        create table ZHISTORYITEM (Z_PK integer primary key, Z_ENT int, ZCREATETIME real, ZMODIFICATIONTIME real,
            ZQUERY text, ZLOCATIONDISPLAY text, ZLATITUDE real, ZLONGITUDE real, ZMAPITEM int, ZMAPITEMSTORAGE blob,
            ZSTARTWAYPOINT blob, ZENDWAYPOINT blob, ZROUTEREQUESTSTORAGE blob, ZCUSTOMNAME text, ZNAVIGATIONINTERRUPTED int);
        create table ZMIXINMAPITEM (Z_PK integer primary key, ZMAPITEMSTORAGE blob);
        create table ZFAVORITEITEM (Z_PK integer primary key, ZCREATETIME real, ZCUSTOMNAME text, ZMAPITEMNAME text,
            ZMAPITEMADDRESS text, ZMAPITEMCATEGORY text, ZTYPE int, ZLATITUDE real, ZLONGITUDE real, ZHIDDEN int);
        create table ZCOLLECTION (Z_PK integer primary key, ZTITLE text, ZCOLLECTIONDESCRIPTION text, ZCREATETIME real,
            ZPLACESCOUNT int);
        create table ZCOLLECTIONITEM (Z_PK integer primary key, ZCREATETIME real, ZCUSTOMNAME text, ZMAPITEMNAME text,
            ZMAPITEMADDRESS text, ZMAPITEMCATEGORY text, ZPLACEITEMNOTE text, ZLATITUDE real, ZLONGITUDE real);
        create table Z_6PLACES (Z_6COLLECTIONS int, Z_7PLACES int);
        create table ZVISITEDLOCATION (Z_PK integer primary key, ZMAPITEMNAME text, ZMAPITEMADDRESS text, ZMAPITEMCITY text,
            ZMAPITEMCATEGORY text, ZLATITUDE real, ZLONGITUDE real);
        create table ZVISIT (Z_PK integer primary key, ZSTARTDATE real, ZHIDDEN int, ZLOCATION int);
        create table ZREVIEWEDPLACE (Z_PK integer primary key, ZCREATETIME real, ZMODIFICATIONTIME real, ZRATING int,
            ZHASUSERREVIEWED int, ZUPLOADEDPHOTOSCOUNT int, ZLASTSUGGESTEDREVIEWDATE real, ZLATITUDE real, ZLONGITUDE real,
            ZMAPITEMSTORAGE blob);
        insert into Z_PRIMARYKEY values (16, 'HistoryDirectionsItem', 14, 0), (20, 'HistoryPlaceItem', 14, 0),
            (22, 'HistorySearchItem', 14, 0);
    """)
    t = 780000000
    con.executemany("insert into ZHISTORYITEM (Z_PK, Z_ENT, ZCREATETIME, ZQUERY, ZLOCATIONDISPLAY, ZMAPITEM, ZSTARTWAYPOINT, "
                    "ZENDWAYPOINT, ZLATITUDE, ZLONGITUDE) values (?,?,?,?,?,?,?,?,?,?)", [
                        (1, 22, t, "ferry timetable", "Oban", None, None, None, None, None),
                        (2, 22, t + 1, "bakery", None, None, None, None, None, None),
                        (3, 16, t + 2, None, None, None, place_blob("Home"), place_blob("Seal Cove Harbour", "1 Quay Rd"), None, None),
                        (4, 20, t + 3, None, None, 1, None, None, 56.41, -5.47)])
    con.execute("insert into ZMIXINMAPITEM values (1, ?)", (place_blob("Kelp & Co", "2 Shore St", "Oban"),))
    con.execute("insert into ZFAVORITEITEM values (1, ?, 'Allotment', 'Plot 14', 'Hill Rd', 'Garden', 4, 56.4, -5.4, 0)", (t,))
    con.execute("insert into ZCOLLECTION values (1, 'Islands to see', 'Next summer', ?, 1)", (t,))
    con.execute("insert into ZCOLLECTIONITEM values (7, ?, null, 'Isle of Kerrera', 'Kerrera', 'Island', 'Take the small ferry', 56.39, -5.53)", (t,))
    con.execute("insert into Z_6PLACES values (1, 7)")
    con.execute("insert into ZVISITEDLOCATION values (1, 'Harbour Cafe', '3 Quay Rd', 'Oban', 'Cafe', 56.41, -5.47)")
    con.execute("insert into ZVISIT values (1, ?, 0, 1)", (t + 86400,))
    con.execute("insert into ZREVIEWEDPLACE values (1, ?, ?, 1, 0, 2, null, 56.41, -5.47, ?)", (t, t + 10, place_blob("The Chip Shop", "4 Pier Rd")))
    con.execute("insert into ZREVIEWEDPLACE values (2, ?, ?, 0, null, 0, ?, 56.4, -5.4, ?)", (t, t, t + 50, place_blob("Ferry Terminal")))
    con.execute("insert into ZFAVORITEITEM (Z_PK, ZCREATETIME, ZTYPE, ZHIDDEN) values (2, ?, 3, 0)", (t,))  # never filled in
    con.commit()
    con.close()


class AppleMapsTests(Base):
    def test_searches_directions_places_guides_visits_and_ratings(self):
        maps_sync(self.home / "Library/Containers/com.apple.Maps/Data/Maps/MapsSync_0.0.1")
        # The iPhone backup's Maps (iLEAPP's mapsSync) already has the bakery search.
        norm = self.corpus / "normalized"
        norm.mkdir()
        (norm / "phone_mapssync.jsonl").write_text(json.dumps({"id": "mapsSync:x", "source": "phone_mapssync", "kind": "record",
                                                               "meta": {"fields": {"Timestamp": "2025-09-19T18:40:01Z", "Location Search": "bakery"}}}) + "\n")
        run(self.home, self.corpus, "apple_maps")
        recs = {r["id"]: r for r in records(self.corpus, "apple_maps")}
        self.assertNotIn("recent:2", recs)
        self.assertEqual(manifest(self.corpus, "apple_maps")["notes"], {"in_the_iphone_backup": 1, "empty_favorites": 1})
        self.assertEqual((recs["recent:1"]["kind"], recs["recent:1"]["text"]), ("search", "Searched Maps for ferry timetable near Oban"))
        self.assertEqual((recs["recent:3"]["kind"], recs["recent:3"]["text"]), ("directions", "Directions to Seal Cove Harbour from Home"))
        self.assertEqual(recs["recent:4"]["text"], "Looked at Kelp & Co, 2 Shore St, Oban in Maps")
        self.assertEqual(recs["recent:4"]["meta"]["lat"], 56.41)
        self.assertEqual(recs["favorite:1"]["text"], "Favorite in Maps: Plot 14, Hill Rd (Garden) (you call it Allotment)")
        self.assertEqual(recs["guide:1"]["text"], "Your guide in Maps: Islands to see\nNext summer")
        self.assertEqual((recs["guide_place:7"]["thread_name"], recs["guide_place:7"]["text"]),
                         ("Islands to see", "Saved in Maps to Islands to see: Isle of Kerrera, Kerrera (Island)\nYour note: Take the small ferry"))
        self.assertEqual((recs["visit:1"]["kind"], recs["visit:1"]["text"]), ("place_visit", "Visited Harbour Cafe, 3 Quay Rd (Cafe)"))
        self.assertEqual(recs["visit:1"]["ts"], "2025-09-20T18:40:00Z")
        self.assertEqual(recs["rating:1"]["text"], "Rated The Chip Shop, 4 Pier Rd in Maps, and added 2 photos")
        self.assertEqual(recs["rating:1"]["meta"]["rating"], 1)
        asked = recs["rating:2"]
        self.assertEqual((asked["kind"], asked["text"], asked["author"], asked["is_me"]),
                         ("rating_asked", "Maps asked you to rate Ferry Terminal", "Maps", False), "asked, not rated")
        self.assertEqual(asked["ts"], "2025-09-19T18:40:50Z")


class BooksTests(Base):
    def test_library_finished_books_and_highlights(self):
        docs = self.home / "Library/Containers/com.apple.iBooksX/Data/Documents"
        (docs / "BKLibrary").mkdir(parents=True)
        (docs / "AEAnnotation").mkdir()
        con = sqlite3.connect(docs / "BKLibrary/BKLibrary-1-091020131601.sqlite")
        con.execute("create table ZBKLIBRARYASSET (Z_PK integer primary key, ZASSETID text, ZTITLE text, ZAUTHOR text, "
                    "ZGENRE text, ZREADINGPROGRESS real, ZDATEFINISHED real, ZISFINISHED int, ZLASTOPENDATE real, "
                    "ZCREATIONDATE real, ZPURCHASEDATE real, ZISSAMPLE int)")
        con.executemany("insert into ZBKLIBRARYASSET values (?,?,?,?,?,?,?,?,?,?,?,?)", [
            (1, "B1", "The Tidal Year", "M. Fenwick", "Nature", 1.0, 780000000, 1, 780000000, 700000000, None, 0),
            (2, "B2", "Knots for Sailors", None, None, 0.42, None, 0, 779000000, 760000000, None, 1)])
        con.commit()
        con.close()
        con = sqlite3.connect(docs / "AEAnnotation/AEAnnotation_v10312011_1727_local.sqlite")
        con.execute("create table ZAEANNOTATION (Z_PK integer primary key, ZANNOTATIONUUID text, ZANNOTATIONASSETID text, "
                    "ZANNOTATIONSELECTEDTEXT text, ZANNOTATIONNOTE text, ZANNOTATIONCREATIONDATE real, "
                    "ZANNOTATIONMODIFICATIONDATE real, ZANNOTATIONDELETED int, ZANNOTATIONSTYLE int, ZFUTUREPROOFING5 text)")
        con.executemany("insert into ZAEANNOTATION values (?,?,?,?,?,?,?,?,?,?)", [
            ("1", "H1", "B1", "The sea keeps its own calendar.", "Use this in the talk", 770000000, 770000100, 0, 3, "Spring tides"),
            ("2", "H2", "B1", "An old line I took back.", None, 770000200, None, 1, 1, None),
            ("3", "H3", "B2", None, None, 770000300, None, 0, 0, None)])  # a bookmark
        con.commit()
        con.close()
        run(self.home, self.corpus, "books")
        recs = {r["id"]: r for r in records(self.corpus, "books")}
        self.assertEqual(recs["book:B1"]["text"], "The Tidal Year by M. Fenwick, in your Books library: finished")
        self.assertEqual(recs["book:B2"]["text"], "Knots for Sailors, in your Books library: 42% read (a sample)")
        self.assertEqual((recs["finished:B1"]["kind"], recs["finished:B1"]["ts"]), ("read", "2025-09-19T18:40:00Z"))
        h = recs["H1"]
        self.assertEqual((h["kind"], h["title"], h["thread"]), ("highlight", "The Tidal Year", "B1"))
        self.assertEqual(h["text"], "“The sea keeps its own calendar.”\nYour note: Use this in the talk")
        self.assertEqual((h["meta"]["chapter"], h["meta"]["book_author"]), ("Spring tides", "M. Fenwick"))
        self.assertEqual(recs["H2"]["meta"]["tier"], "deleted", "a highlight taken back is kept, marked")
        self.assertNotIn("H3", recs)
        self.assertEqual(manifest(self.corpus, "books")["notes"], {"bookmarks_and_places": 1})


if __name__ == "__main__":
    unittest.main()
