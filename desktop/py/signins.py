"""Which services this Mac's browsers are signed in to, for Do It for Me: from the names and expiry dates of their
session cookies, never their values. Chrome keeps each cookie's site, name and dates in plain columns (only the value
is encrypted), so nothing is decrypted and no Keychain prompt appears; Safari's cookie file (it needs Full Disk Access)
is read the same way, its values skipped over. Only the sites asked about are looked at, and nothing is kept.

    signins([{"id": "instagram", "domains": ["instagram.com"], "cookies": ["sessionid"]}, ...])

A cookie name ending in * matches by prefix (ChatGPT splits its session cookie into .0, .1). Chrome profiles say whether
the Claude in Chrome extension is in them: that's the profile Do It for Me works in.

"Chrome" here is the browser Do It for Me works in: Chrome, or the one picked in Your Setup (UMP_AGENT_BROWSER, a
connectors/browsers.py id). Edge, Brave, Arc, Vivaldi and Opera keep Chrome's cookie file, at their own folder."""

import datetime as dt
import json
import os
import sqlite3
import struct
import time
from pathlib import Path
from urllib.parse import quote

CLAUDE_EXTENSION = "fcoeoabgfenejglbffodgkkbkcdhcgfn"  # Claude in Chrome, as the Chrome Web Store lists it
UTC = dt.timezone.utc
CHROME_EPOCH = dt.datetime(1601, 1, 1, tzinfo=UTC)
MAC_EPOCH = dt.datetime(2001, 1, 1, tzinfo=UTC)


def chrome_dir():
    """The data folder of the browser Do It for Me works in (Chrome unless Your Setup picked another Chromium one)."""
    pick = os.environ.get("UMP_AGENT_BROWSER")
    if pick and pick != "chrome":
        try:
            import browsers
            b = browsers.BY_ID.get(pick)
            if b and b[4] == "chromium":
                return Path.home() / b[5].relative_to(browsers.HOME)  # this home's, whenever browsers.py was imported
        except ImportError:  # run without connectors/ on the path
            pass
    return Path.home() / "Library/Application Support/Google/Chrome"


def safari_file():
    return Path.home() / "Library/Containers/com.apple.Safari/Data/Library/Cookies/Cookies.binarycookies"


def _site(host, domains):
    host = (host or "").lstrip(".").lower()
    return any(host == d or host.endswith("." + d) for d in domains)


def _named(name, names):
    return any(name == n or (n.endswith("*") and name.startswith(n[:-1])) for n in names)


def _chrome_time(us):
    return (CHROME_EPOCH + dt.timedelta(microseconds=us)).isoformat() if us else None


def chrome_profiles():
    """Chrome's profiles that have a cookie file: folder, the name Chrome shows, the Google account, and whether
    Claude in Chrome is installed in it."""
    root = chrome_dir()
    try:
        info = json.loads((root / "Local State").read_text())["profile"]["info_cache"]
    except (OSError, KeyError, ValueError, TypeError):
        info = {}
    out = []
    # Opera keeps its one profile in the data folder itself.
    for d in ([root] if (root / "Cookies").is_file() or (root / "Network/Cookies").is_file() else []) + (sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []):
        db = next((x for x in (d / "Network/Cookies", d / "Cookies") if x.is_file()), None)
        if not db:
            continue
        i = info.get(d.name) or {}
        out.append({"dir": d.name if d != root else "Default", "name": i.get("name") or (d.name if d != root else "Default"), "email": i.get("user_name") or None,
                    "claude": (d / "Extensions" / CLAUDE_EXTENSION).is_dir(), "db": db})
    return out


