"""Account data exports dropped into corpus/imports/ (zip files, nested zips, or unzipped folders).
Formats are auto-detected from file names / columns, so exports can be dropped in as downloaded.

    ChatGPT ......... conversations.json with "mapping"            -> chatgpt
    Claude.ai ....... conversations.json with "chat_messages"      -> claude_ai
    Google Takeout .. Mail/*.mbox -> gmail; My Activity/*/MyActivity.json, YouTube watch/search history
                      -> google_activity; Calendar/*.ics -> google_calendar; Contacts/*.vcf -> google_contacts;
                      Chrome/History.json -> chrome_synced; Keep/*.json -> google_keep;
                      Google Chat/Groups/*/messages.json -> google_chat; Google Photos/*.json
                      sidecars -> google_photos; Maps saved places / reviews -> google_maps_places;
                      Timeline.json or Semantic Location History -> location_history
    Discord ......... Messages/index.json + Messages/c*/messages.json|csv -> discord
    Meta ............ messages/*/*/message_N.json -> instagram | messenger; posts / comments -> *_activity
    X ............... data/tweets.js, direct-messages*.js, like.js -> x
    LinkedIn ........ messages.csv, Connections.csv, Shares.csv, Comments.csv -> linkedin
    Reddit .......... comments.csv, posts.csv, messages.csv -> reddit
    Spotify ......... Streaming_History_*.json / StreamingHistory*.json -> spotify
    WhatsApp ........ exported chat .txt -> whatsapp_export
    Slack ........... users.json + <channel>/<YYYY-MM-DD>.json -> slack
    Zoom ............ *.vtt transcripts -> zoom
    anything else ... pdf/docx/pptx/pages/md/txt/html/ipynb -> imported_documents (e.g. Drive, Notion export)
"""

import collections
import csv
import hashlib
import io
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

from browser_history import classify
from common import MANIFEST, CORPUS, Writer, from_unix
from contacts import parse_vcards, vcard_name
from mapped_exports import MAPPED, mapped_exports
from email_parse import html_to_text, iter_mbox, parse as parse_email
from identity import ME, is_me_email, is_me_name

IMPORTS = CORPUS / "imports"
MEDIA = CORPUS / "media"  # attachments copied out of exports, as plain files
DROP = "Drop the downloaded export (zip or folder) into corpus/imports/."
AV = {
    "chatgpt": f"ChatGPT > Settings > Data controls > Export data (emailed link, ~minutes-hours). {DROP}",
    "claude_ai": f"claude.ai > Settings > Privacy > Export data (emailed link). {DROP}",
    "gmail": f"Google Takeout (takeout.google.com) > Mail (mbox). {DROP}",
    "hotmail": f"Outlook.com: add the account in System Settings > Internet Accounts > Microsoft Exchange, let Mail.app download it, then Mailbox > Export Mailbox into corpus/imports/hotmail/ (outlook.live.com has no web export). {DROP}",
    "google_activity": f"Google Takeout > My Activity (choose JSON, not HTML) + YouTube and YouTube Music (history in JSON). {DROP}",
    "google_calendar": f"Google Takeout > Calendar (.ics). {DROP}",
    "google_contacts": f"Google Takeout > Contacts (vCard). {DROP}",
    "vcard_contacts": f"Any other vCard export, e.g. iPhone Contacts > Lists > All Contacts > Export (AirDrop the .vcf to the Mac). {DROP}",
    "chrome_synced": f"Google Takeout > Chrome (History.json, synced history beyond Chrome's local 90 days). {DROP}",
    "google_keep": f"Google Takeout > Keep. {DROP}",
    "google_chat": f"Google Takeout > Google Chat (includes old Hangouts). {DROP}",
    "google_photos": f"Google Takeout > Google Photos (JSON sidecars give time, GPS, people). {DROP}",
    "google_maps_places": f"Google Takeout > Maps (your places) / Saved. {DROP}",
    "location_history": f"Google Maps app on phone > Settings > Location & privacy > Export Timeline data (Timeline.json); older Takeouts have Semantic Location History. {DROP}",
    "discord": f"Discord > Settings > Data & Privacy > Request all of my data (emailed, up to 30 days). Only your own messages. {DROP}",
    "instagram": f"Meta Accounts Center > Your information and permissions > Download your information (JSON). {DROP}",
    "messenger": f"Meta Accounts Center > Download your information > Facebook (JSON, include Messages). {DROP}",
    "instagram_activity": f"Meta Accounts Center > Download your information (JSON). {DROP}",
    "facebook_activity": f"Meta Accounts Center > Download your information > Facebook (JSON). {DROP}",
    "x": f"X > Settings > Your account > Download an archive of your data (~24h). {DROP}",
    "linkedin": f"LinkedIn > Settings > Data privacy > Get a copy of your data (full archive, ~24h). {DROP}",
    "reddit": f"reddit.com/settings/data-request (emailed, ~days). {DROP}",
    "spotify": f"Spotify account > Privacy settings > Download your data (Extended streaming history, ~days-30 days). {DROP}",
    "whatsapp_export": f"WhatsApp on phone > chat > Export chat (without media), per chat. History retained on the phone comes from connectors/iphone.py via iLEAPP (phone_whatsapp). {DROP}",
    "slack": f"Slack workspace export (admin) or slackdump. {DROP}",
    "zoom": f"Zoom web > Recordings > Cloud recordings > download transcript (.vtt). {DROP}",
    "notion_export": f"Notion > Settings > General > Export all workspace content (Markdown & CSV, include subpages). {DROP}",
    "imported_documents": f"Any other files (Google Drive via Takeout, Notion 'Export all workspace content'). {DROP}",
}
DOC_EXT = {".pdf", ".docx", ".doc", ".rtf", ".odt", ".pptx", ".pages", ".key", ".md", ".markdown", ".txt", ".tex",
           ".html", ".htm", ".ipynb"}


class Entry:
    def __init__(self, path, opener, size, origin):
        self.path, self.open, self.size, self.origin = path, opener, size, origin

    @property
    def name(self):
        return PurePosixPath(self.path).name

    def read(self):
        with self.open() as f:
            return f.read()

    def text(self):
        return self.read().decode("utf-8-sig", "replace")

    def json(self):
        return json.loads(self.text())


def safe_member(name):
    """An archive entry name that stays inside the archive: no absolute path, drive or '..' (zip-slip)."""
    parts = name.replace("\\", "/").split("/")
    return not (name.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", name) or ".." in parts)


TAR_EXT = (".tar", ".tar.gz", ".tgz")
_unpacked = []  # where tar exports were unpacked, removed when the run ends


def entries():
    out = []
    if not IMPORTS.exists():
        return out

    def add_zip(z, origin, prefix=""):
        for info in z.infolist():
            if info.is_dir() or "__MACOSX/" in info.filename or not safe_member(info.filename):
                continue
            if info.filename.lower().endswith(".zip") and info.file_size < 2**31:
                try:
                    add_zip(zipfile.ZipFile(io.BytesIO(z.read(info))), origin, prefix + info.filename + "/")
                except zipfile.BadZipFile:
                    pass
                continue
            out.append(Entry(prefix + info.filename, lambda z=z, i=info: z.open(i), info.file_size, origin))

    def add_tar(p, origin):
        """GitHub's export is a .tar.gz. Unpacked once (a compressed tar can't be read file by file without starting
        over each time), with tarfile's "data" filter: no links, devices or names outside the folder."""
        tmp = tempfile.TemporaryDirectory(prefix="ump-tar-")
        _unpacked.append(tmp)
        try:
            with tarfile.open(p) as t:
                t.extractall(tmp.name, members=[m for m in t.getmembers() if m.isfile() and safe_member(m.name)],
                             filter="data")
        except (tarfile.TarError, OSError, EOFError):
            return
        root = Path(tmp.name)
        for f in sorted(root.rglob("*")):
            if f.is_symlink() or not f.is_file():
                continue
            name = f.relative_to(root).as_posix()
            if name.lower().endswith(".zip"):
                try:
                    add_zip(zipfile.ZipFile(f), origin, name + "/")
                except zipfile.BadZipFile:
                    pass
                continue
            out.append(Entry(name, lambda f=f: open(f, "rb"), f.stat().st_size, origin))

    for p in sorted(IMPORTS.rglob("*")):
        # A link in an export folder could pull in any file on this Mac (~/.ssh/...): only real files count.
        # (rglob doesn't descend into linked folders.)
        if p.is_symlink() or not p.is_file() or p.name.startswith("."):
            continue
        rel = p.relative_to(IMPORTS)
        if p.suffix.lower() == ".zip":
            try:
                add_zip(zipfile.ZipFile(p), str(rel))
            except zipfile.BadZipFile:
                pass
        elif p.name.lower().endswith(TAR_EXT):
            add_tar(p, str(rel))
        else:
            out.append(Entry(rel.as_posix(), lambda p=p: open(p, "rb"), p.stat().st_size, rel.parts[0]))
    return out


def iso(d):
    return d.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if d.tzinfo else d.isoformat()


def parse_time(s, *fmts):
    if not s:
        return None
    s = str(s).strip()
    try:
        return iso(datetime.fromisoformat(s.replace("Z", "+00:00").replace(" UTC", "+00:00")))
    except ValueError:
        pass
    for f in fmts:
        try:
            return iso(datetime.strptime(s, f))
        except ValueError:
            continue
    return None


def rid(*parts):
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:20]


