"""The Mac's own sources in every shape they come in, on made-up databases and files: older and newer macOS schemas,
tables or columns missing, empty or locked databases, odd encodings and times. Each is read, or at least never stops
the run, and nothing is lost without the manifest saying so.

Run: python3 -m unittest discover -s connectors/tests -p 'test_*.py'
"""
import datetime as dt
import gzip
import json
import os
import plistlib
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import types
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

CONNECTORS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONNECTORS))
import imessage  # noqa: E402

APPLE = dt.datetime(2001, 1, 1, tzinfo=dt.timezone.utc)
WEBKIT = 11644473600  # 1601-01-01 to 1970-01-01, in seconds


def iso(apple_seconds):
    return (APPLE + dt.timedelta(seconds=apple_seconds)).isoformat().replace("+00:00", "Z")


def wall(*args):
    """A wall-clock time as Calendar keeps a floating one: seconds since 2001-01-01, in no zone."""
    return (dt.datetime(*args) - dt.datetime(2001, 1, 1)).total_seconds()


def make_db(path, script="", rows=()):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(script)
    for sql, params in rows:
        con.execute(sql, params)
    con.commit()
    con.close()
    return path


class Home(unittest.TestCase):
    """A made-up home folder and corpus; each connector runs on its own, as the app runs it."""

    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.home, self.corpus = Path(t.name) / "home", Path(t.name) / "corpus"
        self.home.mkdir()
        self.corpus.mkdir()
        (self.corpus / "identity.json").write_text('{"names":["Ada"],"emails":["ada@example.test"],"usernames":[],"phones":[]}')

    def lib(self, rel):
        p = self.home / "Library" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def run_module(self, module, **env):
        e = {**os.environ, "HOME": str(self.home), "CORPUS_DIR": str(self.corpus), **env}
        r = subprocess.run([sys.executable, "-c", f"import {module}; {module}.main()"], cwd=CONNECTORS, env=e,
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-3000:])
        return r

    def records(self, source):
        f = self.corpus / "normalized" / f"{source}.jsonl"
        return {x["id"]: x for x in map(json.loads, f.read_text().splitlines())} if f.exists() else {}

    def notes(self, source):
        return json.loads((self.corpus / "manifest.json").read_text()).get(source, {}).get("notes", {})


# ---------------------------------------------------------------- Messages

def typedstream(text, mutable=False):
    """message.attributedBody as Messages writes it: an NSAttributedString in Apple's typedstream, its string's length
    in one byte, or 0x81 and two bytes, or 0x82 and four."""
    s = text.encode()
    n = len(s)
    size = bytes([n]) if n < 0x80 else b"\x81" + n.to_bytes(2, "little") if n < 0x8000 else b"\x82" + n.to_bytes(4, "little")
    string = (b"\x84\x84\x84\x0fNSMutableString\x01\x84\x84\x08NSString\x01\x95\x84\x01+" if mutable
              else b"\x84\x84\x84\x08NSString\x01\x94\x84\x01+")
    return (b"\x04\x0bstreamtyped\x81\xe8\x03\x84\x01@\x84\x84\x84" + (b"\x19NSMutableAttributedString\x00\x84\x84" if mutable else b"")
            + b"\x12NSAttributedString\x00\x84\x84\x08NSObject\x00\x85\x92" + string + size + s
            + b"\x86\x84\x02iI\x01\x01\x92\x84\x84\x84\x0cNSDictionary\x00\x94\x84\x01i\x01\x92\x84\x96\x96\x1d"
            b"__kIMMessagePartAttributeName\x86\x92\x84\x84\x84\x08NSNumber\x00\x84\x84\x07NSValue\x00\x94\x84\x01*\x84\x99\x99\x00\x86\x86\x86")


MESSAGES = """
create table handle (ROWID integer primary key, id text, service text);
create table chat (ROWID integer primary key, guid text, style int, display_name text, chat_identifier text, service_name text, is_filtered int);
create table chat_handle_join (chat_id int, handle_id int);
create table chat_message_join (chat_id int, message_id int, message_date int);
create table attachment (ROWID integer primary key, guid text, filename text, mime_type text, transfer_name text, total_bytes int);
create table message_attachment_join (message_id int, attachment_id int);
create table message (ROWID integer primary key, guid text, text text, attributedBody blob, handle_id int, service text,
  is_from_me int, date int, date_read int, date_delivered int, item_type int, other_handle int, group_title text,
  group_action_type int, associated_message_guid text, associated_message_type int, associated_message_emoji text,
  balloon_bundle_id text, expressive_send_style_id text, thread_originator_guid text, thread_originator_part text,
  is_audio_message int, subject text, date_edited int, date_retracted int, message_summary_info blob, is_empty int);
"""
# macOS 10.12 and before (and an old iPhone's sms.db): none of the columns added since, times in seconds.
MESSAGES_OLD = """
create table handle (ROWID integer primary key, id text);
create table chat (ROWID integer primary key, guid text, style int, display_name text, chat_identifier text);
create table chat_handle_join (chat_id int, handle_id int);
create table chat_message_join (chat_id int, message_id int);
create table attachment (ROWID integer primary key, filename text, mime_type text, transfer_name text, total_bytes int);
create table message_attachment_join (message_id int, attachment_id int);
create table message (ROWID integer primary key, guid text, text text, handle_id int, service text, is_from_me int, date int);
"""
NAMES = types.SimpleNamespace(label=lambda x: {"+15550100": "Grace", "alan@example.test": "Alan"}.get(x, x))
NS = 10**9


class MessagesTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        p = patch.dict(os.environ, {"HOME": t.name})  # an attachment's ~/Library path is looked for here
        p.start()
        self.addCleanup(p.stop)

    def chat_db(self, schema=MESSAGES):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.executescript(schema)
        con.executescript("""
            insert into handle (ROWID, id) values (1, '+15550100'), (2, 'alan@example.test');
            insert into chat (ROWID, guid, style, display_name, chat_identifier) values (1, 'chat-grace', 45, null, '+15550100'),
                (2, 'chat-group', 43, null, 'chat123456');
            insert into chat_handle_join values (1, 1), (2, 1), (2, 2);
        """)
        self.addCleanup(con.close)
        return con

    def add(self, con, rowid, guid, chat=1, **cols):
        row = {"guid": guid, "handle_id": 1, "is_from_me": 0, "date": 700000000 * NS, "service": "iMessage", "item_type": 0,
               "associated_message_type": 0, **cols}
        con.execute(f"insert into message (ROWID, {', '.join(row)}) values (?, {', '.join('?' * len(row))})", (rowid, *row.values()))
        con.execute("insert into chat_message_join (chat_id, message_id) values (?, ?)", (chat, rowid))

    def read(self, con):
        return {r["id"]: r for r in imessage.messages(con, NAMES, "mac")}

    def test_bodies_only_in_attributed_body_of_every_length(self):
        con = self.chat_db()
        long_ = "é" * 200  # 400 bytes: the length in 0x81 and two bytes
        huge = "words " * 12000  # 72,000 bytes: 0x82 and four
        self.add(con, 1, "short", text=None, attributedBody=typedstream("See you at 6"))
        self.add(con, 2, "long", text=None, attributedBody=typedstream(long_))
        self.add(con, 3, "huge", text=None, attributedBody=typedstream(huge))
        self.add(con, 4, "mutable", text=None, attributedBody=typedstream("Sent from the Mac", mutable=True))
        self.add(con, 5, "both", text="The text column", attributedBody=typedstream("The body"))
        cut = typedstream("Cut short")
        self.add(con, 6, "cut", text=None, attributedBody=cut[:cut.index(b"+") + 1])  # ends where its length would be
        got = self.read(con)
        self.assertEqual(got["short"]["text"], "See you at 6")
        self.assertEqual(got["long"]["text"], long_)
        self.assertEqual(got["huge"]["text"], huge.strip())
        self.assertEqual(got["mutable"]["text"], "Sent from the Mac")
        self.assertEqual(got["both"]["text"], "The text column")
        self.assertIn("cut", got, "a body cut short is a message without its text, not a stopped run")

    def test_apple_time_in_seconds_and_in_nanoseconds(self):
        old = self.chat_db(MESSAGES_OLD)
        old.execute("insert into message values (1, 'old', 'From 2016', 1, 'SMS', 0, 500000000)")
        old.execute("insert into chat_message_join values (1, 1)")
        new = self.chat_db()
        self.add(new, 1, "new", text="From 2016 too", date=500000000 * NS)
        self.assertEqual(self.read(old)["old"]["ts"], iso(500000000), "macOS 10.12 and before: seconds")
        self.assertEqual(self.read(new)["new"]["ts"], iso(500000000), "macOS 10.13 on: nanoseconds")

    def test_an_old_database_without_the_newer_columns(self):
        con = self.chat_db(MESSAGES_OLD)
        con.execute("insert into message values (1, 'old-1', 'Hi', 1, 'iMessage', 1, 500000000)")
        con.execute("insert into message values (2, 'old-2', 'Hello back', 1, 'iMessage', 0, 500000060)")
        con.execute("insert into chat_message_join values (1, 1), (1, 2)")
        got = self.read(con)
        self.assertEqual((got["old-1"]["text"], got["old-1"]["author"], got["old-2"]["author"]), ("Hi", "me", "Grace"))
        self.assertEqual(got["old-2"]["kind"], "message")

    def test_an_edited_message_keeps_what_it_said_before(self):
        con = self.chat_db()
        info = plistlib.dumps({"otr": {"0": {"le": 12, "lo": 0}}, "ep": [0], "ec": {"0": [
            {"d": 690513474, "t": typedstream("See you at 5"), "bcg": "m1"},
            {"d": 690513480, "t": typedstream("See you at 6")}]}}, fmt=plistlib.FMT_BINARY)
        self.add(con, 1, "m1", text=None, attributedBody=typedstream("See you at 6"), date_edited=690513480 * NS, message_summary_info=info)
        self.add(con, 2, "m2", text=None, attributedBody=None, date_edited=690513480 * NS, message_summary_info=info)  # body only in its history
        got = self.read(con)
        self.assertEqual(got["m1"]["text"], "See you at 6")
        self.assertEqual(got["m1"]["meta"]["edited"], iso(690513480))
        self.assertEqual(got["m1"]["meta"]["edits"], [{"at": iso(690513474), "text": "See you at 5"}])
        self.assertEqual(got["m2"]["text"], "See you at 6", "no body but its last version")

    def test_an_unsent_message_says_so(self):
        con = self.chat_db()
        gone = plistlib.dumps({"otr": {"0": {"le": 5, "lo": 0}}, "rp": [0], "amc": 0, "ust": True}, fmt=plistlib.FMT_BINARY)
        # macOS 15 and on: an unsend is an edit to nothing (date_edited, rp), date_retracted left at 0.
        self.add(con, 1, "sequoia", text=None, attributedBody=None, date_edited=700000100 * NS, date_retracted=0,
                 message_summary_info=gone, is_empty=1)
        # macOS 13 and 14: date_retracted.
        self.add(con, 2, "ventura", text=None, attributedBody=None, date_retracted=700000200 * NS, message_summary_info=gone)
        # Edited, then unsent: what it said is gone as its sender meant, history and all.
        both = plistlib.dumps({"otr": {"0": {"le": 6, "lo": 0}}, "rp": [0], "ec": {"0": [
            {"d": 700000000, "t": typedstream("secret")}, {"d": 700000050, "t": typedstream("secret!")}]}}, fmt=plistlib.FMT_BINARY)
        self.add(con, 3, "edited-then-unsent", text=None, attributedBody=None, date_edited=700000300 * NS, message_summary_info=both)
        # Two parts, a photo and a line; the line unsent, the photo still there.
        part = plistlib.dumps({"otr": {"0": {"le": 1, "lo": 0}, "1": {"le": 4, "lo": 1}}, "rp": [1]}, fmt=plistlib.FMT_BINARY)
        con.execute("insert into attachment values (1, 'at1', null, 'image/jpeg', 'IMG_2.JPG', 10)")
        self.add(con, 4, "partly", text=None, attributedBody=typedstream("\ufffc"), date_edited=700000400 * NS, message_summary_info=part)
        con.execute("insert into message_attachment_join values (4, 1)")
        got = self.read(con)
        self.assertEqual(got["sequoia"]["meta"]["unsent"], iso(700000100))
        self.assertNotIn("edited", got["sequoia"]["meta"], "unsent, not edited")
        self.assertEqual(got["sequoia"]["text"], "[unsent message]")
        self.assertEqual(got["ventura"]["meta"]["unsent"], iso(700000200))
        third = got["edited-then-unsent"]
        self.assertEqual((third["text"], third["meta"]["unsent"]), ("[unsent message]", iso(700000300)))
        self.assertNotIn("edits", third["meta"])
        partly = got["partly"]
        self.assertEqual((partly["text"], partly["meta"]["unsent_parts"]), ("[attachment: IMG_2.JPG (image/jpeg)]", 1))
        self.assertNotIn("unsent", partly["meta"])

    def test_tapbacks_stickers_and_taking_them_back(self):
        con = self.chat_db()
        self.add(con, 1, "m1", text="See you at 6", is_from_me=1)
        self.add(con, 2, "loved", text="Loved “See you at 6”", associated_message_type=2000, associated_message_guid="p:0/m1")
        self.add(con, 3, "liked", text="Liked “See you at 6”", associated_message_type=2001, associated_message_guid="bp:m1")
        self.add(con, 4, "unliked", text="Removed a like from “See you at 6”", associated_message_type=3001, associated_message_guid="p:0/m1")
        self.add(con, 5, "emoji", text="Reacted 🎉 to “See you at 6”", associated_message_type=2006, associated_message_guid="p:0/m1",
                 associated_message_emoji="🎉")
        self.add(con, 6, "sticker", text=None, associated_message_type=1000, associated_message_guid="p:0/m1")  # placed on it (iOS 10-16)
        got = self.read(con)
        for guid, said in (("loved", "loved"), ("liked", "liked"), ("unliked", "removed liked"), ("emoji", "reacted to"), ("sticker", "stickered")):
            with self.subTest(guid):
                self.assertEqual((got[guid]["kind"], got[guid]["meta"]["reaction"]), ("reaction", said))
                self.assertEqual(got[guid]["meta"]["reacts_to"], "m1", "the message's own guid, which is its record's id")
        self.assertEqual(got["m1"]["kind"], "message")

    def test_tapbacks_as_they_stand(self):
        con = self.chat_db()
        self.add(con, 1, "m1", text="See you at 6", is_from_me=1)
        self.add(con, 2, "loved", text="Loved “See you at 6”", associated_message_type=2000, associated_message_guid="p:0/m1")
        self.add(con, 3, "liked", text="Liked “See you at 6”", associated_message_type=2001, associated_message_guid="bp:m1")
        self.add(con, 4, "unliked", text="Removed a like from “See you at 6”", associated_message_type=3001, associated_message_guid="p:0/m1")
        self.add(con, 5, "emoji", text="Reacted 🎉 to “See you at 6”", associated_message_type=2006, associated_message_guid="re:m1",
                 associated_message_emoji="🎉")
        self.add(con, 6, "sticker", text=None, associated_message_type=1000, associated_message_guid="p:0/m1")
        self.add(con, 7, "gone", text="Loved “a deleted message”", associated_message_type=2000, associated_message_guid="p:0/deleted")
        self.add(con, 8, "sms", text="Liked “See you at 6”", service="SMS", handle_id=2)  # a phone that isn't Apple's: the tapback as text
        recs = list(imessage.messages(con, NAMES, "mac"))
        imessage.settle(recs)
        got = {r["id"]: r for r in recs}
        m = got["m1"]["meta"]
        self.assertEqual([x["reaction"] for x in m["reactions"]], ["🎉", "sticker", "👍"],
                         "each person's newest tapback, a sticker beside it, and the text one from another phone")
        self.assertTrue(got["loved"]["meta"]["withdrawn"] and got["liked"]["meta"]["withdrawn"], "replaced, then taken back")
        self.assertEqual(got["unliked"]["meta"]["cancels"], "liked")
        self.assertNotIn("withdrawn", got["emoji"]["meta"])
        self.assertTrue(got["emoji"]["meta"]["on_message"], "re:<guid> is the message too")
        self.assertEqual((got["sms"]["kind"], got["sms"]["meta"]["reacts_to"], got["sms"]["meta"]["text_tapback"]), ("reaction", "m1", True))
        self.assertTrue(got["gone"]["meta"]["target_gone"])
        self.assertNotIn("on_message", got["gone"]["meta"], "one on a message deleted since stays a line of its own")

    def test_a_reply_quotes_the_part_it_answers(self):
        con = self.chat_db()
        self.add(con, 1, "long", text="Dinner Friday? Also, can you bring the projector", is_from_me=1)
        self.add(con, 2, "r1", text="Yes to dinner", handle_id=2, thread_originator_guid="long", thread_originator_part="0:0:14")
        self.add(con, 3, "r2", text="Sure", handle_id=2, thread_originator_guid="long", thread_originator_part="0:0:99")
        got = self.read(con)
        self.assertEqual(got["r1"]["meta"]["reply_text"], "Dinner Friday?")
        self.assertEqual(got["r2"]["meta"]["reply_text"], "Dinner Friday? Also, can you bring the projector", "a range past it: the whole")

    def test_replies_group_chats_and_sms_imessage_rcs(self):
        con = self.chat_db()
        self.add(con, 1, "g1", chat=2, text="Who's in?", is_from_me=1)
        self.add(con, 2, "g2", chat=2, text="Me", handle_id=2, thread_originator_guid="g1", thread_originator_part="0:0:9")
        self.add(con, 3, "sms", text="By text", service="SMS")
        self.add(con, 4, "rcs", text="Over RCS", service="RCS")
        got = self.read(con)
        self.assertEqual(got["g2"]["meta"]["reply_to"], "g1")
        self.assertEqual((got["g1"]["meta"]["group"], got["g1"]["thread_name"], got["g1"]["participants"]), (True, "Alan, Grace", ["Alan", "Grace"]))
        self.assertEqual(got["g2"]["author"], "Alan")
        self.assertEqual([got[g]["meta"]["service"] for g in ("g1", "sms", "rcs")], ["iMessage", "SMS", "RCS"])

    def test_attachments_with_and_without_their_names(self):
        con = self.chat_db()
        home = Path(os.environ["HOME"])
        photo = home / "Library/Messages/Attachments/ab/01/IMG_1.HEIC"
        photo.parent.mkdir(parents=True)
        photo.write_bytes(b"heic")
        con.execute("insert into attachment values (1, 'at1', '~/Library/Messages/Attachments/ab/01/IMG_1.HEIC', 'image/heic', 'IMG_1.HEIC', 4)")
        con.execute("insert into attachment values (2, 'at2', null, null, null, null)")
        self.add(con, 1, "pics", text=None, attributedBody=typedstream("￼￼"))
        con.execute("insert into message_attachment_join values (1, 1), (1, 2)")
        got = self.read(con)["pics"]
        self.assertEqual(got["text"], "[attachment: IMG_1.HEIC (image/heic)]\n[attachment: file (?)]")
        self.assertEqual(got["meta"]["files"], [str(photo)])


