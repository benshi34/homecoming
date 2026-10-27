"""Chat and mail exports as they come: Slack's workspace exports (standard, every conversation, an Enterprise Grid
org's, one member's as JSON or text), its threads, edits, bots, files and markup; Reddit's CSVs, with bodies over many
lines, deleted posts, drafts and the header files beside them; WhatsApp's Export chat from an iPhone and from Android
in the languages and clock styles phones write it, with its own lines (encryption, groups, deleted, edited), media and
names with ": " in them; loose mail (.eml, Mail's .emlx, Thunderbird's mailboxes without an extension, Outlook for
Mac's .olm) in old encodings; vCards 2.1 to 4.0 from Google, iCloud, Android and old Macs. And files that are damaged
or an odd shape, which stop nothing. Exports are made up here; the importer runs as the app runs it.

Run: python3 -m unittest discover -s connectors/tests -p 'test_chat_mail_formats.py'
"""
import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

CONNECTORS = Path(__file__).resolve().parents[1]
NNBSP, LRM = "\u202f", "\u200e"  # the narrow no-break space before AM/PM, the left-to-right mark WhatsApp writes


def data(x):
    return x if isinstance(x, (str, bytes)) else json.dumps(x)


def csv_text(header, rows):
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(header)
    w.writerows(rows)
    return out.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.home, self.corpus = Path(t.name) / "home", Path(t.name) / "corpus"
        self.imports = self.corpus / "imports"
        self.home.mkdir()
        self.imports.mkdir(parents=True)
        (self.corpus / "identity.json").write_text(json.dumps({"names": ["Ada Lovelace"], "emails": ["ada@example.com"],
                                                               "usernames": ["ada_l"]}))

    def files(self, root, files):
        for name, x in files.items():
            p = self.imports / root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            x = data(x)
            p.write_bytes(x if isinstance(x, bytes) else x.encode())

    def zip(self, rel, files):
        p = self.imports / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(p, "w") as z:
            for name, x in files.items():
                z.writestr(name, data(x))
        return p

    def run_import(self):
        # Times written without a zone (WhatsApp's) are this Mac's clock: one zone for every run of the tests.
        env = {**os.environ, "HOME": str(self.home), "CORPUS_DIR": str(self.corpus), "TZ": "America/New_York"}
        r = subprocess.run([sys.executable, str(CONNECTORS / "imports.py")], cwd=CONNECTORS, env=env,
                           capture_output=True, text=True, timeout=120)
        self.out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, self.out[-3000:])
        self.recs = {f.stem: [json.loads(line) for line in f.read_text().splitlines()]
                     for f in (self.corpus / "normalized").glob("*.jsonl")}
        self.manifest = json.loads((self.corpus / "manifest.json").read_text())
        return self.recs

    def of(self, source, kind=None):
        return [r for r in self.recs.get(source, []) if kind is None or r["kind"] == kind]

    def thread(self, source, thread, kind="message"):
        return sorted((r for r in self.of(source, kind) if r.get("thread") == thread), key=lambda r: (r.get("ts") or "", r["id"]))

    def unclaimed(self):
        """The export files no parser read, by name."""
        return {x for g in self.manifest.get("_imports_unclaimed", []) for x in g["examples"]}


# ---------------------------------------------------------------- Telegram

class TelegramTests(Base):
    def export(self):
        U = 1767600000
        chat = {"name": "Theo Laurent", "type": "personal_chat", "id": 4401, "messages": [
            {"id": 1, "type": "message", "date": "2026-01-05T08:00:00", "date_unixtime": str(U), "from": "Theo Laurent", "from_id": "user77",
             "text": ["Tide at ", {"type": "bold", "text": "six"}, "?"],
             "reactions": [{"type": "emoji", "count": 3, "emoji": "👍", "recent": [{"from": "Ada Lovelace", "from_id": "user11", "date": "2026-01-05T08:01:00"}]}]},
            {"id": 2, "type": "message", "date_unixtime": str(U + 60), "from": "Ada Lovelace", "from_id": "user11", "text": "yes, at the pier",
             "reply_to_message_id": 1, "edited_unixtime": str(U + 90)},
            {"id": 3, "type": "message", "date_unixtime": str(U + 120), "from": "Theo Laurent", "from_id": "user77", "text": "",
             "photo": "photos/photo_1@05-01-2026_08-02-00.jpg", "width": 800, "height": 600},
            {"id": 4, "type": "service", "date_unixtime": str(U + 180), "actor": "Theo Laurent", "actor_id": "user77", "action": "phone_call", "text": ""}]}
        group = {"name": "Pier club", "type": "private_supergroup", "id": 5502, "messages": [
            {"id": 9, "type": "message", "date_unixtime": str(U + 300), "from": "Mo Reyes", "from_id": "user88", "text": "who's in?",
             "reply_to_message_id": 1, "reply_to_peer_id": "channel999"}]}
        self.files("Telegram Desktop/DataExport_2026-01-06", {
            "result.json": {"personal_information": {"user_id": 11, "first_name": "Ada"}, "chats": {"list": [chat, group]}},
            "photos/photo_1@05-01-2026_08-02-00.jpg": b"\xff\xd8\xff\xe0 a made-up jpeg"})

    def test_chats_replies_reactions_edits_and_files(self):
        self.export()
        self.run_import()
        msgs = {r["id"]: r for r in self.of("telegram")}
        one, two, three = msgs["4401:1"], msgs["4401:2"], msgs["4401:3"]
        self.assertEqual((one["text"], one["author"], one["thread_name"], one["participants"]), ("Tide at six?", "Theo Laurent", "Theo Laurent", ["Theo Laurent"]))
        self.assertEqual(one["meta"]["reactions"], [{"who": "me", "reaction": "👍", "ts": "2026-01-05T08:01:00"}, {"reaction": "👍"}, {"reaction": "👍"}],
                         "each person listed, the rest by count")
        self.assertEqual((two["author"], two["is_me"], two["meta"]["reply_to"], two["meta"]["reply_text"]), ("me", True, "4401:1", "Tide at six?"))
        self.assertEqual(two["meta"]["edited"], "2026-01-05T08:01:30Z")
        self.assertEqual(three["text"], "[photo: photo_1@05-01-2026_08-02-00.jpg]")
        self.assertTrue((self.corpus / three["meta"]["files"][0]).exists() if not three["meta"]["files"][0].startswith("/") else Path(three["meta"]["files"][0]).exists())
        self.assertEqual(msgs["4401:4"]["kind"], "event")
        g = msgs["5502:9"]
        self.assertEqual((g["meta"]["group"], g.get("participants")), (True, None))
        self.assertNotIn("reply_to", g["meta"], "a reply to another chat's message isn't one to this chat's")
        self.assertNotIn("photos/photo_1@05-01-2026_08-02-00.jpg", self.unclaimed())


# ---------------------------------------------------------------- Slack

T = 1767600000  # 2026-01-05T08:00:00Z


def ts(n):
    return f"{T + n * 60}.{n:06d}"


USERS = [{"id": "U01", "name": "ada", "real_name": "Ada Lovelace", "profile": {"real_name": "Ada Lovelace"}},
         {"id": "U02", "name": "theo", "profile": {"real_name": "Theo Laurent", "display_name": "theo"}},  # no real_name of its own
         {"id": "U03", "name": "riley", "deleted": True, "profile": {"display_name": "Riley Park"}},
         {"id": "U0BOT", "name": "deploybot", "is_bot": True, "real_name": "Deploy Bot"}]


def say(n, user, text, **extra):
    return {"type": "message", "user": user, "text": text, "ts": ts(n), **extra}