def fix_meta(s):
    """Meta exports double-encode UTF-8 as latin-1."""
    if not isinstance(s, str):
        return s
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def read_csv(e):
    text = e.text()
    if text.startswith("Notes:"):
        i = text.find("\n\n")
        text = text[i + 2:] if i >= 0 else text
    return list(csv.DictReader(io.StringIO(text)))


# ---------------------------------------------------------------- AI assistants

def ai_exports(es, W, used):
    for e in es:
        if e.name != "conversations.json":
            continue
        data = e.json()
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            continue
        used.add(e.path)
        if "mapping" in data[0]:
            w = W("chatgpt")
            for c in data:
                mapping, node, chain = c.get("mapping") or {}, c.get("current_node"), []
                while node in mapping:
                    chain.append(mapping[node])
                    node = mapping[node].get("parent")
                for n in reversed(chain):
                    m = n.get("message") or {}
                    role = (m.get("author") or {}).get("role")
                    content = m.get("content") or {}
                    parts = content.get("parts") or []
                    text = "\n".join(p if isinstance(p, str) else str(p.get("text") or "") for p in parts if isinstance(p, (str, dict)))
                    if role not in ("user", "assistant") or not text.strip() or w.has(m.get("id")):
                        continue
                    w.add(id=m.get("id"), kind="ai_turn", ts=from_unix(m.get("create_time") or c.get("create_time")),
                          author="me" if role == "user" else "chatgpt", is_me=role == "user",
                          thread=c.get("id") or c.get("conversation_id"), thread_name=c.get("title"), text=text,
                          meta={"tool": "chatgpt", "model": (m.get("metadata") or {}).get("model_slug")})
        elif "chat_messages" in data[0]:
            w = W("claude_ai")
            for c in data:
                for m in c.get("chat_messages") or []:
                    text = m.get("text") or "\n".join(b.get("text", "") for b in m.get("content") or [] if b.get("type") == "text")
                    files = [a.get("file_name") for a in (m.get("attachments") or []) + (m.get("files") or []) if a.get("file_name")]
                    if files:
                        text += "\n" + "\n".join(f"[attachment: {f}]" for f in files)
                    if not text.strip() or w.has(m.get("uuid")):
                        continue
                    me = m.get("sender") == "human"
                    w.add(id=m.get("uuid"), kind="ai_turn", ts=m.get("created_at"), author="me" if me else "claude", is_me=me,
                          thread=c.get("uuid"), thread_name=c.get("name"), text=text, meta={"tool": "claude.ai"})


# ---------------------------------------------------------------- Google Takeout

ACTIVITY = (("Searched for ", "search"), ("Watched ", "media"), ("Listened to ", "media"), ("Visited ", "visit"),
            ("Viewed ", "visit"), ("Used ", "app_usage"), ("Prompted ", "ai_turn"), ("Asked ", "ai_turn"))


SENT_FOLDERS = {"sent", "sent items", "sent messages", "sent mail"}
# Kept, but tagged meta.tier so searches can leave them out: junk can hide real mail, and deleted mail is mail
# the user received or wrote.
SKIP_FOLDERS = {"junk", "junk email", "spam", "trash", "deleted items", "deleted messages", "outbox"}
TIER_OF_FOLDER = {"junk": "spam", "junk email": "spam", "spam": "spam", "trash": "deleted", "deleted items": "deleted",
                  "deleted messages": "deleted", "outbox": "unsent"}


def mbox_folder(p):
    """Mail.app's Export Mailbox writes <Folder>.mbox/mbox; other tools write <Folder>.mbox."""
    path = PurePosixPath(p)
    name = path.parent.name if path.name == "mbox" else path.name
    name = name[:-5] if name.lower().endswith(".mbox") else name
    base = re.sub(r" \d+$", "", name)  # Mail splits big folders into ~2 GB pieces: Inbox, Inbox 2, Inbox 3, ...
    return base if base.lower() in SENT_FOLDERS | SKIP_FOLDERS | {"inbox", "archive", "drafts"} else name


def google(es, W, used):
    for e in es:
        p = e.path
        if p.lower().endswith(".mbox") or p.endswith(".mbox/mbox"):
            used.add(p)
            takeout = "Takeout/" in p or "Mail/" in p and "takeout" in e.origin.lower()
            # Takeout mail is Gmail; any other mailbox export is named after its folder in corpus/imports/ (e.g. hotmail)
            source = "gmail" if takeout else re.sub(r"\W+", "_", PurePosixPath(e.origin).parts[0].lower())
            folder = mbox_folder(p)
            w = W(source)
            with e.open() as f:
                for raw in iter_mbox(f):
                    try:
                        rec = parse_email(raw)
                    except Exception:
                        continue
                    labels = rec.pop("_labels")
                    if takeout and ("Spam" in labels or "Trash" in labels):
                        rec["meta"]["tier"] = "spam" if "Spam" in labels else "deleted"
                    if not takeout:  # no Gmail labels: the folder decides
                        if folder.lower() in SKIP_FOLDERS:
                            rec["meta"]["tier"] = TIER_OF_FOLDER[folder.lower()]
                        if folder.lower() in SENT_FOLDERS or folder.lower() in ("drafts", "outbox"):
                            rec["is_me"], rec["author"] = True, "me"
                        rec["meta"]["folder"] = folder
                    if w.has(rec["id"]):
                        continue
                    w.add(kind="email", **rec)
        elif p.endswith("MyActivity.json") or re.search(r"(watch|search)-history\.json$", p):
            used.add(p)
            w = W("google_activity")
            try:
                items = e.json()
            except ValueError:
                continue
            for it in items if isinstance(items, list) else []:
                title = it.get("title") or ""
                kind, text = "activity", title
                for pre, k in ACTIVITY:
                    if title.startswith(pre):
                        kind, text = k, title[len(pre):]
                        break
                subs = ", ".join(s.get("name", "") for s in it.get("subtitles") or [] if s.get("name"))
                resp = " ".join(html_to_text(h.get("html", "")) for h in it.get("safeHtmlItem") or [] if isinstance(h, dict))
                key = rid(it.get("header"), title, it.get("time"))
                if w.has(key):
                    continue
                w.add(id=key, kind=kind, ts=parse_time(it.get("time")), author="me", is_me=True, thread=it.get("header"),
                      thread_name=it.get("header"), title=text[:300], text="\n".join(x for x in (text, subs, resp[:20000]) if x),
                      url=it.get("titleUrl"), meta={"product": it.get("header")})
        elif p.lower().endswith(".ics"):
            used.add(p)
            w = W("google_calendar")
            body = re.sub(r"\r?\n[ \t]", "", e.text())
            for block in re.findall(r"BEGIN:VEVENT\r?\n(.*?)END:VEVENT", body, re.S):
                props, people = {}, []
                for line in block.splitlines():
                    if ":" not in line:
                        continue
                    key, val = line.split(":", 1)
                    name, *params = key.split(";")
                    val = val.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";")
                    if name == "ATTENDEE":
                        cn = next((x[3:] for x in params if x.upper().startswith("CN=")), None)
                        people.append((cn or val.replace("mailto:", "")).strip('"'))
                    else:
                        props.setdefault(name, val)
                start = ics_time(props.get("DTSTART", ""))
                key = f"{props.get('UID')}:{props.get('RECURRENCE-ID') or props.get('DTSTART')}"
                if w.has(key):
                    continue
                lines = [props.get("SUMMARY", ""), f"Location: {props['LOCATION']}" if props.get("LOCATION") else "",
                         "Attendees: " + ", ".join(people) if people else "", props.get("DESCRIPTION", "")]
                w.add(id=key, kind="event", ts=start, ts_end=ics_time(props.get("DTEND", "")), title=props.get("SUMMARY"),
                      text="\n".join(x for x in lines if x), participants=people or None,
                      thread=PurePosixPath(p).stem, thread_name=PurePosixPath(p).stem,
                      meta={k: v for k, v in (("location", props.get("LOCATION")), ("recurring", "RRULE" in props or None)) if v})
        elif p.lower().endswith(".vcf"):
            used.add(p)
            w = W("google_contacts" if "Takeout/" in p or "/Contacts/" in "/" + p else "vcard_contacts")
            for d in parse_vcards(e.text()):
                name = vcard_name(d)
                key = rid(name, d.get("TEL"), d.get("EMAIL"))
                if not name or w.has(key):
                    continue
                lines = [name] + [f"{k.lower()}: {v}" for k in ("TEL", "EMAIL", "ORG", "TITLE", "BDAY", "ADR", "URL", "NOTE") for v in d.get(k, [])]
                w.add(id=key, kind="contact", title=name, text="\n".join(lines))
        elif re.search(r"Chrome/(Browser)?History\.json$", p):
            used.add(p)
            w = W("chrome_synced")
            for it in e.json().get("Browser History", []):
                key = rid(it.get("url"), it.get("time_usec"))
                if w.has(key):
                    continue
                tag, q = classify(it.get("url") or "")
                kind = "search" if tag in ("search", "youtube_search") and q else "visit"
                w.add(id=key, kind=kind, ts=from_unix(it.get("time_usec"), "us"), author="me", is_me=True,
                      title=q if kind == "search" else it.get("title"), url=it.get("url"),
                      text=q if kind == "search" else "\n".join(x for x in (it.get("title"), it.get("url")) if x),
                      meta={"tag": tag, "transition": it.get("page_transition")})
        elif "/Keep/" in "/" + p and p.endswith(".json"):
            used.add(p)
            d = e.json()
            if not isinstance(d, dict) or d.get("isTrashed"):
                continue
            items = "\n".join(("[x] " if i.get("isChecked") else "[ ] ") + i.get("text", "") for i in d.get("listContent") or [])
            W("google_keep").add(id=p, kind="note", ts=from_unix(d.get("createdTimestampUsec"), "us"), author="me", is_me=True,
                                 thread="Keep", thread_name="Google Keep", title=d.get("title") or None,
                                 text="\n".join(x for x in (d.get("title"), d.get("textContent"), items) if x),
                                 meta={"modified": from_unix(d.get("userEditedTimestampUsec"), "us"),
                                       "labels": [l.get("name") for l in d.get("labels") or []] or None})
        elif "Google Photos/" in p and p.endswith(".json"):
            used.add(p)
            try:
                d = e.json()
            except ValueError:
                continue
            if not isinstance(d, dict) or "photoTakenTime" not in d:
                continue
            geo = d.get("geoData") or {}
            people = [x.get("name") for x in d.get("people") or [] if x.get("name")]
            album = PurePosixPath(p).parent.name
            lines = [f"Photo: {d.get('title')}", f"Album: {album}", "People: " + ", ".join(people) if people else "",
                     d.get("description") or ""]
            W("google_photos").add(id=p, kind="photo", ts=from_unix((d.get("photoTakenTime") or {}).get("timestamp")),
                                   author="me", is_me=True, thread=album, thread_name=album, title=d.get("title"),
                                   participants=people or None, text="\n".join(x for x in lines if x), url=d.get("url"),
                                   meta={k: v for k, v in (("lat", geo.get("latitude") or None), ("lon", geo.get("longitude") or None)) if v})
        elif p.endswith(("Saved Places.json", "Reviews.json")) or "Labeled places" in p:
            used.add(p)
            w = W("google_maps_places")
            for f in e.json().get("features", []):
                pr = f.get("properties") or {}
                loc = pr.get("location") or {}
                name = loc.get("name") or pr.get("Title") or pr.get("name") or loc.get("address")
                review = pr.get("review_text_published")
                coords = (f.get("geometry") or {}).get("coordinates") or [None, None]
                key = rid(p, name, pr.get("date"), coords)
                if not name or w.has(key):
                    continue
                lines = [name, loc.get("address") or pr.get("address") or "",
                         f"Rating: {pr['five_star_rating_published']}" if pr.get("five_star_rating_published") else "",
                         review or "", pr.get("Comment") or ""]
                w.add(id=key, kind="place", ts=parse_time(pr.get("date") or pr.get("Published")), author="me", is_me=True,
                      thread=PurePosixPath(p).stem, thread_name=PurePosixPath(p).stem, title=name,
                      text="\n".join(x for x in lines if x), url=pr.get("google_maps_url"),
                      meta={"lon": coords[0], "lat": coords[1] if len(coords) > 1 else None})
        elif PurePosixPath(p).name in ("Timeline.json", "location-history.json") or "Semantic Location History" in p:
            used.add(p)
            location_history(e, W("location_history"))