# ---------------------------------------------------------------- Phone and FaceTime calls

CALLS = """
create table ZCALLRECORD (Z_PK integer primary key, Z_ENT int, ZANSWERED int, ZCALLTYPE int, ZORIGINATED int, ZREAD int,
  ZDATE real, ZDURATION real, ZADDRESS varchar, ZNAME varchar, ZLOCATION varchar, ZSERVICE_PROVIDER varchar, ZUNIQUE_ID varchar,
  ZISO_COUNTRY_CODE varchar, ZDISCONNECTED_CAUSE int);
create table ZHANDLE (Z_PK integer primary key, ZTYPE int, ZVALUE varchar, ZNORMALIZEDVALUE varchar);
create table Z_2REMOTEPARTICIPANTHANDLES (Z_2REMOTEPARTICIPANTCALLS int, Z_4REMOTEPARTICIPANTHANDLES int);
"""


class CallsTests(Home):
    def store(self, script=CALLS, rows=()):
        return make_db(self.lib("Application Support/CallHistoryDB/CallHistory.storedata"), script, rows)

    def call(self, pk, uid, calltype, out, answered, seconds, address, name=None, provider="com.apple.Telephony", when=None):
        return ("insert into ZCALLRECORD (Z_PK, ZUNIQUE_ID, ZCALLTYPE, ZORIGINATED, ZANSWERED, ZDURATION, ZADDRESS, ZNAME, "
                "ZSERVICE_PROVIDER, ZDATE) values (?,?,?,?,?,?,?,?,?,?)",
                (pk, uid, calltype, out, answered, seconds, address, name, provider, when or 700000000 + pk * 3600))

    def test_phone_and_facetime_audio_and_video_missed_and_how_long(self):
        self.store(rows=[self.call(1, "phone", 1, 1, 1, 125, "+15555550100", "Grace"),
                         self.call(2, "video", 8, 0, 1, 600, "grace@example.test", provider="com.apple.FaceTime"),
                         self.call(3, "missed-audio", 16, 0, 0, 0, "+15555550100", "Grace", provider="com.apple.FaceTime"),
                         self.call(4, "whatsapp", 0, 1, 1, 60, "+15555550142", "Alan", provider="net.whatsapp.WhatsApp")])
        self.run_module("calls")
        got = self.records("calls")
        self.assertEqual(got["phone"]["text"], "outgoing phone call with Grace, 2.1 min")
        self.assertEqual(got["video"]["text"], "incoming facetime video call with grace@example.test, 10.0 min")
        self.assertEqual((got["missed-audio"]["text"], got["missed-audio"]["meta"]["direction"]),
                         ("missed facetime audio call with Grace, 0.0 min", "missed"))
        self.assertEqual(got["phone"]["ts"], iso(700003600))
        self.assertEqual(got["whatsapp"]["text"], "outgoing WhatsApp call with Alan, 1.0 min", "an app's call, not a 'call call'")
        self.assertEqual((got["whatsapp"]["meta"]["type"], got["whatsapp"]["meta"]["app"]), ("WhatsApp", "net.whatsapp.WhatsApp"))

    def test_an_address_kept_as_bytes_and_a_call_with_no_caller_id(self):
        self.store(rows=[self.call(1, "blob", 1, 0, 1, 30, b"+15555550199"),
                         self.call(2, "hidden", 1, 0, 1, 30, None)])
        self.run_module("calls")
        got = self.records("calls")
        self.assertEqual((got["blob"]["author"], got["blob"]["meta"]["handle"]), ("+15555550199", "+15555550199"))
        self.assertNotIn("b'", got["blob"]["text"])
        self.assertEqual(got["hidden"]["text"], "incoming phone call with unknown, 0.5 min")

    def test_a_group_facetime_names_everyone_on_it(self):
        self.store(rows=[self.call(1, "group", 8, 1, 1, 900, None, provider="com.apple.FaceTime"),
                         ("insert into ZHANDLE values (?, ?, ?, ?)", (1, 2, "+15555550101", "+15555550101")),
                         ("insert into ZHANDLE values (?, ?, ?, ?)", (2, 3, "alan@example.test", "alan@example.test")),
                         ("insert into ZHANDLE values (?, ?, ?, ?)", (3, 2, "+15555550102", "+15555550102")),
                         ("insert into Z_2REMOTEPARTICIPANTHANDLES values (?, ?)", (1, 1)),
                         ("insert into Z_2REMOTEPARTICIPANTHANDLES values (?, ?)", (1, 2)),
                         ("insert into Z_2REMOTEPARTICIPANTHANDLES values (?, ?)", (1, 3))])
        self.run_module("calls")
        group = self.records("calls")["group"]
        self.assertEqual(group["participants"], ["+15555550101", "+15555550102", "alan@example.test"])
        self.assertNotIn("unknown", group["text"])

    def test_an_older_store_without_the_location_or_provider_columns(self):
        self.store("""create table ZCALLRECORD (Z_PK integer primary key, ZUNIQUE_ID varchar, ZDATE real, ZDURATION real, ZADDRESS varchar,
                        ZNAME varchar, ZORIGINATED int, ZANSWERED int, ZCALLTYPE int)""",
                   [("insert into ZCALLRECORD values (1, 'old', 500000000, 60, '+15555550100', 'Grace', 1, 1, 1)", ())])
        self.run_module("calls")
        self.assertEqual(self.records("calls")["old"]["text"], "outgoing phone call with Grace, 1.0 min")


# ---------------------------------------------------------------- Calendar

CALENDAR = """
create table Store (ROWID integer primary key, type int, name text);
create table Calendar (ROWID integer primary key, title text, store_id int);
create table Identity (ROWID integer primary key, display_name text, address text);
create table Participant (ROWID integer primary key, owner_id int, status int, is_self int, entity_type int, identity_id int, email text);
create table Location (ROWID integer primary key, title text, address text);
create table Recurrence (ROWID integer primary key, owner_id int, frequency int, interval int);
create table CalendarItem (ROWID integer primary key, UUID text, summary text, description text, start_date real, start_tz text,
  end_date real, end_tz text, all_day int, calendar_id int, location_id int, url text, has_recurrences int, status int,
  creation_date real, last_modified real, conference_url text, organizer_id int, self_attendee_id int, entity_type int,
  orig_item_id int, orig_date real);
insert into Store values (1, 1, 'iCloud');
insert into Calendar values (1, 'Home', 1);
"""


