"""Explore: artifacts assembled from the corpus on this Mac, for the app's Explore page. Read-only, no network, no
model: every number comes from corpus.db, and every item carries the rowid of a record it rests on, so the app can
open it.

    python3 explore.py summary              one line per artifact, for the Explore page's cards
    python3 explore.py on-this-day [MM-DD]  every past year's same day: photos, people, searches, what you made
    python3 explore.py people               everyone you've talked to one on one, with their history, and your
                                            closest people each year
    python3 explore.py person KEY           one person over the years: messages by month and app, calls, photos
    python3 explore.py places               where your photos were taken, and trips: stretches of days away from home
    python3 explore.py rhythms              when in the day and week you message, browse, search, watch and code
    python3 explore.py firsts               firsts: each person, country, city, project and app
    python3 explore.py made                 what you made, day by day: code, writing, posts, photos
    python3 explore.py groups               every group chat, from any app: who talks, when, its own words and emoji
    python3 explore.py listening            the music you played: artists and songs by year, your eras, songs on repeat
    python3 explore.py movement             your steps and sleep over the years: best days, streaks, bedtimes, trips
    python3 explore.py curiosity            what you searched for: each year's own topics, questions, searches before trips
    python3 explore.py watching             what you watched: channels and shows, rewatches, late nights
    python3 explore.py journeys             every time you went somewhere far, worked out from where your photos (or
                                            anything else with a location) were made; which of them were flights
    python3 explore.py year [YYYY]          a year as a story: people, trips, distance, photos, what you made, steps;
                                            the latest year by default
    python3 explore.py stream [YYYY-MM]     a month as a stream of events, in order (connectors/stream.py): the latest
                                            month by default
    python3 explore.py records ROWID,...    records in brief, for an event's list of them
    python3 explore.py stream-build         write corpus/stream/ now (the one command here that writes; the index
                                            rebuild also does it, for the months that changed)
    python3 explore.py thumbs ROWID,...     small JPEGs of photos, base64
    python3 explore.py thread ROWID [before|after TS]   the conversation a message is in: its day, and a little
                                            either side; or the next messages before or after a time

Times are local: this Mac's time zone (UMP_TZ to change it), or a record's own (photos and Health keep theirs).
Results are cached (UMP_EXPLORE_CACHE, else the temp folder) until corpus.db changes. While an artifact is built,
lines on stderr starting "@progress " say how far it is (JSON: the steps, then the step at and done/total), for the
app's loading screen.
"""
import base64
import collections
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(os.environ.get("UMP_REPO") or Path(__file__).resolve().parents[2])
CORPUS = Path(os.environ.get("CORPUS_DIR") or REPO / "corpus")
DB = CORPUS / "corpus.db"
CACHE = Path(os.environ.get("UMP_EXPLORE_CACHE") or Path(tempfile.gettempdir()) / "ump-explore")
VERSION = 2  # bump when an artifact's shape changes, so old cached results aren't served

CHATS = ("imessage", "instagram", "messenger", "discord", "phone_whatsapp", "whatsapp")
ONE_SIDED = {"discord"}  # exports that keep only your own messages
SEARCHES = (("google_activity", "search"), ("browser_history", "search"), ("chrome_synced", "search"))
VISITS = (("browser_history", "visit"), ("chrome_synced", "visit"), ("google_activity", "visit"))
APP_NAMES = {"imessage": "Messages", "instagram": "Instagram", "messenger": "Messenger", "discord": "Discord",
             "phone_whatsapp": "WhatsApp", "whatsapp": "WhatsApp", "calls": "Calls", "gmail": "Gmail", "hotmail": "Outlook",
             "mail": "Mail", "x": "X", "reddit": "Reddit", "linkedin": "LinkedIn", "tiktok": "TikTok", "spotify": "Spotify", "chatgpt": "ChatGPT",
             "claude_ai": "Claude", "google_chat": "Google Chat", "notion": "Notion", "photos": "Photos",
             "git_commits": "Git", "phone_venmo": "Venmo", "phone_splitwise": "Splitwise", "phone_uberclient": "Uber",
             "phone_airbnb": "Airbnb", "phone_united_airlines": "United", "apple_notes": "Notes", "calendar": "Calendar",
             "facebook_activity": "Facebook", "instagram_activity": "Instagram"}


# ---------------------------------------------------------------- basics

def local_zone():
    name = os.environ.get("UMP_TZ")
    if not name:
        try:  # /etc/localtime -> /var/db/timezone/zoneinfo/America/Los_Angeles
            name = str(Path("/etc/localtime").resolve()).split("zoneinfo/", 1)[1]
        except (IndexError, OSError):
            name = "UTC"
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("UTC")


TZ = local_zone()


def zone_of(tz):
    """A record's own time zone: 'Asia/Tokyo', or Photos' 'GMT-0500'; None if it has none we can read."""
    if not tz:
        return None
    m = re.fullmatch(r"GMT([+-])(\d\d):?(\d\d)", str(tz))
    if m:
        return timezone((1 if m.group(1) == "+" else -1) * timedelta(hours=int(m.group(2)), minutes=int(m.group(3))))
    try:
        return ZoneInfo(str(tz))
    except Exception:
        return None


# A time before 1990 or after tomorrow, or the very first second of Apple's clock, is a clock or a conversion gone
# wrong (a missing time read as 0: 1970, 2001; a date years ahead), not when something happened: it counts as no
# time at all, as it does for the years Your Year offers and the days On This Day looks at.
FIRST_YEAR = 1990
LATEST = datetime.now(timezone.utc) + timedelta(days=1)
APPLE_ZERO = datetime(2001, 1, 1, tzinfo=timezone.utc)


def parse(ts, tz=None):
    """An ISO time from the corpus as a local datetime (UTC when it has no zone), in the record's own zone when it
    has one, else this Mac's; or None (no time, or one that can't be right)."""
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    if t.year < FIRST_YEAR or t > LATEST or t == APPLE_ZERO:
        return None
    try:
        return t.astimezone(zone_of(tz) or TZ)
    except (OverflowError, ValueError):
        return None


def num(v):
    """A number from what a record holds (12, 12.5, "12.5"); 0 when it isn't one."""
    if isinstance(v, bool):
        return 0.0
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return f if math.isfinite(f) else 0.0


def steps_of(meta):
    """A Health day's steps (0 when it says none, or something that isn't a count)."""
    return max(0.0, num(meta_of(meta).get("steps")))


def local_date(ts):
    """The day a record's time was here (this Mac's time zone), or None."""
    t = parse(ts)
    return t.date() if t else None


def day_of(ts):
    """A whole day's record (Health's, at midnight without a zone) as its date; None when it has none that can be
    right."""
    try:
        d = date.fromisoformat(str(ts)[:10])
    except (TypeError, ValueError):
        return None
    return d if FIRST_YEAR <= d.year and d <= LATEST.date() and d != APPLE_ZERO.date() else None


class Progress:
    """An artifact's steps, and how far through the current one, as "@progress {json}" lines on stderr. An artifact
    built inside another one (people, for firsts) reports as a detail of the outer one's current step, so the app
    shows one list of steps."""
    stack = []

    def __init__(self, steps):
        self.steps, self.at, self.done, self.total, self.last, self.label = steps, -1, 0, None, 0.0, None
        self.outer = Progress.stack[-1] if Progress.stack else None
        Progress.stack.append(self)
        if not self.outer:
            self.emit({"steps": steps})

    def step(self, i, total=None):
        self.at, self.done, self.total = i, 0, total
        if self.outer:
            self.outer.detail(self.steps[i], 0, total)
        else:
            self.emit({"at": i, "done": 0, "total": total})

    def tick(self, done):
        """Called often (every row); writes at most ten times a second."""
        self.done = done
        if (done % 500 == 0 or (self.total or 0) < 5000) and time.monotonic() - self.last > 0.1:
            self.last = time.monotonic()
            if self.outer:
                self.outer.detail(self.steps[self.at], done, self.total)
            else:
                self.emit({"at": self.at, "done": done, "total": self.total})

    def detail(self, label, done, total):
        if time.monotonic() - self.last > 0.1 or done == 0:
            self.last = time.monotonic()
            self.emit({"at": self.at, "detail": label, "done": done, "total": total})

    def emit(self, d):
        if self.outer:
            return
        try:
            sys.stderr.write("@progress " + json.dumps(d) + "\n")
            sys.stderr.flush()
        except (OSError, ValueError):
            pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        Progress.stack.remove(self)


def count_where(con, where, args=()):
    return con.execute(f"select count(*) from records where {where}", args).fetchone()[0]


def connect():
    if not DB.exists():
        raise FileNotFoundError("corpus.db doesn't exist yet: read some sources first")
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=10)
    con.execute("PRAGMA query_only = ON")
    con.set_authorizer(lambda action, *_: sqlite3.SQLITE_DENY if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH) else sqlite3.SQLITE_OK)
    return con


def me_names():
    """You, by every name you go by (loosely, as key() compares them); and "me" and "you", which is how some exports
    write you."""
    try:
        d = json.loads((CORPUS / "identity.json").read_text())
    except (OSError, ValueError):
        d = {}
    d = d if isinstance(d, dict) else {}
    return {key(n) for n in (d.get("names") or []) + (d.get("usernames") or []) if n and key(n)} | {"me", "you"}


def key(name):
    """A person's name, compared loosely: "Grace Hopper", "grace hopper" and "Grace  Hopper!" are one person."""
    return re.sub(r"[\W_]+", "", str(name or "").casefold())


def meta_of(m):
    """A record's meta as a dict: {} when it has none, or it isn't one (a list, a string, something cut off)."""
    try:
        d = json.loads(m) if m else {}
    except (ValueError, TypeError):
        return {}
    return d if isinstance(d, dict) else {}


# Country names as Apple's Photos writes them (English), to tell a country from a region, sea or landmark in a
# place line: "San Francisco, California, United States, San Francisco Bay".
COUNTRIES = set("""Afghanistan|Albania|Algeria|Andorra|Angola|Antigua and Barbuda|Argentina|Armenia|Aruba|Australia|Austria|
Azerbaijan|Bahamas|Bahrain|Bangladesh|Barbados|Belarus|Belgium|Belize|Benin|Bermuda|Bhutan|Bolivia|Bosnia and Herzegovina|
Botswana|Brazil|British Virgin Islands|Brunei|Bulgaria|Burkina Faso|Burundi|Cambodia|Cameroon|Canada|Cape Verde|Cayman Islands|
Central African Republic|Chad|Chile|China|Colombia|Comoros|Congo|Costa Rica|Côte d'Ivoire|Croatia|Cuba|Curaçao|Cyprus|Czechia|
Czech Republic|Democratic Republic of the Congo|Denmark|Djibouti|Dominica|Dominican Republic|Ecuador|Egypt|El Salvador|Equatorial Guinea|
Eritrea|Estonia|Eswatini|Ethiopia|Fiji|Finland|France|French Polynesia|Gabon|Gambia|Georgia|Germany|Ghana|Gibraltar|Greece|
Greenland|Grenada|Guadeloupe|Guam|Guatemala|Guinea|Guinea-Bissau|Guyana|Haiti|Honduras|Hong Kong|Hungary|Iceland|India|Indonesia|
Iran|Iraq|Ireland|Isle of Man|Israel|Italy|Jamaica|Japan|Jersey|Jordan|Kazakhstan|Kenya|Kiribati|Kosovo|Kuwait|Kyrgyzstan|Laos|
Latvia|Lebanon|Lesotho|Liberia|Libya|Liechtenstein|Lithuania|Luxembourg|Macao|Macau|Madagascar|Malawi|Malaysia|Maldives|Mali|Malta|
Marshall Islands|Martinique|Mauritania|Mauritius|Mexico|Micronesia|Moldova|Monaco|Mongolia|Montenegro|Morocco|Mozambique|Myanmar|
Namibia|Nauru|Nepal|Netherlands|New Caledonia|New Zealand|Nicaragua|Niger|Nigeria|North Korea|North Macedonia|Norway|Oman|Pakistan|
Palau|Palestinian Territories|Panama|Papua New Guinea|Paraguay|Peru|Philippines|Poland|Portugal|Puerto Rico|Qatar|Réunion|Romania|
Russia|Rwanda|Saint Kitts and Nevis|Saint Lucia|Saint Vincent and the Grenadines|Samoa|San Marino|São Tomé and Príncipe|Saudi Arabia|
Senegal|Serbia|Seychelles|Sierra Leone|Singapore|Sint Maarten|Slovakia|Slovenia|Solomon Islands|Somalia|South Africa|South Korea|
South Sudan|Spain|Sri Lanka|Sudan|Suriname|Sweden|Switzerland|Syria|Taiwan|Tajikistan|Tanzania|Thailand|Timor-Leste|Togo|Tonga|
Trinidad and Tobago|Tunisia|Turkey|Türkiye|Turkmenistan|Turks and Caicos Islands|Tuvalu|Uganda|Ukraine|United Arab Emirates|
United Kingdom|United States|U.S. Virgin Islands|Uruguay|Uzbekistan|Vanuatu|Vatican City|Venezuela|Vietnam|Yemen|Zambia|Zimbabwe""".replace("\n", "").split("|"))


# Parts of a place line that are a county or the like, between a city and its state.
SUBREGION = re.compile(r"\b(County|Parish|Borough|Prefecture|Province|Oblast|Municipality)$", re.I)


def place_parts(text):
    """'Photo\\nPlace: Golden Gate Park, San Francisco, California, United States\\n...' -> ('San Francisco',
    'United States'): the city, and the country (the last part that is one; None when no part is). Photos lists a
    place from the most particular (a park, a neighborhood) out to the country, a state or region just before it; the
    city is the part before the region. A city that is its own region is named twice ("Tokyo, Tokyo, Japan"). With
    only two parts there's no telling a neighborhood and its city from a city and its state: the first, then."""
    m = re.search(r"^Place: (.+)$", text or "", re.M)
    if not m:
        return None, None
    parts = [p.strip() for p in m.group(1).split(",") if p.strip()]
    country = next((p for p in reversed(parts) if p in COUNTRIES), None)
    if country:
        parts = parts[:parts.index(country)]
    twice = next((a for a, b in zip(parts, parts[1:]) if a.casefold() == b.casefold()), None)
    if twice:
        return twice, country
    parts = [p for p in parts if not SUBREGION.search(p)] or parts
    if not parts:
        return None, country
    return (parts[-2] if len(parts) >= 3 else parts[0]), country


def spot_of(text):
    """A place line's first part, the most particular ("the West Loop"): for a day's photos, where in town."""
    m = re.search(r"^Place: ([^,\n]+)", text or "", re.M)
    p = m.group(1).strip() if m else None
    return None if not p or p in COUNTRIES else p


def people_in_photo(text):
    m = re.search(r"^People: (.+)$", text or "", re.M)
    return [p.strip() for p in m.group(1).split(",")] if m else []