def ics_time(v):
    v = v.strip()
    try:
        if len(v) == 8:
            return datetime.strptime(v, "%Y%m%d").date().isoformat()
        if v.endswith("Z"):
            return iso(datetime.strptime(v, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc))
        return datetime.strptime(v[:15], "%Y%m%dT%H%M%S").isoformat()
    except ValueError:
        return None


def location_history(e, w):
    d = e.json()
    segs = d.get("semanticSegments") if isinstance(d, dict) else d
    if isinstance(segs, list):  # on-device Timeline export
        for s in segs:
            visit = s.get("visit") if isinstance(s, dict) else None
            if not visit:
                continue
            top = visit.get("topCandidate") or {}
            latlng = (top.get("placeLocation") or {}).get("latLng") or top.get("placeLocation")
            key = rid(s.get("startTime"), top.get("placeId"))
            if w.has(key):
                continue
            w.add(id=key, kind="place_visit", ts=parse_time(s.get("startTime")), ts_end=parse_time(s.get("endTime")),
                  author="me", is_me=True, title=top.get("semanticType"),
                  text=f"Visited {top.get('semanticType') or 'place'} at {latlng}",
                  meta={"place_id": top.get("placeId"), "latlng": latlng, "probability": top.get("probability")})
    for obj in (d.get("timelineObjects") or []) if isinstance(d, dict) else []:
        pv = obj.get("placeVisit")
        if not pv:
            continue
        loc, dur = pv.get("location") or {}, pv.get("duration") or {}
        start = dur.get("startTimestamp") or from_unix(dur.get("startTimestampMs"), "ms")
        key = rid(start, loc.get("placeId"))
        if w.has(key):
            continue
        name = loc.get("name") or loc.get("address") or "place"
        w.add(id=key, kind="place_visit", ts=parse_time(start), ts_end=parse_time(dur.get("endTimestamp")) or from_unix(dur.get("endTimestampMs"), "ms"),
              author="me", is_me=True, title=name, text="\n".join(x for x in (f"Visited {name}", loc.get("address")) if x),
              meta={"place_id": loc.get("placeId"), "lat": (loc.get("latitudeE7") or 0) / 1e7 or None,
                    "lon": (loc.get("longitudeE7") or 0) / 1e7 or None, "semantic": loc.get("semanticType")})


# ---------------------------------------------------------------- Chat apps

def discord(es, W, used):
    """Discord data package: Messages/index.json names channels, Messages/c<id>/{channel.json,messages.json|csv}
    hold only messages I sent. Account/user.json's friends list names DM and group-DM recipients."""
    names, chans, people, me_id = {}, collections.defaultdict(dict), {}, None
    for e in es:
        if re.search(r"(^|/)messages/index\.json$", e.path, re.I):
            names = e.json()
            used.add(e.path)
        elif re.search(r"(^|/)account/user\.json$", e.path, re.I):
            used.add(e.path)
            u = e.json()
            me_id = u.get("id")
            for r in u.get("relationships") or []:
                user = r.get("user") or {}
                people[str(user.get("id") or r.get("id"))] = r.get("nickname") or user.get("global_name") or user.get("username")
        m = re.search(r"(^|/)messages/c?(\d+)/(channel\.json|messages\.json|messages\.csv)$", e.path, re.I)
        if m:
            chans[m.group(2)][m.group(3).lower()] = e
            used.add(e.path)
    for cid, files in chans.items():
        info = files["channel.json"].json() if "channel.json" in files else {}
        guild = (info.get("guild") or {}).get("name")
        others = [people.get(str(r), str(r)) for r in info.get("recipients") or [] if str(r) != str(me_id)]
        known = [p for p in others if not p.isdigit()]  # recipients not on my friends list stay as raw ids
        name = names.get(cid)
        if not name or name == "None" or "Unknown Participant" in name:  # the index leaves many DMs unnamed
            who = ", ".join(known) + (f" +{len(others) - len(known)}" if len(others) > len(known) else "")
            name = info.get("name") or (("DM with " if info.get("type") == "DM" else "Group DM with ") + who.lstrip(" ")
                                         if others else guild or cid)
        if "messages.json" in files:
            msgs = files["messages.json"].json()
        elif "messages.csv" in files:
            msgs = list(csv.DictReader(io.StringIO(files["messages.csv"].text())))
        else:
            continue
        w = W("discord")
        for m in msgs:
            text = (m.get("Contents") or "") + (f"\n[attachment: {m['Attachments']}]" if m.get("Attachments") else "")
            key = f"{cid}:{m.get('ID')}"
            if not text.strip() or w.has(key):
                continue
            w.add(id=key, kind="message", ts=parse_time(m.get("Timestamp")), author="me", is_me=True, thread=cid,
                  thread_name=name, participants=others or None, text=text,
                  meta={k: v for k, v in (("server", guild), ("channel_type", info.get("type"))) if v})


# Meta (Instagram / Facebook) data files besides messages: path pattern -> kind; first match wins. Every other
# JSON file is kept too, as kind "record" (ads shown, payments, settings, ...), except META_SKIP (other people:
# suggestions) and META_SECURITY (logins, sessions, IP addresses, devices, cookies, 2FA).
META_SKIP = r"people_you_may_know|suggested"  # other people Meta suggested
META_SECURITY = (r"login|logout|session|password|two_factor|recognized_devices|authorized|ip_address|cookie|"
                 r"security_and_login|account_activity|device")
