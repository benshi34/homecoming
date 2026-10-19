"""Browsing history from every browser on this Mac (browsers.py): Safari, Chrome and the other Chromium browsers
(Arc, Edge, Brave, Vivaldi, Opera...), Firefox and Zen. Pages, search queries, YouTube watches and Maps lookups."""

import datetime as dt
import json
import plistlib
import re
import sqlite3
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import browsers
from common import HOME, UTC, Writer, columns, connect, from_apple, from_webkit, snapshot_sqlite

AVENUE = ("Local SQLite. Safari: ~/Library/Safari/History.db (needs Full Disk Access; includes other "
          "devices' visits when iCloud Safari sync is on, origin=1). Chrome and every Chromium browser (Arc, Edge, "
          "Brave, Vivaldi, Opera...): <data folder>/<profile>/History (locked while the browser runs, so copied "
          "first; Chrome keeps ~90 days locally, older history only via Google Takeout). Firefox and Zen: "
          "Profiles/<profile>/places.sqlite. Searches come from Chromium's keyword_search_terms and search-engine "
          "URLs. Browsers the person turned off in Your Setup (UMP_BROWSERS_SKIP) aren't read. Safari's other profiles: "
          "~/Library/Containers/com.apple.Safari/Data/Library/Safari/Profiles/<id>/History.db, named from SafariTabs.db. A "
          "Chromium visit synced from another device (visits.originator_cache_guid) is meta.other_device. A profile whose "
          "history can't be read is named in the manifest (notes.unreadable) and the rest are read; one locked mid-write is "
          "read as it was before that write.")

SEARCH_HOSTS = {"www.google.com": "q", "google.com": "q", "www.bing.com": "q", "duckduckgo.com": "q",
                "www.youtube.com": "search_query", "search.yahoo.com": "p", "www.perplexity.ai": "q",
                # the engines other browsers start with: Brave's, Ecosia, Kagi (Orion)
                "search.brave.com": "q", "www.ecosia.org": "q", "kagi.com": "q"}
GOOGLE = re.compile(r"^(www\.)?google\.(co\.)?[a-z]{2,3}(\.[a-z]{2})?$")  # google.co.uk, google.ca, google.com.au...
SUBFRAME = {3, 4}


def classify(url):
    """Return (tag, query) for search / youtube / maps URLs."""
    try:
        u = urlparse(url)
    except ValueError:
        return None, None
    host, path = u.netloc.lower(), u.path
    qs = parse_qs(u.query)
    param = SEARCH_HOSTS.get(host) or ("q" if GOOGLE.match(host) else None)
    if param and ("/search" in path or "/results" in path or host == "duckduckgo.com"):
        q = qs.get(param, [None])[0]
        if q:
            return ("youtube_search" if "youtube" in host else "search"), q
    if "youtube.com" in host and path == "/watch" or host == "youtu.be":
        return "youtube_watch", None
    if host.startswith("www.google.") and path.startswith("/maps") or host == "maps.google.com" or host == "maps.apple.com":
        place = path.split("/place/")[1].split("/")[0].replace("+", " ") if "/place/" in path else qs.get("q", [None])[0]
        return "maps", place
    return None, None


def chromium_profiles(bid):
    """(folder, the profile's own name, History file) for each profile of a Chromium browser."""
    root = browsers.BY_ID[bid][5]
    try:
        info = json.loads((root / "Local State").read_text())["profile"]["info_cache"]
    except (OSError, KeyError, ValueError, TypeError):
        info = {}
    for pdir, path in browsers.history_files(bid):
        yield pdir, (info.get(pdir) or {}).get("name", pdir), path


# Firefox visit types that aren't the person going to a page: embedded frames (4, 8) and downloads (7).
FIREFOX_SKIP = {4, 7, 8}


def add_visit(w, rid, browser, profile, ts, url, title, meta, name):
    tag, q = classify(url)
    if tag in ("search", "youtube_search") and q:
        w.add(id=f"{rid}:q", kind="search", ts=ts, author="me", is_me=True, thread=f"{browser}:{profile}",
              thread_name=f"{name} ({profile})", title=q, text=q, url=url,
              meta={"engine": urlparse(url).netloc, "youtube": tag == "youtube_search" or None, **meta})
        return
    text = "\n".join(x for x in (title, url) if x)
    if tag == "maps" and q:
        text = f"Maps: {q}\n{text}"
    w.add(id=rid, kind="visit", ts=ts, author="me", is_me=True, thread=f"{browser}:{profile}",
          thread_name=f"{name} ({profile})", title=title, text=text, url=url,
          meta={"tag": tag, **meta} if tag else meta)


def unreadable(w, profile):
    """A profile whose history can't be read (a file never written, or not a database): the others are read, and the
    manifest names it."""
    w.notes["unreadable"] = sorted({*w.notes.get("unreadable", []), profile})