class CalendarTests(Home):
    def calendar(self, script=CALENDAR, rows=()):
        return make_db(self.lib("Group Containers/group.com.apple.calendar/Calendar.sqlitedb"), script, rows)

    def item(self, rowid, uid, title, start, end, tz="America/New_York", all_day=0, **more):
        cols = {"ROWID": rowid, "UUID": uid, "summary": title, "start_date": start, "start_tz": tz, "end_date": end, "end_tz": tz,
                "all_day": all_day, "calendar_id": 1, "entity_type": 2, **more}
        return f"insert into CalendarItem ({', '.join(cols)}) values ({', '.join('?' * len(cols))})", tuple(cols.values())

    def test_zoned_floating_and_all_day_times(self):
        self.calendar(rows=[self.item(1, "ZONED", "Call Paris", 700000000, 700003600, "Europe/Paris"),
                            self.item(2, "FLOAT", "Dentist", wall(2024, 6, 1, 10), wall(2024, 6, 1, 10, 30), "_float"),
                            self.item(3, "DAY", "Holiday", wall(2024, 6, 1), wall(2024, 6, 2), "_float", all_day=1)])
        self.run_module("calendar_events", TZ="America/Los_Angeles")
        got = self.records("calendar")
        self.assertEqual((got["ZONED"]["ts"], got["ZONED"]["ts_end"]), (iso(700000000), iso(700003600)))
        self.assertEqual((got["FLOAT"]["ts"], got["FLOAT"]["ts_end"]), ("2024-06-01T17:00:00Z", "2024-06-01T17:30:00Z"),
                         "a floating time is the clock on this Mac (Pacific here)")
        self.assertTrue(got["FLOAT"]["meta"]["floating"])
        self.assertEqual((got["DAY"]["ts"], got["DAY"]["meta"]["all_day"]), ("2024-06-01T00:00:00Z", True), "a whole day keeps its date")

    def test_a_repeating_event_and_an_occurrence_moved_on_its_own(self):
        self.calendar(rows=[self.item(5, "R1", "Standup", 700000000, 700000900, has_recurrences=1),
                            ("insert into Recurrence values (1, 5, 2, 1)", ()),
                            # One week's moved an hour: its own row, which can share the series' UUID.
                            self.item(6, "R1", "Standup (moved)", 700608400, 700609300, orig_item_id=5, orig_date=700604800)])
        self.run_module("calendar_events")
        got = self.records("calendar")
        self.assertEqual(got["R1"]["meta"]["repeats"], "every week")
        moved = [r for k, r in got.items() if k != "R1"]
        self.assertEqual([r["title"] for r in moved], ["Standup (moved)"])
        self.assertEqual(moved[0]["meta"]["occurrence_of"], "R1")

    def test_an_older_calendar_without_identities_or_newer_columns(self):
        self.calendar("""
            create table Store (ROWID integer primary key, type int, name text);
            create table Calendar (ROWID integer primary key, title text, store_id int);
            create table Participant (ROWID integer primary key, owner_id int, status int, entity_type int, email text);
            create table Location (ROWID integer primary key, title text, address text);
            create table Recurrence (ROWID integer primary key, owner_id int, frequency int, interval int);
            create table CalendarItem (ROWID integer primary key, UUID text, summary text, description text, start_date real,
              end_date real, all_day int, calendar_id int, location_id int, url text, has_recurrences int, status int,
              creation_date real, last_modified real, entity_type int);
            insert into Calendar values (1, 'On My Mac', 7);
            insert into Participant values (1, 1, 2, 7, 'mailto:grace@example.test');
            insert into CalendarItem values (1, 'OLD', 'Lunch', null, 500000000, 500003600, 0, 1, null, null, 0, 0, null, null, 2);
        """)
        self.run_module("calendar_events")
        ev = self.records("calendar")["OLD"]
        self.assertEqual((ev["title"], ev["participants"]), ("Lunch", ["grace@example.test"]))
        self.assertEqual(ev["thread_name"], "On My Mac", "a calendar whose account isn't there any more")

    def test_no_calendar_database_yet(self):
        self.run_module("calendar_events")  # macOS 13 and before keep Calendar Cache instead; a fresh Mac has neither
        self.assertEqual(self.records("calendar"), {})


# ---------------------------------------------------------------- Notes

def varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def pb(field, payload):
    return varint(field << 3 | 2) + varint(len(payload)) + payload


def note_proto(text):
    """A note's body as Notes keeps it: NoteStoreProto -> document (2) -> note (3) -> its text (2)."""
    note = pb(2, text.encode()) + pb(5, varint(1 << 3) + varint(len(text)))
    return pb(2, varint(2 << 3) + varint(0) + pb(3, note))


NOTES = """
create table Z_PRIMARYKEY (Z_ENT int, Z_NAME text);
insert into Z_PRIMARYKEY values (5, 'ICAttachment'), (14, 'ICFolder'), (11, 'ICNote');
create table ZICNOTEDATA (Z_PK integer primary key, ZNOTE int, ZDATA blob);
create table ZICCLOUDSYNCINGOBJECT (Z_PK integer primary key, Z_ENT int, ZIDENTIFIER text, ZTITLE1 text, ZTITLE2 text, ZSNIPPET text,
  ZFOLDER int, ZFOLDERTYPE int, ZISPASSWORDPROTECTED int, ZISPINNED int, ZMARKEDFORDELETION int, ZCREATIONDATE1 real,
  ZCREATIONDATE3 real, ZMODIFICATIONDATE1 real, ZNOTE int, ZTYPEUTI text, ZTITLE text);
insert into ZICCLOUDSYNCINGOBJECT (Z_PK, Z_ENT, ZTITLE2, ZFOLDERTYPE) values (1, 14, 'Notes', 0), (2, 14, 'Recently Deleted', 1), (3, 14, 'Recipes', 0);
"""


class NotesTests(Home):
    def store(self, script=NOTES, rows=()):
        return make_db(self.lib("Group Containers/group.com.apple.notes/NoteStore.sqlite"), script, rows)

    def note(self, pk, ident, title, folder=1, data=None, snippet=None, **more):
        cols = {"Z_PK": pk, "Z_ENT": 11, "ZIDENTIFIER": ident, "ZTITLE1": title, "ZFOLDER": folder, "ZSNIPPET": snippet,
                "ZCREATIONDATE1": 700000000, "ZMODIFICATIONDATE1": 700000500, **more}
        out = [(f"insert into ZICCLOUDSYNCINGOBJECT ({', '.join(cols)}) values ({', '.join('?' * len(cols))})", tuple(cols.values()))]
        if data is not None:
            out.append(("insert into ZICNOTEDATA (ZNOTE, ZDATA) values (?, ?)", (pk, data)))
        return out

    def test_bodies_folders_locked_and_recently_deleted(self):
        self.store(rows=[*self.note(10, "GZ", "Groceries", 3, gzip.compress(note_proto("Groceries\nEggs\nMilk"))),
                         *self.note(11, "RAW", "Plain", data=note_proto("Plain, not compressed")),
                         *self.note(12, "JUNK", "Odd", data=b"\x1f\x8b not really gzip", snippet="Odd snippet"),
                         *self.note(13, "LOCKED", "Bank", data=bytes(range(7, 250)), ZISPASSWORDPROTECTED=1),
                         *self.note(14, "TRASH", "Old list", 2, gzip.compress(note_proto("Old list"))),
                         *self.note(15, "PURGED", "Gone", data=gzip.compress(note_proto("Gone")), ZMARKEDFORDELETION=1),
                         *self.note(16, "NODATA", "Not downloaded", snippet="Only the snippet"),
                         *self.note(17, "NEW", "Newer", data=gzip.compress(note_proto("Newer")), ZCREATIONDATE1=None, ZCREATIONDATE3=690000000)])
        self.run_module("apple_notes")
        got = self.records("apple_notes")
        self.assertEqual((got["GZ"]["text"], got["GZ"]["thread"]), ("Groceries\nEggs\nMilk", "Recipes"))
        self.assertEqual(got["RAW"]["text"], "Plain, not compressed")
        self.assertEqual(got["JUNK"]["text"], "Odd snippet")
        self.assertEqual((got["LOCKED"]["title"], got["LOCKED"]["meta"]["locked"]), ("Bank", True))
        self.assertNotIn("text", got["LOCKED"], "a locked note's body is encrypted: none of it is read")
        for key in ("TRASH", "PURGED"):
            with self.subTest(key):
                self.assertTrue(got[key]["meta"]["deleted"])
                self.assertEqual(got[key]["meta"]["tier"], "deleted", "kept, and left out of searches as deleted mail is")
        self.assertNotIn("tier", got["GZ"]["meta"])
        self.assertEqual(got["NODATA"]["text"], "Only the snippet")
        self.assertEqual(got["NEW"]["ts"], iso(690000000), "macOS 13 on: ZCREATIONDATE3")

    def test_an_older_notes_schema(self):
        self.store("""
            create table Z_PRIMARYKEY (Z_ENT int, Z_NAME text);
            insert into Z_PRIMARYKEY values (14, 'ICFolder'), (11, 'ICNote');
            create table ZICNOTEDATA (Z_PK integer primary key, ZNOTE int, ZDATA blob);
            create table ZICCLOUDSYNCINGOBJECT (Z_PK integer primary key, Z_ENT int, ZIDENTIFIER text, ZTITLE1 text, ZTITLE2 text,
              ZFOLDER int, ZCREATIONDATE1 real, ZMODIFICATIONDATE1 real, ZNOTE int);
            insert into ZICCLOUDSYNCINGOBJECT (Z_PK, Z_ENT, ZTITLE2) values (1, 14, 'Notes');
        """, [("insert into ZICCLOUDSYNCINGOBJECT values (2, 11, 'OLD', 'Old note', null, 1, 500000000, 500000100, null)", ()),
              ("insert into ZICNOTEDATA (ZNOTE, ZDATA) values (2, ?)", (gzip.compress(note_proto("Old note\nwritten in 2016")),))])
        self.run_module("apple_notes")
        old = self.records("apple_notes")["OLD"]
        self.assertEqual((old["text"], old["thread"], old["ts"]), ("Old note\nwritten in 2016", "Notes", iso(500000000)))


# ---------------------------------------------------------------- Photos

U = "B0000000-0000-0000-0000-00000000000{}".format