class SlackTests(Base):
    def test_a_standard_export_threads_edits_bots_files_and_markup(self):
        day = [
            say(0, "U01", "standup in 5"),
            say(1, "U02", "<@U02> has joined the channel", subtype="channel_join"),
            say(2, "U02", "Plan for <#C02|random>? See <https://example.com/doc|the doc> &amp; <!here>", thread_ts=ts(2), reply_count=1,
                replies=[{"user": "U01", "ts": ts(3)}], reactions=[{"name": "thumbsup", "users": ["U01"], "count": 1}]),
            say(3, "U01", "Yes, <@U02|theo>, and <@U09>", thread_ts=ts(2), parent_user_id="U02"),
            say(4, "U01", "fixed typo", edited={"user": "U01", "ts": f"{T + 300}.000000"}),
            say(5, "U01", "Also here", subtype="thread_broadcast", thread_ts=ts(2)),
            {"type": "message", "subtype": "bot_message", "bot_id": "B01", "username": "Deploy Bot", "text": "", "ts": ts(6),
             "attachments": [{"fallback": "Deploy #42 finished", "text": "Deploy #42 finished", "title": "prod"}]},
            say(7, "U02", "", subtype="file_share", files=[{"id": "F01", "name": "plan.pdf", "title": "Q1 plan", "mimetype": "application/pdf"},
                                                          {"id": "F02", "mode": "hidden_by_limit"}]),
            say(8, "U02", "", blocks=[{"type": "rich_text", "elements": [{"type": "rich_text_section", "elements": [
                {"type": "text", "text": "Hello "}, {"type": "user", "user_id": "U01"}, {"type": "text", "text": ", see "},
                {"type": "link", "url": "https://example.com", "text": "this"}]}]}]),
            say(9, "U01", "set the channel topic: Launch", subtype="channel_topic", topic="Launch"),
            {"type": "message", "subtype": "tombstone", "user": "USLACKBOT", "text": "This message was deleted.", "hidden": True,
             "ts": ts(10), "thread_ts": ts(10), "reply_count": 1},
            say(11, "U03", "from a deactivated account"),
            say(12, "U02", "with a link preview https://example.com/x",
                attachments=[{"from_url": "https://example.com/x", "title": "Example", "text": "A page about examples"}])]
        self.zip("slack/Lumen Labs Slack export Jan 1 2026 - Jan 31 2026.zip", {
            "users.json": USERS, "channels.json": [{"id": "C01", "name": "general", "members": ["U01", "U02"]}, {"id": "C02", "name": "random"}],
            "integration_logs.json": {"logs": [{"service_type": "Google Drive", "date": str(T), "change_type": "added"}]},
            "general/2026-01-05.json": day})
        self.run_import()
        got = {r["id"].split(":")[1]: r for r in self.of("slack")}
        say_ = lambda n: got[ts(n)]  # noqa: E731
        self.assertEqual((say_(0)["author"], say_(0)["text"], say_(0)["ts"]), ("me", "standup in 5", "2026-01-05T08:00:00Z"))
        self.assertNotIn(ts(1), got, "who joined isn't a message")
        self.assertEqual(say_(2)["text"], "Plan for #random? See the doc (https://example.com/doc) & @here")
        self.assertEqual((say_(2)["author"], say_(2)["thread_name"], say_(2)["meta"]["reactions"]), ("Theo Laurent", "#general", [{"who": "me", "reaction": "👍"}]))
        self.assertEqual((say_(3)["text"], say_(3)["meta"]["reply_to"]), ("Yes, @Theo Laurent, and @U09", f"general:{ts(2)}"), "a reply names its parent's record")
        self.assertTrue(say_(4)["meta"]["edited"].startswith("2026-01-05T08:05"))
        self.assertEqual(say_(5)["text"], "Also here")
        self.assertEqual((say_(6)["author"], say_(6)["text"], say_(6)["meta"]["bot"], say_(6).get("is_me")),
                         ("Deploy Bot", "prod\nDeploy #42 finished", True, False))
        self.assertEqual(say_(7)["text"], "[file: Q1 plan]\n[a file Slack no longer keeps]")
        self.assertEqual(say_(8)["text"], "Hello @Ada Lovelace, see this (https://example.com)")
        self.assertEqual(say_(9)["kind"], "event")
        self.assertEqual((say_(10)["meta"]["tier"], say_(10)["author"]), ("deleted", "Slackbot"))
        self.assertEqual(say_(11)["author"], "Riley Park")
        self.assertEqual(say_(12)["text"], "with a link preview https://example.com/x", "a link's preview is the link's, not the message's")

    def test_slackdumps_export_files_and_a_reply_the_next_day(self):
        jpeg = b"\xff\xd8\xff\xe0 made-up"
        pic = {"id": "F0AAAAAAA", "name": "pier.jpg", "title": "pier.jpg", "mimetype": "image/jpeg"}
        doc = {"id": "F0BBBBBBB", "name": "notes.txt", "title": "notes", "mimetype": "text/plain"}
        self.zip("slack/slackdump_20260106_120000.zip", {
            "users.json": USERS, "channels.json": [{"id": "C01", "name": "general", "members": ["U01", "U02"]}],
            "dms.json": [{"id": "D01", "members": ["U01", "U02"]}],
            "general/2026-01-05.json": [say(0, "U02", "the pier at dawn", thread_ts=ts(0), reply_count=1, files=[pic],
                                            reactions=[{"name": "heart", "users": ["U01", "U02"], "count": 2}])],
            "general/2026-01-06.json": [say(1500, "U01", "worth the early start", thread_ts=ts(0), parent_user_id="U02")],
            "__uploads/F0AAAAAAA/pier.jpg": jpeg,  # slackdump's default (Mattermost) layout
            "D01/2026-01-05.json": [say(5, "U01", "", files=[doc])],
            "D01/attachments/F0BBBBBBB-notes.txt": "bring the tripod",  # its standard layout
            "__uploads/F0CCCCCCC/stray.bin": b"no message names it"})
        self.run_import()
        got = {r["id"]: r for r in self.of("slack")}
        first, reply = got[f"general:{ts(0)}"], got[f"general:{ts(1500)}"]
        self.assertEqual(first["meta"]["reactions"], [{"who": "me", "reaction": "❤️"}, {"who": "Theo Laurent", "reaction": "❤️"}])
        self.assertEqual(first["meta"]["attachments"], ["pier.jpg"], "a file's name, whatever reactions it has")
        self.assertEqual((reply["meta"]["reply_to"], reply["meta"]["reply_text"]), (f"general:{ts(0)}", "the pier at dawn\n[file: pier.jpg]"))
        for r, want in ((first, jpeg), (got[f"D01:{ts(5)}"], b"bring the tripod")):
            with self.subTest(r["id"]):
                f = Path(r["meta"]["files"][0])
                self.assertEqual((f if f.is_absolute() else self.corpus / f).read_bytes(), want, "copied out of the export")
        self.assertNotIn("__uploads/F0AAAAAAA/pier.jpg", self.unclaimed())

    def test_every_conversation_private_channels_dms_and_group_dms(self):
        self.files("slack/Lumen Labs export", {
            "users.json": USERS, "channels.json": [{"id": "C01", "name": "general", "members": ["U01", "U02", "U03"]}],
            "groups.json": [{"id": "G01", "name": "leads", "members": ["U01", "U02"]}],
            "dms.json": [{"id": "D01", "created": T, "members": ["U01", "U02"]}],
            "mpims.json": [{"id": "G02", "name": "mpdm-ada--theo--riley-1", "members": ["U01", "U02", "U03"]}],
            "general/2026-01-05.json": [say(0, "U01", "hi all")], "leads/2026-01-05.json": [say(1, "U02", "budget?")],
            "D01/2026-01-05.json": [say(2, "U02", "got a minute?"), say(3, "U01", "sure")],
            "mpdm-ada--theo--riley-1/2026-01-06.json": [say(4, "U03", "lunch?")]})
        self.run_import()
        names = {r["thread"]: (r["thread_name"], r["meta"].get("conversation"), r.get("participants")) for r in self.of("slack")}
        self.assertEqual(names, {"general": ("#general", "channel", None), "leads": ("#leads", "private channel", None),
                                 "D01": ("Theo Laurent", "dm", ["Ada Lovelace", "Theo Laurent"]),
                                 "mpdm-ada--theo--riley-1": ("Theo Laurent, Riley Park", "group dm", ["Ada Lovelace", "Theo Laurent", "Riley Park"])})

    def test_an_enterprise_grid_export_and_two_workspaces_side_by_side(self):
        # An org's export names its people in org_users.json; two exports in one folder each have their own users.json.
        self.files("slack/org", {"org_users.json": USERS, "channels.json": [{"id": "C01", "name": "general"}],
                                 "general/2026-01-05.json": [say(0, "U02", "org-wide hello", team="T01", user_team="T01")]})
        self.files("slack/two", {"Lumen/users.json": [{"id": "U01", "real_name": "Ada Lovelace"}, {"id": "U02", "real_name": "Theo Laurent"}],
                                 "Lumen/general/2026-01-05.json": [say(1, "U02", "from Lumen")],
                                 "Acme/users.json": [{"id": "U02", "real_name": "Wile E. Coyote"}],
                                 "Acme/general/2026-01-05.json": [say(2, "U02", "from Acme")]})
        self.run_import()
        by = {r["text"]: r["author"] for r in self.of("slack")}
        self.assertEqual(by, {"org-wide hello": "Theo Laurent", "from Lumen": "Theo Laurent", "from Acme": "Wile E. Coyote"})

    def test_days_without_lists_and_damaged_files_stop_nothing(self):
        # One member's export (or slackdump's) can have the days and nothing else: who wrote each is in the message.
        self.files("slack/member", {"channels/general/2026-01-05.json": [
            say(0, "U02", "no users.json here", user_profile={"real_name": "Theo Laurent", "display_name": "theo"})]})
        self.zip("slack/broken.zip", {
            "users.json": "[{not json", "channels.json": {"oops": True},
            "general/2026-01-05.json": [say(1, "U02", "still read", user_profile={"real_name": "Theo Laurent"}),
                                        "a string, not a message", {"type": "message", "text": "no ts"},
                                        say(2, "U02", "odd ts", ts="soon"), {"subtype": "bot_message", "text": "no type", "ts": ts(3), "username": "CI"}],
            "general/2026-01-06.json": "{cut short",
            "general/2026-01-07.json": {"not": "a list"}})
        self.run_import()
        by = {r["text"]: r for r in self.of("slack")}
        self.assertEqual(by["no users.json here"]["author"], "Theo Laurent")
        self.assertEqual(by["still read"]["author"], "Theo Laurent")
        self.assertIsNone(by["odd ts"].get("ts"), "a time that isn't one is left out, not 1970")
        self.assertEqual(by["no type"]["author"], "CI")
        self.assertIn("2026-01-06.json", self.unclaimed(), "the damaged day is listed as not read")

    def test_one_members_export_as_text(self):
        self.files("slack/member-export", {
            "channels/general.txt": "[2020-04-20 13:47:27] <jjordan> standup: in 5\n[2020-04-20 13:48:00] <ada_l> on my way\n"
                                    "[2020-04-20 13:49:00] <jjordan> agenda: one\ntwo\n[2020-04-20 13:50:00] <mcollins> re: agenda\n",
            "dms/ada_l-jjordan.txt": "[2020-04-21 09:00:00] <jjordan> hi\n[2020-04-21 09:01:00] <ada_l> hello\n",
            "files/plan.pdf": b"%PDF-1.4"})
        self.run_import()
        general = self.thread("slack", "general")
        self.assertEqual([(m["author"], m["text"]) for m in general],
                         [("jjordan", "standup: in 5"), ("me", "on my way"), ("jjordan", "agenda: one\ntwo"), ("mcollins", "re: agenda")])
        self.assertEqual((general[0]["ts"], general[0]["thread_name"]), ("2020-04-20T13:47:27Z", "#general"))
        self.assertEqual(len(self.thread("slack", "ada_l-jjordan")), 2)
        self.assertNotIn("whatsapp_export", self.recs, "not a WhatsApp chat")


