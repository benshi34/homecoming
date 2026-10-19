"""Tests for desktop/py/bridge.py. Each test runs the bridge as the app does (a subprocess with HOME and
CORPUS_DIR pointed at a sandbox), so nothing touches the real Library or corpus. The real-export tests only
read files."""

import datetime as dt
import json
import os
import plistlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

DESKTOP = Path(__file__).resolve().parents[2]
REPO = DESKTOP.parent
BRIDGE = DESKTOP / "py" / "bridge.py"
sys.path.insert(0, str(DESKTOP / "test" / "fixtures"))
import make_fixtures  # noqa: E402

REAL_IMPORTS = REPO / "corpus" / "imports"


def bridge(args, home, corpus, stdin=None, extra_env=None):
    env = {k: v for k, v in os.environ.items() if k not in ("CORPUS_DIR", "UMP_EXTRA_PYPATH", "UMP_IPHONE_MODULE", "IPHONE_BACKUP_PASSWORD")}
    env.update(HOME=str(home), CORPUS_DIR=str(corpus), UMP_REPO=str(REPO), PYTHONDONTWRITEBYTECODE="1", **(extra_env or {}))
    return subprocess.run([sys.executable, str(BRIDGE), *args], input=stdin, capture_output=True, text=True, env=env, timeout=300)