def photos_library(home, asset="ZASSET", faces=("ZASSETFORFACE", "ZPERSONFORFACE"), psi=True, imported_by=True):
    """A library as Photos keeps it on macOS 14 and on; asset and faces name the columns older versions had (ZGENERICASSET on
    10.15; ZDETECTEDFACE.ZASSET and .ZPERSON through 13)."""
    lib = home / "Pictures/Photos Library.photoslibrary"
    make_db(lib / "database/Photos.sqlite", f"""
        create table ZMOMENT (Z_PK integer primary key, ZTITLE text, ZSUBTITLE text);
        create table ZPERSON (Z_PK integer primary key, ZFULLNAME text, ZDISPLAYNAME text);
        create table ZDETECTEDFACE (Z_PK integer primary key, {faces[0]} int, {faces[1]} int);
        create table ZASSETDESCRIPTION (Z_PK integer primary key, ZLONGDESCRIPTION text);
        create table ZADDITIONALASSETATTRIBUTES (Z_PK integer primary key, ZASSET int, ZORIGINALFILENAME text, ZTITLE text,
            ZTIMEZONENAME text, {"ZIMPORTEDBYDISPLAYNAME text," if imported_by else ""} ZASSETDESCRIPTION int);
        create table ZGENERICALBUM (Z_PK integer primary key, ZTITLE text, ZKIND int);
        create table Z_26ASSETS (Z_26ALBUMS int, Z_34ASSETS int);
        create table {asset} (Z_PK integer primary key, ZUUID text, ZDATECREATED real, ZLATITUDE real, ZLONGITUDE real,
            ZFILENAME text, ZKIND int, ZFAVORITE int, ZHIDDEN int, ZTRASHEDSTATE int, ZDURATION real, ZMOMENT int, ZHASADJUSTMENTS int);
        insert into ZMOMENT values (1, 'Lisbon', 'Alfama');
        insert into ZPERSON values (1, 'Grace Hopper', 'Grace');
        insert into ZGENERICALBUM values (1, 'Trip', 2);
        insert into Z_26ASSETS values (1, 1);
        insert into ZDETECTEDFACE values (1, 1, 1);
        insert into {asset} values (1, '{U(1)}', 700000000, 38.71, -9.13, 'IMG_1.HEIC', 0, 0, 0, 0, 0, 1, 0);
        insert into {asset} values (2, '{U(2)}', 700000100, 38.71, -9.13, 'IMG_2.HEIC', 0, 0, 1, 0, 0, 1, 0);
        insert into {asset} values (3, '{U(3)}', 700000200, 38.71, -9.13, 'IMG_3.HEIC', 0, 0, 0, 1, 0, 1, 0);
        insert into {asset} values (4, '{U(4)}', 700000300, 38.71, -9.13, 'IMG_4.HEIC', 0, 0, 0, 0, 0, 1, 1);
        insert into {asset} values (5, '{U(5)}', 700000400, -180, -180, 'IMG_5.HEIC', 0, 0, 0, 0, 0, null, 0);
        insert into {asset} values (6, '{U(6)}', 700000500, null, null, 'IMG_6.MOV', 1, 0, null, 0, 12.4, null, 0);
    """)
    if psi:
        make_db(lib / "database/search/psi.sqlite", "create table groups (category int, content_string text);"
                "create table assets (uuid_0 int, uuid_1 int); create table ga (groupid int, assetid int);")
    return lib


class PhotosTests(Home):
    def test_renamed_library_is_read(self):
        lib = photos_library(self.home)
        lib.rename(lib.with_name("Family Archive.photoslibrary"))
        self.assertEqual(sorted(self.run_photos()), ["1", "4", "5", "6"])

    def test_external_system_library_is_read(self):
        lib = photos_library(self.home)
        external = self.home / "External Drive/Archive.photoslibrary"
        external.parent.mkdir()
        lib.rename(external)
        prefs = self.home / "Library/Containers/com.apple.photolibraryd/Data/Library/Preferences/com.apple.photolibraryd.plist"
        prefs.parent.mkdir(parents=True, exist_ok=True)
        prefs.write_bytes(plistlib.dumps({"SystemLibraryPath": str(external)}))
        self.assertEqual(sorted(self.run_photos()), ["1", "4", "5", "6"])

    def test_memories_from_every_library_and_kept_while_a_drive_is_away(self):
        # Two libraries, each with a Memory, and one they share (a library copied from the other): all three, once each.
        def memories(lib, rows):
            con = sqlite3.connect(lib / "database/Photos.sqlite")
            con.execute("create table ZMEMORY (Z_PK integer primary key, ZUUID text, ZTITLE text, ZSUBTITLE text, ZSTARTDATE real, ZENDDATE real)")
            con.executemany("insert into ZMEMORY (ZUUID, ZTITLE, ZSTARTDATE, ZENDDATE) values (?, ?, 700000000, 700086400)", rows)
            con.commit()
            con.close()
        first = photos_library(self.home)
        first = first.rename(first.with_name("Family Archive.photoslibrary"))
        memories(first, [("M1", "Lisbon"), ("SAME", "Summer")])
        second = photos_library(self.home)
        memories(second, [("M2", "Tokyo"), ("SAME", "Summer")])
        self.run_photos()
        self.assertEqual(sorted(r["title"] for r in self.records("photos_memories").values()), ["Lisbon", "Summer", "Tokyo"])
        # The libraries go (an external drive unplugged): what was read of them stays.
        shutil.rmtree(first)
        shutil.rmtree(second)
        self.run_photos()
        self.assertEqual(len(self.records("photos_memories")), 3)

    def run_photos(self):
        self.run_module("photos")
        return {k[-1]: v for k, v in self.records("photos").items()}

    def test_faces_on_every_version(self):
        for faces in (("ZASSET", "ZPERSON"), ("ZASSETFORFACE", "ZPERSONFORFACE")):  # macOS 11-13, 14 on
            with self.subTest(faces[0]):
                self.setUp()
                photos_library(self.home, faces=faces)
                one = self.run_photos()["1"]
                self.assertEqual(one["participants"], ["Grace Hopper"])
                self.assertIn("People: Grace Hopper", one["text"])

    def test_a_catalina_library(self):
        photos_library(self.home, asset="ZGENERICASSET", faces=("ZASSET", "ZPERSON"), imported_by=False)
        got = self.run_photos()
        self.assertEqual(sorted(got), ["1", "4", "5", "6"])
        self.assertIn("Albums: Trip", got["1"]["text"])

    def test_no_search_index_or_one_with_a_row_missing_its_uuid(self):
        photos_library(self.home, psi=False)
        self.assertEqual(sorted(self.run_photos()), ["1", "4", "5", "6"], "Photos hasn't built its search index yet")
        make_db(self.home / "Pictures/Photos Library.photoslibrary/database/search/psi.sqlite",
                "create table groups (category int, content_string text); create table assets (uuid_0 int, uuid_1 int);"
                "create table ga (groupid int, assetid int); insert into groups values (1500, 'Beach'); insert into assets values (null, null);"
                "insert into ga values (1, 1);")
        self.assertEqual(sorted(self.run_photos()), ["1", "4", "5", "6"])

    def test_hidden_and_in_the_trash_are_counted_not_lost_silently(self):
        photos_library(self.home)
        got = self.run_photos()
        self.assertNotIn("2", got)
        self.assertNotIn("3", got)
        self.assertIn("6", got, "a hidden flag never set (null) isn't hidden")
        self.assertEqual({k: v for k, v in self.notes("photos").items() if k in ("hidden_left_out", "in_trash_left_out")},
                         {"hidden_left_out": 1, "in_trash_left_out": 1})

    def test_an_edited_photo_links_its_edited_version(self):
        lib = photos_library(self.home)
        (lib / "originals/B").mkdir(parents=True)
        (lib / f"originals/B/{U(4)}.heic").write_bytes(b"original")
        (lib / "resources/renders/B").mkdir(parents=True)
        (lib / f"resources/renders/B/{U(4)}_1_201_a.jpeg").write_bytes(b"edited")
        got = self.run_photos()
        self.assertTrue(got["4"]["meta"]["edited"])
        self.assertEqual(got["4"]["meta"]["files"], [str(lib / f"resources/renders/B/{U(4)}_1_201_a.jpeg")], "as it looks now")
        self.assertNotIn("edited", got["1"]["meta"])

    def test_where_a_photo_was_taken_and_where_none_was_kept(self):
        photos_library(self.home)
        got = self.run_photos()
        self.assertEqual((got["1"]["meta"]["lat"], got["1"]["meta"]["lon"]), (38.71, -9.13))
        for k in ("5", "6"):  # -180: Photos' "no location"; none at all
            self.assertNotIn("lat", got[k]["meta"])
        self.assertEqual(got["6"]["meta"]["seconds"], 12)


# ---------------------------------------------------------------- Browsers

def webkit(unix):
    return int((unix + WEBKIT) * 1e6)


def chromium_history(path, url="https://example.com/page", visit_time=webkit(1700000000), other_device=None):
    return make_db(path, """
        create table urls (id integer primary key, url text, title text, visit_count int);
        create table visits (id integer primary key, url int, visit_time int, transition int, visit_duration int,
          originator_cache_guid text);
        create table keyword_search_terms (url_id int, term text);
    """, [("insert into urls values (1, ?, 'A page', 2)", (url,)),
          ("insert into visits values (1, 1, ?, 805306368, 4000000, '')", (visit_time,)),
          *([("insert into visits values (2, 1, ?, 805306368, 0, ?)", (visit_time + 60_000_000, other_device))] if other_device else [])])


