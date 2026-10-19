"""A collected source at a glance (bridge.py glance): when its records are from, month by month and day by day; the
hours and weekdays they fall on; and what's worth saying about them in words, by the kind of record they are (talk
time for calls, words for notes, steps for Health...). Read-only, from corpus.db, in this Mac's own time zone.

  python3 bridge.py glance imessage            one source's manifest keys
  python3 bridge.py glance gmail google_activity   several: a source made of several parts (Google)"""

import datetime as dt
import json
import os
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

# Records that are a whole day, not a moment: no hour to put them at.
DAY_KINDS = {"health_day", "app_usage_day", "sleep"}
# Not something you did: left out of the charts (they'd drown them), and of what's said about it.
NOT_ACTIVITY = {"health_sample", "contact", "record", "app", "profile", "inference", "advertiser", "interaction", "ad", "off_platform"}
WORD = {"message": ("message", "messages"), "email": ("email", "emails"), "photo": ("photo", "photos"), "video": ("video", "videos"),
        "visit": ("page visited", "pages visited"), "search": ("search", "searches"), "call": ("call", "calls"), "note": ("note", "notes"),
        "event": ("event", "events"), "commit": ("commit", "commits"), "document": ("document", "documents"), "ai_turn": ("AI prompt", "AI prompts"),
        "media": ("video watched", "videos watched"), "song": ("song played", "songs played"), "app_usage": ("app session", "app sessions"),
        "health_day": ("day of Health data", "days of Health data"), "transaction": ("payment", "payments"), "voice_memo": ("recording", "recordings"),
        "reaction": ("reaction", "reactions"), "post": ("post", "posts"), "comment": ("comment", "comments"), "listen": ("episode played", "episodes played"),
        "file_edit": ("saved version", "saved versions"), "command": ("command", "commands"),
        "saved": ("thing saved", "things saved"),
        "app_usage_day": ("day of Screen Time", "days of Screen Time"), "sleep": ("night of sleep", "nights of sleep")}


def _word(kind):
    return WORD.get(kind, (kind.replace("_", " "), kind.replace("_", " ") + "s"))


def _plural(n, kind):
    one, many = _word(kind)
    return f"1 {one}" if n == 1 else f"{n:,} {many}"


def _hours(seconds):
    h = seconds / 3600
    if h < 1:
        return f"{round(seconds / 60):,} minutes"
    if h < 48:
        return f"{h:,.1f} hours".replace(".0 hours", " hours")
    return f"{round(h):,} hours ({h / 24:,.0f} days)"


def _day(d):
    return dt.date.fromisoformat(d).strftime("%b %-d, %Y")


def _snippet(s, n=90):
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _streak(days):
    """The longest run of days in a row, from a sorted list of ISO dates: (length, first, last)."""
    best, start, prev, run_start, run = (0, None, None), None, None, None, 0
    for d in days:
        x = dt.date.fromisoformat(d)
        if prev and (x - prev).days == 1:
            run += 1
        else:
            run, run_start = 1, x
        if run > best[0]:
            best = (run, run_start.isoformat(), x.isoformat())
        prev = x
    return best