def jsonout(r):
    if r.returncode != 0:
        raise AssertionError(f"exit {r.returncode}: {r.stderr[-2000:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def events(r):
    out = []
    for line in r.stdout.splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            out.append({"type": "raw", "line": line})
    return out


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ump-py-"))
        self.home = self.tmp / "home"
        self.corpus = self.tmp / "corpus"
        self.home.mkdir()
        self.corpus.mkdir()

    def tearDown(self):
        for root, dirs, _ in os.walk(self.tmp):
            for d in dirs:
                try:
                    os.chmod(os.path.join(root, d), 0o755)
                except OSError:
                    pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def probe(self):
        return jsonout(bridge(["probe"], self.home, self.corpus))


class ProbeTests(Sandbox):
    def test_empty_home(self):
        p = self.probe()
        self.assertIsNone(p["fda"])
        self.assertEqual(set(p["sources"].values()), {"absent"})
        self.assertEqual(p["backups"], [])
        self.assertIsNone(p["identity"])
        self.assertFalse(p["corpus"]["in_icloud"])
        self.assertGreater(p["corpus"]["free_bytes"], 0)
        self.assertEqual(p["retention"]["claude"], {"present": False})
        self.assertEqual(p["retention"]["messages"], {"readable": False, "value": None})

    def test_protected_folders_wait_until_asked(self):
        """Before the Setup Assistant is past Full Disk Access (UMP_DEFER_FOLDERS=1), Documents, Desktop and Downloads
        aren't looked in, so macOS asks nothing yet; with Full Disk Access they are, as they are without the flag."""
        (self.home / "Documents").mkdir()
        (self.home / "Documents" / "notes.txt").write_text("x")
        (self.home / "Downloads").mkdir()
        early = jsonout(bridge(["probe"], self.home, self.corpus, extra_env={"UMP_DEFER_FOLDERS": "1"}))
        self.assertEqual((early["sources"]["documents"], early["downloads"]), ("absent", "later"))
        now = self.probe()
        self.assertEqual((now["sources"]["documents"], now["downloads"]), ("ok", "ok"))
        (self.home / "Library/Messages").mkdir(parents=True)
        (self.home / "Library/Messages/chat.db").write_bytes(b"x")  # Full Disk Access: nothing to ask
        fda = jsonout(bridge(["probe"], self.home, self.corpus, extra_env={"UMP_DEFER_FOLDERS": "1"}))
        self.assertEqual((fda["fda"], fda["sources"]["documents"], fda["downloads"]), (True, "ok", "ok"))

    def test_cloud_drives_and_other_apps_data_wait_too(self):
        """A cloud drive's folder alone makes Documents there, and WhatsApp's, Maps' and Books' own folders are other
        apps' data: none is looked in before the Setup Assistant is past Full Disk Access."""
        (self.home / "Library/CloudStorage/OneDrive-Personal").mkdir(parents=True)
        maps = self.home / "Library/Containers/com.apple.Maps/Data/Maps"
        maps.mkdir(parents=True)
        (maps / "MapsSync_0.0.1").write_bytes(b"x")
        chats = self.home / "Library/Group Containers/group.net.whatsapp.WhatsApp.shared"
        chats.mkdir(parents=True)
        (chats / "ChatStorage.sqlite").write_bytes(b"x")
        (self.home / "Library/Containers/com.apple.iBooksX/Data/Documents/BKLibrary").mkdir(parents=True)
        ids = ("documents", "apple_maps", "whatsapp", "books")
        early = jsonout(bridge(["probe"], self.home, self.corpus, extra_env={"UMP_DEFER_FOLDERS": "1"}))
        self.assertEqual([early["sources"][k] for k in ids], ["absent"] * 4)
        self.assertEqual([self.probe()["sources"][k] for k in ids], ["ok"] * 4)

    def test_terminal_history_settings_and_fix(self):
        env = {"SHELL": "/bin/zsh"}
        rc = self.home / ".zshrc"
        rc.write_text("# mine\nexport SAVEHIST=5000  # more\nalias ll='ls -l'")
        p = jsonout(bridge(["probe"], self.home, self.corpus, extra_env=env))["retention"]["shell"]
        self.assertEqual((p["shell"], p["savehist"], p["extended"], p["ours"]), ("zsh", 5000, False, False))
        fixed = jsonout(bridge(["fix-shell-retention"], self.home, self.corpus, extra_env=env))
        self.assertEqual((fixed["savehist"], fixed["extended"], fixed["ours"]), (1000000, True, True))
        jsonout(bridge(["fix-shell-retention"], self.home, self.corpus, extra_env=env))
        text = rc.read_text()
        self.assertTrue(text.startswith("# mine\nexport SAVEHIST=5000  # more\nalias ll='ls -l'\n\n"), "what was there stays")
        self.assertEqual(text.count("SAVEHIST=1000000"), 1, "fixing twice adds it once")
        # A block added under the app's earlier name (User Model) still counts as ours, and isn't added again.
        rc.write_text(text.replace("Added by Homecoming", "Added by User Model"))
        self.assertTrue(jsonout(bridge(["probe"], self.home, self.corpus, extra_env=env))["retention"]["shell"]["ours"])
        jsonout(bridge(["fix-shell-retention"], self.home, self.corpus, extra_env=env))
        self.assertEqual(rc.read_text().count("SAVEHIST=1000000"), 1)
        (self.home / ".zshrc").write_text("source $ZSH/oh-my-zsh.sh\n")
        p = jsonout(bridge(["probe"], self.home, self.corpus, extra_env=env))["retention"]["shell"]
        self.assertEqual((p["savehist"], p["extended"]), (10000, True))
        self.assertEqual(jsonout(bridge(["probe"], self.home, self.corpus, extra_env={"SHELL": "/bin/bash"}))["retention"]["shell"], {"shell": "bash"})

    def test_fake_home_sources_and_settings(self):
        make_fixtures.home(self.home)
        p = self.probe()
        self.assertIs(p["fda"], True)  # Library/Mail is readable
        self.assertEqual(p["sources"]["ai_coding"], "ok")
        self.assertEqual(p["sources"]["git_commits"], "ok")
        self.assertEqual(p["sources"]["imessage"], "absent")
        self.assertEqual(p["retention"]["claude"]["days"], 7)
        self.assertEqual(p["retention"]["messages"], {"readable": True, "value": 0})
        self.assertFalse(p["retention"]["safari"]["readable"])
        self.assertEqual(p["retention"]["codex"], {"present": False})
        self.assertFalse(p["retention"]["iphone_messages"]["readable"], "no backup read yet")
        prefs = self.corpus / "raw/iphone/files/HomeDomain/Library/Preferences"
        prefs.mkdir(parents=True)
        (prefs / "com.apple.MobileSMS.plist").write_bytes(plistlib.dumps({"KeepMessageForDays": 30}))
        (self.home / ".codex/sessions").mkdir(parents=True)
        p = self.probe()
        self.assertEqual(p["retention"]["iphone_messages"], {"readable": True, "value": 30})
        self.assertEqual(p["retention"]["codex"], {"present": True})

    def test_no_full_disk_access(self):
        make_fixtures.home(self.home)
        os.chmod(self.home / "Library/Messages", 0)
        p = self.probe()
        self.assertIs(p["fda"], False)
        self.assertTrue(p["fda_path"].endswith("Messages/chat.db"))
        self.assertEqual(p["sources"]["imessage"], "blocked")

    def test_backups(self):
        make_fixtures.backup(self.home)
        p = self.probe()
        [b] = p["backups"]
        self.assertTrue(b["encrypted"])
        self.assertTrue(b["finished"])
        self.assertFalse(b["in_progress"])
        self.assertEqual(b["device"], "Test iPhone")
        self.assertEqual(b["date"], "2026-09-01T10:00:00+00:00")

    def test_backup_in_progress_and_unencrypted(self):
        make_fixtures.backup(self.home, encrypted=False, finished=False)
        [b] = self.probe()["backups"]
        self.assertFalse(b["encrypted"])
        self.assertFalse(b["finished"])
        self.assertTrue(b["in_progress"])

    def test_mirror_mailboxes_identity(self):
        (self.corpus / "raw/iphone").mkdir(parents=True)
        (self.corpus / "raw/iphone/backup.json").write_text(json.dumps({"backup": "X", "backed_up": "2026-09-01 10:00:00"}))
        (self.corpus / "imports/Hotmail/Inbox.mbox").mkdir(parents=True)
        (self.corpus / "imports/takeout-1/Mail").mkdir(parents=True)
        (self.corpus / "identity.json").write_text(json.dumps(make_fixtures.ME))
        p = self.probe()
        self.assertEqual(p["mirror"]["backup"], "X")
        self.assertEqual(p["mailbox_sources"], ["hotmail"])
        self.assertEqual(p["identity"]["emails"], ["ada@example.com"])
        self.assertIsNone(p["identity_suggestion"])

    def test_icloud_detection(self):
        r = subprocess.run(["xattr", "-w", "com.apple.file-provider-domain-id", "com.apple.CloudDocs.iCloudDriveFileProvider/TEST", str(self.corpus)], capture_output=True)
        if r.returncode != 0:
            self.skipTest("can't set the iCloud xattr here")
        self.assertTrue(self.probe()["corpus"]["in_icloud"])
        inner = self.corpus / "deeper"
        inner.mkdir()
        p = jsonout(bridge(["probe"], self.home, inner))
        self.assertTrue(p["corpus"]["in_icloud"], "a folder inside a synced folder is synced too")
        nosync = self.tmp / "corpus.nosync"
        nosync.mkdir()
        self.assertFalse(jsonout(bridge(["probe"], self.home, nosync))["corpus"]["in_icloud"])


class IdentifyTests(Sandbox):
    EXPECTED = {
        "google_takeout": "google_takeout", "google_photos_drive": "google_photos_drive", "instagram": "instagram",
        "facebook": "facebook", "discord": "discord", "linkedin": "linkedin", "linkedin_nested": "linkedin",
        "notion": "notion", "x": "x", "chatgpt": "chatgpt", "claude_ai": "claude_ai", "spotify": "spotify",
        "reddit": "reddit", "whatsapp_chats": "whatsapp_chats", "slack": "slack", "iphone_vcard": "iphone_vcard",
        "mailbox": "mailbox", "zoom": "zoom", "maps_timeline": "maps_timeline", "unknown": None,
        "google_takeout_folder": "google_takeout",
    }

    def test_every_kind(self):
        made = make_fixtures.exports(self.tmp / "exports")
        names = list(self.EXPECTED)
        res = jsonout(bridge(["identify", *[made[n] for n in names]], self.home, self.corpus))
        for name, r in zip(names, res):
            with self.subTest(name):
                self.assertEqual(r["kind"], self.EXPECTED[name], r)
                self.assertTrue(r["valid"])
                self.assertGreater(r["size"], 0)
        by = dict(zip(names, res))
        self.assertEqual(by["google_takeout"]["export_id"], "20250301")
        self.assertEqual(by["google_photos_drive"]["export_id"], "20250302")
        self.assertEqual(by["unknown"]["reason"], "not a recognized export")
        self.assertIsNone(by["linkedin"]["already_imported"])

    def test_unzipped_by_safari_and_tgz(self):
        """Safari unzips "safe" downloads: a Takeout becomes a folder named Takeout (the zip's top), ChatGPT's a folder
        named after its zip. Takeout can also come as .tgz. Each is still known for what it is."""
        import tarfile, zipfile
        made = make_fixtures.exports(self.tmp / "exports")
        out = self.tmp / "Downloads"
        with zipfile.ZipFile(made["google_takeout"]) as z:
            z.extractall(out / "unz")
            z.extractall(self.tmp / "tgz")
        (out / "unz" / "Takeout").rename(out / "Takeout")
        with zipfile.ZipFile(made["chatgpt"]) as z:
            z.extractall(out / "a1b2c3-2026-10-17-12-00-00")
        tgz = out / "takeout-20250301T120000Z-1-001.tgz"
        with tarfile.open(tgz, "w:gz") as t:
            t.add(self.tmp / "tgz" / "Takeout", arcname="Takeout")
        takeout, chatgpt, packed = jsonout(bridge(["identify", str(out / "Takeout"), str(out / "a1b2c3-2026-10-17-12-00-00"), str(tgz)], self.home, self.corpus))
        self.assertEqual(takeout["kind"], "google_takeout", takeout)
        self.assertEqual(chatgpt["kind"], "chatgpt", chatgpt)
        self.assertEqual((packed["kind"], packed["valid"], packed["export_id"]), ("google_takeout", True, "20250301"), packed)

    def test_already_imported_under_another_name(self):
        made = make_fixtures.exports(self.tmp / "exports")
        (self.corpus / "imports" / "linkedin").mkdir(parents=True)
        shutil.copy(made["linkedin"], self.corpus / "imports" / "linkedin" / "Basic_LinkedInDataExport.zip")
        other = self.tmp / "same-size.zip"
        data = bytearray(Path(made["linkedin"]).read_bytes())
        data[-1] ^= 1  # same size, different bytes: a zip's last byte is the comment length's high byte, so still a zip
        other.write_bytes(data)
        res = jsonout(bridge(["identify", made["linkedin"], str(other)], self.home, self.corpus))
        self.assertEqual(res[0]["already_imported"], "linkedin/Basic_LinkedInDataExport.zip")
        self.assertFalse(res[1].get("already_imported"))

    def test_broken_and_missing(self):
        made = make_fixtures.exports(self.tmp / "exports")
        broken, missing = jsonout(bridge(["identify", made["broken"], str(self.tmp / "nope.zip")], self.home, self.corpus))
        self.assertFalse(broken["valid"])
        self.assertIn("not a complete zip", broken["reason"])
        self.assertFalse(missing["valid"])

    def test_password_locked_zip(self):
        """WeChat's download is a zip locked with a password: said so, not taken for an export with nothing in it."""
        import zipfile
        locked = self.tmp / "wechat_export.zip"
        with zipfile.ZipFile(locked, "w") as z:
            z.writestr("moments.json", '{"moments": []}')
        data = bytearray(locked.read_bytes())
        for sig, at in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):  # set the encrypted bit in both headers
            i = data.index(sig)
            data[i + at] |= 0x1
        locked.write_bytes(data)
        [res] = jsonout(bridge(["identify", str(locked)], self.home, self.corpus))
        self.assertFalse(res["valid"])
        self.assertTrue(res["encrypted"])
        self.assertIn("password", res["reason"])

    @unittest.skipUnless(REAL_IMPORTS.exists(), "no real exports on this machine")
    def test_real_exports(self):
        """Every export already in this machine's corpus/imports/ is a complete file, and the ones in a built-in
        source's folder are recognized (read-only). A service someone added (TikTok, say) has no recognizer: its
        files are filed by name."""
        import re
        catalog = (DESKTOP / "src/shared/catalog.ts").read_text()
        builtin = set(re.findall(r"importDir: '([^']+)'", catalog))
        paths = [str(p) for p in sorted(REAL_IMPORTS.rglob("*"))
                 if not any(part.startswith(".") for part in p.relative_to(REAL_IMPORTS).parts)
                 and (p.suffix.lower() in (".zip", ".vcf") or (p.is_dir() and p.suffix.lower() == ".mbox"))]
        if not paths:
            self.skipTest("no real exports")
        res = jsonout(bridge(["identify", *paths], self.home, self.corpus))
        for p, r in zip(paths, res):
            top = Path(p).relative_to(REAL_IMPORTS).parts[0]
            with self.subTest(Path(p).parent.name):
                if top in builtin or top.startswith("takeout"):
                    self.assertIsNotNone(r["kind"], r["reason"])
                self.assertTrue(r["valid"], r["reason"])


class TakeoutKindTests(unittest.TestCase):
    def test_photos_and_drive_alone_in_any_language_and_the_main_one_by_anything_else(self):
        code = ("import sys, json; sys.path.insert(0, sys.argv[1]); import bridge; "
                "print(json.dumps([bridge.classify_names(n.split(',')) for n in sys.argv[2:]]))")
        cases = {"Takeout/Google Fotos/Fotos von 2024/a.jpg,Takeout/archive_browser.html": "google_photos_drive",
                 "Takeout/Google Photos/Trip/a.jpg,Takeout/Drive/notes.txt": "google_photos_drive",
                 "Takeout/Meine Aktivitäten/Suche/MeineAktivitäten.html,Takeout/Google Fotos/a.jpg": "google_takeout",
                 "Takeout/Correo/Todo el correo.mbox": "google_takeout"}
        r = subprocess.run([sys.executable, "-c", code, str(BRIDGE.parent), *cases], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout.strip().splitlines()[-1]), list(cases.values()))