def safari_history(path, url="https://example.com/safari", when=700000000):
    return make_db(path, """
        create table history_items (id integer primary key, url text, visit_count int);
        create table history_visits (id integer primary key, history_item int, visit_time real, title text, load_successful int,
          redirect_source int, redirect_destination int, origin int);
    """, [("insert into history_items values (1, ?, 1)", (url,)), ("insert into history_visits values (1, 1, ?, 'Safari page', 1, null, null, 0)", (when,))])


class BrowserTests(Home):
    SUPPORT = "Application Support"

    def run_browsers(self):
        self.run_module("browser_history", UMP_BROWSERS_SKIP="")
        return self.records("browser_history")

    def test_every_chromium_browser_and_profile_in_webkit_time(self):
        s = self.SUPPORT
        chromium_history(self.lib(f"{s}/Google/Chrome/Default/History"))
        chromium_history(self.lib(f"{s}/Google/Chrome/Profile 1/History"), "https://work.example/")
        self.lib(f"{s}/Google/Chrome/Local State").write_text(json.dumps({"profile": {"info_cache": {"Profile 1": {"name": "Work"}}}}))
        for folder in ("Microsoft Edge/Default", "BraveSoftware/Brave-Browser/Default", "Vivaldi/Default", "Arc/User Data/Default"):
            chromium_history(self.lib(f"{s}/{folder}/History"))
        chromium_history(self.lib(f"{s}/com.operasoftware.Opera/History"))  # Opera's one profile, in its data folder
        got = self.run_browsers()
        for rid in ("chrome:Default:1", "chrome:Profile 1:1", "edge:Default:1", "brave:Default:1", "vivaldi:Default:1", "arc:Default:1",
                    "opera:Default:1"):
            with self.subTest(rid):
                self.assertEqual(got[rid]["ts"], "2023-11-14T22:13:20Z")
        self.assertEqual(got["chrome:Profile 1:1"]["thread_name"], "Chrome (Work)")

    def test_opera_after_it_moved_its_profile_into_default(self):
        s = self.SUPPORT
        chromium_history(self.lib(f"{s}/com.operasoftware.Opera/History"), "https://old.example/")  # left behind
        chromium_history(self.lib(f"{s}/com.operasoftware.Opera/Default/History"), "https://new.example/")
        got = self.run_browsers()
        self.assertEqual([r["url"] for r in got.values() if r["id"].startswith("opera:")], ["https://new.example/"])

    def test_chrome_visits_synced_from_other_devices(self):
        chromium_history(self.lib(f"{self.SUPPORT}/Google/Chrome/Default/History"), other_device="9f1c0a")
        got = self.run_browsers()
        self.assertEqual(got["chrome:Default:2"]["meta"]["other_device"], True)
        self.assertNotIn("other_device", got["chrome:Default:1"]["meta"])

    def test_a_profile_that_cant_be_read_doesnt_stop_the_rest(self):
        s = self.SUPPORT
        chromium_history(self.lib(f"{s}/Google/Chrome/Default/History"))
        self.lib(f"{s}/Google/Chrome/Profile 2/History").write_bytes(b"")  # made, never written
        self.lib(f"{s}/Microsoft Edge/Default/History").write_bytes(b"not a database " * 100)
        firefox = self.lib(f"{s}/Firefox/Profiles/ab12.default-release/places.sqlite")
        firefox.write_bytes(b"\x00" * 10)
        got = self.run_browsers()
        self.assertIn("chrome:Default:1", got)
        self.assertEqual(self.notes("browser_history")["unreadable"], ["chrome:Profile 2", "edge:Default", "firefox:ab12.default-release"])

    def test_a_history_locked_by_its_browser_mid_write(self):
        path = chromium_history(self.lib(f"{self.SUPPORT}/Google/Chrome/Default/History"))
        con = sqlite3.connect(path, isolation_level=None)  # as Chrome holds it: exclusively, a write under way
        self.addCleanup(con.close)
        con.execute("pragma locking_mode=exclusive")
        con.execute("pragma cache_size=1")
        con.execute("begin exclusive")
        con.executemany("insert into urls (url, title) values (?, ?)", [(f"https://half.example/{i}", "x" * 3000) for i in range(100)])
        self.assertTrue(Path(str(path) + "-journal").stat().st_size > 0)
        got = self.run_browsers()
        self.assertEqual(got["chrome:Default:1"]["url"], "https://example.com/page", "what it had written before")
        con.execute("rollback")

    def test_firefox_profiles_one_of_them_locked(self):
        s = self.SUPPORT
        for i, pdir in enumerate(("ab12.default-release", "cd34.work")):
            make_db(self.lib(f"{s}/Firefox/Profiles/{pdir}/places.sqlite"), """
                pragma journal_mode=wal;
                create table moz_places (id integer primary key, url text, title text, visit_count int);
                create table moz_historyvisits (id integer primary key, place_id int, visit_date int, visit_type int);
            """, [("insert into moz_places values (1, ?, 'Fox', 1)", (f"https://fox.example/{i}",)),
                  ("insert into moz_historyvisits values (1, 1, ?, 1)", (1700000000_000000,))])
        con = sqlite3.connect(self.lib(f"{s}/Firefox/Profiles/cd34.work/places.sqlite"), isolation_level=None)
        self.addCleanup(con.close)
        con.execute("pragma locking_mode=exclusive")
        con.execute("begin exclusive")
        con.execute("insert into moz_places (url) values ('https://half.example/')")
        got = self.run_browsers()
        con.execute("rollback")
        self.assertEqual(sorted(r["thread_name"] for r in got.values()), ["Firefox (default-release)", "Firefox (work)"])
        self.assertTrue(all(r["ts"] == "2023-11-14T22:13:20Z" for r in got.values()))

    def test_skipped_safari_is_not_read_or_copied(self):
        safari_history(self.lib("Safari/History.db"))
        container = "Containers/com.apple.Safari/Data/Library/Safari"
        safari_history(self.lib(f"{container}/Profiles/work/History.db"), "https://work.example/")
        for folder in ("Safari", container):
            make_db(self.lib(f"{folder}/SafariTabs.db"),
                    "create table bookmarks (title text, server_id text, external_uuid text)",
                    [("insert into bookmarks values ('Work', 'work', null)", ())])
        chromium_history(self.lib(f"{self.SUPPORT}/Google/Chrome/Default/History"))

        self.run_module("browser_history", UMP_BROWSERS_SKIP="safari")

        self.assertEqual(list(self.records("browser_history")), ["chrome:Default:1"])
        self.assertEqual(self.records("browser_saved"), {})
        self.assertEqual(self.notes("browser_history")["not_read"], ["safari"])
        self.assertEqual(list((self.corpus / "raw/browser").glob("safari*")), [],
                         "turning Safari off must also prevent copies of its profile databases")

    def test_safari_profiles(self):
        safari_history(self.lib("Safari/History.db"))
        container = "Containers/com.apple.Safari/Data/Library/Safari"
        safari_history(self.lib(f"{container}/Profiles/5F3A9C1E-0B2D-4E7F-8A6B-1C2D3E4F5A6B/History.db"), "https://work.example/", 700000500)
        make_db(self.lib(f"{container}/SafariTabs.db"), "create table bookmarks (id integer primary key, title text, server_id text, external_uuid text)",
                [("insert into bookmarks values (1, 'Work', '5F3A9C1E-0B2D-4E7F-8A6B-1C2D3E4F5A6B', 'E1')", ()),
                 ("insert into bookmarks values (2, '', 'DefaultProfile', 'E0')", ())])
        got = self.run_browsers()
        self.assertEqual(got["safari:1"]["thread_name"], "Safari (default)")
        work = got["safari:5F3A9C1E-0B2D-4E7F-8A6B-1C2D3E4F5A6B:1"]
        self.assertEqual((work["url"], work["thread_name"], work["ts"]), ("https://work.example/", "Safari (Work)", iso(700000500)))


# ---------------------------------------------------------------- Reminders

REMINDER_STORE = """
create table ZREMCDBASELIST (Z_PK integer primary key, ZNAME text);
create table ZREMCDREMINDER (Z_PK integer primary key, ZIDENTIFIER blob, ZCKIDENTIFIER text, ZTITLE text, ZNOTES text, ZCOMPLETED int,
  ZCOMPLETIONDATE real, ZCREATIONDATE real, ZDUEDATE real, ZFLAGGED int, ZPRIORITY int, ZLIST int, ZPARENTREMINDER int,
  ZLASTMODIFIEDDATE real, ZMARKEDFORDELETION int);
insert into ZREMCDBASELIST values (1, 'Trip');
"""