META_FILES = (
    (r"posts_viewed|videos_watched|stories_viewed|threads_viewed|link_history|"
     r"interactions/(profile_visits|groups_and_events|items_viewed|shows_you_have)", "visit"),
    (r"likes/|likes_and_reactions|story_likes|story_interactions/", "reaction"),
    (r"saved/|saved_items", "saved"),
    (r"followers|following|close_friends|follow_requests|recently_unfollowed|friends/|group_membership_activity", "follow"),
    (r"recent_searches/|search_history|searches", "search"),
    (r"comments", "comment"),
    (r"media/(posts|archived_posts|stories|reels|profile_photos|other_content)|your_posts|posts_on_other_pages|"
     r"posts/album/|uncategorized_photos", "post"),
    (r"event_invitations|event_responses", "event"),
    (r"your_places/", "place"),
    (r"interest_categories|your_topics|ads_interests", "inference"),
    (r"personal_information/personal_information/(personal_information|profile_changes)|instagram_profile_information|"
     r"profile_information/(profile_information|profile_update_history)\.json", "profile"),
)
MEDIA_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".mp4", ".mov", ".m4a", ".aac", ".mp3", ".wav", ".srt")


def meta_item(item):
    """Flatten one item of a Meta export into (label, value) pairs, media uris and unix times. Handles both
    layouts: label_values lists ({label, value | href | timestamp_value | media | dict | vec}), the older
    string_map_data / string_list_data, and plain items like {"name": ..., "timestamp": ...}."""
    pairs, media, times = [], [], []

    def take(label, d):
        v = d.get("value") or d.get("href")
        if v not in (None, ""):
            pairs.append((label, fix_meta(str(v))))
        if d.get("timestamp") or d.get("timestamp_value"):
            times.append(d.get("timestamp") or d.get("timestamp_value"))

    def walk(x, label):
        if isinstance(x, list):
            for y in x:
                walk(y, label)
        elif isinstance(x, dict):
            if isinstance(x.get("uri"), str):  # a media file
                if x["uri"]:
                    media.append(x["uri"])
                if x.get("creation_timestamp"):
                    times.append(x["creation_timestamp"])
                if x.get("title"):
                    pairs.append(("Title", fix_meta(x["title"])))
                return
            if "label" in x:
                label = fix_meta(x["label"])
                take(label, x)
                for k in ("media", "dict", "vec"):
                    walk(x.get(k), label)
                return
            for k, v in x.items():
                if k == "string_map_data":
                    for lab, d in v.items():
                        take(fix_meta(lab), d)
                elif k == "string_list_data":
                    for d in v:
                        take(label or "Value", d)
                elif k in ("timestamp", "creation_timestamp") and v:
                    times.append(v)
                elif isinstance(v, str) and v and k not in ("fbid", "href"):  # older plain items: {"name": ..., "timestamp": ...}
                    pairs.append((k.replace("_", " ").capitalize(), fix_meta(v)))
                elif isinstance(v, (list, dict)) and k != "media_metadata":
                    walk(v, label)

    walk(item, None)
    return pairs, media, times


def meta(es, W, used):
    """Instagram and Facebook exports from Accounts Center (JSON). DMs -> instagram / messenger; the files in
    META_FILES -> instagram_activity / facebook_activity. Photos and videos are copied as-is to
    corpus/media/<instagram|facebook>/<path in export> and listed in meta.files."""
    media_idx = {}
    for e in es:  # every attachment a message or post can point at (photos, videos, audio, and files: pdf, code, ...)
        low = f"{e.origin}/{e.path}".lower()
        if not e.path.lower().endswith((".json", ".html")) and ("instagram" in low or "facebook" in low):
            path = e.path
            while True:  # uris are relative to the export root; the entry may sit under extra folders
                media_idx.setdefault(path, e)
                if "/" not in path:
                    break
                path = path.split("/", 1)[1]

    def site_of(e):
        return "instagram" if "instagram" in f"{e.origin}/{e.path}".lower() else "facebook"

    def keep_media(e, uris, ts):
        out = []
        for u in uris:
            if u in media_idx:
                used.add(media_idx[u].path)
                out.append(save_media(media_idx[u], MEDIA / site_of(e) / u, ts))
        return [x for x in out if x]

    threads = [e for e in es if re.search(r"(^|/)messages/[^/]+/[^/]+/message_\d+\.json$", e.path)]
    parsed, seen_in = [], collections.Counter()
    for e in threads:
        used.add(e.path)
        d = e.json()
        senders = {fix_meta(m.get("sender_name") or m.get("senderName")) for m in d.get("messages") or []}
        seen_in.update(senders)
        parsed.append((e, d))
    owner = next((n for n in seen_in if is_me_name(n)), None) or (seen_in.most_common(1)[0][0] if len(parsed) > 2 else None)
    for e, d in parsed:
        source = "instagram" if site_of(e) == "instagram" else "messenger"
        thread = PurePosixPath(e.path).parent.name
        title = fix_meta(d.get("title")) or thread
        people = [fix_meta(x.get("name")) for x in d.get("participants") or [] if x.get("name")]
        w = W(source)
        for m in d.get("messages") or []:
            sender = fix_meta(m.get("sender_name") or m.get("senderName"))
            ts_ms = m.get("timestamp_ms") or m.get("timestamp")
            ts = from_unix(ts_ms, "ms")
            text = fix_meta(m.get("content") or m.get("text") or "")
            if m.get("share", {}).get("link"):
                text += f"\n[shared: {m['share']['link']}]"
            uris = []
            for kind_ in ("photos", "videos", "audio_files", "files", "gifs", "sticker"):
                items = m.get(kind_) or []
                items = [items] if isinstance(items, dict) else items
                if items:
                    text += f"\n[{kind_.rstrip('s')}]"
                    uris += [x.get("uri") for x in items if isinstance(x, dict) and x.get("uri")]
            key = rid(thread, ts_ms, sender, text[:50])
            if not text.strip() or w.has(key):
                continue
            me = sender == owner or is_me_name(sender)
            files = keep_media(e, uris, ts)
            w.add(id=key, kind="message", ts=ts, author="me" if me else sender, is_me=me, thread=thread,
                  thread_name=title, participants=people or None, text=text.strip(), meta={"files": files or None})

    for e in es:
        low = f"{e.origin}/{e.path}".lower()
        if e.path in used or not low.endswith(".json") or not ("instagram" in low or "facebook" in low):
            continue
        if re.search(META_SKIP, e.path.lower()) or re.search(META_SECURITY, e.path.lower()):
            continue
        kind = next((k for pat, k in META_FILES if re.search(pat, e.path.lower())), "record")
        used.add(e.path)
        try:
            d = e.json()
        except ValueError:
            continue
        if isinstance(d, dict) and "label_values" not in d and "uri" not in d:
            d = next((v for v in d.values() if isinstance(v, list) and v and isinstance(v[0], dict)), [d])
        site, label = site_of(e), PurePosixPath(e.path).stem
        w = W(f"{site}_activity")
        for it in d if isinstance(d, list) else [d]:
            pairs, uris, times = meta_item(it)
            if not pairs and not uris:
                continue
            t = next((x for x in times if x), None)
            ts = from_unix(t)
            text = f"{site.title()} {label.replace('_', ' ')}\n" + "\n".join(f"{k}: {v}" for k, v in pairs)
            key = rid(e.path, t, text[:500])
            if w.has(key):
                continue
            them = kind == "follow" and ("followers" in label or "received" in label)  # they follow / requested me
            head = next((v for lab in ("Caption", "Comment", "Search", "Interest", "Name", "Title", "Value")
                         for k, v in pairs if k == lab), None)
            w.add(id=key, kind=kind, ts=ts, author=(pairs[0][1] if them and pairs else "me"), is_me=not them,
                  title=(head or label.replace("_", " "))[:300], text=text[:20000],
                  url=next((v for _, v in pairs if v.startswith("http")), None),
                  meta={"file": label, "files": keep_media(e, uris, ts) or None})


def ytd(e):
    t = e.text()
    return json.loads(t[t.index("=") + 1:])


