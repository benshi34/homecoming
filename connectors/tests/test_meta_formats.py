"""Meta's exports as they come: Instagram, Facebook and Messenger in the layouts Meta has used since 2019 (messages/…
before 2022, your_activity_across_facebook/… in 2022-23, your_instagram_activity/…, your_facebook_activity/…,
connections/… and personal_information/… since), JSON and HTML, a zip in parts, two exports side by side, the
latin-1 mojibake, emoji, times in seconds or milliseconds, attachments of every kind, unsent messages, deleted
accounts, and empty or broken files. Exports are made up here; the importer runs as the app runs it.

Run: python3 -m unittest discover -s connectors/tests -p 'test_*.py'
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path

CONNECTORS = Path(__file__).resolve().parents[1]
T = 1790000000  # 2026-09-21T14:13:20Z


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")


def moji(s):
    """Text as Meta writes it: its UTF-8 bytes, each read as a latin-1 character ("é" -> "Ã©")."""
    return s.encode("utf-8").decode("latin-1")


def data(x):
    return x if isinstance(x, (str, bytes)) else json.dumps(x)


def thread(title, people, messages, **extra):
    return {"participants": [{"name": p} for p in people], "messages": messages, "title": title,
            "is_still_participant": True, **extra}


def msg(sender, t, content=None, **extra):
    m = {"sender_name": sender, "timestamp_ms": t * 1000, **extra}
    if content is not None:
        m["content"] = content
    return m


class Base(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.home, self.corpus = Path(t.name) / "home", Path(t.name) / "corpus"
        self.imports = self.corpus / "imports"
        self.home.mkdir()
        self.imports.mkdir(parents=True)
        self.me(["Ada Lovelace"], ["ada_l"])

    def me(self, names, usernames=()):
        (self.corpus / "identity.json").write_text(json.dumps({"names": names, "emails": [], "usernames": list(usernames)}))

    def zip(self, rel, files):
        p = self.imports / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(p, "w") as z:
            for name, x in files.items():
                z.writestr(name, data(x))

    def folder(self, rel, files):
        for name, x in files.items():
            p = self.imports / rel / name
            p.parent.mkdir(parents=True, exist_ok=True)
            (p.write_bytes if isinstance(x, bytes) else p.write_text)(data(x))

    def run_import(self):
        env = {**os.environ, "HOME": str(self.home), "CORPUS_DIR": str(self.corpus)}
        r = subprocess.run([sys.executable, str(CONNECTORS / "imports.py")], cwd=CONNECTORS, env=env,
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-3000:])
        self.recs = {f.stem: [json.loads(line) for line in f.read_text().splitlines()]
                     for f in (self.corpus / "normalized").glob("*.jsonl")}
        self.manifest = json.loads((self.corpus / "manifest.json").read_text())
        return self.recs

    def of(self, source, kind=None):
        return [r for r in self.recs.get(source, []) if kind is None or r["kind"] == kind]

    def thread_of(self, source, thread):
        return sorted((r for r in self.of(source, "message") if r.get("thread") == thread), key=lambda r: r["ts"])

    def unclaimed(self):
        return {g["group"].split(" :: ")[-1] for g in self.manifest.get("_imports_unclaimed", [])}


FB = "your_facebook_activity/messages/"
IG = "your_instagram_activity/messages/"


class MessageTests(Base):
    def test_messenger_in_a_facebook_export_with_splits_folders_and_groups(self):
        # Meta writes the newest messages first, and a long chat goes on in message_2.json, message_3.json ...
        self.zip("facebook/facebook-ada-2026-10-01-AbCd.zip", {
            f"{FB}inbox/gracehopper_10/message_1.json": thread("Grace Hopper", ["Grace Hopper", "Ada Lovelace"], [
                msg("Ada Lovelace", T + 300, "See you then"), msg("Grace Hopper", T + 200, "Tomorrow?")], thread_path="inbox/gracehopper_10"),
            f"{FB}inbox/gracehopper_10/message_2.json": thread("Grace Hopper", ["Grace Hopper", "Ada Lovelace"], [
                msg("Grace Hopper", T + 100, "Hello"), msg("Ada Lovelace", T, "Hi")], thread_path="inbox/gracehopper_10"),
            f"{FB}archived_threads/alanturing_11/message_1.json": thread("Alan Turing", ["Alan Turing", "Ada Lovelace"], [msg("Alan Turing", T, "Old chat")]),
            f"{FB}filtered_threads/someone_12/message_1.json": thread("Someone", ["Someone", "Ada Lovelace"], [msg("Someone", T, "A request")]),
            f"{FB}message_requests/other_13/message_1.json": thread("Other", ["Other", "Ada Lovelace"], [msg("Other", T, "Another request")]),
            f"{FB}e2ee_cutover/katherine_14/message_1.json": thread("Katherine Johnson", ["Katherine Johnson", "Ada Lovelace"], [msg("Katherine Johnson", T, "Before encryption")]),
            f"{FB}inbox/bookclub_15/message_1.json": thread("Book Club", ["Grace Hopper", "Alan Turing", "Katherine Johnson", "Ada Lovelace"], [
                msg("Grace Hopper", T + 50, "Grace named the group Book Club."), msg("Alan Turing", T + 60, "Next book?")], thread_type="RegularGroup"),
            f"{FB}autofill_information.json": {"autofill_information_v2": {}},
        })
        self.run_import()
        self.assertEqual([r["text"] for r in self.thread_of("messenger", "gracehopper_10")], ["Hi", "Hello", "Tomorrow?", "See you then"])
        self.assertEqual([r["author"] for r in self.thread_of("messenger", "gracehopper_10")], ["me", "Grace Hopper", "Grace Hopper", "me"])
        self.assertEqual({r["thread"] for r in self.of("messenger")},
                         {"gracehopper_10", "alanturing_11", "someone_12", "other_13", "katherine_14", "bookclub_15"})
        group = self.thread_of("messenger", "bookclub_15")
        self.assertEqual((group[0]["thread_name"], len(group[0]["participants"])), ("Book Club", 4))
        self.assertNotIn("instagram", self.recs)

    def test_each_layout_goes_to_its_app(self):
        one = lambda who, text: thread(who, [who, "Ada Lovelace"], [msg(who, T, text)])  # noqa: E731
        self.zip("facebook/facebook-ada-2019.zip", {"messages/inbox/grace_1/message_1.json": one("Grace Hopper", "fb before 2022")})
        self.zip("facebook/facebook-ada-2023.zip", {"your_activity_across_facebook/messages/inbox/grace_2/message_1.json": one("Grace Hopper", "fb 2022-23")})
        self.zip("facebook/facebook-ada-2026.zip", {
            f"{FB}inbox/grace_3/message_1.json": one("Grace Hopper", "fb since 2024"),
            # A Messenger chat with a deleted Instagram account: its folder says instagram, the export doesn't.
            f"{FB}inbox/instagramuser_4/message_1.json": one("Instagram User", "fb chat across apps")})
        self.zip("instagram/ada_l_20211001.zip", {"messages/inbox/grace_5/message_1.json": one("Grace Hopper", "ig before 2023")})
        self.zip("instagram/instagram-ada_l-2026.zip", {f"{IG}inbox/grace_6/message_1.json": one("Grace Hopper", "ig since 2023")})
        self.run_import()
        where = {r["text"]: s for s in ("messenger", "instagram") for r in self.of(s, "message")}
        self.assertEqual(where, {"fb before 2022": "messenger", "fb 2022-23": "messenger", "fb since 2024": "messenger",
                                 "fb chat across apps": "messenger", "ig before 2023": "instagram", "ig since 2023": "instagram"})

    def test_mojibake_is_undone_everywhere_and_good_text_is_left_alone(self):
        self.zip("facebook/facebook-ada-2026.zip", {
            f"{FB}inbox/cafe_1/message_1.json": thread(moji("Café ☕ club"), [moji("José Martí"), "Ada Lovelace"], [
                msg(moji("José Martí"), T, moji("Ça va? 😂 👍🏽"), reactions=[{"reaction": moji("❤"), "actor": "Ada Lovelace", "timestamp": T + 5}],
                    share={"link": "https://example.com/r", "share_text": moji("Crème brûlée")}),
                msg("Ada Lovelace", T + 10, "naïve café, 日本語 🎉"),  # already right: stays as it is
                msg("Ada Lovelace", T + 20, moji("Très bien 👋")[:-2]),  # cut off in the middle of the emoji
                msg("Ada Lovelace", T + 30, "half an emoji \ud83d"),  # a lone surrogate doesn't stop the writer
            ]),
            "your_facebook_activity/comments_and_reactions/comments.json": {"comments_v2": [
                {"timestamp": T, "data": [{"comment": {"timestamp": T, "comment": moji("Génial 🔥"), "author": "Ada Lovelace"}}], "title": moji("Ada commented on José's post.")}]},
        })
        self.run_import()
        by = {r["ts"]: r for r in self.of("messenger", "message")}
        first = by[iso(T)]
        self.assertEqual((first["text"].split("\n")[0], first["author"], first["thread_name"]), ("Ça va? 😂 👍🏽", "José Martí", "Café ☕ club"))
        self.assertEqual(first["participants"], ["José Martí", "Ada Lovelace"])
        self.assertEqual((first["meta"]["reactions"][0]["reaction"], first["meta"]["share_text"]), ("❤", "Crème brûlée"))
        self.assertEqual(by[iso(T + 10)]["text"], "naïve café, 日本語 🎉")
        self.assertTrue(by[iso(T + 20)]["text"].startswith("Très bien"), by[iso(T + 20)]["text"])
        self.assertTrue(by[iso(T + 30)]["text"].startswith("half an emoji"))
        (c,) = self.of("facebook_activity", "comment")
        self.assertIn("Génial 🔥", c["text"])
        self.assertIn("Ada commented on José's post.", c["text"])

    def test_times_in_seconds_or_milliseconds(self):
        self.zip("instagram/instagram-ada_l-2026.zip", {
            f"{IG}inbox/grace_1/message_1.json": thread("Grace Hopper", ["Grace Hopper", "Ada Lovelace"], [
                {"sender_name": "Grace Hopper", "timestamp_ms": T * 1000, "content": "in ms"},
                {"sender_name": "Grace Hopper", "timestamp": T + 60, "content": "in seconds"},
                {"sender_name": "Grace Hopper", "timestamp": (T + 120) * 1000, "content": "ms under timestamp",
                 "reactions": [{"reaction": "👍", "actor": "Ada Lovelace", "timestamp": (T + 130) * 1000}]},
            ]),
            # A time written out instead of a number: read, and nothing stops over it.
            "your_instagram_activity/likes/liked_posts.json": {"likes_media_likes": [
                {"title": "grace_h", "string_list_data": [{"href": "https://www.instagram.com/p/a/", "value": "👍", "timestamp": T}]},
                {"title": "alan_t", "string_list_data": [{"href": "https://www.instagram.com/p/b/", "value": "👍", "timestamp": "2026-09-21T14:15:00+00:00"}]}]},
        })
        self.run_import()
        ts = {r["text"]: r["ts"] for r in self.of("instagram", "message")}
        self.assertEqual(ts, {"in ms": iso(T), "in seconds": iso(T + 60), "ms under timestamp": iso(T + 120)})
        r = next(r for r in self.of("instagram", "message") if r["text"] == "ms under timestamp")
        self.assertEqual(r["meta"]["reactions"], [{"who": "Ada Lovelace", "reaction": "👍", "ts": iso(T + 130)}])
        likes = {r["title"]: r["ts"] for r in self.of("instagram_activity", "reaction")}
        self.assertEqual(likes, {"grace_h": iso(T), "alan_t": iso(T + 100)})

    def test_attachments_of_every_kind_are_copied_and_listed(self):
        root = "your_facebook_activity/messages/inbox/grace_1/"
        self.folder("facebook/facebook-ada-2026-10-01", {  # unzipped, one folder down: uris are from the export's root
            f"{root}message_1.json": thread("Grace Hopper", ["Grace Hopper", "Ada Lovelace"], [
                msg("Grace Hopper", T, photos=[{"uri": f"{root}photos/1.jpg", "creation_timestamp": T}]),
                msg("Grace Hopper", T + 1, videos=[{"uri": f"{root}videos/2.mp4", "creation_timestamp": T, "thumbnail": {"uri": f"{root}videos/2.jpg"}}]),
                msg("Ada Lovelace", T + 2, audio_files=[{"uri": f"{root}audio/3.m4a", "creation_timestamp": T}]),
                msg("Ada Lovelace", T + 3, "the slides", files=[{"uri": f"{root}files/4.pdf", "creation_timestamp": T}]),
                msg("Grace Hopper", T + 4, gifs=[{"uri": f"{root}gifs/5.gif"}]),
                msg("Grace Hopper", T + 5, sticker={"uri": "your_facebook_activity/messages/stickers_used/6.png", "ai_stickers": []}),
            ]),
            f"{root}photos/1.jpg": b"jpg", f"{root}videos/2.mp4": b"mp4", f"{root}videos/2.jpg": b"thumb",
            f"{root}audio/3.m4a": b"m4a", f"{root}files/4.pdf": b"%PDF", f"{root}gifs/5.gif": b"gif",
            "your_facebook_activity/messages/stickers_used/6.png": b"png",
        })
        self.run_import()
        got = {r["ts"]: (r["text"], [Path(f).name for f in r["meta"].get("files", [])]) for r in self.of("messenger", "message")}
        self.assertEqual(got, {iso(T): ("[photo]", ["1.jpg"]), iso(T + 1): ("[video]", ["2.mp4"]), iso(T + 2): ("[audio_file]", ["3.m4a"]),
                               iso(T + 3): ("the slides\n[file]", ["4.pdf"]), iso(T + 4): ("[gif]", ["5.gif"]), iso(T + 5): ("[sticker]", ["6.png"])})
        f = next(r for r in self.of("messenger") if r["ts"] == iso(T))["meta"]["files"][0]
        self.assertEqual((self.corpus / f).read_bytes(), b"jpg")

    def test_two_messages_alike_in_one_file_are_both_kept(self):
        # Two photos sent in the same moment are two messages; the same chat in an older export is still read once.
        root = "your_instagram_activity/messages/inbox/grace_1/"
        both = thread("Grace Hopper", ["Grace Hopper", "Ada Lovelace"], [
            msg("Grace Hopper", T, photos=[{"uri": f"{root}photos/b.jpg"}]), msg("Grace Hopper", T, photos=[{"uri": f"{root}photos/a.jpg"}])])
        self.zip("instagram/instagram-ada_l-2026.zip", {f"{root}message_1.json": both, f"{root}photos/a.jpg": b"a", f"{root}photos/b.jpg": b"b"})
        self.zip("instagram/instagram-ada_l-2025.zip", {f"{root}message_1.json": both, f"{root}photos/a.jpg": b"a", f"{root}photos/b.jpg": b"b"})
        self.run_import()
        files = sorted(Path(r["meta"]["files"][0]).name for r in self.of("instagram", "message"))
        self.assertEqual(files, ["a.jpg", "b.jpg"])

    def test_shares_unsent_and_messages_with_nothing_in_them(self):
        self.zip("facebook/facebook-ada-2026.zip", {f"{FB}inbox/grace_1/message_1.json": thread("Grace Hopper", ["Grace Hopper", "Ada Lovelace"], [
            msg("Grace Hopper", T, "Look", share={"link": "https://example.com/a"}),
            msg("Grace Hopper", T + 1, share={"share_text": "Only a caption"}),
            msg("Ada Lovelace", T + 2, is_unsent=True),
            msg("Grace Hopper", T + 3, is_geoblocked_for_viewer=True),  # nothing to show, but it was sent
            msg("Grace Hopper", T + 4, "Grace unsent a message."),
        ])})
        self.run_import()
        got = {r["ts"]: r["text"] for r in self.of("messenger", "message")}
        self.assertEqual(got[iso(T)], "Look\n[shared: https://example.com/a]")
        self.assertEqual(got[iso(T + 1)], "[shared: Only a caption]")
        self.assertEqual(got[iso(T + 2)], "[unsent]")
        self.assertEqual(got[iso(T + 4)], "Grace unsent a message.")
        self.assertIn(iso(T + 3), got, "a message with nothing in the export is still kept")

    def test_deleted_accounts_are_never_you(self):
        # Nothing says who you are: you're the one in every chat, not "Facebook user", who sent the most requests.
        self.me([])
        requests = {f"{FB}message_requests/facebookuser_{n}/message_1.json": thread("Facebook user", ["Facebook user", "Ada Lovelace"], [
            msg("Facebook user", T + n, f"spam {n}")]) for n in range(3)}
        self.zip("facebook/facebook-ada-2026.zip", {**requests, f"{FB}inbox/grace_9/message_1.json": thread("Grace Hopper", ["Grace Hopper", "Ada Lovelace"], [
            msg("Ada Lovelace", T + 10, "Hi Grace"), msg("Grace Hopper", T + 11, "Hi Ada")])})
        self.run_import()
        mine = sorted(r["text"] for r in self.of("messenger", "message") if r["is_me"])
        self.assertEqual(mine, ["Hi Grace"])
        self.assertEqual({r["author"] for r in self.of("messenger", "message") if r["text"].startswith("spam")}, {"Facebook user"})

    def test_a_message_without_a_sender_is_not_yours(self):
        self.me([])
        self.zip("facebook/facebook-ada-2026.zip", {f"{FB}inbox/grace_1/message_1.json": thread("Grace Hopper", ["Grace Hopper", ""], [
            {"timestamp_ms": T * 1000, "content": "from a deleted account"}, msg("Grace Hopper", T + 1, "Hi")])})
        self.run_import()
        r = next(r for r in self.of("messenger", "message") if r["text"] == "from a deleted account")
        self.assertFalse(r["is_me"])

    def test_encrypted_chats_download(self):
        # Messenger's "Download secure storage data" (end-to-end encrypted chats): participants are plain names, and
        # threadName, senderName, text, timestamp (ms), media and isUnsent; its text isn't mojibake.
        e2ee = {"participants": ["Grace Hopper", "Ada Lovelace"], "threadName": "Grace Hopper", "messages": [
            {"isUnsent": False, "media": [], "reactions": [{"actor": "Ada Lovelace", "reaction": "❤"}], "senderName": "Grace Hopper",
             "text": "Encrypted hello, café", "timestamp": T * 1000, "type": "text"},
            {"isUnsent": False, "media": [{"uri": "media/photo_1.jpg"}], "reactions": [], "senderName": "Ada Lovelace", "text": "",
             "timestamp": (T + 60) * 1000, "type": "media"},
            {"isUnsent": True, "media": [], "reactions": [], "senderName": "Ada Lovelace", "text": "", "timestamp": (T + 120) * 1000, "type": "text"}]}
        self.zip("facebook/messages.zip", {"messages/inbox/gracehopper_10/message_1.json": e2ee, "media/photo_1.jpg": b"jpg"})
        self.run_import()
        got = {r["ts"]: r for r in self.thread_of("messenger", "gracehopper_10")}
        self.assertEqual(got[iso(T)]["text"], "Encrypted hello, café")
        self.assertEqual((got[iso(T)]["thread_name"], got[iso(T)]["participants"]), ("Grace Hopper", ["Grace Hopper", "Ada Lovelace"]))
        self.assertEqual(got[iso(T)]["meta"]["reactions"], [{"who": "Ada Lovelace", "reaction": "❤"}])
        self.assertEqual((got[iso(T + 60)]["text"], [Path(f).name for f in got[iso(T + 60)]["meta"]["files"]]), ("[photo]", ["photo_1.jpg"]))
        self.assertEqual((got[iso(T + 120)]["text"], got[iso(T + 120)]["is_me"]), ("[unsent]", True))

    def test_an_encrypted_chat_saved_under_its_own_name(self):
        # The same download's chats may be one file each, named after the chat rather than message_1.json.
        e2ee = {"participants": ["Grace Hopper", "Ada Lovelace"], "threadName": "Grace Hopper", "messages": [
            {"senderName": "Grace Hopper", "text": "One file per chat", "timestamp": T * 1000, "media": [], "reactions": [], "isUnsent": False}]}
        self.zip("facebook/messages.zip", {"messages/grace_hopper_10.json": e2ee})
        self.run_import()
        (r,) = self.of("messenger", "message")
        self.assertEqual((r["text"], r["thread"], r["ts"]), ("One file per chat", "grace_hopper_10", iso(T)))

    @unittest.expectedFailure  # Instagram's single messages.json (before Dec 2020) is left as records: usernames, not names, so it can't be matched to a newer export's copy of the same chats
    def test_instagram_before_2021_one_messages_json(self):
        self.zip("instagram/ada_l_20191001.zip", {"messages.json": [{"participants": ["ada_l", "grace_h"], "conversation": [
            {"sender": "grace_h", "created_at": "2019-09-30T10:00:00.123456+00:00", "text": "Old DM"},
            {"sender": "ada_l", "created_at": "2019-09-30T10:01:00.000000+00:00", "text": "Old reply"}]}]})
        self.run_import()
        self.assertEqual(sorted((r["text"], r["is_me"]) for r in self.of("instagram", "message")), [("Old DM", False), ("Old reply", True)])


class FileTests(Base):
    def test_empty_and_broken_files_dont_stop_the_import(self):
        good = thread("Grace Hopper", ["Grace Hopper", "Ada Lovelace"], [msg("Grace Hopper", T, "Still here")])
        self.zip("facebook/facebook-ada-2026.zip", {
            f"{FB}inbox/empty_1/message_1.json": "",
            f"{FB}inbox/cut_2/message_1.json": '{"participants": [{"name": "Grace Hopper"}], "messages": [{"sender_name": "Gr',
            f"{FB}inbox/list_3/message_1.json": [],
            f"{FB}inbox/null_4/message_1.json": {"participants": None, "messages": None, "title": None},
            f"{FB}inbox/odd_5/message_1.json": {"participants": ["Grace Hopper", {"name": "Ada Lovelace"}, None], "messages": [
                None, "x", 7, {"sender_name": "Grace Hopper", "timestamp_ms": T * 1000, "content": "Odd but readable", "photos": "nope",
                               "reactions": ["x"], "share": "y"}]},
            f"{FB}inbox/good_6/message_1.json": good,
            "your_facebook_activity/comments_and_reactions/comments.json": "",
            "your_facebook_activity/posts/your_posts_1.json": "[{\"timestamp\": 17",
            "your_facebook_activity/saved_items_and_collections/saved_items_and_collections.json": {"saves_v2": [
                {"timestamp": T, "title": "Ada saved a link.", "string_map_data": {"Link": "not a dict"}, "string_list_data": ["x"]}]},
        })
        self.run_import()
        self.assertEqual(sorted(r["text"] for r in self.of("messenger", "message")), ["Odd but readable", "Still here"])
        self.assertTrue(any("saved a link" in r["text"] for r in self.of("facebook_activity")))
        # What couldn't be read is said so, not counted as read.
        self.assertTrue({f"{FB}inbox/cut_2", "your_facebook_activity/posts"} <= self.unclaimed(), self.unclaimed())

    def test_a_zip_in_parts(self):
        # A big download comes as several zips: a chat in one, its second half and its photos in another.
        root = f"{FB}inbox/grace_1/"
        self.zip("facebook/facebook-ada-2026-10-01-AbCd.zip", {f"{root}message_1.json": thread("Grace Hopper", ["Grace Hopper", "Ada Lovelace"], [
            msg("Grace Hopper", T + 10, photos=[{"uri": f"{root}photos/p.jpg", "creation_timestamp": T}])])})
        self.zip("facebook/facebook-ada-2026-10-01-EfGh.zip", {f"{root}message_2.json": thread("Grace Hopper", ["Grace Hopper", "Ada Lovelace"], [
            msg("Grace Hopper", T, "First")]), f"{root}photos/p.jpg": b"jpg"})
        self.run_import()
        got = [(r["text"], [Path(f).name for f in r.get("meta", {}).get("files", [])]) for r in self.thread_of("messenger", "grace_1")]
        self.assertEqual(got, [("First", []), ("[photo]", ["p.jpg"])])
        self.assertNotIn("facebook_files", self.recs, "the photo is the message's, not left over")

    def test_two_exports_with_the_same_paths_are_both_read(self):
        # Two accounts (or two downloads) are zips with the same files inside: each is read.
        liked = lambda who: {"likes_media_likes": [{"title": who, "string_list_data": [  # noqa: E731
            {"href": f"https://www.instagram.com/p/{who}/", "value": "👍", "timestamp": T}]}]}
        self.zip("instagram/instagram-ada_l-2026.zip", {"your_instagram_activity/likes/liked_posts.json": liked("grace_h")})
        self.zip("instagram/instagram-ada_work-2026.zip", {"your_instagram_activity/likes/liked_posts.json": liked("alan_t")})
        self.run_import()
        self.assertEqual(sorted(r["title"] for r in self.of("instagram_activity", "reaction")), ["alan_t", "grace_h"])

    def test_html_export_is_kept_as_documents(self):
        # Meta's default format is HTML. Nothing is lost: each page is kept as a document.
        page = ('<html><head><title>Grace Hopper</title></head><body><div class="_a6-g"><div class="_a6-h">Grace Hopper</div>'
                '<div class="_a6-p"><div>Look at this</div></div><div class="_a6-o">Sep 21, 2026 2:13:20 pm</div></div></body></html>')
        self.zip("instagram/instagram-ada_l-2026-html.zip", {f"{IG}inbox/grace_1/message_1.html": page,
                                                              "your_instagram_activity/likes/liked_posts.html": "<html><body>grace_h Sep 21, 2026</body></html>"})
        self.run_import()
        docs = " ".join(r["text"] for r in self.of("imported_documents"))
        self.assertIn("Look at this", docs)
        self.assertIn("grace_h", docs)

    @unittest.expectedFailure  # HTML conversations aren't read as messages: Meta's class names change between versions and its dates are in the account's language; the app asks for JSON
    def test_html_conversations_are_read_as_messages(self):
        page = ('<html><body><div class="_a6-g"><div class="_a6-h">Grace Hopper</div><div class="_a6-p"><div>Look at this</div></div>'
                '<div class="_a6-o">Sep 21, 2026 2:13:20 pm</div></div></body></html>')
        self.zip("instagram/instagram-ada_l-2026-html.zip", {f"{IG}inbox/grace_1/message_1.html": page})
        self.run_import()
        self.assertEqual([r["text"] for r in self.of("instagram", "message")], ["Look at this"])


class ActivityTests(Base):
    def test_instagram_before_and_after_2023(self):
        self.zip("instagram/ada_l_20211001.zip", {
            "content/posts_1.json": [{"media": [{"uri": "media/posts/202109/1.jpg", "creation_timestamp": T, "title": moji("Tide pools 🌊")}]}],
            "content/stories.json": {"ig_stories": [{"uri": "media/stories/202109/2.mp4", "creation_timestamp": T + 1, "title": ""}]},
            "personal_information/personal_information.json": {"profile_user": [{"string_map_data": {
                "Name": {"value": "Ada Lovelace", "timestamp": 0}, "Username": {"value": "ada_l", "timestamp": 0}}}]},
            "followers_and_following/followers.json": {"relationships_followers": [
                {"title": "", "media_list_data": [], "string_list_data": [{"href": "https://www.instagram.com/grace_h", "value": "grace_h", "timestamp": T}]}]},
            "media/posts/202109/1.jpg": b"jpg",
        })
        self.zip("instagram/instagram-ada_l-2026.zip", {
            "your_instagram_activity/media/posts_1.json": [{"media": [{"uri": "media/posts/202609/3.jpg", "creation_timestamp": T + 2, "title": "Pier"}]}],
            # Since 2024 following.json has the account in title, and only a link in string_list_data.
            "connections/followers_and_following/following.json": {"relationships_following": [
                {"title": "alan_t", "string_list_data": [{"href": "https://www.instagram.com/_u/alan_t", "timestamp": T + 3}]}]},
            "connections/followers_and_following/followers_1.json": [
                {"title": "", "media_list_data": [], "string_list_data": [{"href": "https://www.instagram.com/katherine_j", "value": "katherine_j", "timestamp": T + 4}]}],
            "personal_information/personal_information/personal_information.json": {"profile_user": [{"string_map_data": {"Username": {"value": "ada_l"}}}]},
        })
        self.run_import()
        posts = {r["title"]: r["ts"] for r in self.of("instagram_activity", "post")}
        self.assertEqual(posts, {"Tide pools 🌊": iso(T), "stories": iso(T + 1), "Pier": iso(T + 2)})
        self.assertEqual(len(self.of("instagram_activity", "profile")), 2)
        follows = {(r["title"], r["is_me"]) for r in self.of("instagram_activity", "follow")}
        self.assertEqual(follows, {("grace_h", False), ("alan_t", True), ("katherine_j", False)})
        old_post = next(r for r in self.of("instagram_activity", "post") if r["ts"] == iso(T))
        self.assertEqual([Path(f).name for f in old_post["meta"]["files"]], ["1.jpg"])

    def test_facebook_files_whose_items_sit_deeper_or_are_plain_names(self):
        self.zip("facebook/facebook-ada-2026.zip", {
            # Each event is its own, with its date and which list it's on.
            "your_facebook_activity/events/your_event_responses.json": {"event_responses_v2": {
                "events_joined": [{"name": "Tide walk", "start_timestamp": T, "end_timestamp": 0}],
                "events_declined": [{"name": "Gala", "start_timestamp": T + 86400, "end_timestamp": 0}],
                "events_interested": []}},
            # Ad topics are a list of plain names.
            "logged_information/other_logged_information/ads_interests.json": {"topics_v2": ["Rock climbing", moji("Pâtisserie")]},
            # A post's tags are plain names too.
            "your_facebook_activity/posts/your_posts__check_ins__photos_and_videos_1.json": [
                {"timestamp": T, "data": [{"post": "Beach day"}], "tags": [{"name": "Grace Hopper"}], "title": "Ada Lovelace updated her status."},
                {"timestamp": T + 1, "data": [{"post": "With friends"}], "tags": ["Alan Turing"]}],
            "connections/friends/your_friends.json": {"friends_v2": [{"name": "Grace Hopper", "timestamp": T}]},
            "personal_information/profile_information/profile_information.json": {"profile_v2": {
                "name": {"full_name": "Ada Lovelace"}, "emails": {"emails": ["ada@example.com"]}, "registration_timestamp": T}},
        })
        self.run_import()
        events = {r["title"]: r for r in self.of("facebook_activity", "event")}
        self.assertEqual(set(events), {"Tide walk", "Gala"})
        self.assertEqual((events["Tide walk"]["ts"], events["Gala"]["ts"]), (iso(T), iso(T + 86400)))
        self.assertIn("joined", events["Tide walk"]["text"])
        self.assertIn("declined", events["Gala"]["text"])
        topics = {r["title"] for r in self.of("facebook_activity", "inference")}
        self.assertEqual(topics, {"Rock climbing", "Pâtisserie"})
        posts = {r["ts"]: r["text"] for r in self.of("facebook_activity", "post")}
        self.assertIn("Grace Hopper", posts[iso(T)])
        self.assertIn("Alan Turing", posts[iso(T + 1)])
        self.assertEqual([r["title"] for r in self.of("facebook_activity", "follow")], ["Grace Hopper"])
        (profile,) = self.of("facebook_activity", "profile")
        self.assertIn("Ada Lovelace", profile["text"])
        self.assertIn("ada@example.com", profile["text"])


if __name__ == "__main__":
    unittest.main()