class RemindersTests(Home):
    STORES = "Group Containers/group.com.apple.reminders/Container_v1/Stores"

    def test_ids_are_uuids_not_bytes_and_an_earlier_runs_copy_isnt_kept_twice(self):
        parent, child = uuid.UUID("11111111-2222-3333-4444-555555555555"), uuid.UUID("66666666-7777-8888-9999-aaaaaaaaaaaa")
        make_db(self.lib(f"{self.STORES}/Data-ABC.sqlite"), REMINDER_STORE, [
            ("insert into ZREMCDREMINDER values (7, ?, null, 'Pack', null, 0, null, 700000000, null, 0, 0, 1, 0, null, 0)", (parent.bytes,)),
            ("insert into ZREMCDREMINDER values (8, ?, null, 'Passport', null, 0, null, 700000001, null, 0, 0, 1, 7, null, 0)", (child.bytes,))])
        # What an earlier run wrote, when the id was the bytes as Python prints them.
        (self.corpus / "normalized").mkdir()
        (self.corpus / "normalized/reminders.jsonl").write_text(json.dumps(
            {"id": str(parent.bytes), "source": "reminders", "kind": "reminder", "ts": iso(700000000), "title": "Pack"}) + "\n")
        self.run_module("reminders")
        got = self.records("reminders")
        self.assertEqual(sorted(got), [str(parent).upper(), str(child).upper()])
        self.assertEqual(got[str(child).upper()]["meta"]["subtask_of"], str(parent).upper())

    def test_a_store_without_reminders_and_an_older_store(self):
        make_db(self.lib(f"{self.STORES}/Data-local.sqlite"), "create table Z_METADATA (Z_VERSION int)")
        make_db(self.lib(f"{self.STORES}/Data-OLD.sqlite"), """
            create table ZREMCDBASELIST (Z_PK integer primary key, ZNAME text);
            create table ZREMCDREMINDER (Z_PK integer primary key, ZTITLE text, ZNOTES text, ZCOMPLETED int, ZCOMPLETIONDATE real,
              ZCREATIONDATE real, ZDUEDATE real, ZPRIORITY int, ZLIST int, ZMARKEDFORDELETION int);
            insert into ZREMCDBASELIST values (1, 'Errands');
            insert into ZREMCDREMINDER values (3, 'Post the letter', null, 1, 500003600, 500000000, null, 0, 1, 0);
        """)
        self.run_module("reminders")
        got = self.records("reminders")
        self.assertEqual(got["Data-OLD:3"]["thread"], "Errands")
        self.assertTrue(got["Data-OLD:3"]["meta"]["completed"])


# ---------------------------------------------------------------- Voice Memos, Podcasts, Books, Maps

class VoiceMemosTests(Home):
    def test_titles_paths_transcripts_and_recently_deleted(self):
        root = self.lib("Group Containers/group.com.apple.VoiceMemos.shared/Recordings/x").parent
        doc = json.dumps({"locale": {"identifier": "en_US"}, "attributedString": {"runs": ["Today we ", 0, "talked about tides", 1]}}).encode()
        (root / "20230308 202640.m4a").write_bytes(b"\x00\x00\x00\x18ftypM4A " + b"\x00" * 12 + (len(doc) + 8).to_bytes(4, "big") + b"tsrp" + doc)
        make_db(root / "CloudRecordings.db", """
            create table ZCLOUDRECORDING (Z_PK integer primary key, ZUNIQUEID text, ZDATE real, ZDURATION real, ZPATH text,
              ZCUSTOMLABEL text, ZEVICTIONDATE real);
            insert into ZCLOUDRECORDING values (1, 'V1', 700000000, 61.5, '20230308 202640.m4a', 'Lecture', null);
            insert into ZCLOUDRECORDING values (2, 'V2', 700000100, 5, '/elsewhere/old.m4a', 'Oops', 700000200);
            insert into ZCLOUDRECORDING values (3, 'V3', 700000300, 9, null, null, null);
        """)
        self.run_module("voice_memos")
        got = self.records("voice_memos")
        self.assertEqual(got["V1"]["text"], "Lecture\nToday we talked about tides")
        self.assertTrue(got["V1"]["meta"]["transcribed"])
        self.assertEqual((got["V2"]["meta"]["deleted"], got["V2"]["meta"]["tier"]), (True, "deleted"), "in Recently Deleted")
        self.assertNotIn("tier", got["V1"]["meta"])
        self.assertIn("V3", got)


class PodcastsTests(Home):
    def test_a_library_without_some_columns(self):
        make_db(self.lib("Group Containers/243LU875E5.groups.com.apple.podcasts/Documents/MTLibrary.sqlite"), """
            create table ZMTPODCAST (Z_PK integer primary key, ZUUID text, ZTITLE text, ZAUTHOR text);
            create table ZMTEPISODE (Z_PK integer primary key, ZUUID text, ZTITLE text, ZPODCAST int, ZLASTDATEPLAYED real,
              ZPLAYHEAD real, ZDURATION real);
            insert into ZMTPODCAST values (1, 'p1', 'Engines Weekly', 'Ada');
            insert into ZMTEPISODE values (1, 'e1', 'Gears', 1, 780000000, 1500, 1800);
            insert into ZMTEPISODE values (2, 'e2', 'Not played', 1, null, 0, 1800);
        """)
        self.run_module("podcasts")
        got = self.records("podcasts")
        self.assertEqual([r["title"] for r in got.values()], ["Gears"])
        self.assertEqual(next(iter(got.values()))["thread_name"], "Engines Weekly")


class BooksTests(Home):
    def test_an_older_library_and_annotations(self):
        docs = "Containers/com.apple.iBooksX/Data/Documents"
        make_db(self.lib(f"{docs}/BKLibrary/BKLibrary-1-091020131601.sqlite"), """
            create table ZBKLIBRARYASSET (Z_PK integer primary key, ZASSETID text, ZTITLE text, ZAUTHOR text, ZREADINGPROGRESS real);
            insert into ZBKLIBRARYASSET values (1, 'B1', 'Moby-Dick', 'Herman Melville', 0.5);
        """)
        make_db(self.lib(f"{docs}/AEAnnotation/AEAnnotation_v10312011_1727_local.sqlite"), """
            create table ZAEANNOTATION (Z_PK integer primary key, ZANNOTATIONASSETID text, ZANNOTATIONSELECTEDTEXT text);
            insert into ZAEANNOTATION values (1, 'B1', 'Call me Ishmael.');
        """)
        self.run_module("books")
        got = self.records("books")
        self.assertEqual(got["book:B1"]["text"], "Moby-Dick by Herman Melville, in your Books library: 50% read")
        self.assertEqual((got["pk:1"]["title"], got["pk:1"]["text"]), ("Moby-Dick", "“Call me Ishmael.”"))


# ---------------------------------------------------------------- Screen Time (Biome)

def focus(start, bundle, t):
    """An App.InFocus event: 3 = starting (1) or ending (0), 4 = when (a double, Apple seconds), 6 = the app."""
    return varint(3 << 3) + varint(1 if start else 0) + varint(4 << 3 | 1) + struct.pack("<d", t) + pb(6, bundle.encode())


def segb_v2(records):
    data, trailer = bytearray(), []
    for rec, t in records:
        data += b"\x00" * 8 + rec
        trailer.append(struct.pack("<iid", len(data), 1, t))
        data += b"\x00" * (-len(data) % 4)
    return b"SEGB" + struct.pack("<i", len(records)) + b"\x00" * 24 + bytes(data) + b"".join(reversed(trailer))


def segb_v1(records):
    body = bytearray()
    for rec, t in records:
        body += struct.pack("<iiddI4x", len(rec), 1, t, t, 0) + rec
        body += b"\x00" * (-len(body) % 8)
    return struct.pack("<i", 56 + len(body)) + b"\x00" * 48 + b"SEGB" + bytes(body)


class AppUsageTests(Home):
    def test_both_biome_formats_and_files_cut_short(self):
        stream = self.lib("Biome/streams/restricted/App.InFocus/local/x").parent
        t = 780000000.0
        cut = varint(3 << 3) + varint(1) + varint(4 << 3 | 1) + b"\x00\x00"  # its time cut off two bytes in
        (stream / "780000000000000").write_bytes(segb_v2([(focus(True, "com.apple.Safari", t), t), (cut, t + 1),
                                                          (focus(False, "com.apple.Safari", t + 120), t + 120)]))
        (stream / "780000000000001").write_bytes(b"SEGB\x01\x00")  # a file being written
        (stream / "780000000000002").write_bytes(b"")
        remote = self.lib("Biome/streams/restricted/App.InFocus/remote/PHONE-1/x").parent
        (remote / "770000000000000").write_bytes(segb_v1([(focus(True, "com.apple.mobilesafari", t + 600), t + 600),
                                                          (focus(False, "com.apple.mobilesafari", t + 900), t + 900)]))
        self.run_module("app_usage")
        got = [r for r in self.records("app_usage").values() if r["kind"] == "app_usage"]
        self.assertEqual(sorted((r["title"], r["thread"], r["meta"]["seconds"]) for r in got),
                         [("Safari", "PHONE-1", 300), ("Safari", "this Mac", 120)])


# ---------------------------------------------------------------- Terminal, editors, Notion, coding assistants

