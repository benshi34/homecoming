"""Exports of X, LinkedIn, Discord, Spotify, Notion, ChatGPT and Claude.ai in the shapes they've come in: X's archive
since 2019 and before 2018, in parts, edited and long posts, links, media folders old and new; LinkedIn's CSVs with
their preamble, a BOM and Windows line ends; Discord's package before and after 2024 and in another language; both
Spotify downloads, their older names, podcasts and music; Notion's Markdown and HTML exports, in parts and twice;
ChatGPT's branches and content types; Claude.ai's content blocks, projects folder and memories. And files that are
empty, cut short or an odd shape, which stop nothing. Exports are made up here; the importer runs as the app runs it.

Run: python3 -m unittest discover -s connectors/tests -p 'test_service_formats.py'
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
T = 1790000000  # 2026-09-21T14:13:20Z


def data(x):
    return x if isinstance(x, (str, bytes)) else json.dumps(x)


def ytd(part, items):
    """An X archive file: JSON after a line that names it."""
    return f"window.YTD.{part}.part0 = " + json.dumps(items, indent=2)


def csv_text(header, rows, end="\n"):
    out = io.StringIO()
    w = csv.writer(out, lineterminator=end)
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

    def zip_bytes(self, files):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for name, x in files.items():
                z.writestr(name, data(x))
        return buf.getvalue()

    def run_import(self, timeout=120):
        env = {**os.environ, "HOME": str(self.home), "CORPUS_DIR": str(self.corpus), "TZ": "America/New_York"}
        r = subprocess.run([sys.executable, str(CONNECTORS / "imports.py")], cwd=CONNECTORS, env=env,
                           capture_output=True, text=True, timeout=timeout)
        self.out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, self.out[-3000:])
        self.recs = {f.stem: [json.loads(line) for line in f.read_text().splitlines()]
                     for f in (self.corpus / "normalized").glob("*.jsonl")}
        self.manifest = json.loads((self.corpus / "manifest.json").read_text())
        return self.recs

    def of(self, source, kind=None):
        return [r for r in self.recs.get(source, []) if kind is None or r["kind"] == kind]

    def by_id(self, source, kind=None):
        return {r["id"]: r for r in self.of(source, kind)}

    def unclaimed(self):
        """The export files no parser read, by name."""
        return {x for g in self.manifest.get("_imports_unclaimed", []) for x in g["examples"]}


# ---------------------------------------------------------------- X

def tweet(id_, text, when="Tue Sep 01 10:00:00 +0000 2026", **extra):
    return {"tweet": {"id_str": id_, "id": id_, "full_text": text, "created_at": when, "favorite_count": "0",
                      "retweet_count": "0", "entities": {"urls": [], "hashtags": [], "user_mentions": [], "symbols": []}, **extra}}


ACCOUNT = ytd("account", [{"account": {"accountId": "42", "username": "ada_l", "accountDisplayName": "Ada"}}])


class XTests(Base):
    def test_tweets_in_parts_and_the_2019_tweet_js(self):
        # A big archive splits tweets.js into tweets-part1.js ...; one from 2019 calls it tweet.js, its items not wrapped.
        self.zip("x/twitter-2026-10-01-abc.zip", {
            "data/account.js": ACCOUNT,
            "data/tweets.js": ytd("tweets", [tweet("1", "part zero")]),
            "data/tweets-part1.js": "window.YTD.tweets.part1 = " + json.dumps([tweet("2", "part one")])})
        self.zip("x/twitter-2019-05-01.zip", {"data/tweet.js": "window.YTD.tweet.part0 = " + json.dumps([
            {"id_str": "3", "full_text": "from 2019", "created_at": "Wed May 01 10:00:00 +0000 2019"}])})
        self.run_import()
        posts = self.by_id("x", "post")
        self.assertEqual({k: v["text"] for k, v in posts.items()}, {"1": "part zero", "2": "part one", "3": "from 2019"})
        self.assertEqual(posts["3"]["ts"], "2019-05-01T10:00:00Z")

    def test_an_archive_from_before_2018(self):
        # "Grailbird": a file a month in data/js/tweets/, "text" not "full_text", times written another way, the
        # same tweets again in tweets.csv, and a retweet with the whole of what it retweeted.
        rt = {"id_str": "11", "text": "RT @grace_h: Spring tides are higher because the sun and the moon line up, which happens twi…",
              "created_at": "2012-02-03 08:00:00 +0000", "entities": {"urls": [], "media": [], "user_mentions": []},
              "retweeted_status": {"id_str": "5", "created_at": "2012-02-03 07:00:00 +0000", "user": {"screen_name": "grace_h"},
                                   "text": "Spring tides are higher because the sun and the moon line up, which happens twice a month."}}
        self.zip("x/tweets-2017.zip", {
            "tweets.csv": csv_text(["tweet_id", "in_reply_to_status_id", "in_reply_to_user_id", "timestamp", "source", "text",
                                    "retweeted_status_id", "retweeted_status_user_id", "retweeted_status_timestamp", "expanded_urls"],
                                   [["10", "", "", "2012-01-31 23:59:59 +0000", "web", "Tides &amp; the moon http://t.co/aa", "", "", "", "http://example.com/tides"]]),
            "data/js/tweet_index.js": 'var tweet_index = [{"file_name": "data/js/tweets/2012_01.js", "year": 2012, "month": 1, "tweet_count": 1}]',
            "data/js/tweets/2012_01.js": "Grailbird.data.tweets_2012_01 = \n" + json.dumps([
                {"id_str": "10", "text": "Tides &amp; the moon http://t.co/aa", "created_at": "2012-01-31 23:59:59 +0000",
                 "entities": {"urls": [{"url": "http://t.co/aa", "expanded_url": "http://example.com/tides", "indices": [21, 35]}]}}]),
            "data/js/tweets/2012_02.js": "Grailbird.data.tweets_2012_02 = \n" + json.dumps([rt])})
        self.run_import()
        posts = self.by_id("x", "post")
        self.assertEqual(set(posts), {"10", "11"}, "each tweet once: tweets.csv holds the same ones")
        self.assertEqual((posts["10"]["text"], posts["10"]["ts"]), ("Tides & the moon http://example.com/tides", "2012-01-31T23:59:59Z"))
        self.assertEqual(posts["11"]["text"], "RT @grace_h: Spring tides are higher because the sun and the moon line up, which happens twice a month.")
        self.assertEqual(posts["11"]["meta"]["retweet_of"], "grace_h")
        self.assertNotIn("x_other", self.recs, "nothing of it left to the catch-all")
        self.assertFalse({"tweets.csv", "2012_01.js", "tweet_index.js"} & self.unclaimed(), self.unclaimed())

    def test_links_entities_escapes_emoji_replies_and_retweets(self):
        self.zip("x/twitter-2026.zip", {"data/account.js": ACCOUNT, "data/tweets.js": ytd("tweets", [
            tweet("1", "Tides &amp; currents &lt;3 🌊🎉 https://t.co/abc https://t.co/pic", entities={
                "urls": [{"url": "https://t.co/abc", "expanded_url": "https://example.com/tides", "display_url": "example.com/tides"}],
                "media": [{"url": "https://t.co/pic", "expanded_url": "https://x.com/ada_l/status/1/photo/1", "type": "photo"}]}),
            tweet("2", "@grace_h agreed", in_reply_to_screen_name="grace_h", in_reply_to_status_id_str="9"),
            tweet("3", "RT @grace_h: Spring tides", retweeted=False)])})
        self.run_import()
        posts = self.by_id("x", "post")
        self.assertEqual(posts["1"]["text"], "Tides & currents <3 🌊🎉 https://example.com/tides https://x.com/ada_l/status/1/photo/1")
        self.assertEqual(posts["2"]["meta"]["reply_to"], "grace_h")
        self.assertEqual(posts["3"]["meta"]["retweet_of"], "grace_h")

    def test_an_edited_post_keeps_every_version(self):
        # Each version of an edited post is a tweet of its own; edit_info ties them together.
        ids = {"editTweetIds": ["20", "21"], "editableUntil": "2026-09-01T11:00:00.000Z", "editsRemaining": "4", "isEditEligible": True}
        self.zip("x/twitter-2026.zip", {"data/account.js": ACCOUNT, "data/tweets.js": ytd("tweets", [
            tweet("21", "Tides are high", "Tue Sep 01 10:02:00 +0000 2026", edit_info={"edit": {"initialTweetId": "20", "editControlInitial": ids}}),
            tweet("20", "Tides are hgih", edit_info={"initial": ids}),
            tweet("22", "Not edited", edit_info={"initial": {"editTweetIds": ["22"], "editsRemaining": "5"}})])})
        self.run_import()
        posts = self.by_id("x", "post")
        self.assertEqual(set(posts), {"20", "21", "22"})
        self.assertEqual((posts["20"]["meta"]["replaced_by"], posts["20"]["meta"]["tier"]), ("21", "superseded"))
        self.assertEqual(posts["21"]["meta"]["edit_of"], "20")
        self.assertNotIn("tier", posts["21"]["meta"])
        self.assertFalse({"edit_of", "replaced_by"} & set(posts["22"]["meta"]))

    def test_media_folders_old_and_new_and_community_posts(self):
        self.zip("x/twitter-2026.zip", {
            "data/account.js": ACCOUNT,
            "data/tweets.js": ytd("tweets", [tweet("30", "old folder"), tweet("31", "new folder")]),
            "data/deleted-tweets.js": ytd("deleted_tweets", [tweet("32", "deleted", deleted_at="Tue Sep 01 11:00:00 +0000 2026")]),
            "data/community-tweet.js": ytd("community_tweet", [tweet("33", "in a community", community_id_str="777")]),
            "data/tweet_media/30-a.jpg": b"jpg30", "data/tweets_media/31-b.jpg": b"jpg31",
            "data/deleted_tweets_media/32-c.jpg": b"jpg32", "data/community_tweet_media/33-d.mp4": b"mp433"})
        self.run_import()
        posts = self.by_id("x", "post")
        self.assertEqual({k: [Path(f).name for f in v["meta"].get("files", [])] for k, v in posts.items()},
                         {"30": ["30-a.jpg"], "31": ["31-b.jpg"], "32": ["32-c.jpg"], "33": ["33-d.mp4"]})
        self.assertTrue(posts["33"]["meta"]["community"])
        self.assertNotIn("x_files", self.recs, "every file is its post's")

    def test_messages_likes_and_follows(self):
        self.zip("x/twitter-2026.zip", {
            "data/account.js": ACCOUNT,
            "data/direct-messages.js": ytd("directMessages", [{"dmConversation": {"conversationId": "7-42", "messages": [
                {"messageCreate": {"id": "m2", "senderId": "42", "recipientId": "7", "text": "see https://t.co/x",
                                   "urls": [{"url": "https://t.co/x", "expanded": "https://example.com/tides", "display": "example.com/tides"}],
                                   "mediaUrls": [], "reactions": [], "createdAt": "2026-09-02T10:01:00.000Z"}},
                {"messageCreate": {"id": "m1", "senderId": "7", "recipientId": "42", "text": "hi Ada", "urls": [], "mediaUrls": [],
                                   "reactions": [], "createdAt": "2026-09-02T10:00:00.000Z"}}]}}]),
            "data/like.js": ytd("like", [{"like": {"tweetId": "500", "fullText": "A post I liked", "expandedUrl": "https://twitter.com/i/web/status/500"}},
                                         {"like": {"tweetId": "501", "expandedUrl": "https://twitter.com/i/web/status/501"}}]),
            "data/follower.js": ytd("follower", [{"follower": {"accountId": "7", "userLink": "https://twitter.com/intent/user?user_id=7"}}]),
            "data/following.js": ytd("following", [{"following": {"accountId": "8", "userLink": "https://twitter.com/intent/user?user_id=8"}}])})
        self.run_import()
        dms = self.by_id("x", "message")
        self.assertEqual((dms["m2"]["text"], dms["m2"]["is_me"], dms["m1"]["is_me"]), ("see https://example.com/tides", True, False))
        likes = self.by_id("x", "reaction")
        self.assertEqual(set(likes), {"like:500", "like:501"}, "a like whose post's text isn't in the archive is kept too")
        self.assertEqual(likes["like:501"]["url"], "https://twitter.com/i/web/status/501")
        follows = {(r["meta"]["what"], r["meta"]["account"], r["is_me"]) for r in self.of("x", "follow")}
        self.assertEqual(follows, {("follower", "7", False), ("following", "8", True)})

    def test_empty_and_broken_files_stop_nothing(self):
        self.zip("x/twitter-2026.zip", {
            "data/account.js": ACCOUNT,  # one that names no account fails the archive (test_bridge.py's malformed export)
            "data/tweets.js": 'window.YTD.tweets.part0 = [{"tweet": {"id_str": "1", "full_te',
            "data/tweets-part1.js": "window.YTD.tweets.part1 = " + json.dumps([None, "x", tweet("2", "still here"), {"tweet": {"id_str": "3"}}]),
            "data/like.js": "not javascript at all",
            "data/note-tweet.js": "",
            "data/direct-messages.js": ytd("directMessages", [{"dmConversation": {"conversationId": "7-42", "messages": [
                {"messageCreate": {"id": "m1", "senderId": "7", "text": "hello", "createdAt": "2026-09-02T10:00:00.000Z"}}, "odd"]}}])})
        self.run_import()
        self.assertEqual({k: v.get("text") for k, v in self.by_id("x", "post").items()}, {"2": "still here", "3": None})
        self.assertEqual([r["text"] for r in self.of("x", "message")], ["hello"])
        self.assertTrue({"tweets.js", "like.js"} <= self.unclaimed(), self.unclaimed())


# ---------------------------------------------------------------- LinkedIn

LI = "linkedin/Complete_LinkedInDataExport_10-01-2026.zip"
NOTES = ('Notes:\r\n"When exporting your connection data, you may notice that some of the email addresses are missing. You will only '
         'see email addresses for connections who have allowed their connections to see or download their email address."\r\n\r\n')


class LinkedInTests(Base):
    def test_connections_with_their_notes_a_bom_and_windows_line_ends(self):
        rows = csv_text(["First Name", "Last Name", "URL", "Email Address", "Company", "Position", "Connected On"],
                        [["Grace", "Hopper", "https://www.linkedin.com/in/grace", "", "Navy", "Admiral", "01 Jan 2024"],
                         ["Alan", "Turing", "https://www.linkedin.com/in/alan", "alan@example.com", "Bletchley", "Cryptanalyst", "01/15/2024"]], end="\r\n")
        self.zip(LI, {"Connections.csv": "﻿" + NOTES + rows})
        self.run_import()
        got = {r["title"]: r for r in self.of("linkedin", "contact")}
        self.assertEqual(set(got), {"Grace Hopper", "Alan Turing"})
        self.assertEqual((got["Grace Hopper"]["ts"], got["Alan Turing"]["ts"]), ("2024-01-01T00:00:00", "2024-01-15T00:00:00"))
        self.assertNotIn("linkedin_other", self.recs)

    def test_connections_of_an_older_export_without_notes_or_links(self):
        self.zip("linkedin/Basic_LinkedInDataExport_2021.zip", {"Connections.csv": csv_text(
            ["First Name", "Last Name", "Email Address", "Company", "Position", "Connected On"], [["Grace", "Hopper", "", "Navy", "Admiral", "15 Mar 2021"]])})
        self.run_import()
        self.assertEqual([(r["title"], r["ts"]) for r in self.of("linkedin", "contact")], [("Grace Hopper", "2021-03-15T00:00:00")])

    def test_messages_written_over_several_lines(self):
        head = ["CONVERSATION ID", "CONVERSATION TITLE", "FROM", "SENDER PROFILE URL", "TO", "RECIPIENT PROFILE URLS", "DATE", "SUBJECT",
                "CONTENT", "FOLDER", "IS MESSAGE DRAFT"]
        self.zip(LI, {"messages.csv": "﻿" + csv_text(head, [
            ["c1", "", "Grace Hopper", "https://www.linkedin.com/in/grace", "Ada Lovelace", "https://www.linkedin.com/in/ada", "2024-01-01 10:00:00 UTC",
             "", "<p>Hello Ada,</p><p>Lunch on \"Friday\"?\nSay yes.</p>", "INBOX", "No"],
            ["c1", "", "Ada Lovelace", "https://www.linkedin.com/in/ada", "Grace Hopper", "https://www.linkedin.com/in/grace", "2024-01-01 11:00:00 UTC",
             "", "Yes!\r\nSee you 🎉", "SENT", "No"]], end="\r\n")})
        self.run_import()
        msgs = sorted(self.of("linkedin", "message"), key=lambda r: r["ts"])
        self.assertEqual([(r["ts"], r["author"], r["is_me"]) for r in msgs],
                         [("2024-01-01T10:00:00Z", "Grace Hopper", False), ("2024-01-01T11:00:00Z", "me", True)])
        self.assertIn('Lunch on "Friday"?\nSay yes.', msgs[0]["text"])
        self.assertIn("See you 🎉", msgs[1]["text"])

    def test_the_basic_and_the_complete_archive_together(self):
        # The basic archive arrives first and the complete one later: what's in both is kept once.
        files = {
            "Profile.csv": csv_text(["First Name", "Last Name", "Maiden Name", "Address", "Birth Date", "Headline", "Summary", "Industry"],
                                    [["Ada", "Lovelace", "", "", "Dec 10", "Mathematician", "Notes on the engine.\nAnd more.", "Research"]]),
            "Positions.csv": csv_text(["Company Name", "Title", "Description", "Location", "Started On", "Finished On"],
                                      [["Analytical Engines", "Programmer", "The first program", "London", "Jan 1843", ""]]),
            "Education.csv": csv_text(["School Name", "Start Date", "End Date", "Notes", "Degree Name", "Activities"], [["Home", "1830", "1835", "", "", ""]]),
            "Skills.csv": csv_text(["Name"], [["Mathematics"], ["Poetry"]]),
            "Invitations.csv": csv_text(["From", "To", "Sent At", "Message", "Direction", "inviterProfileUrl", "inviteeProfileUrl"],
                                        [["Grace Hopper", "Ada Lovelace", "1/15/24, 10:00 AM", "", "INCOMING", "", ""]])}
        self.zip("linkedin/Basic_LinkedInDataExport_10-01-2026.zip", files)
        self.zip(LI, {**files,
                      "Shares_123456789.csv": csv_text(["Date", "ShareLink", "ShareCommentary", "SharedUrl", "MediaUrl", "Visibility"],
                                                       [["2024-02-01 09:00:00", "https://www.linkedin.com/feed/update/1", '"Quoted," she said.\nTwo lines.', "", "", "MEMBER_NETWORK"],
                                                        ["2024-02-02 09:00:00", "https://www.linkedin.com/feed/update/2", "", "", "", "MEMBER_NETWORK"]]),
                      "Comments_123456789.csv": csv_text(["Date", "Link", "Message"], [["2024-02-03 09:00:00", "https://www.linkedin.com/feed/update/3", 'I said "yes"']]),
                      "Reactions.csv": csv_text(["Date", "Type", "Link"], [["2024-02-04 09:00:00", "LIKE", "https://www.linkedin.com/feed/update/4"]])})
        self.run_import()
        kinds = {}
        for r in self.of("linkedin"):
            kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
        self.assertEqual(kinds, {"profile": 1, "position": 1, "education": 1, "skill": 2, "invitation": 1, "post": 3, "reaction": 1})
        posts = {r["url"]: r for r in self.of("linkedin", "post")}
        self.assertEqual(posts["https://www.linkedin.com/feed/update/1"]["text"], '"Quoted," she said.\nTwo lines.')
        self.assertEqual(posts["https://www.linkedin.com/feed/update/3"]["text"], 'I said "yes"')
        pos = self.of("linkedin", "position")[0]
        self.assertEqual((pos["title"], pos["ts"]), ("Programmer · Analytical Engines", "1843-01-01T00:00:00"))
        inv = self.of("linkedin", "invitation")[0]
        self.assertEqual((inv["author"], inv["is_me"], inv["ts"]), ("Grace Hopper", False, "2024-01-15T10:00:00"))

    def test_a_damaged_file_stops_nothing(self):
        p = self.zip(LI, {"Skills.csv": csv_text(["Name"], [["Mathematics"]]),
                          "Connections.csv": NOTES + csv_text(["First Name", "Last Name", "URL", "Email Address", "Company", "Position", "Connected On"],
                                                              [["Grace", "Hopper", "", "", "", "", "01 Jan 2024"]])})
        raw = bytearray(p.read_bytes())
        i = raw.index(b"Mathematics")  # stored, not deflated: the member fails its check
        raw[i:i + 4] = b"MATH"
        p.write_bytes(bytes(raw))
        self.run_import()
        self.assertEqual([r["title"] for r in self.of("linkedin", "contact")], ["Grace Hopper"])


# ---------------------------------------------------------------- Discord

DM, GUILD, GROUP = "111111111111111111", "222222222222222222", "333333333333333333"


class DiscordTests(Base):
    def test_a_package_from_before_2024(self):
        # Lowercase folders, no "c" before a channel's id (before late 2021), messages.csv, numbers for channel types,
        # times with a zone, and a message over several lines.
        self.zip("discord/package-2020.zip", {
            "messages/index.json": {DM: None, GUILD: "general in Book Club", GROUP: None},
            f"messages/{DM}/channel.json": {"id": DM, "type": 1, "recipients": ["42", "7"]},
            f"messages/{DM}/messages.csv": "ID,Timestamp,Contents,Attachments\n"
                                           '1,2020-08-25 22:54:05.726000+00:00,"line one\nline two",\n'
                                           "2,2020-08-25 22:55:00+00:00,,https://cdn.discordapp.com/attachments/1/2/a.png\n",
            f"messages/{GUILD}/channel.json": {"id": GUILD, "type": 0, "name": "general", "guild": {"id": "9", "name": "Book Club"}},
            f"messages/{GUILD}/messages.csv": "ID,Timestamp,Contents,Attachments\n3,2020-08-26 10:00:00+00:00,hi all,\n",
            f"messages/{GROUP}/channel.json": {"id": GROUP, "type": 3, "recipients": ["42", "7", "8"]},
            f"messages/{GROUP}/messages.csv": "ID,Timestamp,Contents,Attachments\n4,2020-08-27 10:00:00+00:00,hello group,\n",
            "account/user.json": {"id": "42", "username": "ada", "relationships": [
                {"id": "7", "type": 1, "nickname": None, "user": {"id": "7", "username": "grace", "discriminator": "0001"}}]}})
        self.run_import()
        msgs = self.by_id("discord", "message")
        self.assertEqual(msgs[f"{DM}:1"]["text"], "line one\nline two")
        self.assertEqual(msgs[f"{DM}:1"]["ts"], "2020-08-25T22:54:05.726000Z")
        self.assertIn("a.png", msgs[f"{DM}:2"]["text"])
        self.assertEqual({k.split(":")[0]: v["thread_name"] for k, v in msgs.items()},
                         {DM: "DM with grace", GUILD: "general in Book Club", GROUP: "Group DM with grace +1"})

    def test_a_package_since_2024(self):
        c = "444444444444444444"
        u = "555555555555555555"
        self.zip("discord/package.zip", {
            "Messages/index.json": {u: "Direct Message with Unknown Participant"},
            f"Messages/c{c}/channel.json": {"id": c, "type": "GUILD_TEXT", "name": "general", "guild": {"id": "9", "name": "Book Club"}},
            f"Messages/c{c}/messages.json": [
                {"ID": 5, "Timestamp": "2024-01-01 10:00:00", "Contents": "hello", "Attachments": ""},
                {"ID": 6, "Timestamp": "2024-01-01 10:05:00", "Contents": "",
                 "Attachments": "https://cdn.discordapp.com/attachments/1/2/a.png https://cdn.discordapp.com/attachments/1/3/b.png"}],
            f"Messages/c{u}/channel.json": {"id": u, "type": "DM", "recipients": ["42", "999"]},
            f"Messages/c{u}/messages.json": [{"ID": 7, "Timestamp": "2024-01-02 10:00:00", "Contents": "hi stranger", "Attachments": ""}],
            "Account/user.json": {"id": "42", "username": "ada", "relationships": []},
            "Servers/index.json": {"9": "Book Club"},
            "Activity/analytics/events-2024-00000-of-00001.json": '{"event_type": "app_opened"}\n{"event_type": "send_message"}\n'})
        self.run_import()
        msgs = self.by_id("discord", "message")
        self.assertEqual((msgs[f"{c}:5"]["ts"], msgs[f"{c}:5"]["thread_name"]), ("2024-01-01T10:00:00Z", "general in Book Club"),
                         "Discord's times are UTC, written without a zone; a channel the index doesn't name is named by its server")
        self.assertIn("b.png", msgs[f"{c}:6"]["text"])
        self.assertEqual(msgs[f"{u}:7"]["thread_name"], "DM with 999", "someone not on the friends list, by their id")
        self.assertIn("events-2024-00000-of-00001.json", self.unclaimed())

    def test_a_package_in_another_language(self):
        c = "666666666666666666"
        self.zip("discord/package-de.zip", {
            "Nachrichten/index.json": {c: "allgemein in Lesekreis"},
            f"Nachrichten/c{c}/channel.json": {"id": c, "type": "GUILD_TEXT", "name": "allgemein", "guild": {"id": "9", "name": "Lesekreis"}},
            f"Nachrichten/c{c}/messages.json": [{"ID": 8, "Timestamp": "2025-07-01 10:00:00", "Contents": "Hallo", "Attachments": ""}]})
        self.run_import()
        self.assertEqual([(r["text"], r["thread_name"]) for r in self.of("discord", "message")], [("Hallo", "allgemein in Lesekreis")])

    def test_empty_and_broken_files_stop_nothing(self):
        good, cut = "777777777777777777", "888888888888888888"
        self.zip("discord/package.zip", {
            "Messages/index.json": "[]",
            "Account/user.json": '{"id": "42", "relationships": [{"id": ',
            f"Messages/c{cut}/channel.json": {"id": cut, "type": "DM"},
            f"Messages/c{cut}/messages.json": '[{"ID": 1, "Timestamp": "2024-01',
            f"Messages/c{good}/channel.json": "",
            f"Messages/c{good}/messages.json": [None, "x", {"ID": 2, "Timestamp": None, "Contents": "still here"}, {"ID": 3, "Contents": 5}]})
        self.run_import()
        self.assertEqual([r["text"] for r in self.of("discord", "message")], ["still here", "5"])
        self.assertIn("messages.json", self.unclaimed())


# ---------------------------------------------------------------- Spotify

class SpotifyTests(Base):
    def test_account_data_music_and_podcasts(self):
        a = "Spotify Account Data/"
        self.zip("spotify/my_spotify_data.zip", {
            a + "StreamingHistory_music_0.json": [{"endTime": "2024-01-01 10:00", "artistName": "Band A", "trackName": "Song A", "msPlayed": 200000}],
            a + "StreamingHistory_podcast_0.json": [{"endTime": "2024-01-02 08:00", "podcastName": "Show S", "episodeName": "Ep 1", "msPlayed": 1200000}]})
        self.zip("spotify/my_spotify_data_2022.zip", {"MyData/StreamingHistory0.json": [
            {"endTime": "2022-03-01 10:00", "artistName": "Band B", "trackName": "Song B", "msPlayed": 150000}]})
        self.run_import()
        plays = {r["title"]: r for r in self.of("spotify", "media")}
        self.assertEqual(set(plays), {"Song A", "Ep 1", "Song B"})
        self.assertEqual((plays["Song A"]["ts"], plays["Song A"]["meta"]["artist"], plays["Song A"]["meta"]["what"]), ("2024-01-01T10:00:00Z", "Band A", "song"))
        ep = plays["Ep 1"]["meta"]
        self.assertEqual((ep.get("artist"), ep["show"], ep["what"]), (None, "Show S", "episode"), "a podcast isn't a song by an artist")

    def test_extended_history_under_every_name_it_has_had(self):
        # endsong_N.json before 2023; Streaming_History_Audio_<years>_N.json and Streaming_History_Video_<years>.json since.
        old = [{"ts": "2021-05-01T10:00:00Z", "username": "ada", "platform": "iOS 14.4 (iPhone12,1)", "ms_played": 180000, "conn_country": "US",
                "ip_addr_decrypted": "203.0.113.5", "user_agent_decrypted": "unknown", "master_metadata_track_name": "Song C",
                "master_metadata_album_artist_name": "Band C", "master_metadata_album_album_name": "Album C", "spotify_track_uri": "spotify:track:c",
                "episode_name": None, "episode_show_name": None, "spotify_episode_uri": None, "reason_start": "trackdone", "reason_end": "trackdone",
                "shuffle": False, "skipped": None, "offline": False, "offline_timestamp": 0, "incognito_mode": False}]
        new = lambda **x: {"ts": "2016-01-01T10:00:00Z", "platform": "android", "ms_played": 600000, "conn_country": "PT", "ip_addr": "203.0.113.6",  # noqa: E731
                           "master_metadata_track_name": None, "master_metadata_album_artist_name": None, "master_metadata_album_album_name": None,
                           "spotify_track_uri": None, "episode_name": None, "episode_show_name": None, "spotify_episode_uri": None,
                           "audiobook_title": None, "audiobook_uri": None, "audiobook_chapter_uri": None, "audiobook_chapter_title": None,
                           "reason_start": "clickrow", "reason_end": "endplay", "shuffle": False, "skipped": False, "offline": False,
                           "offline_timestamp": None, "incognito_mode": False, **x}
        self.zip("spotify/my_spotify_data (old).zip", {"MyData/endsong_0.json": old, "MyData/Read_Me_First.pdf": b"%PDF-1.4"})
        x = "Spotify Extended Streaming History/"
        self.zip("spotify/my_spotify_data (1).zip", {
            x + "Streaming_History_Audio_2014-2016_0.json": [
                new(master_metadata_track_name="Song D", master_metadata_album_artist_name="Band D", spotify_track_uri="spotify:track:d"),
                new(ts="2016-01-02T10:00:00Z", episode_name="Ep 2", episode_show_name="Show S", spotify_episode_uri="spotify:episode:e2")],
            x + "Streaming_History_Video_2020-2024.json": [new(ts="2021-01-02T10:00:00Z", episode_name="Video ep", episode_show_name="Show V")]})
        self.run_import()
        plays = {r["title"]: r for r in self.of("spotify", "media")}
        self.assertEqual(set(plays), {"Song C", "Song D", "Ep 2", "Video ep"})
        self.assertEqual((plays["Song C"]["meta"]["artist"], plays["Song C"]["meta"]["what"]), ("Band C", "song"))
        self.assertEqual((plays["Ep 2"]["meta"].get("artist"), plays["Ep 2"]["meta"]["show"]), (None, "Show S"))
        out = json.dumps(self.recs)
        self.assertNotIn("203.0.113", out, "IP addresses stay out")
        self.assertNotIn("spotify_other", self.recs)

    def test_empty_and_broken_files_stop_nothing(self):
        a = "Spotify Account Data/"
        self.zip("spotify/my_spotify_data.zip", {
            a + "StreamingHistory_music_0.json": '[{"endTime": "2024-01-01 10:00", "artistN',
            a + "StreamingHistory_music_1.json": [None, 3, {"endTime": None, "trackName": "No time", "msPlayed": 200000},
                                                  {"endTime": "2024-01-03 10:00", "artistName": "Band A", "trackName": "Still here", "msPlayed": "200000"}],
            a + "Playlist1.json": "not json",
            a + "YourLibrary.json": [],
            a + "SearchQueries.json": {"a": 1},
            a + "Inferences.json": {"inferences": None}})
        self.run_import()
        self.assertEqual(sorted(r["title"] for r in self.of("spotify", "media")), ["No time", "Still here"])
        self.assertIn("StreamingHistory_music_0.json", self.unclaimed())


# ---------------------------------------------------------------- Notion

N1 = "Export-0a1b2c3d-1111-2222-3333-444455556666"
P1, P2, P3 = "1" * 32, "2" * 32, "3" * 32


class NotionTests(Base):
    def test_an_export_in_parts_inside_its_zip(self):
        # A big workspace comes as one zip holding Export-<id>-Part-1.zip, -Part-2.zip ...: a page in one, its subpage
        # and the subpage's photo in another.
        part1 = self.zip_bytes({f"Private & Shared/Trips {P1}.md": "# Trips\n\nCreated: January 1, 2024 10:00 AM\n\nWhere next?",
                                f"Private & Shared/Garden {P3}.md": "# Garden\n\nCreated: March 2, 2024 14:30\n\nBeds.",
                                # a subpage's folder named without its page's id, as some exports have it
                                f"Private & Shared/Garden/Beds {'4' * 32}.md": "# Beds\n\nTomatoes."})
        part2 = self.zip_bytes({f"Private & Shared/Trips {P1}/Lisbon {P2}.md": f"# Lisbon\n\nTrams.\n\n![photo](Lisbon%20{P2}/tram.jpg)",
                                f"Private & Shared/Trips {P1}/Lisbon {P2}/tram.jpg": b"jpg"})
        self.zip(f"notion/{N1}.zip", {f"{N1}-Part-1.zip": part1, f"{N1}-Part-2.zip": part2})
        self.run_import()
        pages = self.by_id("notion_export", "note")
        self.assertEqual(pages[P2]["thread_name"], "Private & Shared › Trips")
        self.assertEqual((pages[P2]["ts"], pages[P2]["meta"]["ts_from"]), ("2024-01-01T15:00:00Z", "parent page"))
        self.assertEqual([Path(f).name for f in pages[P2]["meta"]["files"]], ["tram.jpg"])
        self.assertEqual((pages[P3]["ts"], pages["4" * 32]["ts"]), ("2024-03-02T19:30:00Z", "2024-03-02T19:30:00Z"))
        self.assertNotIn("notion_files", self.recs)

    def test_a_workspace_exported_twice(self):
        page = {f"Private & Shared/Garden {P1}.md": "# Garden\n\nTomatoes", f"Private & Shared/Plants {P3}.csv": "Name,Kind\nTomato,Fruit\n",
                f"Private & Shared/Plants {P3}_all.csv": "Name,Kind\nTomato,Fruit\nBasil,Herb\n"}
        self.zip(f"notion/{N1}.zip", page)
        self.zip("notion/Export-9a1b2c3d-1111-2222-3333-444455556666.zip", page)
        self.run_import()
        self.assertEqual(sorted(r["id"] for r in self.of("notion_export")), [P1, f"{P3}:table"])
        self.assertIn("Basil", self.of("notion_export", "database")[0]["text"], "the _all view")

    def test_the_html_export(self):
        page = (f'<html><head><meta charset="utf-8"><title>Garden</title><style>body {{ margin: 0 }}</style></head><body>'
                f'<article id="{P1}" class="page sans"><header><h1 class="page-title">Garden</h1><table class="properties"><tbody>'
                '<tr class="property-row property-row-created_time"><th>Created</th><td><time>@January 1, 2024 10:00 AM</time></td></tr>'
                '</tbody></table></header><div class="page-body"><p>Tomatoes in bed 2</p><ul><li>Basil</li></ul></div></article></body></html>')
        self.zip(f"notion/{N1}.zip", {"index.html": "<html><body><a href='Private%20%26%20Shared/Garden.html'>Garden</a></body></html>",
                                      f"Private & Shared/Garden {P1}.html": page})
        self.run_import()
        (note,) = self.of("notion_export", "note")
        self.assertEqual((note["id"], note["title"], note["ts"]), (P1, "Garden", "2024-01-01T15:00:00Z"))
        self.assertIn("Tomatoes in bed 2", note["text"])
        self.assertNotIn("margin", note["text"])
        self.assertNotIn("imported_documents", self.recs, "not a document as well, nor is the export's index")


# ---------------------------------------------------------------- ChatGPT

def node(id_, parent, children, role=None, content=None, t=None, **meta):
    m = None if role is None else {"id": id_, "author": {"role": role, "name": meta.pop("name", None), "metadata": {}}, "create_time": t,
                                   "content": content, "status": "finished_successfully", "metadata": meta, "recipient": meta.pop("recipient", "all")}
    return {"id": id_, "message": m, "parent": parent, "children": children}


def text(*parts):
    return {"content_type": "text", "parts": list(parts)}


def convo(id_, title, nodes, current, t=T):
    return {"id": id_, "conversation_id": id_, "title": title, "create_time": t, "update_time": t + 100, "current_node": current,
            "mapping": {n["id"]: n for n in nodes}}


class ChatGPTTests(Base):
    def test_regenerated_answers_and_edited_prompts_are_kept_apart(self):
        self.files("chatgpt/export", {"conversations.json": [convo("c1", "Tides", [
            node("r", None, ["u1", "u1b"]),
            node("u1", "r", ["a1", "a1b"], "user", text("What causes tides?"), T),
            node("a1", "u1", [], "assistant", text("The moon."), T + 5),
            node("a1b", "u1", [], "assistant", text("Mostly the moon's gravity."), T + 30),  # regenerated: the one shown
            node("u1b", "r", [], "user", text("What causes tides??"), T + 1)], "a1b")]})
        self.run_import()
        turns = self.by_id("chatgpt", "ai_turn")
        self.assertEqual(set(turns), {"u1", "a1", "a1b", "u1b"})
        self.assertEqual({k: v.get("meta", {}).get("tier") for k, v in turns.items()},
                         {"u1": None, "a1b": None, "a1": "superseded", "u1b": "superseded"})

    def test_every_kind_of_content(self):
        hidden = {"is_visually_hidden_from_conversation": True}
        nodes = [
            node("r", None, ["s"]),
            node("s", "r", ["ctx"], "system", text(""), None, **hidden),
            node("ctx", "s", ["u1"], "user", {"content_type": "user_editable_context", "user_profile": "I'm a sailor in Lisbon.",
                                              "user_instructions": "Answer briefly."}, None, **hidden),
            node("u1", "ctx", ["u2"], "user", {"content_type": "multimodal_text", "parts": [
                {"content_type": "image_asset_pointer", "asset_pointer": "file-service://file-abc", "width": 10, "height": 10},
                "What is in this photo?"]}, T, attachments=[{"id": "file-abc", "name": "beach.jpg", "size": 3}]),
            node("u2", "u1", ["a1"], "user", {"content_type": "multimodal_text", "parts": [
                {"content_type": "image_asset_pointer", "asset_pointer": "file-service://file-def"}]}, T + 1),
            node("a1", "u2", ["code"], "assistant", {"content_type": "thoughts", "thoughts": [{"summary": "Looking", "content": "The user sent a beach."}]}, T + 2),
            node("code", "a1", ["out"], "assistant", {"content_type": "code", "language": "python", "text": "print(2+2)"}, T + 3, recipient="python"),
            node("out", "code", ["q"], "tool", {"content_type": "execution_output", "text": "4"}, T + 4, name="python"),
            node("q", "out", ["recap"], "tool", {"content_type": "tether_quote", "url": "https://example.com/tides", "domain": "example.com",
                                                  "title": "Tides", "text": "Tides are caused by the moon."}, T + 5, name="browser"),
            node("recap", "q", ["a2"], "assistant", {"content_type": "reasoning_recap", "content": "Thought for 3 seconds"}, T + 6),
            node("a2", "recap", ["v"], "assistant", text("A beach at low tide."), None),  # no time of its own
            node("v", "a2", ["mem"], "user", {"content_type": "multimodal_text", "parts": [
                {"content_type": "audio_transcription", "text": "Is it high tide?", "direction": "in"},
                {"content_type": "audio_asset_pointer", "asset_pointer": "sediment://file_1", "size_bytes": 100}]}, T + 8),
            node("mem", "v", ["img"], "assistant", {"content_type": "model_editable_context", "model_set_context": "1. Sails in Lisbon."}, T + 9, **hidden),
            node("img", "mem", [], "tool", {"content_type": "multimodal_text", "parts": [
                {"content_type": "image_asset_pointer", "asset_pointer": "file-service://file-gen"}]}, T + 10, name="dalle.text2im")]
        again = [node("r", None, ["ctx"]),
                 node("ctx", "r", ["u"], "user", {"content_type": "user_editable_context", "user_profile": "I'm a sailor in Lisbon.",
                                                  "user_instructions": "Answer briefly."}, None, **hidden),
                 node("u", "ctx", [], "user", text("Hello"), T + 100)]
        self.files("chatgpt/export", {
            "conversations.json": [convo("c2", "Beach", nodes, "img"), convo("c3", "Hi", again, "u", T + 100)],
            "user.json": {"id": "user-abc", "email": "ada@example.com", "chatgpt_plus_user": True},
            "shared_conversations.json": [{"id": "s1", "conversation_id": "c2", "title": "Beach", "is_anonymous": True}],
            "message_feedback.json": [{"id": "f1", "conversation_id": "c2", "rating": "thumbsUp", "create_time": "2026-09-21T14:13:20Z"}],
            "chat.html": "<html><body>Beach</body></html>"})
        self.run_import()
        turns = self.by_id("chatgpt", "ai_turn")
        self.assertEqual(turns["u1"]["text"], "[image]\nWhat is in this photo?\n[attachment: beach.jpg]")
        self.assertEqual(turns["u2"]["text"], "[image]", "a photo sent alone is a turn too")
        self.assertIn("print(2+2)", turns["code"]["text"])
        self.assertEqual((turns["out"]["text"], turns["out"]["author"], turns["out"]["is_me"]), ("4", "chatgpt", False))
        self.assertIn("Tides are caused by the moon.", turns["q"]["text"])
        self.assertEqual(turns["a2"]["ts"], "2026-09-21T14:13:20Z", "the conversation's time, for a turn without one")
        self.assertEqual(turns["v"]["text"], "Is it high tide?")
        self.assertEqual((turns["img"]["text"], turns["img"]["meta"]["from"]), ("[image]", "dalle.text2im"), "a picture it made")
        self.assertFalse({"s", "ctx", "a1", "recap", "mem"} & set(turns), "hidden turns and the model's own thinking stay out")
        notes = self.of("chatgpt", "note")
        self.assertEqual(len([n for n in notes if "sailor in Lisbon" in n["text"]]), 1, "custom instructions, once")
        self.assertTrue(any("Sails in Lisbon" in n["text"] and not n["is_me"] for n in notes), "what ChatGPT remembered")
        self.assertNotIn("imported_documents", self.recs, "chat.html is the same chats")

    def test_odd_trees_stop_nothing(self):
        self.files("chatgpt/export", {"conversations.json": [
            None,
            convo("c4", "No current node", [node("r", None, ["u"]), node("u", "r", ["a"], "user", text("first"), T),
                                            node("a", "u", [], "assistant", text("second"), T + 1)], None),
            convo("c5", "A loop", [node("x", "y", ["y"], "user", text("in a loop"), T), node("y", "x", ["x"], "assistant", text("around"), T + 1)], "x"),
            convo("c6", "Odd nodes", [node("r", None, ["u"]), {"id": "u", "message": "oops", "parent": "r", "children": []},
                                      node("w", "r", [], "user", {"content_type": "text", "parts": [None, 3, "ok"]}, T)], "w")]})
        self.run_import(timeout=60)
        self.assertEqual(sorted(r["text"] for r in self.of("chatgpt", "ai_turn")), ["around", "first", "in a loop", "ok", "second"])


# ---------------------------------------------------------------- Claude.ai

def claude_msg(uuid, sender, text_, content=None, **extra):
    return {"uuid": uuid, "sender": sender, "text": text_, "content": content if content is not None else [{"type": "text", "text": text_}],
            "created_at": "2026-09-01T10:00:00Z", "updated_at": "2026-09-01T10:00:00Z", "attachments": [], "files": [], **extra}


class ClaudeTests(Base):
    def test_content_blocks_artifacts_and_the_placeholder(self):
        placeholder = "\n\n```\nThis block is not supported on your current device yet.\n```\n\n"
        msgs = [
            claude_msg("m1", "human", "Write me a fib function"),
            claude_msg("m2", "assistant", "Here it is." + placeholder + "Done.", [
                {"type": "thinking", "thinking": "The user wants a Fibonacci function.", "summaries": [{"summary": "Planning"}]},
                {"type": "text", "text": "Here it is.", "citations": []},
                {"type": "tool_use", "name": "artifacts", "input": {"id": "fib", "type": "application/vnd.ant.code", "title": "fib.py",
                                                                    "command": "create", "language": "python", "content": "def fib(n):\n    return n"}},
                {"type": "tool_result", "name": "artifacts", "content": [{"type": "text", "text": "OK"}], "is_error": False},
                {"type": "text", "text": "Done."}]),
            claude_msg("m3", "assistant", placeholder + "It is 12,586,269,025.", [
                {"type": "tool_use", "name": "web_search", "input": {"query": "50th fibonacci number"}},
                {"type": "tool_result", "name": "web_search", "content": [{"type": "knowledge", "title": "Fibonacci number", "url": "https://example.com/fib",
                                                                           "text": "F(50) = 12586269025"}]},
                {"type": "some_future_block", "payload": {"x": 1}},
                {"type": "text", "text": "It is 12,586,269,025."},
                {"type": "tool_use", "name": "artifacts", "input": {"id": "fib", "command": "update", "title": "fib.py", "old_str": "def fib", "new_str": "def fibonacci"}}]),
            claude_msg("m4", "human", None, ["a string", None, {"type": "text", "text": "odd blocks"}], attachments="nope", files=[None])]
        self.zip("claude/data-2026-10-01-batch-0000.zip", {"conversations.json": [
            {"uuid": "c1", "name": "Fib", "summary": "", "created_at": "2026-09-01T10:00:00Z", "chat_messages": msgs}, None,
            {"uuid": "c2", "name": "Empty", "chat_messages": None}]})
        self.zip("claude/data-2026-10-01-batch-0001.zip", {"conversations.json": [
            {"uuid": "c3", "name": "Later", "created_at": "2026-09-02T10:00:00Z", "chat_messages": [claude_msg("m5", "human", "from the second batch")]}]})
        self.run_import()
        turns = self.by_id("claude_ai", "ai_turn")
        self.assertEqual(set(turns), {"m1", "m2", "m3", "m4", "m5"})
        m2 = turns["m2"]["text"]
        self.assertTrue(m2.startswith("Here it is.") and m2.endswith("Done."), m2)
        self.assertIn("def fib(n):\n    return n", m2)
        self.assertNotIn("not supported on your current device", m2)
        self.assertNotIn("The user wants", m2, "Claude's thinking stays out")
        m3 = turns["m3"]["text"]
        for s in ("50th fibonacci number", "It is 12,586,269,025.", "def fibonacci"):
            self.assertIn(s, m3)
        self.assertNotIn("not supported", m3)
        self.assertEqual(turns["m4"]["text"], "odd blocks")

    def test_projects_folder_memories_and_users(self):
        self.zip("claude/data-2026-10-01-batch-0000.zip", {
            "conversations.json": [{"uuid": "c1", "name": "Hi", "chat_messages": [claude_msg("m1", "human", "hello")]}],
            "projects/p1.json": {"uuid": "p1", "name": "Garden plans", "description": "Planting", "prompt_template": "Answer briefly",
                                 "created_at": "2026-08-01T00:00:00Z", "creator": {"uuid": "u1", "full_name": "Ada Lovelace"},
                                 "docs": [{"uuid": "d1", "filename": "beds.md", "content": "Tomatoes in bed 2", "created_at": "2026-08-01T01:00:00Z"}]},
            "memories.json": [{"conversations_memory": "**Work**\nAda is a mathematician.", "project_memories": {"p1": "The garden is in Lisbon."},
                               "memory_files": [{"path": "/profile.md", "content": "Name: Ada", "updated_at": "2026-09-01T00:00:00Z"}],
                               "account_uuid": "acc1"}],
            "users.json": [{"uuid": "u1", "full_name": "Ada Lovelace", "email_address": "ada@example.com"}]})
        self.run_import()
        notes = {r["title"]: r for r in self.of("claude_ai", "note")}
        self.assertIn("Instructions: Answer briefly", notes["Garden plans"]["text"])
        self.assertEqual([(d["title"], d["text"]) for d in self.of("claude_ai", "document")], [("beds.md", "Tomatoes in bed 2")])
        memories = [r for r in self.of("claude_ai", "note") if r.get("meta", {}).get("memory")]
        self.assertEqual(sorted(r["text"] for r in memories), ["**Work**\nAda is a mathematician.", "Name: Ada", "The garden is in Lisbon."])
        self.assertFalse(any(r["is_me"] for r in memories), "what Claude remembered, not what you wrote")
        self.assertEqual(next(r for r in memories if "garden" in r["text"])["thread_name"], "Garden plans")
        self.assertTrue({"p1.json", "memories.json"}.isdisjoint(self.unclaimed()))


if __name__ == "__main__":
    unittest.main()
