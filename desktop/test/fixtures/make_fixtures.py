#!/usr/bin/env python3
"""Synthetic exports and a fake home folder for the tests. Shapes follow what connectors/imports.py and
the Mac connectors read, so the real parsers run on them.

    make_fixtures.py exports <dir>    one file per export kind (plus broken and unknown ones)
    make_fixtures.py home <dir>       a fake $HOME: Claude Code sessions, a git repo, Mail, Messages, settings
    make_fixtures.py backup <home>    a fake encrypted Finder backup under <home>/Library/.../MobileSync/Backup
    make_fixtures.py ask-corpus <dir> a small indexed corpus (corpus.db) for the Ask assistant
    make_fixtures.py cited-corpus <dir> one for opening what an answer cites (conversations, events)
"""

import collections
import datetime as dt
import io
import json
import os
import plistlib
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

ME = {"names": ["Ada Lovelace"], "emails": ["ada@example.com"], "usernames": ["ada_l"], "phones": []}


def _zip(path, files):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data if isinstance(data, (bytes, str)) else json.dumps(data))
    return path


MBOX = (
    "From MAILER-DAEMON Thu Jan  4 10:00:00 2024\n"
    "From: Ada Lovelace <ada@example.com>\nTo: Charles Babbage <charles@example.com>\n"
    "Subject: The engine\nDate: Thu, 04 Jan 2024 10:00:00 +0000\nMessage-ID: <1@example.com>\n\n"
    "Notes on the analytical engine.\n\n"
    "From MAILER-DAEMON Fri Jan  5 11:00:00 2024\n"
    "From: Charles Babbage <charles@example.com>\nTo: Ada Lovelace <ada@example.com>\n"
    "Subject: Re: The engine\nDate: Fri, 05 Jan 2024 11:00:00 +0000\nMessage-ID: <2@example.com>\n\n"
    "Splendid.\n\n"
)


def discord_files():
    return {
        "README.txt": "Discord data package",
        "Account/user.json": {"id": "1", "username": "ada_l", "relationships": [{"id": "2", "user": {"id": "2", "username": "charles"}}]},
        "Messages/index.json": {"123": "general in Test Server", "456": None},
        "Messages/c123/channel.json": {"id": "123", "type": 0, "name": "general", "guild": {"id": "9", "name": "Test Server"}},
        "Messages/c123/messages.json": [
            {"ID": "1001", "Timestamp": "2024-01-02 03:04:05", "Contents": "hello from the fixture", "Attachments": ""},
            {"ID": "1002", "Timestamp": "2024-01-03 04:05:06", "Contents": "second message", "Attachments": ""},
        ],
        "Messages/c456/channel.json": {"id": "456", "type": 1, "recipients": ["1", "2"]},
        "Messages/c456/messages.json": [{"ID": "2001", "Timestamp": "2024-02-01 10:00:00", "Contents": "a DM", "Attachments": ""}],
        "Servers/index.json": {"9": "Test Server"},
    }


def linkedin_files():
    return {
        "Connections.csv": "First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
                           "Charles,Babbage,https://www.linkedin.com/in/cb,,Difference Engines,Inventor,04 Jan 2024\n",
        "Registration.csv": "Registered At,Registration Ip,Subscription Types\n1/2/16, 10:00 AM,1.2.3.4,Basic\n",
        "Skills.csv": "Name\nMathematics\n",
        "Email Addresses.csv": "Email Address,Confirmed,Primary,Updated On\nada@example.com,Yes,Yes,\nada.work@example.com,Yes,No,\n",
        "Profile.csv": "First Name,Last Name,Headline\nAda,Lovelace,Analyst\n",
    }


