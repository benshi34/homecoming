"""The event stream: what happened, in order, one month at a time.

Every timestamped record in corpus.db becomes part of an event, except what isn't something you did or that happened
to you: device bookkeeping (an iPhone's file index, Wi-Fi joins, app state), raw Health samples, spam and deleted
mail. The same thing seen by several sources (a Chrome visit in Chrome, Chrome Sync and Google's My Activity; an
event in three calendars) becomes one, and a run of the same thing (texts with one person, a stretch of browsing, a
batch of photos, a coding session) becomes one event that lists every record in it.

    python3 stream.py month YYYY-MM      the month's events, one JSON object per line
    python3 stream.py build [--all]      corpus/stream/YYYY-MM.jsonl for each month whose records changed (every
                                         month with --all), and corpus/stream/months.json
    python3 stream.py months             the months with records, and how many each has

An event: start and end (local time, ISO with offset; end only when it lasted), kind, app, device, title (one line,
plain words), lines (a preview: the first messages, the sites, the queries), people, count (records in it, after
duplicates are merged), mine (how many of them were yours), and refs ("source:id" of every record in it, duplicates
included, so nothing is lost). Records are referred to by source and id, which survive the database being rebuilt;
rowids don't.

Times are this Mac's time zone (UMP_TZ to change it), or a record's own where it keeps one (photos, Health). Months
are local months. Read-only on corpus.db; build writes only corpus/stream/.
"""

import hashlib
import json
import os
import re
import sqlite3
import sys
import zlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

CORPUS = Path(os.environ.get("CORPUS_DIR") or Path(__file__).resolve().parent.parent / "corpus")
DB = CORPUS / "corpus.db"
OUT = CORPUS / "stream"
VERSION = 5  # bump when events change shape or rules change, so every month is rebuilt (2: whole days on their own date;
# 3: what services showed or decided about you left out everywhere, YouTube's comments and playlists, bookmarks;
# 4: date-only calendar events and Discord DM fallback names; 5: records from 1900 on, a clock's first second left out)

# ---------------------------------------------------------------- time


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


def parse(ts, tz=None):
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(zone_of(tz) or TZ)


def whole_day(ts, tz=None):
    """A record of a whole day (a day's Health totals, an all-day event) as midnight of its own date, here: a date
    written without a zone ("2026-09-10T00:00:00", Health's) or a floating all-day one at UTC midnight is that date;
    an instant with the record's own zone is the date it was there. Or None."""
    if not ts:
        return None
    s = str(ts)
    t = parse(s, tz)
    if not t:
        return None
    zoned = s.endswith("Z") or re.search(r"[+-]\d\d:?\d\d$", s)
    try:
        d = t.date() if zoned and tz else date.fromisoformat(s[:10])
    except ValueError:
        d = t.date()
    return datetime(d.year, d.month, d.day, tzinfo=TZ)


def month_range(month):
    """'2026-09' -> the local month's first instant and the next month's, in UTC (for the ts index)."""
    y, m = map(int, month.split("-"))
    lo = datetime(y, m, 1, tzinfo=TZ)
    hi = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=TZ)
    return lo, hi


def iso(t):
    return t.isoformat(timespec="seconds") if t else None


def num(v):
    """A number from whatever a record holds: 12, "12.5", "1,234", "90 s"; 0 when there's none to read."""
    if isinstance(v, bool):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v) if v == v and abs(v) != float("inf") else 0.0
    m = re.search(r"-?\d+(?:\.\d+)?", str(v or "").replace(",", ""))
    return float(m.group(0)) if m else 0.0


def duration(seconds):
    s = int(round(seconds or 0))
    if s < 60:
        return f"{s} s"
    h, m = divmod(round(s / 60), 60)
    return f"{h} h {m} min" if h and m else f"{h} h" if h else f"{m} min"


# ---------------------------------------------------------------- names

APPS = {"imessage": "Messages", "instagram": "Instagram", "messenger": "Messenger", "discord": "Discord",
        "phone_whatsapp": "WhatsApp", "whatsapp_export": "WhatsApp", "phone_wechat": "WeChat", "google_chat": "Google Chat",
        "calls": "Phone", "gmail": "Gmail", "hotmail": "Outlook", "mail": "Mail", "x": "X", "reddit": "Reddit", "linkedin": "LinkedIn",
        "tiktok": "TikTok", "spotify": "Spotify", "chatgpt": "ChatGPT", "claude_ai": "Claude", "notion": "Notion",
        "notion_export": "Notion", "phone_notion": "Notion", "photos": "Photos", "shared_photos": "Shared Albums", "git_commits": "Git",
        "phone_venmo": "Venmo", "phone_splitwise": "Splitwise", "phone_uberclient": "Uber", "phone_uberplaces": "Uber",
        "phone_airbnb": "Airbnb", "phone_united_airlines": "United", "apple_notes": "Notes", "phone_notes": "Notes",
        "calendar": "Calendar", "google_calendar": "Google Calendar", "phone_calendarall": "Calendar",
        "facebook_activity": "Facebook", "instagram_activity": "Instagram", "reminders": "Reminders",
        "phone_reminders": "Reminders", "documents": "Files", "imported_documents": "Files", "editor_history": "Code editor",
        "voice_memos": "Voice Memos", "phone_voicerecordings": "Voice Memos", "health": "Health", "phone_health": "Health",
        "google_keep": "Keep", "google_maps_places": "Google Maps", "phone_netflix": "Netflix", "podcasts": "Podcasts",
        "whatsapp": "WhatsApp", "books": "Books", "apple_maps": "Maps",
        "shell_history": "Terminal", "browser_history": "Browser", "chrome_synced": "Chrome", "phone_safarihistory": "Safari",
        "youtube": "YouTube", "google_tasks": "Google Tasks", "google_saved": "Google Saved",
        "phone_safariwebsearch": "Safari", "phone_corpusxdirectmessages": "X", "contacts": "Contacts",
        "iphone_contacts": "Contacts", "google_contacts": "Google Contacts", "vcard_contacts": "Contacts"}


def app_name(source):
    if source in APPS:
        return APPS[source]
    base = re.sub(r"_(other|files)$", "", source or "")
    if base != source:
        return app_name(base)
    if source == "phone_whatsappextended":
        return "WhatsApp"
    s = re.sub(r"^(phone|takeout)_", "", source or "").replace("_", " ").strip()
    return s[:1].upper() + s[1:] if s else "An app"