def x_archive(es, W, used):
    """X archive (data/*.js). Tweet and DM media (data/tweets_media/<tweet id>-*, data/direct_messages(_group)_media/
    <message id>-*) are copied to corpus/media/x/ and listed in meta.files."""
    acct = next((e for e in es if e.path.endswith("data/account.js")), None)
    me_id = ytd(acct)[0]["account"]["accountId"] if acct else None
    media = collections.defaultdict(list)
    for e in es:
        m = re.search(r"data/(tweets_media|direct_messages_media|direct_messages_group_media)/(\d+)-[^/]+$", e.path)
        if m:
            media[m.group(2)].append(e)

    def files_for(item_id, ts):
        out = []
        for e in media.get(str(item_id), []):
            used.add(e.path)
            out.append(save_media(e, MEDIA / "x" / PurePosixPath(e.path).name, ts))
        return [x for x in out if x] or None
    for e in es:
        p = e.path
        if re.search(r"data/(tweets?|tweets-part\d+)\.js$", p):
            used.add(p)
            w = W("x")
            for item in ytd(e):
                t = item.get("tweet", item)
                if w.has(t.get("id_str")):
                    continue
                ts = parse_time(t.get("created_at"), "%a %b %d %H:%M:%S %z %Y")
                w.add(id=t.get("id_str"), kind="post", ts=ts, author="me", is_me=True, text=t.get("full_text"),
                      url=f"https://x.com/i/status/{t.get('id_str')}",
                      meta={k: v for k, v in (("reply_to", t.get("in_reply_to_screen_name")),
                                              ("likes", t.get("favorite_count")), ("retweets", t.get("retweet_count")),
                                              ("files", files_for(t.get("id_str"), ts))) if v})
        elif re.search(r"data/direct-messages(-group)?\.js$", p):
            used.add(p)
            w = W("x")
            for conv in ytd(e):
                c = conv.get("dmConversation") or {}
                for m in c.get("messages") or []:
                    mc = m.get("messageCreate")
                    if not mc or w.has(mc.get("id")):
                        continue
                    me = me_id is not None and mc.get("senderId") == me_id
                    ts = parse_time(mc.get("createdAt"))
                    w.add(id=mc.get("id"), kind="message", ts=ts,
                          author="me" if me else mc.get("senderId"), is_me=me, thread=c.get("conversationId"),
                          thread_name=c.get("conversationId"), text=mc.get("text"),
                          meta={"files": files_for(mc.get("id"), ts)})
        elif p.endswith("data/like.js"):
            used.add(p)
            w = W("x")
            for item in ytd(e):
                l = item.get("like") or {}
                key = f"like:{l.get('tweetId')}"
                if l.get("fullText") and not w.has(key):
                    w.add(id=key, kind="reaction", author="me", is_me=True, text=l.get("fullText"), url=l.get("expandedUrl"),
                          meta={"reaction": "liked"})


# ---------------------------------------------------------------- CSV exports (LinkedIn, Reddit)

# Other LinkedIn files kept one record per row: file -> (kind, title columns, time column). Not kept: ads,
# logins and security challenges (IP addresses), phone/email lists, receipts, verifications, credibility scores.
LINKEDIN_FILES = {
    "profile.csv": ("profile", ("Headline",), None),
    "profile summary.csv": ("profile", ("Profile Summary",), None),
    "positions.csv": ("position", ("Title", "Company Name"), "Started On"),
    "education.csv": ("education", ("School Name", "Degree Name"), "Start Date"),
    "skills.csv": ("skill", ("Name",), None),
    "honors.csv": ("honor", ("Title",), "Issued On"),
    "courses.csv": ("course", ("Name",), None),
    "languages.csv": ("language", ("Name",), None),
    "job seeker preferences.csv": ("profile", ("Job Titles",), None),
    "learning.csv": ("course", ("Content Title",), "Content Last Watched Date (if viewed)"),
    "inferences_about_you.csv": ("inference", ("Inference",), None),
    "ad_targeting.csv": ("inference", (), None),
    "searchqueries.csv": ("search", ("Search Query",), "Time"),
    "invitations.csv": ("invitation", ("From", "To"), "Sent At"),
    "reactions.csv": ("reaction", ("Type",), "Date"),
    "instantreposts.csv": ("post", (), "Date"),
    "member_follows.csv": ("follow", ("FullName",), "Date"),
    "company follows.csv": ("follow", ("Organization",), "Followed On"),
    "endorsement_given_info.csv": ("endorsement", ("Skill Name",), "Endorsement Date"),
    "endorsement_received_info.csv": ("endorsement", ("Skill Name",), "Endorsement Date"),
    "votes.csv": ("vote", ("OptionText",), "Date"),
}
LINKEDIN_TIME = ("%b %Y", "%Y/%m/%d %H:%M:%S UTC", "%m/%d/%y, %I:%M %p", "%a %b %d %H:%M:%S UTC %Y", "%Y")


def linkedin_rows(e, n, w):
    """One record per row, keeping every non-empty column (csv.reader, since some files repeat column names)."""
    kind, title_cols, time_col = LINKEDIN_FILES[n]
    text = e.text().lstrip("﻿")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return
    head, label = rows[0], PurePosixPath(n).stem.replace("_", " ")
    for row in rows[1:]:
        pairs = [(k, v.strip()) for k, v in zip(head, row) if v and v.strip() and v.strip() != "N/A"]
        if not pairs:
            continue
        d = dict(pairs)
        if n == "invitations.csv" and d.get("Direction") == "INCOMING":
            author, me = d.get("From"), False
        elif n == "endorsement_received_info.csv":
            author, me = f"{d.get('Endorser First Name', '')} {d.get('Endorser Last Name', '')}".strip(), False
        else:
            author, me = "me", True
        key = rid("li", n, *(v for _, v in pairs))
        if w.has(key):
            continue
        w.add(id=key, kind=kind, ts=parse_time(d.get(time_col), *LINKEDIN_TIME) if time_col else None, author=author,
              is_me=me, title=" · ".join(d[c] for c in title_cols if d.get(c))[:300] or None,
              text=f"LinkedIn {label}\n" + "\n".join(f"{k}: {v}" for k, v in pairs),
              url=d.get("Link") or d.get("inviteeProfileUrl") or None, meta={"file": n})


def csv_exports(es, W, used):
    for e in es:
        if not e.name.lower().endswith(".csv"):
            continue
        try:
            rows = read_csv(e)
        except (csv.Error, UnicodeDecodeError):
            continue
        cols = set(rows[0].keys()) if rows else set()
        n = re.sub(r"_\d+(?=\.csv$)", "", e.name.lower())  # LinkedIn now appends a member id: Shares_<member id>.csv
        if {"CONVERSATION ID", "FROM", "CONTENT"} <= cols:
            used.add(e.path)
            w = W("linkedin")
            for r in rows:
                me = is_me_name(r.get("FROM"))
                key = rid(r.get("CONVERSATION ID"), r.get("DATE"), r.get("FROM"), (r.get("CONTENT") or "")[:40])
                if r.get("CONTENT") and not w.has(key):
                    w.add(id=key, kind="message", ts=parse_time(r.get("DATE")), author="me" if me else r.get("FROM"),
                          is_me=me, thread=r.get("CONVERSATION ID"), thread_name=r.get("CONVERSATION TITLE") or r.get("TO"),
                          title=r.get("SUBJECT") or None, text=html_to_text(r.get("CONTENT")))
        elif n == "connections.csv" and "First Name" in cols:
            used.add(e.path)
            w = W("linkedin")
            for r in rows:
                name = f"{r.get('First Name', '')} {r.get('Last Name', '')}".strip()
                key = rid("conn", name, r.get("URL"))
                if name and not w.has(key):
                    w.add(id=key, kind="contact", ts=parse_time(r.get("Connected On"), "%d %b %Y"), title=name,
                          text="\n".join(x for x in (name, r.get("Position"), r.get("Company"), r.get("Email Address")) if x),
                          url=r.get("URL"), meta={"source": "linkedin connection"})
        elif n == "shares.csv" and "ShareCommentary" in cols:
            used.add(e.path)
            for r in rows:
                key = rid("share", r.get("Date"), r.get("ShareLink"))
                if not W("linkedin").has(key):
                    W("linkedin").add(id=key, kind="post", ts=parse_time(r.get("Date")), author="me", is_me=True,
                                      text=r.get("ShareCommentary") or "[share]", url=r.get("SharedUrl") or r.get("ShareLink"))
        elif n == "comments.csv" and {"Message", "Link"} <= cols:
            used.add(e.path)
            for r in rows:
                key = rid("comment", r.get("Date"), r.get("Link"))
                if r.get("Message") and not W("linkedin").has(key):
                    W("linkedin").add(id=key, kind="post", ts=parse_time(r.get("Date")), author="me", is_me=True,
                                      text=r.get("Message"), url=r.get("Link"), meta={"type": "comment"})
        elif n in LINKEDIN_FILES and "linkedin" in f"{e.origin}/{e.path}".lower():  # generic names like skills.csv
            used.add(e.path)
            linkedin_rows(e, n, W("linkedin"))
        elif {"subreddit", "body"} <= cols or {"from", "to", "subject", "body"} <= cols:
            used.add(e.path)
            w = W("reddit")
            for r in rows:
                key = r.get("id") or rid(e.path, r.get("date"), r.get("body", "")[:40])
                if w.has(key):
                    continue
                if "from" in cols:
                    me = is_me_name(r.get("from"))
                    w.add(id=key, kind="message", ts=parse_time(r.get("date")), author="me" if me else r.get("from"), is_me=me,
                          thread=r.get("thread_id"), thread_name=r.get("subject"), title=r.get("subject"), text=r.get("body"))
                else:
                    w.add(id=key, kind="post", ts=parse_time(r.get("date")), author="me", is_me=True,
                          thread=r.get("subreddit"), thread_name=f"r/{r.get('subreddit')}", title=r.get("title") or None,
                          text="\n".join(x for x in (r.get("title"), r.get("body")) if x) or r.get("url"),
                          url=r.get("permalink"), meta={"type": "post" if "title" in cols else "comment"})