def chrome_cookies(db, domains):
    """(site, name, expires, updated) for the cookies on these sites. Read in place and read-only, without a lock
    (immutable): a running Chrome doesn't stop it, and no copy of the file is made. Values are never selected.
    None when it couldn't be read (caught mid-write three times): that's "can't tell", not "signed out"."""
    where = " or ".join(["host_key = ? or host_key = ? or host_key like ?"] * len(domains))
    args = [x for d in domains for x in (d, "." + d, "%." + d)]
    for attempt in range(3):  # Chrome can be mid-write: a moment later
        try:
            con = sqlite3.connect(f"file:{quote(str(db))}?mode=ro&immutable=1", uri=True)
            try:
                cols = {r[1] for r in con.execute("pragma table_info(cookies)")}
                updated = "last_update_utc" if "last_update_utc" in cols else "creation_utc"
                return con.execute(f"select host_key, name, case when has_expires then expires_utc else 0 end, {updated} "
                                   f"from cookies where {where}", args).fetchall()
            finally:
                con.close()
        except sqlite3.DatabaseError:
            time.sleep(0.3)
    return None


def _cstr(b, at):
    end = b.find(b"\0", at)
    return b[at:end if end >= 0 else len(b)].decode("utf-8", "replace")


def safari_cookies(domains, path=None):
    """(site, name, expires) for Safari's cookies on these sites, from Cookies.binarycookies (pages of cookies, each
    with offsets to its strings: the value's is skipped). None when it can't be read (no Full Disk Access, no Safari)."""
    try:
        data = (path or safari_file()).read_bytes()
    except OSError:
        return None
    if data[:4] != b"cook" or len(data) < 8:
        return None
    out = []
    try:
        pages = struct.unpack(">I", data[4:8])[0]
        sizes = struct.unpack(f">{pages}I", data[8:8 + 4 * pages])
        at = 8 + 4 * pages
        for size in sizes:
            page, at = data[at:at + size], at + size
            count = struct.unpack("<I", page[4:8])[0]
            for start in struct.unpack(f"<{count}I", page[8:8 + 4 * count]):
                c = page[start:]
                if len(c) < 56:
                    continue
                site_at, name_at = struct.unpack("<II", c[16:24])
                site = _cstr(c, site_at)
                if not _site(site, domains):
                    continue
                try:
                    expires = struct.unpack("<d", c[40:48])[0]
                    until = (MAC_EPOCH + dt.timedelta(seconds=expires)).isoformat() if expires else None
                except (OverflowError, ValueError):
                    continue  # a date out of any range (or not a number): not one to go by
                out.append((site, _cstr(c, name_at), until))
    except struct.error:
        pass  # a file cut short: what was read so far
    return out


def signins(asked, now=None):
    now = now or dt.datetime.now(UTC)
    profiles = chrome_profiles()
    live = lambda until: not until or dt.datetime.fromisoformat(until) > now
    sources = {}
    every = sorted({d for a in asked for d in a.get("domains", [])})
    rows = {p["dir"]: chrome_cookies(p["db"], every) if every else [] for p in profiles}
    unreadable = [d for d, r in rows.items() if r is None]
    safari = safari_cookies(every) if every else None
    for a in asked:
        domains, names = a.get("domains", []), a.get("cookies", [])
        chrome = []
        for p in profiles:
            hits = [(_chrome_time(exp), _chrome_time(upd)) for host, name, exp, upd in rows[p["dir"]] or []
                    if _site(host, domains) and _named(name, names) and live(_chrome_time(exp))]
            if hits:
                chrome.append({"profile": p["dir"], "until": max((h[0] for h in hits if h[0]), default=None),
                               "since": max((h[1] for h in hits if h[1]), default=None)})
        sources[a["id"]] = {"chrome": chrome, "safari": any(_site(s, domains) and _named(n, names) and live(u) for s, n, u in safari or [])}
        if unreadable and not chrome:
            sources[a["id"]]["unreadable"] = unreadable  # not found, but a profile couldn't be read: can't tell
    return {"chrome": {"installed": chrome_dir().is_dir(), "profiles": [{k: v for k, v in p.items() if k != "db"} for p in profiles]},
            "safari": {"readable": safari is not None}, "sources": sources}