def add_chromium(w, bid, ws, renamed):
    for pdir, pname, path in chromium_profiles(bid):
        try:
            add_chromium_profile(w, bid, ws, renamed, pdir, pname, path)
        except (sqlite3.Error, OSError):
            unreadable(w, f"{bid}:{pdir}")


def add_chromium_profile(w, bid, ws, renamed, pdir, pname, path):
    name = browsers.BY_ID[bid][1]
    chromium_bookmarks(ws, bid, pdir, pname, path, name)  # a file of their own: read whatever the history's state
    # Chrome's files and ids are as they always were; every other browser's are named after it.
    con = connect(snapshot_sqlite(path, f"browser/{bid}_{pdir.replace(' ', '_')}_History"))
    visits = columns(con, "visits")
    if not visits:
        raise sqlite3.OperationalError("no visits table")
    chromium_downloads(ws, con, bid, pdir, pname, name, renamed)
    try:
        terms = {r["url_id"]: r["term"] for r in con.execute("select url_id, term from keyword_search_terms")}
    except Exception:  # a browser without the table
        terms = {}
    # A visit synced from another device signed in to the same account has the device's sync id (empty for this one's).
    synced = "v.originator_cache_guid" if "originator_cache_guid" in visits else "null"
    for r in con.execute(f"""select v.id, v.visit_time, v.transition, v.visit_duration, u.id url_id,
                                    u.url, u.title, u.visit_count, {synced} synced
                             from visits v join urls u on u.id = v.url"""):
        if ((r["transition"] or 0) & 0xFF) in SUBFRAME:
            continue
        meta = {"seconds": round((r["visit_duration"] or 0) / 1e6) or None, "visit_count": r["visit_count"],
                "other_device": True if r["synced"] else None}
        rid = f"{bid}:{pdir}:{r['id']}"
        ts = from_webkit(r["visit_time"])
        term = terms.get(r["url_id"])
        if term and not classify(r["url"])[1]:
            w.add(id=f"{rid}:q", kind="search", ts=ts, author="me", is_me=True, thread=f"{bid}:{pname}",
                  thread_name=f"{name} ({pname})", title=term, text=term, url=r["url"],
                  meta={"engine": urlparse(r["url"]).netloc})
            continue
        add_visit(w, rid, bid, pname, ts, r["url"], r["title"], {k: v for k, v in meta.items() if v}, name)


def add_firefox(w, bid, ws):
    for pdir, path in browsers.history_files(bid):
        try:
            add_firefox_profile(w, bid, ws, pdir, path)
        except (sqlite3.Error, OSError):
            unreadable(w, f"{bid}:{pdir}")


def add_firefox_profile(w, bid, ws, pdir, path):
    name = browsers.BY_ID[bid][1]
    con = connect(snapshot_sqlite(path, f"browser/{bid}_{pdir.replace(' ', '_')}_places.sqlite"))
    firefox_bookmarks(ws, bid, pdir, con, name)
    pname = pdir.split(".", 1)[-1]  # "abcd1234.default-release" -> "default-release"
    for r in con.execute("""select v.id, v.visit_date, v.visit_type, p.url, p.title, p.visit_count
                            from moz_historyvisits v join moz_places p on p.id = v.place_id"""):
        if r["visit_type"] in FIREFOX_SKIP or not r["visit_date"]:
            continue
        ts = (dt.datetime(1970, 1, 1, tzinfo=UTC) + dt.timedelta(microseconds=r["visit_date"])).isoformat().replace("+00:00", "Z")
        add_visit(w, f"{bid}:{pdir}:{r['id']}", bid, pname, ts, r["url"], r["title"],
                  {"visit_count": r["visit_count"]} if r["visit_count"] else {}, name)


# What you kept in each browser besides its history (browser_saved): bookmarks and Safari's Reading List, downloads,
# and the tabs open on your other devices (Safari's iCloud Tabs).
SAFARI_TABS = HOME / "Library/Containers/com.apple.Safari/Data/Library/Safari/CloudTabs.db"