# ---------------------------------------------------------------- Media, transcripts, other chats

def spotify(es, W, used):
    for e in es:
        n = e.name
        if not (n.startswith(("Streaming_History", "StreamingHistory")) and n.endswith(".json")):
            continue
        used.add(e.path)
        w = W("spotify")
        for it in e.json():
            ms = it.get("ms_played", it.get("msPlayed", 0)) or 0
            track = it.get("master_metadata_track_name") or it.get("trackName") or it.get("episode_name") or it.get("episodeName")
            artist = it.get("master_metadata_album_artist_name") or it.get("artistName") or it.get("episode_show_name") or it.get("podcastName")
            ts = parse_time(it.get("ts")) or parse_time((it.get("endTime") or "") + "+00:00", "%Y-%m-%d %H:%M%z")
            key = rid(ts, track, ms)
            if ms < 10_000 or not track or w.has(key):
                continue
            album = it.get("master_metadata_album_album_name")
            w.add(id=key, kind="media", ts=ts, author="me", is_me=True, title=track,
                  text=" — ".join(x for x in (track, artist, album) if x) + " (Spotify)",
                  meta={k: v for k, v in (("artist", artist), ("album", album), ("seconds", round(ms / 1000)),
                                          ("skipped", it.get("skipped")), ("platform", it.get("platform"))) if v})


WA = [re.compile(r"^‎?\[(\d{1,4}[./-]\d{1,2}[./-]\d{1,4}),?\s+(\d{1,2}[:.]\d{2}(?:[:.]\d{2})?(?:\s?[AaPp]\.?\s?[Mm]\.?)?)\]\s([^:]{1,80}):\s(.*)$"),
      re.compile(r"^(\d{1,4}[./-]\d{1,2}[./-]\d{1,4}),?\s+(\d{1,2}[:.]\d{2}(?:\s?[AaPp]\.?\s?[Mm]\.?)?)\s[-–]\s([^:]{1,80}):\s(.*)$")]


def wa_match(line):
    line = line.replace(" ", " ").replace("‎", "")
    return next((m for m in (rx.match(line) for rx in WA) if m), None)


def wa_time(d, t, dayfirst):
    parts = re.split(r"[./-]", d)
    if len(parts[0]) == 4:
        y, m, dd = parts
    elif dayfirst:
        dd, m, y = parts
    else:
        m, dd, y = parts
    y = int(y) + (2000 if int(y) < 100 else 0)
    t = t.replace(".", ":").upper().replace("A:M:", "AM").replace("P:M:", "PM").replace("A:M", "AM").replace("P:M", "PM")
    for fmt in ("%I:%M:%S %p", "%I:%M %p", "%I:%M:%S%p", "%I:%M%p", "%H:%M:%S", "%H:%M"):
        try:
            tm = datetime.strptime(t.strip(), fmt).time()
            return datetime(y, int(m), int(dd), tm.hour, tm.minute, tm.second).isoformat()
        except ValueError:
            continue
    return None


def whatsapp(es, W, used):
    for e in es:
        if not e.name.lower().endswith(".txt") or e.path in used or e.size > 200 * 2**20:
            continue
        lines = e.text().splitlines()
        if sum(1 for l in lines[:40] if wa_match(l)) < 3:
            continue
        used.add(e.path)
        m = re.search(r"WhatsApp Chat (?:with |- )([^/]+?)(?:\.txt)?(?:/|$)", e.origin + "/" + e.path)
        thread = m.group(1) if m else (PurePosixPath(e.path).parent.name or e.name)
        msgs = []
        for l in lines:
            h = wa_match(l)
            if h:
                msgs.append([h.group(1), h.group(2), h.group(3).strip(), h.group(4)])
            elif msgs:
                msgs[-1][3] += "\n" + l
        firsts = [int(re.split(r"[./-]", d)[0]) for d, *_ in msgs if len(re.split(r"[./-]", d)[0]) <= 2]
        dayfirst = any(x > 12 for x in firsts)
        people = sorted({s for _, _, s, _ in msgs})
        w = W("whatsapp_export")
        for i, (d, t, sender, body) in enumerate(msgs):
            me = is_me_name(sender)
            w.add(id=f"{thread}:{i}", kind="message", ts=wa_time(d, t, dayfirst), author="me" if me else sender, is_me=me,
                  thread=thread, thread_name=thread, participants=people, text=body.replace("‎", "").strip())


def slack(es, W, used):
    users_e = next((e for e in es if e.name == "users.json"), None)
    days = [e for e in es if re.search(r"(^|/)[^/]+/\d{4}-\d{2}-\d{2}\.json$", e.path)]
    if not users_e or not days:
        return
    used.add(users_e.path)
    users = {u.get("id"): u.get("real_name") or (u.get("profile") or {}).get("real_name") or u.get("name") for u in users_e.json()}
    w = W("slack")
    for e in days:
        used.add(e.path)
        channel = PurePosixPath(e.path).parent.name
        for m in e.json():
            if m.get("type") != "message" or m.get("subtype") in ("channel_join", "channel_leave", "bot_message"):
                continue
            name = users.get(m.get("user")) or (m.get("user_profile") or {}).get("real_name") or m.get("user")
            key = f"{channel}:{m.get('ts')}"
            if w.has(key):
                continue
            text = re.sub(r"<@(\w+)>", lambda x: "@" + (users.get(x.group(1)) or x.group(1)), m.get("text") or "")
            me = is_me_name(name)
            w.add(id=key, kind="message", ts=from_unix(float(m.get("ts") or 0)), author="me" if me else name, is_me=me,
                  thread=channel, thread_name="#" + channel, text=text, meta={"thread_ts": m.get("thread_ts")})


def chat_time(s):
    try:  # "Wednesday, June 8, 2016 at 3:55:41 AM UTC", with a narrow no-break space before AM/PM
        return iso(datetime.strptime(s.replace(" ", " "), "%A, %B %d, %Y at %I:%M:%S %p UTC").replace(tzinfo=timezone.utc))
    except (ValueError, AttributeError):
        return parse_time(s)


def save_media(e, dest, ts):
    """Copy an export's attachment out to corpus/media/ as a plain file (once), dated like its message. Returns
    its path, or None when the name would land outside corpus/media/ (a crafted export's ../ or absolute uri)."""
    if not dest.resolve().is_relative_to(MEDIA.resolve()):
        print(f"[imports] skipped a file whose name points outside corpus/media: {str(dest)[-80:]}")
        return None
    if not (dest.exists() and dest.stat().st_size == e.size):
        dest.parent.mkdir(parents=True, exist_ok=True)
        with e.open() as src, open(dest, "wb") as out:
            shutil.copyfileobj(src, out)
    if ts:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        os.utime(dest, (t, t))
    return str(dest.relative_to(CORPUS.parent))


def google_chat(es, W, used):
    """Google Chat / Hangouts: Groups/<DM|Space id>/group_info.json lists members, messages.json the messages.
    Attachments (photos, videos) are copied as-is to corpus/media/google_chat/<people> [<id>]/ and each
    message lists its files in meta.files."""
    members, files = {}, collections.defaultdict(dict)
    for e in es:
        m = re.search(r"Google Chat/Groups/([^/]+)/([^/]+)$", e.path)
        if not m:
            continue
        if m.group(2) == "group_info.json":
            used.add(e.path)
            info = e.json()
            members[m.group(1)] = (info.get("name"), [p.get("name") or p.get("email") for p in info.get("members") or []])
        elif not m.group(2).endswith(".json"):
            used.add(e.path)
            files[m.group(1)][m.group(2)] = e
    for e in es:
        m = re.search(r"Google Chat/Groups/([^/]+)/messages\.json$", e.path)
        if not m:
            continue
        used.add(e.path)
        group = m.group(1)
        space_name, people = members.get(group, (None, []))
        others = [p for p in people if p and not is_me_name(p)]
        thread_name = space_name or ", ".join(others) or group
        folder = MEDIA / "google_chat" / re.sub(r"[/:\\]", "-", f"{thread_name[:80]} [{group}]")
        w = W("google_chat")
        repeats = collections.Counter()
        for msg in e.json().get("messages") or []:
            who = msg.get("creator") or {}
            ts = chat_time(msg.get("created_date"))
            names = [f.get("export_name") or f.get("original_name") for f in msg.get("attached_files") or []]
            paths = []
            for n in filter(None, names):
                # On disk Takeout writes "?" as "_" and numbers repeated names X.jpg, X(1).jpg, X(2).jpg in
                # message order, while every message still says X.jpg.
                fn, k = n.replace("?", "_"), repeats[n]
                repeats[n] += 1
                if k:
                    stem, dot, ext = fn.rpartition(".")
                    fn = f"{stem}({k}).{ext}" if dot else f"{fn}({k})"
                if fn in files[group] and (saved := save_media(files[group][fn], folder / fn, ts)):
                    paths.append(saved)
            key = msg.get("message_id") or rid(group, msg.get("created_date"), msg.get("text"))
            if w.has(key):
                continue
            w.add(id=key, kind="message", ts=ts, author=who.get("name") or who.get("email"),
                  is_me=is_me_email(who.get("email")) or is_me_name(who.get("name")), thread=group,
                  thread_name=thread_name, participants=people or None,
                  text="\n".join(x for x in (msg.get("text"), *(f"[attachment: {n}]" for n in names if n)) if x),
                  meta={"group": len(people) > 2 or group.startswith("Space"), "attachments": len(names) or None,
                        "files": paths or None})