# ---------------------------------------------------------------- WhatsApp

def ios(*lines):
    """An iPhone's _chat.txt: [date, time] Name: text, a narrow no-break space before AM/PM."""
    return "\r\n".join(f"{LRM if text.startswith(LRM) else ''}[{d}, {t.replace(' ', NNBSP)}] {who}: {text}"
                       for d, t, who, text in lines) + "\r\n"


def android(*lines):
    """Android's chat .txt: date, time - Name: text; a line WhatsApp wrote itself has no name."""
    return "\n".join(f"{d}, {t} - {who}: {text}" if who else f"{d}, {t} - {text}" for d, t, who, text in lines) + "\n"


class WhatsAppTests(Base):
    def test_an_iphone_chat_its_own_lines_deleted_and_edited(self):
        self.zip("whatsapp/WhatsApp Chat - Bea Quill.zip", {"_chat.txt": ios(
            ("1/2/24", "3:04:05 PM", "Bea Quill", f"{LRM}Messages and calls are end-to-end encrypted. No one outside of this "
                                                  "chat, not even WhatsApp, can read or listen to them."),
            ("1/2/24", "3:05:10 PM", "Bea Quill", "Are the leeks up yet?"),
            ("1/2/24", "3:06:00 PM", "Ada Lovelace", "Not yet.\r\nMaybe Friday, if it stays warm."),
            ("1/2/24", "3:07:00 PM", "Bea Quill", f"{LRM}image omitted"),
            ("1/2/24", "3:08:00 PM", "Bea Quill", f"{LRM}This message was deleted."),
            ("1/2/24", "3:09:00 PM", "Ada Lovelace", f"Lunch at 1? {LRM}<This message was edited>"),
            ("1/13/24", "9:00:00 AM", "Bea Quill", "Back from the allotment"))})
        self.run_import()
        msgs = self.thread("whatsapp_export", "Bea Quill")
        self.assertEqual([(m["author"], m["text"]) for m in msgs], [
            ("Bea Quill", "Are the leeks up yet?"), ("me", "Not yet.\nMaybe Friday, if it stays warm."),
            ("Bea Quill", "image omitted"), ("Bea Quill", "This message was deleted."), ("me", "Lunch at 1?"),
            ("Bea Quill", "Back from the allotment")])
        self.assertEqual((msgs[0]["ts"], msgs[-1]["ts"]), ("2024-01-02T20:05:10Z", "2024-01-13T14:00:00Z"))
        self.assertEqual(msgs[3]["meta"].get("tier"), "deleted", "left out where deleted mail is")
        self.assertTrue(msgs[4]["meta"].get("edited"))
        (notice,) = self.thread("whatsapp_export", "Bea Quill", "event")
        self.assertIn("end-to-end encrypted", notice["text"])
        self.assertNotEqual(notice.get("author"), "Bea Quill", "WhatsApp wrote it, not Bea")
        self.assertEqual(msgs[0]["participants"], ["Ada Lovelace", "Bea Quill"])

    def test_android_lines_whatsapp_wrote_are_its_own(self):
        # Android writes its own lines without a name; read before, the first was lost and the others were glued onto
        # the message before them.
        self.files("whatsapp", {"WhatsApp Chat with Cal Rowan.txt": android(
            ("1/2/24", "3:04 PM", None, "Messages and calls are end-to-end encrypted. No one outside of this chat, not even "
                                        "WhatsApp, can read or listen to them. Tap to learn more."),
            ("1/2/24", "3:05 PM", "Cal Rowan", "Seeds arrived"),
            ("1/2/24", "3:06 PM", "Cal Rowan", "<Media omitted>"),
            ("1/2/24", "3:07 PM", "Ada Lovelace", "Great: plant them Sunday"),
            ("1/2/24", "3:08 PM", None, "Your security code with Cal Rowan changed. Tap to learn more."),
            ("1/2/24", "3:09 PM", "Cal Rowan", "ok"))})
        self.run_import()
        msgs = self.thread("whatsapp_export", "Cal Rowan")
        self.assertEqual([(m["author"], m["text"]) for m in msgs], [
            ("Cal Rowan", "Seeds arrived"), ("Cal Rowan", "<Media omitted>"), ("me", "Great: plant them Sunday"), ("Cal Rowan", "ok")])
        self.assertEqual(msgs[0]["ts"], "2024-01-02T20:05:00Z")
        events = self.thread("whatsapp_export", "Cal Rowan", "event")
        self.assertEqual(len(events), 2)
        self.assertTrue(events[1]["text"].startswith("Your security code with Cal Rowan changed"))

    def test_an_android_group_its_changes_are_events_and_not_people(self):
        self.files("whatsapp", {"WhatsApp Chat with Allotment crew.txt": android(
            ("12/30/23", "9:00 AM", None, "Messages and calls are end-to-end encrypted. No one outside of this chat, not even "
                                          "WhatsApp, can read or listen to them. Tap to learn more."),
            ("12/30/23", "9:00 AM", None, 'Bea Quill created group "Allotment crew"'),
            ("12/30/23", "9:01 AM", None, "Bea Quill added you"),
            ("12/30/23", "9:02 AM", None, 'Bea Quill changed the subject from "Allotment: plot 4" to "Allotment crew"'),
            ("12/30/23", "9:03 AM", "Bea Quill", "Welcome!"),
            ("12/30/23", "9:04 AM", None, "Cal Rowan joined using this group's invite link"),
            ("12/30/23", "9:05 AM", "Cal Rowan", "hi all"),
            ("12/30/23", "9:06 AM", "Ada Lovelace", "Hello both"))})
        self.run_import()
        msgs = self.thread("whatsapp_export", "Allotment crew")
        self.assertEqual([m["text"] for m in msgs], ["Welcome!", "hi all", "Hello both"])
        self.assertEqual(msgs[0]["participants"], ["Ada Lovelace", "Bea Quill", "Cal Rowan"])
        self.assertEqual(len(self.thread("whatsapp_export", "Allotment crew", "event")), 5)

    def test_names_with_a_colon_in_them(self):
        # An iPhone group whose name has ": " in it writes its own lines under that name; a contact saved as "Ana: Work"
        # writes "Ana: Work: Dune". An LRM after the name marks WhatsApp's own lines and media.
        self.zip("whatsapp/WhatsApp Chat - Book Club.zip", {"_chat.txt": ios(
            ("1/2/24", "10:00:00 AM", "Book Club: 2024", f"{LRM}Messages and calls are end-to-end encrypted. No one outside "
                                                         "of this chat, not even WhatsApp, can read or listen to them."),
            ("1/2/24", "10:00:01 AM", "Book Club: 2024", f"{LRM}Bea Quill created group “Book Club: 2024”"),
            ("1/2/24", "10:01:00 AM", "Bea Quill", "First book?"),
            ("1/2/24", "10:02:00 AM", "Ana: Work", "Dune"),
            ("1/2/24", "10:03:00 AM", "Ana: Work", "Or: Emma"),
            ("1/2/24", "10:04:00 AM", "Ana: Work", f"{LRM}image omitted"))})
        self.files("whatsapp", {"WhatsApp Chat with Dev team.txt": android(
            ("1/2/24", "10:01 AM", "Kim: Office", "standup?"), ("1/2/24", "10:02 AM", "Kim: Office", "in 5"),
            ("1/2/24", "10:03 AM", "Kim: Office", "Note: room 4"), ("1/2/24", "10:04 AM", "Ada Lovelace", "Re: coming"))})
        self.run_import()
        club = self.thread("whatsapp_export", "Book Club")
        self.assertEqual([(m["author"], m["text"]) for m in club], [
            ("Bea Quill", "First book?"), ("Ana: Work", "Dune"), ("Ana: Work", "Or: Emma"), ("Ana: Work", "image omitted")])
        self.assertEqual(club[0]["participants"], ["Ana: Work", "Bea Quill"])
        self.assertEqual(len(self.thread("whatsapp_export", "Book Club", "event")), 2)
        dev = self.thread("whatsapp_export", "Dev team")
        self.assertEqual([(m["author"], m["text"]) for m in dev], [
            ("Kim: Office", "standup?"), ("Kim: Office", "in 5"), ("Kim: Office", "Note: room 4"), ("me", "Re: coming")])

    def test_day_first_dates_dots_and_24_hours(self):
        # A British phone: every day 12 or under, so the order of the messages tells day from month. A German one
        # writes dots, which are always day first, and names the file in German.
        self.files("whatsapp", {
            "WhatsApp Chat with Dee.txt": android(("11/01/2024", "15:04", "Dee", "Happy new year"),
                                                  ("02/02/2024", "09:15", "Ada Lovelace", "Thanks!"),
                                                  ("05/02/2024", "18:30", "Dee", "See you Friday")),
            "WhatsApp-Chat mit Emil.txt": android(("02.01.24", "15:04", "Emil", "Frohes neues Jahr"),
                                                  ("02.01.24", "15:05", "Emil", "<Medien ausgeschlossen>"),
                                                  ("03.01.24", "09:15", "Ada Lovelace", "Danke!"))})
        self.zip("whatsapp/WhatsApp Chat - Emil.zip", {"_chat.txt": ios(("04.01.24", "08:00:00", "Emil", "Guten Morgen"),
                                                                       ("04.01.24", "08:01:00", "Emil", "Wie geht's?"),
                                                                       ("05.01.24", "08:02:00", "Ada Lovelace", "Gut!"))})
        self.run_import()
        self.assertEqual([m["ts"] for m in self.thread("whatsapp_export", "Dee")],
                         ["2024-01-11T20:04:00Z", "2024-02-02T14:15:00Z", "2024-02-05T23:30:00Z"])
        emil = self.thread("whatsapp_export", "Emil")
        self.assertEqual([(m["ts"], m["text"]) for m in emil], [
            ("2024-01-02T20:04:00Z", "Frohes neues Jahr"), ("2024-01-02T20:05:00Z", "<Medien ausgeschlossen>"),
            ("2024-01-03T14:15:00Z", "Danke!"), ("2024-01-04T13:00:00Z", "Guten Morgen"),
            ("2024-01-04T13:01:00Z", "Wie geht's?"), ("2024-01-05T13:02:00Z", "Gut!")])

    def test_other_languages_clocks(self):
        # Spanish writes "p. m.", French Android "à" between the date and the time, and some Androids write seconds.
        self.files("whatsapp", {
            "Chat de WhatsApp con Fran.txt": android(("13/1/24", "3:04 p. m.", "Fran", "Hola"),
                                                     ("13/1/24", "3:05 p. m.", "Fran", "<Multimedia omitido>"),
                                                     ("14/1/24", "11:30 a. m.", "Ada Lovelace", "¡Hola!")),
            "Discussion WhatsApp avec Gil.txt": "02/01/2024 à 15:04 - Gil: Salut\n02/01/2024 à 15:05 - Gil: Ça va ?\n"
                                                "13/01/2024 à 09:00 - Ada Lovelace: Oui\n",
            "WhatsApp Chat with Hal.txt": android(("1/2/24", "15:04:05", "Hal", "with seconds"), ("1/2/24", "15:05:00", "Hal", "two"),
                                                  ("1/2/24", "15:06:00", "Ada Lovelace", "three"))})
        self.zip("whatsapp/WhatsApp Chat - Ines.zip", {"_chat.txt": ios(("13/1/24", "3:04:05 p.m.", "Ines", "Olá"),
                                                                       ("13/1/24", "3:05:00 p.m.", "Ines", "Tudo bem?"),
                                                                       ("13/1/24", "3:06:00 p.m.", "Ada Lovelace", "Sim"))})
        self.run_import()
        self.assertEqual([m["ts"] for m in self.thread("whatsapp_export", "Fran")],
                         ["2024-01-13T20:04:00Z", "2024-01-13T20:05:00Z", "2024-01-14T16:30:00Z"])
        self.assertEqual([(m["ts"], m["text"]) for m in self.thread("whatsapp_export", "Gil")],
                         [("2024-01-02T20:04:00Z", "Salut"), ("2024-01-02T20:05:00Z", "Ça va ?"), ("2024-01-13T14:00:00Z", "Oui")])
        self.assertEqual(self.thread("whatsapp_export", "Hal")[0]["ts"], "2024-01-02T20:04:05Z")
        self.assertEqual(self.thread("whatsapp_export", "Ines")[0]["ts"], "2024-01-13T20:04:05Z")
        self.assertFalse([r for r in self.of("imported_documents") if "WhatsApp" in r.get("title", "")])

    def test_finnish_croatian_korean_and_russian(self):
        # Finnish writes "klo" and dots in the time; Croatian a dot after each part of the date and no comma; Korean
        # puts 오후 (PM) before the time; a Russian phone names the file "Чат WhatsApp с ...".
        self.files("whatsapp", {
            "WhatsApp Chat with Aino.txt": "13.1.2024 klo 21.25 - Aino: Hei\n13.1.2024 klo 21.26 - Aino: Mitä kuuluu?\n"
                                           "14.1.2024 klo 8.05 - Ada Lovelace: Hyvää\n",
            "WhatsApp Chat with Ivo.txt": "13. 1. 2024. 21:25 - Ivo: Bok\n13. 1. 2024. 21:26 - Ivo: Kako si?\n14. 1. 2024. 08:05 - Ada Lovelace: Dobro\n",
            "Чат WhatsApp с Олег.txt": android(("13.01.2024", "21:25", "Олег", "Привет"), ("13.01.2024", "21:26", "Олег", "Как дела?"),
                                               ("14.01.2024", "08:05", "Ada Lovelace", "Хорошо"))})
        self.zip("whatsapp/WhatsApp Chat - 민준.zip", {"_chat.txt": "[2024. 1. 13. 오후 9:25:00] 민준: 안녕\n[2024. 1. 13. 오후 9:26:00] 민준: 잘 지내?\n"
                                                                    "[2024. 1. 14. 오전 8:05:00] Ada Lovelace: 응\n"})
        self.run_import()
        for who in ("Aino", "Ivo", "Олег", "민준"):
            self.assertEqual([m["ts"] for m in self.thread("whatsapp_export", who)],
                             ["2024-01-14T02:25:00Z", "2024-01-14T02:26:00Z", "2024-01-14T13:05:00Z"], who)

    def test_a_chat_exported_with_its_media(self):
        # With media, the iPhone's zip has each file next to _chat.txt, named in an <attached: ...> line; Android's names
        # it before "(file attached)", its caption on the line after.
        self.zip("whatsapp/WhatsApp Chat - Jo.zip", {
            "_chat.txt": ios(("1/2/24", "3:04:05 PM", "Jo", f"{LRM}<attached: 00000012-PHOTO-2024-01-02-15-04-05.jpg>"),
                             ("1/2/24", "3:05:00 PM", "Jo", "nice view"), ("1/2/24", "3:06:00 PM", "Ada Lovelace", "wow"),
                             ("1/2/24", "3:07:00 PM", "Jo", f"2015-08-04-PHOTO-00004762.jpg <{LRM}attached>")),  # as before 2017
            "00000012-PHOTO-2024-01-02-15-04-05.jpg": b"\xff\xd8\xff photo", "2015-08-04-PHOTO-00004762.jpg": b"\xff\xd8\xff old"})
        self.zip("whatsapp/WhatsApp Chat with Kit.zip", {
            "WhatsApp Chat with Kit.txt": android(("1/2/24", "3:04 PM", "Kit", "IMG-20240102-WA0001.jpg (file attached)\nLook at this"),
                                                  ("1/2/24", "3:05 PM", "Kit", "PTT-20240102-WA0002.opus (file attached)"),
                                                  ("1/2/24", "3:06 PM", "Ada Lovelace", "wow")),
            "IMG-20240102-WA0001.jpg": b"\xff\xd8\xff photo two", "PTT-20240102-WA0002.opus": b"OggS voice"})
        self.run_import()
        jo = self.thread("whatsapp_export", "Jo")
        self.assertEqual(len(jo[0].get("meta", {}).get("files") or []), 1, jo[0])
        self.assertTrue((self.corpus / jo[0]["meta"]["files"][0]).read_bytes().startswith(b"\xff\xd8"))
        self.assertEqual(len(jo[3].get("meta", {}).get("files") or []), 1, jo[3])
        kit = self.thread("whatsapp_export", "Kit")
        self.assertIn("Look at this", kit[0]["text"])
        self.assertEqual([len(m.get("meta", {}).get("files") or []) for m in kit], [1, 1, 0])
        self.assertNotIn("whatsapp_files", self.recs, "each file goes with its message, not on its own")

    def test_a_short_chat_and_one_with_a_long_first_message(self):
        long = "\n".join(f"line {i} of a long recipe" for i in range(60))
        self.files("whatsapp", {"WhatsApp Chat with Lou.txt": android(("1/2/24", "3:04 PM", "Lou", "Hi"), ("1/2/24", "3:05 PM", "Ada Lovelace", "Hey"))})
        self.zip("whatsapp/WhatsApp Chat - Max.zip", {"_chat.txt": ios(("1/2/24", "3:04:05 PM", "Max", long),
                                                                      ("1/2/24", "3:05:00 PM", "Ada Lovelace", "thanks"),
                                                                      ("1/2/24", "3:06:00 PM", "Max", "enjoy"))})
        self.run_import()
        self.assertEqual([m["text"] for m in self.thread("whatsapp_export", "Lou")], ["Hi", "Hey"])
        self.assertEqual(len(self.thread("whatsapp_export", "Max")), 3)
        self.assertEqual(self.thread("whatsapp_export", "Max")[0]["text"].count("\n"), 59)

    def test_chats_named_some_other_way_stay_apart(self):
        # A _chat.txt in a zip renamed by hand, and two chats as loose files whose names don't say WhatsApp in English.
        self.zip("whatsapp/nora.zip", {"_chat.txt": ios(("1/2/24", "3:04:05 PM", "Nora", "one"), ("1/2/24", "3:05:00 PM", "Nora", "two"),
                                                        ("1/2/24", "3:06:00 PM", "Nora", "three"))})
        self.files("whatsapp", {"Conversa do WhatsApp com Olga.txt": android(("1/2/24", "3:04 PM", "Olga", "a"), ("1/2/24", "3:05 PM", "Olga", "b"),
                                                                            ("1/2/24", "3:06 PM", "Olga", "c")),
                                "Chat WhatsApp con Pia.txt": android(("1/2/24", "3:04 PM", "Pia", "x"), ("1/2/24", "3:05 PM", "Pia", "y"),
                                                                     ("1/2/24", "3:06 PM", "Pia", "z"))})
        self.run_import()
        self.assertEqual(sorted({m["thread"] for m in self.of("whatsapp_export")}), ["Olga", "Pia", "nora"])


