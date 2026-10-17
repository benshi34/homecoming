"""signins.py: which services Chrome and Safari are signed in to, from made-up cookie files. Values never come out."""

import datetime as dt
import json
import os
import sqlite3
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "py"))
import signins  # noqa: E402

NOW = dt.datetime(2026, 10, 16, 12, tzinfo=dt.timezone.utc)
COLS = ["creation_utc", "host_key", "top_frame_site_key", "name", "value", "encrypted_value", "path", "expires_utc", "is_secure", "is_httponly",
        "last_access_utc", "has_expires", "is_persistent", "priority", "samesite", "source_scheme", "source_port", "last_update_utc"]


def chrome_us(d):
    return int((d - signins.CHROME_EPOCH).total_seconds() * 1_000_000)


def chrome_profile(root, folder, name, cookies, claude=False, network=False):
    d = root / folder
    db = d / ("Network/Cookies" if network else "Cookies")
    db.parent.mkdir(parents=True)
    if claude:
        (d / "Extensions" / signins.CLAUDE_EXTENSION / "1.0").mkdir(parents=True)
    con = sqlite3.connect(db)
    con.execute(f"create table cookies ({', '.join(COLS)})")
    for host, cname, expires, updated in cookies:
        row = dict.fromkeys(COLS, 0) | {"host_key": host, "name": cname, "value": "", "encrypted_value": b"v10secret", "path": "/",
                                        "expires_utc": chrome_us(expires) if expires else 0, "has_expires": 1 if expires else 0,
                                        "creation_utc": chrome_us(updated), "last_update_utc": chrome_us(updated)}
        con.execute(f"insert into cookies ({', '.join(row)}) values ({', '.join('?' * len(row))})", list(row.values()))
    con.commit()
    con.close()
    return name


def binarycookies(cookies):
    """Safari's Cookies.binarycookies: one page of cookies (site, name, path, value; expiry and creation in Mac time)."""
    blobs = []
    for site, name, value, expires in cookies:
        strings = b""
        offs = []
        for s in (site, name, "/", value):
            offs.append(56 + len(strings))
            strings += s.encode() + b"\0"
        body = struct.pack("<IIII", 56 + len(strings), 1, 0, 0) + struct.pack("<IIII", *offs) + b"\0" * 8 \
            + struct.pack("<dd", (expires - signins.MAC_EPOCH).total_seconds(), 0) + strings
        blobs.append(body)
    head = struct.pack("<I", 0x100) + struct.pack("<I", len(blobs))
    offs, at = [], len(head) + 4 * len(blobs) + 4
    for b in blobs:
        offs.append(at)
        at += len(b)
    page = head + struct.pack(f"<{len(blobs)}I", *offs) + b"\0\0\0\0" + b"".join(blobs)
    return b"cook" + struct.pack(">I", 1) + struct.pack(">I", len(page)) + page