class DiscoverTests(Sandbox):
    def corpus_db(self, rows):
        con = sqlite3.connect(self.corpus / "corpus.db")
        con.execute("create table records (source text, id text, ts text, kind text, is_me text, url text, title text, meta text)")
        con.executemany("insert into records values (?,?,?,?,?,?,?,?)", rows)
        con.commit()
        con.close()

    def test_found_from_mail_sites_and_apps(self):
        mail = lambda n, frm, ts="2024-05-01T00:00:00Z", me="0": ("gmail", f"m{n}", ts, "email", me, None, None, json.dumps({"from": frm}))
        rows = [mail(i, "Wattpad <noreply@mail.wattpad.com>") for i in range(6)]
        rows += [mail(10, "Wattpad <stories@wattpad.com>", "2016-02-01T00:00:00Z")]
        rows += [mail(20 + i, "Facebook <notification@facebookmail.com>") for i in range(3)]  # a service's own mail domain
        rows += [mail(30 + i, "Corner Climbing Gym <hello@cornerclimb.example>") for i in range(4)]  # in no directory
        rows += [mail(40 + i, "A Friend <friend@gmail.com>") for i in range(9)]  # people, not services
        rows += [mail(50, "Me <ada@wattpad.com>", me="1")]  # mail you sent doesn't count
        rows += [("browser_history", f"v{i}", None, "visit", None, f"https://www.wattpad.com/story/{i}", None, "{}") for i in range(3)]
        # Someone's GitHub Pages site isn't Matrix, though Matrix's directory entry lists two other github.io pages.
        rows += [("browser_history", f"g{i}", None, "visit", None, f"https://someone.github.io/notes/{i}", None, "{}") for i in range(25)]
        rows += [("phone_installed_apps", "a1", None, "app", None, None, "Duolingo", json.dumps({"bundle": "com.duolingo.DuolingoMobile"}))]
        self.corpus_db(rows)
        apps = self.tmp / "Applications/Sketchbook.app/Contents"
        apps.mkdir(parents=True)
        (apps / "Info.plist").write_bytes(plistlib.dumps({"CFBundleName": "Sketchbook", "CFBundleIdentifier": "com.sketchbook-tool.app"}))
        d = jsonout(bridge(["discover-services"], self.home, self.corpus, extra_env={"UMP_APPLICATIONS": str(self.tmp / "Applications")}))
        by = {f["slug"]: f for f in d["found"]}
        self.assertGreater(d["services"], 2000, "the bundled directory")
        w = by["wattpad"]
        self.assertEqual((w["emails"], w["automated"], w["visits"], w["first"]), (7, 6, 3, "2016-02-01T00:00:00Z"), "stories@ is not an automated address")
        self.assertIn("export", w, "its export steps come along")
        self.assertEqual(by["duolingo"]["apps"], ["Duolingo on your iPhone"])
        self.assertIn("facebook", by, "facebookmail.com is Facebook")
        self.assertEqual(sorted((u["domain"], u["name"]) for u in d["unmatched"]), [("cornerclimb.example", "Corner Climbing Gym"), ("sketchbook-tool.com", "Sketchbook")],
                         "mail from account addresses, and an app, that no directory knows, by the names they go by")
        self.assertFalse(any("gmail" in f["slug"] for f in d["found"]), "a mail host is not a service")
        self.assertEqual(sum(f["visits"] for f in d["found"]), 3, "only Wattpad's visits: a github.io site is its own site")

    def test_empty_corpus(self):
        d = jsonout(bridge(["discover-services"], self.home, self.corpus, extra_env={"UMP_APPLICATIONS": str(self.tmp / "none")}))
        self.assertEqual((d["found"], d["unmatched"], d["services"] > 0), ([], [], True))


def notification_db(path, items):
    """A Notification Center database like macOS's: items are (app id, when, title, subtitle, body)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("create table app (app_id integer primary key, identifier text, badge integer)")
    con.execute("create table record (rec_id integer primary key, app_id integer, uuid blob, data blob, request_date real, "
                "request_last_date real, delivered_date real, presented integer, style integer, snooze_fire_date real)")
    apps = {}
    epoch = dt.datetime(2001, 1, 1, tzinfo=dt.timezone.utc)
    for ident, when, title, subtitle, body in items:
        apps.setdefault(ident, len(apps) + 1)
        con.execute("insert or ignore into app values (?, ?, 0)", (apps[ident], ident))
        data = plistlib.dumps({"app": ident, "req": {"titl": title, "subt": subtitle, "body": body}}, fmt=plistlib.FMT_BINARY)
        secs = (when - epoch).total_seconds()
        con.execute("insert into record (app_id, data, delivered_date) values (?, ?, ?)", (apps[ident], data, secs))
    con.commit()
    con.close()


def mail_index(root, items):
    """An Apple Mail store like macOS's: MailData/Envelope Index (sender, subject, first lines, mailbox) and each
    message as an .emlx under its account's folder. items: (when, address, name, subject, first lines, html body)."""
    (root / "MailData").mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(root / "MailData/Envelope Index")
    con.executescript("""create table messages (ROWID integer primary key, sender integer, subject integer, summary integer,
                         date_received integer, mailbox integer, deleted integer default 0);
                         create table addresses (ROWID integer primary key, address text, comment text);
                         create table subjects (ROWID integer primary key, subject text);
                         create table summaries (ROWID integer primary key, summary text);
                         create table mailboxes (ROWID integer primary key, url text);
                         insert into mailboxes values (1, 'imap://ACCOUNT-1/INBOX');""")
    box = root / "ACCOUNT-1/INBOX.mbox/1F2E3D4C/Data/Messages"
    box.mkdir(parents=True, exist_ok=True)
    for i, (when, addr, name, subject, summary, html) in enumerate(items, 1):
        con.execute("insert into addresses values (?, ?, ?)", (i, addr, name))
        con.execute("insert into subjects values (?, ?)", (i, subject))
        con.execute("insert into summaries values (?, ?)", (i, summary))
        con.execute("insert into messages (ROWID, sender, subject, summary, date_received, mailbox) values (?, ?, ?, ?, ?, 1)",
                    (i, i, i, i, int(when.timestamp())))
        msg = (f"From: {name} <{addr}>\r\nSubject: {subject}\r\nMIME-Version: 1.0\r\nContent-Type: text/html; charset=utf-8\r\n\r\n{html}\r\n").encode()
        (box / f"{i}.emlx").write_bytes(f"{len(msg)}\n".encode() + msg + b"<?xml version=\"1.0\"?><plist version=\"1.0\"><dict/></plist>")
    con.commit()
    con.close()
    return root / "MailData/Envelope Index"