def chromium_bookmarks(ws, bid, pdir, pname, path, name):
    f = Path(path).parent / "Bookmarks"
    try:
        roots = json.loads(f.read_text()).get("roots", {})
    except (OSError, ValueError):
        return
    def walk(node, folder):
        if node.get("type") == "url":
            ws.add(id=f"{bid}:{pdir}:bookmark:{node.get('guid') or node.get('id')}", kind="bookmark", ts=from_webkit(int(node.get("date_added") or 0) or None),
                   author="me", is_me=True, thread=f"{bid}:{pname}", thread_name=f"{name} ({pname})", title=node.get("name"),
                   text="\n".join(x for x in (node.get("name"), node.get("url")) if x), url=node.get("url"),
                   meta={k: v for k, v in (("folder", folder or None), ("last_used", from_webkit(int(node.get("date_last_used") or 0) or None))) if v})
        for c in node.get("children") or []:
            walk(c, "/".join(x for x in (folder, node.get("name")) if x) if node.get("type") == "folder" and node.get("name") else folder)
    for key, root in roots.items():
        if isinstance(root, dict):  # the root's own name is the label below, in plain words
            for c in root.get("children") or []:
                walk(c, {"bookmark_bar": "Bookmarks bar", "other": "Other bookmarks", "synced": "Mobile bookmarks"}.get(key, ""))


def chromium_downloads(ws, con, bid, pdir, pname, name, renamed):
    """Each download, by Chrome's guid for it: its row number starts again from 1 once download history is cleared, so
    a later download would take an earlier one's place. An earlier run's record by row number of the same download (same
    row, same time) goes in `renamed`, so it isn't kept as a second copy."""
    try:
        chains = {}
        for r in con.execute("select id, url from downloads_url_chains order by id, chain_index"):
            chains[r["id"]] = r["url"]  # the last in its chain: where the file came from
        guid = "guid" if "guid" in columns(con, "downloads") else "null guid"
        rows = con.execute(f"select id, {guid}, target_path, start_time, total_bytes, state, mime_type, referrer, tab_url "
                           "from downloads").fetchall()
    except Exception:  # a browser without the tables
        return
    for r in rows:
        file = (r["target_path"] or "").rsplit("/", 1)[-1]
        if not file:
            continue
        ts = from_webkit(r["start_time"])
        if r["guid"]:
            renamed[f"{bid}:{pdir}:download:{r['id']}"] = ts
        ws.add(id=f"{bid}:{pdir}:download:{r['guid'] or r['id']}", kind="download", ts=ts, author="me", is_me=True,
               thread=f"{bid}:{pname}", thread_name=f"{name} ({pname})", title=file,
               text="\n".join(x for x in (file, chains.get(r["id"]), r["tab_url"]) if x), url=chains.get(r["id"]),
               meta={k: v for k, v in (("bytes", r["total_bytes"] or None), ("mime", r["mime_type"] or None), ("from_page", r["tab_url"] or r["referrer"] or None),
                                       ("finished", r["state"] == 1 or None)) if v})


def safari_saved(ws):
    try:
        root = plistlib.loads((browsers.BY_ID["safari"][5] / "Bookmarks.plist").read_bytes())
    except (OSError, plistlib.InvalidFileException, ValueError):
        root = None
    def walk(node, folder):
        if node.get("WebBookmarkType") == "WebBookmarkTypeLeaf":
            rl = node.get("ReadingList")
            title = (node.get("URIDictionary") or {}).get("title")
            added = rl.get("DateAdded") if isinstance(rl, dict) else None
            ws.add(id=f"safari:{'reading' if rl is not None else 'bookmark'}:{node.get('WebBookmarkUUID')}", kind="reading_list" if rl is not None else "bookmark",
                   ts=added.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z") if isinstance(added, dt.datetime) else None,
                   author="me", is_me=True, thread="safari:default", thread_name="Safari (default)", title=title,
                   text="\n".join(x for x in (title, node.get("URLString"), rl.get("PreviewText") if isinstance(rl, dict) else None) if x),
                   url=node.get("URLString"), meta={"folder": folder} if folder and rl is None else {})
        for c in node.get("Children") or []:
            sub = node.get("Title") if node.get("WebBookmarkType") == "WebBookmarkTypeList" and node.get("Title") not in (None, "com.apple.ReadingList") else None
            walk(c, "/".join(x for x in (folder, sub) if x) if sub else folder)
    if root:
        walk(root, "")
    # Open on your other devices, as iCloud Tabs has them now (last viewed, where it says).
    if SAFARI_TABS.exists():
        try:
            con = connect(snapshot_sqlite(SAFARI_TABS, "browser/safari_CloudTabs.db"))
            devices = {r["device_uuid"]: r["device_name"] for r in con.execute("select device_uuid, device_name from cloud_tab_devices")}
            for r in con.execute("select tab_uuid, device_uuid, title, url, is_pinned, last_viewed_time from cloud_tabs"):
                device = devices.get(r["device_uuid"]) or "another device"
                ws.add(id=f"safari:tab:{r['tab_uuid']}", kind="open_tab", ts=from_apple(r["last_viewed_time"]), author="me", is_me=True,
                       thread=f"safari:{device}", thread_name=f"Safari on {device}", title=r["title"],
                       text="\n".join(x for x in (r["title"], r["url"]) if x), url=r["url"],
                       meta={k: v for k, v in (("device", device), ("pinned", bool(r["is_pinned"]) or None)) if v})
        except Exception:  # an older Safari's database
            pass