# ---------------------------------------------------------------- Reddit

RD = "reddit/export_ada_l_20261001/"
COMMENTS = ["id", "permalink", "date", "ip", "subreddit", "gildings", "link", "parent", "body", "media"]
POSTS = ["id", "permalink", "date", "ip", "subreddit", "gildings", "title", "url", "body"]
MESSAGES = ["id", "permalink", "thread_id", "date", "ip", "from", "to", "subject", "body"]


class RedditTests(Base):
    def test_bodies_over_many_lines_link_posts_and_both_message_files(self):
        body = 'First line, with a comma.\n\n> a quote\n\nAnd "quotes" ✓'
        self.files(RD, {
            "comments.csv": csv_text(COMMENTS, [["c1", "https://www.reddit.com/r/tides/comments/p1/spring/c1/", "2024-01-02 03:04:05 UTC",
                                                 "", "tides", "0", "https://www.reddit.com/r/tides/comments/p1/spring/", "t3_p1", body, ""]]),
            "posts.csv": csv_text(POSTS, [["p1", "https://www.reddit.com/r/tides/comments/p1/spring/", "2024-01-01 10:00:00 UTC", "", "tides", "0",
                                           "Why are spring tides higher?", "https://www.reddit.com/r/tides/comments/p1/spring/", "Self post\nbody"],
                                          ["p2", "https://www.reddit.com/r/baking/comments/p2/loaf/", "2024-01-03 10:00:00 UTC", "", "baking", "0",
                                           "My first loaf", "https://i.redd.it/loaf.jpg", ""]]),
            "messages.csv": csv_text(MESSAGES, [["m1", "https://www.reddit.com/message/messages/m1", "t1", "2024-01-04 10:00:00 UTC", "",
                                                 "grace_h", "ada_l", "re: tides", "Thanks!\nSee you"]]),
            "messages_archive.csv": csv_text(MESSAGES, [["m0", "https://www.reddit.com/message/messages/m0", "t1", "2023-01-04 10:00:00 UTC", "",
                                                         "ada_l", "grace_h", "tides", "Old one"],
                                                        ["m1", "https://www.reddit.com/message/messages/m1", "t1", "2024-01-04 10:00:00 UTC", "",
                                                         "grace_h", "ada_l", "re: tides", "Thanks!\nSee you"]])})
        self.run_import()
        posts = {r["id"]: r for r in self.of("reddit", "post")}
        self.assertEqual(posts["c1"]["text"], body)
        self.assertEqual(posts["c1"]["ts"], "2024-01-02T03:04:05Z")
        self.assertEqual(posts["p1"]["text"], "Why are spring tides higher?\nSelf post\nbody")
        self.assertIn("https://i.redd.it/loaf.jpg", posts["p2"]["text"] + posts["p2"].get("url", ""))
        msgs = {r["id"]: r for r in self.of("reddit", "message")}
        self.assertEqual(sorted(msgs), ["m0", "m1"], "a message in both files is kept once")
        self.assertEqual((msgs["m0"]["author"], msgs["m1"]["author"], msgs["m1"]["text"]), ("me", "grace_h", "Thanks!\nSee you"))

    def test_deleted_posts_short_rows_and_rows_without_ids(self):
        # A row cut short (fewer fields than the header) once stopped the whole import.
        self.files(RD, {
            "comments.csv": "\r\n".join([",".join(COMMENTS),
                                         "c1,https://www.reddit.com/r/tides/comments/p1/x/c1/,2024-01-02 03:04:05 UTC,,tides,0,,,[deleted],",
                                         "c2,https://www.reddit.com/r/tides/comments/p1/x/c2/,2024-01-02 03:05:05 UTC,,tides,0,,,[removed],",
                                         ",,2024-01-02 03:06:05 UTC,,tides"]) + "\r\n",
            "posts.csv": csv_text(POSTS, [["p1", "https://www.reddit.com/r/tides/comments/p1/x/", "2024-01-01 10:00:00 UTC", "", "tides", "0",
                                           "A title", "", "[deleted]"]])})
        self.run_import()
        posts = {r["id"]: r for r in self.of("reddit", "post")}
        self.assertEqual(posts["c1"]["meta"].get("tier"), "deleted")
        self.assertEqual(posts["c2"]["meta"].get("tier"), "deleted")
        self.assertNotEqual(posts["p1"]["meta"].get("tier"), "deleted", "a post whose title is kept is still yours")
        self.assertTrue({"c1", "c2", "p1"} <= set(posts))

    def test_the_2026_layout_drafts_and_profile_posts(self):
        # Since 2025: no messages.csv, only messages_archive.csv, its links written with one slash and names with "u/";
        # comments.csv has more gildings columns; drafts.csv dates rows "created"; a post to your profile is in "u_<you>".
        comments = ["id", "permalink", "date", "ip", "subreddit", "gildings", "gildings_silver", "gildings_supergold", "link", "parent", "body", "media"]
        self.files(RD, {
            "comments.csv": csv_text(comments, [["c1", "https://www.reddit.com/r/tides/comments/p1/x/c1/", "2026-03-09 15:59:23 UTC", "", "tides",
                                                 "0", "0", "0", "https://www.reddit.com/r/tides/comments/p1/x/", "t3_p1", "nice", ""]]),
            "posts.csv": csv_text(POSTS, [["p9", "https://www.reddit.com/user/ada_l/comments/p9/hello/", "2026-03-09 16:00:00 UTC", "", "u_ada_l",
                                           "0", "Hello from my profile", "https://www.reddit.com/user/ada_l/comments/p9/hello/", ""],
                                          ["p8", "https://www.reddit.com/r/tides/comments/p8/x/", "2026-03-09 17:00:00 UTC", "", "tides", "0",
                                           "[deleted by user]", "", "[deleted]"]]),
            "messages_archive.csv": csv_text(MESSAGES, [["m5", "https:/www.reddit.com/message/messages/m5", "t5", "2026-03-10 10:00:00 UTC", "",
                                                         "/u/ada_l", "u/grace_h", "tides", "Mine"]]),
            "drafts.csv": csv_text(["id", "title", "body", "kind", "created", "spoiler", "nsfw", "original_content", "content_category",
                                    "flair_id", "flair_text", "send_replies", "subreddit", "is_public_link"],
                                   [["d1", "Half a thought", "to finish later", "self", "2026-03-11 09:00:00 UTC", "false", "false", "false",
                                     "", "", "", "true", "tides", "false"]]),
            "post_votes.csv": "id,permalink,direction\r\np1,https://www.reddit.com/r/tides/comments/p1/x/,none\r\n",
            "checkfile.csv": "filename,sha256\r\ncomments.csv,0123abcd\r\n"})
        self.run_import()
        got = {r["id"]: r for r in self.of("reddit")}
        self.assertEqual(got["c1"]["meta"]["post"], "https://www.reddit.com/r/tides/comments/p1/x/")
        self.assertEqual((got["p9"]["thread_name"], got["p9"]["text"]), ("u/ada_l", "Hello from my profile"))
        self.assertEqual(got["p8"]["meta"].get("tier"), "deleted")
        self.assertEqual((got["m5"]["author"], got["m5"]["url"]), ("me", "https://www.reddit.com/message/messages/m5"))
        self.assertEqual((got["d1"]["ts"], got["d1"]["meta"].get("tier")), ("2026-03-11T09:00:00Z", "unsent"), "a draft was never posted")
        self.assertIn("took back a vote", got["post_votes.csv:p1"]["text"])
        self.assertFalse([r for r in self.of("reddit_other") if "checkfile" in r["meta"]["file"]], "a list of the export's own files")

    def test_header_files_logins_and_settings(self):
        # comment_headers.csv and the like are comments.csv without the bodies: the same comments, not more of them.
        # ip_logs.csv is when and where the account was signed in to: left out, as other exports' login files are.
        self.files(RD, {
            "comments.csv": csv_text(COMMENTS, [["c1", "https://www.reddit.com/r/tides/comments/p1/x/c1/", "2024-01-02 03:04:05 UTC", "",
                                                 "tides", "0", "", "", "hello", ""]]),
            "comment_headers.csv": csv_text(COMMENTS[:-2], [["c1", "https://www.reddit.com/r/tides/comments/p1/x/c1/", "2024-01-02 03:04:05 UTC",
                                                             "", "tides", "0", "", ""]]),
            "posts.csv": csv_text(POSTS, [["p1", "https://www.reddit.com/r/tides/comments/p1/x/", "2024-01-01 10:00:00 UTC", "", "tides", "0", "T", "", "b"]]),
            "post_headers.csv": csv_text(POSTS[:-1], [["p1", "https://www.reddit.com/r/tides/comments/p1/x/", "2024-01-01 10:00:00 UTC", "", "tides", "0", "T", ""]]),
            "messages.csv": csv_text(MESSAGES, [["m1", "", "t1", "2024-01-04 10:00:00 UTC", "", "grace_h", "ada_l", "s", "b"]]),
            "message_headers.csv": csv_text(MESSAGES[:-1], [["m1", "", "t1", "2024-01-04 10:00:00 UTC", "", "grace_h", "ada_l", "s"]]),
            "ip_logs.csv": "date,ip\r\n2024-01-02 03:04:05 UTC,192.0.2.1\r\n",
            "user_preferences.csv": "preference,value\r\nlang,en\r\nshow_nsfw,false\r\n",
            "statistics.csv": "statistic,value\r\naccount name,ada_l\r\n"})
        self.run_import()
        self.assertEqual(sorted(r["id"] for r in self.of("reddit")), ["c1", "m1", "p1"])
        other = self.of("reddit_other")
        self.assertFalse([r for r in other if "headers" in r["meta"]["file"]], "the header files say nothing comments.csv doesn't")
        self.assertFalse([r for r in other if "ip_logs" in r["meta"]["file"]])
        self.assertTrue([r for r in other if "user_preferences" in r["meta"]["file"]], "settings are kept")
        self.assertFalse({x for x in self.unclaimed() if x.endswith("headers.csv")})