def exports(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    made = {}
    made["google_takeout"] = _zip(out / "takeout-20250301T120000Z-1-001.zip", {
        "Takeout/Mail/All mail Including Spam and Trash.mbox": MBOX,
        "Takeout/Chrome/History.json": {"Browser History": [{"title": "Fixture", "url": "https://example.com/", "time_usec": 1704067200000000}]},
        "Takeout/YouTube and YouTube Music/comments/comments.csv":
            "Comment ID,Channel ID,Comment Create Timestamp,Price,Parent Comment ID,Post ID,Video ID,Comment Text,Top-Level Comment ID\n"
            'c1,UCada,2024-01-02T10:00:00.123+00:00,0,,,vid00000001,"{""text"":""What a machine""}",\n',
        "Takeout/Tasks/Tasks.json": {"kind": "tasks#taskLists", "items": [{"kind": "tasks#tasks", "id": "L1", "title": "My Tasks", "items": [
            {"kind": "tasks#task", "id": "t1", "title": "Write the notes", "status": "needsAction", "created": "2024-01-03T09:00:00.000Z"}]}]},
    })
    made["google_photos_drive"] = _zip(out / "takeout-20250302T000000Z-1-001.zip", {
        "Takeout/Google Photos/Trip/IMG_0001.jpg.json": {"title": "IMG_0001.jpg", "photoTakenTime": {"timestamp": "1704067200"}},
    })
    made["instagram"] = _zip(out / "instagram-ada_l-2025-03-01-abc.zip", {
        "your_instagram_activity/messages/inbox/charles_1/message_1.json": {
            "participants": [{"name": "Charles"}, {"name": "Ada Lovelace"}], "title": "Charles",
            "messages": [{"sender_name": "Ada Lovelace", "timestamp_ms": 1704067200000, "content": "hi"}]},
        "personal_information/personal_information/personal_information.json": {},
    })
    made["facebook"] = _zip(out / "facebook-ada-2025-03-01-xyz.zip", {
        "your_facebook_activity/messages/inbox/charles_1/message_1.json": {
            "participants": [{"name": "Charles"}, {"name": "Ada Lovelace"}], "title": "Charles",
            "messages": [{"sender_name": "Charles", "timestamp_ms": 1704067200000, "content": "hello"}]},
    })
    made["discord"] = _zip(out / "package.zip", discord_files())
    made["linkedin"] = _zip(out / "Complete_LinkedInDataExport_03-01-2025.zip", linkedin_files())
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z:
        for k, v in linkedin_files().items():
            z.writestr(k, v)
    made["linkedin_nested"] = _zip(out / "Basic_LinkedInDataExport_03-02-2025.zip.zip", {"Basic_LinkedInDataExport_03-02-2025.zip": inner.getvalue()})
    made["notion"] = _zip(out / "Export-1a2b3c4d-0000-4000-8000-00000000abcd.zip", {
        "Export-1a2b3c4d-0000-4000-8000-00000000abcd/Private & Shared/Research 0123456789abcdef0123456789abcdef.md": "# Research\nNotes.",
        "Export-1a2b3c4d-0000-4000-8000-00000000abcd/Private & Shared/Ideas fedcba9876543210fedcba9876543210.md": "# Ideas\nMore.",
    })
    made["x"] = _zip(out / "twitter-2025-03-01-abc.zip", {
        "data/account.js": 'window.YTD.account.part0 = [{"account": {"accountId": "42", "username": "ada_l"}}]',
        "data/tweets.js": 'window.YTD.tweets.part0 = [{"tweet": {"id_str": "1", "full_text": "first post", "created_at": "Tue Jan 02 03:04:05 +0000 2024"}}]',
    })
    made["x_malformed"] = _zip(out / "twitter-2025-03-02-old.zip", {
        "data/account.js": 'window.YTD.account.part0 = [{"account": {"username": "ada_l"}}]',
        "data/tweets.js": 'window.YTD.tweets.part0 = []',
    })
    made["chatgpt"] = _zip(out / "4f1c-2025-03-01-chatgpt.zip", {
        "conversations.json": [{"title": "Engines", "create_time": 1704067200, "mapping": {"a": {"id": "a", "message": None, "parent": None, "children": []}}, "current_node": "a"}],
        "chat.html": "<html></html>",
    })
    made["claude_ai"] = _zip(out / "data-2025-03-01-batch-0000.zip", {
        "conversations.json": [{"uuid": "c1", "name": "Engines", "created_at": "2024-01-01T00:00:00Z", "chat_messages": []}],
        "users.json": [{"uuid": "u1"}],
    })
    made["spotify"] = _zip(out / "my_spotify_data.zip", {
        "Spotify Extended Streaming History/Streaming_History_Audio_2024.json": [{"ts": "2024-01-01T00:00:00Z", "master_metadata_track_name": "Song", "master_metadata_album_artist_name": "Band", "ms_played": 180000}],
    })
    made["spotify_empty"] = _zip(out / "my_spotify_data (account only).zip", {
        "Spotify Account Data/StreamingHistory_music_0.json": [{"endTime": "2024-01-01 00:00", "trackName": "Skip", "msPlayed": 2000}],
    })
    made["reddit"] = _zip(out / "export_ada_l_20250301.zip", {
        "comments.csv": "id,permalink,date,body\n1,/r/x/1,2024-01-01 00:00:00 UTC,hi\n",
        "posts.csv": "id,permalink,date,title,body\n",
        "statistics.csv": "statistic,value\n",
    })
    made["whatsapp_chats"] = _zip(out / "WhatsApp Chat - Charles.zip", {
        "_chat.txt": "[1/2/24, 3:04:05 AM] Charles: hello\n[1/2/24, 3:05:00 AM] Ada Lovelace: hi\n",
    })
    made["slack"] = _zip(out / "Slack export Mar 1 2025.zip", {
        "users.json": [{"id": "U1", "name": "ada_l"}], "channels.json": [{"id": "C1", "name": "general"}],
        "general/2024-01-01.json": [{"user": "U1", "text": "hello", "ts": "1704067200.000100"}],
    })
    (out / "All Contacts.vcf").write_text("BEGIN:VCARD\nVERSION:3.0\nFN:Charles Babbage\nTEL:+14155550100\nEND:VCARD\n")
    made["iphone_vcard"] = out / "All Contacts.vcf"
    (out / "Inbox.mbox").mkdir(exist_ok=True)
    (out / "Inbox.mbox" / "mbox").write_text(MBOX)
    made["mailbox"] = out / "Inbox.mbox"
    (out / "meeting.vtt").write_text("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nAda Lovelace: hello\n")
    made["zoom"] = out / "meeting.vtt"
    (out / "Timeline.json").write_text(json.dumps({"semanticSegments": [
        {"startTime": "2024-01-02T03:00:00.000-08:00", "endTime": "2024-01-02T05:00:00.000-08:00",
         "visit": {"topCandidate": {"placeId": "p1", "semanticType": "HOME", "placeLocation": {"latLng": "37.4°, -122.1°"}}}}]}))
    made["maps_timeline"] = out / "Timeline.json"
    made["unknown"] = _zip(out / "holiday-photos.zip", {"IMG_0001.txt": "not an export"})
    good = _zip(out / "_tmp.zip", discord_files())
    (out / "package-broken.zip").write_bytes(good.read_bytes()[: good.stat().st_size // 2])
    good.unlink()
    made["broken"] = out / "package-broken.zip"
    unz = out / "takeout-20250303T000000Z-1-001"
    (unz / "Takeout/Mail").mkdir(parents=True, exist_ok=True)
    (unz / "Takeout/Mail/All mail Including Spam and Trash.mbox").write_text(MBOX)
    made["google_takeout_folder"] = unz
    # slackdump's export: a thread, a reply the next day, reactions, a file it downloaded (__uploads/<id>/<name>)
    t = 1704067200
    users = [{"id": "U01", "name": "ada", "real_name": "Ada Lovelace"}, {"id": "U02", "name": "charles", "real_name": "Charles Babbage"}]
    made["slack"] = _zip(out / "slackdump_20250301_120000.zip", {
        "users.json": users, "channels.json": [{"id": "C01", "name": "engine", "members": ["U01", "U02"]}], "dms.json": [],
        "engine/2024-01-01.json": [{"type": "message", "user": "U02", "text": "The mill turns at last", "ts": f"{t}.000100",
                                    "thread_ts": f"{t}.000100", "reply_count": 1, "files": [{"id": "F0FIXTURE1", "name": "mill.jpg"}],
                                    "reactions": [{"name": "tada", "users": ["U01"], "count": 1}]}],
        "engine/2024-01-02.json": [{"type": "message", "user": "U01", "text": "Then the notes can run", "ts": f"{t + 86400}.000200",
                                    "thread_ts": f"{t}.000100", "parent_user_id": "U02"}],
        "__uploads/F0FIXTURE1/mill.jpg": b"\xff\xd8\xff\xe0 fixture"})
    # Telegram Desktop's JSON export, as the folder it saves (DataExport_<date>/result.json)
    tg = out / "Telegram Desktop" / "DataExport_2025-03-01"
    tg.mkdir(parents=True, exist_ok=True)
    (tg / "result.json").write_text(json.dumps({"personal_information": {"user_id": 11, "first_name": "Ada"}, "chats": {"list": [
        {"name": "Charles Babbage", "type": "personal_chat", "id": 4401, "messages": [
            {"id": 1, "type": "message", "date_unixtime": str(t), "from": "Charles Babbage", "from_id": "user77", "text": "Tea at four?",
             "reactions": [{"type": "emoji", "emoji": "❤", "count": 1, "recent": [{"from": "Ada Lovelace", "from_id": "user11", "date": "2024-01-01T00:01:00"}]}]},
            {"id": 2, "type": "message", "date_unixtime": str(t + 60), "from": "Ada Lovelace", "from_id": "user11", "text": "Four it is",
             "reply_to_message_id": 1}]}]}}))
    made["telegram"] = tg
    return {k: str(v) for k, v in made.items()}


def home(root):
    root = Path(root)
    (root / "Library/Mail").mkdir(parents=True, exist_ok=True)
    (root / "Library/Messages").mkdir(parents=True, exist_ok=True)
    (root / "Library/Preferences").mkdir(parents=True, exist_ok=True)
    (root / "Downloads").mkdir(parents=True, exist_ok=True)
    (root / "Library/Preferences/com.apple.MobileSMS.plist").write_bytes(plistlib.dumps({"KeepMessageForDays": 0}))
    # Where a Mac says who its owner is: Apple ID, iMessage addresses, the Claude account.
    (root / "Library/Preferences/MobileMeAccounts.plist").write_bytes(plistlib.dumps({"Accounts": [{"AccountID": "ada.lovelace@icloud.example"}]}))
    (root / "Library/Preferences/com.apple.madrid.plist").write_bytes(plistlib.dumps(
        {"IMD-IDS-Aliases": {"allAliases": ["ada@example.com", "+14155550100"], "selectedAliases": ["ada@example.com"]}}))
    (root / ".claude.json").write_text(json.dumps({"oauthAccount": {"emailAddress": "ada@example.com", "fullName": "Ada Lovelace"}}))
    proj = root / ".claude/projects/-Users-ada-engine"
    proj.mkdir(parents=True, exist_ok=True)
    (root / ".claude/settings.json").write_text(json.dumps({"theme": "dark", "cleanupPeriodDays": 7}))
    lines = [
        {"type": "user", "uuid": "u-1", "sessionId": "s-1", "timestamp": "2026-10-01T10:00:00Z", "cwd": "/Users/ada/engine",
         "message": {"role": "user", "content": "Add a test for the difference engine"}},
        {"type": "assistant", "uuid": "a-1", "sessionId": "s-1", "timestamp": "2026-10-01T10:00:05Z",
         "message": {"role": "assistant", "model": "claude-test", "content": [{"type": "text", "text": "Added test_engine.py."}]}},
    ]
    (proj / "s-1.jsonl").write_text("\n".join(json.dumps(l) for l in lines) + "\n")
    repo = root / "Documents/engine"
    repo.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "GIT_AUTHOR_NAME": "Ada Lovelace", "GIT_AUTHOR_EMAIL": "ada@example.com",
           "GIT_COMMITTER_NAME": "Ada Lovelace", "GIT_COMMITTER_EMAIL": "ada@example.com",
           "GIT_AUTHOR_DATE": "2024-01-02T03:04:05Z", "GIT_COMMITTER_DATE": "2024-01-02T03:04:05Z", "HOME": str(root),
           "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env)
    (repo / "notes.txt").write_text("first\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-q", "-m", "Start the engine"], check=True, env=env)
    return str(root)


def backup(home_dir, encrypted=True, finished=True, device="Test iPhone", when=None):
    when = when or dt.datetime(2026, 9, 1, 10, 0, 0)
    d = Path(home_dir) / "Library/Application Support/MobileSync/Backup/00008120-TEST"
    d.mkdir(parents=True, exist_ok=True)
    (d / "Info.plist").write_bytes(plistlib.dumps(
        {"Device Name": device, "Product Type": "iPhone99,1", "Product Version": "26.0", "Last Backup Date": when}))
    (d / "Manifest.plist").write_bytes(plistlib.dumps({"IsEncrypted": encrypted, "Version": "10.0"}))
    (d / "Status.plist").write_bytes(plistlib.dumps({"SnapshotState": "finished" if finished else "uploading", "Date": when}))
    (d / "Manifest.db").write_bytes(b"")
    return str(d)


def ask_corpus(corpus):
    """A small corpus for the Ask assistant's tests, indexed like the real one: chats, a document whose original
    holds a fake API key, a photo with its picture, calendar events. Everyone in it is made up."""
    corpus = Path(corpus)
    norm = corpus / "normalized"
    norm.mkdir(parents=True, exist_ok=True)
    files = corpus / "files"
    files.mkdir(exist_ok=True)
    doc = files / "trip-notes.txt"
    doc.write_text("Packing list for Lisbon\n" + "Bring sunscreen and the blue jacket.\n" * 40
                   + "Booking site api_key = sk-ant-api03-FAKEFAKEFAKEFAKEFAKEFAKE0000\nThe end.\n")
    # An 8x8 PNG (one color), so view_image has a picture to send.
    png = files / "IMG_0001.png"
    png.write_bytes(bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000008000000080802000000"
        "4b6d29dc0000001549444154789c63fccfc0f09f8101cc5880510106"
        "0d00a3d01fe1ba4a0b3d0000000049454e44ae426082"))

    def rec(source, i, **f):
        return {"id": f"{source}-{i}", "source": source, "kind": f.pop("kind", "record"), "ts": f.pop("ts", None), **f}

    sets = {
        "imessage": [
            rec("imessage", 1, kind="message", ts="2026-03-02T18:04:00Z", author="Grace Hopper", is_me=False, thread="c1",
                thread_name="Grace Hopper", text="Are we still on for dinner at Tasca on Friday?"),
            rec("imessage", 2, kind="message", ts="2026-03-02T18:06:00Z", author="me", is_me=True, thread="c1",
                thread_name="Grace Hopper", text="Yes! 7:30, I booked a table."),
            rec("imessage", 3, kind="message", ts="2026-03-09T09:00:00Z", author="Alan Turing", is_me=False, thread="c2",
                thread_name="Alan Turing", text="The wifi password is hunter2swordfish"),
        ],
        "documents": [rec("documents", 1, kind="document", ts="2026-02-20T12:00:00Z", title="trip-notes.txt",
                          text="Packing list for Lisbon", meta={"path": str(doc)})],
        "photos": [rec("photos", 1, kind="photo", ts="2026-03-07T20:15:00Z", title="IMG_0001.HEIC",
                       text="Place: Lisbon, Portugal\nScenes: dinner, table", meta={"files": [str(png)], "timezone": "Europe/Lisbon"})],
        "calendar": [
            rec("calendar", 1, kind="event", ts="2026-03-06T19:30:00Z", ts_end="2026-03-06T21:30:00Z", title="Dinner with Grace"),
            rec("calendar", 2, kind="event", ts="2026-04-10T16:00:00Z", ts_end="2026-04-10T17:00:00Z", title="Dentist"),
        ],
    }
    for source, rows in sets.items():
        with (norm / f"{source}.jsonl").open("w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
    env = {**os.environ, "CORPUS_DIR": str(corpus)}
    subprocess.run([sys.executable, str(REPO / "connectors" / "build_index.py")], check=True, env=env, capture_output=True)
    return str(corpus)


def cited_corpus(corpus):
    """A corpus for opening what an Ask answer cites. A conversation with Grace in Messages over four days: one
    message whose time was lost (read as 0, so 1970), a picture, a tapback, an edit with what it said before, a menu
    sent as a file. A book club on Instagram (a group, with reactions kept on its messages). Calendar events with a
    place, invitees and notes, and an all-day one. A note. Times are UTC; everyone in it is made up."""
    corpus = Path(corpus)
    norm = corpus / "normalized"
    norm.mkdir(parents=True, exist_ok=True)
    (corpus / "identity.json").write_text(json.dumps(ME))
    png = corpus / "files" / "IMG_0002.png"
    png.parent.mkdir(exist_ok=True)
    png.write_bytes(bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000008000000080802000000"
        "4b6d29dc0000001549444154789c63fccfc0f09f8101cc5880510106"
        "0d00a3d01fe1ba4a0b3d0000000049454e44ae426082"))
    grace = []

    def g(ts, text, me=False, **f):
        grace.append({"id": f"im-{len(grace)}", "source": "imessage", "kind": f.pop("kind", "message"), "ts": ts, "author": "me" if me else "Grace Hopper",
                      "is_me": me, "thread": "chat-grace", "thread_name": "Grace Hopper", "text": text,
                      "meta": {"service": "iMessage", "group": False, **f.pop("meta", {})}, **f})

    g("1970-01-01T00:00:00Z", "an old message whose time was lost")
    for i, t in enumerate(["Can you send me the slides?", "Sure, give me a minute", "Got them, thanks!", "Good luck tomorrow"]):
        g(f"2026-02-20T15:{10 + i:02d}:00Z", t, me=i % 2 == 1)
    g("2026-03-01T10:00:00Z", "Did you see the eclipse?")
    g("2026-03-01T10:01:00Z", "Not yet! send a picture", me=True)
    g("2026-03-01T10:02:00Z", "[attachment: IMG_0002.png (image/png)]", meta={"files": [str(png)]})
    g("2026-03-01T10:03:00Z", "wow")
    g("2026-03-02T18:04:00Z", "Are we still on for dinner at Tasca on Friday?")
    g("2026-03-02T18:06:00Z", "Yes! 7:30, I booked a table.", me=True,
      meta={"reply_text": "Are we still on for dinner at Tasca on Friday?", "reactions": [{"who": "Grace Hopper", "reaction": "‼️"}]})
    # a tapback the message shows (it's on a message here), and the one it replaced
    g("2026-03-02T18:06:30Z", "Liked “Yes! 7:30, I booked a table.”", kind="reaction",
      meta={"reaction": "liked", "on_message": True, "withdrawn": "2026-03-02T18:06:40Z"})
    g("2026-03-02T18:06:40Z", "Emphasized “Yes! 7:30, I booked a table.”", kind="reaction", meta={"reaction": "emphasized", "on_message": True})
    g("2026-03-02T18:07:00Z", "Loved “Yes! 7:30, I booked a table.”", kind="reaction", meta={"reaction": "loved"})
    g("2026-03-02T18:09:00Z", "Should I bring the wine?", me=True,
      meta={"edited": "2026-03-02T18:10:00Z", "edits": [{"at": "2026-03-02T18:09:00Z", "text": "Should I bring wine"}]})
    g("2026-03-02T18:11:00Z", "🍷🍷")
    g("2026-03-02T18:12:00Z", "[attachment: Tasca menu.pdf (application/pdf)]", me=True)
    g("2026-03-07T09:00:00Z", "That was so much fun")
    g("2026-03-07T09:05:00Z", "Same time next month?", me=True)
    club = []
    who = ["Katherine Johnson", "Dorothy Vaughan", "me"]
    for i in range(24):
        d = 10 + i // 8
        a = who[i % 3]
        club.append({"id": f"ig-{i}", "source": "instagram", "kind": "message", "ts": f"2026-03-{d:02d}T20:{i % 8 * 5:02d}:00Z",
                     "author": a, "is_me": a == "me", "thread": "ig-book-club", "thread_name": "Book club",
                     "participants": ["Katherine Johnson", "Dorothy Vaughan", "Ada Lovelace"],
                     "text": "Chapter 7 is the best one" if i == 9 else f"book club message {i}",
                     "meta": {"reactions": [{"who": "Dorothy Vaughan", "reaction": "❤"}, {"who": "Ada Lovelace", "reaction": "😂"}]} if i == 9 else {}})
    sets = {
        "imessage": grace,
        "instagram": club,
        "calendar": [
            {"id": "cal-1", "source": "calendar", "kind": "event", "ts": "2026-03-06T19:30:00Z", "ts_end": "2026-03-06T21:30:00Z",
             "title": "Dinner with Grace", "thread": "Personal", "thread_name": "iCloud / Personal", "participants": ["Grace Hopper", "Alan Turing"],
             "text": "Dinner with Grace\nLocation: Tasca, Lisbon\nOrganized by Grace Hopper\nAttendees: Grace Hopper, Alan Turing\nYou accepted\nBring the good wine.",
             "meta": {"location": "Tasca, Lisbon", "organizer": "Grace Hopper", "my_reply": "accepted"}},
            {"id": "cal-2", "source": "calendar", "kind": "event", "ts": "2026-03-22T00:00:00Z", "ts_end": "2026-03-23T00:00:00Z",
             "title": "Grace's birthday", "thread": "Birthdays", "thread_name": "Birthdays", "text": "Grace's birthday", "meta": {"all_day": True}},
        ],
        "apple_notes": [{"id": "note-1", "source": "apple_notes", "kind": "note", "ts": "2026-03-03T08:00:00Z", "is_me": True,
                         "title": "Dinner ideas", "text": "Dinner ideas\nTasca on Friday\nthe wine bar after"}],
    }
    for source, rows in sets.items():
        with (norm / f"{source}.jsonl").open("w") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    subprocess.run([sys.executable, str(REPO / "connectors" / "build_index.py")], check=True, env={**os.environ, "CORPUS_DIR": str(corpus)}, capture_output=True)
    return str(corpus)


def explore_corpus(corpus):
    """A corpus for the Explore page's tests: a close friend across two apps under two names, a Discord friend (whose
    side the export doesn't keep), group chats (one in an app nothing here knows), calls, photos at home in Princeton
    and on a three-day trip to Tokyo (flown both ways), Health days, commits, notes and searches over 2024-2026. Times
    are UTC; tests run with UMP_TZ=UTC. Everyone is made up."""
    corpus = Path(corpus)
    norm = corpus / "normalized"
    norm.mkdir(parents=True, exist_ok=True)
    (corpus / "identity.json").write_text(json.dumps({"names": ["Ada Lovelace"], "emails": ["ada@example.com"], "usernames": ["ada_l"], "phones": []}))
    png = corpus / "files" / "IMG_0001.png"
    png.parent.mkdir(exist_ok=True)
    png.write_bytes(bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000008000000080802000000"
        "4b6d29dc0000001549444154789c63fccfc0f09f8101cc5880510106"
        "0d00a3d01fe1ba4a0b3d0000000049454e44ae426082"))
    n = iter(range(1, 10 ** 6))
    sets = {k: [] for k in ("imessage", "instagram", "discord", "calls", "photos", "shared_photos", "health", "git_commits", "apple_notes",
                            "google_activity", "calendar", "signal", "phone_airbnb", "x")}

    def add(source, **f):
        sets[source].append({"id": f"{source}-{next(n)}", "source": source, "kind": f.pop("kind", "record"), **f})

    # Grace: "Grace H" in Messages (a few times a week since 2024), "Grace Hopper" on Instagram. She starts most
    # conversations; you start the rest.
    for i, day in enumerate(["2024-03-12", "2024-03-14", "2025-03-12", "2025-07-01", "2026-03-12", "2026-03-13"]):
        add("imessage", kind="message", ts=f"{day}T17:00:00Z", author="Grace H", is_me=False, thread="g1", thread_name="Grace H",
            text=f"hey! day {i}", meta={"group": False})
        add("imessage", kind="message", ts=f"{day}T17:05:00Z", author="me", is_me=True, thread="g1", thread_name="Grace H",
            text="hi Grace", meta={"group": False})
    add("instagram", kind="message", ts="2024-01-02T10:00:00Z", author="me", is_me=True, thread="ig1",
        thread_name="Grace Hopper", participants=["Ada Lovelace", "Grace Hopper"], text="saw your post!")
    add("instagram", kind="message", ts="2024-01-02T10:10:00Z", author="Grace Hopper", is_me=False, thread="ig1",
        thread_name="Grace Hopper", participants=["Ada Lovelace", "Grace Hopper"], text="thanks!")
    # A group chat: nobody's one-on-one. Its own word is "croissant"; the lines an app writes itself ("X sent an
    # attachment.") come from three of you and aren't anyone's words.
    add("imessage", kind="message", ts="2025-03-12T18:00:00Z", author="Alan Turing", is_me=False, thread="grp",
        thread_name="Dinner club", meta={"group": True}, text="who's in?")
    for i in range(8):
        day = f"2025-05-{i + 1:02d}"
        for who, me, hour in (("Alan Turing", False, 18), ("Grace H", False, 19), ("me", True, 17)):
            add("imessage", kind="message", ts=f"{day}T{hour}:00:00Z", author=who, is_me=me, thread="grp", thread_name="Dinner club",
                meta={"group": True}, text=f"{who.split()[0] if not me else 'You'} sent an attachment.")
        add("imessage", kind="message", ts=f"{day}T18:30:00Z", author="Alan Turing" if i % 2 else "Grace H", is_me=False, thread="grp",
            thread_name="Dinner club", meta={"group": True}, text="croissant time again 🥐")
    # A group in an app this code has never heard of, that nobody named: its name is its members'. Dorothy writes late.
    for i in range(16):
        add("signal", kind="message", ts=f"2025-06-{i + 1:02d}T02:00:00Z", author="Dorothy Vaughan", is_me=False, thread="sig1",
            thread_name="Katherine Johnson, Dorothy Vaughan", participants=["Ada Lovelace", "Katherine Johnson", "Dorothy Vaughan"],
            text="the orbit numbers check out")
        add("signal", kind="message", ts=f"2025-06-{i + 1:02d}T15:00:00Z", author="Katherine Johnson", is_me=False, thread="sig1",
            thread_name="Katherine Johnson, Dorothy Vaughan", participants=["Ada Lovelace", "Katherine Johnson", "Dorothy Vaughan"],
            text="run the orbit again")
    # Three lines whose writer the export left out: they count toward the chat, not as a person in it.
    for i in range(3):
        add("signal", kind="message", ts=f"2025-06-2{i}T15:00:00Z", is_me=False, thread="sig1",
            thread_name="Katherine Johnson, Dorothy Vaughan", participants=["Ada Lovelace", "Katherine Johnson", "Dorothy Vaughan"],
            text="(a message)")
    # A host, a co-host and you: a conversation with a business, not a group chat of yours.
    for i in range(20):
        add("phone_airbnb", kind="message", ts=f"2025-08-{i + 1:02d}T12:00:00Z", author=("Jay (Host)", "Jay (Co-Host)", "me")[i % 3],
            is_me=i % 3 == 2, thread="1894995745", thread_name="1894995745", text="check-in is at 3")
    # A server channel an export keeps only your side of: not a chat you can see the others in.
    for i in range(25):
        add("discord", kind="message", ts=f"2025-07-{i + 1:02d}T17:00:00Z", author="me", is_me=True, thread="chan1",
            thread_name="#general", participants=["lin", "pat", "sam"], text="anyone up for a game")
    # Discord keeps only your side.
    for d in ("2025-03-12", "2025-03-13"):
        add("discord", kind="message", ts=f"{d}T22:00:00Z", author="me", is_me=True, thread="dm1",
            thread_name="Direct Message with lin.", participants=["lin"], text="gg")
    add("calls", kind="call", ts="2025-03-12T19:00:00Z", author="Grace H", is_me=False, thread="Grace H", thread_name="Grace H",
        meta={"direction": "incoming", "type": "facetime audio", "seconds": 600})
    # Photos: home in Princeton on several days, then three days in Tokyo with Grace.
    home = [("2025-03-01", 1), ("2025-03-05", 2), ("2025-03-12", 3), ("2025-04-02", 1), ("2025-04-20", 2), ("2026-03-12", 1)]
    princeton = {"text": "Photo\nPlace: Princeton, New Jersey, United States\nPeople: Ada Lovelace",
                 "meta": {"lat": 40.35, "lon": -74.66, "files": [str(png)]}}
    for day, k in home:
        for j in range(k):
            add("photos", kind="photo", ts=f"{day}T15:0{j}:00Z", title="IMG.HEIC", is_me=True, **princeton)
    # Leaving and getting back: the flights to and from Tokyo are the hours between these and the Tokyo photos.
    for ts in ("2025-03-19T08:00:00Z", "2025-03-23T02:00:00Z", "2025-04-02T16:00:00Z"):
        add("photos", kind="photo", ts=ts, title="IMG.HEIC", is_me=True, **princeton)
    # Not where you were: a picture someone sent you, saved from Messages, and one with a location nothing could have
    # reached half an hour either side of being in Princeton.
    add("photos", kind="photo", ts="2025-04-20T16:00:00Z", title="IMG.HEIC", is_me=True, text="Photo\nPlace: Sydney, Australia",
        meta={"lat": -33.87, "lon": 151.21, "imported_by": "Messages", "files": [str(png)]})
    add("photos", kind="photo", ts="2025-04-02T15:30:00Z", title="IMG.HEIC", is_me=True, text="Photo\nPlace: Sydney, Australia",
        meta={"lat": -33.87, "lon": 151.21, "files": [str(png)]})
    for day in ("2025-03-20", "2025-03-21", "2025-03-22"):
        add("photos", kind="photo", ts=f"{day}T03:00:00Z", title="IMG.HEIC", is_me=True,
            text="Photo\nPlace: Shinjuku, Tokyo, Japan\nPeople: Grace", meta={"lat": 35.69, "lon": 139.70, "timezone": "Asia/Tokyo",
                                                                              "files": [str(png)]})
    # Not where you were either: a friend's photo in a shared album (photos.py's shared_photos), from Lisbon, with Grace.
    add("shared_photos", kind="photo", ts="2025-06-10T12:00:00Z", title="IMG.HEIC", author="someone else", is_me=False,
        text="Photo\nIn a shared album\nPlace: Lisbon, Portugal\nPeople: Grace",
        meta={"lat": 38.72, "lon": -9.14, "shared": "shared_album", "files": [str(png)]})
    for d, steps in (("2025-03-12", 9000), ("2025-03-13", 4000)):
        add("health", kind="health_day", ts=f"{d}T00:00:00", meta={"steps": steps})
    for i, d in enumerate(("2025-03-10", "2025-03-11", "2025-03-12")):
        add("git_commits", kind="commit", ts=f"{d}T20:00:00Z", author="Ada", is_me=True, thread="/code/engine",
            thread_name="engine", title=f"Commit {i}")
    add("git_commits", kind="commit", ts="2025-03-12T21:00:00Z", author="Someone", is_me=False, thread="/code/engine",
        thread_name="engine", title="Not mine")
    add("apple_notes", kind="note", ts="2025-03-12T08:00:00Z", is_me=True, title="Trip packing list", text="passport")
    add("google_activity", kind="search", ts="2025-03-12T12:00:00Z", is_me=True, title="Searched for tokyo ramen")
    # Enough of 2024 for it to be a year of its own in Your Year.
    for i in range(20):
        add("google_activity", kind="search", ts=f"2024-06-{i + 1:02d}T12:00:00Z", is_me=True, title=f"Searched for recipe {i}")
    add("google_activity", kind="media", ts="2025-03-12T23:00:00Z", is_me=True, title="How engines work",
        text="https://www.youtube.com/watch?v=abc")
    add("calendar", kind="event", ts="2025-03-12T19:30:00Z", title="Dinner with Grace")
    # A post of yours on X, and a retweet: someone else's post, not something you made.
    add("x", kind="post", ts="2025-05-01T09:00:00Z", author="me", is_me=True, text="Shipped the engine")
    add("x", kind="post", ts="2025-05-01T10:00:00Z", author="me", is_me=True, text="RT @grace_h: Compilers are fun",
        meta={"retweet_of": "grace_h"})
    for source, rows in sets.items():
        with (norm / f"{source}.jsonl").open("w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
    env = {**os.environ, "CORPUS_DIR": str(corpus)}
    subprocess.run([sys.executable, str(REPO / "connectors" / "build_index.py")], check=True, env=env, capture_output=True)
    return str(corpus)


def inserts_corpus(corpus):
    """A corpus for what an Ask answer shows (explore.py embed): Explore's (explore_corpus: Grace in two apps, home in
    Princeton and three days in Tokyo, a day in March 2025 with a bit of everything), and with it an email thread with
    a reply it quotes, songs and a podcast, nights of sleep, calendar events (an all-day one across the trip, one still
    to come) and what Facebook and Instagram decided about you. Times UTC; tests run with UMP_TZ=UTC. Everyone is
    made up."""
    corpus = Path(explore_corpus(corpus))
    norm = corpus / "normalized"
    n = iter(range(1, 10 ** 6))
    sets = collections.defaultdict(list)

    def add(source, **f):
        sets[source].append({"id": f"{source}-x{next(n)}", "source": source, "kind": f.pop("kind", "record"), **f})

    add("gmail", kind="email", ts="2025-03-11T15:00:00Z", author="Katherine Johnson", is_me=False, participants=["Ada Lovelace"],
        title="Orbit numbers for Friday", thread="t-orbit", thread_name="Orbit numbers for Friday",
        text="Orbit numbers for Friday\nHi Ada,\n\nThe numbers check out: launch at 9:40.\nThe sheet is attached.\n\nKatherine\n\n"
             "On Mon, Mar 10, 2025 at 9:00 AM Ada Lovelace <ada@example.com> wrote:\n> Can you check the orbit before Friday?",
        meta={"from": "katherine@example.com", "to": ["ada@example.com"], "attachments": ["orbit.xlsx"], "labels": "Inbox"})
    add("gmail", kind="email", ts="2025-03-11T16:00:00Z", author="me", is_me=True, participants=["Katherine Johnson"],
        title="Re: Orbit numbers for Friday", thread="t-orbit", thread_name="Re: Orbit numbers for Friday",
        text="Re: Orbit numbers for Friday\nThank you!", meta={"from": "ada@example.com", "to": ["katherine@example.com"], "labels": "Sent"})
    for i in range(5):
        add("spotify", kind="media", ts=f"2025-03-12T0{i}:10:00Z", author="me", is_me=True, title="Warp", text="Warp — The Weavers (Spotify)",
            meta={"artist": "The Weavers", "album": "Loom", "seconds": 200})
    add("spotify", kind="media", ts="2025-03-12T07:00:00Z", author="me", is_me=True, title="Spindle", text="Spindle — The Looms (Spotify)",
        meta={"artist": "The Looms", "seconds": 180})
    add("podcasts", kind="listen", ts="2025-03-12T08:30:00Z", author="me", is_me=True, title="Episode 12: Gears", thread="show-1",
        thread_name="Engine Hour", text="Listened to Episode 12: Gears (Engine Hour)", meta={"show": "Engine Hour", "duration": 2400})
    for d in (10, 11, 12):
        add("health", kind="sleep", ts=f"2025-03-{d:02d}T23:00:00Z", ts_end=f"2025-03-{d + 1:02d}T06:00:00Z", title="Sleep", text="Slept",
            meta={"asleep_min": 420, "tz": "UTC"})
    add("calendar", kind="event", ts="2025-03-12T15:00:00Z", ts_end="2025-03-12T15:15:00Z", title="Orbit review", thread="Work",
        thread_name="iCloud / Work", meta={"location": "Room 4"})
    add("calendar", kind="event", ts="2025-03-19T00:00:00Z", ts_end="2025-03-23T00:00:00Z", title="Tokyo trip", thread="Home",
        thread_name="iCloud / Home", meta={"all_day": True})
    later = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=30)).strftime("%Y-%m-%dT16:00:00Z")
    add("calendar", kind="event", ts=later, ts_end=later.replace("T16", "T17"), title="Dentist", thread="Home", thread_name="iCloud / Home")
    for site in ("facebook", "instagram"):
        add(f"{site}_activity", kind="inference", author="x", is_me=False, title="Frequent travelers", text="",
            meta={"what": "category", "service": site.title()})
        add(f"{site}_activity", kind="advertiser", author="x", is_me=False, title="Acme Outdoor", text="", meta={"how": "list", "service": site.title()})
    add("facebook_activity", kind="inference", author="x", is_me=False, title="Rock climbing", text="", meta={"what": "interest", "service": "Facebook"})
    for source, rows in sets.items():
        with (norm / f"{source}.jsonl").open("a") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
    env = {**os.environ, "CORPUS_DIR": str(corpus)}
    subprocess.run([sys.executable, str(REPO / "connectors" / "build_index.py")], check=True, env=env, capture_output=True)
    return str(corpus)


