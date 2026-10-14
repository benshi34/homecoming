"""Safari + Chrome browsing history, search queries, YouTube watches and Maps lookups."""

import json
from urllib.parse import parse_qs, urlparse

from common import LIB, Writer, connect, from_apple, from_webkit, snapshot_sqlite

AVENUE = ("Local SQLite. Safari: ~/Library/Safari/History.db (needs Full Disk Access; includes other "
          "devices' visits when iCloud Safari sync is on, origin=1). Chrome: ~/Library/Application Support/"
          "Google/Chrome/<profile>/History (locked while Chrome runs, so copy the file first; keeps ~90 days "
          "locally, older history only via Google Takeout). Searches come from Chrome keyword_search_terms "
          "and search-engine URLs.")

CHROME = LIB / "Application Support/Google/Chrome"
SEARCH_HOSTS = {"www.google.com": "q", "google.com": "q", "www.bing.com": "q", "duckduckgo.com": "q",
                "www.youtube.com": "search_query", "search.yahoo.com": "p", "www.perplexity.ai": "q"}
SUBFRAME = {3, 4}


def classify(url):
    """Return (tag, query) for search / youtube / maps URLs."""
    try:
        u = urlparse(url)
    except ValueError:
        return None, None
    host, path = u.netloc.lower(), u.path
    qs = parse_qs(u.query)
    if host in SEARCH_HOSTS and ("/search" in path or "/results" in path or host == "duckduckgo.com"):
        q = qs.get(SEARCH_HOSTS[host], [None])[0]
        if q:
            return ("youtube_search" if "youtube" in host else "search"), q
    if "youtube.com" in host and path == "/watch" or host == "youtu.be":
        return "youtube_watch", None
    if host.startswith("www.google.") and path.startswith("/maps") or host == "maps.google.com" or host == "maps.apple.com":
        place = path.split("/place/")[1].split("/")[0].replace("+", " ") if "/place/" in path else qs.get("q", [None])[0]
        return "maps", place
    return None, None


def chrome_profiles():
    try:
        info = json.loads((CHROME / "Local State").read_text())["profile"]["info_cache"]
    except (OSError, KeyError, ValueError):
        info = {}
    for d in sorted(CHROME.glob("*/History")):
        yield d.parent.name, info.get(d.parent.name, {}).get("name", d.parent.name), d


def add_visit(w, rid, browser, profile, ts, url, title, meta):
    tag, q = classify(url)
    if tag in ("search", "youtube_search") and q:
        w.add(id=f"{rid}:q", kind="search", ts=ts, author="me", is_me=True, thread=f"{browser}:{profile}",
              thread_name=f"{browser} ({profile})", title=q, text=q, url=url,
              meta={"engine": urlparse(url).netloc, "youtube": tag == "youtube_search" or None, **meta})
        return
    text = "\n".join(x for x in (title, url) if x)
    if tag == "maps" and q:
        text = f"Maps: {q}\n{text}"
    w.add(id=rid, kind="visit", ts=ts, author="me", is_me=True, thread=f"{browser}:{profile}",
          thread_name=f"{browser} ({profile})", title=title, text=text, url=url,
          meta={"tag": tag, **meta} if tag else meta)


def main():
    with Writer("browser_history", AVENUE) as w:
        safari = LIB / "Safari/History.db"
        if safari.exists():
            con = connect(snapshot_sqlite(safari, "browser/safari_History.db"))
            for r in con.execute("""select v.id, v.visit_time, v.title, v.origin, v.load_successful,
                                           v.redirect_destination, i.url, i.visit_count
                                    from history_visits v join history_items i on i.id = v.history_item"""):
                if r["redirect_destination"] is not None:
                    continue
                add_visit(w, f"safari:{r['id']}", "safari", "default", from_apple(r["visit_time"]), r["url"],
                          r["title"], {"other_device": r["origin"] == 1 or None, "visit_count": r["visit_count"]})

        for pdir, pname, path in chrome_profiles():
            con = connect(snapshot_sqlite(path, f"browser/chrome_{pdir.replace(' ', '_')}_History"))
            terms = {r["url_id"]: r["term"] for r in con.execute("select url_id, term from keyword_search_terms")}
            for r in con.execute("""select v.id, v.visit_time, v.transition, v.visit_duration, u.id url_id,
                                           u.url, u.title, u.visit_count
                                    from visits v join urls u on u.id = v.url"""):
                if (r["transition"] & 0xFF) in SUBFRAME:
                    continue
                meta = {"seconds": round(r["visit_duration"] / 1e6) or None, "visit_count": r["visit_count"]}
                rid = f"chrome:{pdir}:{r['id']}"
                ts = from_webkit(r["visit_time"])
                term = terms.get(r["url_id"])
                if term and not classify(r["url"])[1]:
                    w.add(id=f"{rid}:q", kind="search", ts=ts, author="me", is_me=True, thread=f"chrome:{pname}",
                          thread_name=f"chrome ({pname})", title=term, text=term, url=r["url"],
                          meta={"engine": urlparse(r["url"]).netloc})
                    continue
                add_visit(w, rid, "chrome", pname, ts, r["url"], r["title"],
                          {k: v for k, v in meta.items() if v})


if __name__ == "__main__":
    main()