def norm(s):
    return re.sub(r"[\W_]+", " ", str(s or "").casefold()).strip()


def clip(s, n=140):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def first_name(name):
    return (str(name or "").split() or ["?"])[0]


def me_names():
    try:
        d = json.loads((CORPUS / "identity.json").read_text())
    except (OSError, ValueError):
        return set()
    d = d if isinstance(d, dict) else {}  # who you are, cut off or written oddly: nobody, rather than no stream
    return {norm(n).replace(" ", "") for n in (d.get("names") or []) + (d.get("usernames") or []) if n}


def norm_url(u):
    """One page however it was written down: no fragment, no tracking parameters, no trailing slash, any case of host."""
    try:
        p = urlsplit(str(u or "").strip())
    except ValueError:
        return str(u or "")
    q = urlencode([(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith(("utm_", "fbclid", "gclid", "ref"))])
    host = p.netloc.lower().removeprefix("www.")
    return urlunsplit(("", host, p.path.rstrip("/"), q, ""))


def host_of(u):
    try:
        return urlsplit(str(u or "")).netloc.lower().removeprefix("www.") or None
    except ValueError:
        return None


# ---------------------------------------------------------------- what to leave out

DROP_SOURCES = {
    "health_samples",              # every Health sample; the day totals and nights of sleep are kept
    "phone_interactionccontacts",  # iOS's index of whom you messaged and called: the messages and calls themselves are kept
    "phone_recents", "phone_keyboardinputcontexts", "phone_parsecdcache", "phone_safaritabs", "phone_mmkvcarved",
    "phone_walstrings", "phone_tcc", "phone_applewifiplist", "phone_applicationstatedb",
}
DROP = {("app_usage", "app_usage_day"),  # day totals of the app sessions that are kept
        ("photos_memories", "memory"), ("photos_memories", "highlight"),  # Photos' summaries of your photos, not events
        ("browser_saved", "open_tab"),  # tabs open on your other devices now: a state, not something that happened
        ("phone_safarihistory", "record")}  # Safari's tags on visits that are kept
# What a service showed you or decided about you, from any export: ads (YouTube's, sponsored results, X's), its guesses,
# the advertisers that have you, what other companies told it. Not something you did (Explore's What They Know has them).
DROP_KINDS = {"ad", "advertiser", "inference", "off_platform"}
DROP_TIERS = {"device", "spam", "deleted", "superseded"}  # superseded: an earlier version (an edited post, a regenerated answer)
# Export files that hold no event of yours: ads you were shown, and X's bookkeeping for direct messages (the messages
# themselves are kept).
DROP_FILES = re.compile(r"^(ads_viewed|data/(message-event|direct-message-headers|direct-message-group-headers|ad-[\w-]+)\.js)$")
AUTOMATED_LABELS = {"Category Promotions", "Category Updates", "Category Social", "Category Forums"}
AUTOMATED_SENDER = re.compile(r"(no-?reply|do-?not-?reply|notifications?|newsletter|news|updates?|alerts?|info|hello|"
                              r"marketing|support|team|mailer|digest)@", re.I)

# ---------------------------------------------------------------- records


class Rec:
    __slots__ = ("rowid", "source", "id", "kind", "t", "end", "author", "me", "thread", "thread_name", "participants",
                 "title", "text", "url", "meta", "fields")

    def __init__(self, row):
        (self.rowid, self.source, self.id, self.kind, ts, ts_end, self.author, is_me, self.thread, self.thread_name,
         self.participants, self.title, self.text, self.url, meta) = row
        try:
            self.meta = json.loads(meta) if meta else {}
        except ValueError:
            self.meta = {}
        if not isinstance(self.meta, dict):
            self.meta = {}
        self.fields = self.meta.get("fields") if isinstance(self.meta.get("fields"), dict) else {}
        tz = self.meta.get("timezone") or self.meta.get("tz")
        if self.kind == "event" and isinstance(ts, str) and len(ts) == 10:
            self.meta["all_day"] = True
        if self.kind == "health_day" or self.meta.get("all_day") is True:
            # A whole day is a date, not an instant: on its own day (and in its own month), wherever this Mac is.
            self.t, self.end = whole_day(ts, tz), whole_day(ts_end, tz)
        else:
            self.t = parse(ts, tz)
            self.end = parse(ts_end, tz)
        self.me = str(is_me) == "1" or self.author == "me"

    @property
    def ref(self):
        return f"{self.source}:{self.id}"


class Item:
    """A record as one part of an event: what kind of event it belongs to, which run (key), how long a pause ends
    the run (gap, seconds), and, for things several sources record, what makes two of them the same (same, within
    window seconds)."""
    __slots__ = ("r", "kind", "app", "device", "key", "gap", "same", "window", "rank", "dupes")

    def __init__(self, r, kind, app, key, gap, device=None, same=None, window=0, rank=0):
        self.r, self.kind, self.app, self.key, self.gap, self.device = r, kind, app, key, gap, device
        self.same, self.window, self.rank, self.dupes = same, window, rank, []


def chat_partner(r, mine):
    """The one other person in a one-on-one chat, or None for a group."""
    if r.source == "imessage":
        return None if r.meta.get("group") else r.thread_name
    if r.source == "discord":
        name = r.thread_name or ""
        channel_type = r.meta.get("channel_type")
        if channel_type in ("GROUP_DM", 3, "3"):
            return None
        if channel_type not in ("DM", 1, "1") and not name.startswith(("Direct Message with", "DM with ")):
            return None
        return r.participants or name.removeprefix("Direct Message with").removeprefix("DM with ").strip(" .")
    if r.source == "phone_wechat":
        return r.fields.get("Chat Partner Name") or r.fields.get("Chat Partner") or r.thread_name
    others = [p.strip() for p in (r.participants or "").split(",") if p.strip() and norm(p).replace(" ", "") not in mine]
    if r.participants:
        return others[0] if len(others) == 1 else None
    return r.thread_name


def classify(r, mine, ctx):
    """The Item a record becomes, or None to leave it out."""
    s, k, m, f = r.source, r.kind, r.meta, r.fields
    if s in DROP_SOURCES or (s, k) in DROP or k in DROP_KINDS or m.get("tier") in DROP_TIERS or DROP_FILES.match(str(m.get("file") or "")):
        return None
    if s == "phone_amdsqlitedb" and ctx.get("screen_time_iphone"):
        return None  # the iPhone's app log; Screen Time has the same sessions
    app = app_name(s)

    # Conversations: a run of messages in one chat, until a pause of 45 minutes.
    if k in ("message", "reaction") or (s == "imessage" and k == "event"):
        who = chat_partner(r, mine)
        others = [p.strip() for p in (r.participants or "").split(",") if p.strip() and norm(p).replace(" ", "") not in mine]
        group = None if who else (f"“{r.thread_name}”" if r.thread_name and r.thread_name != r.participants
                                  else f"a group with {', '.join(others[:-1]) + ' and ' + others[-1] if len(others) > 1 else (others or ['others'])[0]}")
        r.meta["_who"], r.meta["_group"] = who, group
        return Item(r, "conversation", app, ("chat", s, r.thread or r.thread_name or who), 45 * 60,
                    same=(norm(r.text)[:80], norm(who or group)) if k == "message" and r.text else None, window=120)
    if k == "call" or s == "calls":
        return Item(r, "call", "FaceTime" if "facetime" in str(m.get("type", "")).lower() else "Phone", ("call", r.rowid), 0)
    if k == "email":
        labels = {x.strip() for x in str(m.get("labels") or "").split(",")}
        if r.me or "Sent" in labels:
            return Item(r, "email", app, ("email", r.rowid), 0)
        sender = str(m.get("from") or r.author or "")
        automatic = m.get("category") in ("transactions", "updates", "promotions")  # Mail's own sorting (mail_app.py)
        if automatic or labels & AUTOMATED_LABELS or AUTOMATED_SENDER.search(sender) or "unsubscribe" in (r.text or "").lower():
            return Item(r, "mail", app, ("mail", s, r.t.date()), 10 ** 9)  # newsletters and notifications, a day at a time
        return Item(r, "email", app, ("email", r.rowid), 0)

    # The web: pages and searches, a session at a time on each device, until a pause of 10 minutes.
    url = r.url or f.get("URL")
    if k == "visit" and s in ("browser_history", "chrome_synced", "google_activity", "phone_safarihistory"):
        product = m.get("product")
        if s == "google_activity" and product in ("YouTube",) or m.get("tag") == "youtube_watch" or re.search(r"youtube\.com/watch|youtu\.be/", url or ""):
            return Item(r, "watch", "YouTube", ("watch", "YouTube"), 30 * 60, same=("yt", norm_url(url) or norm(r.title)), window=600,
                        rank=_rank(s))
        if m.get("tag") == "maps" or product == "Maps":
            return Item(r, "maps", "Maps", ("maps",), 15 * 60, same=("map", norm_url(url)), window=300, rank=_rank(s))
        device = "iPhone" if s == "phone_safarihistory" or m.get("other_device") else "Mac"
        return Item(r, "browsing", "Safari" if s == "phone_safarihistory" else "Browser", ("web", device), 10 * 60,
                    device=device, same=("url", norm_url(url)), window=120, rank=_rank(s))
    if s == "apple_maps" and k in ("search", "directions", "place_lookup"):  # Apple Maps: what you looked up
        r.meta["_q"] = r.title
        return Item(r, "maps", "Maps", ("maps",), 15 * 60, same=("mapq", norm(r.title)), window=300)
    if k == "search":
        q = r.title if s != "phone_safariwebsearch" else (f.get("Search Term") or r.title)
        q = re.sub(r"^Searched for\s+", "", str(q or r.text or ""))
        r.meta["_q"] = q
        product = m.get("product")
        if s in ("browser_history", "chrome_synced", "phone_safariwebsearch") or (s == "google_activity" and product in ("Search", None)):
            device = "iPhone" if s == "phone_safariwebsearch" or m.get("other_device") else "Mac"
            return Item(r, "browsing", "Safari" if s == "phone_safariwebsearch" else "Browser", ("web", device), 10 * 60,
                        device=device, same=("q", norm(q)), window=180, rank=_rank(s))
        if product == "Maps":
            return Item(r, "maps", "Maps", ("maps",), 15 * 60, same=("mapq", norm(q)), window=300)
        name = product or app
        return Item(r, "search", name, ("search", name), 10 * 60, same=("q", name, norm(q)), window=180)
    if k == "media":
        player = m.get("app") or (app if s != "app_usage" else "Music")
        video = s == "phone_netflix" or player in ("Netflix", "YouTube", "TV", "Prime Video", "Disney+", "X") or (s == "google_activity" and m.get("product") == "YouTube")
        name = "YouTube" if s == "google_activity" else player
        kind = "watch" if video else "listen"
        return Item(r, kind, name, (kind, name), 30 * 60, same=(kind, norm(r.title), norm(m.get("artist"))), window=90)
    if s == "google_activity" and k == "activity":
        product = m.get("product") or "Google"
        if product == "Ads":
            return None  # ads Google showed you
        if product == "Maps":
            return Item(r, "maps", "Maps", ("maps",), 15 * 60)
        return Item(r, "other", product, ("other", s, product), 30 * 60)
    if s == "google_activity" and k == "app_usage":
        name = m.get("product") or "an app"
        return Item(r, "app", name, ("gapp", name), 10 * 60, device="Phone")

    # Things you made, kept or looked at.
    if s in ("photos", "shared_photos"):
        place = re.search(r"^Place: ([^,\n]+)", r.text or "", re.M)
        r.meta["_place"] = place.group(1).strip() if place else None
        if s == "shared_photos":  # someone else's (or a copy you posted to a shared album): a run of its own
            how = m.get("shared") or "shared"
            return Item(r, "photos", SHARED_APPS.get(how, "Photos"), ("shared_photos", how, bool(m.get("copy"))), 45 * 60)
        return Item(r, "photos", "Photos", ("photos",), 45 * 60)
    if k == "event" and s in ("calendar", "google_calendar", "phone_calendarall") or s.endswith("calendar") and k == "event":
        return Item(r, "calendar", app, ("cal", r.rowid), 0, same=("cal", norm(r.title)), window=600, rank=_rank(s))
    if k == "note" or s in ("apple_notes", "phone_notes", "google_keep"):
        return Item(r, "note", app, ("note", s, norm(r.title)), 30 * 60, same=("note", norm(r.title)), window=900, rank=_rank(s))
    if k == "reminder" or s in ("reminders", "phone_reminders"):
        return Item(r, "reminder", "Reminders", ("rem", r.rowid), 0, same=("rem", norm(r.title)), window=3600, rank=_rank(s))
    if k == "voice_memo" or s in ("voice_memos", "phone_voicerecordings"):
        return Item(r, "voice", "Voice Memos", ("voice", r.rowid), 0, same=("voice", norm(r.title)), window=600, rank=_rank(s))
    if k in ("document", "file_edit") or s in ("documents", "imported_documents", "editor_history"):
        return Item(r, "document", app, ("doc", s), 30 * 60)
    if s == "git_commits" or k == "commit":
        return Item(r, "code", "Git", ("git", m.get("repo") or r.thread_name or r.thread), 2 * 3600)
    if k == "ai_turn":
        tool = {"claude-code": "Claude Code", "codex": "Codex"}.get(m.get("tool"), m.get("product") or app)
        return Item(r, "ai", tool, ("ai", tool, r.thread or m.get("cwd")), 45 * 60)

    # Screen Time: the same app on one device, until it's left alone for 10 minutes. Under 2 minutes in all is a glance,
    # and left out (see month()).
    if s == "app_usage" and k == "app_usage":
        device = "iPhone" if "iphone" in str(m.get("device") or "").lower() else "Mac"
        return Item(r, "app", r.title or app, ("app", device, r.title), 10 * 60, device=device)
    if s == "phone_amdsqlitedb":
        name = f.get("App Name") or "an app"
        return Item(r, "app", name, ("app", "iPhone", name), 10 * 60, device="iPhone")

    if s == "phone_health" and f.get("Achievement"):
        return Item(r, "health", "Health", ("award", r.rowid), 0)
    if s == "facebook_activity" and m.get("file") in ("emails_we_sent_you", "notifications"):
        return Item(r, "mail", "Facebook", ("mail", s, m.get("file"), r.t.date()), 10 ** 9)
    if s == "health" and k == "health_day":
        return Item(r, "health", "Health", ("health", r.rowid), 0)
    if s == "health" and k == "sleep":
        return Item(r, "sleep", "Health", ("sleep", r.rowid), 0)
    if s == "instagram_activity" and m.get("file") == "ai_conversations":
        return Item(r, "ai", "Meta AI", ("ai", "Meta AI"), 45 * 60)
    if s in ("instagram_activity", "facebook_activity", "linkedin", "x", "x_other", "reddit", "tiktok", "threads", "bluesky", "youtube"):
        return Item(r, "social", app, ("social", s, k, m.get("file")), 30 * 60)
    if s in ("phone_venmo", "phone_splitwise") or k in ("payment", "transaction"):
        return Item(r, "money", app, ("money", s), 30 * 60)
    if k in ("trip", "flight") or s in ("phone_united_airlines", "phone_uberclient", "phone_uberplaces", "phone_airbnb"):
        return Item(r, "travel", app, ("travel", s, k), 30 * 60)
    # Bookmarks, songs added to a playlist and the like: a run in each list (a bookmarks folder, a playlist). A bookmark
    # Chrome has on this Mac and in Google Takeout is one, shown from the Mac's copy.
    same = ("bookmark", norm_url(r.url)) if k == "bookmark" and r.url else None
    return Item(r, "other", app, ("other", s, k, m.get("list")), 30 * 60, same=same, window=120 if same else 0, rank=_rank(s) if same else 0)


# Which of several sources' copies of one thing to show: the one closest to where it happened.
RANK = ["browser_history", "browser_saved", "phone_safarihistory", "phone_safariwebsearch", "chrome_synced", "google_activity",
        "calendar", "phone_calendarall", "google_calendar", "apple_notes", "phone_notes", "reminders", "phone_reminders",
        "voice_memos", "phone_voicerecordings"]


def _rank(source):
    return RANK.index(source) if source in RANK else len(RANK)


# ---------------------------------------------------------------- merging


def merge_duplicates(items):
    """Items that are the same thing (same `same`, within `window` seconds of each other) become one: the best
    ranked copy, carrying the others as dupes."""
    out, buckets = [], {}
    for it in items:
        if it.same is None:
            out.append(it)
        else:
            buckets.setdefault((it.kind, it.same), []).append(it)
    for group in buckets.values():
        group.sort(key=lambda i: i.r.t)
        cluster = [group[0]]
        for it in group[1:]:
            if (it.r.t - cluster[-1].r.t).total_seconds() <= it.window:
                cluster.append(it)
            else:
                out.append(_keep(cluster))
                cluster = [it]
        out.append(_keep(cluster))
    return out


def _keep(cluster):
    best = min(cluster, key=lambda i: (i.rank, i.r.t))
    best.dupes = [i for i in cluster if i is not best]
    return best


def runs(items):
    """Items in runs: the same key, each within its gap of the one before."""
    by_key = {}
    for it in items:
        by_key.setdefault(it.key, []).append(it)
    for group in by_key.values():
        group.sort(key=lambda i: i.r.t)
        run = [group[0]]
        last = group[0].r.end or group[0].r.t
        for it in group[1:]:
            if (it.r.t - last).total_seconds() <= it.gap:
                run.append(it)
            else:
                yield run
                run = [it]
            last = max(last, it.r.end or it.r.t)
        yield run


# ---------------------------------------------------------------- events


def event(run):
    """One event from a run of items: its time, its title in plain words, a preview, everyone in it."""
    head = run[0]
    kind, app = head.kind, head.app
    recs = [i.r for i in run]
    start = recs[0].t
    end = max((r.end or r.t) for r in recs)
    e = {"start": iso(start), "end": iso(end) if end > start else None, "kind": kind, "app": app, "device": head.device,
         "title": "", "lines": [], "people": [], "count": len(recs), "mine": sum(r.me for r in recs),
         "refs": [x.r.ref for i in run for x in [i, *i.dupes]], "rowids": [r.rowid for r in recs]}
    try:
        SUMMARIES.get(kind, sum_other)(e, recs, run)
    except Exception:  # noqa: BLE001 - a record shaped in a way no rule expects is still an event
        e.update(title="", lines=[], people=[])
        sum_other(e, recs, run)
    e["people"] = [str(p) for p in e["people"] if p]
    e["lines"] = [str(x) for x in e["lines"] if x]
    e["_at"] = datetime.fromisoformat(e["start"])  # where it sorts: its start as shown (a day's totals move to midnight)
    return e


def day_long(e, t):
    """An event about the whole day (a day's totals, a day's newsletters): shown at its start, with no end."""
    e["start"], e["end"], e["all_day"] = iso(t.replace(hour=0, minute=0, second=0, microsecond=0)), None, True


def plural(n, one, many=None):
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


def sum_conversation(e, recs, run):
    msgs = [r for r in recs if r.kind == "message"]
    who, group = recs[0].meta.get("_who"), recs[0].meta.get("_group")
    verb, past = ("Texted", "texted") if recs[0].source == "imessage" else ("Messaged", "messaged")
    mine = sum(r.me for r in msgs)
    n = plural(len(msgs), "message")
    if group:
        authors = sorted({r.author for r in msgs if r.author and not r.me})
        e["title"] = (f"Chatted in {group}" if mine else f"{authors[0]} wrote in {group}" if len(authors) == 1
                      else f"Messages in {group}")
        e["people"] = authors
    elif not msgs:
        e["title"] = f"Reacted in your chat with {who}"
        e["people"] = [who]
    else:
        e["title"] = f"{verb} with {who}" if 0 < mine < len(msgs) else f"{verb} {who}" if mine else f"{who} {past} you"
        e["people"] = [who]
    e["title"] += f" ({n})" if len(msgs) > 1 else ""
    for r in msgs[:5]:
        e["lines"].append(f"{'You' if r.me else first_name(r.author or who)}: {clip(r.text, 120)}")


def sum_call(e, recs, run):
    r = recs[0]
    m = r.meta
    who = r.thread_name or r.author or "someone"
    secs = num(m.get("seconds"))
    out = str(m.get("direction", "")).lower().startswith("out") or r.me
    if not out and secs == 0:
        e["title"] = f"Missed a call from {who}"
    else:
        e["title"] = (f"Called {who}" if out else f"{who} called you") + (f" ({duration(secs)})" if secs else "")
        if secs:
            e["end"] = iso(r.t + timedelta(seconds=secs))
    e["people"] = [who]


def sum_email(e, recs, run):
    r = recs[0]
    to = str(r.meta.get("to") or r.participants or "").split(",")[0].strip()
    subject = clip(r.title or "(no subject)", 90)
    if r.me:
        e["title"] = f"Emailed {re.sub(r' *<[^>]*>', '', to) or 'someone'}: “{subject}”"
    else:
        sender = re.sub(r" *<[^>]*>", "", str(r.author or r.meta.get("from") or "someone"))
        e["title"] = f"Email from {sender}: “{subject}”"
        e["people"] = [sender]
    if r.text:
        e["lines"].append(clip(r.text, 160))


def sum_mail(e, recs, run):
    senders = {}
    for r in recs:
        name = re.sub(r" *<[^>]*>", "", str(r.author or r.meta.get("from") or "?")).strip() or "?"
        senders[name] = senders.get(name, 0) + 1
    e["title"] = f"{plural(len(recs), 'newsletter or notification', 'newsletters and notifications')} in {e['app']}"
    e["lines"] = [f"{name} ({n})" if n > 1 else name for name, n in sorted(senders.items(), key=lambda x: -x[1])]
    if recs[0].source == "facebook_activity":
        what = "notification" if recs[0].meta.get("file") == "notifications" else "email"
        e["title"] = f"{plural(len(recs), what)} from Facebook"
        e["lines"] = [clip(r.text if norm(r.title) in ("", norm(r.meta.get("file"))) else r.title, 100) for r in recs if r.title or r.text]
    day_long(e, recs[0].t)


def sum_browsing(e, recs, run):
    pages = [r for r in recs if r.kind == "visit"]
    queries = [r.meta.get("_q") for r in recs if r.kind == "search"]
    sites = {}
    for r in pages:
        h = host_of(r.url or r.fields.get("URL"))
        if h:
            sites[h] = sites.get(h, 0) + 1
    parts = [plural(len(pages), "page")] if pages else []
    if queries:
        parts.append("searched " + {1: "once", 2: "twice"}.get(len(queries), f"{len(queries)} times"))
    where = f" on your {e['device']}" if e["device"] == "iPhone" else ""
    if len(pages) == 1 and not queries:
        e["title"] = f"Visited {clip(pages[0].title or host_of(pages[0].url) or 'a page', 80)}{where}"
    elif not pages:
        e["title"] = f"Searched for “{clip(queries[0], 80)}”" + (f" and {plural(len(queries) - 1, 'other')}" if len(queries) > 1 else "") + where
    else:
        e["title"] = f"Browsed {' and '.join(parts)}{where}"
    e["lines"] = [f"Searched “{clip(q, 100)}”" for q in queries]
    e["lines"] += [f"{h} ({n})" if n > 1 else h for h, n in sorted(sites.items(), key=lambda x: -x[1])]


def sum_search(e, recs, run):
    qs = [r.meta.get("_q") for r in recs]
    e["title"] = f"Searched {e['app']} for “{clip(qs[0], 80)}”" + (f" and {plural(len(qs) - 1, 'other')}" if len(qs) > 1 else "")
    e["lines"] = [f"“{clip(q, 100)}”" for q in qs]


def sum_watch(e, recs, run):
    titles = [clip(re.sub(r"^Watched\s+", "", r.title or "a video"), 90) for r in recs]
    e["title"] = f"Watched {titles[0]}" if len(recs) == 1 else f"Watched {plural(len(recs), 'video')} on {e['app']}"
    e["lines"] = titles


def sum_listen(e, recs, run):
    artists = []
    for r in recs:
        a = r.meta.get("artist")
        if a and a not in artists:
            artists.append(a)
    if len(recs) == 1:
        e["title"] = f"Listened to {clip(recs[0].title, 70)}" + (f" by {artists[0]}" if artists else "")
    else:
        e["title"] = f"Listened to {plural(len(recs), 'track')} on {e['app']}" + (f": {', '.join(artists[:3])}" + (" and others" if len(artists) > 3 else "") if artists else "")
    e["lines"] = [clip(r.title, 70) + (f" — {r.meta['artist']}" if r.meta.get("artist") else "") for r in recs]


def sum_maps(e, recs, run):
    what = [clip(r.meta.get("_q") or re.sub(r"^(Viewed|Searched for|Directions to)\s+", "", r.title or "") or "a place", 90) for r in recs]
    e["title"] = f"Looked at maps: {what[0]}" + (f" and {plural(len(what) - 1, 'other')}" if len(what) > 1 else "")
    e["lines"] = what


# Photos others shared with you (photos.py's shared_photos), by how they came.
SHARED_APPS = {"shared_album": "Shared Albums", "shared_with_you": "Messages", "icloud_link": "iCloud Links", "shared_library": "Shared Library"}
SHARED_TITLES = {"shared_album": "in a shared album", "shared_with_you": "shared with you in Messages",
                 "icloud_link": "shared with you as an iCloud link", "shared_library": "added to your Shared Library by someone else"}


def sum_photos(e, recs, run):
    videos = sum(1 for r in recs if r.meta.get("type") == "video")
    photos = len(recs) - videos
    what = " and ".join(x for x in (plural(photos, "photo") if photos else "", plural(videos, "video") if videos else "") if x)
    place = next((r.meta.get("_place") for r in recs if r.meta.get("_place")), None)
    if recs[0].source == "shared_photos":  # not photos you took
        how = recs[0].meta.get("shared")
        e["title"] = (f"Posted {what} to a shared album" if recs[0].meta.get("copy")
                      else f"{what[0].upper()}{what[1:]} {SHARED_TITLES.get(how, 'shared with you')}")
    else:
        e["title"] = f"Took {what}" + (f" in {place}" if place else "")
    people = []
    for r in recs:
        m = re.search(r"^People: (.+)$", r.text or "", re.M)
        for p in (m.group(1).split(",") if m else []):
            if p.strip() and p.strip() not in people:
                people.append(p.strip())
    e["people"] = people
    places = []
    for r in recs:
        if r.meta.get("_place") and r.meta["_place"] not in places:
            places.append(r.meta["_place"])
    e["lines"] = [f"In {', '.join(places)}"] if len(places) > 1 else []
    e["photos"] = [r.rowid for r in recs][:12]


def sum_calendar(e, recs, run):
    r = recs[0]
    all_day = bool(r.meta.get("all_day")) or (r.end and (r.end - r.t) >= timedelta(hours=23) and r.t.hour == 0 and r.t.minute == 0)
    e["title"] = clip(r.title or "An event", 100)
    e["all_day"] = bool(all_day)
    if r.meta.get("location"):
        e["lines"].append(f"At {clip(r.meta['location'], 100)}")


def sum_note(e, recs, run):
    r = recs[0]
    e["title"] = f"Wrote in {e['app']}: {clip(r.title or 'a note', 80)}" if len(recs) == 1 else f"Wrote {plural(len(recs), 'note')} in {e['app']}"
    e["lines"] = [clip(x.title, 90) for x in recs if x.title] if len(recs) > 1 else ([clip(r.text, 160)] if r.text else [])


def sum_reminder(e, recs, run):
    e["title"] = f"Reminder: {clip(recs[0].title or 'something', 90)}"


def sum_voice(e, recs, run):
    r = recs[0]
    secs = r.meta.get("seconds") or r.meta.get("duration")
    e["title"] = f"Recorded a voice memo{': ' + clip(r.title, 60) if r.title else ''}" + (f" ({duration(num(secs))})" if num(secs) else "")


def sum_document(e, recs, run):
    names = [clip(r.title or Path(str(r.meta.get("path") or "")).name or "a file", 80) for r in recs]
    e["title"] = f"Worked on {names[0]}" if len(recs) == 1 else f"Worked on {plural(len(recs), 'file')}"
    e["lines"] = names if len(recs) > 1 else []


def sum_code(e, recs, run):
    repo = recs[0].meta.get("repo") or recs[0].thread_name or "a project"
    repo = Path(str(repo)).name or repo
    e["title"] = f"Committed to {repo}" + (f" ({len(recs)} commits)" if len(recs) > 1 else "")
    e["lines"] = [clip(r.title or r.text, 100) for r in recs]


def sum_ai(e, recs, run):
    asks = [r for r in recs if r.me]
    where = recs[0].meta.get("cwd")
    project = Path(str(where)).name if where else (recs[0].thread_name or None)
    tool = e["app"]
    e["title"] = (f"Worked with {tool}" if tool in ("Claude Code", "Codex") else f"Chatted with {tool}") + (f" on {clip(project, 50)}" if project else "") \
        + (f" ({plural(len(asks), 'prompt')})" if asks else "")
    e["lines"] = [clip(r.text, 140) for r in asks[:6]]


def sum_app(e, recs, run):
    secs = sum(num(r.meta.get("seconds") or r.fields.get("Foreground Duration (as stored)")) for r in recs)
    if not secs:
        secs = sum(((r.end or r.t) - r.t).total_seconds() for r in recs)
    e["title"] = f"Used {e['app']}" + (f" for {duration(secs)}" if secs >= 1 else "") + (f" on your {e['device']}" if e["device"] else "")
    e["seconds"] = round(secs)


def sum_health(e, recs, run):
    m, f = recs[0].meta, recs[0].fields
    if f.get("Achievement"):
        name = re.sub(r"(?<=[a-z])(?=[A-Z0-9])", " ", str(f["Achievement"])).replace("Percent", "%")
        e["title"] = f"Earned a Health award: {clip(name, 60)}"
        return
    bits = []
    if num(m.get("steps")):
        bits.append(f"walked {int(num(m['steps'])):,} steps")
    if num(m.get("distance_km")):
        bits.append(f"{num(m['distance_km']):.1f} km")
    if num(m.get("flights")):
        bits.append(f"{plural(int(num(m['flights'])), 'flight')} of stairs")
    e["title"] = ("You " + ", ".join(bits)) if bits else "Health: a day's totals"
    day_long(e, recs[0].t)


def sum_sleep(e, recs, run):
    r = recs[0]
    mins = num(r.meta.get("asleep_min")) or ((r.end - r.t).total_seconds() / 60 if r.end and r.end > r.t else 0)
    e["title"] = f"Slept {duration(mins * 60)}" if mins else "Slept"


SOCIAL_VERBS = {"reaction": ("Liked", "post"), "follow": ("Followed", "account"), "saved": ("Saved", "post"),
                "visit": ("Viewed", "post"), "post": ("Posted", "post"), "comment": ("Commented on", "post"),
                "contact": ("Connected with", "person"), "invitation": ("Invitations:", "invitation"),
                "message": ("Messaged", "person"), "search": ("Searched", "time"), "playlist": ("Made", "playlist"),
                "subscription": ("Subscribed to", "channel"), "vote": ("Voted on", "post")}
# Instagram's export says which list a record is from: the same kind can be something you did or something done to you.
SOCIAL_FILES = {"following": ("Followed", "account"), "close_friends": ("Added", "person to Close Friends", "people to Close Friends"),
                "recent_follow_requests": ("Asked to follow", "account"), "recently_unfollowed_profiles": ("Unfollowed", "account"),
                "liked_posts": ("Liked", "post"), "story_likes": ("Liked", "story", "stories"), "saved_posts": ("Saved", "post"),
                "videos_watched": ("Watched", "video"), "posts_viewed": ("Viewed", "post"), "stories_viewed": ("Viewed", "story", "stories"),
                "threads_viewed": ("Viewed", "thread"), "link_history": ("Opened", "link"), "liked_comments": ("Liked", "comment"),
                "post_comments_1": ("Commented on", "post"), "stories": ("Posted", "story", "stories"),
                "posts_you're_not_interested_in": ("Marked", "post as not interesting", "posts as not interesting"),
                # YouTube's (imports.py youtube)
                "comments.csv": ("Commented on", "video"), "live chats.csv": ("Chatted on", "live stream"),
                "videos.csv": ("Uploaded", "video")}


def added_to(e, recs, prep):
    """Something saved to a list (a playlist, Watch later): "Added Song A to “Road trip” on Spotify", or how many."""
    r = recs[0]
    what = clip(r.title, 70) if len(recs) == 1 and r.title else plural(len(recs), str(r.meta.get("what") or "item"))
    e["title"] = f"Added {what} to “{clip(r.meta['list'], 50)}” {prep} {e['app']}"
    e["lines"] = [clip(x.title or x.text, 100) for x in recs if (x.title or x.text)] if len(recs) > 1 else []


def sum_social(e, recs, run):
    k, file = recs[0].kind, str(recs[0].meta.get("file") or "")
    if k == "saved" and recs[0].meta.get("list"):
        return added_to(e, recs, "on")
    verb, *noun = SOCIAL_FILES.get(file) or SOCIAL_VERBS.get(k, ("Activity:", "item"))
    one, many = noun[0], (noun[1] if len(noun) > 1 else ("people" if noun[0] == "person" else None))
    if file.startswith("followers"):
        e["title"] = f"{plural(len(recs), 'person', 'people')} followed you on {e['app']}"
    elif file.startswith("follow_requests_you"):
        e["title"] = f"{plural(len(recs), 'person', 'people')} asked to follow you on {e['app']}"
    elif k == "post" and len(recs) == 1:
        e["title"] = f"Posted on {e['app']}: {clip(recs[0].text or recs[0].title, 90)}"
    elif k == "contact" and len(recs) == 1:
        e["title"] = f"Connected with {clip(recs[0].title, 60)} on {e['app']}"
    elif k == "invitation":
        sent = sum(r.me for r in recs)
        e["title"] = (f"Invited {plural(sent, 'person', 'people')}" if sent == len(recs) else f"Got {plural(len(recs) - sent, 'invitation')}"
                      + (f" and sent {sent}" if sent else "")) + f" on {e['app']}"
    elif verb == "Activity:":
        e["title"] = f"{plural(len(recs), 'thing')} on {e['app']}"
    else:
        e["title"] = f"{verb} {plural(len(recs), one, many)} on {e['app']}"
    e["lines"] = [clip(r.title or r.text, 100) for r in recs if (r.title or r.text)]


def sum_other(e, recs, run):
    k = recs[0].kind
    if k == "saved" and recs[0].meta.get("list"):
        return added_to(e, recs, "in")
    if k == "bookmark":
        e["title"] = f"Bookmarked {clip(recs[0].title or host_of(recs[0].url) or 'a page', 80)}" if len(recs) == 1 \
            else f"Bookmarked {plural(len(recs), 'page')} in {e['app']}"
        e["lines"] = [clip(r.title or r.url, 100) for r in recs if (r.title or r.url)] if len(recs) > 1 else []
        return
    first = clip(recs[0].title or recs[0].text, 90)
    if re.fullmatch(r"[\w./-]+", first or "") and not re.search(r"\d{3}", first):  # a machine word: "note-tweet", "data/x.js"
        first = re.sub(r"[_-]+", " ", Path(first).stem)
    if len(recs) == 1:
        e["title"] = f"{e['app']}: {first}" if first else f"Something in {e['app']}"
    else:
        e["title"] = f"{plural(len(recs), 'thing')} in {e['app']}"
        e["lines"] = [clip(r.title or r.text, 100) for r in recs if (r.title or r.text)]


SUMMARIES = {"conversation": sum_conversation, "call": sum_call, "email": sum_email, "mail": sum_mail,
             "browsing": sum_browsing, "search": sum_search, "watch": sum_watch, "listen": sum_listen, "maps": sum_maps,
             "photos": sum_photos, "calendar": sum_calendar, "note": sum_note, "reminder": sum_reminder,
             "voice": sum_voice, "document": sum_document, "code": sum_code, "ai": sum_ai, "app": sum_app,
             "health": sum_health, "sleep": sum_sleep, "social": sum_social, "money": sum_other, "travel": sum_other,
             "other": sum_other}

# ---------------------------------------------------------------- a month


def connect():
    if not DB.exists():
        raise FileNotFoundError("corpus.db doesn't exist yet: read some sources first")
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=10)
    con.execute("PRAGMA query_only = ON")
    return con