def zoom(es, W, used):
    for e in es:
        if not e.name.lower().endswith(".vtt"):
            continue
        used.add(e.path)
        cues = []
        for block in re.split(r"\n\s*\n", e.text()):
            lines = [l for l in block.strip().splitlines() if l and "-->" not in l and not l.strip().isdigit() and l.strip() != "WEBVTT"]
            if lines:
                cues.append(" ".join(lines))
        folder = PurePosixPath(e.path).parent.name
        m = re.match(r"(\d{4}-\d{2}-\d{2}) (\d{2})\.(\d{2})\.(\d{2}) (.*)", folder)
        W("zoom").add(id=e.path, kind="document", ts=f"{m.group(1)}T{m.group(2)}:{m.group(3)}:{m.group(4)}" if m else None,
                      title=m.group(5) if m else (folder or e.name), text="\n".join(cues),
                      thread="zoom", thread_name="Zoom transcripts", meta={"file": e.path})


NOTION_EXPORT = re.compile(r"Export-[0-9a-f]{8}-[0-9a-f-]{27}")
NOTION_ID = re.compile(r" ([0-9a-f]{32})(?:_all)?\.(md|csv)$")


def notion_export(es, W, used):
    """Notion "Export all workspace content" (Markdown & CSV, folders for subpages). One record per page, one
    per database table (CSV). Reads only the export: page files carry no dates (every zip entry is stamped with
    the export time), so ts comes from a "Created time" property (database rows), else the nearest parent page
    that has one, else stays empty; meta.ts_from says which. Attachments are copied to corpus/media/notion/ and
    listed in meta.files; PDFs and docs are also read by other_documents."""
    mine = [e for e in es if NOTION_EXPORT.search(f"{e.origin}/{e.path}")]
    if not mine:
        return
    by_path = {e.path: e for e in mine}
    rel = lambda path: path.split("/", 1)[1] if NOTION_EXPORT.match(path) else path  # drop the Export-<id>/ root
    crumbs = lambda path: " › ".join(NOTION_ID.sub("", re.sub(r" [0-9a-f]{32}$", "", c)) for c in rel(path).split("/")[:-1])
    pages = {}  # path without " <id>.md" -> (page id, ts) so subpages can inherit a date
    for e in sorted((e for e in mine if e.path.endswith(".md")), key=lambda e: e.path.count("/")):
        used.add(e.path)
        text = e.text()
        m = NOTION_ID.search(e.path)
        pid = m.group(1) if m else rid(e.path)
        title = next((l[2:].strip() for l in text.splitlines()[:3] if l.startswith("# ")), None) or NOTION_ID.sub("", PurePosixPath(e.path).name)
        prop = lambda name: (re.search(rf"^{name}: (.+)$", text[:2000], re.M) or [None, None])[1]
        when = lambda v: parse_time(v.strip(), "%B %d, %Y %I:%M %p", "%B %d, %Y") if v else None
        ts, modified = when(prop("Created(?: time)?")), when(prop("Last edited time"))
        ts_from = "created property" if ts else None
        if not ts:
            parent = pages.get(PurePosixPath(e.path).parent.as_posix())
            ts, ts_from = (parent[1], "parent page") if parent and parent[1] else (None, None)
        pages[NOTION_ID.sub("", e.path)] = (pid, ts)
        files = []
        for target in re.findall(r"\]\(([^)]+)\)", text):
            target = unquote(target.split(" ")[0])
            if target.startswith(("http", "#")) or target.endswith((".md", ".csv")):
                continue
            path = posixpath.normpath(posixpath.join(PurePosixPath(e.path).parent.as_posix(), target))
            if path in by_path and (saved := save_media(by_path[path], MEDIA / "notion" / rel(path), ts)):
                files.append(saved)
        body = re.sub(r"\[([^\]]*)\]\([^)]+\.(?:md|csv)\)", r"[\1]", text)  # links to other pages -> their titles
        W("notion_export").add(id=pid, kind="note", ts=ts, author="me", is_me=True, thread=rel(e.path).split("/")[0],
                               thread_name=crumbs(e.path) or None, title=title[:300], text=body[:200_000],
                               meta={"path": rel(e.path), "ts_from": ts_from, "modified": modified, "files": files or None})
    tables = {}
    for e in mine:
        m = NOTION_ID.search(e.path)
        if e.path.endswith(".csv") and m and (m.group(1) not in tables or e.path.endswith("_all.csv")):
            tables[m.group(1)] = e  # Notion writes the current view and _all; keep _all
    for pid, e in tables.items():
        used.update(x.path for x in mine if x.path.endswith(".csv") and pid in x.path)
        W("notion_export").add(id=f"{pid}:table", kind="database", author="me", is_me=True, thread=rel(e.path).split("/")[0],
                               thread_name=crumbs(e.path) or None, title=NOTION_ID.sub("", PurePosixPath(e.path).name),
                               text=e.text().lstrip("\ufeff")[:200_000], meta={"path": rel(e.path)})


def other_documents(es, W, used):
    from documents import iwork_text, pdf_text, pptx_text
    for e in es:
        ext = PurePosixPath(e.name).suffix.lower()
        if e.path in used or ext not in DOC_EXT or e.size > 60 * 2**20 or e.size == 0 or e.name == "archive_browser.html" or "Takeout/Keep/" in e.path:  # Keep has JSON twins
            continue
        data = e.read()
        try:
            if ext == ".pdf":
                with tempfile.NamedTemporaryFile(suffix=".pdf") as t:
                    t.write(data)
                    t.flush()
                    text = pdf_text(Path(t.name))
            elif ext in (".docx", ".doc", ".rtf", ".odt"):
                with tempfile.NamedTemporaryFile(suffix=ext) as t:
                    t.write(data)
                    t.flush()
                    text = subprocess.run(["textutil", "-convert", "txt", "-stdout", t.name], capture_output=True,
                                          text=True, timeout=60).stdout
            elif ext == ".pptx":
                text = pptx_text(io.BytesIO(data))
            elif ext in (".pages", ".key"):
                text = iwork_text(io.BytesIO(data))
            elif ext in (".html", ".htm"):
                text = html_to_text(data.decode("utf-8", "replace"))
            elif ext == ".ipynb":
                text = "\n\n".join("".join(c.get("source", [])) for c in json.loads(data).get("cells", []))
            else:
                text = data.decode("utf-8", "replace")
        except Exception:
            text = ""
        title = re.sub(r"\s[0-9a-f]{32}$", "", PurePosixPath(e.name).stem)  # Notion appends page ids
        W("imported_documents").add(id=f"{e.origin}:{e.path}", kind="document", author="me", title=title,
                                    text=re.sub(r"[ \t]+", " ", text).strip()[:200_000] or title,
                                    thread=e.origin, thread_name=str(PurePosixPath(e.path).parent),
                                    meta={"origin": e.origin, "path": e.path, "ext": ext})


# Leftovers nobody else read. Left out only: security files, viewer/app assets, mail indexes, other people's server art.
LEFTOVER_SECURITY = (r"login|logout|session|password|token|cookie|webhook|payment_source|reward_code|ip_address|"
                     r"ip.?audit|creation.?ip|registration|key.?registry|(^|/)sso\.|connected.?application|"
                     r"billing.?profile|security|device|authoriz|two_factor|recovery|credential|api_key")
LEFTOVER_OTHERS = META_SKIP + r"|(^|/)emoji(/|\.json$)"  # suggested people, other servers' custom emoji
LEFTOVER_NO_INFO = (r"(^|/)assets/|archive_browser|table_of_contents|(^|/)manifest\.js$|(^|/)emoji/|(^|/)icon\.[a-z]+$|"
                    r"avatar\.[a-z]+$|Takeout/Keep/.*\.html$")
# Fields inside a leftover record that are about the device or login, not the person: ad ids, IPs (TikTok's
# user_data_tiktok.json keeps them next to the watch history).
LEFTOVER_IDS = r"idfa|idfv|gaid|android.?id|advertis\w*.?id|(^|[._ ])ip($|[._ ])"
LEFTOVER_FIELDS = LEFTOVER_SECURITY + "|" + LEFTOVER_IDS
FILE_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".mp4", ".mov", ".m4a", ".aac", ".mp3", ".wav", ".svg")


