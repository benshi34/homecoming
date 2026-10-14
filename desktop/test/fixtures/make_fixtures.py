#!/usr/bin/env python3
"""Synthetic exports and a fake home folder for the tests. Shapes follow what connectors/imports.py and
the Mac connectors read, so the real parsers run on them.

    make_fixtures.py exports <dir>    one file per export kind (plus broken and unknown ones)
    make_fixtures.py home <dir>       a fake $HOME: Claude Code sessions, a git repo, Mail, Messages, settings
    make_fixtures.py backup <home>    a fake encrypted Finder backup under <home>/Library/.../MobileSync/Backup
    make_fixtures.py ask-corpus <dir> a small indexed corpus (corpus.db) for the Ask assistant
"""

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
    sets = {k: [] for k in ("imessage", "instagram", "discord", "calls", "photos", "health", "git_commits", "apple_notes",
                            "google_activity", "calendar", "signal", "phone_airbnb")}

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
    for source, rows in sets.items():
        with (norm / f"{source}.jsonl").open("w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
    env = {**os.environ, "CORPUS_DIR": str(corpus)}
    subprocess.run([sys.executable, str(REPO / "connectors" / "build_index.py")], check=True, env=env, capture_output=True)
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
    elif cmd == "explore-corpus":
        print(json.dumps({"corpus": explore_corpus(target)}))