COLS = "rowid, source, id, kind, ts, ts_end, author, is_me, thread, thread_name, participants, title, text, url, meta"


def month(name, con=None, progress=None):
    """Every event in a local month ('2026-09'), in order. Also how many records were read, and how many left out."""
    lo, hi = month_range(name)
    return {"month": name, **between(lo, hi, con, progress)}


def between(lo, hi, con=None, progress=None):
    """Every event from one local time to another (a month; a day, for Ask), in order, with how many records were
    read and how many left out."""
    con = con or connect()
    # A day either side in UTC, for records in their own time zones; then only what falls in the span locally.
    rows = con.execute(f"select {COLS} from records where ts >= ? and ts < ? order by ts",
                       ((lo - timedelta(days=1)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
                        (hi + timedelta(days=1)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"))).fetchall()
    mine = me_names()
    recs = [r for r in map(Rec, rows) if r.t and lo <= r.t < hi]
    ctx = {"screen_time_iphone": any(r.source == "app_usage" and "iphone" in str(r.meta.get("device") or "").lower() for r in recs)}
    items, left_out = [], 0
    for i, r in enumerate(recs):
        if progress and i % 2000 == 0:
            progress(i, len(recs))
        try:
            it = classify(r, mine, ctx)
        except Exception:  # noqa: BLE001 - as in event(): an unexpected shape makes a plain event, never an error
            it = Item(r, "other", app_name(r.source), ("other", r.source, r.kind), 30 * 60)
        if it:
            items.append(it)
        else:
            left_out += 1
    events = [event(run) for run in runs(merge_duplicates(items))]
    # Glances at an app (under 2 minutes in a run) are left out; Google's "used an app" records have no length.
    events = [e for e in events if not (e["kind"] == "app" and e.get("seconds") is not None and 0 < e["seconds"] < 120)]
    # In the order things happened, whatever zone each is written in (photos keep their own).
    events.sort(key=lambda e: (e.pop("_at"), e["kind"]))
    return {"records": len(recs), "left_out": left_out, "events": events}


def this_month():
    return datetime.now(TZ).strftime("%Y-%m")


def months(con=None):
    """Months with records, newest first, up to this one (a record dated later is a bad date, or a plan), and how
    many records each has (by UTC month, a close guide)."""
    con = con or connect()
    rows = con.execute("select substr(ts, 1, 7), count(*) from records where ts >= '1900' and ts < '2100' "
                       "and ts not like '1900-01-01T00:00:00%' and ts not like '1970-01-01T00:00:00%' and ts not like '2001-01-01T00:00:00%' and ts not in ('1900-01-01', '1970-01-01', '2001-01-01') "
                       "group by 1 order by 1 desc").fetchall()
    now = this_month()
    return [{"month": m, "records": n} for m, n in rows if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", m or "") and m <= now]


def record_hash(*fields):
    """32 bits of a record's fields: summed over a month, the sum changes when any record does."""
    return zlib.crc32("\x1f".join("" if f is None else str(f) for f in fields).encode("utf-8", "replace"))


def signature(con, name):
    """What a month's events are made of: every record's fields an event uses (who wrote it and whether it's yours,
    when, its title and thread, its meta), its text by length, and who you are. A relabel (an address added to who you
    are, a sender put right) changes no count, but it's a new month all the same."""
    lo, hi = month_range(name)
    a, b = ((x - timedelta(days=1)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") for x in (lo, hi + timedelta(days=2)))
    con.create_function("record_hash", -1, record_hash, deterministic=True)
    row = con.execute("select count(*), total(length(coalesce(text, ''))), sum(record_hash(source, id, kind, ts, ts_end, author, "
                      "is_me, thread, thread_name, participants, title, url, meta)) from records where ts >= ? and ts < ?",
                      (a, b)).fetchone()
    return hashlib.sha1(json.dumps([VERSION, str(TZ), row, sorted(me_names())]).encode()).hexdigest()[:16]


def build(everything=False, log=print):
    """corpus/stream/YYYY-MM.jsonl for every month whose records changed since it was last written."""
    con = connect()
    OUT.mkdir(parents=True, exist_ok=True)
    index_file = OUT / "months.json"
    try:
        index = json.loads(index_file.read_text())
    except (OSError, ValueError):
        index = {}
    have = {m["month"] for m in months(con)}
    # A UTC month can hold the first hours of the next local month (or the last of the one before).
    local = set()
    for m in have:
        y, mm = map(int, m.split("-"))
        for d in (-1, 0, 1):
            yy, m2 = y + (mm + d - 1) // 12, (mm + d - 1) % 12 + 1
            local.add(f"{yy:04d}-{m2:02d}")
    built = 0
    local = {m for m in local if m <= this_month()}
    for name in sorted(local):
        sig = signature(con, name)
        if not everything and index.get(name, {}).get("signature") == sig and (OUT / f"{name}.jsonl").exists():
            continue
        r = month(name, con)
        if not r["events"]:
            (OUT / f"{name}.jsonl").unlink(missing_ok=True)
            index.pop(name, None)
            continue
        tmp = OUT / f"{name}.jsonl.tmp"
        with tmp.open("w") as fh:
            for e in r["events"]:
                fh.write(json.dumps({k: v for k, v in e.items() if k not in ("rowids", "photos")}, ensure_ascii=False) + "\n")
        tmp.replace(OUT / f"{name}.jsonl")
        index[name] = {"events": len(r["events"]), "records": r["records"], "left_out": r["left_out"], "signature": sig}
        built += 1
    for name in [m for m in index if m not in local]:
        (OUT / f"{name}.jsonl").unlink(missing_ok=True)
        index.pop(name)
    tmp = index_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(dict(sorted(index.items())), indent=1))
    tmp.replace(index_file)
    log(f"stream: {built} month{'s' if built != 1 else ''} written, {len(index)} in corpus/stream/")
    return index


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else ""
    if cmd == "month" and len(argv) > 1:
        for e in month(argv[1])["events"]:
            print(json.dumps({k: v for k, v in e.items() if k not in ("rowids", "photos")}, ensure_ascii=False))
    elif cmd == "build":
        build(everything="--all" in argv)
    elif cmd == "months":
        print(json.dumps(months()))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