class MailTests(Sandbox):
    def test_a_ready_email_with_its_download_link(self):
        t = lambda d, h=12: dt.datetime(2026, 10, d, h, tzinfo=dt.timezone.utc)
        db = mail_index(self.tmp / "Mail/V10", [
            (t(6), "noreply-takeout@google.com", "Google Takeout", "Archive of Google data requested", "We're preparing your archive",
             '<a href="https://takeout.google.com/settings/takeout">Manage</a>'),
            (t(8), "no-reply@mail.instagram.com", "Instagram", "Your Instagram information is ready to download", "Hi ada_l, your information is ready",
             '<a href="https://help.instagram.com/1234">Help</a> <a href="https://accountscenter.instagram.com/info_and_permissions/dyi/?entry=email&amp;id=99">Download your information</a>'
             ' <a href="https://www.instagram.com/emails/unsubscribe/?x=1">Unsubscribe</a>'),
            (t(9), "noreply-takeout@google.com", "Google Takeout", "Your Google data is ready to download", "Your Google data is ready",
             '<a href="https://support.google.com/accounts">Learn more</a> <a href="https://takeout.google.com/settings/takeout/downloads?user=1">Download your files</a>'),
            (t(9), "no-reply@spotify.com", "Spotify", "Your Wrapped is ready", "Your year in music is ready to share", '<a href="https://open.spotify.com/wrapped">See it</a>'),
            (t(10), "ada@example.com", "Ada Lovelace", "dinner?", "are we still on", "<p>see you at 7</p>"),
        ])
        asked = [{"id": "instagram", "names": ["Instagram"], "domains": ["instagram.com"], "since": "2026-10-05T00:00:00Z"},
                 {"id": "google_takeout", "names": ["Google"], "domains": ["google.com", "takeout.google.com"], "since": "2026-10-05T00:00:00Z"},
                 {"id": "spotify", "names": ["Spotify"], "domains": ["spotify.com"], "since": "2026-10-05T00:00:00Z"}]
        env = {"UMP_MAIL_DB": str(db), "UMP_NOTIFICATIONS_DB": str(self.tmp / "missing/db")}
        d = jsonout(bridge(["export-signals"], self.home, self.corpus, stdin=json.dumps(asked), extra_env=env))
        by = {m["source"]: m for m in d["matches"]}
        self.assertTrue(d["mail"])
        self.assertEqual(set(by), {"instagram", "google_takeout"}, "Spotify's Wrapped mail is ready, but isn't about your data")
        self.assertEqual((by["instagram"]["via"], by["instagram"]["sender"]), ("Mail", "Instagram"))
        self.assertEqual(by["instagram"]["link"], "https://accountscenter.instagram.com/info_and_permissions/dyi/?entry=email&id=99", "the download, not help or unsubscribe")
        self.assertEqual(by["google_takeout"]["at"], "2026-10-09T12:00:00.000+00:00", "the ready mail, not the \"requested\" one before it")
        self.assertEqual(by["google_takeout"]["link"], "https://takeout.google.com/settings/takeout/downloads?user=1")
        self.assertNotIn("dinner", json.dumps(d), "nothing else leaves")
        asked[0]["seen"] = by["instagram"]["at"]
        again = jsonout(bridge(["export-signals"], self.home, self.corpus, stdin=json.dumps(asked), extra_env=env))
        self.assertNotIn("instagram", {m["source"] for m in again["matches"]}, "a sign already known isn't news")
        # Turned off in Your Setup: Mail isn't looked in at all.
        off = jsonout(bridge(["export-signals"], self.home, self.corpus, stdin=json.dumps(asked[1:]), extra_env={**env, "UMP_READY_MAIL": "0"}))
        self.assertEqual((off["mail"], off["matches"]), (False, []))

    def test_a_ready_email_not_from_the_service_is_only_a_guess_and_junk_is_nothing(self):
        """Anyone can write "Your Instagram data is ready": from another domain it's a guess with no link (a link from it
        is what could steer Claude), and from Junk it's nothing."""
        t = lambda d, h=12: dt.datetime(2026, 10, d, h, tzinfo=dt.timezone.utc)
        db = mail_index(self.tmp / "Mail/V10", [
            (t(8), "help@insta-gram-support.example", "Instagram", "Your Instagram information is ready to download", "Get it now",
             '<a href="https://docs.google.com/document/d/evil">Download your information</a>'),
            (t(9), "no-reply@mail.instagram.com", "Instagram", "Your Instagram information is ready to download", "Hi, it's ready",
             '<a href="https://accountscenter.instagram.com/info_and_permissions/dyi/?id=1">Download your information</a>'),
        ])
        con = sqlite3.connect(db)
        con.execute("insert into mailboxes values (2, 'imap://ACCOUNT-1/Junk')")
        con.execute("update messages set mailbox = 2 where ROWID = 2")
        con.commit()
        con.close()
        asked = [{"id": "instagram", "names": ["Instagram"], "domains": ["instagram.com"], "since": "2026-10-05T00:00:00Z"}]
        env = {"UMP_MAIL_DB": str(db), "UMP_NOTIFICATIONS_DB": str(self.tmp / "missing/db")}
        [m] = jsonout(bridge(["export-signals"], self.home, self.corpus, stdin=json.dumps(asked), extra_env=env))["matches"]
        self.assertEqual(m["at"][:10], "2026-10-08", "the one in Junk counts for nothing, though it's from Instagram")
        self.assertNotIn("link", m)
        self.assertNotIn("sender", m, "a guess: not \"Instagram emailed you\"")

    def test_an_email_beats_a_notification_about_the_same_export(self):
        t = lambda d, h=12: dt.datetime(2026, 10, d, h, tzinfo=dt.timezone.utc)
        db = mail_index(self.tmp / "Mail/V10", [(t(8), "noreply@discord.com", "Discord", "Your Discord data package is ready", "Download it below",
                                                 '<a href="https://click.discord.com/ls/click?upn=abc">Download data package</a>')])
        notification_db(self.tmp / "db2/db", [("com.hnc.discord", t(9), "Discord", "", "Your data package is ready")])
        d = jsonout(bridge(["export-signals"], self.home, self.corpus, extra_env={"UMP_MAIL_DB": str(db), "UMP_NOTIFICATIONS_DB": str(self.tmp / "db2/db")},
                           stdin=json.dumps([{"id": "discord", "names": ["Discord"], "domains": ["discord.com"], "since": "2026-10-05T00:00:00Z"}])))
        self.assertEqual([(m["via"], m["link"]) for m in d["matches"]], [("Mail", "https://click.discord.com/ls/click?upn=abc")])


class NotificationTests(Sandbox):
    def test_a_ready_notification_for_an_export_you_asked_for(self):
        t = lambda d, h=12: dt.datetime(2026, 10, d, h, tzinfo=dt.timezone.utc)
        db = self.tmp / "db2/db"
        notification_db(db, [
            ("com.apple.mail", t(9), "Spotify", "Your data is ready to download", "Hi Ada, the data you asked for is ready."),
            ("com.apple.mail", t(3), "Discord", "Your data package is ready", "From before you asked: ignored"),
            ("com.hnc.discord", t(9), "general", "", "is the new album ready? (a chat, not Discord's data)"),
            ("com.apple.mobilesms", t(9), "Mum", "", "dinner at 7"),
            ("com.reddit.Reddit", t(10), "Reddit", "", "Your Reddit data request is complete"),
            ("com.apple.mail", t(9), ["X"], "", ["Your X archive is ready"]),
        ])
        asked = [{"id": "spotify", "names": ["Spotify", "spotify"], "since": "2026-10-05T00:00:00Z"},
                 {"id": "discord", "names": ["Discord"], "since": "2026-10-05T00:00:00Z"},
                 {"id": "reddit", "names": ["Reddit"], "since": "2026-10-05T00:00:00Z"},
                 {"id": "x", "names": ["X (Twitter)", "X", "Twitter"], "since": "2026-10-05T00:00:00Z"}]
        d = jsonout(bridge(["export-signals"], self.home, self.corpus, stdin=json.dumps(asked), extra_env={"UMP_NOTIFICATIONS_DB": str(db)}))
        by = {m["source"]: m for m in d["matches"]}
        self.assertTrue(d["readable"])
        self.assertEqual(set(by), {"spotify", "reddit", "x"},
                         "Discord's ready mail came before it was asked for; its chat mentions \"ready\" but isn't about data")
        self.assertEqual((by["spotify"]["via"], by["spotify"]["at"]), ("Mail", "2026-10-09T12:00:00.000+00:00"))
        self.assertIn("Your data is ready to download", by["spotify"]["text"])
        self.assertEqual(by["reddit"]["via"], "Reddit", "an iPhone app's notification, forwarded to the Mac")
        self.assertNotIn("dinner", json.dumps(d), "nothing else leaves")

    def test_whether_a_test_notification_was_shown(self):
        t = lambda m: dt.datetime(2026, 10, 16, 21, m, tzinfo=dt.timezone.utc)
        db = self.tmp / "db2/db"
        notification_db(db, [("org.homecoming.desktop", t(10), "Homecoming notifications are on", "", "earlier"),
                             ("org.homecoming.desktop", t(15), "Homecoming notifications are on", "", "now"),
                             ("com.apple.mail", t(15), "Something else", "", "")])
        env = {"UMP_NOTIFICATIONS_DB": str(db)}
        ask = lambda since: jsonout(bridge(["notification-shown"], self.home, self.corpus, extra_env=env,
                                           stdin=json.dumps({"title": "Homecoming notifications are on", "since": since})))
        self.assertEqual(ask("2026-10-16T21:14:00Z"), {"readable": True, "found": True, "presented": False, "app": "org.homecoming.desktop"},
                         "macOS kept it without showing it")
        con = sqlite3.connect(db)
        con.execute("update record set presented = 1 where rec_id = 2")
        con.commit()
        con.close()
        self.assertTrue(ask("2026-10-16T21:14:00Z")["presented"], "shown")
        self.assertEqual(ask("2026-10-16T21:16:00Z"), {"readable": True, "found": False}, "none since then: macOS didn't take it")
        self.assertEqual(jsonout(bridge(["notification-shown"], self.home, self.corpus, stdin="{}",
                                        extra_env={"UMP_NOTIFICATIONS_DB": str(self.tmp / "missing/db")})), {"readable": False})

    def test_notification_settings_for_this_app(self):
        # usernoted's preferences: each app's flags. Bit 25 allows its notifications; bit 3 is banners, bit 4 alerts.
        prefs = self.tmp / "usernoted.plist"
        apps = [{"bundle-id": "org.homecoming.desktop", "flags": (1 << 25) | (1 << 3) | 0b110},
                {"bundle-id": "org.homecoming.desktop.dev", "flags": (1 << 3) | 0b110},
                {"bundle-id": "com.example.alerts", "flags": (1 << 25) | (1 << 4)},
                {"bundle-id": "com.example.quiet", "flags": 1 << 25}]
        prefs.write_bytes(plistlib.dumps({"apps": apps, "version": 1}, fmt=plistlib.FMT_BINARY))
        ask = lambda b, p=prefs: jsonout(bridge(["notification-prefs", b], self.home, self.corpus, extra_env={"UMP_NOTIFICATION_PREFS": str(p)}))
        self.assertEqual(ask("org.homecoming.desktop"), {"readable": True, "found": True, "allowed": True, "style": "banners"})
        self.assertEqual(ask("org.homecoming.desktop.dev")["allowed"], False, "turned off")
        self.assertEqual(ask("com.example.alerts")["style"], "alerts")
        self.assertEqual(ask("com.example.quiet")["style"], "none", "allowed, kept in Notification Center only")
        self.assertEqual(ask("org.never.asked"), {"readable": True, "found": False}, "macOS hasn't asked yet")
        self.assertEqual(ask("org.homecoming.desktop", self.tmp / "missing.plist"), {"readable": False})

    def test_unreadable_without_access(self):
        d = jsonout(bridge(["export-signals"], self.home, self.corpus, stdin=json.dumps([{"id": "spotify", "names": ["Spotify"], "since": "2026-10-05T00:00:00Z"}]),
                           extra_env={"UMP_NOTIFICATIONS_DB": str(self.tmp / "missing/db")}))
        self.assertEqual(d, {"readable": False, "mail": False, "matches": []})

    def test_the_probe_copies_nothing_and_a_place_turned_off_keeps_no_copy(self):
        db = self.tmp / "db2/db"
        notification_db(db, [("com.apple.mail", dt.datetime(2026, 10, 9, 12, tzinfo=dt.timezone.utc), "Spotify", "", "Your data is ready")])
        cache = self.tmp / "cache"
        env = {"UMP_NOTIFICATIONS_DB": str(db), "UMP_CACHE_DIR": str(cache)}
        copy = cache / "copies/notifications/db"
        self.assertTrue(jsonout(bridge(["probe"], self.home, self.corpus, extra_env=env))["notifications"]["readable"])
        self.assertFalse(copy.exists(), "whether it can be read is asked of the file itself: nothing copied for it")
        asked = json.dumps([{"id": "spotify", "names": ["Spotify"], "since": "2026-10-05T00:00:00Z"}])
        self.assertEqual(len(jsonout(bridge(["export-signals"], self.home, self.corpus, stdin=asked, extra_env=env))["matches"]), 1)
        self.assertTrue(copy.exists(), "looked in for an export on its way: read from a copy")
        jsonout(bridge(["probe"], self.home, self.corpus, extra_env={**env, "UMP_READY_NOTIFICATIONS": "0"}))
        self.assertFalse(copy.exists(), "turned off in General: the copy goes too")
        self.assertFalse(copy.parent.exists(), "and its folder")

    def test_iphone_notifications_on_this_mac(self):
        prefs = self.home / "Library/Group Containers/group.com.apple.usernoted/Library/Preferences/group.com.apple.usernoted.plist"
        prefs.parent.mkdir(parents=True)
        local = {"bundle-id": "com.apple.mail", "path": "/System/Applications/Mail.app"}
        system = {"bundle-id": "_SYSTEM_CENTER_:com.apple.accountsd"}
        prefs.write_bytes(plistlib.dumps({"apps": [local, system]}))
        self.assertFalse(self.probe()["notifications"]["iphone"], "only Mac apps and system services")
        prefs.write_bytes(plistlib.dumps({"apps": [local, system, {"bundle-id": "com.reddit.Reddit"}]}))
        self.assertTrue(self.probe()["notifications"]["iphone"], "an app with nothing on this Mac: the iPhone's")