def glance(db_path, sources):
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
    q = ",".join("?" * len(sources))
    where = f"source in ({q}) and ts is not null and kind not in ({','.join('?' * len(NOT_ACTIVITY))})"
    args = [*sources, *sorted(NOT_ACTIVITY)]
    total = con.execute(f"select count(*) from records where {where}", args).fetchone()[0]
    if not total:
        return {"total": 0}
    kinds = dict(con.execute(f"select kind, count(*) from records where {where} group by kind order by 2 desc", args).fetchall())
    months = dict(con.execute(f"select strftime('%Y-%m', ts, 'localtime') m, count(*) from records where {where} and m is not null group by m", args).fetchall())
    timed = f"{where} and kind not in ({','.join('?' * len(DAY_KINDS))}) and length(ts) > 10"
    targs = [*args, *sorted(DAY_KINDS)]
    hours = [0] * 24
    for h, n in con.execute(f"select cast(strftime('%H', ts, 'localtime') as integer) h, count(*) from records where {timed} and h is not null group by h", targs):
        hours[h] = n
    weekdays = [0] * 7  # Sunday first, as strftime('%w') has it
    for w, n in con.execute(f"select cast(strftime('%w', ts, 'localtime') as integer) w, count(*) from records where {timed} and w is not null group by w", targs):
        weekdays[w] = n
    days = dict(con.execute(f"select date(ts, 'localtime') d, count(*) from records where {where} and d is not null group by d", args).fetchall())
    today = dt.date.today()
    year_ago = (today - dt.timedelta(days=371)).isoformat()
    recent = {d: n for d, n in days.items() if d >= year_ago}
    ordered = sorted(days)
    first = con.execute(f"select ts, kind, title, text, thread_name, is_me from records where {where} order by ts limit 1", args).fetchone()
    last = con.execute(f"select ts from records where {where} order by ts desc limit 1", args).fetchone()
    busiest = max(days.items(), key=lambda x: x[1]) if days else None
    streak = _streak(ordered)

    main_kind = next(iter(kinds))
    facts = []
    # The first one, in words: "Your first message: Jan 3, 2014, with Maya Chen: “hey”".
    if first:
        ts, kind, title, text, thread_name, is_me = first
        what = _word(kind)[0]
        bits = [_day(ts[:10]) if len(ts) >= 10 else ts]
        if thread_name and kind in ("message", "call", "email"):
            bits.append(f"with {thread_name}")
        said = _snippet(title or text, 70)
        facts.append({"label": f"Your first {what}", "value": ", ".join(bits), "detail": f"“{said}”" if said and kind not in ("call", "photo", "health_day") else None})
    # A source of whole days (Health, a day's Screen Time) has one a day: no busiest day to speak of.
    if busiest and main_kind not in DAY_KINDS:
        facts.append({"label": "Busiest day", "value": _day(busiest[0]), "detail": _plural(busiest[1], main_kind) if len(kinds) == 1 else f"{busiest[1]:,} records"})
    if streak[0] > 1:
        facts.append({"label": "Longest run", "value": f"{streak[0]:,} days in a row", "detail": f"{_day(streak[1])} to {_day(streak[2])}"})
    span = (dt.date.fromisoformat(ordered[-1]) - dt.date.fromisoformat(ordered[0])).days + 1 if ordered else 0
    if ordered and main_kind not in DAY_KINDS:
        facts.append({"label": "Days with any", "value": f"{len(ordered):,} of {span:,}", "detail": f"about {total / len(ordered):,.1f} a day on those days".replace(".0 a day", " a day")})
    facts += _kind_facts(con, sources, kinds)
    con.close()
    return {"total": total, "kinds": kinds, "months": months, "hours": hours, "weekdays": weekdays, "recent": recent,
            "first": first[0] if first else None, "last": last[0] if last else None, "facts": [f for f in facts if f]}