def km(a, b):
    """Great-circle distance between (lat, lon) points."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(min(1, math.sqrt(h)))


def cached(name, fn, *args):
    """fn(*args), kept until corpus.db changes."""
    try:
        stamp = f"{DB.stat().st_mtime_ns}:{DB.stat().st_size}"
    except OSError:
        stamp = "none"
    h = hashlib.sha1(json.dumps([VERSION, name, args, stamp, str(TZ)]).encode()).hexdigest()[:16]
    f = CACHE / f"{name}-{h}.json"
    if f.exists():
        try:
            return json.loads(f.read_text())
        except ValueError:
            pass
    out = fn(*args)
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        for old in CACHE.glob(f"{name}-*.json"):
            old.unlink(missing_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(out, ensure_ascii=False))
        tmp.replace(f)
    except OSError:
        pass
    return out


def sources_present(con):
    return {s for (s,) in con.execute("select distinct source from records")}


# ---------------------------------------------------------------- people

def chat_partner(source, thread_name, participants, meta, mine):
    """The one other person in a one-on-one conversation, or None for a group or a server channel."""
    if source == "imessage":
        return None if meta.get("group") else thread_name
    if source == "discord":
        if not (thread_name or "").startswith("Direct Message with"):
            return None
        return participants or thread_name.removeprefix("Direct Message with").strip(" .")
    others = [p.strip() for p in (participants or "").split(",") if p.strip() and key(p) not in mine]
    if participants:
        return others[0] if len(others) == 1 else None
    return thread_name


MESSAGES = f"kind = 'message' and source in ({','.join(repr(s) for s in CHATS)}) and ts is not null"


def message_rows(con, mine, pg=None):
    """(person key, display name, source, local time, is_me, rowid, thread) for every one-on-one message, oldest
    first (in the database's order: a library's times are UTC, so it's the order they happened, and nothing has to
    hold every message to sort them)."""
    q = f"select rowid, source, ts, is_me, thread, thread_name, participants, meta from records where {MESSAGES} order by ts"
    for i, (rowid, source, ts, is_me, thread, thread_name, participants, meta) in enumerate(con.execute(q)):
        if pg:
            pg.tick(i)
        m = meta_of(meta) if source == "imessage" else {}
        who = chat_partner(source, thread_name, participants, m, mine)
        k = key(who)
        if not k or k in mine:
            continue
        t = parse(ts)
        if t:
            yield k, who, source, t, str(is_me) == "1", rowid, thread


def people(con=None):
    con = con or connect()
    mine = me_names()
    with Progress(["Reading your messages", "Adding your calls", "Finding who's in your photos",
                   "Ranking your closest people, year by year"]) as pg:
        return _people(con, mine, pg)


def _people(con, mine, pg):
    P = {}

    def person(k, name):
        p = P.get(k)
        if not p:
            p = P[k] = {"key": k, "names": collections.Counter(), "messages": 0, "sent": 0, "apps": collections.Counter(),
                        "years": collections.Counter(), "first": None, "last": None, "calls": 0, "call_minutes": 0.0,
                        "photos": 0, "starts_me": 0, "starts_them": 0, "_last": {}}
        p["names"][name] += 1
        return p

    pg.step(0, count_where(con, MESSAGES))
    for k, name, source, t, is_me, rowid, thread in message_rows(con, mine, pg):
        p = person(k, name)
        p["messages"] += 1
        p["sent"] += is_me
        p["apps"][source] += 1
        p["years"][t.year] += 1
        if not p["first"]:
            p["first"] = {"ts": t.isoformat(), "rowid": rowid, "app": source}
        p["last"] = {"ts": t.isoformat(), "rowid": rowid, "app": source}
        # A conversation starts after eight quiet hours: who broke the silence? (Not countable where the export
        # keeps only your side.)
        if source not in ONE_SIDED:
            prev = p["_last"].get(thread)
            if prev is None or (t - prev).total_seconds() > 8 * 3600:
                p["starts_me" if is_me else "starts_them"] += 1
            p["_last"][thread] = t
    pg.step(1, count_where(con, "source = 'calls'"))
    for i, (rowid, ts, thread_name, meta) in enumerate(con.execute("select rowid, ts, thread_name, meta from records where source = 'calls' and ts is not null")):
        pg.tick(i)
        k = key(thread_name)
        if not k or k in mine:
            continue
        p = person(k, thread_name)
        p["calls"] += 1
        p["call_minutes"] += num(meta_of(meta).get("seconds")) / 60
    alias = merge_initials(P)
    # Photos often names people by first name alone ("Ada"): that's the one person you talk to with that first
    # name, when there's only one (of the people you've exchanged ten or more messages with): two Graces, no match.
    by_first = collections.defaultdict(list)
    for k, p in P.items():
        if p["messages"] >= 10:
            by_first[key(p["names"].most_common(1)[0][0].split()[0])].append(k)
    pg.step(2, count_where(con, "source = 'photos' and text like '%People:%'"))
    for i, (text,) in enumerate(con.execute("select text from records where source = 'photos' and text like '%People:%'")):
        pg.tick(i)
        for name in people_in_photo(text):
            k = alias.get(key(name), key(name))
            if k not in P and len(name.split()) == 1 and len(by_first.get(k, [])) == 1:
                P[by_first[k][0]].setdefault("photo_keys", set()).add(k)
                k = by_first[k][0]
            if k and k not in mine and k in P:
                P[k]["photos"] += 1
    pg.step(3)
    out = []
    for p in P.values():
        if p["messages"] + p["calls"] == 0:
            continue
        p.pop("_last")
        p["photo_keys"] = sorted(p.get("photo_keys", ()))
        p["name"] = p.pop("names").most_common(1)[0][0]
        p["apps"] = dict(p["apps"].most_common())
        p["years"] = {str(y): n for y, n in sorted(p["years"].items())}
        p["call_minutes"] = round(p["call_minutes"])
        out.append(p)
    out.sort(key=lambda p: (-p["messages"], -p["calls"], p["name"].casefold()))  # most messages first, as the page says
    years = sorted({int(y) for p in out for y in p["years"]})
    circle = {}
    for y in years:
        ranked = sorted((p for p in out if p["years"].get(str(y))), key=lambda p: -p["years"][str(y)])
        circle[str(y)] = [{"key": p["key"], "name": p["name"], "messages": p["years"][str(y)]} for p in ranked[:10]]
    return {"people": out, "circle": circle, "total_messages": sum(p["messages"] for p in out)}


def merge_initials(P):
    """"Ada L" in Messages and "Ada Lovelace" in Instagram are one person: a name that ends in a lone initial
    joins the only other name with the same first name and that initial. Returns {merged key: kept key}."""
    alias = {}
    names = {k: p["names"].most_common(1)[0][0].split() for k, p in P.items()}
    for k, toks in names.items():
        if len(toks) != 2 or len(toks[1].rstrip(".")) != 1:
            continue
        first, initial = toks[0].casefold(), toks[1][0].casefold()
        match = [kk for kk, tt in names.items() if kk != k and len(tt) >= 2 and tt[0].casefold() == first
                 and len(tt[-1]) > 1 and tt[-1][0].casefold() == initial]
        if len(match) == 1:
            alias[k] = match[0]
    for k, into in alias.items():
        a, b = P.pop(k), P[into]
        full = b["names"].most_common(1)[0][0]
        for f in ("messages", "sent", "calls", "call_minutes", "photos", "starts_me", "starts_them"):
            b[f] += a[f]
        for f in ("names", "apps", "years"):
            b[f].update(a[f])
        b["names"][full] += 10 ** 9  # shown by the full name, not the initial
        b["first"] = min(filter(None, (a["first"], b["first"])), key=lambda x: x["ts"], default=None)
        b["last"] = max(filter(None, (a["last"], b["last"])), key=lambda x: x["ts"], default=None)
        b.setdefault("aliases", []).append(k)
    return alias


def person(k):
    con = connect()
    mine = me_names()
    entry = next((p for p in cached("people", people)["people"] if p["key"] == k), None)
    keys = {k, *(entry.get("aliases", []) if entry else [])}
    photo_keys = keys | set(entry.get("photo_keys", []) if entry else [])
    with Progress(["Reading your messages", "Calls and photos together"]) as pg:
        return _person(con, mine, k, entry, keys, photo_keys, pg)


def _person(con, mine, k, entry, keys, photo_keys, pg):
    months = collections.defaultdict(collections.Counter)
    hours = [0] * 24
    sample = []
    name = entry["name"] if entry else None
    pg.step(0, count_where(con, MESSAGES))
    for pk, who, source, t, is_me, rowid, _ in message_rows(con, mine, pg):
        if pk not in keys:
            continue
        name = name or who
        months[t.strftime("%Y-%m")][source] += 1
        hours[t.hour] += 1
        sample.append((t, rowid, is_me))
    calls = []
    pg.step(1)
    for rowid, ts, thread_name, meta in con.execute("select rowid, ts, thread_name, meta from records where source = 'calls'"):
        if key(thread_name) in keys:
            name = name or thread_name
            m = meta_of(meta)
            t = parse(ts)
            if t:
                calls.append({"ts": t.isoformat(), "rowid": rowid, "minutes": round(num(m.get("seconds")) / 60, 1),
                              "type": m.get("type"), "direction": m.get("direction")})
    photos = []
    for rowid, ts, text, meta in con.execute("select rowid, ts, text, meta from records where source = 'photos' and text like '%People:%' order by ts"):
        if any(key(n) in photo_keys for n in people_in_photo(text)):
            photos.append(rowid)
    sample.sort()
    # Busiest days: the days you talked most, each with its first message.
    days = collections.Counter(t.date().isoformat() for t, _, _ in sample)
    first_of = {}
    for t, rowid, _ in sample:
        first_of.setdefault(t.date().isoformat(), rowid)
    busiest = [{"date": d, "messages": n, "rowid": first_of[d]} for d, n in days.most_common(8)]
    return {"key": k, "name": name, "months": {m: dict(c) for m, c in sorted(months.items())}, "hours": hours,
            "calls": calls[-200:], "call_count": len(calls), "photos": photos, "photo_count": len(photos),
            "busiest_days": busiest, "first": sample[0][1] if sample else None, "last": sample[-1][1] if sample else None}


# ---------------------------------------------------------------- on this day

def on_this_day(md=None):
    con = connect()
    today = datetime.now(TZ).date()
    try:
        month, day = (int(x) for x in (md or today.strftime("%m-%d")).split("-"))
        date(2000, month, day)
    except ValueError:
        return {"error": f"There's no day {md} in the year."}
    mine = me_names()
    merged = merged_names()
    first = con.execute("select min(ts) from records where ts > '1990'").fetchone()[0]
    start_year = int(first[:4]) if first and first[:4].isdigit() else today.year
    years = []
    for y in range(today.year, start_year - 1, -1):
        try:
            d = date(y, month, day)
        except ValueError:  # 29 February
            continue
        if d > today:
            continue
        # A day either side in UTC, for times written with an offset rather than Z; then only what was on this day
        # here (a day with a clock change is 23 or 25 hours).
        lo = datetime(y, month, day, tzinfo=TZ) - timedelta(days=1)
        hi = datetime(y, month, day, tzinfo=TZ) + timedelta(days=2)
        rows = [r for r in con.execute("select rowid, source, kind, ts, is_me, author, thread, thread_name, participants, title, text, meta "
                                       "from records where ts >= ? and ts < ? order by ts",
                                       (lo.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), hi.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")))
                if r[1] != "health" and local_date(r[3]) == d]  # Health's days: by date, below
        if not rows:
            continue
        photos, places, threads, searches, watched, made, events, calls, steps = [], collections.Counter(), {}, [], [], [], [], [], None
        watch_count = 0
        for rowid, source, kind, ts, is_me, author, thread, thread_name, participants, title, text, meta in rows:
            if source == "photos":
                photos.append(rowid)
                p = spot_of(text)
                if p:
                    places[p] += 1
            elif kind == "message" and source in CHATS:
                # One person once, whichever apps you talked in (the busiest conversation opens); a group as a group.
                m = meta_of(meta) if source == "imessage" else {}
                who = chat_partner(source, thread_name, participants, m, mine)
                if who:
                    pk, name = merged.get(key(who), (key(who), who))
                    t = threads.setdefault(("person", pk), {"name": name, "key": pk, "group": False, "members": [], "apps": collections.Counter(),
                                                            "messages": 0, "by_thread": collections.Counter(), "first": {}})
                else:
                    t = threads.setdefault(("group", source, thread), {"name": thread_name or "A group", "key": None, "group": True, "members": [],
                                                                       "apps": collections.Counter(), "messages": 0, "by_thread": collections.Counter(), "first": {}})
                    if str(is_me) != "1" and author and author not in t["members"] and len(t["members"]) < 3:
                        t["members"].append(author)
                t["messages"] += 1
                t["apps"][APP_NAMES.get(source, source)] += 1
                t["by_thread"][(source, thread)] += 1
                t["first"].setdefault((source, thread), rowid)
            elif kind == "search" and (source, kind) in SEARCHES:
                q = (title or text or "").removeprefix("Searched for ").strip()
                if q and q not in [s["text"] for s in searches]:
                    searches.append({"text": q[:120], "rowid": rowid})
            elif source == "google_activity" and kind == "media" and "youtube.com/watch" in (text or ""):
                watch_count += 1
                if title and not title.startswith("http"):  # the video's title, when Google kept it
                    watched.append({"title": title[:120], "rowid": rowid})
            elif source == "calls":
                calls.append({"name": merged.get(key(thread_name), (None, thread_name))[1], "rowid": rowid,
                              "minutes": round(num(meta_of(meta).get("seconds")) / 60, 1)})
            elif source in ("calendar", "google_calendar") and kind == "event":
                events.append({"title": (title or "")[:100], "rowid": rowid})
            elif source == "health":
                continue  # Health days are dated, not timed: looked up by date below
            elif (source == "git_commits" and str(is_me) == "1") or source in ("apple_notes", "notion") or \
                    (source == "documents" and str(is_me) == "1") or kind == "post":
                made.append({"kind": made_kind(source, kind), "title": (title or (text or "").split("\n")[0])[:100], "rowid": rowid})
        # Health days are stored at local midnight without a zone: look them up by date.
        r = con.execute("select meta from records where source = 'health' and kind = 'health_day' and ts like ?", (f"{d.isoformat()}%",)).fetchone()
        if r:
            steps = int(steps_of(r[0])) or None
        top = []
        for t in sorted(threads.values(), key=lambda t: -t["messages"]):
            busiest = t.pop("by_thread").most_common(1)[0][0]
            apps = [a for a, _ in t.pop("apps").most_common()]
            t["rowid"], t["apps"], t["app"] = t.pop("first")[busiest], apps, " and ".join(apps)
            top.append(t)
        entry = {"year": y, "date": d.isoformat(), "ago": today.year - y,
                 "photos": {"count": len(photos), "sample": spread(photos, 12), "ids": photos, "places": [p for p, _ in places.most_common(4)]},
                 "messages": {"count": sum(t["messages"] for t in top), "threads": top, "conversations": len(top)},
                 "calls": calls, "searches": searches, "search_count": len(searches), "watched": watched,
                 "watch_count": watch_count, "made": made, "made_count": len(made), "events": events, "steps": steps}
        if entry["photos"]["count"] or entry["messages"]["count"] or searches or made or events or calls or watch_count:
            years.append(entry)
    out = {"date": f"{month:02d}-{day:02d}", "label": date(2000, month, day).strftime("%B %-d"), "years": years}
    if not years:
        out["nearest"] = nearest_days(con, date(2000, month, day))
    return out


def nearest_days(con, d):
    """For a day with nothing on it: how many days before and after it the nearest days with something are (in any
    year), or None."""
    have = set()
    shown = (f"source = 'photos' or (kind = 'message' and source in ({','.join(repr(c) for c in CHATS)})) or source = 'calls' "
             f"or (kind = 'search' and source in ({','.join(repr(a) for a, _ in SEARCHES)})) or (source = 'google_activity' and kind = 'media') "
             "or (source in ('calendar', 'google_calendar') and kind = 'event') or (source in ('git_commits', 'documents') and is_me = '1') "
             "or source in ('apple_notes', 'notion') or kind = 'post'")  # what a day here shows
    for (h,) in con.execute(f"select distinct substr(ts, 1, 13) from records where ts > '1990' and ({shown})"):
        t = parse(f"{h}:00:00")
        if t:
            have.add((t.month, t.day))
    out = {"before": None, "after": None}
    for n in range(1, 367):
        for side, k in (("before", -n), ("after", n)):
            dd = d + timedelta(days=k)
            if out[side] is None and (dd.month, dd.day) in have:
                out[side] = n
    return out


def spread(items, n):
    """Up to n items spread evenly through the list (a day's photos from morning to night, not the first burst)."""
    if len(items) <= n:
        return list(items)
    step = len(items) / n
    return [items[int(i * step)] for i in range(n)]


def made_kind(source, kind):
    if source == "git_commits":
        return "code"
    if source in ("apple_notes", "notion", "notion_export", "documents"):
        return "writing"
    if source == "ai_coding":
        return "ai"
    if source == "photos":
        return "photos"
    return "posts"


# ---------------------------------------------------------------- places and trips

def places():
    with Progress(["Reading where you were", "Finding your trips", "Who you talked to on each trip"]) as pg:
        return _places(connect(), pg)


def _places(con, pg):
    pts = located(con, pg)  # (local datetime, lat, lon, place, country, rowid)
    # The map: photos pooled into cells about 10 km across.
    cells = {}
    for t, lat, lon, place, country, rowid in pts:
        c = cells.setdefault((round(lat, 1), round(lon, 1)), {"lat": 0.0, "lon": 0.0, "photos": 0, "places": collections.Counter(),
                                                               "first": t, "last": t, "rowid": rowid, "days": set()})
        c["lat"] += lat
        c["lon"] += lon
        c["photos"] += 1
        c["last"] = t
        c["days"].add(t.date())
        if place:
            c["places"][place] += 1
    points = [{"lat": round(c["lat"] / c["photos"], 4), "lon": round(c["lon"] / c["photos"], 4), "photos": c["photos"],
               "days": len(c["days"]), "place": c["places"].most_common(1)[0][0] if c["places"] else None,
               "first": c["first"].date().isoformat(), "last": c["last"].date().isoformat(), "rowid": c["rowid"]}
              for c in cells.values()]
    points.sort(key=lambda p: -p["photos"])
    pg.step(1)
    trips = find_trips(con, pts, pg=pg)
    countries = collections.Counter()
    cities = collections.Counter()
    for t, lat, lon, place, country, rowid in pts:
        if country:
            countries[country] += 1
        if place:
            cities[place] += 1
    return {"points": points, "trips": trips, "photos_with_place": len(pts), "countries": dict(countries.most_common()),
            "places": len(cities), "first": pts[0][0].date().isoformat() if pts else None,
            "last": pts[-1][0].date().isoformat() if pts else None}


def find_trips(con, pts, away_km=100, gap_days=2, pg=None):
    """Stretches of days whose photos are far from home. Home is where you took photos on the most days in the
    90 days around (it moves when you move); a trip is consecutive days away, allowing a couple of days without
    photos in between."""
    if not pts:
        return []
    by_day = collections.defaultdict(list)
    for p in pts:
        by_day[p[0].date()].append(p)
    days = sorted(by_day)
    coarse = {d: collections.Counter((round(p[1] * 2) / 2, round(p[2] * 2) / 2) for p in by_day[d]) for d in days}

    def home(d):
        votes = collections.Counter()
        for dd in days_between(d - timedelta(days=45), d + timedelta(days=45)):
            if dd in coarse:
                votes[coarse[dd].most_common(1)[0][0]] += 1
        return votes.most_common(1)[0][0] if votes else None

    away = {}
    for d in days:
        h = home(d)
        far = [p for p in by_day[d] if h and km(h, (p[1], p[2])) > away_km]
        if far and len(far) * 2 >= len(by_day[d]):  # most of that day's photos
            away[d] = (far, h)
    trips, cur = [], []
    for d in sorted(away):
        if cur and (d - cur[-1]).days > gap_days + 1:
            trips.append(cur)
            cur = []
        cur.append(d)
    if cur:
        trips.append(cur)
    out = []
    merged = merged_names()
    if pg:
        pg.step(2, len(trips))
    for i, ds in enumerate(trips):
        if pg:
            pg.tick(i)
        photos = [p for d in ds for p in away[d][0]]
        h = away[ds[0]][1]
        places, countries = collections.Counter(), collections.Counter()
        for p in photos:
            if p[3]:
                places[p[3]] += 1
            if p[4]:
                countries[p[4]] += 1
        far = max(photos, key=lambda p: km(h, (p[1], p[2])))
        start, end = ds[0], ds[-1]
        lo = datetime(start.year, start.month, start.day, tzinfo=TZ).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        hi = (datetime(end.year, end.month, end.day, tzinfo=TZ) + timedelta(days=1)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        out.append({"id": f"{start.isoformat()}-{i}", "start": start.isoformat(), "end": end.isoformat(),
                    "days": (end - start).days + 1, "photos": len(photos), "places": [p for p, _ in places.most_common(6)],
                    "countries": [c for c, _ in countries.most_common()], "farthest_km": round(km(h, (far[1], far[2]))),
                    "lat": round(sum(p[1] for p in photos) / len(photos), 3), "lon": round(sum(p[2] for p in photos) / len(photos), 3),
                    "sample": spread([p[5] for p in photos], 12), "photo_ids": [p[5] for p in photos],  # every one, in order
                    "people": trip_people(con, lo, hi, merged),
                    "money": con.execute("select count(*) from records where source in ('phone_splitwise', 'phone_venmo') "
                                         "and ts >= ? and ts < ?", (lo, hi)).fetchone()[0]})
    out.sort(key=lambda t: t["start"], reverse=True)
    return out


def days_between(a, b):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def merged_names():
    """{key: (kept key, display name)} for everyone in the people artifact, including the names merged into others."""
    out = {}
    for p in cached("people", people)["people"]:
        for k in [p["key"], *p.get("aliases", [])]:
            out[k] = (p["key"], p["name"])
    return out


def trip_people(con, lo, hi, merged=None):
    """Who you messaged most during a trip, by the names the people artifact uses."""
    mine = me_names()
    merged = merged if merged is not None else merged_names()
    c = collections.Counter()
    names = {}
    for source, thread_name, participants, meta in con.execute(
            f"select source, thread_name, participants, meta from records where kind = 'message' and source in ({','.join('?' * len(CHATS))}) "
            "and ts >= ? and ts < ?", (*CHATS, lo, hi)):
        who = chat_partner(source, thread_name, participants, meta_of(meta) if source == "imessage" else {}, mine)
        if who and key(who) not in mine:
            k, name = merged.get(key(who), (key(who), who))
            c[k] += 1
            names[k] = name
    return [{"key": k, "name": names[k], "messages": n} for k, n in c.most_common()]


# ---------------------------------------------------------------- rhythms

def rhythms():
    con = connect()
    # Each kind's records, by a query; searches and videos are the ones Curiosity and Watching count (each search
    # once, every video service), so the pages agree.
    kinds = {
        "messages": ("Messages you sent", f"kind = 'message' and is_me = '1' and source in ({','.join(repr(s) for s in CHATS)})"),
        "browsing": ("Pages you visited", " or ".join(f"(source = '{s}' and kind = '{k}')" for s, k in VISITS)),
        "searches": ("Searches", lambda: (t for t, _, _ in searches(con))),
        "watching": ("Videos you watched", lambda: (v[0] for v in videos(con))),
        "coding": ("Code you wrote", "(source = 'git_commits' and is_me = '1') or (source = 'ai_coding' and is_me = '1')"),
        "photos": ("Photos you took", "source = 'photos'"),
    }
    with Progress([label for label, _ in kinds.values()] + ["Your steps"]) as pg:
        return _rhythms(con, kinds, pg)


def _rhythms(con, kinds, pg):
    out = {}
    for si, (k, (label, where)) in enumerate(kinds.items()):
        pg.step(si)
        grid = [[0] * 24 for _ in range(7)]  # Monday first
        by_year = collections.defaultdict(lambda: [0] * 24)
        last_of_day, per_day = {}, collections.Counter()
        n = 0
        times = where() if callable(where) else (parse(ts, meta_of(meta).get("timezone") if meta else None) for ts, meta in con.execute(
            f"select ts, case when source = 'photos' then meta end from records where ({where}) and ts is not null"))
        for t in times:
            if not t:
                continue
            n += 1
            pg.tick(n)
            grid[t.weekday()][t.hour] += 1
            by_year[t.year][t.hour] += 1
            # Late nights count toward the day before: a day runs from 5 am to 5 am.
            d = (t - timedelta(hours=5)).date()
            hrs = (t - datetime(d.year, d.month, d.day, tzinfo=t.tzinfo)).total_seconds() / 3600
            per_day[d] += 1
            if hrs > last_of_day.get(d, -1):
                last_of_day[d] = hrs
        if not n:
            continue
        # Only busy days say when a day ends: on a day with two messages, the last one isn't a bedtime.
        late = collections.defaultdict(list)
        for d, hrs in last_of_day.items():
            if per_day[d] >= 5:
                late[d.year].append(hrs)
        total_by_hour = [sum(grid[w][h] for w in range(7)) for h in range(24)]
        out[k] = {"label": label, "count": n, "grid": grid,
                  "peak_hour": max(range(24), key=lambda h: total_by_hour[h]),
                  "peak_day": max(range(7), key=lambda w: sum(grid[w])),
                  "after_midnight": round(sum(total_by_hour[h] for h in range(0, 5)) / n, 3),
                  "weekend": round(sum(sum(grid[w]) for w in (5, 6)) / n, 3),
                  "years": {str(y): v for y, v in sorted(by_year.items())},
                  # Median time of the day's last activity, as hours after midnight (25.5 = 1:30 am).
                  "bedtime": {str(y): round(sorted(v)[len(v) // 2], 2) for y, v in sorted(late.items()) if len(v) >= 30}}
    pg.step(len(kinds))
    steps_by_day = [[] for _ in range(7)]
    steps_by_month = collections.defaultdict(list)
    for ts, meta in con.execute("select ts, meta from records where source = 'health' and kind = 'health_day'"):
        d = day_of(ts)
        if not d:
            continue
        s = steps_of(meta)
        if s:
            steps_by_day[d.weekday()].append(s)
            steps_by_month[d.strftime("%Y-%m")].append(s)
    steps = None
    if any(steps_by_day):
        steps = {"weekday": [round(sum(v) / len(v)) if v else 0 for v in steps_by_day],
                 "months": {m: round(sum(v) / len(v)) for m, v in sorted(steps_by_month.items())},
                 "days": sum(len(v) for v in steps_by_day)}
    return {"kinds": out, "steps": steps, "timezone": str(TZ)}


# ---------------------------------------------------------------- firsts

def firsts():
    with Progress(["Your people", "Places and countries", "Projects and apps"]) as pg:
        return _firsts(connect(), me_names(), pg)


def _firsts(con, mine, pg):
    items = []
    seen = set()
    pg.step(0)
    talked = {key(p["name"]) for p in cached("people", people)["people"] if p["messages"] >= 20}
    pg.step(0, count_where(con, MESSAGES))
    for k, who, source, t, is_me, rowid, _ in message_rows(con, mine, pg):
        if k not in seen:
            seen.add(k)
            items.append({"kind": "person", "what": who, "ts": t.isoformat(), "rowid": rowid, "detail": APP_NAMES.get(source, source)})
    # Only people you went on to talk to: a first message nobody answered isn't much of a first.
    items = [i for i in items if key(i["what"]) in talked]
    countries, first_at, place_days = set(), {}, collections.defaultdict(set)
    for t, _, _, place, country, rowid in located(con, pg, step=1):  # where you were, not where a saved picture was
        if country and country not in countries:
            countries.add(country)
            items.append({"kind": "country", "what": country, "ts": t.isoformat(), "rowid": rowid, "detail": place})
        if place:
            place_days[place].add(t.date())
            first_at.setdefault(place, {"kind": "place", "what": place, "ts": t.isoformat(), "rowid": rowid, "detail": country})
    # A place you were on three different days, not every café a photo happened to name.
    items += [first_at[p] for p, ds in place_days.items() if len(ds) >= 3]
    pg.step(2)
    repos = set()
    for rowid, ts, thread_name, title in con.execute("select rowid, ts, thread_name, title from records where source = 'git_commits' "
                                                     "and is_me = '1' and ts is not null order by ts"):
        t = parse(ts)
        if t and thread_name and thread_name not in repos:
            repos.add(thread_name)
            items.append({"kind": "project", "what": thread_name, "ts": t.isoformat(), "rowid": rowid, "detail": (title or "")[:80]})
    def first_of(source):
        """A source's first record with a time that can be right: (rowid, local time), or None."""
        for rowid, ts in con.execute("select rowid, ts from records where source = ? and ts > '1995' order by ts limit 200", (source,)):
            t = parse(ts)
            if t:
                return rowid, t
        return None

    apps = {}
    for source, label in APP_NAMES.items():
        if source in ("photos", "calendar", "apple_notes", "git_commits"):
            continue  # milestones below
        r = first_of(source)
        if r and (label not in apps or r[1].isoformat() < apps[label]["ts"]):
            apps[label] = {"kind": "app", "what": label, "ts": r[1].isoformat(), "rowid": r[0], "detail": None}
    items += apps.values()
    for kind_, src in (("photo", "photos"), ("note", "apple_notes"), ("commit", "git_commits")):
        r = first_of(src)
        if r:
            items.append({"kind": "milestone", "what": {"photo": "Your first photo", "note": "Your first note", "commit": "Your first commit"}[kind_],
                          "ts": r[1].isoformat(), "rowid": r[0], "detail": None})
    items.sort(key=lambda i: i["ts"])
    return {"items": items, "counts": dict(collections.Counter(i["kind"] for i in items))}


# ---------------------------------------------------------------- what you made

def made():
    con = connect()
    kinds = {
        "code": ("Code", "source = 'git_commits' and is_me = '1'"),
        "ai": ("AI conversations", "(source in ('ai_coding', 'chatgpt', 'claude_ai') or (source = 'x' and kind = 'ai_turn')) and is_me = '1'"),  # x: Grok
        "writing": ("Writing", "source in ('apple_notes', 'notion', 'notion_export') or (source = 'documents' and is_me = '1')"),
        "posts": ("Posts", "kind = 'post'"),
        "photos": ("Photos", "source = 'photos'"),
    }
    with Progress([label for label, _ in kinds.values()]) as pg:
        return _made(con, kinds, pg)


def _made(con, kinds, pg):
    days = collections.defaultdict(collections.Counter)
    totals = collections.defaultdict(collections.Counter)
    biggest = {}
    for si, (k, (label, where)) in enumerate(kinds.items()):
        pg.step(si)
        seen_threads = set()
        n = 0
        for rowid, ts, thread, meta in con.execute(f"select rowid, ts, thread, case when source = 'photos' then meta end from records "
                                                   f"where ({where}) and ts is not null"):
            t = parse(ts, meta_of(meta).get("timezone") if meta else None)
            if not t:
                continue
            n += 1
            pg.tick(n)
            if k == "ai":  # one per conversation per day, not one per prompt
                tag = (thread, t.date())
                if tag in seen_threads:
                    continue
                seen_threads.add(tag)
            d = t.date().isoformat()
            days[d][k] += 1
            totals[str(t.year)][k] += 1
            if days[d][k] > biggest.get(k, (0, None, None))[0]:
                biggest[k] = (days[d][k], d, rowid)
    active = sorted(d for d, c in days.items() if any(n for kk, n in c.items() if kk != "photos"))
    best, run, prev = (0, None, None), 0, None
    for d in active:
        cur = date.fromisoformat(d)
        run = run + 1 if prev and (cur - prev).days == 1 else 1
        if run > best[0]:
            best = (run, (cur - timedelta(days=run - 1)).isoformat(), d)
        prev = cur
    return {"labels": {k: v[0] for k, v in kinds.items()}, "days": {d: dict(c) for d, c in sorted(days.items())},
            "totals": {y: dict(c) for y, c in sorted(totals.items())},
            "busiest": {k: {"count": v[0], "date": v[1], "rowid": v[2]} for k, v in biggest.items()},
            "streak": {"days": best[0], "start": best[1], "end": best[2]}}


# ---------------------------------------------------------------- listening

# What the Mac said was playing (Now Playing): music apps only; the rest (Netflix, a video in a browser) is watching.
MUSIC_APPS = ("spotify", "music", "tidal", "deezer", "soundcloud", "pandora", "youtube music", "amazon music", "qobuz", "bandcamp")
QUARTER = lambda t: f"{t.year}-Q{(t.month - 1) // 3 + 1}"  # noqa: E731


def plays(con, pg=None):
    """(local time, track, artist, seconds or None, rowid, from) for every song played: Spotify's streaming history,
    what the Mac was playing in a music app, and YouTube's artist channels ("Artist - Topic" is YouTube Music's)."""
    where = ("ts is not null and ((source = 'spotify' and kind = 'media') or (source = 'app_usage' and kind = 'media') "
             "or (source = 'google_activity' and kind = 'media' and text like '%- Topic%'))")
    if pg:
        pg.step(0, count_where(con, where))
    out = []
    for i, (rowid, source, ts, title, text, meta) in enumerate(con.execute(f"select rowid, source, ts, title, text, meta from records where {where}")):
        if pg:
            pg.tick(i)
        m = meta_of(meta)
        if source == "spotify":
            artist, secs, via = m.get("artist"), m.get("seconds"), "Spotify"
            if isinstance(secs, (int, float)) and secs < 30:  # Spotify counts a play from 30 seconds; less is a skip
                continue
        elif source == "app_usage":
            if not any(a in str(m.get("app") or "").casefold() for a in MUSIC_APPS):
                continue
            artist, secs, via = m.get("artist"), m.get("duration"), str(m.get("app"))
        else:
            lines = (text or "").split("\n")
            channel = lines[1].strip() if len(lines) > 1 else ""
            if not channel.endswith(" - Topic"):
                continue
            artist, secs, via = channel[: -len(" - Topic")], None, "YouTube"
        t = parse(ts)
        if t and title and artist:
            out.append((t, str(title).strip(), str(artist).strip(), num(secs) if isinstance(secs, (int, float)) else None, rowid, via))
    out.sort(key=lambda p: p[0])
    return out


def listening():
    with Progress(["Songs you played", "Your artists over the years"]) as pg:
        return _listening(connect(), pg)


def _listening(con, pg):
    ps = plays(con, pg)
    pg.step(1)
    # Every play opens the latest of its kind: an artist's or song's latest play (in the year, for a year's), a day's
    # song on repeat that day, an era's in that era.
    artists, tracks, day_track, day_rowid = {}, {}, collections.Counter(), {}
    years = collections.defaultdict(lambda: {"plays": 0, "seconds": 0, "artists": collections.Counter(), "tracks": collections.Counter(), "hours": [0] * 24,
                                             "latest": {}})
    quarters = collections.defaultdict(collections.Counter)
    quarter_rowid = {}
    months, by_hour, weekday, via = collections.Counter(), [0] * 24, [0] * 7, collections.Counter()
    first_heard = {}
    for t, track, artist, secs, rowid, src in ps:
        a = artists.setdefault(artist, {"name": artist, "plays": 0, "seconds": 0, "first": t.isoformat(), "last": t.isoformat(), "rowid": rowid, "years": collections.Counter()})
        a["plays"] += 1
        a["seconds"] += secs or 0
        a["last"], a["rowid"] = t.isoformat(), rowid
        a["years"][str(t.year)] += 1
        tk = (track, artist)
        tr = tracks.setdefault(tk, {"title": track, "artist": artist, "plays": 0, "rowid": rowid, "first": t.isoformat()})
        tr["plays"] += 1
        tr["rowid"] = rowid
        day_track[(track, artist, t.date().isoformat())] += 1
        day_rowid[(track, artist, t.date().isoformat())] = rowid
        y = years[str(t.year)]
        y["plays"] += 1
        y["seconds"] += secs or 0
        y["artists"][artist] += 1
        y["tracks"][tk] += 1
        y["hours"][t.hour] += 1
        y["latest"][artist] = y["latest"][tk] = rowid
        first_heard.setdefault(artist, str(t.year))
        quarters[QUARTER(t)][artist] += 1
        quarter_rowid[(QUARTER(t), artist)] = rowid
        months[t.strftime("%Y-%m")] += 1
        by_hour[t.hour] += 1
        weekday[t.weekday()] += 1
        via[src] += 1
    new_by_year = collections.Counter(first_heard.values())
    # Your eras: each quarter's most-played artist, when they had a real share of it; the same artist quarter after
    # quarter is one era.
    eras = []
    for q in sorted(quarters):
        c = quarters[q]
        top, n = c.most_common(1)[0]
        if n < 10 or n < 0.08 * sum(c.values()):
            continue
        if eras and eras[-1]["artist"] == top:
            eras[-1]["end"], eras[-1]["plays"], eras[-1]["rowid"] = q, eras[-1]["plays"] + n, quarter_rowid[(q, top)]
        else:
            eras.append({"artist": top, "start": q, "end": q, "plays": n, "rowid": quarter_rowid[(q, top)]})

    def on_repeat(year=None, n=10):
        """One song three or more times in a day, most first."""
        return [{"title": tr, "artist": ar, "date": d, "plays": c, "rowid": day_rowid[(tr, ar, d)]}
                for (tr, ar, d), c in day_track.most_common() if c >= 3 and (year is None or d[:4] == year)][:n]
    repeat = on_repeat()
    rank = lambda xs, k: sorted(xs, key=lambda x: -x[k])  # noqa: E731
    top_artists = [{**a, "minutes": round(a["seconds"] / 60), "years": dict(sorted(a["years"].items()))} for a in rank(artists.values(), "plays")[:30]]
    for a in top_artists:
        del a["seconds"]
    return {
        "plays": len(ps), "minutes": round(sum(p[3] or 0 for p in ps) / 60), "artists": len(artists), "songs": len(tracks),
        "first": {"title": ps[0][1], "artist": ps[0][2], "ts": ps[0][0].isoformat(), "rowid": ps[0][4]} if ps else None,
        "last": ps[-1][0].isoformat() if ps else None, "from": dict(via.most_common()),
        "top_artists": top_artists, "top_tracks": rank(tracks.values(), "plays")[:30],
        "years": {yy: {"plays": v["plays"], "minutes": round(v["seconds"] / 60), "artists": len(v["artists"]), "new_artists": new_by_year.get(yy, 0),
                       "top_artists": [{"name": a, "plays": n, "rowid": v["latest"][a]} for a, n in v["artists"].most_common(10)],
                       "top_tracks": [{"title": tr, "artist": ar, "plays": n, "rowid": v["latest"][(tr, ar)]} for (tr, ar), n in v["tracks"].most_common(10)],
                       "by_hour": v["hours"], "on_repeat": on_repeat(yy)}
                  for yy, v in sorted(years.items())},
        "eras": eras, "on_repeat": repeat, "months": dict(sorted(months.items())), "by_hour": by_hour, "weekday": weekday,
    }


# ---------------------------------------------------------------- moving and sleep

STEP_GOAL = 10000


def movement():
    with Progress(["Your days", "Your nights", "Where you walked most"]) as pg:
        return _movement(connect(), pg)


def _movement(con, pg):
    pg.step(0)
    days = {}
    for rowid, ts, meta in con.execute("select rowid, ts, meta from records where source = 'health' and kind = 'health_day'"):
        m = meta_of(meta)
        d, steps = day_of(ts), steps_of(meta)
        if d and steps > 0:
            days[d] = (steps, num(m.get("distance_km")), num(m.get("flights")), rowid)
    ordered = sorted(days)
    years = collections.defaultdict(list)
    months = collections.defaultdict(list)
    weekday = [[] for _ in range(7)]
    for d in ordered:
        years[str(d.year)].append(d)
        months[d.strftime("%Y-%m")].append(days[d][0])
        weekday[d.weekday()].append(days[d][0])
    def streak(ds):
        """The longest run of days in a row over the goal."""
        best, run, prev, start = (0, None, None), 0, None, None
        for d in ds:
            if days[d][0] >= STEP_GOAL:
                if not (prev and (d - prev).days == 1 and run):
                    run, start = 0, d
                run += 1
                if run > best[0]:
                    best = (run, start.isoformat(), d.isoformat())
                prev = d
            else:
                run = 0
        return {"days": best[0], "start": best[1], "end": best[2]}
    avg = lambda xs: round(sum(xs) / len(xs)) if xs else 0  # noqa: E731
    dayrec = lambda d: {"date": d.isoformat(), "steps": round(days[d][0]), "km": round(days[d][1], 1), "rowid": days[d][3]}  # noqa: E731
    pg.step(1)
    nights = []
    for rowid, ts, end, meta in con.execute("select rowid, ts, ts_end, meta from records where source = 'health' and kind = 'sleep' and ts is not null"):
        m = meta_of(meta)
        a, b = parse(ts, m.get("tz")), parse(end, m.get("tz")) if end else None
        mins = num(m.get("asleep_min")) or num(m.get("in_bed_min"))
        if not a or not b or mins < 120:  # a nap, or a night the watch was off
            continue
        bed = a.hour + a.minute / 60 + (24 if a.hour < 15 else 0)  # 1 am is 25: late is later
        nights.append((b.date(), mins, bed, b.hour + b.minute / 60, rowid))
    nights.sort()
    sleep = None
    if nights:
        by_year = collections.defaultdict(list)
        for n in nights:
            by_year[str(n[0].year)].append(n)
        med = lambda xs: round(sorted(xs)[len(xs) // 2], 2)  # noqa: E731
        bed_months = collections.defaultdict(list)
        for n in nights:
            bed_months[n[0].strftime("%Y-%m")].append(n[2])
        weekdays = lambda ns: [avg([n[1] for n in ns if (n[0] - timedelta(days=1)).weekday() == w]) for w in range(7)]  # noqa: E731 - by the night it began
        night = lambda n: {"date": n[0].isoformat(), "minutes": round(n[1]), "rowid": n[4]}  # noqa: E731
        sleep = {"nights": len(nights), "avg_min": avg([n[1] for n in nights]),
                 "years": {y: {"nights": len(v), "avg_min": avg([n[1] for n in v]), "bedtime": med([n[2] for n in v]), "wake": med([n[3] for n in v]),
                               "weekday": weekdays(v), "longest": night(max(v, key=lambda n: n[1]))}
                           for y, v in sorted(by_year.items())},
                 "bedtime_months": {m: med(v) for m, v in sorted(bed_months.items()) if len(v) >= 5},
                 "weekday": weekdays(nights),
                 "longest": night(max(nights, key=lambda n: n[1])), "shortest": night(min(nights, key=lambda n: n[1]))}
    pg.step(2)
    # Your biggest days (of all, and each year's), and where you were (the place your photos that day name most), and
    # steps on trips.
    biggest = lambda ds: sorted(ds, key=lambda d: -days[d][0])[:10]  # noqa: E731
    top = biggest(ordered)
    where_on = collections.defaultdict(collections.Counter)
    if top:
        wanted = set(top).union(*(biggest(v) for v in years.values()))
        for t, _, _, place, _, _ in located(con):
            if t.date() in wanted and place:
                where_on[t.date()][place] += 1
    trip_days = set()
    if ordered:
        try:
            for tr in cached("places", places)["trips"]:
                trip_days |= {date.fromisoformat(tr["start"]) + timedelta(days=i) for i in range(tr["days"])}
        except FileNotFoundError:
            pass
    on_trips = [days[d][0] for d in ordered if d in trip_days]
    top_day = lambda d: {**dayrec(d), "place": where_on[d].most_common(1)[0][0] if where_on[d] else None, "trip": d in trip_days}  # noqa: E731
    return {
        "days": len(ordered), "first": ordered[0].isoformat() if ordered else None, "last": ordered[-1].isoformat() if ordered else None,
        "steps": round(sum(days[d][0] for d in ordered)), "km": round(sum(days[d][1] for d in ordered)), "avg": avg([days[d][0] for d in ordered]),
        "best": dayrec(top[0]) if top else None, "goal": STEP_GOAL, "goal_days": sum(1 for d in ordered if days[d][0] >= STEP_GOAL),
        "streak": streak(ordered),
        "years": {y: {"days": len(v), "avg": avg([days[d][0] for d in v]), "steps": round(sum(days[d][0] for d in v)), "km": round(sum(days[d][1] for d in v)),
                      "flights": round(sum(days[d][2] for d in v)), "best": dayrec(max(v, key=lambda d: days[d][0])),
                      "goal_days": sum(1 for d in v if days[d][0] >= STEP_GOAL), "streak": streak(v),
                      "weekday": [avg([days[d][0] for d in v if d.weekday() == w]) for w in range(7)], "top_days": [top_day(d) for d in biggest(v)]}
                  for y, v in sorted(years.items())},
        "months": {m: avg(v) for m, v in sorted(months.items())}, "weekday": [avg(v) for v in weekday],
        "top_days": [top_day(d) for d in top],
        "trips": {"avg": avg(on_trips), "days": len(on_trips), "home_avg": avg([days[d][0] for d in ordered if d not in trip_days])} if on_trips else None,
        "sleep": sleep,
    }


# ---------------------------------------------------------------- curiosity

SEARCH_FROM = SEARCHES + (("phone_safariwebsearch", "search"), ("phone_safarirecentwebsearches", "search"))
QUESTION = re.compile(r"^(who|what|when|where|why|how|is|are|can|does|do|did|should|will|which)\b", re.I)
# Words that say how you searched, not what about.
SEARCH_WORDS = set("""best near nearby free online com www http https org net google search youtube reddit wiki wikipedia
amazon review reviews vs versus meaning definition define example examples tutorial guide list open hours time today tomorrow
week year 2015 2016 2017 2018 2019 2020 2021 2022 2023 2024 2025 2026 2027 price cost cheap login sign download app apps pdf
recipe recipes ticket tickets reservation reservations hours tips ideas plan plans map schedule restaurant restaurants things
neighborhoods airport worth is to of my in on at an do it be by or as if me we us so up no vs""".split())
# The first word of a place's name: "new" in New York isn't a word to drop.
PLACE_START = {"new", "san", "santa", "los", "las", "saint", "st", "el", "la", "le", "rio", "west", "east", "north", "south"}


def searches(con, pg=None):
    """(local time, query, rowid) for every search, once: the same words searched in two places (Chrome's history and
    Google's, within the minute) count once. Searches inside Gmail and the Play Store aren't curiosity."""
    where = "ts is not null and (" + " or ".join(f"(source = '{s}' and kind = '{k}')" for s, k in SEARCH_FROM) + ")"
    if pg:
        pg.step(0, count_where(con, where))
    out, seen = [], set()
    for i, (rowid, source, ts, title, text, meta) in enumerate(con.execute(f"select rowid, source, ts, title, text, meta from records where {where}")):
        if pg:
            pg.tick(i)
        if source == "google_activity" and meta_of(meta).get("product") in ("Gmail", "Google Play Store"):
            continue
        q = re.sub(r"^Searched for\s+", "", str(title or (text or "").split("\n")[0]).strip())
        q = re.sub(r"\s+", " ", q).strip()
        t = parse(ts)
        if not q or not t or len(q) > 200:
            continue
        k = (q.casefold(), t.strftime("%Y-%m-%d %H:%M"))
        if k in seen:
            continue
        seen.add(k)
        out.append((t, q, rowid))
    out.sort(key=lambda s: s[0])
    return out


def search_terms(q):
    """A search's words, and its phrases of two to four words ("mexico city", "day of the dead"), without the words
    that only say how you searched; a phrase doesn't start or end with one of those."""
    words = re.findall(r"[^\W_]+(?:'[^\W_]+)?", q.casefold())  # a number stays, so a phrase doesn't run across it
    how = lambda w: w in SEARCH_WORDS or (w in STOPWORDS and w not in PLACE_START) or len(w) < 2 or any(c.isdigit() for c in w)  # noqa: E731
    out = {w for w in words if (len(w) > 2 or UNSPACED.search(w)) and not how(w) and w not in PLACE_START}
    for n in (2, 3, 4, 5):
        for i in range(len(words) - n + 1):
            g = words[i:i + n]
            if not how(g[0]) and not how(g[-1]) and g[-1] not in PLACE_START and not any(w in SEARCH_WORDS or any(c.isdigit() for c in w) for w in g):
                out.add(" ".join(g))
    return out


def first_asked(ss):
    """Each question once, the first time it was asked."""
    seen, out = set(), []
    for t, q, rowid in ss:
        if QUESTION.match(q) and q.casefold() not in seen:
            seen.add(q.casefold())
            out.append((t, q, rowid))
    return out


def curiosity():
    with Progress(["Your searches", "What you were curious about", "What you looked up before a trip"]) as pg:
        return _curiosity(connect(), pg)


def _curiosity(con, pg):
    ss = searches(con, pg)
    pg.step(1)
    queries, months, by_hour = {}, collections.Counter(), [0] * 24
    years = collections.defaultdict(list)
    term_years = collections.defaultdict(collections.Counter)
    term_example = {}
    term_queries = collections.defaultdict(set)  # a few of the searches each word came in, a year at a time
    year_queries = collections.defaultdict(dict)  # a year's searches, each with how often and its latest
    year_hours = collections.defaultdict(lambda: [0] * 24)
    for t, q, rowid in ss:
        k = q.casefold()
        e = queries.setdefault(k, {"q": q, "count": 0, "first": t.isoformat(), "last": t.isoformat(), "rowid": rowid})
        e["count"] += 1
        e["last"], e["rowid"] = t.isoformat(), rowid
        ye = year_queries[str(t.year)].setdefault(k, {"q": q, "count": 0, "first": t.isoformat(), "last": t.isoformat(), "rowid": rowid})
        ye["count"] += 1
        ye["last"], ye["rowid"] = t.isoformat(), rowid
        months[t.strftime("%Y-%m")] += 1
        by_hour[t.hour] += 1
        year_hours[str(t.year)][t.hour] += 1
        years[str(t.year)].append((t, q, rowid))
        for term in search_terms(q):
            term_years[term][str(t.year)] += 1
            term_example.setdefault((term, str(t.year)), rowid)
            if " " not in term and len(term_queries[(term, str(t.year))]) < 2:
                term_queries[(term, str(t.year))].add(k)
    n_years = max(1, len(years))

    weight = {1: 1.0, 2: 1.7, 3: 2.1, 4: 2.3, 5: 2.4}  # a phrase says more than a word

    def topics(y, n=12):
        """The year's own words: much more searched that year than in the others. Nothing that shares a word with
        one already picked (no "place market" after "pike place market")."""
        scored = []
        for term, c in term_years.items():
            here = c.get(y, 0)
            if here < 3:
                continue
            others = (sum(c.values()) - here) / max(1, n_years - 1)
            scored.append((here / (1 + others) * weight[len(term.split(" "))], term, here))
        scored.sort(reverse=True)
        out, used = [], set()
        for score, term, here in scored:
            ws = set(term.split(" ")) - PLACE_START
            if ws & used:
                continue
            if score < 0.2 * scored[0][0] or (" " not in term and (here < 5 or len(term) < 4 or len(term_queries[(term, y)]) < 2)):
                continue  # the tail: a word searched a few times, or in only one search, isn't what a year was about
            used |= ws
            out.append({"word": term, "count": here, "rowid": term_example[(term, y)]})
            if len(out) >= n:
                break
        return out

    # Each question once, in the year you first asked it: every year's add up to the number asked.
    asked = first_asked(ss)
    asked_in = collections.defaultdict(list)
    for t, q, rowid in asked:
        asked_in[str(t.year)].append({"q": q, "ts": t.isoformat(), "rowid": rowid})
    again = lambda qs: sorted((x for x in qs if x["count"] > 1), key=lambda x: -x["count"])[:25]  # noqa: E731
    pg.step(2)
    before = []
    try:
        for tr in cached("places", places)["trips"]:
            start = date.fromisoformat(tr["start"])
            # Where it was, by every name the trip's own photos give it (not the ones from home either side of it): a
            # trip is named for its city (Tokyo), and searched for by a neighborhood (Shinjuku) or its country.
            names = {p.casefold() for p in tr["places"] + tr["countries"] if p}
            ids = tr.get("photo_ids") or tr["sample"]
            for i in range(0, len(ids), 500):
                part = ids[i:i + 500]
                for (text,) in con.execute(f"select text from records where rowid in ({','.join('?' * len(part))})", part):
                    m = re.search(r"^Place: (.+)$", text or "", re.M)
                    names |= {p.strip().casefold() for p in (m.group(1).split(",") if m else []) if len(p.strip()) > 2}
            said = re.compile(r"\b(" + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)) + r")\b") if names else None
            hits = {}
            for t, q, rowid in ss:
                if said and start - timedelta(days=60) <= t.date() <= start and said.search(q.casefold()):
                    hits.pop(q.casefold(), None)
                    hits[q.casefold()] = {"q": q, "ts": t.isoformat(), "rowid": rowid}  # each search once, at its latest
            hits = list(hits.values())
            if hits:
                before.append({"trip": tr["id"], "places": tr["places"], "start": tr["start"], "days": tr["days"], "searches": hits[-8:], "count": len(hits)})
    except FileNotFoundError:
        pass
    return {
        "searches": len(ss), "queries": len(queries), "questions": len(asked),
        "first": {"q": ss[0][1], "ts": ss[0][0].isoformat(), "rowid": ss[0][2]} if ss else None, "last": ss[-1][0].isoformat() if ss else None,
        "top": again(queries.values()),
        "years": {y: {"count": len(v), "topics": topics(y), "questions": asked_in.get(y, []), "top": again(year_queries[y].values()), "by_hour": year_hours[y]}
                  for y, v in sorted(years.items())},
        "months": dict(sorted(months.items())), "by_hour": by_hour, "before_trips": sorted(before, key=lambda b: b["start"], reverse=True),
    }


# ---------------------------------------------------------------- watching

VIDEO_APPS = ("netflix", "youtube", "disney", "hulu", "max", "prime video", "apple tv", "tv", "twitch", "plex", "vlc", "iina", "infuse")


def videos(con, pg=None):
    """(local time, title, channel or show, service, rowid) for every video: YouTube (Google's history of it; artist
    channels are songs, and count in Listening), Netflix, TikTok, and video apps the Mac said were playing."""
    where = ("ts is not null and ((source = 'google_activity' and kind = 'media') or (source = 'phone_netflix' and kind = 'media') "
             "or (source = 'tiktok' and kind = 'watch') or (source = 'app_usage' and kind = 'media'))")
    if pg:
        pg.step(0, count_where(con, where))
    out = []
    for i, (rowid, source, ts, title, text, meta, url, author) in enumerate(con.execute(f"select rowid, source, ts, title, text, meta, url, author from records where {where}")):
        if pg:
            pg.tick(i)
        m = meta_of(meta)
        if source == "google_activity":
            if m.get("product") != "YouTube" and "youtube.com/watch" not in (url or ""):
                continue
            lines = (text or "").split("\n")
            channel = lines[1].strip() if len(lines) > 1 else None
            if channel and channel.endswith(" - Topic"):
                continue
            name, service = re.sub(r"^Watched\s+", "", str(title or lines[0])), "YouTube"
        elif source == "phone_netflix":
            f = m.get("fields") or {}
            name, service = str(f.get("Displayed Title") or f.get("Cached Title") or title or ""), "Netflix"
            channel = name.split(":")[0].strip() if ":" in name else name  # the show, before ": Season 1: Episode"
        elif source == "tiktok":
            name, channel, service = str(title or text or "A TikTok")[:120], author if author and author != "me" else None, "TikTok"
        else:
            app = str(m.get("app") or "")
            if not any(a == app.casefold() or app.casefold().startswith(a + " ") for a in VIDEO_APPS):
                continue
            name, channel, service = str(title or ""), m.get("artist") or None, app
        t = parse(ts)
        if t and name.strip():
            out.append((t, name.strip(), channel or None, service, rowid))
    out.sort(key=lambda v: v[0])
    return out


def watching():
    with Progress(["Videos you watched", "Channels and shows"]) as pg:
        return _watching(connect(), pg)


def _watching(con, pg):
    vs = videos(con, pg)
    pg.step(1)
    # Each opens its latest: a channel's latest video (in the year, for a year's), a video's latest watch.
    channels, titles, nights = {}, {}, collections.Counter()
    years = collections.defaultdict(lambda: {"count": 0, "channels": collections.Counter(), "latest": {}, "hours": [0] * 24, "titles": collections.Counter()})
    months, by_hour, weekday, services = collections.Counter(), [0] * 24, [0] * 7, collections.Counter()
    night_rowid, night_channels = {}, collections.defaultdict(collections.Counter)
    for t, name, channel, service, rowid in vs:
        y = years[str(t.year)]
        if channel:
            c = channels.setdefault(channel, {"name": channel, "count": 0, "first": t.isoformat(), "last": t.isoformat(), "rowid": rowid, "service": service, "years": collections.Counter()})
            c["count"] += 1
            c["last"], c["rowid"] = t.isoformat(), rowid
            c["years"][str(t.year)] += 1
            y["channels"][channel] += 1
            y["latest"][channel] = rowid
        tk = name.casefold()
        tt = titles.setdefault(tk, {"title": name, "channel": channel, "count": 0, "rowid": rowid, "service": service})
        tt["count"] += 1
        tt["rowid"] = rowid
        y["count"] += 1
        y["hours"][t.hour] += 1
        y["titles"][tk] += 1
        y["latest"][("title", tk)] = rowid
        months[t.strftime("%Y-%m")] += 1
        by_hour[t.hour] += 1
        weekday[t.weekday()] += 1
        services[service] += 1
        night = (t - timedelta(hours=5)).date().isoformat()  # an evening that runs past midnight is one evening
        nights[night] += 1
        night_rowid.setdefault(night, rowid)
        if channel:
            night_channels[night][channel] += 1
    top_ch = sorted(channels.values(), key=lambda c: -c["count"])[:25]

    def binges(year=None):
        """The evenings you watched most (four videos or more), most first."""
        return [{"date": d, "count": n, "rowid": night_rowid[d], "channel": night_channels[d].most_common(1)[0][0] if night_channels[d] else None}
                for d, n in nights.most_common() if n >= 4 and (year is None or d[:4] == year)][:8]

    def late(hours):
        return round(sum(hours[h] for h in range(0, 5)) / sum(hours), 3) if sum(hours) else 0
    return {
        "videos": len(vs), "channels": len(channels), "from": dict(services.most_common()),
        "first": {"title": vs[0][1], "channel": vs[0][2], "ts": vs[0][0].isoformat(), "rowid": vs[0][4]} if vs else None,
        "last": vs[-1][0].isoformat() if vs else None,
        "top_channels": [{**c, "years": dict(sorted(c["years"].items()))} for c in top_ch],
        "rewatched": sorted((x for x in titles.values() if x["count"] >= 2), key=lambda x: -x["count"])[:15],
        "years": {y: {"count": v["count"], "channels": len(v["channels"]),
                      "top_channels": [{"name": c, "count": n, "rowid": v["latest"][c]} for c, n in v["channels"].most_common(10)],
                      "rewatched": [{**titles[k], "count": n, "rowid": v["latest"][("title", k)]} for k, n in v["titles"].most_common() if n >= 2][:15],
                      "binges": binges(y), "after_midnight": late(v["hours"]), "by_hour": v["hours"]}
                  for y, v in sorted(years.items())},
        "binges": binges(),
        "after_midnight": late(by_hour),
        "months": dict(sorted(months.items())), "by_hour": by_hour, "weekday": weekday,
    }


# ---------------------------------------------------------------- what they know

# What advertisers and the services keep about you, from your exports (connectors/imports.py: kind advertiser,
# inference, off_platform and ad). An older import kept some of it under the file it came from: that's read too.
SERVICE_OF = {"facebook_activity": "Facebook", "instagram_activity": "Instagram", "x": "X", "linkedin": "LinkedIn",
              "tiktok": "TikTok", "google_activity": "Google", "spotify": "Spotify"}
WHAT_OF_FILE = {"interest_categories": "interest", "see_less_topics": "see less", "inferences_about_you.csv": "Inferences",
                "other_categories_used_to_reach_you": "category"}
# Guesses at who you are (as against what you're into), and what you're into.
GUESSES = {"gender", "age", "language", "location", "audiences", "category", "Member Age", "Member Gender", "Member Traits",
           "High Value Audience Segments", "Standard Audience Segments", "Buyer Groups", "Job Seniorities", "Years of Experience",
           "Inferred personal characteristics", "Career inferences", "Profile Locations", "Job Functions", "Inferences", "segment"}
INTERESTS = {"interest", "Member Interests", "Inferred interests", "partner interest", "show", "see less"}
WHAT_LABEL = {"interest": "Interests", "show": "Shows you watch", "category": "Categories you're reached under", "gender": "Your gender",
              "age": "Your age", "language": "Languages", "location": "Where you are", "audiences": "Audiences you're in",
              "see less": "Topics you asked to see less of", "partner interest": "Interests from its partners",
              "segment": "Ad segments you're in", "artist listener": "The kind of listener you are, artist by artist"}
AD_FILES = ("ads_viewed",)


def they_know():
    with Progress(["Advertisers that have you", "What they decided about you", "Who told them what you did elsewhere"]) as pg:
        return _they_know(connect(), pg)


def _alnum(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").casefold())


def _they_know(con, pg):
    def svc(source, m):
        return m.get("service") or SERVICE_OF.get(source, source)

    # Advertisers: one entry a name, with each service it has you on and how it got you there.
    adv, hows = {}, collections.defaultdict(collections.Counter)
    for rowid, source, title, meta in con.execute("select rowid, source, title, meta from records where kind = 'advertiser'"):
        m, name = meta_of(meta), (title or "").strip()
        if not name:
            continue
        s, how = svc(source, m), m.get("how") or "list"
        # One entry for a company however it's written: X's "@airbnb" is Meta's "Airbnb". Its name, not its handle.
        a = adv.setdefault(_alnum(name.lstrip("@")) or name, {"name": name, "services": {}, "rowid": rowid})
        if a["name"].startswith("@") and not name.startswith("@"):
            a["name"], a["rowid"] = name, rowid
        if how not in a["services"].setdefault(s, []):
            a["services"][s].append(how)
            hows[s][how] += 1
    # Which of them you've heard from: an advertiser named like an email's sender, or like its domain.
    senders = set()
    for (frm,) in con.execute("select json_extract(meta, '$.from') from records where kind = 'email' and json_extract(meta, '$.from') is not null"):
        mm = re.match(r'\s*"?([^"<]*?)"?\s*<([^>]*)>', str(frm))
        name_, addr = (mm.group(1), mm.group(2)) if mm else ("", str(frm))
        if name_.strip():
            senders.add(_alnum(name_))
        parts = [p for p in addr.split("@")[-1].lower().split(".") if p not in ("com", "net", "org", "co", "io", "us", "uk", "mail", "email", "e", "em", "news", "info", "www")]
        if "@" in addr and parts:
            senders.add(_alnum(parts[-1]))
    for a in adv.values():
        k = _alnum(a["name"].lstrip("@"))
        a["emailed"] = len(k) >= 3 and k in senders
    pg.step(1)

    # What each service decided about you, by what it is (an interest, your age, a segment, a LinkedIn targeting
    # column...). X lets you turn an interest off: those say so.
    decided = {}
    for rowid, source, title, meta in con.execute("select rowid, source, title, meta from records where kind = 'inference'"):
        m, value = meta_of(meta), (title or "").strip()
        what = m.get("what") or WHAT_OF_FILE.get(str(m.get("file")), str(m.get("file") or "inference"))
        if not value or what == "ad_targeting.csv":  # an older import's whole LinkedIn targeting file, as one record
            continue
        s = svc(source, m)
        g = decided.setdefault((s, what), {"service": s, "what": what, "label": WHAT_LABEL.get(what, what), "items": [],
                                           "group": "guess" if what in GUESSES else "interest" if what in INTERESTS else "other"})
        g["items"].append({"value": value, "rowid": rowid, **({"off": True} if m.get("turned_off") else {})})
    pg.step(2)

    # Who told them what you did elsewhere: companies (an app, a shop's website) that sent a service your activity.
    told, told_months = [], collections.Counter()
    for rowid, source, kind, title, ts, text, meta in con.execute(
            "select rowid, source, kind, title, ts, text, meta from records where kind = 'off_platform' "
            "or (kind = 'record' and json_extract(meta, '$.file') = 'your_activity_off_meta_technologies')"):
        m = meta_of(meta)
        ev = m.get("events") or ([{"type": t, "ts": None} for t in re.findall(r"^Event: (.+)$", text or "", re.M)] if kind == "record" else [])
        types = collections.Counter(e.get("type") for e in ev if e.get("type"))
        times = sorted(e["ts"] for e in ev if e.get("ts"))
        for t in times:
            told_months[t[:7]] += 1
        told.append({"name": (title or "").strip() or "A company", "service": svc(source, m), "events": len(ev), "types": dict(types.most_common()),
                     "first": times[0] if times else ts, "last": times[-1] if times else ts, "rowid": rowid,
                     # each one, for the timeline (the most recent 400)
                     "timeline": sorted(({"type": e.get("type"), "ts": e["ts"]} for e in ev if e.get("ts")), key=lambda e: e["ts"])[-400:]})
    told.sort(key=lambda x: (-x["events"], x["name"].casefold()))

    # Ads you were shown: Instagram's and X's, and your Google ad activity.
    ads, ad_by, ad_months, ad_rowid = collections.Counter(), collections.Counter(), collections.Counter(), {}
    for rowid, source, title, ts, meta in con.execute(
            "select rowid, source, title, ts, meta from records where kind = 'ad' or (source = 'google_activity' and json_extract(meta, '$.product') = 'Ads') "
            "or (kind = 'record' and json_extract(meta, '$.file') = 'ads_viewed')"):
        m = meta_of(meta)
        s = svc(source, m)
        ads[s] += 1
        if ts:
            ad_months[ts[:7]] += 1
        if s != "Google" and title and title not in ("An ad", "ads viewed"):
            ad_by[title] += 1
            ad_rowid.setdefault(title, rowid)

    # Meta keeps one ad profile for Facebook and Instagram: the same list from both is said once, as both's.
    merged = {}
    for g in decided.values():
        k = (g["what"], tuple(sorted(i["value"] for i in g["items"])))
        if k in merged:
            merged[k]["services"].append(g["service"])
        else:
            merged[k] = {**g, "services": [g["service"]]}
    for g in merged.values():
        g["service"] = " and ".join(g["services"])

    services = sorted({s for a in adv.values() for s in a["services"]} | {g["service"] for g in decided.values()} | {t["service"] for t in told} | set(ads),
                      key=lambda s: -(sum(1 for a in adv.values() if s in a["services"]) + sum(len(g["items"]) for g in decided.values() if g["service"] == s)))
    order = {"guess": 0, "interest": 1, "other": 2}
    return {
        "advertisers": len(adv),
        "on_lists": sum(1 for a in adv.values() if any("list" in h for h in a["services"].values())),
        "from_activity": sum(1 for a in adv.values() if any(set(h) & {"activity", "store"} for h in a["services"].values())),
        "emailed": sum(1 for a in adv.values() if a["emailed"]),
        "decided_count": sum(len(g["items"]) for g in merged.values()), "told_count": len(told), "ads_count": sum(ads.values()),
        "services": [{"service": s, "advertisers": sum(1 for a in adv.values() if s in a["services"]), "how": dict(hows[s]),
                      "decided": sum(len(g["items"]) for g in decided.values() if g["service"] == s),
                      "told": sum(1 for t in told if t["service"] == s), "ads": ads.get(s, 0)} for s in services],
        "advertiser_list": sorted(adv.values(), key=lambda a: (-len(a["services"]), not any("list" in h for h in a["services"].values()), a["name"].casefold())),
        "decided": sorted(merged.values(), key=lambda g: (services.index(g["services"][0]) if g["services"][0] in services else 99, order[g["group"]], -len(g["items"]))),
        "told": told, "told_months": dict(sorted(told_months.items())),
        "ads": {"by_service": dict(ads.most_common()), "top": [{"name": n, "count": c, "rowid": ad_rowid[n]} for n, c in ad_by.most_common(30)],
                "months": dict(sorted(ad_months.items()))},
    }


# ---------------------------------------------------------------- group chats

_LABELS = {}


def app_label(source, con=None):
    """A source's name in plain words: "imessage" -> "Messages". For one this file doesn't know by name, the app its
    records say they came from (an iPhone backup's "X - Direct Messages" -> "X"), else its own name tidied
    ("phone_wechat" -> "Wechat")."""
    if source in APP_NAMES:
        return APP_NAMES[source]
    if source not in _LABELS:
        art = None
        if con is not None:
            r = con.execute("select json_extract(meta, '$.artifact') from records where source = ? and json_valid(meta) "
                            "and json_extract(meta, '$.artifact') like '% - %' limit 1", (source,)).fetchone()
            art = r[0].split(" - ")[0].strip() if r and r[0] else None
        s = re.sub(r"^(phone|takeout)_", "", source or "").replace("_", " ").strip()
        _LABELS[source] = art or (s[:1].upper() + s[1:] if s else "An app")
    return _LABELS[source]


# Words that say nothing about one chat in particular. English only: in other languages a chat's own words still
# stand out by how rare they are in your other chats.
STOPWORDS = set("""about above after again against also always another anyone anything around because been before being
below between both cannot could couldn did didn does doesn doing done don down during each else even ever every from
further going gonna gotta had hadn has hasn have haven having here hers herself him himself his how into isn its itself
just know last least less let like lol lmao made make many might more most much must myself need never next nope not now
off okay once one only other our ours out over own really said same say says see shall she should shouldn some something
still such sure than thank thanks that the their theirs them then there these they thing things think this those though
through time too under until upon very want wanna was wasn way well were weren what when where whether which while who
whom whose why will with won would wouldn yeah yea yes yep you your yours yourself are and but for can get got all any
him her its our out was who why how did has had may now new way use too two say she his day see top let ill ive youre
theyre thats dont cant wont didnt doesnt isnt wasnt arent haha hahaha hahahaha omg idk tbh rn ngl its im ive id youve
youd youll hes shes whats lets theres wheres heres aint gonna yall thing gotta lmk""".split())
REACTED = re.compile(r"^(Loved|Liked|Disliked|Laughed at|Emphasized|Questioned|Reacted|Removed)\b[^“\"]*[“\"]")
URLS = re.compile(r"https?://\S+|www\.\S+")
WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?")
EMOJI = re.compile("[\U0001F300-\U0001F3FA\U0001F400-\U0001FAFF☀-➿⭐❤]")
UNSPACED = re.compile(r"[฀-๿぀-ヿ㐀-鿿가-힯]")  # scripts written without spaces between words


# Messages with a business (an Airbnb host and its support), not chats of yours.
NOT_CHATS = ("phone_airbnb",)


def groups():
    with Progress(["Finding your group chats", "Reading what was said", "Finding each chat's own words"]) as pg:
        return _groups(connect(), me_names(), pg)


def _groups(con, mine, pg):
    """Every conversation with two or more other people in it, from any app: one an app marks as a group, one
    whose participants list two or more others, or one where two or more others wrote. A conversation an export
    keeps only your side of isn't one you can see the others in, so it's left out."""
    is_me = lambda a: key(a) in mine or key(a) in ("me", "you")
    where = f"kind = 'message' and thread is not null and ts is not null and source not in ({','.join(repr(x) for x in NOT_CHATS)})"
    pg.step(0, count_where(con, where))
    T = {}
    for i, (source, th, name, author, me, parts, meta) in enumerate(con.execute(
            f"select source, thread, thread_name, author, is_me, participants, meta from records where {where}")):
        pg.tick(i)
        t = T.get((source, th))
        if t is None:
            t = T[(source, th)] = {"n": 0, "mine": 0, "others": set(), "parts": None, "flag": False, "name": name}
        t["n"] += 1
        if str(me) == "1" or (author and is_me(author)):
            t["mine"] += 1
        elif author and len(t["others"]) < 50:
            t["others"].add(author)
        if t["parts"] is None and parts:
            t["parts"] = {p.strip() for p in parts.split(",") if p.strip() and not is_me(p.strip())}
        if not t["flag"] and meta and '"group": true' in meta:
            t["flag"] = True
        if name and not t["name"]:
            t["name"] = name
    chosen = {k: t for k, t in T.items() if t["n"] >= 20 and t["n"] > t["mine"]
              and (t["flag"] or len(t["parts"] or ()) >= 2 or len(t["others"]) >= 2)}
    del T
    pg.step(1, sum(t["n"] for t in chosen.values()))
    G = {k: {"by": collections.Counter(), "night": collections.Counter(), "emoji_msgs": collections.Counter(), "chars": collections.Counter(),
             "months": collections.Counter(), "hours": [0] * 24, "days": collections.Counter(), "day_rowid": {}, "first": None, "last": None,
             "shapes": {}, "emoji": collections.Counter(), "n": 0} for k in chosen}
    shapes_seen = {}  # shape -> [times, up to three of the people who wrote it]
    try:
        mine_words = [str(n).casefold() for n in json.loads((CORPUS / "identity.json").read_text()).get("names") or [] if n]
    except (OSError, ValueError, AttributeError, TypeError):
        mine_words = []
    threads = sorted({th for _, th in chosen})
    done = 0
    for c in range(0, len(threads), 400):
        ths = threads[c:c + 400]
        for rowid, source, th, ts, author, me, text in con.execute(
                f"select rowid, source, thread, ts, author, is_me, text from records where kind = 'message' and ts is not null "
                f"and thread in ({','.join('?' * len(ths))})", ths):
            g = G.get((source, th))
            if g is None:
                continue
            done += 1
            pg.tick(done)
            t = parse(ts)
            if not t:
                continue
            # Some exports leave out who wrote a message: it counts toward the chat, not toward anyone in it.
            who = "You" if str(me) == "1" or (author and is_me(author)) else (" ".join((author or "").split()) or None)
            g["n"] += 1
            if who:
                g["by"][who] += 1
            g["months"][t.strftime("%Y-%m")] += 1
            g["hours"][t.hour] += 1
            d = t.date().isoformat()
            g["days"][d] += 1
            g["day_rowid"].setdefault(d, (ts, rowid))
            if ts < g["day_rowid"][d][0]:
                g["day_rowid"][d] = (ts, rowid)
            if g["first"] is None or ts < g["first"][0]:
                g["first"] = (ts, rowid)
            if g["last"] is None or ts > g["last"][0]:
                g["last"] = (ts, rowid)
            if t.hour < 5 and who:
                g["night"][who] += 1
            body = re.sub(r"\[attachment: [^\]]*\]", " ", text or "")
            if REACTED.match(body):
                continue
            if who:
                g["chars"][who] += len(body)
            em = [e for e in EMOJI.findall(body)]
            if em:
                if who:
                    g["emoji_msgs"][who] += 1
                g["emoji"].update(em)
            who = who or "?"  # for telling one writer from another below
            # Words are kept by the message's shape (its text without its author's name or numbers), so lines an app
            # writes itself ("Grace sent an attachment.", "Membership updated") can be told apart afterwards.
            low = URLS.sub(" ", body).casefold().replace("’", "'")
            names = ["you", "me", *mine_words] if who == "You" else [author.casefold(), *author.casefold().split()[:1]] if author else []
            names = [n for n in names if n.strip()]
            shape = re.sub(r"\d+", "#", re.sub("|".join(rf"\b{re.escape(n)}\b" for n in names), " ", low) if names else low)
            shape = " ".join(shape.split())
            e = g["shapes"].get(shape)
            if e is None:
                g["shapes"][shape] = [1, {who}]
            else:
                e[0] += 1
                if len(e[1]) < 2:
                    e[1].add(who)
            seen = shapes_seen.get(shape)
            if seen is None:
                shapes_seen[shape] = [1, {who}]
            else:
                seen[0] += 1
                if len(seen[1]) < 3:
                    seen[1].add(who)
    # A line an app writes itself: short, and word for word the same from three or more people once their own names
    # are taken out, many times over. People rarely type the same line as each other; "X sent an attachment." does.
    template = {sh for sh, (c, who) in shapes_seen.items() if c >= 20 and len(who) >= 3 and len(sh.split()) <= 8}
    pg.step(2, len(G))
    for g in G.values():
        words = {}
        for sh, (c, who) in g["shapes"].items():
            if sh in template:
                continue
            for w in WORD.findall(sh):
                w = w.replace("'", "")
                if 3 <= len(w) <= 24 and w not in STOPWORDS and not UNSPACED.search(w):
                    e = words.setdefault(w, [0, set()])
                    e[0] += c
                    if len(e[1]) < 2:
                        e[1] |= who
        g["words"] = words
        del g["shapes"]
    # A chat's own words: ones two or more of you use often, and far more there than in your other chats.
    total = collections.Counter()
    for g in G.values():
        for w, (c, _) in g["words"].items():
            total[w] += c
    n_all = sum(total.values())
    out = []
    for i, ((source, th), g) in enumerate(G.items()):
        pg.tick(i)
        t = chosen[(source, th)]
        n = g["n"]
        if not n or not g["first"]:
            continue
        for short_, long_ in same_people(set(g["by"]) - {"You"} | (t["parts"] or set())):
            g["by"][long_] += g["by"].pop(short_, 0)
            g["night"][long_] += g["night"].pop(short_, 0)
            g["emoji_msgs"][long_] += g["emoji_msgs"].pop(short_, 0)
            g["chars"][long_] += g["chars"].pop(short_, 0)
            if t["parts"]:
                t["parts"].discard(short_)
        spoke = {key(m) for m in g["by"]}
        members = sorted((set(g["by"]) - {"You"}) | {m for m in (t["parts"] or ()) if key(m) not in spoke}, key=lambda m: -g["by"].get(m, 0))
        names = {tok for m in members + [t["name"] or ""] for tok in WORD.findall(m.casefold())}
        n_g = sum(c for c, _ in g["words"].values()) or 1
        scored = []
        for w, (c, who) in g["words"].items():
            if c < 4 or len(who) < 2 or w in names:
                continue
            ratio = (c / n_g) / ((total[w] - c + 1) / (n_all - n_g + 1))
            if len(G) < 3 or ratio >= 3:  # with only a chat or two, there's nothing to compare against
                scored.append((c * math.log(max(ratio, 1.01)) if len(G) >= 3 else c, w, c))
        scored.sort(reverse=True)
        busiest = max(g["days"].items(), key=lambda kv: (kv[1], kv[0]))
        out.append({"key": hashlib.sha1(f"{source}\0{th}".encode()).hexdigest()[:12], "source": source, "app": app_label(source, con),
                    "name": group_title(t["name"], members), "named": not unnamed(t["name"], members),
                    "messages": n, "mine": g["by"].get("You", 0), "member_count": len(members),
                    "members": [{"name": m, "messages": c} for m, c in g["by"].most_common(12)],
                    "first": {"ts": parse(g["first"][0]).isoformat(), "rowid": g["first"][1]},
                    "last": {"ts": parse(g["last"][0]).isoformat(), "rowid": g["last"][1]},
                    "months": dict(sorted(g["months"].items())), "hours": g["hours"],
                    "busiest": {"date": busiest[0], "messages": busiest[1], "rowid": g["day_rowid"][busiest[0]][1]},
                    "words": [{"word": w, "count": c} for _, w, c in scored[:12]],
                    "emoji": [{"emoji": e, "count": c} for e, c in g["emoji"].most_common(8)],
                    "superlatives": superlatives(g, n)})
    out.sort(key=lambda x: -x["messages"])
    return {"groups": out, "messages": sum(x["messages"] for x in out), "apps": sorted({x["app"] for x in out})}


def same_people(names):
    """(shorter, longer) for names in one chat that are one person: a first name alone, or with an initial, next to
    the only full name it fits ("Grace" and "Grace Hopper", "Ada L" and "Ada Lovelace")."""
    out = []
    for a in names:
        wa = a.casefold().split()
        if not wa or len(wa) > 2 or (len(wa) == 2 and len(wa[1].rstrip(".")) != 1):
            continue
        fits = [b for b in names if b != a and len(b.split()) >= 2 and b.casefold().split()[0] == wa[0]
                and (len(wa) == 1 or b.casefold().split()[1].startswith(wa[1].rstrip(".")))]
        if len(fits) == 1:
            out.append((a, fits[0]))
    return out


def unnamed(name, members):
    """A chat nobody named: no name, or its name is just its members' names ("Grace H, Alan Turing")."""
    parts = [p.strip() for p in (name or "").split(",") if p.strip()]
    known = {key(m) for m in members}
    return not parts or (len(parts) >= 2 and all(key(p) in known for p in parts))


def group_title(name, members):
    """A chat's name; for one nobody named, its members' first names, in the order the app lists them."""
    if not unnamed(name, members):
        return name
    listed = [p.strip() for p in (name or "").split(",") if p.strip()] or members
    first = [m if re.match(r"^[+\d(]", m) else m.split()[0] for m in listed[:3]]
    rest = len(listed) - len(first)
    return ", ".join(first) + (f" and {rest} more" if rest > 0 else "") if first else (name or "A group")


def superlatives(g, n):
    """Who stands out in a chat: talks most, writes late, uses the most emoji, writes the longest. Only people with a
    fair share of the messages count."""
    floor = max(15, n * 0.03)
    who = [w for w, c in g["by"].items() if c >= floor]
    if len(who) < 2:
        return []
    out = []
    top = max(who, key=lambda w: g["by"][w])
    out.append({"title": "Talks most", "glyph": "bubbles", "name": top, "value": f"{round(100 * g['by'][top] / n)}% of the messages"})
    night = max(who, key=lambda w: g["night"][w] / g["by"][w])
    if g["night"][night] / g["by"][night] >= 0.05:
        out.append({"title": "Night owl", "glyph": "clock", "name": night, "value": f"{round(100 * g['night'][night] / g['by'][night])}% after midnight"})
    emo = max(who, key=lambda w: g["emoji_msgs"][w] / g["by"][w])
    if g["emoji_msgs"][emo] / g["by"][emo] >= 0.05:
        out.append({"title": "Uses the most emoji", "glyph": "sparkle", "name": emo,
                    "value": f"in {round(100 * g['emoji_msgs'][emo] / g['by'][emo])}% of {'your' if emo == 'You' else 'their'} messages"})
    long_ = max(who, key=lambda w: g["chars"][w] / g["by"][w])
    out.append({"title": "Writes the longest", "glyph": "note", "name": long_, "value": f"{round(g['chars'][long_] / g['by'][long_])} characters a message"})
    return out


# ---------------------------------------------------------------- journeys

def journeys():
    with Progress(["Reading where you were", "Finding when you moved", "Adding it up"]) as pg:
        return _journeys(connect(), pg)


def _journeys(con, pg):
    """Every time you went somewhere far: consecutive places you were, from any record that says where (photos,
    videos, check-ins), more than 150 km apart. A move counts as a flight when nothing on the ground is that fast
    (250 km/h over the whole gap, faster than a high-speed train averages), or when it crosses 2,500 km within three
    days."""
    pts = located(con, pg)
    pg.step(1, len(pts))
    stays = []  # runs of places within 60 km of each other
    for i, (t, lat, lon, place, country, rowid) in enumerate(pts):
        pg.tick(i)
        s = stays[-1] if stays else None
        if s and km((s["lat"], s["lon"]), (lat, lon)) <= 60:
            s["n"] += 1
            s["lat"] += (lat - s["lat"]) / s["n"]
            s["lon"] += (lon - s["lon"]) / s["n"]
            s["end"], s["last"] = t, rowid
        else:
            s = {"lat": lat, "lon": lon, "n": 1, "start": t, "end": t, "first": rowid, "last": rowid,
                 "places": collections.Counter(), "countries": collections.Counter()}
            stays.append(s)
        if place:
            s["places"][place] += 1
        if country:
            s["countries"][country] += 1

    # A place you'd have had to reach and leave faster than a jet flies is pictures from somewhere else.
    changed = True
    while changed:
        changed = False
        for i in range(1, len(stays) - 1):
            a, s, b = stays[i - 1], stays[i], stays[i + 1]
            out_, back = km((a["lat"], a["lon"]), (s["lat"], s["lon"])), km((s["lat"], s["lon"]), (b["lat"], b["lon"]))
            hours = max(0.05, (b["start"] - a["end"]).total_seconds() / 3600)
            if out_ > 300 and back > 300 and (out_ + back) / hours > 900:
                del stays[i]
                changed = True
                break

    def where(s):
        return {"lat": round(s["lat"], 3), "lon": round(s["lon"], 3), "place": s["places"].most_common(1)[0][0] if s["places"] else None,
                "country": s["countries"].most_common(1)[0][0] if s["countries"] else None}

    pg.step(2)
    legs = []
    for a, b in zip(stays, stays[1:]):
        d = km((a["lat"], a["lon"]), (b["lat"], b["lon"]))
        if d <= 150:
            continue
        hours = max(0.5, (b["start"] - a["end"]).total_seconds() / 3600)
        flew = d >= 300 and (d / hours >= 250 or (d >= 2500 and hours <= 72))
        legs.append({"from": where(a), "to": where(b), "left": a["end"].date().isoformat(), "arrived": b["start"].date().isoformat(),
                     "km": round(d), "flew": flew, "from_rowid": a["last"], "to_rowid": b["first"]})
    by_year = collections.defaultdict(lambda: {"km": 0, "flights": 0, "legs": 0, "countries": set(), "order": {}, "cities": collections.defaultdict(lambda: {"days": set(), "rowid": None, "country": None})})
    for leg in legs:
        y = by_year[leg["arrived"][:4]]
        y["km"] += leg["km"]
        y["legs"] += 1
        y["flights"] += leg["flew"]
    countries, cities = {}, collections.defaultdict(lambda: {"days": set(), "rowid": None, "country": None})
    for t, lat, lon, place, country, rowid in pts:
        y = by_year[str(t.year)]
        if country:
            y["countries"].add(country)
            countries.setdefault(country, {"country": country, "date": t.date().isoformat(), "rowid": rowid})
            y["order"].setdefault(country, {"country": country, "date": t.date().isoformat(), "rowid": rowid})
        if place:
            for c in (cities[(place, country)], y["cities"][(place, country)]):
                c["days"].add(t.date())
                c["rowid"] = c["rowid"] or rowid
                c["country"] = country

    def most_days(cs):
        return [{"place": p, "country": c["country"], "days": len(c["days"]), "rowid": c["rowid"]}
                for (p, _), c in sorted(cs.items(), key=lambda kv: -len(kv[1]["days"]))[:16]]
    total = sum(leg["km"] for leg in legs)
    return {"legs": legs[::-1], "km": total, "flights": sum(leg["flew"] for leg in legs),
            "km_flown": sum(leg["km"] for leg in legs if leg["flew"]),
            "longest": max(legs, key=lambda leg: leg["km"]) if legs else None,
            # A year's countries in the order you went that year, and where its days were.
            "by_year": {y: {**v, "countries": sorted(v["countries"]), "order": list(v["order"].values()), "cities": most_days(v["cities"])}
                        for y, v in sorted(by_year.items())},
            "countries": list(countries.values()),
            "cities": most_days(cities),
            "points": len(pts), "first": pts[0][0].date().isoformat() if pts else None}


# Records that say where you were when they were made (not, say, an address in a contact).
WHERE_YOU_WERE = ("photo", "video", "checkin", "location")
# A picture saved from one of these was taken by someone else, somewhere else: its location isn't yours. (Ones from
# a camera, including camera apps and glasses, are.) Compared without case, spaces or marks.
SAVED_FROM = {re.sub(r"\W", "", a).casefold() for a in (
    "Messages", "WhatsApp", "Messenger", "Instagram", "WeChat", "Telegram", "Signal", "Snapchat", "Discord", "Slack", "LINE",
    "Viber", "QQ", "KakaoTalk", "X", "Twitter", "Facebook", "TikTok", "Threads", "Reddit", "Pinterest", "Safari", "Chrome",
    "Firefox", "Mail", "Gmail", "Outlook", "Files", "Drive", "Dropbox", "AirDrop", "Teams", "Zoom", "Skype")}


def located(con, pg=None, step=0):
    """(local time, lat, lon, place, country, rowid) for every record that says where you were, by time. A point far
    from the ones either side of it that nothing could have reached in time (a picture saved with someone else's
    location, a wrong clock) is left out."""
    # Not photos others shared with you (photos.py's shared_photos): where they were, not you.
    where = (f"kind in ({','.join(repr(k) for k in WHERE_YOU_WERE)}) and source != 'shared_photos' and ts is not null "
             "and json_extract(meta, '$.lat') is not null")
    if pg:
        pg.step(step, count_where(con, where))
    pts = []
    for i, (rowid, ts, text, meta) in enumerate(con.execute(f"select rowid, ts, text, meta from records where {where}")):
        if pg:
            pg.tick(i)
        m = meta_of(meta)
        try:
            lat, lon = float(m["lat"]), float(m["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):  # not a place on Earth (nor NaN)
            continue
        if abs(lat) < 0.01 and abs(lon) < 0.01:  # "no location" written as 0,0
            continue
        if re.sub(r"\W", "", str(m.get("imported_by") or "")).casefold() in SAVED_FROM:
            continue
        t = parse(ts, m.get("timezone"))
        if not t:
            continue
        place, country = place_parts(text)
        pts.append((t, lat, lon, place or m.get("place") or m.get("city"), country or m.get("country"), rowid))
    pts.sort(key=lambda p: p[0])

    def impossible(a, b):
        d = km((a[1], a[2]), (b[1], b[2]))
        return d > 300 and d / max(0.05, abs((b[0] - a[0]).total_seconds()) / 3600) > 1100

    return [p for i, p in enumerate(pts) if not (0 < i < len(pts) - 1 and impossible(pts[i - 1], p) and impossible(p, pts[i + 1]))]


# ---------------------------------------------------------------- your year

# What you did, by kind, for your busiest day; kinds this file doesn't know still count toward it.
YEAR_KINDS = {"message": "messages", "photo": "photos", "video": "videos", "email": "emails", "search": "searches",
              "visit": "pages visited", "commit": "commits", "note": "notes", "document": "documents", "post": "posts",
              "call": "calls", "voice_memo": "voice memos", "ai_turn": "AI prompts", "event": "events", "transaction": "payments",
              "media": "videos watched", "song": "songs played"}
# For the year in numbers: the kinds counted from the year's records. The rest come from the page that shows them,
# counted the way it counts (each search once, every video service, songs past a skip), so the numbers agree.
YEAR_OWN = ("message", "photo", "video", "email", "call", "voice_memo", "event", "transaction")
BUSY_SKIP = ("visit", "media", "song", "event", "transaction", "activity")
NOT_YOURS = ("health_sample", "health_day", "sleep", "app_usage", "app_usage_day", "interaction", "contact", "record", "app",
             "profile", "inference", "follow", "invitation", "ad", "advertiser", "off_platform")  # the last: what They Know has


def middle_out(ids):
    """A list from its middle outwards: the photo nearest the middle of a day first."""
    mid = len(ids) // 2
    return [ids[i] for i in sorted(range(len(ids)), key=lambda i: abs(i - mid))]


def viewable(con, rowids):
    """The first of these records this Mac has a picture of, for a thumbnail; or None."""
    for rowid in rowids:
        r = con.execute("select source, id, meta from records where rowid = ?", (rowid,)).fetchone()
        if r and preview_file(r[0], r[1], meta_of(r[2]).get("files")):
            return rowid
    return None


def years_present(con):
    """Years with something of what you did in them (twenty records or more), newest first."""
    rows = con.execute(f"select substr(ts, 1, 4) y, count(*) from records where ts > '1990' and ts not like '2001-01-01T00:00:00%' "
                       f"and kind not in ({','.join(repr(k) for k in NOT_YOURS)}) group by y").fetchall()
    today = datetime.now(TZ).year
    return [y for y, n in sorted(rows, reverse=True) if n >= 20 and y.isdigit() and int(y) <= today]


def year(y):
    con = connect()
    steps = ["Your people", "Your places", "Your journeys", "Your rhythms", "Your firsts", "What you made",
             "Your listening, watching and searches", "The year, day by day"]
    with Progress(steps) as pg:
        pg.step(0)
        P = cached("people", people)
        pg.step(1)
        PL = cached("places", places)
        pg.step(2)
        J = cached("journeys", journeys)
        pg.step(3)
        R = cached("rhythms", rhythms)
        pg.step(4)
        F = cached("firsts", firsts)
        pg.step(5)
        M = cached("made", made)
        pg.step(6)
        media = {k: cached(k, fn) for k, fn in (("listening", listening), ("watching", watching), ("curiosity", curiosity))}
        pg.step(7)
        return _year(con, y, P, PL, J, R, F, M, media, pg)


def _year(con, y, P, PL, J, R, F, M, media, pg):
    today = datetime.now(TZ).date()
    lo = datetime(int(y), 1, 1, tzinfo=TZ).astimezone(timezone.utc) - timedelta(days=1)
    hi = datetime(int(y) + 1, 1, 1, tzinfo=TZ).astimezone(timezone.utc) + timedelta(days=1)
    rng = (lo.strftime("%Y-%m-%dT%H:%M:%S"), hi.strftime("%Y-%m-%dT%H:%M:%S"))
    pg.tick(0)
    counts, apps, day_counts, day_kinds = collections.Counter(), collections.Counter(), collections.Counter(), collections.defaultdict(collections.Counter)
    sent = received = 0
    photos_by_day = collections.defaultdict(list)
    for i, (rowid, source, kind, ts, is_me, meta) in enumerate(con.execute(
            f"select rowid, source, kind, ts, is_me, case when kind in ('photo', 'video') then meta end from records "
            f"where ts >= ? and ts < ? and kind not in ({','.join(repr(k) for k in NOT_YOURS)}) and source != 'shared_photos'", rng)):
        pg.tick(i)
        t = parse(ts, meta_of(meta).get("timezone") if meta else None)
        if not t or t.year != int(y):
            continue
        if kind == "media" and source in ("spotify", "app_usage"):
            kind = "song"  # a song played, not a video watched
        counts[kind] += 1
        mine = str(is_me) == "1"
        if kind == "message":
            apps[app_label(source, con)] += 1
            sent += mine
            received += not mine
        if (kind == "email" and not mine) or kind in BUSY_SKIP:
            continue  # mail that came to you, pages loading and calendar entries aren't things you did that day
        d = t.date().isoformat()
        day_counts[d] += 1
        day_kinds[d][kind] += 1
        if kind in ("photo", "video"):
            photos_by_day[d].append(rowid)
    # Twelve photos, one a month: from the month's most photographed day, the photo nearest the middle of it that
    # this Mac has a picture of (a video's, or one only in iCloud, may not have one).
    months = []
    for mo in range(1, 13):
        ds = sorted((d for d in photos_by_day if d[5:7] == f"{mo:02d}"), key=lambda x: -len(photos_by_day[x]))
        if ds:
            pick = viewable(con, [r for d in ds[:3] for r in middle_out(photos_by_day[d])][:10])
            if pick:
                months.append({"month": f"{y}-{mo:02d}", "rowid": pick, "count": sum(len(photos_by_day[x]) for x in ds)})
    busiest = max(day_counts.items(), key=lambda kv: kv[1]) if day_counts else None
    # People: your closest this year, how many you talked to, and who was new.
    in_year = [p for p in P["people"] if p["years"].get(y)]
    new = sorted((p for p in in_year if p.get("first") and p["first"]["ts"][:4] == y), key=lambda p: -p["years"][y])
    trips = [t for t in PL["trips"] if t["start"][:4] == y]
    jy = J["by_year"].get(y, {"km": 0, "flights": 0, "legs": 0, "countries": []})
    new_countries = [i for i in F["items"] if i["kind"] == "country" and i["ts"][:4] == y]
    firsts_y = [i for i in F["items"] if i["ts"][:4] == y]
    order = {"country": 0, "project": 1, "place": 2, "person": 3, "app": 4, "milestone": 5}
    highlights = sorted(firsts_y, key=lambda i: (order.get(i["kind"], 9), i["ts"]))[:8]
    made_days = sorted(d for d, c in M["days"].items() if d[:4] == y and any(n for k, n in c.items() if k != "photos"))
    best, run, prev = (0, None, None), 0, None
    for d in made_days:
        cur = date.fromisoformat(d)
        run = run + 1 if prev and (cur - prev).days == 1 else 1
        if run > best[0]:
            best = (run, (cur - timedelta(days=run - 1)).isoformat(), d)
        prev = cur
    msgs = R["kinds"].get("messages")
    hours = msgs["years"].get(y) if msgs else None
    steps = [(ts[:10], steps_of(m)) for ts, m in con.execute(
        "select ts, meta from records where kind = 'health_day' and ts like ?", (f"{y}-%",))]
    steps = [(d, s) for d, s in steps if s]
    best_steps = max(steps, key=lambda x: x[1]) if steps else None
    made_y = M["totals"].get(y, {})
    browsing = R["kinds"].get("browsing")
    numbers = collections.Counter({YEAR_KINDS[k]: n for k, n in counts.items() if k in YEAR_OWN})
    numbers.update({"searches": media["curiosity"]["years"].get(y, {}).get("count", 0),
                    "videos watched": media["watching"]["years"].get(y, {}).get("count", 0),
                    "songs played": media["listening"]["years"].get(y, {}).get("plays", 0),
                    "pages visited": sum(browsing["years"].get(y, [])) if browsing else 0,
                    "commits": made_y.get("code", 0), "notes and documents": made_y.get("writing", 0), "posts": made_y.get("posts", 0),
                    "AI conversations": made_y.get("ai", 0)})
    return {
        "year": y, "years": years_present(con), "so_far": int(y) == today.year, "through": today.isoformat() if int(y) == today.year else None,
        "counts": {k: n for k, n in numbers.most_common() if n},
        "messages": {"sent": sent, "received": received, "apps": [{"app": a, "messages": n} for a, n in apps.most_common(6)]},
        "people": {"count": len(in_year), "top": [{"key": p["key"], "name": p["name"], "messages": p["messages"]} for p in P["circle"].get(y, [])[:5]],
                   "new": len(new), "new_top": [{"key": p["key"], "name": p["name"], "messages": p["years"][y]} for p in new[:6]]},
        "trips": [{"id": t["id"], "start": t["start"], "end": t["end"], "days": t["days"], "places": t["places"][:2], "countries": t["countries"],
                   "sample": t["sample"][:1]} for t in sorted(trips, key=lambda t: -t["days"])[:6]],
        "trip_count": len(trips),
        "travel": {"km": jy["km"], "flights": jy["flights"], "countries": jy["countries"], "new_countries": [i["what"] for i in new_countries],
                   "legs": [leg for leg in J["legs"] if leg["arrived"][:4] == y][:80]},
        "photos": {"count": counts["photo"] + counts["video"], "months": months},
        "made": {"days": len(made_days), "totals": {k: n for k, n in M["totals"].get(y, {}).items() if k != "photos"},
                 "streak": {"days": best[0], "start": best[1], "end": best[2]}},
        "rhythm": {"peak_hour": max(range(24), key=lambda h: hours[h]) if hours and any(hours) else None,
                   "bedtime": msgs["bedtime"].get(y) if msgs else None},
        "steps": {"total": round(sum(s for _, s in steps)), "days": len(steps), "average": round(sum(s for _, s in steps) / len(steps)),
                  "best": {"date": best_steps[0], "steps": round(best_steps[1])}} if steps else None,
        "firsts": {"count": len(firsts_y), "highlights": highlights},
        "busiest": {"date": busiest[0], "count": busiest[1], "kinds": {YEAR_KINDS[k]: n for k, n in day_kinds[busiest[0]].most_common() if k in YEAR_KINDS},
                    "photo": viewable(con, middle_out(photos_by_day.get(busiest[0], []))[:10])} if busiest else None,
    }


# ---------------------------------------------------------------- a conversation

def thread(rowid, direction=None, edge=None, limit=60):
    """The conversation around a message, both sides, as a chat app shows it: every message and reaction in its
    thread that local day (or the 300 nearest, on a very long day), plus a dozen before and after so it doesn't
    start mid-sentence. With direction "before"/"after" and the edge message's time, the next `limit` that way."""
    con = connect()
    if not re.fullmatch(r"\d+", str(rowid)):
        return {"error": "not a message in a conversation"}
    r = con.execute("select rowid, source, kind, thread, thread_name, participants, ts, meta from records where rowid = ?",
                    (int(rowid),)).fetchone()
    if not r or r[2] not in ("message", "reaction") or not r[3]:
        return {"error": "not a message in a conversation"}
    _, source, _, th, thread_name, participants, ts, meta = r
    cols = "rowid, ts, is_me, author, kind, text, meta"
    base = f"select {cols} from records where source = ? and thread = ? and kind in ('message', 'reaction') and ts is not null"

    def take(where, args, order, n):
        rows = con.execute(f"{base} and {where} order by ts {order} limit {int(n)}", (source, th, *args)).fetchall()
        return rows if order == "asc" else rows[::-1]

    if direction in ("before", "after") and edge:
        rows = take("ts < ?", (edge,), "desc", limit) if direction == "before" else take("ts > ?", (edge,), "asc", limit)
    elif not parse(ts):
        # A message with no time that can be right: the ones kept either side of it, and it.
        rows = take("ts < ?", (ts,), "desc", 30) + take("ts >= ?", (ts,), "asc", 30) if ts else []
        if not any(x[0] == int(rowid) for x in rows):
            rows += con.execute(f"select {cols} from records where rowid = ?", (int(rowid),)).fetchall()
    else:
        t = parse(ts)
        lo = datetime(t.year, t.month, t.day, tzinfo=TZ).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        hi = (datetime(t.year, t.month, t.day, tzinfo=TZ) + timedelta(days=1)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        day = take("ts >= ? and ts < ?", (lo, hi), "asc", 301)
        if len(day) > 300:  # a very long day: the 300 around this message
            day = take("ts < ?", (ts,), "desc", 150) + take("ts >= ?", (ts,), "asc", 150)
            rows = day
        else:
            rows = take("ts < ?", (lo,), "desc", 12) + day + take("ts >= ?", (hi,), "asc", 12)
    out = _messages(rows)
    first, last = (rows[0][1], rows[-1][1]) if rows else (ts, ts)
    more = lambda op, t: con.execute(f"select 1 from records where source = ? and thread = ? and kind in ('message', 'reaction') "
                                     f"and ts {op} ? limit 1", (source, th, t)).fetchone() is not None
    return {"rowid": int(rowid), **_who(con, source, th, thread_name, participants, meta), "messages": out,
            "more_before": more("<", first), "more_after": more(">", last)}


def _messages(rows):
    """Rows of (rowid, ts, is_me, author, kind, text, meta) as a chat app shows them."""
    out = []
    for rid, ts_, is_me, author, kind, text, m in rows:
        files = [f for f in (meta_of(m).get("files") or []) if isinstance(f, str)]
        body = re.sub(r"\s*\[attachment: [^\]]*\]", "", text or "").strip()
        lt = parse(ts_)
        out.append({"rowid": rid, "ts": lt.isoformat() if lt else None, "at": ts_, "me": str(is_me) == "1", "author": author,
                    "kind": kind, "text": body, "files": len(files),
                    "image": any(Path(f).suffix.lower() in IMAGE_EXT for f in files)})
    return out


def _who(con, source, th, thread_name, participants, meta):
    """Which app a conversation is in, who it's with (no one name for a group), and whether only your side is kept."""
    m = meta_of(meta) if source == "imessage" else {}
    who = chat_partner(source, thread_name, participants, m, me_names())
    others = con.execute("select 1 from records where source = ? and thread = ? and kind = 'message' and is_me != '1' limit 1",
                         (source, th)).fetchone()
    return {"app": app_label(source, con), "name": who or thread_name or "A conversation", "group": who is None,
            "one_sided": source in ONE_SIDED or others is None}


SNIPPET = 16  # most messages one snippet shows


def embed(kind, spec):
    """What an Ask answer shows rather than cites. "chat" with "ROWID": that message with two before it and three
    after, in its conversation; with "FROM-TO": those two messages and every one between them (the first SNIPPET).
    "photos" with "ROWID,ROWID": each photo (or message with an image) and where and when it was taken, with its
    thumbnail. Read from corpus.db on this Mac; nothing here goes to the model."""
    con = connect()
    if kind == "chat":
        ids = [int(x) for x in re.findall(r"\d+", spec)][:2]
        if not ids:
            return {"error": "no message"}
        q = "select rowid, source, kind, thread, thread_name, participants, ts, meta from records where rowid = ?"
        ends = [con.execute(q, (i,)).fetchone() for i in ids]
        if any(not r or r[2] not in ("message", "reaction") or not r[3] or not r[6] for r in ends):
            return {"error": "not a message in a conversation"}
        if len(ends) == 2 and (ends[0][1], ends[0][3]) != (ends[1][1], ends[1][3]):
            return {"error": "those messages are in different conversations"}
        _, source, _, th, thread_name, participants, ts, meta = ends[0]
        base = ("select rowid, ts, is_me, author, kind, text, meta from records where source = ? and thread = ? "
                "and kind in ('message', 'reaction') and ts is not null")
        if len(ends) == 2:
            lo, hi = sorted([ends[0][6], ends[1][6]])
            rows = con.execute(f"{base} and ts >= ? and ts <= ? order by ts, rowid limit {SNIPPET}", (source, th, lo, hi)).fetchall()
            anchors = ids
        else:
            before = con.execute(f"{base} and (ts < ? or (ts = ? and rowid < ?)) order by ts desc, rowid desc limit 2",
                                 (source, th, ts, ts, ids[0])).fetchall()[::-1]
            after = con.execute(f"{base} and (ts > ? or (ts = ? and rowid >= ?)) order by ts, rowid limit 4",
                                (source, th, ts, ts, ids[0])).fetchall()
            rows, anchors = before + after, ids
        out = _messages(rows)
        pics = thumbs([m["rowid"] for m in out if m["image"]], 360)
        for m in out:
            if str(m["rowid"]) in pics:
                m["thumb"] = pics[str(m["rowid"])]
        return {"kind": "chat", "rowid": ids[0], **_who(con, source, th, thread_name, participants, meta), "messages": out, "anchors": anchors}
    if kind in ("photos", "photo"):
        ids = list(dict.fromkeys(int(x) for x in re.findall(r"\d+", spec)))[:6]
        pics = thumbs(ids, 480)
        out = []
        for rowid in ids:
            r = con.execute("select ts, text, meta from records where rowid = ?", (rowid,)).fetchone()
            if not r or str(rowid) not in pics:
                continue
            mt = meta_of(r[2])
            t = parse(r[0], mt.get("timezone") or mt.get("tz"))
            place = next((ln.split(":", 1)[1].strip() for ln in (r[1] or "").splitlines() if ln.startswith("Place:")), None)
            out.append({"rowid": rowid, "ts": t.isoformat(timespec="seconds") if t else None, "place": place, "thumb": pics[str(rowid)]})
        return {"kind": "photos", "photos": out} if out else {"error": "no photos to show"}
    return {"error": f"can't show {kind}"}


# ---------------------------------------------------------------- summary and thumbnails

# ---------------------------------------------------------------- the stream

def _stream():
    sys.path.insert(0, str(REPO / "connectors"))
    import stream
    return stream


def stream_month(m=None):
    """A month's events (the same ones corpus/stream/ keeps), with each record's rowid so the page can open it."""
    st = _stream()
    con = connect()
    have = st.months(con)
    if not m or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", m) or not FIRST_YEAR <= int(m[:4]) <= LATEST.year:
        m = have[0]["month"] if have else datetime.now(TZ).strftime("%Y-%m")
    with Progress(["Reading the month", "Putting it in order"]) as pg:
        pg.step(0)
        r = st.month(m, con, progress=lambda done, total: (pg.step(0, total) if done == 0 else pg.tick(done)))
        pg.step(1)
    y, mm = map(int, m.split("-"))
    f = st.OUT / f"{m}.jsonl"
    return {"month": m, "label": datetime(y, mm, 1).strftime("%B %Y"), "months": have, "records": r["records"],
            "left_out": r["left_out"], "file": str(f) if f.exists() else None,
            "events": [{k: v for k, v in e.items() if k != "refs"} for e in r["events"]]}


def records_brief(rowids):
    """Each record in a line or two, in order: when, which app, who, what."""
    st = _stream()
    con = connect()
    marks = ",".join("?" * len(rowids))
    out = []
    for rowid, source, kind, ts, author, is_me, thread_name, title, text, url, meta in con.execute(
            f"select rowid, source, kind, ts, author, is_me, thread_name, title, text, url, meta from records where rowid in ({marks})", rowids):
        mt = meta_of(meta)
        t = parse(ts, mt.get("timezone") or mt.get("tz"))
        out.append({"rowid": rowid, "ts": t.isoformat(timespec="seconds") if t else None, "app": st.app_name(source), "kind": kind,
                    "who": "You" if str(is_me) == "1" or author == "me" else (author or thread_name), "title": st.clip(title, 120) or None,
                    "text": st.clip(text, 280) or None, "url": url, "message": kind == "message"})
    return sorted(out, key=lambda x: x["ts"] or "")


def summary():
    """A line or two per artifact, for the cards: cheap queries only (the full artifacts load when opened)."""
    con = connect()
    have = sources_present(con)
    otd = on_this_day()
    p = cached("people", people)
    pl = cached("places", places)
    r = cached("rhythms", rhythms)
    f = cached("firsts", firsts)
    m = cached("made", made)
    msgs = r["kinds"].get("messages")
    return {
        "on_this_day": {"label": otd["label"], "years": len(otd["years"]),
                        "photos": sum(y["photos"]["count"] for y in otd["years"]),
                        "cover": next((y["photos"]["sample"][0] for y in otd["years"] if y["photos"]["sample"]), None)},
        "people": {"count": len(p["people"]), "messages": p["total_messages"], "top": [x["name"] for x in p["people"][:3]]},
        "places": {"trips": len(pl["trips"]), "countries": len(pl["countries"]), "places": pl["places"], "photos": pl["photos_with_place"]},
        "rhythms": {"peak_hour": msgs["peak_hour"] if msgs else None, "kinds": len(r["kinds"])},
        "firsts": {"count": len(f["items"]), "first": f["items"][0] if f["items"] else None},
        "made": {"streak": m["streak"], "days": sum(1 for c in m["days"].values() if any(n for k, n in c.items() if k != "photos"))},
        "sources": sorted(have & set(APP_NAMES)),
    }


IMAGE_EXT = (".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff", ".webp")


def preview_file(source, rid, files):
    """The picture to make a thumbnail from: a file the record points to, else Photos' own preview of it. Photos keeps
    small previews on this Mac (resources/derivatives/<first letter>/<id>_*.jpeg) even when the original, or a
    video, is only in iCloud; a photo record's id is its Photos id."""
    files = [x for x in (files or []) if isinstance(x, str)]
    path = next((Path(x) for x in files if Path(x).suffix.lower() in IMAGE_EXT and Path(x).exists()), None)
    if path or source != "photos":
        return path
    lib = next((Path(x.split(".photoslibrary")[0] + ".photoslibrary") for x in files if ".photoslibrary" in x),
               Path.home() / "Pictures/Photos Library.photoslibrary")
    u = str(rid or "")
    if not re.fullmatch(r"[0-9A-F-]{36}", u):
        u = next((Path(x).name.split("_")[0] for x in files if re.match(r"[0-9A-F-]{36}_", Path(x).name)), "")
    if not u:
        return None
    for p in (lib / "resources/derivatives" / u[0] / f"{u}_1_105_c.jpeg", lib / "resources/derivatives/masters" / u[0] / f"{u}_4_5005_c.jpeg"):
        if p.exists():
            return p
    return next((p for p in sorted((lib / "resources/derivatives" / u[0]).glob(f"{u}_*.jpeg"))), None)


def thumbs(rowids, size=360):
    """{rowid: data URL} for photos (and image attachments), made with sips from the record's file or Photos' own
    preview; cached by rowid and size."""
    con = connect()
    out = {}
    tdir = CACHE / "thumbs"
    tdir.mkdir(parents=True, exist_ok=True)
    for rowid in rowids:
        f = tdir / f"{int(rowid)}-{size}.jpg"
        if not f.exists():
            r = con.execute("select source, id, meta from records where rowid = ?", (int(rowid),)).fetchone()
            path = preview_file(r[0], r[1], meta_of(r[2]).get("files")) if r else None
            if not path:
                continue
            p = subprocess.run(["/usr/bin/sips", "-s", "format", "jpeg", "-s", "formatOptions", "70", "-Z", str(size), str(path), "--out", str(f)],
                               capture_output=True, timeout=60)
            if p.returncode or not f.exists():
                continue
        out[str(rowid)] = "data:image/jpeg;base64," + base64.b64encode(f.read_bytes()).decode()
    return out


def main(argv):
    cmd, rest = (argv[0], argv[1:]) if argv else ("summary", [])
    if cmd == "summary":
        out = summary()
    elif cmd == "on-this-day":
        out = on_this_day(rest[0] if rest else None)
    elif cmd == "people":
        out = cached("people", people)
    elif cmd == "person":
        k = key(rest[0] if rest else "")
        out = cached(f"person-{k}", person, k) if k else {"error": "Which person?"}
    elif cmd == "places":
        out = cached("places", places)
    elif cmd == "rhythms":
        out = cached("rhythms", rhythms)
    elif cmd == "firsts":
        out = cached("firsts", firsts)
    elif cmd == "made":
        out = cached("made", made)
    elif cmd == "groups":
        out = cached("groups", groups)
    elif cmd == "they-know":
        out = cached("they-know-v2", they_know)  # v2: who told on you has each time it told
    elif cmd in ("listening", "movement", "curiosity", "watching"):
        out = cached(cmd, {"listening": listening, "movement": movement, "curiosity": curiosity, "watching": watching}[cmd])
    elif cmd == "journeys":
        out = cached("journeys", journeys)
    elif cmd == "year":
        y = rest[0] if rest and rest[0].isdigit() else None
        if not y:
            ys = years_present(connect())
            y = ys[0] if ys else str(datetime.now(TZ).year)
        out = cached(f"year-{int(y)}", year, str(int(y))) if FIRST_YEAR <= int(y) <= LATEST.year else {"error": f"Nothing could be from {y}."}
    elif cmd == "stream":
        m = rest[0] if rest else None
        out = cached(f"stream-{m or 'latest'}-v{_stream().VERSION}", stream_month, m)  # new rules, new events
        f = _stream().OUT / f"{out['month']}.jsonl"
        out["file"] = str(f) if f.exists() else None  # written since it was cached, perhaps
    elif cmd == "stream-build":
        index = _stream().build(log=lambda line: None)
        out = {"months": len(index), "events": sum(v["events"] for v in index.values())}
    elif cmd == "records":
        out = records_brief([int(x) for x in (rest[0] if rest else "").split(",") if x.strip().isdigit()][:2000])
    elif cmd == "thread":
        out = thread(rest[0] if rest else "", *(rest[1:3] if len(rest) >= 3 else ()))
    elif cmd == "embed":
        out = embed(rest[0] if rest else "", rest[1] if len(rest) > 1 else "")
    elif cmd == "thumbs":
        size = int(rest[1]) if len(rest) > 1 and rest[1].isdigit() else 360
        out = thumbs([int(x) for x in (rest[0] if rest else "").split(",") if x.strip().isdigit()][:60], max(32, min(size, 2048)))
    else:
        sys.exit(f"unknown command {cmd}")
    sys.stdout.write(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except FileNotFoundError as e:
        sys.stdout.write(json.dumps({"error": str(e)}))