class MappingTests(Sandbox):
    MAPPING = {"service": "Wattpad", "items": [
        {"describe": "Stories you wrote", "file": "export.json", "path": "data.stories", "kind": "post", "time": "created",
         "title": "title", "text": ["blurb"], "author": "me", "id": "id"},
        {"describe": "Comments", "file": "*.csv", "kind": "comment", "time": "when", "text": ["body"], "author": "who"},
        {"describe": "Nothing", "file": "missing.json", "kind": "not-a-kind"}]}

    def setUp(self):
        super().setUp()
        d = self.corpus / "imports/wattpad"
        d.mkdir(parents=True)
        (d / "export.json").write_text(json.dumps({"data": {"stories": [
            {"id": 1, "title": "Secret Title", "blurb": "Private words", "created": 1551434400, "tags": ["a"]},
            {"id": 2, "title": "Second", "blurb": "More", "created": "2020-01-02T03:04:05Z"}]}, "settings": {"theme": "dark"}}))
        (d / "comments.csv").write_text("who,body,when\nbabbage,Nice,2019-03-02\n")
        (d / "cover.jpg").write_bytes(b"\xff\xd8")
        self.lib = self.tmp / "library"
        self.env = {"UMP_MAPPING_LIBRARY": str(self.lib)}

    def run_bridge(self, *args, stdin=None):
        return jsonout(bridge(list(args), self.home, self.corpus, stdin=stdin, extra_env=self.env))

    def test_describe_shows_structure_and_values_only_when_asked(self):
        d = self.run_bridge("describe-export", "wattpad", "--service=Wattpad")
        self.assertEqual(d["structured"], 2)
        self.assertEqual(len(d["files"]), 3)
        for what in ("wattpad/comments.csv  (1 file, CSV", "wattpad/export.json  (1 file, JSON", "(1 file, media, kept as a file"):
            self.assertIn(what, d["prompt"])
        self.assertIn('"created": "date and time or number (looks like a Unix time in seconds)"', d["prompt"])
        self.assertIn("personal-data export from Wattpad", d["prompt"])
        self.assertNotIn("Secret Title", d["prompt"])
        self.assertNotIn("Private words", d["prompt"])
        ex = self.run_bridge("describe-export", "wattpad", "--examples")
        self.assertIn('e.g. \\"Secret Title\\"', ex["prompt"])

    def test_names_in_paths_and_keys_never_reach_claude(self):
        # One folder per conversation, named after the people in it; pages named after their titles; a table
        # keyed by ids. None of those names or ids may appear in what would be sent.
        d = self.corpus / "imports/wattpad"
        for who in ("adalovelace_1234567", "charlesbabbage_7654321", "maryshelley_1111111", "percyshelley_2222222"):
            (d / "inbox" / who).mkdir(parents=True)
            (d / "inbox" / who / "message_1.json").write_text(json.dumps({"participants": [{"name": "x"}], "messages": [{"sender_name": "x", "content": "hi", "timestamp_ms": 1600000000000}]}))
        (d / "pages").mkdir()
        (d / "pages/Secret Plans 1a2b3c4d5e6f7a8b9c0d1e2f.md").write_text("# hi")
        (d / "channels.json").write_text(json.dumps({"749054660769218631": "general", "225417092604755969": "random"}))
        p = self.run_bridge("describe-export", "wattpad")["prompt"]
        self.assertIn("inbox/*/message_*.json  (4 files, JSON", p)
        self.assertIn("pages/*.md  (1 file", p)
        self.assertIn('"map with keys": "2 numbers"', p)
        for leak in ("adalovelace", "babbage", "shelley", "Secret Plans", "749054660769218631", "general"):
            self.assertNotIn(leak, p)

    def test_try_save_remove(self):
        t = self.run_bridge("try-mapping", "wattpad", stdin=json.dumps(self.MAPPING))
        by = {r["describe"]: r for r in t["rules"]}
        self.assertEqual((by["Stories you wrote"]["items"], by["Stories you wrote"]["timed"]), (2, 2), "Unix seconds and ISO times both read")
        self.assertEqual(by["Stories you wrote"]["first"], "2019-03-01T10:00:00Z")
        self.assertEqual(by["Comments"]["items"], 1)
        self.assertEqual((by["Nothing"]["items"], by["Nothing"]["kind"]), (0, "record"), "an unknown kind is a record")
        self.assertEqual((t["structured"], t["mapped"], t["unmapped"]), (2, 2, []))
        self.assertIn("error", self.run_bridge("try-mapping", "wattpad", stdin='{"items": []}'))
        self.assertIn("error", self.run_bridge("try-mapping", "wattpad", stdin='not json'))
        self.run_bridge("save-mapping", "wattpad", "--share=wattpad", stdin=json.dumps(self.MAPPING))
        saved = json.loads((self.corpus / "mappings/wattpad.json").read_text())
        self.assertFalse((self.lib / "wattpad.json").exists(), "the app's own mappings are never written to")
        self.assertNotIn("Secret", json.dumps(saved), "a mapping holds field names, never data")
        self.run_bridge("save-mapping", "wattpad", "--remove")
        self.assertFalse((self.corpus / "mappings/wattpad.json").exists())

    def test_try_says_when_ids_repeat(self):
        """A mapping whose id field is the same for many items (a shelf, not a book): Try Mapping says how many would be
        left out, rather than the import failing on them."""
        mapping = {"service": "Wattpad", "items": [{"describe": "Stories", "file": "export.json", "path": "data.stories", "kind": "post",
                                                    "title": "title", "id": "tags"}]}
        d = self.corpus / "imports/wattpad/export.json"
        d.write_text(json.dumps({"data": {"stories": [{"title": "A", "tags": "x"}, {"title": "B", "tags": "x"}, {"title": "C", "tags": "y"}]}}))
        rule = self.run_bridge("try-mapping", "wattpad", stdin=json.dumps(mapping))["rules"][0]
        self.assertEqual((rule["items"], rule["repeats"]), (2, 1))