# ---------------------------------------------------------------- Loose mail

def eml(mid, subject="Hello", body="Hi Ada.", frm="Grace Hopper <grace@example.com>", to="Ada Lovelace <ada@example.com>",
        date="Tue, 02 Jan 2024 15:04:05 +0000", ctype="text/plain; charset=UTF-8", headers=""):
    head = f"Message-ID: <{mid}@example.com>\r\nFrom: {frm}\r\nTo: {to}\r\nSubject: {subject}\r\nDate: {date}\r\n" + headers
    return (head + f"MIME-Version: 1.0\r\nContent-Type: {ctype}\r\n\r\n").encode() + (body if isinstance(body, bytes) else body.encode()) + b"\r\n"


def emlx(raw, partial=False):
    """Mail's own message file: the message's length in bytes on a line, the message, then a plist."""
    plist = b'<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict><key>flags</key><integer>8590195713</integer></dict></plist>\n'
    return f"{len(raw)}\n".encode() + raw + plist


class LooseMailTests(Base):
    def test_eml_files_in_folders_and_old_encodings(self):
        self.files("old_mail", {
            "Inbox/hello.eml": eml("e1"),
            "Inbox/latin1.eml": eml("e2", subject="=?ISO-8859-1?Q?Caf=E9_ma=F1ana?=", body="Nos vemos en el caf=E9.",
                                    ctype="text/plain; charset=ISO-8859-1", headers="Content-Transfer-Encoding: quoted-printable\r\n"),
            # 8-bit Windows text that never said its charset: Python reads it as ASCII, every é a "?"
            "Inbox/nocharset.eml": eml("e3", body=b"Caf\xe9 \x93quoted\x94", ctype="text/plain",
                                       headers="Content-Transfer-Encoding: 8bit\r\n"),
            "Sent/reply.eml": eml("e4", frm="Ada <ada.alias@work.example>", to="Grace Hopper <grace@example.com>", subject="Re: Hello"),
            "Inbox/attached.eml": eml("e5", subject="CV", ctype='multipart/mixed; boundary="XX"', body=(
                "--XX\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nSee attached\r\n--XX\r\nContent-Type: application/pdf\r\n"
                "Content-Disposition: attachment; filename*=UTF-8''r%C3%A9sum%C3%A9.pdf\r\nContent-Transfer-Encoding: base64\r\n\r\n"
                "JVBERi0xLjQK\r\n--XX--")),
            "Inbox/forwarded.eml": eml("e6", subject="Fwd: plans", ctype='multipart/mixed; boundary="XX"', body=(
                "--XX\r\nContent-Type: message/rfc822\r\n\r\nFrom: Alan <alan@example.org>\r\nSubject: plans\r\n\r\n"
                "The inner message's words\r\n--XX--")),
            "Inbox/garbage.eml": b"\x00\x01\x02 not mail at all \xff\xfe"})
        self.run_import()
        got = {r["id"]: r for r in self.of("old_mail", "email")}
        self.assertTrue({"<e1@example.com>", "<e2@example.com>", "<e3@example.com>", "<e4@example.com>", "<e5@example.com>",
                         "<e6@example.com>"} <= set(got), sorted(got))
        self.assertEqual(got["<e2@example.com>"]["text"], "Café mañana\nNos vemos en el café.")
        self.assertIn("Café “quoted”", got["<e3@example.com>"]["text"])
        self.assertEqual((got["<e4@example.com>"]["author"], got["<e4@example.com>"]["is_me"]), ("me", True), "in Sent: yours")
        self.assertEqual(got["<e5@example.com>"]["meta"]["attachments"], ["résumé.pdf"])
        self.assertIn("The inner message's words", got["<e6@example.com>"]["text"])
        self.assertEqual(got["<e1@example.com>"]["meta"]["folder"], "Inbox")

    def test_mails_own_emlx_files_from_a_copied_mail_folder(self):
        root = "old_mac/Mail/V10/0A1B2C3D-1111-2222-3333-444455556666/"
        self.files("", {
            root + "INBOX.mbox/7E6D/Data/0/1/Messages/12.emlx": emlx(eml("x1", body="In the inbox")),
            root + "INBOX.mbox/7E6D/Data/0/1/Messages/13.partial.emlx": emlx(eml("x2", body="Partly downloaded")),
            root + "Sent Messages.mbox/7E6E/Data/Messages/14.emlx": emlx(eml("x3", frm="Ada <ada.alias@work.example>", body="Sent by me")),
            root + "INBOX.mbox/Info.plist": "<plist/>"})
        self.run_import()
        got = {r["id"]: r for r in self.of("old_mac", "email")}
        self.assertEqual(sorted(got), ["<x1@example.com>", "<x2@example.com>", "<x3@example.com>"])
        self.assertNotIn("plist", got["<x1@example.com>"]["text"], "the plist after the message isn't part of it")
        self.assertEqual(got["<x1@example.com>"]["meta"]["folder"], "INBOX")
        self.assertTrue(got["<x3@example.com>"]["is_me"], "in Sent Messages: yours")

    def test_thunderbird_mailboxes_have_no_extension(self):
        sep = "From - Tue Jan  2 15:04:05 2024\r\nX-Mozilla-Status: 0001\r\nX-Mozilla-Status2: 00000000\r\n"
        self.files("thunderbird", {
            "Local Folders/Inbox": sep.encode() + eml("t1", body="first") + b"\r\n" + sep.encode() + eml("t2", body="second"),
            "Local Folders/Inbox.msf": "// <!-- <mdb:mork:z v=\"1.4\"/> -->\n",
            "Local Folders/Sent": sep.encode() + eml("t3", frm="Ada <ada.alias@work.example>", body="mine"),
            "Local Folders/Inbox.sbd/Receipts": sep.encode() + eml("t4", body="a receipt"),
            "Local Folders/Trash": sep.encode() + eml("t5", body="binned"),
            "Local Folders/msgFilterRules.dat": 'version="9"\n'})
        self.run_import()
        got = {r["id"]: r for r in self.of("thunderbird", "email")}
        self.assertEqual(sorted(got), ["<t1@example.com>", "<t2@example.com>", "<t3@example.com>", "<t4@example.com>", "<t5@example.com>"])
        self.assertTrue(got["<t3@example.com>"]["is_me"])
        self.assertEqual(got["<t5@example.com>"]["meta"].get("tier"), "deleted")
        self.assertEqual(got["<t4@example.com>"]["meta"]["folder"], "Receipts")

    def test_an_outlook_for_mac_archive(self):
        # An .olm is a zip: a message an XML file, in com.microsoft.__Messages/<folder>/, its attachments beside it.
        def olm(mid, subject, frm, to, body, sent="2022-05-26T17:55:40", attachments=""):
            who = lambda tag, a, n: (f'<{tag}><emailAddress OPFContactEmailAddressAddress="{a}" OPFContactEmailAddressName="{n}" '  # noqa: E731
                                     f'OPFContactEmailAddressType="0"/></{tag}>')
            return ('<?xml version="1.0" encoding="UTF-8"?>\n<emails elementCount="1"><email xml:space="preserve">'
                    f"<OPFMessageCopySubject>{subject}</OPFMessageCopySubject><OPFMessageCopyMessageID>&lt;{mid}@example.com&gt;</OPFMessageCopyMessageID>"
                    + who("OPFMessageCopyFromAddresses", *frm) + who("OPFMessageCopyToAddresses", *to)
                    + f"<OPFMessageCopySentTime>{sent}</OPFMessageCopySentTime><OPFMessageCopyHTMLBody>{body}</OPFMessageCopyHTMLBody>"
                    + attachments + "</email></emails>")
        box = "Accounts/ada@example.com/com.microsoft.__Messages/"
        self.zip("outlook/Outlook for Mac Archive.olm", {
            box + "Inbox/message_00001.xml": olm("o1", "Invoice", ("grace@example.com", "Grace Hopper"), ("ada@example.com", "Ada Lovelace"),
                                                 "&lt;html&gt;&lt;body&gt;&lt;p&gt;Please find the invoice, café.&lt;/p&gt;&lt;/body&gt;&lt;/html&gt;",
                                                 attachments='<OPFMessageCopyAttachmentList><messageAttachment OPFAttachmentName="invoice.pdf" '
                                                 'OPFAttachmentContentType="application/pdf" OPFAttachmentURL="' + box
                                                 + 'Inbox/com.microsoft.__Attachments/invoice_0000"/></OPFMessageCopyAttachmentList>'),
            box + "Inbox/com.microsoft.__Attachments/invoice_0000": b"%PDF-1.4",
            box + "Sent Items/message_00002.xml": olm("o2", "Re: Invoice", ("ada.alias@work.example", "Ada"), ("grace@example.com", "Grace Hopper"),
                                                      "Thanks!"),
            box + "Deleted Items/message_00003.xml": "<emails><email><OPFMessageCopySubject>cut sh",
            "Accounts/ada@example.com/Contacts.xml": "<contacts/>"})
        self.run_import()
        got = {r["id"]: r for r in self.of("outlook", "email")}
        self.assertEqual(sorted(got), ["<o1@example.com>", "<o2@example.com>"])
        inv = got["<o1@example.com>"]
        self.assertEqual((inv["author"], inv["ts"], inv["meta"]["attachments"], inv["meta"]["folder"]),
                         ("Grace Hopper", "2022-05-26T17:55:40Z", ["invoice.pdf"], "Inbox"))
        self.assertIn("Please find the invoice, café.", inv["text"])
        self.assertTrue(got["<o2@example.com>"]["is_me"], "in Sent Items: yours")
        self.assertNotIn("invoice_0000", self.unclaimed(), "an attachment goes with its message")
        self.assertIn("message_00003.xml", self.unclaimed(), "the damaged one is listed as not read")

    def test_a_message_file_in_another_sources_folder_isnt_its_mail(self):
        # An .eml sent in a WhatsApp chat (imports/whatsapp/) read as mail would replace what whatsapp.py read from this
        # Mac (source whatsapp); one in imports/mail/ what Mail.app's connector read (source mail).
        (self.corpus / "normalized").mkdir(parents=True)
        (self.corpus / "normalized/whatsapp.jsonl").write_text('{"id": "S1", "source": "whatsapp", "kind": "message", "text": "kept"}\n')
        (self.corpus / "normalized/mail.jsonl").write_text('{"id": "<m1@x>", "source": "mail", "kind": "email", "text": "kept"}\n')
        self.zip("whatsapp/WhatsApp Chat - Uma.zip", {
            "_chat.txt": ios(("1/2/24", "3:04:05 PM", "Uma", f"{LRM}<attached: 00000013-receipt.eml>"), ("1/2/24", "3:05:00 PM", "Uma", "got it?"),
                             ("1/2/24", "3:06:00 PM", "Ada Lovelace", "yes")),
            "00000013-receipt.eml": eml("w1", body="a receipt")})
        self.files("mail", {"note.eml": eml("w2")})
        self.run_import()
        self.assertEqual((self.corpus / "normalized/whatsapp.jsonl").read_text().count("kept"), 1)
        self.assertEqual((self.corpus / "normalized/mail.jsonl").read_text().count("kept"), 1)
        self.assertEqual(len(self.thread("whatsapp_export", "Uma")[0]["meta"]["files"]), 1, "the .eml goes with its message")

    def test_eml_beside_an_mbox_survives_a_second_run(self):
        # The second run keeps an unchanged mailbox as it was read; its loose .eml must not replace what it holds.
        self.files("work", {"Archive.mbox": b"From a@b.c Tue Jan  2 15:04:05 2024\r\n" + eml("b1", body="in the mbox"),
                            "one.eml": eml("b2", body="loose")})
        self.run_import()
        first = sorted(r["id"] for r in self.of("work"))
        self.assertEqual(first, ["<b1@example.com>", "<b2@example.com>"])
        self.run_import()
        self.assertEqual(sorted(r["id"] for r in self.of("work")), first)