def _kind_facts(con, sources, kinds):
    """What's worth saying about each kind of record there is, from what its records carry."""
    q = ",".join("?" * len(sources))
    one = lambda sql, *a: con.execute(sql, (*sources, *a)).fetchone()
    out = []
    if "message" in kinds:
        mine, threads = one(f"select sum(is_me = '1'), count(distinct thread) from records where source in ({q}) and kind = 'message'")
        # None marked as yours: the export doesn't say who wrote what (not that you wrote nothing).
        if mine:
            out.append({"label": "Written by you", "value": f"{(mine or 0) / kinds['message']:.0%}", "detail": f"{(mine or 0):,} of {kinds['message']:,} messages"})
        if threads:
            out.append({"label": "Conversations", "value": f"{threads:,}"})
    if "email" in kinds:
        mine, people = one(f"select sum(is_me = '1'), count(distinct case when is_me != '1' then author end) from records where source in ({q}) and kind = 'email'")
        if mine:
            out.append({"label": "Sent by you", "value": f"{(mine or 0):,}", "detail": f"of {kinds['email']:,} emails"})
        if people:
            out.append({"label": "People who wrote to you", "value": f"{people:,}"})
    if "call" in kinds:
        secs, longest = one(f"select sum(cast(json_extract(meta, '$.seconds') as real)), max(cast(json_extract(meta, '$.seconds') as real)) from records where source in ({q}) and kind = 'call'")
        if secs:
            out.append({"label": "Time on calls", "value": _hours(secs)})
            row = one(f"select ts, thread_name from records where source in ({q}) and kind = 'call' order by cast(json_extract(meta, '$.seconds') as real) desc limit 1")
            out.append({"label": "Longest call", "value": _hours(longest), "detail": ", ".join(x for x in [_day(row[0][:10]), f"with {row[1]}" if row[1] else ""] if x)})
    if "photo" in kinds or "video" in kinds:
        placed, fav, cams = one(f"select sum(json_extract(meta, '$.lat') is not null), sum(json_extract(meta, '$.favorite') in (1, 'true', '1')), count(distinct json_extract(meta, '$.camera')) "
                                f"from records where source in ({q}) and kind in ('photo', 'video')")
        n = kinds.get("photo", 0) + kinds.get("video", 0)
        if placed:
            out.append({"label": "With a place", "value": f"{placed / n:.0%}", "detail": f"{placed:,} of {n:,}"})
        if fav:
            out.append({"label": "Favorites", "value": f"{fav:,}"})
        if cams and cams > 1:
            out.append({"label": "Cameras", "value": f"{cams:,}", "detail": "phones and cameras they were taken with"})
    if "visit" in kinds:
        sites = set()
        for (url,) in con.execute(f"select url from records where source in ({q}) and kind = 'visit' and url is not null", sources):
            h = (urlparse(url).hostname or "").removeprefix("www.")
            if h:
                sites.add(h)
        out.append({"label": "Sites visited", "value": f"{len(sites):,}", "detail": f"{kinds['visit']:,} page visits"})
    if "search" in kinds:
        distinct = one(f"select count(distinct lower(coalesce(title, text))) from records where source in ({q}) and kind = 'search'")[0]
        out.append({"label": "Different searches", "value": f"{distinct:,}", "detail": f"of {kinds['search']:,}"})
    if "app_usage" in kinds:
        secs, apps = one(f"select sum(cast(json_extract(meta, '$.seconds') as real)), count(distinct title) from records where source in ({q}) and kind = 'app_usage'")
        if secs:
            out.append({"label": "Screen time", "value": _hours(secs), "detail": f"in {apps:,} apps"})
    if "health_day" in kinds:
        avg, best, km = one(f"select avg(cast(json_extract(meta, '$.steps') as real)), max(cast(json_extract(meta, '$.steps') as real)), "
                            f"sum(cast(json_extract(meta, '$.distance_km') as real)) from records where source in ({q}) and kind = 'health_day'")
        if avg:
            out.append({"label": "Steps a day", "value": f"{avg:,.0f}", "detail": "on average"})
            row = one(f"select ts from records where source in ({q}) and kind = 'health_day' order by cast(json_extract(meta, '$.steps') as real) desc limit 1")
            out.append({"label": "Most steps in a day", "value": f"{best:,.0f}", "detail": _day(row[0][:10])})
        if km:
            out.append({"label": "Walked and ran", "value": f"{km:,.0f} km"})
    if "commit" in kinds:
        repos = one(f"select count(distinct json_extract(meta, '$.repo')) from records where source in ({q}) and kind = 'commit'")[0]
        if repos:
            out.append({"label": "Repositories", "value": f"{repos:,}"})
    if "note" in kinds:
        words = sum(len((t or "").split()) for (t,) in con.execute(f"select text from records where source in ({q}) and kind = 'note'", sources))
        if words:
            out.append({"label": "Words written", "value": f"{words:,}", "detail": f"in {kinds['note']:,} notes"})
    if "ai_turn" in kinds:
        mine, sessions = one(f"select sum(is_me = '1'), count(distinct thread) from records where source in ({q}) and kind = 'ai_turn'")
        if sessions:
            out.append({"label": "Conversations", "value": f"{sessions:,}", "detail": f"{(mine or 0):,} prompts of yours"})
    if "event" in kinds:
        hours, allday = one(f"select sum(case when json_extract(meta, '$.all_day') in (1, 'true', '1') then 0 else (julianday(ts_end) - julianday(ts)) * 24 end), "
                            f"sum(json_extract(meta, '$.all_day') in (1, 'true', '1')) from records where source in ({q}) and kind = 'event' and ts_end is not null")
        if hours and hours > 0:
            out.append({"label": "Time in events", "value": _hours(hours * 3600), "detail": f"not counting {allday or 0:,} all-day ones"})
    if "document" in kinds:
        size = one(f"select sum(cast(json_extract(meta, '$.bytes') as real)) from records where source in ({q}) and kind = 'document'")[0]
        if size:
            out.append({"label": "Size", "value": f"{size / 1e6:,.0f} MB" if size >= 1e6 else f"{size / 1e3:,.0f} KB", "detail": f"in {kinds['document']:,} documents"})
    return out