class StatsTests(Sandbox):
    def test_years_and_manifest(self):
        (self.corpus / "manifest.json").write_text(json.dumps({"imessage": {"count": 3, "first": "2019-01-01T00:00:00Z"}}))
        con = sqlite3.connect(self.corpus / "corpus.db")
        con.execute("create table records (source text, id text, ts text)")
        con.executemany("insert into records values (?,?,?)", [
            ("imessage", "1", "2019-05-01T00:00:00Z"), ("imessage", "2", "2020-05-01T00:00:00Z"),
            ("imessage", "3", "2020-06-01T00:00:00Z"), ("gmail", "4", None), ("gmail", "5", "garbage")])
        con.commit()
        con.close()
        s = jsonout(bridge(["stats"], self.home, self.corpus))
        self.assertEqual(s["manifest"]["imessage"]["count"], 3)
        self.assertEqual(s["years"], {"imessage": {"2019": 1, "2020": 2}})
        self.assertIsNotNone(s["db_mtime"])

    def test_empty_corpus(self):
        s = jsonout(bridge(["stats"], self.home, self.corpus))
        self.assertEqual(s, {"manifest": {}, "years": {}, "copies": {}, "device": [], "facets": {}, "db_mtime": None, "manifest_mtime": None})

    def test_phone_copies_and_internals(self):
        (self.corpus / "manifest.json").write_text(json.dumps({"phone_filesapp": {"count": 3}, "phone_whatsapp": {"count": 1}}))
        con = sqlite3.connect(self.corpus / "corpus.db")
        con.execute("create table records (source text, id text, ts text, meta text)")
        con.executemany("insert into records values (?,?,?,?)", [
            ("imessage", "1", None, '{"copy": "iphone", "service": "iMessage"}'), ("imessage", "2", None, '{"copy": "iphone", "service": "SMS"}'),
            ("imessage", "3", None, '{"copy": "mac", "service": "iMessage"}'), ("calls", "4", None, "{}"),
            ("browser_history", "safari:1", None, "{}"), ("browser_history", "chrome:2", None, "{}"),
            ("git_commits", "a", None, '{"repo": "x"}'), ("git_commits", "b", None, '{"repo": "x"}'),
            ("phone_filesapp", "5", None, '{"tier": "device"}'), ("phone_filesapp", "6", None, '{"tier": "device"}'),
            ("phone_filesapp", "7", None, "{}"), ("phone_whatsapp", "8", None, "{}")])
        con.commit()
        con.close()
        s = jsonout(bridge(["stats"], self.home, self.corpus))
        self.assertEqual(s["copies"], {"imessage": {"iphone": 2, "mac": 1}})
        self.assertEqual(s["facets"], {"imessage": {"iMessage": 2, "SMS": 1}, "browser_history": {"safari": 1, "chrome": 1},
                                       "git_commits": {"repositories": 1}})
        self.assertEqual(s["device"], ["phone_filesapp"])


FAKE_CONNECTORS = """
import sys
from common import Writer

def main():
    print("[fakeconn] reading")
    with Writer("fakeconn", "fixture", parser="fixture") as w:
        w.add(id="1", kind="note", ts="2024-01-01T00:00:00Z", text="hello")
    print("[fakeconn] wrote 1")
"""
FAKE_FAIL = """
def main():
    print("about to fail")
    raise RuntimeError("database is locked")
"""
FAKE_EXIT = """
import sys
def main():
    sys.exit("Wrong password: nothing was written.")
"""
FAKE_IPHONE = """
import json, sys
from common import Writer, RAW

def main(argv=None):
    argv = argv or []
    pw = sys.stdin.readline().rstrip("\\n") if "--password-stdin" in argv else None
    print(f"[fake_iphone] args {argv}")
    if pw != "correct horse":
        sys.exit("Wrong password: the backup's keys didn't unwrap. Nothing was written.")
    (RAW / "iphone").mkdir(parents=True, exist_ok=True)
    (RAW / "iphone/backup.json").write_text(json.dumps({"backup": "00008120-TEST", "backed_up": "2026-09-01 10:00:00"}))
    with Writer("phone_fake", "fixture", parser="fixture") as w:
        w.add(id="1", kind="record", ts="2026-10-01T00:00:00Z", text="from the phone")
    print("[fake_iphone] done")
"""


class RunTests(Sandbox):
    def setUp(self):
        super().setUp()
        self.mods = self.tmp / "mods"
        self.mods.mkdir()
        (self.mods / "fakeconn.py").write_text(FAKE_CONNECTORS)
        (self.mods / "fakefail.py").write_text(FAKE_FAIL)
        (self.mods / "fakeexit.py").write_text(FAKE_EXIT)
        (self.mods / "fake_iphone.py").write_text(FAKE_IPHONE)
        self.env = {"UMP_EXTRA_PYPATH": str(self.mods)}

    def test_success_events_and_index(self):
        r = bridge(["run", "fakeconn"], self.home, self.corpus, extra_env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        ev = events(r)
        types = [e["type"] for e in ev]
        self.assertEqual(types[0], "start")
        self.assertIn({"type": "log", "connector": "fakeconn", "line": "[fakeconn] reading"}, ev)
        self.assertEqual([e for e in ev if e["type"] == "done"][0]["connector"], "fakeconn")
        self.assertEqual(ev[-1], {"type": "finished", "failed": []})
        self.assertTrue((self.corpus / "corpus.db").exists())
        m = json.loads((self.corpus / "manifest.json").read_text())
        self.assertEqual(m["fakeconn"]["count"], 1)
        s = jsonout(bridge(["stats"], self.home, self.corpus))
        self.assertEqual(s["years"], {"fakeconn": {"2024": 1}})

    def test_failures_keep_going(self):
        r = bridge(["run", "fakefail", "fakeexit", "fakeconn", "--no-index"], self.home, self.corpus, extra_env=self.env)
        self.assertEqual(r.returncode, 1)
        ev = events(r)
        errors = {e["connector"]: e["error"] for e in ev if e["type"] == "error"}
        self.assertEqual(errors["fakefail"], "RuntimeError: database is locked")
        self.assertEqual(errors["fakeexit"], "Wrong password: nothing was written.")
        self.assertTrue(any(e["type"] == "done" and e["connector"] == "fakeconn" for e in ev))
        self.assertEqual(ev[-1], {"type": "finished", "failed": ["fakefail", "fakeexit"]})
        self.assertFalse((self.corpus / "corpus.db").exists(), "--no-index skips the index")
        # tracebacks arrive as log lines, never as broken JSON
        self.assertTrue(any(e["type"] == "log" and "Traceback" in e["line"] for e in ev))

    def test_iphone_wrong_then_right_password(self):
        env = {**self.env, "UMP_IPHONE_MODULE": "fake_iphone"}
        bad = bridge(["iphone", "--password-stdin"], self.home, self.corpus, stdin="nope\n", extra_env=env)
        self.assertEqual(bad.returncode, 1)
        err = [e for e in events(bad) if e["type"] == "error"][0]
        self.assertTrue(err["error"].startswith("Wrong password"))
        self.assertNotIn("nope", bad.stdout + bad.stderr, "the password never appears in output")
        good = bridge(["iphone", "--password-stdin"], self.home, self.corpus, stdin="correct horse\n", extra_env=env)
        self.assertEqual(good.returncode, 0, good.stdout)
        self.assertNotIn("correct horse", good.stdout + good.stderr)
        self.assertEqual(json.loads((self.corpus / "manifest.json").read_text())["phone_fake"]["count"], 1)
        self.assertEqual(jsonout(bridge(["probe"], self.home, self.corpus))["mirror"]["backup"], "00008120-TEST")


class RealConnectorsInSandbox(Sandbox):
    """The real connectors, reading a fake home and writing a throwaway corpus."""

    def test_mac_connectors(self):
        make_fixtures.home(self.home)
        (self.corpus / "identity.json").write_text(json.dumps(make_fixtures.ME))
        r = bridge(["run", "ai_coding", "git_commits"], self.home, self.corpus)
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-2000:])
        m = json.loads((self.corpus / "manifest.json").read_text())
        self.assertEqual(m["ai_coding"]["count"], 2)
        self.assertEqual(m["git_commits"]["count"], 1)
        con = sqlite3.connect(self.corpus / "corpus.db")
        title = con.execute("select title from records where source='git_commits'").fetchone()[0]
        con.close()
        self.assertEqual(title, "Start the engine")

    def test_imports(self):
        made = make_fixtures.exports(self.tmp / "exports")
        imports = self.corpus / "imports"
        for kind, folder in (("discord", "discord"), ("linkedin", "linkedin"), ("google_takeout", "takeout-20250301"), ("mailbox", "hotmail")):
            dest = imports / folder
            dest.mkdir(parents=True, exist_ok=True)
            src = Path(made[kind])
            (shutil.copytree if src.is_dir() else shutil.copy)(src, dest / src.name)
        (self.corpus / "identity.json").write_text(json.dumps(make_fixtures.ME))
        r = bridge(["run", "imports"], self.home, self.corpus)
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-2000:])
        m = json.loads((self.corpus / "manifest.json").read_text())
        self.assertEqual(m["discord"]["count"], 3)
        self.assertEqual(m["gmail"]["count"], 2)
        self.assertEqual(m["hotmail"]["count"], 2)
        self.assertGreaterEqual(m["linkedin"]["count"], 2)