def firefox_bookmarks(ws, bid, pdir, con, name):
    pname = pdir.split(".", 1)[-1]
    try:
        rows = con.execute("""select b.id, b.title, b.dateAdded, p.url, f.title folder, f.parent grandparent
                                from moz_bookmarks b join moz_places p on p.id = b.fk
                                left join moz_bookmarks f on f.id = b.parent where b.type = 1""").fetchall()
        # A tag is a folder under the tags root holding an entry for each page tagged with it: not a bookmark.
        tags = {r[0] for r in con.execute("select id from moz_bookmarks where guid = 'tags________' "
                                          "or (parent = 1 and type = 2 and title = 'tags')")}
    except Exception:
        return
    for r in rows:
        if r["grandparent"] in tags:
            ws.skip(f"{bid}:{pdir}:bookmark:{r['id']}")  # and an earlier run's copy of it goes too
            continue
        ts = (dt.datetime(1970, 1, 1, tzinfo=UTC) + dt.timedelta(microseconds=r["dateAdded"])).isoformat().replace("+00:00", "Z") if r["dateAdded"] else None
        ws.add(id=f"{bid}:{pdir}:bookmark:{r['id']}", kind="bookmark", ts=ts, author="me", is_me=True, thread=f"{bid}:{pname}",
               thread_name=f"{name} ({pname})", title=r["title"], text="\n".join(x for x in (r["title"], r["url"]) if x), url=r["url"],
               meta={"folder": r["folder"]} if r["folder"] else {})


def safari_profile_names():
    """Each Safari profile's folder -> its name: the title of its row in SafariTabs.db's bookmarks, whose server_id or
    external_uuid is the folder's name (as DLEAPP reads it)."""
    out = {}
    for i, d in enumerate(browsers.SAFARI_DIRS):
        if not (d / "SafariTabs.db").exists():
            continue
        try:
            con = connect(snapshot_sqlite(d / "SafariTabs.db", f"browser/safari_SafariTabs_{i}.db"))
            cols = columns(con, "bookmarks")
            keys = [c for c in ("server_id", "external_uuid") if c in cols]
            for r in con.execute(f"select title, {', '.join(keys)} from bookmarks where coalesce(title, '') != ''" if keys and "title" in cols
                                 else "select 1 where 0"):
                for k in keys:
                    if r[k]:
                        out.setdefault(r[k], r["title"])
        except sqlite3.Error:
            pass
    return out


def add_safari(w, pid, pname, path):
    """One Safari profile's history. The default profile's ids are as they always were; another's carry its folder."""
    con = connect(snapshot_sqlite(path, "browser/safari_History.db" if pid == "default" else f"browser/safari_{pid}_History.db"))
    for r in con.execute("""select v.id, v.visit_time, v.title, v.origin, v.load_successful,
                                   v.redirect_destination, i.url, i.visit_count
                            from history_visits v join history_items i on i.id = v.history_item"""):
        if r["redirect_destination"] is not None:
            continue
        add_visit(w, f"safari:{r['id']}" if pid == "default" else f"safari:{pid}:{r['id']}", "safari", pname,
                  from_apple(r["visit_time"]), r["url"], r["title"],
                  {"other_device": r["origin"] == 1 or None, "visit_count": r["visit_count"]}, "Safari")


def main():
    skip = browsers.skipped()
    renamed = {}  # an earlier run's id of a download -> its time (chromium_downloads)

    def forget(rec):
        """Not kept from an earlier run: the tabs open on another device then (how things were, not history: only
        today's count), and a download kept by Chrome's row number that is now kept by its guid."""
        return rec.get("kind") == "open_tab" or (rec.get("kind") == "download" and bool(rec.get("ts"))
                                                 and renamed.get(rec.get("id")) == rec.get("ts"))
    with Writer("browser_history", AVENUE) as w, \
            Writer("browser_saved", AVENUE, parser="connectors/browser_history.py:main", forget=forget) as ws:
        if "safari" not in skip:
            safari_saved(ws)
            names = safari_profile_names()
            for pid, path in browsers.history_files("safari"):
                try:
                    add_safari(w, pid, names.get(pid) or pid, path)
                except (sqlite3.Error, OSError):
                    unreadable(w, f"safari:{pid}")
        for bid, _, _, _, kind, _, _ in browsers.BROWSERS:
            if bid in skip:
                continue
            if kind == "chromium":
                add_chromium(w, bid, ws, renamed)
            elif kind == "firefox":
                add_firefox(w, bid, ws)
        if skip:
            w.notes["not_read"] = sorted(skip)


if __name__ == "__main__":
    main()