# ---------------------------------------------------------------- vCards

def card(*lines, version="3.0", end="\r\n"):
    return end.join(["BEGIN:VCARD", f"VERSION:{version}", *lines, "END:VCARD"]) + end


class VCardTests(Base):
    def contacts(self, source="vcard_contacts"):
        return {r["title"]: r for r in self.of(source, "contact")}

    def test_google_icloud_and_vcard_4(self):
        google = card("FN:Grace Hopper", "N:Hopper;Grace;;;", "EMAIL;TYPE=INTERNET;TYPE=HOME:grace@example.com",
                      "TEL;TYPE=CELL:+1 555-0100", "item1.URL:http\\://grace.example.com", "item1.X-ABLabel:",
                      "ADR;TYPE=HOME:;;1 Navy Way;Arlington;VA;22201;US", "CATEGORIES:myContacts")
        icloud = card("PRODID:-//Apple Inc.//iPhone OS 17.0//EN", "N:Johnson;Katherine;;;", "FN:Katherine Johnson",
                      "item1.EMAIL;type=INTERNET;type=pref:kj@example.com", "item1.X-ABLabel:_$!<Other>!$_",
                      "PHOTO;ENCODING=b;TYPE=JPEG:/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAMCAgMCAgMDAwMEAwMEBQgFBQQEBQoHBwYH",
                      " DAoMDAsKCwsNDhIQDQ4RDhELCxAWEBETFBUVFQwPFxgWFBgSFBUU", "NOTE:A note folded over", "  two lines")
        v4 = card("FN:Alan Turing", 'TEL;VALUE=uri;TYPE="cell,voice":tel:+44-20-7946-0958', "EMAIL;PREF=1:mailto:alan@example.org",
                  "BDAY:--0623", version="4.0", end="\n")
        no_fn = card("N:Lovelace;Ada;;;", "TEL;CELL;PREF:+44 7700 900123", "PHOTO;ENCODING=BASE64;JPEG:/9j/4AAQSkZJRgABAQAAAQABAAD",
                     "    FBQUFBQUFBQUFBQUFBQUFBQUFBQ", "    AAEQgAAQABAwEiAAIRAQMRAf", "", version="2.1")
        self.files("contacts", {"Google Contacts.vcf": google, "iCloud vCard.vcf": icloud + v4, "phone.vcf": no_fn.rstrip("\r\n")})
        self.run_import()
        got = self.contacts()
        self.assertEqual(sorted(got), ["Ada Lovelace", "Alan Turing", "Grace Hopper", "Katherine Johnson"])
        self.assertIn("url: http://grace.example.com", got["Grace Hopper"]["text"])
        self.assertIn("1 Navy Way, Arlington, VA, 22201, US", got["Grace Hopper"]["text"])
        self.assertIn("tel: +44-20-7946-0958", got["Alan Turing"]["text"])
        self.assertIn("email: alan@example.org", got["Alan Turing"]["text"])
        self.assertIn("A note folded over two lines", got["Katherine Johnson"]["text"])
        self.assertNotIn("9j", json.dumps(self.recs["vcard_contacts"]), "a photo's data isn't text")

    def test_utf16_and_windows_encoded_exports(self):
        # An old Mac's Address Book wrote vCards in UTF-16; a 2.1 card from an old phone or Outlook can be 8-bit Windows
        # text. Read as UTF-8, neither had a card in it.
        self.files("contacts", {
            "Address Book.vcf": b"\xfe\xff" + card("N:Martí;José;;;", "FN:José Martí", "TEL:+34 600 000 000").encode("utf-16-be"),
            "le.vcf": b"\xff\xfe" + card("FN:Zoë Brontë", "EMAIL:zoe@example.net").encode("utf-16-le"),
            "outlook.vcf": card("N:Müller;Jürgen", "FN:Jürgen Müller", "TEL;WORK;VOICE:+49 30 123456", version="2.1").encode("cp1252"),
            # Address Book 4 (Mac OS X 10.4): UTF-16 without a byte order mark, lines ended with CR alone
            "Tiger.vcf": card("FN:Øyvind Ås", "BDAY;X-APPLE-OMIT-YEAR=1604:1604-12-12", end="\r").encode("utf-16-be")})
        self.run_import()
        self.assertEqual(sorted(self.contacts()), ["José Martí", "Jürgen Müller", "Zoë Brontë", "Øyvind Ås"])
        self.assertIn("bday: --12-12", self.contacts()["Øyvind Ås"]["text"], "a birthday without a year")

    def test_two_people_with_one_name_and_nothing_else_in_common(self):
        a = card("FN:Quill Ashby", "ORG:Acme", "NOTE:the plumber")
        b = card("FN:Quill Ashby", "ORG:Globex", "NOTE:from school")
        self.files("contacts", {"all.vcf": a + b + a})
        self.run_import()
        self.assertEqual(len(self.of("vcard_contacts")), 2, "two people, the first one listed twice")

    def test_the_resolver_reads_utf16_vcards_too(self):
        self.files("contacts", {"Address Book.vcf": b"\xfe\xff" + card("FN:José Martí", "TEL:+1 212 555 0199").encode("utf-16-be")})
        env = {**os.environ, "HOME": str(self.home), "CORPUS_DIR": str(self.corpus)}
        r = subprocess.run([sys.executable, "-c", "import contacts; print(contacts.Resolver().name('+12125550199'))"],
                           cwd=CONNECTORS, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.stdout.strip(), "José Martí", r.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