class ResilientImportsTests(Sandbox):
    def test_one_bad_export_does_not_block_the_rest(self):
        made = make_fixtures.exports(self.tmp / "exports")
        for kind, folder in (("discord", "discord"), ("x_malformed", "x")):
            (self.corpus / "imports" / folder).mkdir(parents=True, exist_ok=True)
            shutil.copy(made[kind], self.corpus / "imports" / folder)
        (self.corpus / "identity.json").write_text(json.dumps(make_fixtures.ME))
        r = bridge(["run", "imports"], self.home, self.corpus)
        self.assertEqual(r.returncode, 1)
        ev = events(r)
        errors = {e["connector"]: e["error"] for e in ev if e["type"] == "error"}
        self.assertEqual(list(errors), ["imports:x_archive"])
        self.assertIn("KeyError", errors["imports:x_archive"])
        self.assertEqual(ev[-1], {"type": "finished", "failed": ["imports:x_archive"]})
        m = json.loads((self.corpus / "manifest.json").read_text())
        self.assertEqual(m["discord"]["count"], 3, "the good export is still imported")
        self.assertNotIn("x", m)
        # the plain imports.py would have lost everything
        r = bridge(["run", "imports", "--no-index"], self.home, self.corpus, extra_env={"UMP_PLAIN_IMPORTS": "1"})
        self.assertEqual([e["connector"] for e in events(r) if e["type"] == "error"], ["imports"])

    def _inprocess(self, body):
        """Run code against bridge.py in a fresh interpreter, with CORPUS_DIR pointed at the sandbox."""
        code = textwrap.dedent(f"""
            import json, os, sys
            os.environ["CORPUS_DIR"] = {str(self.corpus)!r}
            os.environ["UMP_REPO"] = {str(REPO)!r}
            sys.argv = ["bridge"]
            sys.path.insert(0, {str(BRIDGE.parent)!r})
            import bridge
        """) + textwrap.dedent(body)
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={**os.environ, "HOME": str(self.home)})
        if r.returncode != 0:
            raise AssertionError(r.stdout[-2000:] + r.stderr[-3000:])
        return r.stdout

    def test_a_parser_failing_halfway_keeps_the_previous_records(self):
        """The real failure: a mailbox read timed out after part of it was parsed. The source must keep its
        last complete import, not be overwritten with the part read before the error."""
        (self.corpus / "imports/hotmail").mkdir(parents=True)
        (self.corpus / "imports/hotmail/Inbox.mbox").write_text("placeholder")
        (self.corpus / "normalized").mkdir()
        old = "".join(json.dumps({"id": str(i), "source": "hotmail", "kind": "email", "text": f"old {i}"}) + "\n" for i in range(3))
        (self.corpus / "normalized/hotmail.jsonl").write_text(old)
        (self.corpus / "manifest.json").write_text(json.dumps({"hotmail": {"count": 3, "ran_at": "2026-10-01T00:00:00+00:00"}}))
        out = self._inprocess("""
            import imports
            def reads_halfway(es, W, used):
                W("hotmail").add(id="new-1", kind="email", text="first half")
                raise TimeoutError(60, "Operation timed out")
            def fine(es, W, used):
                W("fine_source").add(id="1", kind="note", text="ok")
            imports.PARSERS = [reads_halfway, fine]
            print("FAILED", json.dumps(bridge.resilient_imports(sys.__stdout__)))
        """)
        self.assertIn('FAILED ["imports:reads_halfway"]', out)
        self.assertIn("keeping the previous hotmail records", out)
        self.assertEqual((self.corpus / "normalized/hotmail.jsonl").read_text(), old)
        self.assertFalse((self.corpus / "normalized/hotmail.jsonl.tmp").exists())
        m = json.loads((self.corpus / "manifest.json").read_text())
        self.assertEqual(m["hotmail"], {"count": 3, "ran_at": "2026-10-01T00:00:00+00:00"})
        self.assertEqual(m["fine_source"]["count"], 1, "other parsers are still written")

    def test_cloud_only_exports_are_downloaded_first(self):
        (self.corpus / "imports/hotmail/Inbox.mbox").mkdir(parents=True)
        (self.corpus / "imports/hotmail/Inbox.mbox/mbox").write_text("x")
        out = self._inprocess("""
            import subprocess, time
            calls, checks = [], {"n": 0}
            real_lstat = os.lstat
            class St:
                def __init__(self, s, flags): self.s, self.st_flags = s, flags
                def __getattr__(self, k): return getattr(self.s, k)
            def lstat(p):
                st = real_lstat(p)
                if str(p).endswith("/mbox"):
                    checks["n"] += 1
                    return St(st, bridge.SF_DATALESS if checks["n"] <= 2 else 0)  # cloud-only, then downloaded
                return st
            os.lstat = lstat
            subprocess.run = lambda args, **kw: calls.append(args)
            time.sleep = lambda s: None
            print("LEFT", json.dumps(bridge.materialize(bridge.CORPUS / "imports", timeout=5)))
            print("CALLS", json.dumps(calls))
        """)
        self.assertIn("LEFT []", out)
        self.assertIn('"brctl", "download"', out)
        self.assertIn("1 export files are only in iCloud", out)

    def test_exports_that_stay_cloud_only_stop_the_import_before_anything_is_written(self):
        (self.corpus / "imports/hotmail/Inbox.mbox").mkdir(parents=True)
        (self.corpus / "imports/hotmail/Inbox.mbox/mbox").write_text("x")
        out = self._inprocess("""
            import subprocess, time
            real_lstat = os.lstat
            class St:
                def __init__(self, s): self.s, self.st_flags = s, bridge.SF_DATALESS
                def __getattr__(self, k): return getattr(self.s, k)
            os.lstat = lambda p: St(real_lstat(p)) if str(p).endswith("/mbox") else real_lstat(p)
            subprocess.run = lambda args, **kw: None
            os.environ["UMP_ICLOUD_TIMEOUT"] = "0.01"
            try:
                bridge.resilient_imports(sys.__stdout__)
            except RuntimeError as e:
                print("ERROR", e)
        """)
        self.assertIn("ERROR 1 export files are still only in iCloud (hotmail/Inbox.mbox/mbox)", out)
        self.assertFalse((self.corpus / "manifest.json").exists(), "nothing was written")

    def test_mirror_of_imports_main_is_current(self):
        """bridge.resilient_imports copies imports.main(); fail loudly if imports.main changes shape."""
        import inspect
        sys.path.insert(0, str(REPO / "connectors"))
        try:
            import imports
        finally:
            sys.path.remove(str(REPO / "connectors"))
        src = inspect.getsource(imports.main)
        for needle in ("es = entries()", "with ExitStack() as stack:", "for parser in PARSERS:", "parser(es, W, used)",
                       "accumulate=False", 'avenue = AV.get(source, f"Mailbox export (.mbox) dropped into corpus/imports/{source}/. {DROP}")'):
            self.assertIn(needle, src)
        # Newer imports.py also lists unclaimed export files at the end; the bridge calls it when it's there.
        lines = [l for l in src.strip().splitlines() if "unclaimed_ledger" not in l]
        self.assertEqual(len(lines), 19, "imports.main() changed: update bridge.resilient_imports to match")
        if "unclaimed_ledger" in src:
            self.assertIn('getattr(im, "unclaimed_ledger"', BRIDGE.read_text())