class ShellHistoryTests(Home):
    def test_prezto_history_an_unreadable_file_and_an_odd_fish_entry(self):
        (self.home / ".zhistory").write_bytes(b": 1700000300:0;make test\n")  # Prezto's HISTFILE
        (self.home / ".zsh_history").write_bytes(b": 1700000000:0;git status\n")
        bash = self.home / ".bash_history"
        bash.write_text("ls\n")
        bash.chmod(0)
        self.addCleanup(bash.chmod, 0o644)
        (self.home / ".local/share/fish").mkdir(parents=True)
        (self.home / ".local/share/fish/fish_history").write_text("- cmd: brew update\n  when: soon\n- cmd: ls -la\n  when: 1650000000\n")
        self.run_module("shell_history")
        got = {r["text"]: r for r in self.records("shell_history").values()}
        self.assertEqual(got["make test"]["ts"], "2023-11-14T22:18:20Z")
        self.assertEqual(got["make test"]["meta"]["file"], ".zhistory")
        self.assertIn("git status", got)
        self.assertNotIn("ts", got["brew update"])
        self.assertEqual(got["ls -la"]["ts"], "2022-04-15T05:20:00Z")
        self.assertEqual(self.notes("shell_history")["unreadable"], [".bash_history"])


class EditorHistoryTests(Home):
    def test_entries_files_not_as_expected(self):
        hist = self.lib("Application Support/Code/User/History/x").parent
        (hist / "h1").mkdir()
        (hist / "h1/entries.json").write_text("[1, 2]")
        (hist / "h2").mkdir()
        (hist / "h2/entries.json").write_text(json.dumps({"version": 1, "resource": "file:///Users/ada/gear.py", "entries": [
            "stray", {"id": "e1", "timestamp": "1700000000000"}, {"id": "e1", "timestamp": 1700000000000}, {"id": "e2", "timestamp": "soon"}]}))
        (hist / "h3").mkdir()
        (hist / "h3/entries.json").write_text(json.dumps({"resource": 5, "entries": None}))
        self.run_module("editor_history")
        got = self.records("editor_history")
        self.assertEqual(list(got), ["vscode:h2:e1"])
        self.assertEqual(got["vscode:h2:e1"]["ts"], "2023-11-14T22:13:20Z")


class NotionTests(Home):
    def test_a_cache_with_odd_rows(self):
        make_db(self.lib("Application Support/Notion/notion.db"), """
            create table block (id text, type text, properties text, content text, parent_id text, parent_table text, alive int,
              created_time int, last_edited_time int);
        """, [("insert into block values (?,?,?,?,?,?,?,?,?)", row) for row in (
            ("p1", "page", '{"title": [["Trip plan"]]}', '["b1", "b2", "b3"]', "space", "space", 1, 1700000000000, 1700000500000),
            ("b1", "text", '{"title": [["Pack light"]]}', None, "p1", "block", 1, 1700000000000, None),
            ("b2", "text", "null", "null", "p1", "block", 1, 1700000000000, None),
            ("b3", "text", "{cut off", "[", "p1", "block", 1, 1700000000000, None),
            ("p2", "page", "[]", None, "space", "space", 1, 1700000000000, None))])
        self.run_module("notion_local")
        page = self.records("notion")["p1"]
        self.assertEqual((page["title"], page["text"]), ("Trip plan", "Trip plan\nPack light"))
        self.assertEqual(page["ts"], "2023-11-14T22:13:20Z")


class AiCodingTests(Home):
    def test_sessions_cut_off_mid_write(self):
        cc = self.home / ".claude/projects/-Users-ada-gears"
        cc.mkdir(parents=True)
        (cc / "s1.jsonl").write_text("\n".join([
            json.dumps({"type": "user", "uuid": "u1", "sessionId": "s1", "timestamp": "2026-10-01T10:00:00Z",
                        "message": {"role": "user", "content": "Fix the gear"}}),
            json.dumps({"type": "assistant", "uuid": "a1", "sessionId": "s1", "timestamp": "2026-10-01T10:00:05Z",
                        "message": {"role": "assistant", "content": [{"type": "text", "text": "Done."}]}}),
            '{"type": "user", "uuid": "u2", "message": {"role": "us']))  # still being written
        codex = self.home / ".codex/sessions/2026/10/01"
        codex.mkdir(parents=True)
        (codex / "rollout-2026-10-01T10-00-00-s2.jsonl").write_text("\n".join([
            json.dumps({"type": "session_meta", "timestamp": "2026-10-01T10:00:00Z", "payload": {"id": "s2", "cwd": "/Users/ada/gears"}}),
            "",
            json.dumps({"type": "response_item", "timestamp": "2026-10-01T10:00:01Z",
                        "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Oil the chain"}]}}),
            '{"type": "response_item", "payload": {"type": "mess']))
        (self.home / ".codex/session_index.jsonl").write_text('{"thread_name": "no id"}\n{"id": "s2", "thread_name": "Chain"}\n{"id": ')
        self.run_module("ai_coding")
        got = self.records("ai_coding")
        self.assertEqual((got["u1"]["text"], got["a1"]["text"]), ("Fix the gear", "Done."))
        self.assertEqual((got["codex:s2:1"]["text"], got["codex:s2:1"]["thread_name"]), ("Oil the chain", "Chain"))


class GitTests(Home):
    def test_a_log_encoding_other_than_utf8(self):
        (self.home / ".gitconfig").write_text("[i18n]\n\tlogOutputEncoding = ISO-8859-1\n[user]\n\tname = Ada\n\temail = ada@example.test\n")
        repo = self.home / "Developer/cafe"
        repo.mkdir(parents=True)
        env = {**os.environ, "HOME": str(self.home), "GIT_CONFIG_NOSYSTEM": "1"}
        subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env)
        (repo / "menu.txt").write_text("café")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True, env=env)
        subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-q", "-m", "Café au lait"], check=True, env=env)
        self.run_module("git_commits", GIT_CONFIG_NOSYSTEM="1")
        self.assertEqual([r["title"] for r in self.records("git_commits").values()], ["Café au lait"])


class DocumentsTests(Home):
    def test_files_that_cant_be_read(self):
        docs = self.home / "Documents"
        docs.mkdir()
        (docs / "fine.md").write_text("A note")
        (docs / "locked.md").write_text("Can't open")
        (docs / "locked.md").chmod(0)
        self.addCleanup((docs / "locked.md").chmod, 0o644)
        (docs / "gone.md").symlink_to(docs / "nowhere.md")
        (docs / "broken.docx").write_bytes(b"PK\x03\x04 not really a zip")
        self.run_module("documents")
        got = {Path(k).name: v for k, v in self.records("documents").items()}
        self.assertEqual(got["fine.md"]["text"], "A note")
        self.assertEqual(got["locked.md"]["meta"]["error"], "PermissionError")
        self.assertNotIn("gone.md", got)
        self.assertIn("broken.docx", got)


# ---------------------------------------------------------------- empty and missing databases

class EmptyDatabasesTests(Home):
    """A database file with nothing in it yet (made by its app, never written): nothing read, the run goes on."""

    FILES = {
        "imessage": ["Messages/chat.db"],
        "calls": ["Application Support/CallHistoryDB/CallHistory.storedata"],
        "apple_notes": ["Group Containers/group.com.apple.notes/NoteStore.sqlite"],
        "calendar_events": ["Group Containers/group.com.apple.calendar/Calendar.sqlitedb"],
        "reminders": ["Group Containers/group.com.apple.reminders/Container_v1/Stores/Data-1.sqlite"],
        "podcasts": ["Group Containers/243LU875E5.groups.com.apple.podcasts/Documents/MTLibrary.sqlite"],
        "voice_memos": ["Group Containers/group.com.apple.VoiceMemos.shared/Recordings/CloudRecordings.db"],
        "apple_maps": ["Containers/com.apple.Maps/Data/Maps/MapsSync_0.0.1"],
        "notion_local": ["Application Support/Notion/notion.db"],
        "books": ["Containers/com.apple.iBooksX/Data/Documents/BKLibrary/BKLibrary-1-091020131601.sqlite",
                  "Containers/com.apple.iBooksX/Data/Documents/AEAnnotation/AEAnnotation_v10312011_1727_local.sqlite"],
    }

    def test_each_one_empty(self):
        for module, files in self.FILES.items():
            with self.subTest(module):
                self.setUp()
                for f in files:
                    self.lib(f).write_bytes(b"")
                self.run_module(module)

    def test_photos_empty(self):
        (self.home / "Pictures/Photos Library.photoslibrary/database").mkdir(parents=True)
        (self.home / "Pictures/Photos Library.photoslibrary/database/Photos.sqlite").write_bytes(b"")
        self.run_module("photos")
        self.assertEqual(self.records("photos"), {})

    def test_none_there_at_all(self):
        """run_all.py runs every connector, on a Mac with or without each app."""
        for module in ("imessage", "calls", "apple_notes", "calendar_events", "reminders", "podcasts", "voice_memos", "apple_maps",
                       "notion_local", "books", "photos", "app_usage", "browser_history", "shell_history", "editor_history", "ai_coding"):
            with self.subTest(module):
                self.run_module(module)


if __name__ == "__main__":
    unittest.main()