def media_corpus(corpus):
    """A corpus for Explore's Listening, Moving and Sleep, Curiosity and Watching (times UTC; tests run with
    UMP_TZ=UTC): songs from Spotify (one skipped), the Mac's Now Playing (Spotify, and Netflix, which is watching) and
    YouTube's artist channels; videos from YouTube, Netflix on the iPhone; searches from Google and Safari (one in both
    a minute apart, one inside Gmail) about sourdough in 2024 and Tokyo in 2025, before a trip there; Health's days
    and nights. Everyone is made up."""
    corpus = Path(corpus)
    norm = corpus / "normalized"
    norm.mkdir(parents=True, exist_ok=True)
    (corpus / "identity.json").write_text(json.dumps({"names": ["Ada Lovelace"], "emails": ["ada@example.com"], "usernames": [], "phones": []}))
    n = iter(range(1, 10 ** 6))
    sets = collections.defaultdict(list)

    def add(source, **f):
        sets[source].append({"id": f"{source}-{next(n)}", "source": source, "kind": f.pop("kind", "record"), "author": "me", "is_me": True, **f})

    def song(ts, track, artist, seconds=200):
        add("spotify", kind="media", ts=ts, title=track, text=f"{track} — {artist} (Spotify)", meta={"artist": artist, "seconds": seconds})

    # The Weavers all spring 2025, then the Looms all summer: two eras. A song on repeat one day; a skip that isn't a play.
    for i in range(30):
        song(f"2025-02-{i % 27 + 1:02d}T08:{i % 60:02d}:00Z", ["Warp", "Weft", "Shuttle"][i % 3], "The Weavers")
    for i in range(40):
        song(f"2025-07-{i % 30 + 1:02d}T21:{i % 60:02d}:00Z", ["Bobbin", "Spindle"][i % 2], "The Looms")
    for i in range(5):
        song(f"2025-07-04T1{i}:00:00Z", "Spindle", "The Looms")
    song("2025-07-05T10:00:00Z", "Warp", "The Weavers", seconds=12)
    for i in range(3):
        add("app_usage", kind="media", ts=f"2025-08-0{i + 1}T09:00:00Z", title="Loom Song", meta={"app": "Spotify", "artist": "Ada's Band", "duration": 180})
    add("app_usage", kind="media", ts="2025-08-04T22:00:00Z", title="Our Planet", meta={"app": "Netflix", "artist": None, "duration": 3000})
    for i in range(2):
        add("google_activity", kind="media", ts=f"2025-09-0{i + 1}T20:00:00Z", title="Warp (Official Audio)", text="Warp (Official Audio)\nThe Weavers - Topic",
            url="https://www.youtube.com/watch?v=w1", meta={"product": "YouTube"})
    # Videos: a channel watched night after night, one of them twice; a long night of it.
    for i in range(6):
        add("google_activity", kind="media", ts=f"2025-10-0{i + 1}T23:00:00Z", title=f"How engines work {i % 5}",
            text=f"How engines work {i % 5}\nEngine Lab", url="https://www.youtube.com/watch?v=e{i}", meta={"product": "YouTube"})
    for i, ts in enumerate(["2025-10-10T20:30:00Z", "2025-10-10T21:30:00Z", "2025-10-10T22:30:00Z", "2025-10-10T23:30:00Z", "2025-10-11T00:30:00Z"]):
        add("google_activity", kind="media", ts=ts, title=f"Gears, part {i}", text=f"Gears, part {i}\nEngine Lab",
            url=f"https://www.youtube.com/watch?v=g{i}", meta={"product": "YouTube"})
    for ep in (1, 2):
        add("phone_netflix", kind="media", ts=f"2025-11-0{ep}T21:00:00Z", title=f"Our Planet: Season 1: Episode {ep}",
            meta={"artifact": "netflix", "fields": {"Displayed Title": f"Our Planet: Season 1: Episode {ep}"}})
    # Searches: sourdough in 2024, Tokyo in 2025 (in the weeks before the trip), some every year.
    for i, q in enumerate(["sourdough starter", "sourdough starter feeding", "how to make sourdough starter", "sourdough starter smells",
                           "sourdough starter jar", "why is my sourdough starter flat"]):
        add("google_activity", kind="search", ts=f"2024-05-{i + 1:02d}T12:00:00Z", title=q, text=q, meta={"product": "Search"})
    for i, q in enumerate(["tokyo ramen", "tokyo hotels", "tokyo subway map", "is the tokyo jr pass worth it", "tokyo cherry blossoms", "tokyo in march"]):
        add("google_activity", kind="search", ts=f"2025-03-0{i + 1}T12:00:00Z", title=q, text=q, meta={"product": "Search"})
    add("browser_history", kind="search", ts="2025-03-01T12:00:30Z", title="tokyo ramen", text="tokyo ramen", url="https://www.google.com/search?q=tokyo+ramen")
    add("google_activity", kind="search", ts="2025-03-02T13:00:00Z", title="invoice from tokyo hotel", text="invoice from tokyo hotel", meta={"product": "Gmail"})
    for y in (2024, 2025):
        for i in range(4):
            add("google_activity", kind="search", ts=f"{y}-0{i + 6}-01T09:00:00Z", title="weather", text="weather", meta={"product": "Search"})
    # Home in Princeton, then Tokyo for three days: a trip.
    for d in ("2025-01-05", "2025-01-20", "2025-02-11", "2025-03-01", "2025-04-02", "2025-04-20"):
        add("photos", kind="photo", ts=f"{d}T15:00:00Z", title="Princeton", text="Photo\nPlace: Princeton, New Jersey, United States", meta={"lat": 40.35, "lon": -74.66})
    for d in ("2025-03-20", "2025-03-21", "2025-03-22"):
        add("photos", kind="photo", ts=f"{d}T03:00:00Z", title="Shinjuku", text="Photo\nPlace: Shinjuku, Tokyo, Japan", meta={"lat": 35.69, "lon": 139.70, "timezone": "Asia/Tokyo"})
    # Health: 20 days, the three in Tokyo over 10,000 steps (a streak), and 15 nights, bedtime past midnight on weekends.
    for i in range(20):
        d = f"2025-03-{i + 3:02d}"
        steps = 15000 + i if d in ("2025-03-20", "2025-03-21", "2025-03-22") else 6000 + i * 10
        add("health", kind="health_day", ts=f"{d}T00:00:00", title=f"Health {d}", text=f"Health {d}", meta={"steps": steps, "distance_km": steps * 0.0007, "flights": 3})
    for i in range(15):
        day = 3 + i
        late = i % 7 in (4, 5)
        start = f"2025-03-{day:02d}T23:30:00Z" if not late else f"2025-03-{day + 1:02d}T01:00:00Z"
        end = f"2025-03-{day + 1:02d}T07:00:00Z" if not late else f"2025-03-{day + 1:02d}T09:00:00Z"
        add("health", kind="sleep", ts=start, ts_end=end, title="Sleep", text="Slept", meta={"asleep_min": 420 if not late else 470, "tz": "UTC"})
    add("health", kind="sleep", ts="2025-03-10T14:00:00Z", ts_end="2025-03-10T14:40:00Z", title="Nap", text="Slept", meta={"asleep_min": 40, "tz": "UTC"})
    for source, rows in sets.items():
        with (norm / f"{source}.jsonl").open("w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
    env = {**os.environ, "CORPUS_DIR": str(corpus)}
    subprocess.run([sys.executable, str(REPO / "connectors" / "build_index.py")], check=True, env=env, capture_output=True)
    return str(corpus)


def ads_corpus(corpus):
    """A corpus for Explore's What They Know, written the way connectors/imports.py writes the exports' ads files:
    advertisers on Facebook and Instagram (one on both, one by two routes) and X, what each service decided (an X
    interest turned off, LinkedIn targeting), a company that told Facebook what you did (and an older import's record
    of another, kept under its file), ads on Instagram and X, Google ad activity, and email from one advertiser."""
    corpus = Path(corpus)
    norm = corpus / "normalized"
    norm.mkdir(parents=True, exist_ok=True)
    (corpus / "identity.json").write_text(json.dumps({"names": ["Ada Lovelace"], "emails": ["ada@example.com"], "usernames": [], "phones": []}))
    n = iter(range(1, 10 ** 6))
    sets = collections.defaultdict(list)

    def add(source, kind, **f):
        sets[source].append({"id": f"{source}-{next(n)}", "source": source, "kind": kind, "author": f.pop("author", "x"), "is_me": False, **f})

    for site in ("facebook", "instagram"):
        svc = site.title()
        add(f"{site}_activity", "advertiser", title="Acme Outdoor", text="", meta={"how": "list", "service": svc})
        add(f"{site}_activity", "advertiser", title="Acme Outdoor", text="", meta={"how": "activity", "service": svc})
    add("facebook_activity", "advertiser", title="Night Owl Games", text="", meta={"how": "activity", "service": "Facebook"})
    add("x", "advertiser", title="@acmeoutdoor", text="", meta={"how": "lookalike", "service": "X"})
    add("facebook_activity", "inference", title="Frequent travelers", text="", meta={"what": "category", "service": "Facebook"})
    add("instagram_activity", "inference", title="Frequent travelers", text="", meta={"what": "category", "service": "Instagram"})  # Meta's one profile
    add("instagram_activity", "inference", title="Rock climbing", text="", meta={"file": "interest_categories"})  # an older import: no what
    add("x", "inference", title="female", text="", meta={"what": "gender", "service": "X"})
    add("x", "inference", title="Golf", text="", meta={"what": "interest", "service": "X", "turned_off": True})
    add("linkedin", "inference", title="Python", text="", meta={"what": "Member Skills", "service": "LinkedIn"})
    add("linkedin", "inference", title="ad targeting", text="LinkedIn ad targeting\nMember Age: 25 to 34", meta={"file": "ad_targeting.csv"})  # an older import's whole file
    add("facebook_activity", "off_platform", title="Night Owl Games", ts="2026-01-03T00:00:00Z", text="",
        meta={"service": "Facebook", "events": [{"type": "PURCHASE", "ts": "2026-01-01T00:00:00Z"}, {"type": "PAGE_VIEW", "ts": "2026-01-03T00:00:00Z"}]})
    add("facebook_activity", "record", title="Corner Bakery", text="Facebook your activity off meta technologies\nTitle: Corner Bakery\nEvent: PAGE_VIEW\nEvent: PURCHASE",
        meta={"file": "your_activity_off_meta_technologies"})
    add("instagram_activity", "ad", title="Acme Outdoor", ts="2026-01-02T10:00:00Z", text="", meta={"service": "Instagram"})
    add("instagram_activity", "ad", title="Acme Outdoor", ts="2026-02-02T10:00:00Z", text="", meta={"service": "Instagram"})
    add("x", "ad", title="Corner Bakery", ts="2026-02-03T10:00:00Z", text="", meta={"service": "X", "why": ["Locations: Chicago"]})
    add("google_activity", "activity", title="Viewed an ad", ts="2026-02-04T10:00:00Z", text="", meta={"product": "Ads"})
    add("gmail", "email", title="Your order", ts="2026-01-05T10:00:00Z", text="", meta={"from": "Acme Outdoor <orders@acme-outdoor.example>"})
    for source, rows in sets.items():
        with (norm / f"{source}.jsonl").open("w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
    subprocess.run([sys.executable, str(REPO / "connectors" / "build_index.py")], check=True, env={**os.environ, "CORPUS_DIR": str(corpus)}, capture_output=True)
    return str(corpus)


def edge_corpus(corpus, case):
    """Libraries at the edges, for Explore and Ask. "empty": an index with nothing in it. "one-day": everything on
    one day. "messy": 1990 to 2026, with what goes wrong in real libraries: records with no time, times a clock or a
    conversion got wrong (1970, Apple's first second, a spreadsheet's 1900, Windows' 1601, 2099, 9999, not a date), times with offsets instead of Z
    and across a clock change; text that's empty, a megabyte long, right to left, emoji, NUL, HTML and SQL; two
    people with one name, one of them "me", and you in your own chats; meta that isn't an object; numbers that
    aren't. Times are UTC; tests run with UMP_TZ set. Everyone is made up."""
    corpus = Path(corpus)
    norm = corpus / "normalized"
    norm.mkdir(parents=True, exist_ok=True)
    (corpus / "identity.json").write_text(json.dumps(ME))
    n = iter(range(1, 10 ** 7))
    sets = collections.defaultdict(list)

    def add(source, **f):
        sets[source].append({"id": f"{source}-{next(n)}", "source": source, "kind": f.pop("kind", "record"), **f})

    def msg(ts, who, me, thread, name=None, text="hi", source="imessage", group=False, **f):
        add(source, kind="message", ts=ts, author="me" if me else who, is_me=me, thread=thread, thread_name=name if name is not None else who,
            text=text, meta={"group": group}, **f)

    def photo(ts, lat, lon, place, **meta):
        add("photos", kind="photo", ts=ts, title="IMG.HEIC", is_me=True, text=f"Photo\nPlace: {place}", meta={"lat": lat, "lon": lon, **meta})

    home, tokyo = (40.35, -74.66, "Princeton, New Jersey, United States"), (35.69, 139.70, "Shinjuku, Tokyo, Japan")
    if case not in ("empty", "one-day", "messy"):
        raise SystemExit(f"no edge library {case!r}")
    if case == "empty":
        (norm / "imessage.jsonl").write_text("")
    elif case == "one-day":
        for h in range(24):
            for m in range(0, 60, 10):
                ts = f"2025-06-01T{h:02d}:{m:02d}:00Z"
                msg(ts, "Grace Hopper", m % 20 == 0, "g1")
                msg(ts, ("Alan Turing", "Katherine Johnson")[m % 20 == 0], False, "club", name="Club", group=True, text="see you there 🥐")
                add("google_activity", kind="search", ts=ts, title=f"Searched for how to fold {m} paper cranes", is_me=True)
                add("spotify", kind="media", ts=ts, title=f"Song {m}", meta={"artist": "The Looms", "seconds": 200})
                add("google_activity", kind="media", ts=ts, title=f"Video {m}", text=f"Video {m}\nEngine Lab", url="https://www.youtube.com/watch?v=x",
                    meta={"product": "YouTube"})
                add("git_commits", kind="commit", ts=ts, author="Ada", is_me=True, thread="/code/engine", thread_name="engine", title=f"Commit {m}")
                photo(ts, *home)
        add("health", kind="health_day", ts="2025-06-01T00:00:00", meta={"steps": 12000})
    elif case == "messy":
        big = ("lorem ipsum dolor " * 60000)[:1_000_000]
        odd = ["", big, "مرحبا كيف حالك؟", "שלום מה שלומך", "🥐🥐 👩‍👩‍👧‍👦 🏳️‍🌈", "nul\x00byte", "<script>alert(1)</script><b>bold</b>",
               "' or 1=1; drop table records; --", "\"quoted\" NEAR(a b) title:x *", "tab\there\nnew line"]
        names = ["مريم", "😀 Smiley", "<b>Bob</b>", "a" * 200, "'; drop table records; --"]
        for y in range(1990, 2027):
            for mo in range(1, 13, 2):
                day = f"{y}-{mo:02d}-15"
                msg(f"{day}T17:00:00Z", "Grace Hopper", False, "g1", text=f"hey {y}")
                msg(f"{day}T17:05:00Z", "Grace Hopper", True, "g1", text="hi Grace")
                # Another Grace Hopper, in another app: one name, one person.
                msg(f"{day}T18:00:00Z", "Grace Hopper", mo % 4 == 1, "ig1", source="instagram", participants=["Ada Lovelace", "Grace Hopper"])
                # A conversation with yourself, and with someone called "me".
                msg(f"{day}T19:00:00Z", "Ada Lovelace", True, "self", name="Ada Lovelace")
                msg(f"{day}T19:30:00Z", "me", False, "m1", name="me")
                for i, who in enumerate(("Alan Turing", "Katherine Johnson", "Ada Lovelace")):
                    msg(f"{day}T2{i}:00:00Z", who, False, "club", name="Dinner club", group=True, text=f"croissant time {y} 🥐")
                photo(f"{day}T15:00:00Z", *home)
                add("google_activity", kind="search", ts=f"{day}T09:00:00Z", title=f"Searched for sourdough starter {y}", is_me=True)
                add("spotify", kind="media", ts=f"{day}T08:00:00Z", title=f"Song {y % 5}", meta={"artist": f"Artist {y % 3}", "seconds": 200})
                add("google_activity", kind="media", ts=f"{day}T22:00:00Z", title=f"How engines work {y}", text=f"How engines work {y}\nEngine Lab",
                    url="https://www.youtube.com/watch?v=x", meta={"product": "YouTube"})
                add("git_commits", kind="commit", ts=f"{day}T20:00:00Z", author="Ada", is_me=True, thread=f"/code/p{y}", thread_name=f"project {y}", title="Commit")
                add("health", kind="health_day", ts=f"{day}T00:00:00", meta={"steps": 9000 + mo * 100, "distance_km": 6})
                add("health", kind="sleep", ts=f"{day}T06:00:00Z", ts_end=f"{day}T13:30:00Z", meta={"asleep_min": 450, "tz": "UTC"})
            for d in ("06-20", "06-21", "06-22"):
                photo(f"{y}-{d}T03:00:00Z", *tokyo, timezone="Asia/Tokyo")
        # Times that can't be right, and none at all: none of them a day, a year, a first or a trip.
        for ts in (None, "1970-01-01T00:00:00Z", "2001-01-01T00:00:00Z", "1900-01-01T00:00:00Z", "1601-01-01T00:00:00Z", "2099-12-31T23:59:59Z", "9999-12-31T23:59:59Z",
                   "not a time", "2024-13-45T99:99:99Z"):
            for i in range(25):
                msg(ts, "Grace Hopper", i % 2 == 0, "g1", text="sent at a bad time")
                msg(ts, "Alan Turing", False, "club", name="Dinner club", group=True, text="at a bad time")
                photo(ts, 51.5, -0.12, "London, England, United Kingdom")
                add("google_activity", kind="search", ts=ts, title="Searched for a bad time", is_me=True)
                add("spotify", kind="media", ts=ts, title="Bad Time", meta={"artist": "Nobody", "seconds": 200})
                add("health", kind="health_day", ts=ts, meta={"steps": 99999})
                add("git_commits", kind="commit", ts=ts, author="Ada", is_me=True, thread="/code/never", thread_name="never", title="Commit")
        # Offsets instead of Z, and a clock change (America/Los_Angeles: 9 March and 2 November 2025).
        for ts in ("2025-03-09T09:59:00Z", "2025-03-09T10:30:00Z", "2025-11-02T08:30:00Z", "2025-11-03T07:30:00Z",
                   "2025-06-01T23:30:00-07:00", "2025-06-02T00:30:00+09:00"):
            msg(ts, "Grace Hopper", False, "g1", text=f"at {ts}")
        # Odd text and names, everywhere text shows.
        for i, t in enumerate(odd * 3):
            ts = f"2024-0{i % 9 + 1}-1{i % 9}T1{i % 10}:00:00Z"
            who = names[i % len(names)]
            msg(ts, who, i % 2 == 0, f"odd{i % len(names)}", text=t)
            msg(ts, who, False, "oddgrp", name=t[:100], group=True, text=t)
            msg(ts, names[(i + 1) % len(names)], False, "oddgrp", name=t[:100], group=True, text=t)
            add("google_activity", kind="search", ts=ts, title=t[:150] or None, text=t, is_me=True)
            add("spotify", kind="media", ts=ts, title=t[:150] or "Untitled", meta={"artist": who, "seconds": 200})
            add("apple_notes", kind="note", ts=ts, is_me=True, title=t[:100] or None, text=t)
            add("calls", kind="call", ts=ts, thread_name=who, meta={"seconds": "not a number" if i % 3 == 0 else 60})
            add("facebook_activity", kind="advertiser", title=t[:100] or None, meta={"how": "list", "service": "Facebook"})
            add("x", kind="inference", title=t[:100] or None, meta={"what": "interest", "service": "X"})
            photo(ts, 35.0 + i * 0.001, 139.0, f"{t[:60]}, {who}, Japan")
        add("photos", kind="photo", ts="2025-03-03T03:00:00Z", text="Photo", meta=[1, 2, 3])
        add("photos", kind="photo", ts="2025-03-03T04:00:00Z", text="Photo", meta={"lat": 95, "lon": 400})
        add("health", kind="health_day", ts="2025-03-04T00:00:00", meta={"steps": "lots"})
        add("health", kind="sleep", ts="2025-03-04T23:00:00Z", ts_end="not a time", meta={"asleep_min": "x"})
    for source, rows in sets.items():
        with (norm / f"{source}.jsonl").open("w") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    subprocess.run([sys.executable, str(REPO / "connectors" / "build_index.py")], check=True, env={**os.environ, "CORPUS_DIR": str(corpus)}, capture_output=True)
    return str(corpus)


if __name__ == "__main__":
    cmd, target = sys.argv[1], sys.argv[2]
    if cmd == "exports":
        print(json.dumps(exports(target)))
    elif cmd == "home":
        print(json.dumps({"home": home(target)}))
    elif cmd == "backup":
        print(json.dumps({"backup": backup(target)}))
    elif cmd == "ask-corpus":
        print(json.dumps({"corpus": ask_corpus(target)}))
    elif cmd == "cited-corpus":
        print(json.dumps({"corpus": cited_corpus(target)}))
    elif cmd == "media-corpus":
        print(media_corpus(target))
    elif cmd == "explore-corpus":
        print(json.dumps({"corpus": explore_corpus(target)}))
    elif cmd == "inserts-corpus":
        print(json.dumps({"corpus": inserts_corpus(target)}))
    elif cmd == "edge-corpus":  # edge-corpus DIR CASE
        print(json.dumps({"corpus": edge_corpus(target, sys.argv[3])}))