class IdentityCandidatesTests(Sandbox):
    def cands(self):
        return {(c["kind"], c["value"]): c for c in jsonout(bridge(["identity-candidates"], self.home, self.corpus))["candidates"]}

    def test_a_mac_says_who_its_owner_is(self):
        make_fixtures.home(self.home)
        c = self.cands()
        ada = c[("email", "ada@example.com")]
        self.assertTrue(ada["strong"])
        self.assertEqual({s["label"] for s in ada["sources"]}, {"Messages (iMessage address)", "Claude account"})
        self.assertIn("Apple ID", [s["label"] for s in c[("email", "ada.lovelace@icloud.example")]["sources"]])
        self.assertIn(("phone", "+14155550100"), c)
        self.assertIn(("name", "Ada Lovelace"), c)
        self.assertFalse(any(s["label"] == "Mac user account" for x in c.values() for s in x["sources"]), "a test HOME isn't this account")

    def test_exports_add_what_they_state(self):
        made = make_fixtures.exports(self.tmp / "exports")
        for kind, folder in (("linkedin_nested", "linkedin"), ("discord", "discord"), ("x", "x")):
            (self.corpus / "imports" / folder).mkdir(parents=True, exist_ok=True)
            shutil.copy(made[kind], self.corpus / "imports" / folder)
        c = self.cands()
        self.assertEqual([s["label"] for s in c[("email", "ada.work@example.com")]["sources"]], ["LinkedIn export"])
        self.assertIn(("name", "Ada Lovelace"), c)
        self.assertEqual({s["label"] for s in c[("username", "ada_l")]["sources"]}, {"Discord export", "X export"})

    def test_mailboxes_reveal_their_owner(self):
        con = sqlite3.connect(self.corpus / "corpus.db")
        con.execute("create table records (source text, id text, kind text, ts text, meta text)")
        rows = [("gmail", str(i), "email", None, json.dumps({"from": "Ada <Ada@Example.com>", "to": ["bob@example.com"], "labels": "Sent,Opened"})) for i in range(6)]
        rows += [("gmail", f"in{i}", "email", None, json.dumps({"from": "Bob <bob@example.com>", "to": ["ada@example.com"], "labels": "Inbox"})) for i in range(20)]
        rows += [("hotmail", f"h{i}", "email", None, json.dumps({"from": f"x{i}@example.com", "to": ["ada.old@hotmail.example", "z@example.com"], "folder": "Inbox"})) for i in range(10)]
        con.executemany("insert into records values (?,?,?,?,?)", rows)
        con.commit()
        con.close()
        c = self.cands()
        self.assertEqual(c[("email", "ada@example.com")]["sources"], [{"label": "Gmail: sent mail", "count": 6}])
        self.assertEqual(c[("email", "ada.old@hotmail.example")]["sources"][0]["label"], "Hotmail: receives the mail")
        self.assertNotIn(("email", "bob@example.com"), c, "the people you write to aren't you")

    def test_the_person_in_every_chat_is_the_owner(self):
        con = sqlite3.connect(self.corpus / "corpus.db")
        con.execute("create table records (source text, id text, kind text, ts text, meta text, author text, thread text)")
        rows = []
        for t in range(5):  # Ada (under an old display name) is in all five chats; Charles in two
            rows.append(("google_chat", f"a{t}", "message", None, "{}", "Ada L. (old)", f"t{t}"))
            if t < 2:
                rows.append(("google_chat", f"c{t}", "message", None, "{}", "Charles", f"t{t}"))
        rows.append(("whatsapp_export", "w1", "message", None, "{}", "Ada", "only-one-chat"))
        con.executemany("insert into records values (?,?,?,?,?,?,?)", rows)
        con.commit()
        con.close()
        c = self.cands()
        self.assertEqual(c[("name", "Ada L. (old)")]["sources"], [{"label": "Google Chat: in 5 of 5 chats"}])
        self.assertNotIn(("name", "Charles"), c)
        self.assertNotIn(("name", "Ada"), c, "one chat says nothing about who owns the export")

    def test_normalization(self):
        sys.path.insert(0, str(BRIDGE.parent))
        import bridge as b
        n = b.Candidates.norm
        self.assertEqual(n("email", "Ada <ADA@Example.com>"), "ada@example.com")
        self.assertEqual(n("phone", "(415) 555-0100"), "+14155550100")
        self.assertEqual(n("phone", "+44 20 7946 0958"), "+442079460958")
        self.assertIsNone(n("phone", "123"))
        self.assertEqual(n("username", "@Ada_L"), "ada_l")
        self.assertIsNone(n("name", "ada@example.com"), "an address isn't a name")


class IdentityAndIcloudTests(Sandbox):
    def test_write_identity(self):
        out = jsonout(bridge(["write-identity"], self.home, self.corpus, stdin=json.dumps(
            {"names": [" Ada Lovelace ", ""], "emails": ["ada@example.com"], "usernames": [], "extra": ["x"]})))
        self.assertEqual(out, {"names": ["Ada Lovelace"], "emails": ["ada@example.com"], "usernames": [], "phones": []})
        self.assertEqual(json.loads((self.corpus / "identity.json").read_text()), out)

    def test_exclude_icloud(self):
        (self.corpus / "normalized").mkdir()
        (self.corpus / "normalized/a.jsonl").write_text("{}\n")
        r = jsonout(bridge(["exclude-icloud"], self.home, self.corpus))
        self.assertTrue(r["ok"])
        self.assertTrue(self.corpus.is_symlink())
        self.assertEqual(os.readlink(self.corpus), "corpus.nosync")
        self.assertEqual((self.corpus / "normalized/a.jsonl").read_text(), "{}\n", "the old path still works")
        again = jsonout(bridge(["exclude-icloud"], self.home, self.corpus))
        self.assertTrue(again["already"])

    def test_exclude_icloud_refuses_cloud_only_files(self):
        (self.corpus / "a.txt").write_text("x")
        code = textwrap.dedent(f"""
            import json, os, sys
            os.environ["CORPUS_DIR"] = {str(self.corpus)!r}
            sys.argv = ["bridge"]
            sys.path.insert(0, {str(BRIDGE.parent)!r})
            import bridge
            real = os.lstat
            class St:
                def __init__(self, s): self.s = s
                def __getattr__(self, k): return getattr(self.s, k)
                st_flags = bridge.SF_DATALESS
            os.lstat = lambda p: St(real(p))
            print(json.dumps(bridge.exclude_icloud()))
        """)
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={**os.environ, "HOME": str(self.home), "UMP_REPO": str(REPO)})
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertFalse(out["ok"])
        self.assertIn("only in iCloud", out["error"])
        self.assertFalse(self.corpus.is_symlink())

    def test_exclude_icloud_target_exists(self):
        (self.tmp / "corpus.nosync").mkdir()
        r = jsonout(bridge(["exclude-icloud"], self.home, self.corpus))
        self.assertFalse(r["ok"])
        self.assertIn("already exists", r["error"])


if __name__ == "__main__":
    unittest.main()


class PhoneNotYoursTests(Sandbox):
    """Several devices backed up here: each backup says which device it is, and what was read from one that isn't
    yours comes out of the library, leaving what this Mac had."""

    def test_each_backup_names_its_device(self):
        make_fixtures.backup(self.home)
        b = jsonout(bridge(["probe"], self.home, self.corpus))["backups"][0]
        self.assertEqual(b["udid"], "00008120-TEST", "no Target Identifier: the folder's name")

    def test_forget_phone(self):
        norm = self.corpus / "normalized"
        norm.mkdir()
        rec = lambda src, i, copy=None, kind="message": json.dumps({"id": str(i), "source": src, "kind": kind, "ts": f"2026-0{i}-01T00:00:00Z",
                                                                    **({"meta": {"copy": copy}} if copy else {})})
        (norm / "imessage.jsonl").write_text("\n".join([rec("imessage", 1, "mac"), rec("imessage", 2, "iphone"), rec("imessage", 3, "iphone")]) + "\n")
        (norm / "calls.jsonl").write_text(rec("calls", 4, "iphone", "call") + "\n")
        for src in ("phone_whatsapp", "health", "iphone_contacts", "photos"):
            (norm / f"{src}.jsonl").write_text(rec(src, 5, kind="record") + "\n")
        manifest = {s: {"count": 1} for s in ("phone_whatsapp", "health", "iphone_contacts", "photos", "calls")}
        manifest["imessage"] = {"count": 3, "kinds": {"message": 3}}
        (self.corpus / "manifest.json").write_text(json.dumps(manifest))
        mirror = self.corpus / "raw/iphone"
        (mirror / "files/HomeDomain").mkdir(parents=True)
        (mirror / "files/HomeDomain/sms.db").write_text("x")
        (mirror / "backup.json").write_text("{}")
        r = jsonout(bridge(["forget-phone"], self.home, self.corpus))
        self.assertEqual(r["removed"], {"phone_whatsapp": 1, "health": 1, "iphone_contacts": 1, "imessage": 2, "calls": 1})
        self.assertEqual([json.loads(l)["id"] for l in (norm / "imessage.jsonl").read_text().splitlines()], ["1"], "the Mac's own stays")
        self.assertEqual((norm / "calls.jsonl").read_text(), "")
        self.assertTrue((norm / "photos.jsonl").exists(), "not from the phone")
        m = json.loads((self.corpus / "manifest.json").read_text())
        self.assertEqual(sorted(m), ["calls", "imessage", "photos"])
        self.assertEqual((m["imessage"]["count"], m["imessage"]["kinds"], m["imessage"]["first"]), (1, {"message": 1}, "2026-01-01T00:00:00Z"))
        self.assertFalse((mirror / "files").exists())
        self.assertFalse((mirror / "backup.json").exists())
        self.assertEqual([p.name for p in norm.iterdir() if p.name.endswith(".tmp")], [], "its own temp names, none left")

    def test_forget_phone_as_a_queued_run_then_the_index(self):
        """The app runs it as a job of its queue (index --forget-phone), so no iPhone read writes the same files meanwhile:
        one JSON event per line, then the index rebuilt."""
        norm = self.corpus / "normalized"
        norm.mkdir()
        (norm / "phone_notes.jsonl").write_text(json.dumps({"id": "1", "source": "phone_notes", "kind": "note", "text": "x"}) + "\n")
        (norm / "calls.jsonl").write_text(json.dumps({"id": "2", "source": "calls", "kind": "call", "meta": {"copy": "mac"}}) + "\n")
        (self.corpus / "manifest.json").write_text('{"phone_notes": {"count": 1}, "calls": {"count": 1}, "cut sh')  # cut short by a crash
        r = bridge(["index", "--forget-phone"], self.home, self.corpus)
        self.assertEqual(r.returncode, 0, r.stderr)
        evs = events(r)
        self.assertEqual(evs[-1], {"type": "finished", "failed": []})
        self.assertTrue(any(e.get("connector") == "forget-phone" and "Taken out" in e.get("line", "") for e in evs))
        self.assertFalse((norm / "phone_notes.jsonl").exists())
        self.assertTrue((self.corpus / "corpus.db").exists())
        self.assertNotIn("phone_notes", json.loads((self.corpus / "manifest.json").read_text()), "a manifest that can't be read starts over")