def leftover_source(e):
    top = PurePosixPath(e.origin).parts[0] if e.origin else "imports"
    return re.sub(r"\W+", "_", "takeout" if top.lower().startswith("takeout") else top.lower())


def flat(x, prefix="", out=None):
    """Nested JSON -> [(dotted key, value)] for readable text."""
    out = [] if out is None else out
    if isinstance(x, dict):
        for k, v in x.items():
            flat(v, f"{prefix}{k}.", out)
    elif isinstance(x, list):
        for v in x[:50]:
            flat(v, prefix, out)
    elif x not in (None, ""):
        out.append((prefix[:-1], str(x)))
    return out


def leftover_time(v):
    """A date in a leftover field: ISO-like text or Unix seconds/milliseconds, else None."""
    v = str(v).strip()
    if re.fullmatch(r"\d{10}(\.\d+)?", v):
        return from_unix(float(v))
    if re.fullmatch(r"\d{13}", v):
        return from_unix(int(v), "ms")
    m = re.match(r"(\d{4}-\d{2}-\d{2})([T ]\d{2}:\d{2}(:\d{2})?)?", v)
    if m and 1990 <= int(v[:4]) <= 2100:
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00").replace(" UTC", "+00:00")).astimezone(timezone.utc).isoformat().replace("+00:00", "Z") \
                if m.group(2) else m.group(1) + "T00:00:00"
        except ValueError:
            return m.group(1) + "T00:00:00"
    return None


def item_lists(x, path=()):
    """Every list of objects in a nested export, with the keys leading to it. TikTok's one file keeps its watch
    history at Your Activity > Watch History > VideoList."""
    if isinstance(x, list) and x and all(isinstance(i, dict) for i in x[:20]):
        yield path, x
    elif isinstance(x, dict):
        for k, v in x.items():
            yield from item_lists(v, path + (str(k),))


def other_data(es, W, used):
    """Structured files (.json, .csv, X's .js) no parser above read: one record per item (or per file), source
    <export>_other, so nothing in an export is skipped silently. Security files and assets stay out."""
    LEFTOVER_WRITTEN.clear()
    for e in es:
        ext = PurePosixPath(e.name).suffix.lower()
        if e.path in used or ext not in (".json", ".csv", ".js") or not e.size or e.size > 50 * 2**20:
            continue
        if re.search(LEFTOVER_SECURITY, e.path, re.I) or re.search(LEFTOVER_NO_INFO, e.path) or \
                re.search(LEFTOVER_OTHERS, e.path, re.I):
            continue
        try:
            if ext == ".csv":
                items = list(csv.DictReader(io.StringIO(e.text())))
            elif ext == ".js":
                items = ytd(e)
            else:
                items = e.json()
        except Exception:
            continue
        # One record per item of each list in the file, wherever it sits, and one for whatever else the file says.
        # Lists of logins or device ids stay out like the files named so. Groups are (title, id prefix, items as
        # lists of (key, value) pairs); a plain list keeps the ids it always had (path#n), and so does a file
        # whose only list sits at the top or that has none (one record, path#0).
        stem = PurePosixPath(e.path).stem
        if isinstance(items, list):
            groups = [(stem.replace("_", " "), "", [flat(it) for it in items])]
        elif isinstance(items, dict):
            lists = list(item_lists(items))
            # Discord's newer files describe their own columns (metadata > columns): that's no one's data. Lists a
            # mapping already read are its records, not these.
            keep = [(p, l) for p, l in lists if ".".join(p) not in MAPPED.get(e.path, ())
                    and not re.search(LEFTOVER_SECURITY, "/".join(p), re.I)
                    and not re.search(r"(^|/)(columns|schema)$", "/".join(p), re.I)
                    and not any(re.search(LEFTOVER_IDS, str(k), re.I) for k in l[0])]
            plain = len(lists) == 1 and len(lists[0][0]) == 1
            groups = [(" / ".join(p[-2:]), "" if plain else "/".join(p) + "#", [flat(it) for it in l]) for p, l in keep]
            taken = tuple(".".join(p) + "." for p, _ in lists)
            rest = [(k, v) for k, v in flat(items) if not (k + ".").startswith(taken)]
            if rest:
                groups.append((stem.replace("_", " "), "rest#" if lists else "", [rest]))
        else:
            groups = [(stem.replace("_", " "), "", [flat(items)])]
        if not groups:  # a mapping read all of it
            used.add(e.path)
            continue
        source = f"{leftover_source(e)}_other"
        LEFTOVER_WRITTEN.add(source)
        AV.setdefault(source, f"Files in the {leftover_source(e)} export that no specific parser reads, one record per item. {DROP}")
        used.add(e.path)
        w = W(source)
        for title, prefix, group in groups:
            for n, pairs in enumerate(group):
                pairs = [(k, v) for k, v in pairs if not re.search(LEFTOVER_FIELDS, k.rsplit(".", 1)[-1], re.I)]
                if not pairs:
                    continue
                ts = next((t for k, v in pairs if re.search(r"(date|time|created|timestamp)", k, re.I)
                           for t in [leftover_time(v)] if t), None)
                key = f"{e.path}#{prefix}{n}"
                if w.has(key):
                    continue
                w.add(id=key, kind="record", ts=ts, author="me", title=title,
                      text=f"{title}: " + "; ".join(f"{k}: {v}" for k, v in pairs)[:20000], meta={"file": e.path})


def other_files(es, W, used):
    """Media files no parser linked (attachments of Takeout activity, Notion pages, X ...): copied to
    corpus/media/<export>/ and one record each, source <export>_files."""
    for e in es:
        if e.path in used or not e.path.lower().endswith(FILE_EXT) or not e.size or re.search(LEFTOVER_NO_INFO, e.path):
            continue
        source = f"{leftover_source(e)}_files"
        LEFTOVER_WRITTEN.add(source)
        AV.setdefault(source, f"Media files in the {leftover_source(e)} export that no specific parser links. {DROP}")
        used.add(e.path)
        m = re.search(r"(20\d\d)[-_](\d\d)[-_](\d\d)", e.name)
        ts = f"{m.group(1)}-{m.group(2)}-{m.group(3)}T00:00:00" if m else None
        path = save_media(e, MEDIA / leftover_source(e) / e.path, ts)
        if not path:
            continue
        W(source).add(id=e.path, kind="file", ts=ts, author="me", title=e.name, text=f"File {e.path}",
                      meta={"files": [path]})


PARSERS = [ai_exports, google, google_chat, discord, meta, x_archive, csv_exports, spotify, whatsapp, slack, zoom,
           notion_export, mapped_exports, other_documents, other_data, other_files]


def main():
    es = entries()
    if not es:
        print(f"[imports] nothing in {IMPORTS}")
        return
    used = set()
    with ExitStack() as stack:
        writers = {}

        def W(source):
            if source not in writers:
                parser = f"connectors/imports.py:{sys._getframe(1).f_code.co_name}"  # the parser asking for it
                # An export is a complete snapshot, so nothing carries over from earlier runs.
                avenue = AV.get(source, f"Mailbox export (.mbox) dropped into corpus/imports/{source}/. {DROP}")
                writers[source] = stack.enter_context(Writer(source, avenue, parser=parser, accumulate=False))
            return writers[source]

        for parser in PARSERS:
            parser(es, W, used)
    unclaimed_ledger(es, used)


LEFTOVER_WRITTEN = set()  # catch-all sources written by this run


def unclaimed_ledger(es, used):
    """Every export file no parser read, recorded in the manifest (_imports_unclaimed) so nothing is skipped
    silently: grouped by export and folder, with file counts and bytes. Also removes catch-all sources an
    earlier run wrote and this one didn't (their files are now excluded or read by a real parser)."""
    groups = {}
    for e in es:
        if e.path in used:
            continue
        top = PurePosixPath(e.origin).parts[0] if e.origin else ""
        folder = "/".join(PurePosixPath(e.path).parts[:-1][:4])
        g = groups.setdefault(f"{top} :: {folder}", {"files": 0, "bytes": 0, "examples": []})
        g["files"] += 1
        g["bytes"] += e.size or 0
        if len(g["examples"]) < 3:
            g["examples"].append(PurePosixPath(e.path).name)
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    for source, m in list(manifest.items()):
        if isinstance(m, dict) and str(m.get("parser", "")).endswith((":other_data", ":other_files")) \
                and source not in LEFTOVER_WRITTEN:
            (CORPUS / "normalized" / f"{source}.jsonl").unlink(missing_ok=True)
            del manifest[source]
            print(f"[imports] removed {source}: no longer produced")
    manifest["_imports_unclaimed"] = [{"group": k, **g} for k, g in sorted(groups.items(), key=lambda kv: -kv[1]["bytes"])]
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    print(f"[imports] {sum(g['files'] for g in groups.values()):,} export files no parser read "
          f"({sum(g['bytes'] for g in groups.values()) / 1e6:,.0f} MB), listed in manifest.json _imports_unclaimed")


if __name__ == "__main__":
    main()
