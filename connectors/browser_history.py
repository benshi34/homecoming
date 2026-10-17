"""Browsing history from every browser on this Mac (browsers.py): Safari, Chrome and the other Chromium browsers
(Arc, Edge, Brave, Vivaldi, Opera...), Firefox and Zen. Pages, search queries, YouTube watches and Maps lookups."""

import datetime as dt
import json
import re
from urllib.parse import parse_qs, urlparse

import browsers
from common import UTC, Writer, connect, from_apple, from_webkit, snapshot_sqlite

AVENUE = ("Local SQLite. Safari: ~/Library/Safari/History.db (needs Full Disk Access; includes other "
          "devices' visits when iCloud Safari sync is on, origin=1). Chrome and every Chromium browser (Arc, Edge, "
          "Brave, Vivaldi, Opera...): <data folder>/<profile>/History (locked while the browser runs, so copied "
          "first; Chrome keeps ~90 days locally, older history only via Google Takeout). Firefox and Zen: "
          "Profiles/<profile>/places.sqlite. Searches come from Chromium's keyword_search_terms and search-engine "
          "URLs. Browsers the person turned off in Your Setup (UMP_BROWSERS_SKIP) aren't read.")

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


def add_chromium(w, bid):
    name = browsers.BY_ID[bid][1]
    for pdir, pname, path in chromium_profiles(bid):
        # Chrome's files and ids are as they always were; every other browser's are named after it.
        con = connect(snapshot_sqlite(path, f"browser/{bid}_{pdir.replace(' ', '_')}_History"))
        try:
            terms = {r["url_id"]: r["term"] for r in con.execute("select url_id, term from keyword_search_terms")}
        except Exception:  # a browser without the table
            terms = {}
        for r in con.execute("""select v.id, v.visit_time, v.transition, v.visit_duration, u.id url_id,
                                       u.url, u.title, u.visit_count
                                from visits v join urls u on u.id = v.url"""):
            if (r["transition"] & 0xFF) in SUBFRAME:
                continue
            meta = {"seconds": round((r["visit_duration"] or 0) / 1e6) or None, "visit_count": r["visit_count"]}
            rid = f"{bid}:{pdir}:{r['id']}"
            ts = from_webkit(r["visit_time"])
            term = terms.get(r["url_id"])
            if term and not classify(r["url"])[1]:
                w.add(id=f"{rid}:q", kind="search", ts=ts, author="me", is_me=True, thread=f"{bid}:{pname}",
                      thread_name=f"{name} ({pname})", title=term, text=term, url=r["url"],
                      meta={"engine": urlparse(r["url"]).netloc})
                continue
            add_visit(w, rid, bid, pname, ts, r["url"], r["title"], {k: v for k, v in meta.items() if v}, name)


def add_firefox(w, bid):
    name = browsers.BY_ID[bid][1]
    for pdir, path in browsers.history_files(bid):
        con = connect(snapshot_sqlite(path, f"browser/{bid}_{pdir.replace(' ', '_')}_places.sqlite"))
        pname = pdir.split(".", 1)[-1]  # "abcd1234.default-release" -> "default-release"
        for r in con.execute("""select v.id, v.visit_date, v.visit_type, p.url, p.title, p.visit_count
                                from moz_historyvisits v join moz_places p on p.id = v.place_id"""):
            if r["visit_type"] in FIREFOX_SKIP or not r["visit_date"]:
                continue
            ts = (dt.datetime(1970, 1, 1, tzinfo=UTC) + dt.timedelta(microseconds=r["visit_date"])).isoformat().replace("+00:00", "Z")
            add_visit(w, f"{bid}:{pdir}:{r['id']}", bid, pname, ts, r["url"], r["title"],
                      {"visit_count": r["visit_count"]} if r["visit_count"] else {}, name)


def main():
    skip = browsers.skipped()
    with Writer("browser_history", AVENUE) as w:
        safari = browsers.BY_ID["safari"][5] / "History.db"
        if "safari" not in skip and safari.exists():
            con = connect(snapshot_sqlite(safari, "browser/safari_History.db"))
            for r in con.execute("""select v.id, v.visit_time, v.title, v.origin, v.load_successful,
                                           v.redirect_destination, i.url, i.visit_count
                                    from history_visits v join history_items i on i.id = v.history_item"""):
                if r["redirect_destination"] is not None:
                    continue
                add_visit(w, f"safari:{r['id']}", "safari", "default", from_apple(r["visit_time"]), r["url"],
                          r["title"], {"other_device": r["origin"] == 1 or None, "visit_count": r["visit_count"]}, "Safari")
        for bid, _, _, _, kind, _, _ in browsers.BROWSERS:
            if bid in skip:
                continue
            if kind == "chromium":
                add_chromium(w, bid)
            elif kind == "firefox":
                add_firefox(w, bid)
        if skip:
            w.notes["not_read"] = sorted(skip)


if __name__ == "__main__":
    main()