class SignInsTest(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.home = Path(t.name)
        self.chrome = self.home / "Library/Application Support/Google/Chrome"
        self.chrome.mkdir(parents=True)
        p = patch.dict(os.environ, {"HOME": str(self.home)})
        p.start()
        self.addCleanup(p.stop)

    def test_chrome_profiles_and_safari_from_names_and_dates_only(self):
        later, old = NOW + dt.timedelta(days=90), NOW - dt.timedelta(days=1)
        chrome_profile(self.chrome, "Default", "Riley", [(".instagram.com", "sessionid", later, NOW), (".instagram.com", "csrftoken", later, NOW),
                                                          (".x.com", "auth_token", old, old), ("chatgpt.com", "__Secure-next-auth.session-token.0", None, NOW)],
                       claude=True)
        chrome_profile(self.chrome, "Profile 1", "Work", [(".spotify.com", "sp_dc", later, NOW)], network=True)
        (self.chrome / "Local State").write_text(json.dumps({"profile": {"info_cache": {"Default": {"name": "Riley", "user_name": "riley@example.com"},
                                                                                           "Profile 1": {"name": "Work"}}}}))
        safari = self.home / "Library/Containers/com.apple.Safari/Data/Library/Cookies/Cookies.binarycookies"
        safari.parent.mkdir(parents=True)
        safari.write_bytes(binarycookies([(".x.com", "auth_token", "secret-value", later), (".reddit.com", "reddit_session", "s", later)]))
        asked = [{"id": "instagram", "domains": ["instagram.com"], "cookies": ["sessionid"]},
                 {"id": "x", "domains": ["x.com", "twitter.com"], "cookies": ["auth_token"]},
                 {"id": "chatgpt", "domains": ["chatgpt.com"], "cookies": ["__Secure-next-auth.session-token*"]},
                 {"id": "spotify", "domains": ["spotify.com"], "cookies": ["sp_dc"]},
                 {"id": "reddit", "domains": ["reddit.com"], "cookies": ["reddit_session"]}]
        r = signins.signins(asked, NOW)
        self.assertEqual([(p["dir"], p["name"], p["email"], p["claude"]) for p in r["chrome"]["profiles"]],
                         [("Default", "Riley", "riley@example.com", True), ("Profile 1", "Work", None, False)])
        s = r["sources"]
        self.assertEqual([c["profile"] for c in s["instagram"]["chrome"]], ["Default"])
        self.assertTrue(s["instagram"]["chrome"][0]["until"].startswith("2027-01-14"))
        self.assertEqual(s["x"]["chrome"], [], "an expired session is no sign-in")
        self.assertTrue(s["x"]["safari"], "but Safari has one")
        self.assertEqual(s["chatgpt"]["chrome"][0]["until"], None, "a cookie for this browsing session only, matched by prefix")
        self.assertEqual([c["profile"] for c in s["spotify"]["chrome"]], ["Profile 1"], "the newer Network/Cookies place")
        self.assertTrue(s["reddit"]["safari"] and not s["reddit"]["chrome"])
        self.assertTrue(r["safari"]["readable"])
        self.assertNotIn("secret", json.dumps(r), "no cookie value comes out")

    def test_a_file_it_cant_read_is_cant_tell_and_an_impossible_date_is_skipped(self):
        later = NOW + dt.timedelta(days=90)
        chrome_profile(self.chrome, "Default", "Riley", [(".x.com", "auth_token", later, NOW)], claude=True)
        (self.chrome / "Default/Cookies").write_bytes(b"SQLite format 3\0" + b"\xff" * 4000)  # caught mid-write
        safari = self.home / "Library/Containers/com.apple.Safari/Data/Library/Cookies/Cookies.binarycookies"
        safari.parent.mkdir(parents=True)
        data = bytearray(binarycookies([(".x.com", "auth_token", "v", later), (".reddit.com", "reddit_session", "v", later)]))
        first = data.find(b".x.com") - 56  # the first cookie's start: its expiry, made impossible
        data[first + 40:first + 48] = struct.pack("<d", float("inf"))
        safari.write_bytes(bytes(data))
        with patch.object(signins.time, "sleep", lambda s: None):
            r = signins.signins([{"id": "x", "domains": ["x.com"], "cookies": ["auth_token"]},
                                 {"id": "reddit", "domains": ["reddit.com"], "cookies": ["reddit_session"]}], NOW)
        self.assertEqual(r["sources"]["x"], {"chrome": [], "safari": False, "unreadable": ["Default"]}, "not signed out: can't tell")
        self.assertTrue(r["sources"]["reddit"]["safari"], "the rest of Safari's file is still read")

    def test_the_browser_do_it_for_me_works_in(self):
        # Your Setup picked Arc: its profiles are read, in Chrome's format at its own folder; Chrome's aren't.
        later = NOW + dt.timedelta(days=90)
        chrome_profile(self.chrome, "Default", "Chrome one", [(".x.com", "auth_token", later, NOW)], claude=True)
        arc = self.home / "Library/Application Support/Arc/User Data"
        chrome_profile(arc, "Default", "Arc one", [(".instagram.com", "sessionid", later, NOW)], claude=True)
        opera = self.home / "Library/Application Support/com.operasoftware.Opera"
        opera.mkdir(parents=True)
        sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "connectors"))
        asked = [{"id": "x", "domains": ["x.com"], "cookies": ["auth_token"]}, {"id": "instagram", "domains": ["instagram.com"], "cookies": ["sessionid"]}]
        with patch.dict(os.environ, {"UMP_AGENT_BROWSER": "arc"}):
            r = signins.signins(asked, NOW)
        self.assertEqual([c["profile"] for c in r["sources"]["instagram"]["chrome"]], ["Default"])
        self.assertEqual(r["sources"]["x"]["chrome"], [], "Chrome's sign-ins aren't Arc's")
        self.assertEqual([p["claude"] for p in r["chrome"]["profiles"]], [True])
        # Opera keeps its one profile in its data folder itself.
        con = sqlite3.connect(opera / "Cookies")
        con.execute(f"create table cookies ({', '.join(COLS)})")
        con.close()
        with patch.dict(os.environ, {"UMP_AGENT_BROWSER": "opera"}):
            self.assertIn("Default", [p["dir"] for p in signins.chrome_profiles()])

    def test_nothing_there(self):
        (self.chrome / "Local State").unlink(missing_ok=True)
        self.chrome.rmdir()
        r = signins.signins([{"id": "x", "domains": ["x.com"], "cookies": ["auth_token"]}], NOW)
        self.assertEqual(r, {"chrome": {"installed": False, "profiles": []}, "safari": {"readable": False}, "sources": {"x": {"chrome": [], "safari": False}}})


if __name__ == "__main__":
    unittest.main()