if __name__ == "__main__":
    import sys
    corpus = Path(os.environ.get("CORPUS_DIR") or "corpus")
    print(json.dumps(glance(corpus / "corpus.db", sys.argv[1:]), indent=1))


# What a sample row says about a record, beyond its text: only these, from its meta.
SAMPLE_META = ("seconds", "direction", "type", "steps", "distance_km", "repo", "all_day", "location", "bytes", "ext", "product", "camera", "model", "artist", "album")


def samples(db_path, sources, mode="years", limit=12, offset=0, q="", seed=None):
    """Records to show as they are: spread across the years (a few from each, picked at random), the latest, a
    random handful, or every one, newest first, a page at a time (mode "all", with offset and an optional search)."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
    qs = ",".join("?" * len(sources))
    where = f"source in ({qs}) and ts is not null and kind not in ({','.join('?' * len(NOT_ACTIVITY))})"
    args = [*sources, *sorted(NOT_ACTIVITY)]
    cols = "rowid, source, kind, ts, ts_end, author, is_me, thread, thread_name, title, text, url, meta"
    if q.strip():
        where += " and (title like ? or text like ? or thread_name like ? or author like ?)"
        like = f"%{q.strip()}%"
        args += [like] * 4
    if mode == "recent" or mode == "all":
        rows = con.execute(f"select {cols} from records where {where} order by ts desc limit ? offset ?", (*args, limit, offset)).fetchall()
    elif mode == "random":
        rows = con.execute(f"select {cols} from records where {where} order by random() limit ?", (*args, limit)).fetchall()
        rows.sort(key=lambda r: r[3], reverse=True)
    else:  # a few from each year, oldest year first, so the sample reads as a life
        import random
        rnd = random.Random(seed)
        years = [(y, n) for y, n in con.execute(f"select substr(ts, 1, 4) y, count(*) from records where {where} group by y order by y", args) if y and y.isdigit()]
        each = max(1, -(-limit // max(1, len(years))))  # rounded up: a short history gets more from each year
        rows = []
        # Random places in each year's records, by time (the index on source and time finds them without a full read).
        for y, n in years[-limit:]:
            for k in sorted(rnd.sample(range(n), min(each, n))):
                rows += con.execute(f"select {cols} from records where {where} and ts >= ? and ts < ? order by ts limit 1 offset ?",
                                    (*args, f"{y}-", f"{int(y) + 1}-", k)).fetchall()
        rows.sort(key=lambda r: r[3])
    total = con.execute(f"select count(*) from records where {where}", args).fetchone()[0] if mode == "all" else None
    con.close()
    out = []
    for rowid, source, kind, ts, ts_end, author, is_me, thread, thread_name, title, text, url, meta in rows:
        try:
            m = json.loads(meta) if meta else {}
        except ValueError:
            m = {}
        keep = {k: m[k] for k in SAMPLE_META if k in m and m[k] not in (None, "")}
        if m.get("lat") is not None:
            keep["place"] = True
        # Yours: marked so, or written by "me" (some sources say only that).
        mine = is_me in ("1", "true", "True") or (author or "").lower() == "me"
        out.append({"rowid": rowid, "source": source, "kind": kind, "ts": ts, "ts_end": ts_end, "author": None if mine else author, "is_me": mine,
                    "thread": thread, "thread_name": thread_name, "title": _snippet(title, 200) or None, "text": _snippet(text, 400) or None,
                    "url": url, "meta": keep})
    return {"rows": out, "total": total}
