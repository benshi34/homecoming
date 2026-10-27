"""Account data exports dropped into corpus/imports/ (zip files, nested zips, or unzipped folders).
Formats are auto-detected from file names / columns, so exports can be dropped in as downloaded.

    ChatGPT ......... conversations.json with "mapping"            -> chatgpt
    Claude.ai ....... conversations.json with "chat_messages", projects.json or projects/*.json, memories.json -> claude_ai
    Google Takeout .. Mail/*.mbox -> gmail; My Activity/*/MyActivity.json or .html, YouTube watch/search history
                      -> google_activity; YouTube comments, uploads, subscriptions, playlists -> youtube;
                      Calendar/*.ics -> google_calendar; Contacts/*.vcf -> google_contacts;
                      Chrome/History.json, Bookmarks.html, Reading List.html -> chrome_synced; Keep/*.json (or the
                      .html of an old one) -> google_keep; Tasks/Tasks.json -> google_tasks; Saved/*.csv (Maps lists,
                      saved links) -> google_saved; Google Chat/Groups/*/messages.json -> google_chat; Google Photos/*.json
                      sidecars -> google_photos; Maps saved places / reviews -> google_maps_places;
                      Timeline.json or Semantic Location History -> location_history (visits and trips).
                      Takeout names folders and files in the account's language: a file named some other way is
                      told by what's in it (sniffed)
    Discord ......... Messages/index.json + Messages/c*/messages.json|csv (messages/<id>/ before late 2021) -> discord
    Meta ............ messages/*/*/message_N.json -> instagram | messenger; posts / comments -> *_activity
    X ............... data/tweets.js, note-tweet.js, deleted-tweets.js, community-tweet.js, direct-messages*.js, like.js,
                      follower.js, following.js, grok-chat-item.js; before 2018 data/js/tweets/YYYY_MM.js -> x
    LinkedIn ........ messages.csv, Connections.csv, Shares.csv, Comments.csv -> linkedin
    Reddit .......... comments.csv, posts.csv, messages.csv, chat_history.csv, votes, saved, subscriptions -> reddit
    Spotify ......... Streaming_History_*.json (endsong_*.json) / StreamingHistory*.json, Playlist*.json, YourLibrary.json,
                      SearchQueries.json, Inferences.json, Marquee.json -> spotify
    WhatsApp ........ exported chat .txt (iPhone or Android, any language), with its media -> whatsapp_export
    Slack ........... users.json / org_users.json, channels.json, groups.json, dms.json, mpims.json +
                      <conversation>/<YYYY-MM-DD>.json; one member's export as channels/*.txt, dms/*.txt -> slack
    Mail ............ outside Takeout, .mbox (Mail.app's <Folder>.mbox/mbox; Thunderbird's without an extension), .eml,
                      .emlx, Outlook for Mac's .olm -> the folder's name under corpus/imports/ (e.g. hotmail)
    Zoom ............ *.vtt transcripts -> zoom
    anything else ... pdf/docx/pptx/pages/md/txt/html/ipynb -> imported_documents (e.g. Drive, Notion export)
"""

import bisect
import collections
import csv
import ctypes
import hashlib
import html
import io
import json
import math
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import unicodedata
import zipfile
import zlib
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import common
import identity
from browser_history import classify
from common import (CORPUS, Writer, from_unix, junk_member, looks_like_bomb, member_name, open_nested, read_json, read_manifest,
                    write_atomic, write_manifest, zip_problem)
from contacts import parse_vcards, vcard_name, vcard_text
from mapped_exports import MAPPED, SOURCES as MAPPED_SOURCES, folder_key, load as load_mappings, mapped_exports
from email_parse import (FIRST_HEADER, SENT_FOLDERS, SEPARATOR as MBOX_SEPARATOR, SKIP_FOLDERS, SPAM_LABELS, TIER_OF_FOLDER,
                         TRASH_LABELS, gmail_labels, html_to_text, iter_mbox, olm_message, parse as parse_email)
from identity import ME, is_me_email, is_me_name

IMPORTS = CORPUS / "imports"
MEDIA = CORPUS / "media"  # attachments copied out of exports, as plain files
DROP = "Drop the downloaded export (zip or folder) into corpus/imports/."
AV = {
    "chatgpt": f"ChatGPT > Settings > Data controls > Export data (emailed link, ~minutes-hours). {DROP}",
    "claude_ai": f"claude.ai > Settings > Privacy > Export data (emailed link): conversations and projects. {DROP}",
    "gmail": f"Google Takeout (takeout.google.com) > Mail (mbox). {DROP}",
    "hotmail": f"Outlook.com: add the account in System Settings > Internet Accounts > Microsoft Exchange, let Mail.app download it, then Mailbox > Export Mailbox into corpus/imports/hotmail/ (outlook.live.com has no web export). {DROP}",
    "google_activity": f"Google Takeout > My Activity + YouTube and YouTube Music (history), as JSON (times to the millisecond, in UTC) or the default HTML. {DROP}",
    "google_calendar": f"Google Takeout > Calendar (.ics). {DROP}",
    "google_contacts": f"Google Takeout > Contacts (vCard). {DROP}",
    "vcard_contacts": f"Any other vCard export, e.g. iPhone Contacts > Lists > All Contacts > Export (AirDrop the .vcf to the Mac). {DROP}",
    "chrome_synced": f"Google Takeout > Chrome (History.json, synced history beyond Chrome's local 90 days; Bookmarks.html and Reading List.html). {DROP}",
    "youtube": f"Google Takeout > YouTube and YouTube Music (your comments, uploads, subscriptions and playlists). {DROP}",
    "google_tasks": f"Google Takeout > Tasks. {DROP}",
    "google_saved": f"Google Takeout > Saved (your Maps lists: Want to go, Favorites, your own lists; and saved links). {DROP}",
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
    "spotify": f"Spotify account > Privacy settings > Download your data: Account data (playlists, library, searches, ~5 days) and Extended streaming history (every play, ~days-30 days), which arrive separately. {DROP}",
    "whatsapp_export": f"WhatsApp on phone > chat > Export chat (without media), per chat. History retained on the phone comes from connectors/iphone.py via iLEAPP (phone_whatsapp). {DROP}",
    "slack": f"Slack workspace export (admin) or slackdump. {DROP}",
    "telegram": f"Telegram Desktop > Settings > Advanced > Export Telegram data, Format: Machine-readable JSON (every chat, or one chat's > Export chat history). {DROP}",
    "zoom": f"Zoom web > Recordings > Cloud recordings > download transcript (.vtt). {DROP}",
    "notion_export": f"Notion > Settings > General > Export all workspace content (Markdown & CSV, include subpages). {DROP}",
    "imported_documents": f"Any other files (Google Drive via Takeout, Notion 'Export all workspace content'). {DROP}",
}
EXPORT_SOURCES = frozenset(AV)  # the exports' sources (the catch-alls and mappings add theirs to AV as they run)
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
STAMP = ".unpacked.json"  # which tar, at what size and time, a folder in raw/unpacked/ holds
NESTED = 3  # zips in zips are opened this deep: Notion's parts are one down, a zip of downloaded zips two
# A download a browser is still writing: Chrome's .crdownload, Safari's .download (a folder), Firefox's .part (downloads.ts's PARTIAL).
PARTIAL = re.compile(r"\.(crdownload|download|part|partial|opdownload)$|\.partial\.mbox$|^Unconfirmed \d+", re.I)
# What entries() doesn't hand to the parsers, and why (locked, a zip bomb, still downloading): said, and listed in the ledger.
LEFT_OUT = []


def unpacked_dir():
    """Where tar exports are unpacked, once each, in the library (raw/, which nothing reads as an export)."""
    return IMPORTS.parent / "raw" / "unpacked"


def entries():
    out = []
    LEFT_OUT.clear()
    if not IMPORTS.exists():
        return out
    tars = set()

    def add_zip(z, origin, prefix="", depth=0, room=None):
        # room: what the zips inside this download may unpack to, all told. One's zips are about its size (zipped data doesn't
        # zip smaller); many times more is a zip bomb's.
        room = room if room is not None else [4 * (IMPORTS / origin).stat().st_size + (256 << 20)]
        for info in z.infolist():
            name = member_name(info)
            if name.endswith("/") or junk_member(name) or not safe_member(name):
                continue
            if z.getinfo(info.filename) is not info:  # the same name twice: the last one, as unzipping leaves it
                continue
            why = zip_problem(info) or (looks_like_bomb(info) and f"unpacks to {info.file_size / 1e9:,.0f} GB from "
                                        f"{info.compress_size / 1e6:,.1f} MB, which only a zip bomb does")
            if why:
                left_out(origin, prefix + name, info.file_size, why)
                continue
            if name.lower().endswith(".zip"):
                room[0] -= info.file_size
                if depth >= NESTED or room[0] < 0:
                    left_out(origin, prefix + name, info.file_size, f"a zip inside zips more than {NESTED} deep" if depth >= NESTED
                             else "its zips unpack to many times its size, which only a zip bomb does")
                    continue
                try:
                    add_zip(open_nested(z, info, spill=IMPORTS.parent / "raw"), origin, prefix + name + "/", depth + 1, room)
                except Exception as x:  # noqa: BLE001 - a zip in it that's damaged (BadZipFile, zlib.error, a bad CRC), or no room
                    cut_short(f"{origin}: {prefix}{name}", x)
                continue
            out.append(Entry(prefix + name, lambda z=z, i=info: z.open(i), info.file_size, origin))

    def add_tar(p, origin):
        """GitHub's export is a .tar.gz. A compressed tar can't be read file by file without starting over each time, so
        it's unpacked, with tarfile's "data" filter (no links, devices or names outside the folder), into
        raw/unpacked/<its id>/, and read from there while it's unchanged: once, not on every import. Not one that
        unpacks to over BOMB_RATIO times its size (a tar bomb's), or to more than the disk has free."""
        st = p.stat()
        root = unpacked_dir() / rid(origin)
        tars.add(root.name)
        stamp, want = root / STAMP, {"from": origin, "bytes": st.st_size, "mtime_ns": st.st_mtime_ns}
        if read_json(stamp) != want:
            part = root.with_name(f"{root.name}.part-{os.getpid()}")  # its own: another run may be unpacking it too
            shutil.rmtree(part, ignore_errors=True)
            try:
                with tarfile.open(p) as t:
                    members, end = [], max(common.BOMB_RATIO * st.st_size, 1 << 30)
                    for m in t:  # each header says how far in its file ends, before that file is unpacked to get past it
                        if m.offset_data + m.size > end:
                            left_out(origin, "", st.st_size, f"unpacks to over {common.BOMB_RATIO} times its size, which only a tar bomb does")
                            return
                        if m.isfile() and safe_member(m.name) and not junk_member(m.name):
                            members.append(m)
                    unpacked_dir().mkdir(parents=True, exist_ok=True)
                    need = sum(m.size for m in members)
                    if shutil.disk_usage(unpacked_dir()).free < need + (1 << 30):
                        left_out(origin, "", st.st_size, f"needs {need / 1e9:,.1f} GB free to unpack")
                        return
                    t.extractall(part, members=members, filter="data")
                write_atomic(part / STAMP, json.dumps(want))
                shutil.rmtree(root, ignore_errors=True)
                part.rename(root)
            except (tarfile.TarError, OSError, EOFError, zlib.error) as x:
                shutil.rmtree(part, ignore_errors=True)
                if read_json(stamp) != want:  # not unpacked by another run meanwhile either
                    cut_short(origin, x)
                    return
        for f in sorted(root.rglob("*")):
            if f.is_symlink() or not f.is_file() or f == stamp or junk_member(f.name):
                continue
            name = f.relative_to(root).as_posix()
            if name.lower().endswith(".zip"):
                try:
                    add_zip(zipfile.ZipFile(f), origin, name + "/", room=[4 * f.stat().st_size + (256 << 20)])
                except (zipfile.BadZipFile, OSError) as x:
                    cut_short(f"{origin}: {name}", x)
                continue
            out.append(Entry(name, lambda f=f: open(f, "rb"), f.stat().st_size, origin))

    for p in sorted(IMPORTS.rglob("*")):
        # A link in an export folder could pull in any file on this Mac (~/.ssh/...): only real files count.
        # (rglob doesn't descend into linked folders.)
        if p.is_symlink() or not p.is_file() or p.name.startswith("."):
            continue
        rel = p.relative_to(IMPORTS)
        if any(PARTIAL.search(x) for x in rel.parts[:2]):  # copied in while a browser was still downloading it
            left_out(str(rel), "", p.stat().st_size, "still downloading")
        elif p.suffix.lower() == ".zip" or p.suffix.lower() == ".olm" and zipfile.is_zipfile(p):  # an Outlook for Mac archive is a zip
            try:
                add_zip(zipfile.ZipFile(p), str(rel))
            except (zipfile.BadZipFile, OSError, EOFError) as x:
                cut_short(str(rel), x)
        elif p.name.lower().endswith(TAR_EXT):
            add_tar(p, str(rel))
        else:
            out.append(Entry(rel.as_posix(), lambda p=p: open(p, "rb"), p.stat().st_size, rel.parts[0]))
    for (origin, why, inside), n in sorted(collections.Counter((x["origin"], x["why"], bool(x["path"])) for x in LEFT_OUT).items()):
        hint = (" Double-click it in Finder (enter its password if it asks), then put the folder it makes in corpus/imports/ instead"
                if why in ("locked with a password", "packed in a way that can't be read here") else "")
        print(f"[imports] {origin}: {f'{n:,} file(s) in it' if inside else 'it'} left out: {why}.{hint}")
    # A tar export taken out of corpus/imports: its unpacked copy goes too (and one left half-unpacked by a crash).
    try:
        for d in unpacked_dir().iterdir():
            half = ".part-" in d.name and time.time() - d.stat().st_mtime > 3600
            if half or (".part-" not in d.name and d.name not in tars):
                shutil.rmtree(d, ignore_errors=True)
    except OSError:
        pass
    return out


def left_out(origin, path, size, why):
    """An archive's file (path) or the whole archive (no path) that entries() leaves out, and why, for the message and the ledger."""
    LEFT_OUT.append({"origin": origin, "path": path, "bytes": size, "why": why})


def cut_short(what, x):
    """An archive that can't be opened (a download that stopped before the end, most often): said, not skipped silently.
    The rest of the export is read; this part once it's downloaded again."""
    print(f"[imports] {what} can't be opened ({type(x).__name__}: {str(x)[:120]}), a download cut short? "
          f"Left out until it's downloaded again")


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
    # surrogatepass: text cut off in the middle of an emoji (half of it left) still gets an id
    return hashlib.sha1("|".join(map(str, parts)).encode("utf-8", "surrogatepass")).hexdigest()[:20]


MOJIBAKE = re.compile(r"[\xc2-\xf4][\x80-\xbf]+")  # one character's UTF-8 bytes, each read as a latin-1 character


def fix_meta(s):
    """Meta exports double-encode UTF-8 as latin-1 ("Ã©" for "é"). Each character is put back on its own, so text cut
    off in the middle of one keeps the rest, and text that's right already (é, 日本語, 🎉) stays as it is."""
    if not isinstance(s, str):
        return s

    def one(m):
        try:
            return m.group().encode("latin-1").decode("utf-8")
        except UnicodeDecodeError:
            return m.group()
    return MOJIBAKE.sub(one, s)


def meta_time(v):
    """A time in a Meta export: Unix seconds or milliseconds (both are called timestamp somewhere), as a number or
    as text, or a date written out. None for anything else."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return parse_time(v) if isinstance(v, str) else None
    return from_unix(v, "ms" if abs(v) > 1e11 else "s")


def after_notes(text):
    """A CSV without the notes LinkedIn writes above some files' header (Connections.csv: "Notes:", a quoted paragraph,
    a blank line), whichever line ends it was written with."""
    if not text.startswith("Notes:"):
        return text
    m = re.match(r'Notes:[^\n]*\n"(?:[^"]|"")*"[^\n]*\n(?:[ \t\r]*\n)*', text) or re.search(r"\n[ \t\r]*\n", text) or \
        re.match(r"[^\n]*\n", text)
    return text[m.end():] if m else ""


def read_csv(e):
    text = e.text().replace("\x00", "")  # csv refuses a line with a NUL in it
    return list(csv.DictReader(io.StringIO(after_notes(text))))


# ---------------------------------------------------------------- AI assistants

ATTACHMENT_CAP = 20_000  # characters of a pasted text or file kept with its message


CLAUDE_PROJECT = re.compile(r"(^|/)projects/[^/]+\.json$")  # claude.ai since 2026: a file a project, not projects.json


def ai_exports(es, W, used):
    projects, memories = {}, []  # claude.ai project id -> name, for its memories (memories.json, read last)
    for e in es:
        if e.name not in ("projects.json", "conversations.json", "memories.json") and not CLAUDE_PROJECT.search(e.path):
            continue
        try:  # some other app's file of that name (in a Drive folder, say) that isn't JSON: not these exports'
            data = e.json()
        except (ValueError, *DAMAGED):
            continue
        if e.name == "projects.json" or CLAUDE_PROJECT.search(e.path):
            ps = data if isinstance(data, list) else [data]
            if ps and isinstance(ps[0], dict) and "uuid" in ps[0] and ({"docs", "prompt_template"} & set(ps[0])):
                used.add(e.path)
                projects.update((p.get("uuid"), p.get("name")) for p in ps if isinstance(p, dict))
                guarded(e, used, lambda e: claude_projects(ps, W("claude_ai")))
            continue
        if e.name == "memories.json":
            ms = data if isinstance(data, list) else [data]
            if any(isinstance(m, dict) and {"conversations_memory", "project_memories", "memory_files"} & set(m) for m in ms):
                used.add(e.path)
                memories.append((e, ms))
            continue
        first = next((c for c in data if isinstance(c, dict)), None) if isinstance(data, list) else None
        if first is None:
            continue
        used.add(e.path)
        if "mapping" in first:
            guarded(e, used, lambda e: chatgpt(data, W("chatgpt")))
            # chat.html beside it is the same conversations as a web page: not a document of its own (unless they
            # couldn't be read).
            folder = PurePosixPath(e.path).parent
            if e.path in used:
                used.update(x.path for x in es if x.origin == e.origin and x.name == "chat.html" and PurePosixPath(x.path).parent == folder)
        elif "chat_messages" in first:
            guarded(e, used, lambda e: claude_chats(data, W("claude_ai")))
    for e, ms in memories:
        guarded(e, used, lambda e: claude_memories(ms, projects, W("claude_ai")))


# What a ChatGPT turn's content is: the text a person saw in the chat. The model's own thinking (thoughts,
# reasoning_recap) stays out; so do a tool's turns other than these (search results it browsed, its errors).
CHATGPT_TOOL_SHOWN = ("execution_output", "tether_quote", "multimodal_text")
CHATGPT_THINKING = ("thoughts", "reasoning_recap")


def chatgpt_text(content, meta):
    """A ChatGPT turn's text: its parts (an image as [image], a voice message as what it said), code as code, a
    quote from a page or a file, and the names of files attached to it."""
    ct = content.get("content_type")
    out = []
    if ct == "code":
        out.append(f"```{content.get('language') or ''}\n{content.get('text') or ''}\n```" if content.get("text") else "")
    elif ct == "tether_quote":
        out += [content.get("title") or content.get("domain") or "", content.get("text") or "", content.get("url") or ""]
    elif isinstance(content.get("parts"), list):
        heard = False
        for p in content["parts"]:
            if isinstance(p, str):
                out.append(p)
            elif isinstance(p, dict):
                kind = str(p.get("content_type") or "")
                if isinstance(p.get("text"), str):
                    out.append(p["text"])
                elif "image" in kind:
                    out.append("[image]")
                heard = heard or "audio" in kind
        if heard and not "".join(out).strip():
            out.append("[audio]")
    elif isinstance(content.get("text"), str):
        out.append(content["text"])
    out += [f"[attachment: {a.get('name')}]" for a in listish(meta.get("attachments")) if isinstance(a, dict) and a.get("name")]
    return "\n".join(x for x in out if isinstance(x, str) and x.strip())


def chatgpt(data, w):
    """ChatGPT's conversations.json: each conversation a tree of turns (mapping), current_node the last turn of the
    branch on screen. That branch is read first; a regenerated answer or an edited prompt on another branch is kept too,
    with meta.tier "superseded". With no current node (or one not in the tree), the branch that ends last is the one on
    screen. The custom instructions and the memory ChatGPT hides at the start of conversations are kept once each, as
    notes."""
    hidden = {}  # note id -> record, the earliest time each was seen
    for c in data:
        if not isinstance(c, dict):
            continue
        nodes = {k: n for k, n in (c.get("mapping") or {}).items() if isinstance(n, dict)} if isinstance(c.get("mapping"), dict) else {}

        def branch(node):
            out = []
            while isinstance(node, str) and node in nodes and node not in out:  # a loop stops where it comes round
                out.append(node)
                node = nodes[node].get("parent")
            return out[::-1]

        def when(k):
            m = nodes[k].get("message")
            return (m.get("create_time") or 0) if isinstance(m, dict) and isinstance(m.get("create_time"), (int, float)) else 0
        shown = branch(c.get("current_node"))
        if not shown and nodes:
            leaves = [k for k, n in nodes.items() if not any(x in nodes for x in listish(n.get("children")))] or list(nodes)
            shown = branch(max(leaves, key=when))
        on = set(shown)
        for k in shown + [k for k in nodes if k not in on]:
            m = nodes[k].get("message")
            if not isinstance(m, dict):
                continue
            author = m.get("author") if isinstance(m.get("author"), dict) else {}
            role = author.get("role")
            content = m.get("content") if isinstance(m.get("content"), dict) else {}
            meta = m.get("metadata") if isinstance(m.get("metadata"), dict) else {}
            ct = content.get("content_type")
            ts = from_unix(m.get("create_time") or c.get("create_time"))
            if ct in ("user_editable_context", "model_editable_context"):
                yours = ct == "user_editable_context"
                text = "\n".join(x for x in (content.get("user_profile"), content.get("user_instructions")) if isinstance(x, str) and x.strip()) \
                    if yours else content.get("model_set_context")
                if isinstance(text, str) and text.strip():
                    key = ("instructions:" if yours else "memory:") + rid(text)
                    if key not in hidden or (ts or "~") < (hidden[key]["ts"] or "~"):
                        hidden[key] = dict(id=key, kind="note", ts=ts, author="me" if yours else "chatgpt", is_me=yours,
                                           title="ChatGPT custom instructions" if yours else "What ChatGPT remembered", text=text,
                                           meta={"tool": "chatgpt", **({} if yours else {"memory": True})})
                continue
            if meta.get("is_visually_hidden_from_conversation") or ct in CHATGPT_THINKING or role not in ("user", "assistant", "tool") or \
                    role == "tool" and ct not in CHATGPT_TOOL_SHOWN:
                continue
            text = chatgpt_text(content, meta)
            key = m.get("id") or k
            if not text.strip() or w.has(key):
                continue
            w.add(id=key, kind="ai_turn", ts=ts, author="me" if role == "user" else "chatgpt", is_me=role == "user",
                  thread=c.get("id") or c.get("conversation_id"), thread_name=c.get("title"), text=text,
                  meta={"tool": "chatgpt", "model": meta.get("model_slug"), **({} if k in on else {"tier": "superseded"}),
                        **({"from": author.get("name")} if role == "tool" and author.get("name") else {})})
    for key, rec in hidden.items():
        if not w.has(key):
            w.add(**rec)


# claude.ai writes this in a message's text where a block its export doesn't show was (an artifact, a tool's use).
CLAUDE_PLACEHOLDER = re.compile(r"\s*```\s*This block is not supported on your current device yet\.?\s*```\s*")


def claude_text(m):
    """A claude.ai message's text, from its content blocks when it has them: its text, and what each artifact (or file
    Claude wrote) holds, which the message's own text has only a placeholder for. A tool's use is named ([web_search:
    tides]); what it returned and Claude's thinking stay out."""
    out = []
    for b in listish(m.get("content")):
        if not isinstance(b, dict):
            continue
        if b.get("type") == "text" and isinstance(b.get("text"), str):
            out.append(b["text"])
        elif b.get("type") == "tool_use":
            name, args = b.get("name") or "tool", b.get("input") if isinstance(b.get("input"), dict) else {}
            body = next((args[k] for k in ("content", "file_text", "new_str") if isinstance(args.get(k), str) and args[k]), "")
            if name == "artifacts":
                head = f"[artifact: {args.get('title') or args.get('id') or 'untitled'}" + (", updated]" if args.get("command") == "update" else "]")
            else:
                what = next((args[k] for k in ("query", "title", "path", "description", "command", "url") if isinstance(args.get(k), str) and args[k]), "")
                head = f"[{name}: {what}]" if what else f"[{name}]"
            out.append(head + (f"\n{body}" if body else ""))
    text = "\n\n".join(x for x in out if x.strip())
    if not text and isinstance(m.get("text"), str):
        text = CLAUDE_PLACEHOLDER.sub("\n\n", m["text"]).strip()
    return text


def claude_chats(data, w):
    for c in data:
        if not isinstance(c, dict):
            continue
        for m in listish(c.get("chat_messages")):
            if not isinstance(m, dict):
                continue
            # A pasted text or a file's text comes with its message (extracted_content), up to ATTACHMENT_CAP;
            # images and other files have only a name.
            parts, names = [claude_text(m)], []
            for a in listish(m.get("attachments")) + listish(m.get("files")):
                if not isinstance(a, dict):
                    continue
                name, body = a.get("file_name") or "", (a.get("extracted_content") or "").strip()
                if not (name or body):
                    continue
                names.append(name or "pasted text")
                parts.append(f"[attachment: {name or 'pasted text'}]" + (f"\n{body[:ATTACHMENT_CAP]}" if body else "")
                             + (" […]" if len(body) > ATTACHMENT_CAP else ""))
            text = "\n".join(parts)
            if not text.strip() or not m.get("uuid") or w.has(m.get("uuid")):
                continue
            me = m.get("sender") == "human"
            w.add(id=m.get("uuid"), kind="ai_turn", ts=m.get("created_at"), author="me" if me else "claude", is_me=me,
                  thread=c.get("uuid"), thread_name=c.get("name"), text=text,
                  meta={"tool": "claude.ai", "attachments": names or None})


def claude_memories(data, projects, w):
    """claude.ai's memories.json: what Claude remembers about you, written by Claude, so not yours: the account's memory
    (one document), each project's, and its memory files (/profile.md ...). One note each."""
    for acct in data:
        if not isinstance(acct, dict):
            continue
        pm = acct.get("project_memories") if isinstance(acct.get("project_memories"), dict) else {}
        items = [("memory", None, acct.get("conversations_memory"), None, "What Claude remembered")]
        items += [(f"memory:{pid}", pid, text, None, f"What Claude remembered: {projects.get(pid) or 'a project'}") for pid, text in pm.items()]
        items += [(f"memory:{f.get('path')}", None, f.get("content"), f.get("updated_at"), f"What Claude remembered: {f.get('path')}")
                  for f in listish(acct.get("memory_files")) if isinstance(f, dict)]
        for key, pid, text, ts, title in items:
            key = f"{acct.get('account_uuid') or 'account'}:{key}"
            if not isinstance(text, str) or not text.strip() or w.has(key):
                continue
            w.add(id=key, kind="note", ts=ts, author="claude.ai", is_me=False, thread=pid or "memory",
                  thread_name=(projects.get(pid) or "A project") if pid else "Claude's memory", title=title[:300], text=text[:200_000],
                  meta={"tool": "claude.ai", "memory": True, "project": projects.get(pid)})


def claude_projects(data, w):
    """claude.ai's projects.json: each project (name, description, its instructions) and the documents added to it.
    The starter project claude.ai makes for everyone is kept as not yours."""
    for p in data:
        pid, name = p.get("uuid"), p.get("name") or "A project"
        docs = [d for d in p.get("docs") or [] if isinstance(d, dict)]
        starter = bool(p.get("is_starter_project"))
        key = f"project:{pid}"
        if not pid or w.has(key):
            continue
        lines = [name, p.get("description") or "", f"Instructions: {p['prompt_template']}" if p.get("prompt_template") else "",
                 "Documents: " + ", ".join(d.get("filename") or "untitled" for d in docs) if docs else ""]
        w.add(id=key, kind="note", ts=p.get("created_at"), author="claude.ai" if starter else "me", is_me=not starter,
              thread=pid, thread_name=name, title=name[:300], text="\n".join(x for x in lines if x)[:200_000],
              meta={"tool": "claude.ai", "project": True, "modified": p.get("updated_at"), "documents": len(docs) or None,
                    "private": p.get("is_private"), "starter": starter or None})
        for i, d in enumerate(docs):
            dkey = f"project:{pid}:{d.get('uuid') or i}"
            if w.has(dkey):
                continue
            w.add(id=dkey, kind="document", ts=d.get("created_at"), author="claude.ai" if starter else "me", is_me=not starter,
                  thread=pid, thread_name=name, title=(d.get("filename") or "untitled")[:300],
                  text=(d.get("content") or "")[:200_000] or d.get("filename"), meta={"tool": "claude.ai", "project": name})


# ---------------------------------------------------------------- Google Takeout

ACTIVITY = (("Searched for ", "search"), ("Watched ", "media"), ("Listened to ", "media"), ("Visited ", "visit"),
            ("Viewed ", "visit"), ("Used ", "app_usage"), ("Prompted ", "ai_turn"), ("Asked ", "ai_turn"))




def mbox_folder(p):
    """Mail.app's Export Mailbox writes <Folder>.mbox/mbox; other tools write <Folder>.mbox."""
    path = PurePosixPath(p)
    name = path.parent.name if path.name == "mbox" else path.name
    name = name[:-5] if name.lower().endswith(".mbox") else name
    base = re.sub(r" \d+$", "", name)  # Mail splits big folders into ~2 GB pieces: Inbox, Inbox 2, Inbox 3, ...
    return base if base.lower() in SENT_FOLDERS | SKIP_FOLDERS | {"inbox", "archive", "drafts"} else name


GP_DIR = re.compile(r"Google (?:Photos|Fotos|Foto)/")  # Photos' folder: Google Fotos in German, Google Foto in Italian
# The folder of each year's photos (an album is the others), in the languages it's been seen in.
GP_YEAR = re.compile(r"(?:Photos from|Fotos von|Fotos del|Foto da|Foto_s van) \d{4}")
GP_SUPPLEMENTAL = ".supplemental-metadata"
GP_EDITED = ("-edited", "-bearbeitet", "-modifié", "-editado", "-modificato", "-bewerkt", "-redigerad", "-muokattu")
GP_VIDEO = (".mp4", ".mov")


def google_photos_files(es):
    """{sidecar path: [its photo's entries]} for Google Photos in a Takeout: the photo the sidecar is named after
    (Google adds ".supplemental-metadata", cut short to fit 51 characters, and puts a copy's "(1)" after it all),
    then its edited version and a Live Photo's video, which have no sidecar of their own. Matched within one
    export's folder in corpus/imports/, across its zip parts (a photo and its sidecar can be in different ones)."""
    folder = lambda e: (PurePosixPath(takeout_of(e)).parts[0] if e.origin else "", posixpath.dirname(e.path[GP_DIR.search(e.path).start():]))
    media, sidecars = collections.defaultdict(list), []  # (export folder, folder from Google Photos/, name) -> entries
    for e in es:
        if not GP_DIR.search(e.path):
            continue
        if e.path.endswith(".json"):
            sidecars.append(e)
        elif e.path.lower().endswith(FILE_EXT) and e.size:
            media[(*folder(e), e.name)].append(e)
            if e.name.lower() != e.name:
                media[(*folder(e), e.name.lower())].append(e)
    taken, out = set(), {}

    def pick(e, where, name):
        for n in (name, name.lower()):  # the same name, else the same but for case
            found = [m for m in media.get((*where, n), ()) if m.path not in taken]
            found = [m for m in found if m.origin == e.origin] or found  # the same zip part first
            if found:
                taken.add(found[0].path)
                return found[0]

    for e in sidecars:
        name = e.name[:-5]
        dup = re.search(r"\(\d+\)$", name)
        name = name[:dup.start()] if dup else name
        for k in range(len(GP_SUPPLEMENTAL), 1, -1):
            if name.endswith(GP_SUPPLEMENTAL[:k]):
                name = name[:-k]
                break
        if dup:
            stem, ext = posixpath.splitext(name)
            name = f"{stem}{dup.group(0)}{ext}"
        if m := pick(e, folder(e), name):
            out[e.path] = [m]
    for e in sidecars:  # then what goes with each photo, of what no sidecar is named after
        for m in list(out.get(e.path, [])):
            stem, ext = posixpath.splitext(m.name)
            more = [f"{stem}{x}{ext}" for x in GP_EDITED]
            if ext.lower() not in GP_VIDEO:
                more += [f"{stem}{x}" for x in (".MP4", ".MOV")]
            out[e.path] += [x for x in (pick(e, folder(m), n) for n in more) if x]
    return out


def mbox_source(e):
    """(from a Takeout?, its source) for a mailbox file: Takeout mail is Gmail; any other mailbox export is named
    after its folder in corpus/imports/ (e.g. hotmail)."""
    p = e.path
    takeout = "Takeout/" in p or "Mail/" in p and "takeout" in e.origin.lower()
    return takeout, "gmail" if takeout else mail_source(PurePosixPath(e.origin).parts[0])


MAIL_SOURCES = ("gmail", "hotmail")  # mail already: a mailbox in imports/gmail/ or imports/hotmail/ is theirs
_mapped_folders = []  # the folders with a mapping, once a run (google() starts it again)


def taken(folder):
    """Whether a folder under corpus/imports/ is named as another source is: this Mac's or the iPhone's (OTHER_SOURCES, phone_*),
    an export's (EXPORT_SOURCES), a mapping's, or a catch-all's (<export>_other, <export>_files)."""
    s = re.sub(r"\W+", "_", folder.lower())
    if not _mapped_folders:
        _mapped_folders.append({folder_key(f) for f in load_mappings()})
    return s not in MAIL_SOURCES and (s in OTHER_SOURCES or s in EXPORT_SOURCES or s.startswith("phone_")
                                      or s.endswith(("_other", "_files")) or s in _mapped_folders[0])


def mail_source(folder):
    """A mailbox's source: its folder's name under corpus/imports/ (hotmail, work_mail); in a folder named as another source is, that
    name and _mail (mail_mail, instagram_mail), as the app names the folder it puts such a mailbox in (status.ts mailSource). Read
    as the folder's source, it would replace what Mail on this Mac read, or be mixed in with Instagram's messages."""
    s = re.sub(r"\W+", "_", folder.lower())
    return f"{s}_mail" if taken(s) else s


# ---------------------------------------------------------------- mailboxes read before

# A mailbox source whose .mbox files are all as they were when it was last read (the same files, sizes and times, read
# by the same code for the same you) keeps what that read wrote: a new Spotify export doesn't mean parsing 150,000
# emails again. UMP_REREAD_ALL=1 (the readers changed) reads them all. What was read is remembered once it's written.
READ_CODE = ("imports.py", "email_parse.py", "identity.py", "common.py")
_mail_kept, _mail_read = set(), {}  # this run: sources kept as they were; sources read, and their file before


def _file_stamp(p):
    try:
        st = os.stat(p)
        return [st.st_size, st.st_mtime_ns, st.st_ino]
    except OSError:
        return None


def _mbox_stamp(e):
    """An mbox entry as it is: its own size and time on disk, or its archive's. Raises for one not on disk."""
    p = IMPORTS / e.origin
    st = (p if p.is_file() else IMPORTS / e.path).stat()
    return [e.origin, e.path, e.size, st.st_size, st.st_mtime_ns]


def _reading():
    """What else decides what a mailbox reads as: the code reading it, and your addresses and names."""
    h = hashlib.sha1()
    for n in READ_CODE:
        h.update((Path(__file__).resolve().parent / n).read_bytes())
    me = identity.ME
    h.update(json.dumps([sorted(me.get(k) or ()) for k in ("emails_l", "names_l", "usernames_l")]).encode())
    return h.hexdigest()


def mailboxes_as_before(es):
    """The mailbox sources whose files haven't changed since they were last read (and written)."""
    _mail_kept.clear()
    _mail_read.clear()
    boxes = collections.defaultdict(list)
    for e in es:
        if is_mbox(e.path) or is_message(e):
            boxes[mbox_source(e)[1]].append(e)
    if not boxes:
        return set()
    try:
        state = json.loads(common.MANIFEST.with_name(".imports-read.json").read_text())
        manifest = json.loads(common.MANIFEST.read_text())
    except (OSError, ValueError):
        state, manifest = {}, {}
    reading = _reading()
    for source, box in boxes.items():
        try:
            files = [_mbox_stamp(e) for e in box]
        except OSError:
            continue  # not files on disk: read
        out = _file_stamp(common.NORM / f"{source}.jsonl")
        was = state.get(source) or {}
        if (os.environ.get("UMP_REREAD_ALL") != "1" and out and source in manifest
                and was == {"files": files, "reading": reading, "out": out}):
            _mail_kept.add(source)
        else:
            _mail_read[source] = {"files": files, "reading": reading, "before": out}
    return set(_mail_kept)


def remember_mailboxes(manifest):
    """After the writers: what each mailbox source read, if its file was written (a parser that failed keeps the old
    one, and that isn't remembered as read); the ones kept were read again as far as the manifest says."""
    path = common.MANIFEST.with_name(".imports-read.json")
    if not (_mail_kept or _mail_read):
        return
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError):
        state = {}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for source in _mail_kept:
        if isinstance(manifest.get(source), dict):
            manifest[source].update(ran_at=now, code=common.code_version())
    for source, r in _mail_read.items():
        out = _file_stamp(common.NORM / f"{source}.jsonl")
        if out and out != r["before"]:
            state[source] = {"files": r["files"], "reading": r["reading"], "out": out}
        else:
            state.pop(source, None)
    _mail_kept.clear()
    _mail_read.clear()
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state))
        tmp.replace(path)
    except OSError:
        pass


# Takeout's own folder, and "Takeout 2", "Takeout 3" ...: what Archive Utility calls parts unzipped beside each other.
TAKEOUT = re.compile(r"(^|/)Takeout(?: \d+)?/")


def in_takeout(e):
    return bool(TAKEOUT.search(e.path)) or "takeout" in (e.origin or "").lower()


def head(e, n=1 << 16):
    """An entry's first bytes. Takeout names folders and files in the account's language (Meine Aktivitäten/Suche/
    MeineAktivitäten.html, Aufgaben/, Maps (Meine Orte)/Gespeicherte Orte.json), so what's in a file says what it is."""
    with e.open() as f:
        return f.read(n)


def sniffed(e):
    """What a JSON or HTML file holds, for one named some way the branches above don't know; None for anything else."""
    ext = PurePosixPath(e.name).suffix.lower()
    takeout = in_takeout(e)
    # Timeline is exported by itself too (corpus/imports/timeline/), not only in a Takeout
    if ext not in (".json", ".html") or GP_DIR.search(e.path) or not e.size or \
            not takeout and not (ext == ".json" and re.search(r"timeline|location", f"{e.origin}/{e.path}", re.I)):
        return None
    b = head(e, 8192 if ext == ".json" else 1 << 16)  # a JSON's first keys; a page's style sheet comes first
    if ext == ".json":
        if b'"semanticSegments"' in b or b'"timelineObjects"' in b or \
                re.match(rb'\s*\[\s*\{\s*"(?:startTime|endTime)"', b) and re.search(rb'"(?:topCandidate|timelinePath)"', b):
            return "timeline"
        if not takeout:
            return None
        if re.match(rb'\s*\[\s*\{\s*"header"\s*:', b):
            return "activity"
        if re.match(rb'\s*\{\s*"Browser History"\s*:', b):
            return "chrome"
        if b'"tasks#taskLists"' in b[:200]:
            return "tasks"
        if (b'"FeatureCollection"' in b or re.match(rb'\s*\{\s*"features"\s*:', b)) and "Maps" in e.path:
            return "places"  # Maps (your places), Maps (Meine Orte), Maps/My labeled places
        return None
    if b"outer-cell" in b or b"mdl-" in b:  # My Activity's page: its items are outer-cells (after a long style sheet)
        return "activity_page"
    if b"NETSCAPE-Bookmark-file" in b[:200] and "Chrome/" in e.path:
        return "bookmarks"
    return None


def listish(x):
    return x if isinstance(x, list) else []


# An item that's an ad Google showed you: its details say so ("From Google Ads"; "De los anuncios de Google" ...).
AD_DETAIL = re.compile(r"Google Ads|Google.{0,3}(Anzeigen|annunci|advertenties)|(anuncios|annonces|anúncios|annunci)\s+(de |do |di )?Google", re.I)


def my_activity(items, w):
    """My Activity, and YouTube's watch and search history, which are the same shape: one record per item. In another
    language a title says what you did its own way ("Has visto …"), so the link says it: a search's query, a video."""
    for it in listish(items):
        if not isinstance(it, dict):
            continue
        title = str(it.get("title") or "")
        url = it.get("titleUrl") if isinstance(it.get("titleUrl"), str) else None
        kind, text = "activity", title
        for pre, k in ACTIVITY:
            if title.startswith(pre):
                kind, text = k, title[len(pre):]
                break
        else:
            tag, q = classify(url or "")
            if tag in ("search", "youtube_search") and q:
                kind, text = "search", q
            elif tag == "youtube_watch":
                kind = "media"
        subs = ", ".join(str(s["name"]) for s in listish(it.get("subtitles")) if isinstance(s, dict) and s.get("name"))
        resp = " ".join(html_to_text(str(h.get("html") or "")) for h in listish(it.get("safeHtmlItem")) if isinstance(h, dict))
        vid = re.search(r"youtube\.com/watch\?v=([\w-]+)", url or "")
        if vid and kind == "media" and not text.startswith("http"):
            YT_TITLES.setdefault(vid.group(1), text)
        key = rid(it.get("header"), title, it.get("time"))
        if w.has(key):
            continue
        header = it.get("header") if isinstance(it.get("header"), str) else None
        meta = {"product": header}
        # An ad you were shown (a YouTube ad, a sponsored result), not something you watched or visited. Kept as one,
        # with what it would have looked like, so it isn't counted as yours.
        if any(AD_DETAIL.search(str(d.get("name") or "")) for d in listish(it.get("details")) if isinstance(d, dict)):
            w.add(id=key, kind="ad", ts=parse_time(it.get("time")), author="Google Ads", is_me=False, thread=header,
                  thread_name=header, title=text[:300], text="\n".join(x for x in (text, subs) if x),
                  url=url, meta={**meta, "shown_as": kind})
            continue
        w.add(id=key, kind=kind, ts=parse_time(it.get("time")), author="me", is_me=True, thread=header,
              thread_name=header, title=text[:300], text="\n".join(x for x in (text, subs, resp[:20000]) if x),
              url=url, meta=meta)


# ---------------------------------------------------------------- times written out for people

MONTHS = {}  # a month's name or abbreviation, in the languages Takeout writes dates in, -> its number
for _n, _names in enumerate((
        "january jan januar janvier janv enero ene gennaio gen janeiro januari jänner",
        "february feb februar février févr fév febrero febbraio fevereiro fev februari",
        "march mar märz mär mrz mars marzo março maart mrt",
        "april apr avril avr abril abr aprile",
        "may mai mayo maggio mag maio mei",
        "june jun juni juin junio giugno giu junho",
        "july jul juli juillet juil julio luglio lug julho",
        "august aug août agosto ago augustus",
        "september sep sept septembre septiembre setiembre settembre set setembro",
        "october oct oktober okt octobre octubre ottobre ott outubro out",
        "november nov novembre noviembre novembro",
        "december dec dezember dez décembre déc diciembre dic dicembre dezembro"), 1):
    MONTHS.update(dict.fromkeys(_names.split(), _n))
# Zone abbreviations Takeout writes after a time (CLDR's short names), in minutes from UTC. A zone not here (IST is
# three different ones) is read as this Mac's clock, like a time written with none.
ZONES = {"UTC": 0, "GMT": 0, "UT": 0, "Z": 0, "WET": 0, "WEZ": 0, "BST": 60, "WEST": 60, "WESZ": 60, "CET": 60, "MEZ": 60,
         "CEST": 120, "MESZ": 120, "EET": 120, "OEZ": 120, "EEST": 180, "OESZ": 180, "MSK": 180, "SAST": 120, "CAT": 120,
         "EAT": 180, "WAT": 60, "PKT": 300, "ICT": 420, "WIB": 420, "SGT": 480, "HKT": 480, "PHT": 480, "AWST": 480,
         "JST": 540, "KST": 540, "ACST": 570, "ACDT": 630, "AEST": 600, "AEDT": 660, "NZST": 720, "NZDT": 780,
         "HST": -600, "AKST": -540, "AKDT": -480, "PST": -480, "PDT": -420, "MST": -420, "MDT": -360, "CST": -360,
         "CDT": -300, "EST": -300, "EDT": -240, "AST": -240, "ADT": -180, "NST": -210, "NDT": -150, "BRT": -180,
         "ART": -180, "CLT": -240, "COT": -300, "PET": -300}


def written_date(s):
    """(year, month, day) in a date written out: 13.01.2024, 2024/01/13, 2024년 1월 13일, Jan 13, 2024, 13 ene 2024,
    8. Juni 2016, 8 de junio de 2016. Numbers alone are read day first, unless that can't be (1/13/2024)."""
    m = re.search(r"(\d{4})\s*[./\-年년]\s*(\d{1,2})\s*[./\-月월]\s*(\d{1,2})", s)
    if m:
        return int(m[1]), int(m[2]), int(m[3])
    m = re.search(r"\b(\d{1,2})[./\-](\d{1,2})[./\-](\d{4}|\d{2})\b", s)
    if m:
        a, b, y = int(m[1]), int(m[2]), int(m[3])
        return y + (2000 if y < 100 else 0), *((a, b) if b > 12 else (b, a))
    y = re.search(r"\b(1[89]\d\d|2\d{3})\b", s)
    months = [MONTHS[w.lower()] for w in re.findall(r"[^\W\d_]+", s) if w.lower() in MONTHS]
    day = y and re.search(r"\b(\d{1,2})\b", s[:y.start()] + " " + s[y.end():])
    return (int(y[1]), months[-1], int(day[1])) if y and months and day else None  # the last name: "mar., 13 ene"


def loose_time(s):
    """A time written out for people, as Takeout's pages and Google Chat write it in the account's language ("Jan 13,
    2024, 6:57:09 PM PST", "13.01.2024, 18:57:09 MEZ", "Mittwoch, 8. Juni 2016 um 04:00:00 UTC"), in UTC; with no zone
    it's this Mac's clock. None when it isn't one."""
    if not isinstance(s, str):
        return None
    s = unicodedata.normalize("NFKC", s)  # the narrow no-break space before PM is a space
    t = re.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?(?:[.,]\d+)?(?:\s*([AaPp])\.?\s?[Mm]\.?(?![^\W\d_]))?", s)
    if not t:
        return None
    hh, mm, ss = int(t[1]), int(t[2]), int(t[3] or 0)
    noon = (t[4] or "").lower() or {"午前": "a", "오전": "a", "午後": "p", "오후": "p"}.get(
        (re.search(r"(午前|午後|오전|오후)\s*$", s[:t.start()]) or [None, None])[1], "")
    hh = hh % 12 + (12 if noon == "p" else 0) if noon else hh
    date = written_date(s[:t.start()]) or written_date(s)
    try:
        d = datetime(*date, hh, mm, ss) if date else None
    except ValueError:
        return None
    if not d:
        return None
    rest = s[t.end():]
    z = re.search(r"\b(?:UTC|GMT)\s*([+\-−])\s*(\d{1,2})(?::?(\d{2}))?", rest)
    off = (-1 if z[1] in "-−" else 1) * (int(z[2]) * 60 + int(z[3] or 0)) if z else \
        next((ZONES[w] for w in re.findall(r"\b[A-Z]{1,5}\b", rest) if w in ZONES), None)
    return iso(d.replace(tzinfo=timezone(timedelta(minutes=off)))) if off is not None else local_utc(d)


# ---------------------------------------------------------------- My Activity as a web page (Takeout's default)

class ActivityPage(HTMLParser):
    """My Activity's page (and YouTube's history as a page): one outer-cell per item, its product in the header cell;
    in the first content cell what you did, line by line (<br>): the title and its link, a channel and its link, the
    time, then for Gemini its answer; and in the caption cell Products, Details and Locations, each under its name."""

    def __init__(self):
        super().__init__()
        self.items, self.it, self.depth, self.cell, self.bold = [], None, 0, None, False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "div":
            self.depth += 1
            cls = a.get("class") or ""
            if "outer-cell" in cls:
                self.it = {"at": self.depth, "header": [], "content": [[]], "links": [], "caption": [], "seen": False}
            elif self.it is not None and not self.cell:
                if "header-cell" in cls:
                    self.cell = ("header", self.depth)
                elif "mdl-typography--caption" in cls:
                    self.cell = ("caption", self.depth)
                elif "content-cell" in cls and "text-right" not in cls and not self.it["seen"]:
                    self.cell, self.it["seen"] = ("content", self.depth), True
        elif not self.cell:
            return
        elif tag == "br" or tag in ("p", "li") and self.cell[0] == "content":
            if self.cell[0] == "content":
                self.it["content"].append([])
            elif self.cell[0] == "caption" and self.it["caption"]:
                self.it["caption"][-1][1].append("")
        elif tag == "a" and self.cell[0] == "content" and a.get("href"):
            self.it["links"].append((len(self.it["content"]) - 1, a["href"]))
        elif tag == "b" and self.cell[0] == "caption":
            self.it["caption"].append(["", [""]])
            self.bold = True

    def handle_endtag(self, tag):
        if tag == "b":
            self.bold = False
        if tag != "div":
            return
        if self.cell and self.cell[1] == self.depth:
            self.cell = None
        if self.it is not None and self.it["at"] == self.depth:
            self.items.append(self.finish(self.it))
            self.it = None
        self.depth -= 1

    def handle_data(self, data):
        if not self.cell:
            return
        if self.cell[0] == "header":
            self.it["header"].append(data)
        elif self.cell[0] == "content":
            self.it["content"][-1].append(data)
        elif self.it["caption"]:
            if self.bold:
                self.it["caption"][-1][0] += data
            else:
                self.it["caption"][-1][1][-1] += data

    @staticmethod
    def finish(it):
        clean = lambda x: re.sub(r"\s+", " ", unicodedata.normalize("NFKC", x)).strip()  # noqa: E731
        lines = [clean("".join(x)) for x in it["content"]]
        when = next((i for i in range(1, len(lines)) if len(lines[i]) <= 80 and loose_time(lines[i])), None)
        end = when if when is not None else len(lines)
        link = lambda i: next((h for n, h in it["links"] if n == i), None)  # noqa: E731
        caption = [(clean(k).rstrip(":"), [clean(v) for v in vs if clean(v)]) for k, vs in it["caption"]]
        out = {"header": clean("".join(it["header"])), "title": lines[0] if lines else "", "titleUrl": link(0),
               "time": loose_time(lines[when]) if when is not None else None,
               "subtitles": [{"name": lines[i], "url": link(i)} for i in range(1, end) if lines[i]],
               # the first is Products; one asking a question is "Why is this here?"
               "products": caption[0][1] if caption else [],
               "details": [{"name": v} for k, vs in caption[1:] if not k.endswith("?") for v in vs]}
        answer = "\n".join(x for x in lines[end + 1:] if x) if when is not None else ""
        if answer:
            out["safeHtmlItem"] = [{"html": html.escape(answer)}]
        return out


def activity_page(e):
    """The items of a My Activity page, read as it streams (YouTube's history can be hundreds of MB)."""
    page = ActivityPage()
    dec = io.TextIOWrapper(e.open(), encoding="utf-8", errors="replace")
    with dec:
        for chunk in iter(lambda: dec.read(1 << 20), ""):
            page.feed(chunk)
    page.close()
    return page.items


def guarded(e, used, read, *a):
    """read(e, *a), for one file of an export: one that's damaged, or in a shape not seen before, is said so and left
    to the catch-alls (unreadable), and stops nothing else. What it gave before it failed is kept."""
    try:
        return read(e, *a)
    except Exception as x:  # noqa: BLE001 - not JSON, cut short, a damaged zip member, an item of an odd shape
        unreadable(e, x, used)
        return None


def unreadable(e, x, used):
    """A file a reader failed on (one that's damaged, or in a shape not seen before): said so (once), and left unread, so
    the catch-alls can keep it and the ledger lists it. One file stops nothing else."""
    used.discard(e.path)
    if is_mbox(e.path) or is_message(e):
        _mail_read.pop(mbox_source(e)[1], None)  # read again next time, not remembered as read
    if (e.origin, e.path) not in _unread_said:
        _unread_said.add((e.origin, e.path))
        print(f"[imports] couldn't read {e.origin}: {e.path} ({type(x).__name__}: {str(x)[:200]}); listed as not read")


_unread_said = set()


def is_mbox(p):
    return p.lower().endswith(".mbox") or p.endswith(".mbox/mbox") or p in SNIFFED_MBOX


SNIFFED_MBOX = set()  # mailboxes named without .mbox, found this run (sniff_mboxes)


def sniff_mboxes(es):
    """Mailboxes saved without .mbox: Thunderbird keeps each folder as a file named Inbox, Sent, Trash (Inbox.msf beside
    it is its index), and mbox tools write a plain "mbox". A file with no extension that starts as an mbox does: a
    "From " line, then headers."""
    SNIFFED_MBOX.clear()
    for e in es:
        if re.search(r"\.[A-Za-z0-9]{1,5}$", e.name) or not e.size or in_takeout(e) or is_mbox(e.path):
            continue
        try:
            first, _, rest = head(e, 4096).partition(b"\n")
        except (OSError, *DAMAGED):
            continue
        if MBOX_SEPARATOR.match(first) and FIRST_HEADER.match(rest):
            SNIFFED_MBOX.add(e.path)


# An Outlook for Mac archive's message: Accounts/<account>/com.microsoft.__Messages/<folder>/message_00001.xml (each
# message's attachments in com.microsoft.__Attachments/ beside them).
OLM_MESSAGE = re.compile(r"(^|/)com\.microsoft\.__Messages/(?!(.*/)?com\.microsoft\.__Attachments/).*\.(xml|olk15message)$")
OLM_ATTACHMENT = re.compile(r"(^|/)com\.microsoft\.__Messages/(.*/)?com\.microsoft\.__Attachments/")


# The sources this Mac's own connectors write (mail_app.py's mail, whatsapp.py's whatsapp ...), the iPhone's (phone_*)
# and the other exports': a message file in a folder of corpus/imports/ named like one (an .eml sent in a WhatsApp chat,
# attached to a Notion page) isn't read as that folder's mail, which would replace or join what's read there.
OTHER_SOURCES = {"ai_coding", "app_usage", "apple_maps", "apple_notes", "books", "browser_history", "browser_saved", "calendar",
                 "calls", "contacts", "documents", "editor_history", "git_commits", "health", "health_samples", "imessage",
                 "iphone_contacts", "mail", "notion", "photos", "photos_memories", "podcasts", "reminders", "shared_photos",
                 "shell_history", "voice_memos", "whatsapp"}


def is_message(e):
    """A message saved as a file of its own, out of a Takeout: .eml (dragged out of Mail, Outlook or Thunderbird), .emlx
    (Mail's own, from a copied ~/Library/Mail), or one in an Outlook for Mac archive (.olm). Not in a folder named as
    another source is (taken): an attachment there (an .eml sent in a WhatsApp chat) is that export's."""
    if e.origin.lower().endswith(".olm"):  # a mailbox, wherever it is (in another source's folder, as <folder>_mail)
        return bool(OLM_MESSAGE.search(e.path))
    return e.name.lower().endswith((".eml", ".emlx")) and not in_takeout(e) and not taken(PurePosixPath(e.origin).parts[0])


def message_bytes(e, raw):
    """A message file's message: an .emlx has its length in bytes on the first line, and a plist after it; an Outlook
    archive's is XML."""
    if e.origin.lower().endswith(".olm"):
        return olm_message(raw)
    if e.name.lower().endswith(".emlx"):
        n, _, rest = raw.partition(b"\n")
        return rest[:int(n)] if n.strip().isdigit() else rest
    return raw


def message_folder(e):
    """The mail folder a message file is in: Mail's <Folder>.mbox around an .emlx, else the folder it's in (not its
    export's own)."""
    parts = PurePosixPath(e.path).parts[:-1]
    boxes = [x for x in parts if x.lower().endswith(".mbox")]
    if boxes:
        return mbox_folder(boxes[-1])
    return parts[-1] if parts and "/".join(parts) != e.origin else ""


def vcard_line(k, v):
    """A card's value in words: an address's or a company's parts, which it writes with ";" between them (;;1 Main St;
    Springfield;IL;62701), with commas; a birthday without a year, for which Apple writes 1604, without one."""
    if k in ("ADR", "ORG"):
        v = ", ".join(x.strip() for x in v.split(";") if x.strip())
    elif k == "BDAY":
        v = re.sub(r"^1604-", "--", v)
    return f"{k.lower()}: {v}"


def google(es, W, used):
    YT_TITLES.clear()
    _mapped_folders.clear()
    keep, photos = {}, {}  # Keep notes and Photos' photos, gathered from every Takeout first: each is kept once
    photo_files = None
    sniff_mboxes(es)
    as_before = mailboxes_as_before(es)
    if as_before:
        print(f"[imports] {', '.join(sorted(as_before))}: the mailboxes are as they were when last read; kept as read")
    keep_json = {keep_twin(e) for e in es if is_keep(e.path) and e.path.endswith(".json")}
    named_only = {}  # contacts with only a name: (source, its id) -> the companies and addresses seen with it
    for e in es:
        p = e.path
        try:
            if is_mbox(p) or is_message(e):  # a mailbox, or a message in a file of its own: its folder's mail
                used.add(p)
                takeout, source = mbox_source(e)
                if source in as_before:
                    continue
                folder = mbox_folder(p) if is_mbox(p) else message_folder(e)
                w = W(source)
                with e.open() as f:
                    for raw in iter_mbox(f) if is_mbox(p) else [message_bytes(e, f.read())]:
                        try:
                            rec = parse_email(raw)
                        except Exception:  # noqa: BLE001 - one message that can't be read: counted, the rest are
                            w.notes["unreadable"] = w.notes.get("unreadable", 0) + 1
                            continue
                        labels = set(gmail_labels(rec.pop("_labels")))
                        if takeout and labels & (SPAM_LABELS | TRASH_LABELS):
                            rec["meta"]["tier"] = "spam" if labels & SPAM_LABELS else "deleted"
                        if not takeout and folder:  # no Gmail labels: the folder decides
                            if folder.lower() in SKIP_FOLDERS:
                                rec["meta"]["tier"] = TIER_OF_FOLDER[folder.lower()]
                            if folder.lower() in SENT_FOLDERS or folder.lower() in ("drafts", "outbox"):
                                rec["is_me"], rec["author"] = True, "me"
                            rec["meta"]["folder"] = folder
                        if w.has(rec["id"]):
                            continue
                        w.add(kind="email", **rec)
            elif e.origin.lower().endswith(".olm") and OLM_ATTACHMENT.search(p):
                used.add(p)  # an Outlook message's attachment: named with its message
            elif p.endswith("MyActivity.json") or re.search(r"(watch|search)-history\.json$", p):
                used.add(p)
                try:
                    items = e.json()
                except ValueError:
                    continue
                my_activity(items, W("google_activity"))
            elif p.lower().endswith(".ics"):
                used.add(p)
                calendar(e, W("google_calendar"))
            elif p.lower().endswith(".vcf"):
                used.add(p)
                source = "google_contacts" if TAKEOUT.search(p) or "/Contacts/" in "/" + p else "vcard_contacts"
                w = W(source)
                for d in parse_vcards(vcard_text(e.read())):
                    # A contact with only a company, an address or a number (Google keeps those too) is named by it.
                    name = vcard_name(d) or next((v for k in ("EMAIL", "TEL") for v in d.get(k, []) if v.strip()), "").strip()
                    key = rid(name, d.get("TEL"), d.get("EMAIL"))
                    if name and not (d.get("TEL") or d.get("EMAIL")):
                        # Only a name: two cards are two people unless their company and address are one too.
                        seen, one = named_only.setdefault((source, key), []), rid(name, d.get("ORG"), d.get("ADR"))
                        if one in seen:
                            continue
                        seen.append(one)
                        key = one if len(seen) > 1 else key
                    if not name or w.has(key):
                        continue
                    lines = [name] + [vcard_line(k, v) for k in ("TEL", "EMAIL", "ORG", "TITLE", "BDAY", "ADR", "URL", "NOTE")
                                      for v in d.get(k, []) if v.strip()]
                    w.add(id=key, kind="contact", title=name, text="\n".join(lines))
            elif re.search(r"Chrome/(Browser)?History\.json$", p):
                if chrome_history(e.json(), W("chrome_synced")):
                    used.add(p)
            elif re.search(r"Chrome/(Bookmarks|Reading List)\.html$", p):
                used.add(p)
                chrome_bookmarks(e, W("chrome_synced"))
            elif re.search(r"(^|/)Tasks/[^/]+\.json$", p) and not GP_DIR.search(p):  # not an album named Tasks
                try:
                    d = e.json()
                except ValueError:
                    continue
                if isinstance(d, dict) and (d.get("kind") == "tasks#taskLists" or "items" in d):
                    used.add(p)
                    google_tasks(d, W("google_tasks"))
            elif re.search(r"(^|/)Takeout(?: \d+)?/(Saved|Gespeichert)/[^/]+\.csv$", p):  # Gespeichert: German
                used.add(p)
                google_saved(e, W("google_saved"))
            elif is_keep(p) and p.endswith(".json"):
                used.add(p)
                try:
                    d = e.json()
                except ValueError:
                    continue
                if not isinstance(d, dict):
                    continue
                # A note is the time it was made (a second Takeout has it again, perhaps edited since: the latest edit is
                # kept); its file name is only its title, which another note, or another account's, can have too.
                key = f"keep:{d['createdTimestampUsec']}" if d.get("createdTimestampUsec") else f"keep:{rid(e.origin, p)}"
                edited = lambda n: int(n["userEditedTimestampUsec"]) if str(n.get("userEditedTimestampUsec") or "").isdigit() else 0  # noqa: E731
                if key not in keep or edited(d) > edited(keep[key]):
                    keep[key] = d
            elif TAKEOUT_KEEP.search(p) and p.endswith(".html"):
                # Keep writes each note twice, .json and .html: the JSON is read. Before 2018 there was only the page.
                if keep_twin(e) in keep_json:
                    used.add(p)
                elif (d := keep_page(e))["title"] or d["textContent"]:
                    used.add(p)
                    keep.setdefault(f"keep:{rid(e.origin, p)}", d)
            elif GP_DIR.search(p) and p.endswith(".json"):
                used.add(p)
                try:
                    d = e.json()
                except ValueError:
                    continue
                if not isinstance(d, dict) or "photoTakenTime" not in d:
                    continue
                # A photo is its link (or its name and time): the same one is in "Photos from 2024" and in each of its
                # albums, and in every Takeout since. One record, with every album it's in, and the photo itself.
                key = d.get("url") or rid(d.get("title"), (d.get("photoTakenTime") or {}).get("timestamp"))
                entry = photos.setdefault(key, [d, [], []])
                entry[1].append(PurePosixPath(p).parent.name)
                entry[2].append(p)
            elif p.endswith(("Saved Places.json", "Reviews.json")) or "Labeled places" in p and p.endswith(".json"):
                if maps_places(e, e.json(), W("google_maps_places")):
                    used.add(p)
            elif PurePosixPath(p).name in ("Timeline.json", "location-history.json") or "Semantic Location History" in p:
                if location_history(e.json(), W("location_history")):
                    used.add(p)
            elif what := sniffed(e):
                # Named in another language (or some other way): what's in it says what it is.
                if what == "activity":
                    used.add(p)
                    my_activity(e.json(), W("google_activity"))
                elif what == "activity_page" and (items := activity_page(e)):
                    used.add(p)
                    my_activity(items, W("google_activity"))
                elif what == "chrome" and chrome_history(e.json(), W("chrome_synced")):
                    used.add(p)
                elif what == "bookmarks":
                    used.add(p)
                    chrome_bookmarks(e, W("chrome_synced"))
                elif what == "tasks":
                    used.add(p)
                    google_tasks(e.json(), W("google_tasks"))
                elif what == "places" and maps_places(e, e.json(), W("google_maps_places")):
                    used.add(p)
                elif what == "timeline" and location_history(e.json(), W("location_history")):
                    used.add(p)
        except Exception as x:  # noqa: BLE001 - one file that can't be read stops none of the others
            unreadable(e, x, used)
    for key, d in keep.items():
        items = "\n".join(("[x] " if i.get("isChecked") else "[ ] ") + str(i.get("text") or "")
                          for i in d.get("listContent") or [] if isinstance(i, dict))
        # A link added to a note (Keep shows its preview): its title and address.
        links = [a for a in d.get("annotations") or [] if isinstance(a, dict) and a.get("url")]
        W("google_keep").add(id=key, kind="note", ts=from_unix(d.get("createdTimestampUsec"), "us") or d.get("page_time"),
                             author="me", is_me=True, thread="Keep", thread_name="Google Keep", title=d.get("title") or None,
                             text="\n".join(x for x in (d.get("title"), d.get("textContent"), items,
                                                         *(" ".join(x for x in (a.get("title"), a["url"]) if x) for a in links)) if x),
                             meta={"modified": from_unix(d.get("userEditedTimestampUsec"), "us"),
                                   "labels": [l.get("name") for l in d.get("labels") or [] if isinstance(l, dict)] or None,
                                   **({"links": [a["url"] for a in links]} if links else {}),
                                   **({"archived": True} if d.get("isArchived") else {}),
                                   # in Keep's bin: kept, as mail in the bin is, for searches to leave out
                                   **({"tier": "deleted"} if d.get("isTrashed") else {})})
    for key, (d, albums, paths) in photos.items():
        ts = from_unix((d.get("photoTakenTime") or {}).get("timestamp"))
        # The photo itself goes with its record, in corpus/media/ where other_files kept it (a clone, from a folder):
        # from the first of its sidecars that has it (the same photo in another Takeout isn't kept twice).
        photo_files = google_photos_files(es) if photo_files is None else photo_files
        files = []
        for sp in dict.fromkeys(paths):
            for m in photo_files.get(sp, []):
                try:
                    files.append(save_media(m, MEDIA / leftover_source(m) / m.path, ts))
                except Exception:  # noqa: BLE001 - left to other_files, which fails on it as before (not Gmail with it)
                    continue
                used.add(m.path)
            if files:
                break
        geo = d.get("geoData") or {}
        people = [x.get("name") for x in d.get("people") or [] if isinstance(x, dict) and x.get("name")]
        # Its album: one you made, rather than the folder of its year Takeout puts every photo in.
        albums = list(dict.fromkeys(albums))
        album = next((a for a in albums if not GP_YEAR.fullmatch(a)), albums[0])
        lines = [f"Photo: {d.get('title')}", f"Album: {album}" if len(albums) == 1 else "Albums: " + ", ".join(albums),
                 "People: " + ", ".join(people) if people else "", d.get("description") or ""]
        W("google_photos").add(id=f"photo:{rid(key)}", kind="photo", ts=ts,
                               author="me", is_me=True, thread=album, thread_name=album, title=d.get("title"),
                               participants=people or None, text="\n".join(x for x in lines if x), url=d.get("url"),
                               meta={k: v for k, v in (("lat", geo.get("latitude") or None), ("lon", geo.get("longitude") or None),
                                                       ("albums", albums if len(albums) > 1 else None), ("files", [f for f in files if f] or None)) if v})


def ics_time(v, tzid=None):
    """An iCalendar time, in UTC: in its TZID's zone when it names one, else a floating time (this Mac's clock). A date
    alone (an all-day event) stays a date."""
    v = v.strip()
    try:
        if len(v) == 8:
            return datetime.strptime(v, "%Y%m%d").date().isoformat()
        if v.endswith("Z"):
            return iso(datetime.strptime(v, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc))
        d = datetime.strptime(v[:15], "%Y%m%dT%H%M%S")
    except ValueError:
        return None
    try:
        return iso(d.replace(tzinfo=ZoneInfo(tzid))) if tzid else local_utc(d)
    except (ValueError, KeyError, ZoneInfoNotFoundError):  # a zone named some other way (Outlook's "Pacific Standard Time")
        return local_utc(d)


# A property line: its name, its parameters (a value in quotes can hold ; : and ,), its value.
ICS_LINE = re.compile(r'([^;:]+)((?:;[^=;:]+=(?:"[^"]*"|[^";:]*)(?:,(?:"[^"]*"|[^";:]*))*)*):(.*)', re.S)


def calendar(e, w):
    """An .ics file: one record per event. An alarm's own lines (its text, the address it mails) aren't the event's; an
    event with no UID (made by another app) is its time and title."""
    p = e.path
    body = re.sub(r"\r?\n[ \t]", "", e.text())
    for block in re.findall(r"BEGIN:VEVENT\r?\n(.*?)END:VEVENT", body, re.S):
        block = re.sub(r"BEGIN:VALARM.*?END:VALARM\r?\n?", "", block, flags=re.S)
        props, people, zones = {}, [], {}
        for line in block.splitlines():
            m = ICS_LINE.match(line)
            if not m:
                continue
            name, val = m[1].upper(), m[3]
            params = re.findall(r';([^=;:]+=(?:"[^"]*"|[^";:]*)(?:,(?:"[^"]*"|[^";:]*))*)', m[2])
            val = val.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";")
            if name == "ATTENDEE":
                cn = next((x[3:] for x in params if x.upper().startswith("CN=")), None)
                people.append((cn or val.replace("mailto:", "")).strip('"'))
            else:
                props.setdefault(name, val)
                zones.setdefault(name, next((x[5:].strip('"') for x in params if x.upper().startswith("TZID=")), None))
        start = ics_time(props.get("DTSTART", ""), zones.get("DTSTART"))
        uid = props.get("UID") or rid(p, props.get("SUMMARY"), props.get("DTSTART"))
        key = f"{uid}:{props.get('RECURRENCE-ID') or props.get('DTSTART')}"
        if w.has(key):
            continue
        lines = [props.get("SUMMARY", ""), f"Location: {props['LOCATION']}" if props.get("LOCATION") else "",
                 "Attendees: " + ", ".join(people) if people else "", props.get("DESCRIPTION", "")]
        w.add(id=key, kind="event", ts=start, ts_end=ics_time(props.get("DTEND", ""), zones.get("DTEND")), title=props.get("SUMMARY"),
              text="\n".join(x for x in lines if x), participants=people or None,
              thread=PurePosixPath(p).stem, thread_name=PurePosixPath(p).stem,
              meta={k: v for k, v in (("location", props.get("LOCATION")), ("recurring", "RRULE" in props or None)) if v})


def chrome_history(d, w):
    """Chrome's synced history (Chrome/History.json, BrowserHistory.json since 2023): every visit; a search one's query.
    False for a file that isn't that."""
    items = d.get("Browser History") if isinstance(d, dict) else None
    if not isinstance(items, list):
        return False
    for it in items:
        if not isinstance(it, dict):
            continue
        key = rid(it.get("url"), it.get("time_usec"))
        if w.has(key):
            continue
        tag, q = classify(it.get("url") or "")
        kind = "search" if tag in ("search", "youtube_search") and q else "visit"
        w.add(id=key, kind=kind, ts=from_unix(it.get("time_usec"), "us"), author="me", is_me=True,
              title=q if kind == "search" else it.get("title"), url=it.get("url"),
              text=q if kind == "search" else "\n".join(x for x in (it.get("title"), it.get("url")) if x),
              meta={"tag": tag, "transition": it.get("page_transition")})
    return True


def maps_places(e, d, w):
    """Maps (your places): Saved Places, Reviews and Labeled places, GeoJSON. Since 2023 a place's keys are lower case
    (location.name, google_maps_url, date); before, capitalized (Location.Business Name, Google Maps URL, Published,
    Star Rating, Review Comment). A place Maps no longer has is at 0, 0: no place. False for a file that isn't that."""
    feats = d.get("features") if isinstance(d, dict) else None
    if not isinstance(feats, list):
        return False
    p = e.path
    for f in feats:
        if not isinstance(f, dict):
            continue
        pr = f.get("properties") if isinstance(f.get("properties"), dict) else {}
        loc = pr.get("location") or pr.get("Location") or {}
        loc = loc if isinstance(loc, dict) else {}
        url = pr.get("google_maps_url") or pr.get("Google Maps URL")
        address = loc.get("address") or loc.get("Address") or pr.get("address")
        name = (loc.get("name") or pr.get("Title") or loc.get("Business Name") or pr.get("name") or address
                or classify(url or "")[1] or url)  # a place with only its link: the name in it (?q=…), else the link
        rating = pr.get("five_star_rating_published") or pr.get("Star Rating")
        review = pr.get("review_text_published") or pr.get("Review Comment")
        answers = [f"{q.get('question')}: {q.get('selected_option') or ', '.join(map(str, listish(q.get('selected_options')))) or q.get('text_answer') or q.get('rating') or ''}"
                   for q in listish(pr.get("questions")) if isinstance(q, dict) and q.get("question")]
        coords = (f.get("geometry") if isinstance(f.get("geometry"), dict) else {}).get("coordinates") or [None, None]
        key = rid(p, name, pr.get("date"), coords)
        if not name or w.has(key):
            continue
        lon, lat = (coords + [None, None])[:2] if isinstance(coords, list) else (None, None)
        if not (lon or lat):  # 0, 0: Maps has no place for it
            lon = lat = None
        lines = [name, address or "", f"Rating: {rating}" if rating else "", review or "", *answers, pr.get("Comment") or ""]
        w.add(id=key, kind="place", ts=parse_time(pr.get("date") or pr.get("Published")), author="me", is_me=True,
              thread=PurePosixPath(p).stem, thread_name=PurePosixPath(p).stem, title=name,
              text="\n".join(x for x in lines if x), url=url, meta={k: v for k, v in (("lon", lon), ("lat", lat)) if v is not None})
    return True


def latlng(v):
    """A place in a Timeline export, as it's written: {"latLng": "52.52°, 13.40°"} (Android), "geo:52.52,13.40"
    (iPhone), or {"latitudeE7", "longitudeE7"} (Semantic Location History). As text, or None."""
    if isinstance(v, dict):
        if v.get("latLng"):
            return str(v["latLng"])
        if v.get("latitudeE7") is not None and v.get("longitudeE7") is not None:
            return f"{v['latitudeE7'] / 1e7:.7f}°, {v['longitudeE7'] / 1e7:.7f}°"
        return None
    return str(v) if v else None


def number(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def location_history(d, w):
    """Where you've been, in any of Location History's shapes: the Timeline exported on a phone since 2024 (Android's
    {"semanticSegments": [...]}, the iPhone's list, every value text), and Takeout's Semantic Location History before
    (timelineObjects). A visit is a place_visit, a stretch of travel between two a trip, a place the phone knows you by
    (home, work) a place. The raw points (timelinePath, rawSignals) aren't kept: counted in the manifest's notes.
    False for a file that isn't one of these."""
    segs = d.get("semanticSegments") if isinstance(d, dict) else d
    objs = d.get("timelineObjects") if isinstance(d, dict) else None
    if not isinstance(segs, list) and not isinstance(objs, list):
        return False
    raw = len(listish(d.get("rawSignals"))) if isinstance(d, dict) else 0
    for s in segs if isinstance(segs, list) else []:
        if not isinstance(s, dict):
            continue
        raw += len(listish(s.get("timelinePath")))
        visit, act = s.get("visit"), s.get("activity")
        if isinstance(visit, dict):
            top = visit.get("topCandidate") if isinstance(visit.get("topCandidate"), dict) else {}
            place, where = top.get("placeId") or top.get("placeID"), latlng(top.get("placeLocation"))
            key = rid(s.get("startTime"), place)
            if w.has(key):
                continue
            w.add(id=key, kind="place_visit", ts=parse_time(s.get("startTime")), ts_end=parse_time(s.get("endTime")),
                  author="me", is_me=True, title=top.get("semanticType"),
                  text=f"Visited {top.get('semanticType') or 'place'} at {where}",
                  meta={"place_id": place, "latlng": where, "probability": number(top.get("probability"))})
        elif isinstance(act, dict):
            trip(w, s.get("startTime"), s.get("endTime"), (act.get("topCandidate") or {}).get("type"),
                 number(act.get("distanceMeters")), latlng(act.get("start")), latlng(act.get("end")))
    profile = d.get("userLocationProfile") if isinstance(d, dict) else None
    for f in listish((profile or {}).get("frequentPlaces")) if isinstance(profile, dict) else []:
        if isinstance(f, dict) and (f.get("label") or f.get("placeId")):
            key = f"frequent:{f.get('placeId')}:{f.get('label')}"
            if not w.has(key):
                where = latlng(f.get("placeLocation"))
                w.add(id=key, kind="place", author="me", is_me=True, title=str(f.get("label") or "A place you go often").capitalize(),
                      text=" ".join(x for x in (str(f.get("label") or "A place you go often").capitalize(), "at", where) if x),
                      meta={"place_id": f.get("placeId"), "latlng": where, "frequent": True})
    if raw:
        w.notes["raw_points_not_kept"] = w.notes.get("raw_points_not_kept", 0) + raw
    for obj in objs if isinstance(objs, list) else []:
        if not isinstance(obj, dict):
            continue
        if isinstance(obj.get("activitySegment"), dict):
            a = obj["activitySegment"]
            dur = a.get("duration") or {}
            trip(w, dur.get("startTimestamp") or from_unix(dur.get("startTimestampMs"), "ms"),
                 dur.get("endTimestamp") or from_unix(dur.get("endTimestampMs"), "ms"), a.get("activityType"),
                 number(a.get("distance")), latlng(a.get("startLocation")), latlng(a.get("endLocation")))
        pv = obj.get("placeVisit")
        for v in [pv, *listish((pv or {}).get("childVisits"))] if isinstance(pv, dict) else []:  # a stop inside a visit
            if not isinstance(v, dict):
                continue
            loc, dur = v.get("location") or {}, v.get("duration") or {}
            start = dur.get("startTimestamp") or from_unix(dur.get("startTimestampMs"), "ms")
            key = rid(start, loc.get("placeId"))
            if w.has(key):
                continue
            name = loc.get("name") or loc.get("address") or "place"
            w.add(id=key, kind="place_visit", ts=parse_time(start), ts_end=parse_time(dur.get("endTimestamp")) or from_unix(dur.get("endTimestampMs"), "ms"),
                  author="me", is_me=True, title=name, text="\n".join(x for x in (f"Visited {name}", loc.get("address")) if x),
                  meta={"place_id": loc.get("placeId"), "lat": (loc.get("latitudeE7") or 0) / 1e7 or None,
                        "lon": (loc.get("longitudeE7") or 0) / 1e7 or None, "semantic": loc.get("semanticType")})
    return True


def trip(w, start, end, activity, meters, frm, to):
    key = rid("trip", start, end, frm)
    if w.has(key) or not (start or end):
        return
    how = str(activity or "travel").replace("_", " ").lower()
    w.add(id=key, kind="trip", ts=parse_time(start), ts_end=parse_time(end), author="me", is_me=True, title=how.capitalize(),
          text=f"{how.capitalize()}" + (f", {meters / 1000:.1f} km" if meters else "") + (f", from {frm} to {to}" if frm and to else ""),
          meta={k: v for k, v in (("activity", activity), ("meters", meters), ("from", frm), ("to", to)) if v is not None})


def is_keep(p):
    return "/Keep/" in "/" + p


TAKEOUT_KEEP = re.compile(r"(^|/)Takeout(?: \d+)?/Keep/")


def keep_twin(e):
    """A Keep note's file, less its .json or .html, in its export: its twin has the same, in either part's Takeout folder."""
    return PurePosixPath(takeout_of(e)).parts[0] if e.origin else "", TAKEOUT.sub(r"\1Takeout/", e.path).rsplit(".", 1)[0]


class ClassText(HTMLParser):
    """The text in each element of the given classes (a <br> a new line): Keep's note pages."""

    def __init__(self, classes):
        super().__init__()
        self.classes, self.found, self.open = classes, collections.defaultdict(list), []

    def handle_starttag(self, tag, attrs):
        cls = next((c for c in (dict(attrs).get("class") or "").split() if c in self.classes), None)
        if tag == "br" and self.open:
            self.found[self.open[-1][0]][-1] += "\n"
        elif tag not in ("br", "img", "input", "meta", "link"):
            if cls:
                self.found[cls].append("")
            self.open.append((cls or (self.open[-1][0] if self.open else None), tag))

    def handle_endtag(self, tag):
        if self.open and self.open[-1][1] == tag:
            self.open.pop()

    def handle_data(self, data):
        if self.open and self.open[-1][0]:
            self.found[self.open[-1][0]][-1] += data


def keep_page(e):
    """A Keep note from its page alone (Takeouts before 2018): the same fields its JSON would have."""
    page = ClassText({"heading", "title", "content", "label-name"})
    page.feed(e.text())
    one = lambda c: (page.found.get(c) or [""])[0].strip()  # noqa: E731
    return {"title": one("title"), "textContent": one("content"), "page_time": loose_time(one("heading")),
            "labels": [{"name": x.strip()} for x in page.found.get("label-name", []) if x.strip()]}


class Bookmarks(HTMLParser):
    """A Netscape bookmark file (Chrome's Bookmarks.html and Reading List.html): (folders, title, url, attributes) for
    each link. A folder is an <H3> name followed by a <DL> of what's in it."""

    def __init__(self):
        super().__init__()
        self.folders, self.pending, self.open, self.buf, self.links = [], None, None, [], []

    def handle_starttag(self, tag, attrs):
        if tag in ("h3", "a"):
            self.open, self.buf = (tag, dict(attrs)), []
        elif tag == "dl":
            self.folders.append(self.pending)
            self.pending = None

    def handle_endtag(self, tag):
        if self.open and tag == self.open[0]:
            name = re.sub(r"\s+", " ", "".join(self.buf)).strip()
            if tag == "h3":
                self.pending = name
            else:
                self.links.append(([f for f in self.folders if f], name, self.open[1].get("href"), self.open[1]))
            self.open = None
        elif tag == "dl" and self.folders:
            self.folders.pop()

    def handle_data(self, data):
        if self.open:
            self.buf.append(data)


def chrome_bookmarks(e, w):
    """Chrome's bookmarks and reading list from Takeout: each link with its folder and when it was added."""
    reading = "Reading List" in e.name
    b = Bookmarks()
    b.feed(e.text())
    for folders, title, url, attrs in b.links:
        folder = "Reading list" if reading else " › ".join(folders) or "Bookmarks"
        added = attrs.get("add_date")
        ts = from_unix(int(added)) if str(added or "").isdigit() and int(added) > 0 else None
        key = rid(e.path, folder, url, added)
        if not url or w.has(key):
            continue
        modified = attrs.get("last_modified")
        w.add(id=key, kind="bookmark", ts=ts, author="me", is_me=True, thread=folder, thread_name=folder,
              title=(title or url)[:300], text="\n".join(x for x in (title, url) if x), url=url,
              meta={"folder": folder, "list": "Reading list" if reading else None,
                    "modified": from_unix(int(modified)) if str(modified or "").isdigit() and int(modified) > 0 else None})


def google_tasks(d, w):
    """Google Tasks (Takeout/Tasks/Tasks.json): every list's tasks, with notes, when due and when done. A subtask names
    its parent; a deleted task is kept with meta.tier "deleted"."""
    for lst in d.get("items") or []:
        if not isinstance(lst, dict):
            continue
        name = lst.get("title") or "Tasks"
        for t in lst.get("items") or []:
            if not isinstance(t, dict) or not (t.get("title") or t.get("notes")):
                continue
            key = t.get("id") or rid(name, t.get("title"), t.get("created"))
            if w.has(key):
                continue
            sched = [s for s in t.get("scheduled_time") or [] if isinstance(s, dict) and s.get("start")]
            due = t.get("due") or next((s["start"] for s in sched if s.get("current")), None) or (sched[0]["start"] if sched else None)
            meta = {"completed": t.get("status") == "completed", "completed_at": parse_time(t.get("completed")), "due": parse_time(due),
                    "modified": parse_time(t.get("updated")), "subtask_of": t.get("parent"),
                    "links": [x.get("link") for x in t.get("links") or [] if isinstance(x, dict) and x.get("link")] or None,
                    "tier": "deleted" if t.get("deleted") else None}
            w.add(id=key, kind="reminder", ts=parse_time(t.get("created") or t.get("updated")), author="me", is_me=True,
                  thread=lst.get("id") or name, thread_name=name, title=(t.get("title") or "")[:300] or None,
                  text="\n".join(x for x in (t.get("title"), t.get("notes")) if x), meta={k: v for k, v in meta.items() if v is not None})


def google_saved(e, w):
    """Google Saved (Takeout/Saved/<list>.csv): your Maps lists (Want to go, Favorites, your own) and saved links, one
    row per item: title, note, URL, tags, comment. No dates in the file."""
    lst = PurePosixPath(e.path).stem
    for r in read_csv(e):
        if not ({"Title", "Name"} & set(r)):  # columns named in another language: the title first, the link a link
            vals = [str(v or "").strip() for v in r.values()]
            link = next((v for v in vals if re.match(r"https?://", v)), "")
            r = {"Title": vals[0] if vals and vals[0] != link else "", "URL": link,
                 "Note": "; ".join(v for v in vals[1:] if v and v != link)}
        title, url = (r.get("Title") or r.get("Name") or "").strip(), (r.get("URL") or r.get("Url") or "").strip()
        note, comment, tags = (r.get("Note") or "").strip(), (r.get("Comment") or "").strip(), (r.get("Tags") or "").strip()
        key = rid(e.path, title, url, note)
        if not (title or url) or w.has(key):
            continue
        w.add(id=key, kind="saved", author="me", is_me=True, thread=lst, thread_name=lst, title=(title or url)[:300],
              text="\n".join(x for x in (title, note, comment, f"Tags: {tags}" if tags else "", url) if x), url=url or None,
              meta={"list": lst, "note": note or None, "comment": comment or None, "tags": tags or None,
                    "what": "place" if "google.com/maps" in url or "maps.google" in url else "link"})


# ---------------------------------------------------------------- YouTube (in a Takeout)

YT = "YouTube and YouTube Music/"
YT_DIR = re.compile(r"(^|/)YouTube[^/]*Music/")  # YouTube und YouTube Music/, YouTube y YouTube Music/ (a no-break space)
# Some files' columns in English. Takeout names files and columns in the account's language, the columns in the same
# order: in another language a file is told by what's in it, and read by position.
YT_COLUMNS = {"subscriptions": ["Channel Id", "Channel Url", "Channel Title"],
              "comments": ["Comment ID", "Channel ID", "Comment Create Timestamp", "Price", "Parent Comment ID", "Post ID",
                           "Video ID", "Comment Text"]}
YT_TITLES = {}  # video id -> title, from the watch history google() read: comments and playlists name only ids


def yt_text(cell):
    """YouTube's text cells: JSON segments, {"text": ...} each (a mention or a link to a moment of a video is a segment
    of its own), written one after another without a list's brackets. Their text, joined; anything else as it is."""
    cell = (cell or "").strip()
    if not cell.startswith("{"):
        return cell
    try:
        segs = json.loads(f"[{cell}]")
    except ValueError:
        return cell
    return "".join(str(s.get("text") or "") for s in segs if isinstance(s, dict)).strip()


def yt_url(vid):
    return f"https://www.youtube.com/watch?v={vid}" if vid else None


def takeout_of(e):
    """The export a file is in: its zip, less Takeout's part number (takeout-…-001.zip and -002.zip are one export, and
    so are -001.tgz and -002.tgz)."""
    return re.sub(r"-\d+\.(zip|tgz|tar\.gz|tar)$", "", e.origin or "")


def yt_rows(e, used=None, role=None):
    """A YouTube CSV's rows, by their English column names (by position, in a file in another language). One that can't
    be read is said, and left unread."""
    try:
        rows = read_csv(e)
    except Exception as x:  # noqa: BLE001 - a broken CSV, or a damaged zip member
        if used is not None:
            unreadable(e, x, used)
        return []
    cols = YT_COLUMNS.get(role)
    if cols and rows and cols[0] not in rows[0]:
        rows = [dict(zip(cols, r.values())) for r in rows]
    return rows


def yt_role(e):
    """What a YouTube CSV named in another language holds: your subscriptions (three columns, a channel's link second),
    your comments (eight, the last the text in YouTube's segments); None for any other."""
    try:
        r = csv.reader(io.StringIO(head(e).decode("utf-8-sig", "replace")))
        header, first = next(r, []), next(r, [])
    except Exception:  # noqa: BLE001 - a broken CSV or a damaged zip member: read (and said) as any other
        return None
    if len(header) == len(first) == 3 and "youtube.com/channel/" in first[1]:
        return "subscriptions"
    if len(header) == len(first) == 8 and first[7].lstrip().startswith('{"'):
        return "comments"
    return None


def youtube(es, W, used):
    """YouTube's own files in a Takeout (YouTube and YouTube Music/): your comments and live chat messages, the videos
    you uploaded, your subscriptions and your playlists (Watch later is one), each video added to one a record. Watch
    and search history are google()'s; channel settings and the rest go to the catch-all."""
    # By export and path: a second account's Takeout has the same files at the same paths, and they're its own.
    mine = {(e.origin, e.path): e for e in es if YT_DIR.search(e.path) and e.name.lower().endswith(".csv")}
    if not mine:
        return
    w = W("youtube")
    english = r"/(comments|live chats|subscriptions|playlists|video metadata)/[^/]+\.csv$"
    local = {k: yt_role(e) for k, e in mine.items() if not re.search(english, e.path, re.I)}  # named in another language
    by = lambda rx, role=None: [e for k, e in mine.items() if re.search(rx, k[1], re.I) or role and local.get(k) == role]  # noqa: E731
    uploads, texts, places = {}, {}, {}
    for e in by(r"/video metadata/video texts\.csv$"):
        used.add(e.path)
        for r in yt_rows(e, used):
            texts[r.get("Video ID")] = (yt_text(r.get("Video Title Text Segments 1")), yt_text(r.get("Video Description Text Segments 1")))
    for e in by(r"/video metadata/video recordings\.csv$"):
        used.add(e.path)
        for r in yt_rows(e, used):
            lat, lon = r.get("Video Recording Latitude"), r.get("Video Recording Longitude")
            if lat and lon and (lat, lon) != ("0", "0"):
                places[r.get("Video ID")] = (lat, lon)
    for e in by(r"/video metadata/videos\.csv$"):
        used.add(e.path)
        for r in yt_rows(e, used):
            vid = r.get("Video ID")
            title = yt_text(r.get("Video Title (Original)")) or texts.get(vid, ("", ""))[0]
            desc = yt_text(r.get("Video Description (Original)")) or texts.get(vid, ("", ""))[1]
            tags = [yt_text(v) for k, v in r.items() if k and k.startswith("Tag ") and yt_text(v)]
            key = f"upload:{vid}"
            if not vid or w.has(key):
                continue
            uploads[vid] = title
            ms = r.get("Approx Duration (ms)")
            lat, lon = places.get(vid, (None, None))
            w.add(id=key, kind="post", ts=parse_time(r.get("Video Create Timestamp")), author="me", is_me=True,
                  title=(title or "A video")[:300], text="\n".join(x for x in (title, desc, "Tags: " + ", ".join(tags) if tags else "") if x)
                  or "A video", url=yt_url(vid),
                  meta={k: v for k, v in (("file", "videos.csv"), ("privacy", r.get("Privacy")), ("state", r.get("Video State")),
                                          ("seconds", round(int(ms) / 1000) if str(ms or "").isdigit() else None),
                                          ("category", r.get("Video Category")), ("tags", tags or None),
                                          ("published", parse_time(r.get("Video Publish Timestamp"))), ("lat", lat), ("lon", lon)) if v})
    title_of = lambda vid: uploads.get(vid) or YT_TITLES.get(vid)  # noqa: E731
    for e in by(r"/comments/comments\.csv$", "comments") + by(r"/live chats/live chats\.csv$"):
        used.add(e.path)
        chat = "live chats" in e.path
        for r in yt_rows(e, used, None if chat else "comments"):
            cid = r.get("Live Chat ID" if chat else "Comment ID")
            vid, post = yt_text(r.get("Video ID")), yt_text(r.get("Post ID"))
            text = yt_text(r.get("Live Chat Text" if chat else "Comment Text"))
            key = f"{'chat' if chat else 'comment'}:{cid}"
            if not cid or not text or w.has(key):
                continue
            price = (r.get("Price") or "").strip()
            url = (f"https://www.youtube.com/post/{post}" if post else f"{yt_url(vid)}&lc={cid}" if vid and not chat else yt_url(vid))
            w.add(id=key, kind="comment", ts=parse_time(r.get("Live Chat Create Timestamp" if chat else "Comment Create Timestamp")),
                  author="me", is_me=True, thread=vid or post or None, thread_name=title_of(vid) or None, text=text, url=url,
                  meta={k: v for k, v in (("file", "live chats.csv" if chat else "comments.csv"), ("video", vid or None), ("post", post or None),
                                          ("reply", bool(yt_text(r.get("Parent Comment ID"))) or None),
                                          ("price", price if price not in ("", "0") else None)) if v})
    for e in by(r"/subscriptions/subscriptions\.csv$", "subscriptions"):
        used.add(e.path)
        for r in yt_rows(e, used, "subscriptions"):
            name, cid = (r.get("Channel Title") or "").strip(), r.get("Channel Id") or r.get("Channel ID")
            key = f"subscription:{cid or name}"
            if not (name or cid) or w.has(key):
                continue
            w.add(id=key, kind="subscription", author="me", is_me=True, title=(name or cid)[:300],
                  text=f"Subscribed to {name or cid} on YouTube", url=r.get("Channel Url") or None, meta={"file": "subscriptions.csv"})
    lists = {}  # (export, playlist title) -> id: the files of its videos are named by its title
    for e in by(r"/playlists/playlists\.csv$"):
        used.add(e.path)
        for r in yt_rows(e, used):
            pid, name = r.get("Playlist ID"), yt_text(r.get("Playlist Title (Original)")) or "A playlist"
            lists[takeout_of(e), name] = pid
            key = f"playlist:{pid or name}"
            if w.has(key):
                continue
            w.add(id=key, kind="playlist", ts=parse_time(r.get("Playlist Create Timestamp")), author="me", is_me=True,
                  thread=pid or name, thread_name=name, title=name[:300], text=f"YouTube playlist “{name}”",
                  url=f"https://www.youtube.com/playlist?list={pid}" if pid else None,
                  meta={k: v for k, v in (("file", "playlists.csv"), ("visibility", r.get("Playlist Visibility")),
                                          ("modified", parse_time(r.get("Playlist Update Timestamp")))) if v})
    for e in by(r"/playlists/[^/]+\.csv$"):
        if e.name == "playlists.csv":
            continue
        rows = yt_rows(e, used)
        old = rows and "Playlist Id" in rows[0] and "Video ID" not in rows[0]  # before 2023: a playlist's details, a blank line, its videos
        if old:
            text = e.text()
            head, _, body = text.partition("\n\n")
            info = next(iter(csv.DictReader(io.StringIO(head))), {})
            rows = list(csv.DictReader(io.StringIO(body)))
            name, pid = info.get("Title") or e.name[:-4], info.get("Playlist Id")
        else:
            name = re.sub(r"-videos$", "", PurePosixPath(e.path).stem)
            pid = lists.get((takeout_of(e), name))
        if not rows or not ({"Video ID", "Video Id"} & set(rows[0])):
            continue
        used.add(e.path)
        for i, r in enumerate(rows):
            vid = (r.get("Video ID") or r.get("Video Id") or "").strip()
            key = f"playlist:{pid or name}:{vid}:{i}"
            if not vid or w.has(key):
                continue
            title = title_of(vid)
            w.add(id=key, kind="saved", ts=parse_time(r.get("Playlist Video Creation Timestamp") or r.get("Time Added")), author="me",
                  is_me=True, thread=pid or name, thread_name=name, title=(title or f"A video ({vid})")[:300],
                  text=f"Added to “{name}”: {title or yt_url(vid)}", url=yt_url(vid),
                  meta={"file": e.name, "list": name, "what": "video", "video": vid})


# ---------------------------------------------------------------- Chat apps

# A channel's folder in a Discord package: Messages/c<id>/ (messages/<id>/ before late 2021), named in the account's
# language in some packages since 2025, so a folder of any name holding <id>/channel.json is one too.
DISCORD_CHANNEL = re.compile(r"(^|/)([^/]+)/c?(\d+)/(channel\.json|messages\.json|messages\.csv)$", re.I)
DISCORD_DM, DISCORD_GROUP = ("DM", 1, "1"), ("GROUP_DM", 3, "3")  # a channel's type: its name since 2024, a number before


def discord_time(v):
    """A message's time: with its zone before 2024, in UTC without one since."""
    ts = parse_time(v) if isinstance(v, str) else None
    return ts + "Z" if ts and not ts.endswith("Z") and "T" in ts else ts


def discord(es, W, used):
    """Discord data package: Messages/index.json names channels, Messages/c<id>/{channel.json,messages.json|csv}
    hold only messages I sent. Account/user.json's friends list names DM and group-DM recipients. Each file is read on
    its own: one cut short is listed as not read, and the rest of the package is read."""
    # Every package's names and friends together: two accounts' packages (or two of one account's) each add theirs. And
    # every package's messages of a channel: a package downloaded again ("package (1).zip", which sorts first) has the
    # newer ones, the first the older; ids keep a message in both once.
    names, chans, people, me_ids = {}, collections.defaultdict(lambda: collections.defaultdict(list)), {}, set()
    found = [(e, m) for e in es for m in [DISCORD_CHANNEL.search(e.path)] if m]
    roots = {(e.origin, e.path[:m.end(2)]) for e, m in found
             if m.group(2).lower() == "messages" or (len(m.group(3)) >= 15 and m.group(4).lower() == "channel.json")}
    homes = {(o, r.rpartition("/")[0]) for o, r in roots}  # the package's own folder, where Account/ sits beside Messages/

    def read(e):
        used.add(e.path)
        return guarded(e, used, lambda e: e.json())
    for e in es:
        folder, _, name = e.path.rpartition("/")
        if re.search(r"(^|/)messages/index\.json$", e.path, re.I) or name == "index.json" and (e.origin, folder) in roots:
            d = read(e)
            names.update({str(k): v for k, v in d.items() if isinstance(v, str) and v and v != "None"} if isinstance(d, dict) else {})
        elif re.search(r"(^|/)account/user\.json$", e.path, re.I) or name == "user.json" and (e.origin, folder.rpartition("/")[0]) in homes:
            u = read(e)
            if not isinstance(u, dict):
                continue
            if u.get("id"):
                me_ids.add(str(u["id"]))
            for r in listish(u.get("relationships")):
                user = r.get("user") if isinstance(r, dict) and isinstance(r.get("user"), dict) else {}
                nick = (r.get("nickname") or user.get("global_name") or user.get("username")) if isinstance(r, dict) else None
                if nick:
                    people[str(user.get("id") or r.get("id"))] = str(nick)
    for e, m in found:
        if (e.origin, e.path[:m.end(2)]) in roots:
            chans[m.group(3)][m.group(4).lower()].append(e)
            used.add(e.path)
    for cid, files in chans.items():
        info = {}
        for f in files["channel.json"]:
            d = guarded(f, used, lambda e: e.json())
            info = d if isinstance(d, dict) and d else info
        guild = (info.get("guild") if isinstance(info.get("guild"), dict) else {}).get("name")
        recipients = [str(r) for r in listish(info.get("recipients"))]
        others = [people.get(r) or r for r in recipients if r not in me_ids]
        known = [p for p in others if not p.isdigit()]  # recipients not on my friends list stay as raw ids
        name = names.get(cid)
        if not name or name == "None" or "Unknown Participant" in name:  # the index leaves many DMs unnamed
            who = ", ".join(known) + (f" +{len(others) - len(known)}" if len(others) > len(known) else "") if known else ", ".join(others)
            dm = info.get("type") in DISCORD_DM or info.get("type") not in DISCORD_GROUP and len(recipients) == 2
            name = info.get("name") or ("DM with " if dm else "Group DM with ") + who
            if not others:  # a server's channel, named as the index names one
                name = f"{info['name']} in {guild}" if info.get("name") and guild else info.get("name") or guild or cid
        msgs = []
        for f in files["messages.json"]:
            msgs += [x for x in listish(guarded(f, used, lambda e: e.json())) if isinstance(x, dict)]
        for f in files["messages.csv"]:
            msgs += listish(guarded(f, used, lambda e: list(csv.DictReader(io.StringIO(e.text())))))
        if not msgs:
            continue
        w = W("discord")
        for m in msgs:
            body = m.get("Contents")
            text = ("" if body is None else str(body)) + (f"\n[attachment: {m['Attachments']}]" if m.get("Attachments") else "")
            key = f"{cid}:{m.get('ID')}"
            if not text.strip() or w.has(key):
                continue
            w.add(id=key, kind="message", ts=discord_time(m.get("Timestamp")), author="me", is_me=True, thread=cid,
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
    # Instagram's own posts: media/ since 2024, content/ before
    (r"(media|content)/(posts|archived_posts|stories|reels|profile_photos|other_content|igtv_videos)|your_posts|"
     r"posts_on_other_pages|posts/album/|uncategorized_photos", "post"),
    (r"event_invitations|event_responses", "event"),
    (r"your_places/", "place"),
    (r"interest_categories|your_topics|ads_interests", "inference"),
    # Instagram's profile: personal_information/personal_information/ since 2023, one folder up before
    (r"personal_information/personal_information/(personal_information|profile_changes)|"
     r"(^|/)personal_information/(personal_information|profile_changes)\.json$|instagram_profile_information|"
     r"profile_information/(profile_information|profile_update_history)\.json", "profile"),
)
META_NOBODY = {"facebook user", "instagram user"}  # what a deleted account is called, in every chat it was in
# What advertisers and the services keep about you. Each of these files is one long list (thousands of advertisers
# in one file): kept whole, nothing could count or search it, so each advertiser, category, company and ad is a
# record. kind "advertiser": an advertiser that has you in an audience, and how (meta.how); "inference": something
# a service decided about you (meta.what: interest, category, gender, age, ...); "off_platform": a company that
# told a service what you did in its app or on its website (meta.events); "ad": an ad you were shown.
META_ADS = (r"advertisers_using_your_activity|other_categories_used_to_reach_you|"
            r"your_activity_off_meta_technologies\.json$|ads_and_topics/ads_viewed\.json$")
ADVERTISER_HOW = {
    "list": "uploaded a list (its customers, subscribers or contacts) that you were matched to",
    "activity": "matched you from what you did on its website, in its app or in its store",
    "store": "matched you from a visit to its store",
    "lookalike": "aims its ads at people like those on its lists, and you were counted as one",
    "catalog": "showed you products from its catalog, picked from what you looked at",
    "excluded": "chose not to show you its ads",
}
MEDIA_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".mp4", ".mov", ".m4a", ".aac", ".mp3", ".wav", ".srt")
MEDIA_KIND = {".jpg": "photo", ".jpeg": "photo", ".png": "photo", ".webp": "photo", ".heic": "photo", ".gif": "gif",
              ".mp4": "video", ".mov": "video", ".m4a": "audio_file", ".aac": "audio_file", ".mp3": "audio_file", ".wav": "audio_file"}


def advertiser(w, origin, service, name, how, file):
    name = (name or "").strip()
    key = rid(origin, how, name)
    if name and not w.has(key):
        w.add(id=key, kind="advertiser", author=name, is_me=False, title=name[:300],
              text=f"{service}: {name} {ADVERTISER_HOW[how]}.", meta={"file": file, "how": how, "service": service})


def inference(w, origin, service, value, what, file, text=None, ts=None, extra=None):
    value = (value or "").strip()
    key = rid(origin, what, value)
    if value and not w.has(key):
        w.add(id=key, kind="inference", ts=ts, author=service, is_me=False, title=value[:300],
              text=text or f"{service} decided this about you ({what}): {value}",
              meta={"file": file, "what": what, "service": service, **(extra or {})})


def meta_ads(e, d, w, site):
    """The ads files of a Meta export: who has you on a list, the categories you're reached under, the companies
    that send Meta what you do elsewhere, and the ads you were shown."""
    service = "Facebook" if site == "facebook" else "Instagram"
    stem = PurePosixPath(e.path).stem
    if stem.startswith("advertisers_using"):
        for group in d.get("label_values") or [] if isinstance(d, dict) else []:
            label = fix_meta(group.get("label") or "").lower()
            how = "store" if "store you visited" in label else "activity" if "interaction" in label else "list"
            for v in group.get("vec") or []:
                advertiser(w, e.path, service, fix_meta(str(v.get("value") or "")), how, stem)
    elif stem.startswith("other_categories"):
        for group in d.get("label_values") or [] if isinstance(d, dict) else []:
            for v in group.get("vec") or []:
                name = fix_meta(str(v.get("value") or ""))
                inference(w, e.path, service, name, "category", stem, f"{service} reaches you with ads under the category “{name}”.")
    elif stem.startswith("your_activity_off_meta"):
        for it in d if isinstance(d, list) else []:
            company = fix_meta(it.get("title") or "").strip()
            events = []
            for x in it.get("label_values") or []:
                if x.get("label") != "Events":
                    continue
                for ev in x.get("vec") or []:
                    f = {y.get("label"): y.get("value") if y.get("value") is not None else y.get("timestamp_value") for y in ev.get("dict") or []}
                    events.append({"type": fix_meta(str(f.get("Event") or "")) or None, "ts": meta_time(f.get("Received on"))})
            events.sort(key=lambda x: x["ts"] or "")
            key = rid(e.path, company)
            if not company or w.has(key):
                continue
            types = collections.Counter(x["type"] for x in events if x["type"])
            n = len(events)
            what = ", ".join(f"{t.lower().replace('_', ' ')} ×{c}" for t, c in types.most_common())
            w.add(id=key, kind="off_platform", ts=events[-1]["ts"] if events else None, author=company, is_me=False, title=company[:300],
                  text=f"{company} told {service} what you did in its app or on its website: {n} time{'s' if n != 1 else ''}"
                       + (f" ({what})" if what else "") + ".",
                  meta={"file": stem, "service": service, "events": events})
    elif stem == "ads_viewed":
        for it in d if isinstance(d, list) else []:
            owner = None
            for x in it.get("label_values") or []:
                if x.get("title") == "Owner":
                    inner = next((y for y in x.get("dict") or [] if isinstance(y, dict)), {})
                    owner = inner.get("title") or next((z.get("value") for z in inner.get("dict") or [] if z.get("label") in ("Name", "Username")), None)
            pairs, _uris, times = meta_item(it)
            d2 = dict(pairs)
            owner = fix_meta(owner or d2.get("Brand partner") or "") or None
            ts = meta_time(next((t for t in times if t), None))
            key = rid(e.path, ts, owner, d2.get("URL"))
            if w.has(key):
                continue
            caption = (d2.get("Caption") or "").strip()
            w.add(id=key, kind="ad", ts=ts, author=owner or service, is_me=False, title=(owner or "An ad")[:300],
                  text=f"{service} showed you an ad{f' from {owner}' if owner else ''}" + (f": {caption[:2000]}" if caption else "."),
                  url=d2.get("Ad library public URL") or d2.get("URL"), meta={"file": stem, "service": service})


def meta_item(item):
    """Flatten one item of a Meta export into (label, value) pairs, media uris and unix times. Handles both
    layouts: label_values lists ({label, value | href | timestamp_value | media | dict | vec}), the older
    string_map_data / string_list_data, and plain items like {"name": ..., "timestamp": ...}."""
    pairs, media, times = [], [], []

    def take(label, d):
        d = d if isinstance(d, dict) else {"value": d}
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
                    pairs.append(("Title", fix_meta(str(x["title"]))))
                return
            if "label" in x:
                label = fix_meta(str(x["label"]))
                take(label, x)
                for k in ("media", "dict", "vec"):
                    walk(x.get(k), label)
                return
            for k, v in x.items():
                if k == "string_map_data" and isinstance(v, dict):
                    for lab, d in v.items():
                        take(fix_meta(lab), d)
                elif k == "string_list_data" and isinstance(v, list):
                    for d in v:
                        take(label or "Value", d)
                elif k.endswith("timestamp") and v:  # timestamp, creation_timestamp, an event's start_timestamp
                    times.append(v)
                elif isinstance(v, str) and v and k not in ("fbid", "href"):  # older plain items: {"name": ..., "timestamp": ...}
                    pairs.append((k.replace("_", " ").capitalize(), fix_meta(v)))
                elif isinstance(v, list) and v and all(isinstance(y, str) for y in v):  # plain names: a post's tags, emails
                    pairs.extend((k.replace("_", " ").capitalize(), fix_meta(y)) for y in v if y)
                elif isinstance(v, (list, dict)) and k != "media_metadata":
                    walk(v, label)

    walk(item, None)
    return pairs, media, times


def meta_items(d):
    """The items of a Meta data file. A list is its items. A dict that's only lists holds them ({"comments_v2": [...]}),
    or holds them one level down (Facebook's {"event_responses_v2": {"events_joined": [...], "events_declined": [...]}}):
    every list is read, and when there are several each item says which it's from. A plain name in a list (Facebook's
    ad topics) is an item of its own. Any other dict is one item, or its first list of items as before."""
    if isinstance(d, list):
        lists = [("", d)]
    elif not isinstance(d, dict) or "label_values" in d or "uri" in d:
        return [d]
    else:
        inner = next(iter(d.values()), None)
        holder = inner if len(d) == 1 and isinstance(inner, dict) and inner else d
        if not all(isinstance(v, list) for v in holder.values()):
            return next((v for v in d.values() if isinstance(v, list) and v and isinstance(v[0], dict)), [d])
        lists = [(k, v) for k, v in holder.items() if v]
    several = len(lists) > 1
    return [{**(x if isinstance(x, dict) else {"value": x}), **({"list": k.replace("_", " ")} if several else {})}
            for k, v in lists for x in v if isinstance(x, dict) or isinstance(x, str) and x]


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
        """By the export's own folders first (a Messenger chat's folder can be named after an Instagram account,
        instagramuser_…), then by its zip's or folder's name."""
        low, origin = f"{e.origin}/{e.path}".lower(), (e.origin or "").lower()
        if "your_instagram_activity" in low:
            return "instagram"
        if re.search(r"your_facebook_activity|your_activity_across_facebook", low) or "facebook" in origin and "instagram" not in origin:
            return "facebook"
        return "instagram" if "instagram" in low else "facebook"

    def keep_media(e, uris, ts):
        out = []
        for u in uris:
            if u in media_idx:
                used.add(media_idx[u].path)
                out.append(save_media(media_idx[u], MEDIA / site_of(e) / u, ts))
        return [x for x in out if x]

    def sender_of(m):
        s = fix_meta(m.get("sender_name") or m.get("senderName"))
        return s if isinstance(s, str) else None

    # Chats: messages/<inbox|archived_threads|filtered_threads|message_requests|e2ee_cutover>/<chat>/message_N.json, and
    # any other file under messages/ shaped like one (Messenger's encrypted-chats download may name a chat's file after it).
    named = re.compile(r"(^|/)messages/[^/]+/[^/]+/message_\d+\.json$")
    threads = [e for e in es if named.search(e.path) or e.path not in used and e.path.lower().endswith(".json") and
               re.search(r"(^|/)messages/", e.path) and re.search("instagram|facebook", f"{e.origin}/{e.path}".lower())]
    parsed, names_in, done = [], collections.defaultdict(set), set()
    for e in threads:
        try:
            d = e.json()
        except ValueError:
            continue  # empty or cut short: left unread, so the ledger lists it
        if not isinstance(d, dict) or not (named.search(e.path) or isinstance(d.get("messages"), list) and "participants" in d):
            continue
        used.add(e.path)
        done.add((e.origin, e.path))
        thread = PurePosixPath(e.path).parent.name if named.search(e.path) else PurePosixPath(e.path).stem
        msgs = [m for m in d.get("messages") or [] if isinstance(m, dict)]
        # {"name": ...} each, or plain names (the encrypted-chats download)
        parts = d.get("participants") if isinstance(d.get("participants"), list) else []
        people = [p for p in (fix_meta(x.get("name") if isinstance(x, dict) else x) for x in parts) if isinstance(p, str) and p]
        names_in[thread] |= {n for n in {sender_of(m) for m in msgs} | set(people) if n and n.lower() not in META_NOBODY}
        parsed.append((e, d, thread, msgs, people))
    # You: the name identity.json knows, else whoever is in the most chats (you're in all of them), never a deleted account.
    seen_in = collections.Counter(n for names in names_in.values() for n in names)
    owner = next((n for n in seen_in if is_me_name(n)), None) or \
        (seen_in.most_common(1)[0][0] if len(names_in) > 2 and seen_in else None)
    for e, d, thread, msgs, people in parsed:
        source = "instagram" if site_of(e) == "instagram" else "messenger"
        title = fix_meta(str(d.get("title") or d.get("threadName") or "")) or thread
        w = W(source)
        alike = collections.Counter()
        for m in msgs:
            sender = sender_of(m)
            ts_ms = m.get("timestamp_ms") or m.get("timestamp")
            ts = meta_time(ts_ms)
            text = fix_meta(str(m.get("content") or m.get("text") or ""))
            share = m.get("share") if isinstance(m.get("share"), dict) else {}
            if share.get("link"):
                text += f"\n[shared: {share['link']}]"
            uris = []
            for kind_ in ("photos", "videos", "audio_files", "files", "gifs", "sticker", "media"):
                items = m.get(kind_) or []
                items = [items] if isinstance(items, dict) else items if isinstance(items, list) else []
                if items:
                    # the encrypted-chats download keeps every attachment in media: named by its file's type
                    kinds = [MEDIA_KIND.get(PurePosixPath(str(x.get("uri"))).suffix.lower(), "file") for x in items
                             if isinstance(x, dict)] if kind_ == "media" else [kind_.rstrip("s")]
                    text += "".join(f"\n[{k}]" for k in dict.fromkeys(kinds))
                    uris += [x.get("uri") for x in items if isinstance(x, dict) and x.get("uri")]
            # A message with nothing else to show still happened: a post shared with only its caption, one taken back,
            # one the export keeps nothing of.
            unsent = m.get("is_unsent") or m.get("isUnsent")
            if not text.strip() and share.get("share_text"):
                text = f"[shared: {fix_meta(str(share['share_text']))[:300]}]"
            elif not text.strip() and unsent:
                text = "[unsent]"
            elif not text.strip():
                text = "[no text or attachment in the export]"
            key = rid(thread, ts_ms, sender, text[:50])
            n, alike[key] = alike[key], alike[key] + 1
            if n:  # the same sender, moment and text again in this file: another message (two photos sent at once)
                key = rid(thread, ts_ms, sender, text[:50], n)
            if w.has(key):
                continue  # the same chat in another export
            me = bool(sender) and (sender == owner or is_me_name(sender))
            files = keep_media(e, uris, ts)
            # Reactions on it: who, which, when (Instagram leaves out when on older ones).
            reactions = [{k: v for k, v in (("who", fix_meta(x.get("actor"))), ("reaction", fix_meta(x.get("reaction"))),
                                              ("ts", meta_time(x.get("timestamp")))) if v}
                         for x in (m.get("reactions") if isinstance(m.get("reactions"), list) else []) if isinstance(x, dict)]
            extra = {"files": files or None, "reactions": [x for x in reactions if x] or None,
                     "call_duration": m.get("call_duration"),  # seconds; 0 is a call nobody answered
                     "share_text": fix_meta(share.get("share_text")) or None, "shared_from": fix_meta(share.get("original_content_owner")) or None,
                     "unsent": True if unsent else None}
            w.add(id=key, kind="message", ts=ts, author="me" if me else sender, is_me=me, thread=thread,
                  thread_name=title, participants=people or None, text=text.strip(), meta={k: v for k, v in extra.items() if v is not None})

    # Each export's files by where they are in it: two exports (two accounts, two downloads) have the same paths inside.
    for e in es:  # the ads files, a record per item
        low = f"{e.origin}/{e.path}".lower()
        if (e.origin, e.path) in done or not low.endswith(".json") or not ("instagram" in low or "facebook" in low) or not re.search(META_ADS, e.path.lower()):
            continue
        try:
            d = e.json()
        except ValueError:
            continue
        used.add(e.path)
        done.add((e.origin, e.path))
        try:
            meta_ads(e, d, W(f"{site_of(e)}_activity"), site_of(e))
        except ValueError:
            continue

    for e in es:
        low = f"{e.origin}/{e.path}".lower()
        if (e.origin, e.path) in done or not low.endswith(".json") or not ("instagram" in low or "facebook" in low):
            continue
        if re.search(META_SKIP, e.path.lower()) or re.search(META_SECURITY, e.path.lower()):
            continue
        kind = next((k for pat, k in META_FILES if re.search(pat, e.path.lower())), "record")
        try:
            d = e.json()
        except ValueError:
            continue  # empty or cut short: left unread, so the ledger lists it
        used.add(e.path)
        done.add((e.origin, e.path))
        site, label = site_of(e), PurePosixPath(e.path).stem
        w = W(f"{site}_activity")
        for it in meta_items(d):
            pairs, uris, times = meta_item(it)
            if not pairs and not uris:
                continue
            t = next((x for x in times if x), None)
            ts = meta_time(t)
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
                  meta={"file": label, "files": keep_media(e, uris, ts) or None,
                        **({"what": "see less" if "see_less" in label else "interest", "service": site.title()} if kind == "inference" else {})})


def ytd(e):
    t = e.text()
    return json.loads(t[t.index("=") + 1:])


# Posts: tweets.js (tweet.js in 2019; tweets-part1.js ... in a big archive), deleted-tweets.js, community-tweet.js, and
# before 2018 ("Grailbird") a file a month, data/js/tweets/YYYY_MM.js. Media folders, by their names then and now.
X_POSTS = re.compile(r"data/(deleted-|community-)?tweets?(-part\d+)?\.js$|(^|/)data/js/tweets/\d{4}_\d{2}\.js$")
X_MEDIA = re.compile(r"data/(tweets?_media|deleted_tweets_media|community_tweet_media|direct_messages?_media|direct_messages?_group_media)/(\d+)-[^/]+$")
X_TIME = ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%d %H:%M:%S %z")  # since 2019; Grailbird's


def x_text(t):
    """A post's text as it reads on X: its t.co links as where they lead (entities), and &amp; &lt; &gt;, which the
    archive writes for & < >, as the characters. A Grailbird retweet has the whole of what it retweeted."""
    text = t.get("full_text") or t.get("text")
    rt = t.get("retweeted_status") if isinstance(t.get("retweeted_status"), dict) else None
    if rt and (rt.get("full_text") or rt.get("text")) and isinstance(rt.get("user"), dict) and isinstance(rt["user"].get("screen_name"), str):
        return f"RT @{rt['user']['screen_name']}: {x_text(rt)}"
    if not isinstance(text, str):
        return None
    ents = t.get("entities") if isinstance(t.get("entities"), dict) else {}
    for u in listish(ents.get("urls")) + listish(ents.get("media")):
        if isinstance(u, dict) and isinstance(u.get("url"), str) and u.get("url") and isinstance(u.get("expanded_url"), str):
            text = text.replace(u["url"], u["expanded_url"])
    return html.unescape(text)


def x_versions(posts):
    """Each version of an edited post is a post of its own, edit_info naming them all (editTweetIds): version id ->
    (the first version's id, the latest version's in the archive), for posts with more than one."""
    ids = {str(t.get("id_str") or t.get("id")) for t in posts}
    out = {}
    for t in posts:
        info = t.get("edit_info") if isinstance(t.get("edit_info"), dict) else {}
        init = info.get("initial") if isinstance(info.get("initial"), dict) else {}
        edit = info.get("edit") if isinstance(info.get("edit"), dict) else {}
        ctl = edit.get("editControlInitial") if isinstance(edit.get("editControlInitial"), dict) else {}
        vs = [str(v) for v in listish(init.get("editTweetIds") or ctl.get("editTweetIds"))]
        here = [v for v in vs if v in ids]
        if len(here) > 1:
            latest = max(here, key=lambda v: (len(v), v))  # ids grow with time
            out.update((v, (vs[0], latest)) for v in vs)
    return out


def x_archive(es, W, used):
    """X archive (data/*.js). Tweet and DM media (data/tweets_media/<tweet id>-*, data/direct_messages(_group)_media/
    <message id>-*) are copied to corpus/media/x/ and listed in meta.files. Every file is read on its own: one that's
    cut short or damaged is listed as not read, and the rest of the archive is read."""
    # Whose archive it is. Without it each of your messages would be taken for someone else's, so an account.js that
    # doesn't say fails the whole archive, as before: the app says it couldn't read it, and keeps what it had.
    acct = next((e for e in es if e.path.endswith("data/account.js")), None)
    me_id = str(ytd(acct)[0]["account"]["accountId"]) if acct else None
    media = collections.defaultdict(list)
    for e in es:
        m = X_MEDIA.search(e.path)
        if m:
            media[m.group(2)].append(e)

    def files_for(item_id, ts):
        out = []
        for e in media.get(str(item_id), []):
            used.add(e.path)
            out.append(save_media(e, MEDIA / "x" / PurePosixPath(e.path).name, ts))
        return [x for x in out if x] or None
    notes = x_notes(es, used)
    posts = []  # (file, its posts): every file's first, as an edit's versions can be in two parts of tweets.js
    for e in es:
        if X_POSTS.search(e.path):
            used.add(e.path)
            items = guarded(e, used, ytd)
            posts.append((e, [t for t in (i.get("tweet", i) if isinstance(i, dict) else None for i in listish(items)) if isinstance(t, dict)]))
        elif re.search(r"(^|/)data/js/tweet_index\.js$", e.path):
            used.add(e.path)  # Grailbird's list of its month files
    versions = x_versions([t for _, ts in posts for t in ts])
    who = x_people([t for _, ts in posts for t in ts])
    for e, items in posts:
        guarded(e, used, x_posts, items, W("x"), notes, versions, files_for)
    for e in es:
        if e.name == "tweets.csv" and not in_takeout(e):
            guarded(e, used, x_tweets_csv, W, used)
    for e in es:
        p = e.path
        if re.search(r"data/direct-messages(-group)?\.js$", p):
            used.add(p)
            guarded(e, used, x_messages, W("x"), me_id, files_for, who)
        elif re.search(r"data/grok-chat-item(-part\d+)?\.js$", p):
            used.add(p)
            guarded(e, used, x_grok, W("x"))
        elif p.endswith("data/personalization.js"):
            used.add(p)
            guarded(e, used, x_personalization, W("x"))
        elif re.search(r"data/ad-(impressions|engagements)\.js$", p):
            used.add(p)
            guarded(e, used, x_ads_seen, W("x"))
        elif re.search(r"data/ad-(online|mobile)-conversions-(attributed|unattributed)\.js$", p):
            used.add(p)
            guarded(e, used, x_conversions, W("x"))
        elif p.endswith("data/like.js"):
            used.add(p)
            guarded(e, used, x_likes, W("x"))
        elif re.search(r"data/(follower|following)\.js$", p):
            used.add(p)
            guarded(e, used, x_follows, W("x"))
    # Long posts tweets.js has no cut-down copy of: kept as posts of their own.
    for n in [n for ns in notes.values() for n in ns if not n["used"]]:
        w = W("x")
        key = f"note:{n['id']}"
        if w.has(key):
            continue
        w.add(id=key, kind="post", ts=n["ts"], author="me", is_me=True, text=n["text"],
              meta={k: v for k, v in (("long", True), ("deleted", n["deleted"])) if v})


def x_posts(e, items, w, notes, versions, files_for):
    p = e.path
    for t in items:
        pid = t.get("id_str") or t.get("id")
        if pid is None or w.has(pid):
            continue
        pid = str(pid)
        ts = parse_time(t.get("created_at"), *X_TIME)
        note = x_note_for(notes, ts, t.get("full_text"))
        deleted = parse_time(t.get("deleted_at"), *X_TIME) or t.get("deleted_at")
        text = note["text"] if note else x_text(t)
        rt = re.match(r"RT @(\w+):", text or "")
        first, latest = versions.get(pid, (None, None))
        replaced = latest if latest and latest != pid else None  # an earlier version of an edited post
        w.add(id=pid, kind="post", ts=ts, author="me", is_me=True, text=text, url=f"https://x.com/i/status/{pid}",
              meta={k: v for k, v in (("reply_to", t.get("in_reply_to_screen_name")),
                                      ("likes", t.get("favorite_count")), ("retweets", t.get("retweet_count")),
                                      ("retweet_of", rt.group(1) if rt else None),
                                      ("long", True if note else None),  # the whole of a long post, from note-tweet.js
                                      ("community", True if "community-tweet" in p else None),
                                      ("edit_of", first if first and first != pid else None), ("replaced_by", replaced),
                                      ("deleted", deleted),  # and left out where deleted mail is
                                      ("tier", "deleted" if deleted or "deleted-tweets" in p else "superseded" if replaced else None),
                                      ("files", files_for(pid, ts))) if v})


def x_tweets_csv(e, W, used):
    """Grailbird's tweets.csv: its tweets again, the same as its month files (kept once, by id). Its t.co links are
    expanded from expanded_urls when there are as many of each."""
    rows = read_csv(e)
    if not rows or not {"tweet_id", "timestamp", "text"} <= set(rows[0]):
        return
    used.add(e.path)
    w = W("x")
    for r in rows:
        if not r.get("tweet_id") or w.has(r["tweet_id"]):
            continue
        text, links = r.get("text") or "", [u for u in (r.get("expanded_urls") or "").split(",") if u]
        short = re.findall(r"https?://t\.co/\w+", text)
        if links and len(links) == len(short):
            for s, u in zip(short, links):
                text = text.replace(s, u, 1)
        w.add(id=r["tweet_id"], kind="post", ts=parse_time(r.get("timestamp"), *X_TIME), author="me", is_me=True, text=html.unescape(text),
              url=f"https://x.com/i/status/{r['tweet_id']}", meta={k: v for k, v in (("reply_to_id", r.get("in_reply_to_status_id")),) if v})


def x_people(posts):
    """Account id -> a name, from your own posts: whom they mention (display name) and reply to (@handle). DMs name
    people by account id alone; these are the names to give them."""
    names = {}
    for t in posts:
        for u in listish((t.get("entities") or {}).get("user_mentions") if isinstance(t.get("entities"), dict) else None):
            if isinstance(u, dict) and u.get("id_str") and (u.get("name") or u.get("screen_name")):
                names[str(u["id_str"])] = u.get("name") or f"@{u['screen_name']}"
    for t in posts:
        uid, handle = t.get("in_reply_to_user_id_str"), t.get("in_reply_to_screen_name")
        if uid and handle and str(uid) not in names:
            names[str(uid)] = f"@{handle}"
    return names


def x_messages(e, w, me_id, files_for, who=None):
    who = who or {}
    for conv in listish(ytd(e)):
        c = conv.get("dmConversation") if isinstance(conv, dict) and isinstance(conv.get("dmConversation"), dict) else {}
        msgs = [m for m in listish(c.get("messages")) if isinstance(m, dict)]
        # A group's name is the last one it was given (conversationNameUpdate); else its id, as before.
        names = sorted(((u.get("createdAt") or "", u.get("name")) for m in msgs
                        for u in [m.get("conversationNameUpdate")] if isinstance(u, dict) and u.get("name")), key=lambda x: x[0])
        # Everyone in it but you, by name where your posts give one (else their account id, as before). A one-on-one
        # conversation is named for the other person.
        ids = [str(x) for m in msgs for mc in [m.get("messageCreate")] if isinstance(mc, dict)
               for x in (mc.get("senderId"), mc.get("recipientId")) if x is not None]
        direct = re.fullmatch(r"(\d+)-(\d+)", str(c.get("conversationId") or ""))
        if direct:
            ids += list(direct.groups())
        others = list(dict.fromkeys(i for i in ids if i and i != me_id))
        people = ", ".join(who.get(i, i) for i in others) or None
        name = names[-1][1] if names else who.get(others[0]) if direct and len(others) == 1 and others[0] in who else c.get("conversationId")
        for m in msgs:
            mc = m.get("messageCreate")
            if not isinstance(mc, dict) or not mc.get("id") or w.has(mc.get("id")):
                continue
            me = me_id is not None and str(mc.get("senderId")) == me_id
            ts = parse_time(mc.get("createdAt"))
            text = mc.get("text")
            for u in listish(mc.get("urls")):  # t.co links, as where they lead
                if isinstance(text, str) and isinstance(u, dict) and isinstance(u.get("url"), str) and u.get("url") and isinstance(u.get("expanded"), str):
                    text = text.replace(u["url"], u["expanded"])
            w.add(id=mc.get("id"), kind="message", ts=ts,
                  author="me" if me else who.get(str(mc.get("senderId")), mc.get("senderId")), is_me=me, thread=c.get("conversationId"),
                  thread_name=name, participants=people, text=text,
                  meta={k: v for k, v in (("files", files_for(mc.get("id"), ts)),
                                          ("sender_id", None if me else mc.get("senderId"))) if v})


def x_likes(e, w):
    """like.js: each post you liked; one whose text the archive doesn't have (deleted since, or private) is kept by its
    link."""
    for item in listish(ytd(e)):
        l = item.get("like") if isinstance(item, dict) and isinstance(item.get("like"), dict) else {}
        key = f"like:{l.get('tweetId')}"
        if not l.get("tweetId") or w.has(key):
            continue
        w.add(id=key, kind="reaction", author="me", is_me=True, text=l.get("fullText") or "[liked post]", url=l.get("expandedUrl"),
              meta={"reaction": "liked"})


def x_follows(e, w):
    """follower.js and following.js: the accounts that follow you and that you follow, by id (the archive has no names)."""
    them = PurePosixPath(e.path).stem == "follower"
    for item in listish(ytd(e)):
        f = item.get("follower" if them else "following") if isinstance(item, dict) else None
        if not isinstance(f, dict) or not f.get("accountId"):
            continue
        acct = str(f["accountId"])
        key = f"{'follower' if them else 'following'}:{acct}"
        if w.has(key):
            continue
        w.add(id=key, kind="follow", author=acct if them else "me", is_me=not them, title=acct,
              text=f"The X account {acct} follows you" if them else f"You follow the X account {acct}", url=f.get("userLink"),
              meta={"what": "follower" if them else "following", "account": acct})


def x_notes(es, used):
    """Long posts (data/note-tweet.js; deleted-note-tweet.js for deleted ones): their whole text, which tweets.js cuts
    at 280 characters. By the second they were made, so x_note_for can find each one's post."""
    out = collections.defaultdict(list)
    for e in es:
        m = re.search(r"data/(deleted-)?note-tweet(-part\d+)?\.js$", e.path)
        if not m:
            continue
        used.add(e.path)
        for item in listish(guarded(e, used, ytd)):
            n = item.get("noteTweet") if isinstance(item, dict) and isinstance(item.get("noteTweet"), dict) else {}
            ts, text = parse_time(n.get("createdAt")), (n.get("core") if isinstance(n.get("core"), dict) else {}).get("text")
            if ts and isinstance(text, str) and text:
                out[ts[:19]].append({"id": n.get("noteTweetId"), "text": text, "ts": ts, "used": False,
                                     "deleted": parse_time(n.get("deletedAt")) or (True if m.group(1) else None)})
    return out


def x_note_for(notes, ts, text):
    """The long post a tweets.js post is the start of: made the same second, and its text starts the same way."""
    if not ts or not notes.get(ts[:19]):
        return None
    flat_ = lambda s: re.sub(r"\s+", " ", html.unescape(s or "")).strip()  # noqa: E731
    start = re.sub(r"\s*(https://t\.co/\S+|…)\s*$", "", flat_(text))[:40]
    for n in notes[ts[:19]]:
        if not n["used"] and start and flat_(n["text"]).startswith(start):
            n["used"] = True
            return n
    return None


def x_grok(e, w):
    """Grok chats (data/grok-chat-item.js): one item a turn, yours or Grok's. A chat has no title: it's named by its
    first prompt."""
    items = [i.get("grokChatItem") or {} for i in ytd(e)]
    me = lambda g: str((g.get("sender") or {}).get("name") or "").lower() == "user"  # noqa: E731
    first = {}
    for g in sorted(items, key=lambda g: g.get("createdAt") or ""):
        if me(g) and g.get("message"):
            first.setdefault(g.get("chatId"), re.sub(r"\s+", " ", g["message"]).strip())
    for g in items:
        key = f"grok:{g.get('chatId')}:{g.get('createdAt')}:{'me' if me(g) else 'grok'}"
        if not g.get("message") or w.has(key):
            continue
        name = first.get(g.get("chatId")) or "Grok"
        w.add(id=key, kind="ai_turn", ts=parse_time(g.get("createdAt")), author="me" if me(g) else "grok", is_me=me(g),
              thread=f"grok:{g.get('chatId')}", thread_name=name if len(name) <= 80 else name[:79].rstrip() + "…", text=g["message"],
              meta={"tool": "grok", "product": "Grok", "mode": (g.get("grokMode") or {}).get("name")})


def x_personalization(e, w):
    """What X decided about you (data/personalization.js): interests, gender and age, languages, shows, where you
    are, and the advertisers that have you in their audiences."""
    for item in ytd(e):
        p = item.get("p13nData") or {}
        demo = p.get("demographics") or {}
        g = (demo.get("genderInfo") or {}).get("gender")
        inference(w, e.path, "X", g, "gender", "personalization", f"X guessed your gender: {g}")
        age = p.get("inferredAgeInfo") or {}
        for a in age.get("age") or []:
            inference(w, e.path, "X", a, "age", "personalization", f"X guessed your age: {a}")
        for lang in demo.get("languages") or []:
            inference(w, e.path, "X", lang.get("language"), "language", "personalization", f"X thinks you speak {lang.get('language')}",
                      extra={"turned_off": True} if lang.get("isDisabled") else None)
        ints = p.get("interests") or {}
        for i in ints.get("interests") or []:
            inference(w, e.path, "X", i.get("name"), "interest", "personalization", f"X thinks you're interested in {i.get('name')}",
                      extra={"turned_off": True} if i.get("isDisabled") else None)
        for i in ints.get("partnerInterests") or []:
            name = i.get("name") if isinstance(i, dict) else str(i)
            inference(w, e.path, "X", name, "partner interest", "personalization", f"X's partners think you're interested in {name}")
        aud = ints.get("audienceAndAdvertisers") or {}
        for how, k in (("list", "advertisers"), ("lookalike", "lookalikeAdvertisers"), ("catalog", "catalogAudienceAdvertisers"),
                       ("excluded", "doNotReachAdvertisers")):
            for a in aud.get(k) or []:
                advertiser(w, e.path, "X", a if isinstance(a, str) else (a or {}).get("name"), how, "personalization")
        if str(aud.get("numAudiences") or "0").isdigit() and int(aud.get("numAudiences") or 0):
            n = int(aud["numAudiences"])
            inference(w, e.path, "X", f"{n:,} audiences", "audiences", "personalization", f"Advertisers have put you in {n:,} audiences on X.")
        for show in ints.get("shows") or []:
            inference(w, e.path, "X", show, "show", "personalization", f"X thinks you watch {show}")
        for loc in p.get("locationHistory") or []:
            inference(w, e.path, "X", loc, "location", "personalization", f"X thinks you've been in {loc}")


def x_ads_seen(e, w):
    """Ads X showed you (data/ad-impressions.js) or you engaged with (ad-engagements.js), with why: the targeting
    that matched you."""
    for item in ytd(e):
        u = (item.get("ad") or {}).get("adsUserData") or {}
        shown = [(x, None) for x in (u.get("adImpressions") or {}).get("impressions") or []]
        shown += [(x.get("impressionAttributes") or {}, x.get("engagementAttributes")) for x in (u.get("adEngagements") or {}).get("engagements") or []]
        for imp, engaged in shown:
            who = (imp.get("advertiserInfo") or {}).get("advertiserName")
            why = [f"{c.get('targetingType')}: {c.get('targetingValue')}" if c.get("targetingValue") else str(c.get("targetingType"))
                   for c in imp.get("matchedTargetingCriteria") or [] if c.get("targetingType")]
            ts = parse_time(imp.get("impressionTime"))
            key = rid(e.path, ts, who, imp.get("displayLocation"))
            if w.has(key):
                continue
            text = f"X showed you an ad{f' from {who}' if who else ''}" + (f", because of {'; '.join(why)}" if why else "") + "."
            tweet = (imp.get("promotedTweetInfo") or {}).get("tweetText")
            w.add(id=key, kind="ad", ts=ts, author=who or "X", is_me=False, title=(who or "An ad")[:300],
                  text=text + (f"\n{tweet}" if tweet else ""),
                  meta={"file": PurePosixPath(e.path).stem, "service": "X", "why": why or None,
                        "engaged": [x.get("engagementType") for x in engaged or []] or None})


def x_conversions(e, w):
    """Advertisers that told X you visited their site or used their app after seeing (or not) their ad."""
    for item in ytd(e):
        u = (item.get("ad") or {}).get("adsUserData") or {}
        for group in u.values():
            for c in (group or {}).get("conversions") or [] if isinstance(group, dict) else []:
                who = (c.get("advertiserInfo") or {}).get("advertiserName") or "An advertiser"
                ts = parse_time(c.get("conversionTime"))
                kind_ = c.get("attributedConversionType") or c.get("eventType") or "visit"
                key = rid(e.path, ts, who, kind_)
                if w.has(key):
                    continue
                url = c.get("conversionUrl") or None
                w.add(id=key, kind="off_platform", ts=ts, author=who, is_me=False, title=who[:300],
                      text=f"{who} told X you {'visited its site' if 'site' in kind_.lower() else 'used its app' if 'session' in kind_.lower() else kind_.lower()}"
                           + (f" ({c.get('conversionPlatform')})" if c.get("conversionPlatform") else "") + ".",
                      url=url if url and url.startswith("http") else None,
                      meta={"file": PurePosixPath(e.path).stem, "service": "X", "events": [{"type": kind_, "ts": ts}]})


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
LINKEDIN_DAY = ("%d %b %Y", "%m/%d/%Y", "%m/%d/%y", "%b %d, %Y")  # Connected On: "01 Jan 2024"; "01/15/2024" in some guides
LINKEDIN_TIME = ("%b %Y", "%Y/%m/%d %H:%M:%S UTC", "%m/%d/%y, %I:%M %p", "%a %b %d %H:%M:%S UTC %Y", "%Y")


def linkedin_targeting(e, w):
    """What LinkedIn lets advertisers reach you by (Ad_Targeting.csv): one row, each column a list ("Member
    Interests", "Buyer Groups", "High Value Audience Segments", ...) of values separated by ";"."""
    rows = list(csv.reader(io.StringIO(after_notes(e.text().lstrip("\ufeff")))))
    for row in rows[1:2]:
        for col, cell in zip(rows[0], row):
            col = col.strip()
            for v in (cell or "").split(";"):
                v = v.strip()
                if v and v != "N/A":
                    inference(w, e.path, "LinkedIn", v, col, "ad_targeting.csv", f"LinkedIn lets advertisers reach you by {col}: {v}")


def linkedin_rows(e, n, w):
    """One record per row, keeping every non-empty column (csv.reader, since some files repeat column names)."""
    if n == "ad_targeting.csv":
        return linkedin_targeting(e, w)
    kind, title_cols, time_col = LINKEDIN_FILES[n]
    text = after_notes(e.text().lstrip("﻿"))
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
        if n == "inferences_about_you.csv":  # "Inferred gender: Female", "Career inferences: Human resources professional"
            typ, value = d.get("Type of inference") or "", d.get("Inference") or ""
            title = typ if value.lower() in ("", "yes", "true") else f"{typ}: {value}"
            inference(w, e.path, "LinkedIn", title, d.get("Category") or "inference", n,
                      f"LinkedIn inferred this about you: {typ}: {value or 'yes'}." + (f" {d['Description']}" if d.get("Description") else ""))
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
        except (csv.Error, UnicodeDecodeError, *DAMAGED):  # a damaged one is left to the ledger, as not read
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
                    w.add(id=key, kind="contact", ts=parse_time(r.get("Connected On"), *LINKEDIN_DAY), title=name,
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
            guarded(e, used, linkedin_rows, n, W("linkedin"))
        elif {"subreddit", "body"} <= cols or {"from", "to", "subject", "body"} <= cols:
            used.add(e.path)
            reddit_writing(e, n, cols, rows, W("reddit"))
        elif n in REDDIT_HEADERS and any(x.origin == e.origin and x.name.lower() == REDDIT_HEADERS[n]
                                         and posixpath.dirname(x.path) == posixpath.dirname(e.path) for x in es):
            used.add(e.path)  # the rows of the file beside it, without what they say: read there
        elif {"message_id", "username", "message", "channel_url"} <= cols:
            used.add(e.path)
            reddit_chats(rows, W("reddit"))
        elif n in REDDIT_FILES and (cols == {"subreddit"} or "reddit" in f"{e.origin}/{e.path}".lower()
                                    or any("reddit.com" in (r.get("permalink") or "") for r in rows[:5])):
            used.add(e.path)
            reddit_rows(n, rows, W("reddit"))


# Reddit's files of things you did without writing anything: file -> (kind, what it's about). No dates in them.
REDDIT_FILES = {"post_votes.csv": ("vote", "post"), "comment_votes.csv": ("vote", "comment"), "saved_posts.csv": ("saved", "post"),
                "saved_comments.csv": ("saved", "comment"), "subscribed_subreddits.csv": ("subscription", "subreddit")}


# Reddit's files that are another one without its bodies: read from that one.
REDDIT_HEADERS = {"comment_headers.csv": "comments.csv", "post_headers.csv": "posts.csv", "message_headers.csv": "messages.csv",
                  "messages_archive_headers.csv": "messages_archive.csv"}
REDDIT_GONE = {"[deleted]", "[removed]", "[deleted by user]"}  # what's left of something deleted, by you or a moderator


def reddit_user(name):
    """A username as Reddit's files write it: "u/ada_l", "/u/ada_l" or "ada_l"."""
    return re.sub(r"^/?u/", "", (name or "").strip()) or None


def reddit_url(link):
    """A link in a Reddit file, whole: messages_archive.csv writes them with one slash (https:/www.reddit.com/...)."""
    return re.sub(r"^(https?):/(?!/)", r"\1://", link) if link else None


def reddit_writing(e, n, cols, rows, w):
    """What you wrote: posts.csv, comments.csv, drafts.csv (never posted), and private messages (messages.csv and
    messages_archive.csv, which can hold the same ones). A row cut short has None for what's missing. A link post's
    link is part of its text; what was deleted is kept, tagged as deleted mail is."""
    for r in rows:
        body = r.get("body") or ""
        key = r.get("id") or rid(e.path, r.get("date"), body[:40])
        if w.has(key):
            continue
        ts = parse_time(r.get("date") or r.get("created"))
        if "from" in cols:
            sender = reddit_user(r.get("from"))
            me = is_me_name(sender)
            w.add(id=key, kind="message", ts=ts, author="me" if me else sender, is_me=me, thread=r.get("thread_id"),
                  thread_name=r.get("subject"), title=r.get("subject"), text=body, url=reddit_url(r.get("permalink")),
                  meta={k: v for k, v in (("to", reddit_user(r.get("to"))), ("tier", "deleted" if body.strip() in REDDIT_GONE else None)) if v})
            continue
        sub, title = (r.get("subreddit") or "").strip() or None, r.get("title") or None
        page = reddit_url(r.get("permalink"))
        link = reddit_url(r.get("url")) if r.get("url") and reddit_url(r.get("url")) != page else None
        gone = body.strip() in REDDIT_GONE and (not title or title.strip() in REDDIT_GONE)
        what = "draft" if n == "drafts.csv" else "post" if "title" in cols else "comment"
        w.add(id=key, kind="post", ts=ts, author="me", is_me=True, thread=sub,
              thread_name=(f"u/{sub[2:]}" if sub.startswith("u_") else f"r/{sub}") if sub else None, title=title,
              text="\n".join(x for x in (title, body, link) if x) or page, url=page or link,
              meta={k: v for k, v in (("type", what), ("link", link), ("parent", r.get("parent")), ("post", reddit_url(r.get("link"))),
                                      ("tier", "deleted" if gone else "unsent" if what == "draft" else None)) if v})


def reddit_link(permalink):
    """(subreddit, a title in words) from a Reddit link: .../r/<sub>/comments/<id>/<title_in_the_link>/..."""
    m = re.search(r"/r/([^/]+)/(?:comments/[^/]+/([^/?#]*))?", permalink or "")
    return (m.group(1), (m.group(2) or "").replace("_", " ").strip() or None) if m else (None, None)


def reddit_rows(n, rows, w):
    kind, what = REDDIT_FILES[n]
    for r in rows:
        if kind == "subscription":
            sub = (r.get("subreddit") or "").strip()
            key = f"subscription:{sub}"
            if sub and not w.has(key):
                w.add(id=key, kind="subscription", author="me", is_me=True, thread=sub, thread_name=f"r/{sub}", title=f"r/{sub}",
                      text=f"Subscribed to r/{sub}", url=f"https://www.reddit.com/r/{sub}/", meta={"file": n})
            continue
        link = r.get("permalink") or ""
        sub, words = reddit_link(link)
        key = f"{n}:{r.get('id') or link}"
        if not (r.get("id") or link) or w.has(key):
            continue
        vote = (r.get("direction") or "").strip().lower()
        did = {"up": "upvoted", "down": "downvoted"}.get(vote, "took back a vote on") if kind == "vote" else "saved"
        w.add(id=key, kind=kind, author="me", is_me=True, thread=sub, thread_name=f"r/{sub}" if sub else None,
              title=(words or link or r.get("id"))[:300],
              text=f"You {did} a {what}" + (f" in r/{sub}" if sub else "") + (f": {words}" if words else "") + (f"\n{link}" if link else ""),
              url=link or None, meta={k: v for k, v in (("file", n), ("on", what), ("vote", vote if kind == "vote" else None)) if v})


def reddit_chats(rows, w):
    """Reddit Chat (chat_history.csv): both sides of every chat, a row a message. A chat without a name is named
    after the others in it."""
    people = collections.defaultdict(set)
    for r in rows:
        if r.get("username"):
            people[r.get("channel_url")].add(r["username"])
    # The export's owner is in every one of their chats: when who you said you are names none of the people here, the
    # one name two or more chats all share is yours.
    everyone = set().union(*people.values()) if people else set()
    common = set.intersection(*people.values()) if len(people) > 1 and not any(map(is_me_name, everyone)) else set()
    owner = next(iter(common)) if len(common) == 1 else None
    mine = lambda name: is_me_name(name) or (owner is not None and name == owner)  # noqa: E731
    for r in rows:
        ch, sender = r.get("channel_url"), r.get("username")
        key = r.get("message_id") or rid(ch, r.get("created_at"), sender, (r.get("message") or "")[:40])
        if not (r.get("message") or "").strip() or w.has(key):
            continue
        me = mine(sender)
        others = sorted(p for p in people[ch] if not mine(p))
        w.add(id=key, kind="message", ts=parse_time(r.get("created_at")), author="me" if me else sender, is_me=me, thread=ch,
              thread_name=r.get("channel_name") or ", ".join(others) or ch, participants=sorted(people[ch]) or None,
              text=r.get("message"), meta={k: v for k, v in (("subreddit", r.get("subreddit")), ("type", r.get("conversation_type")),
                                                             ("reply_to", r.get("thread_parent_message_id"))) if v})


# ---------------------------------------------------------------- Media, transcripts, other chats

# Spotify's plays. Extended streaming history: Streaming_History_Audio_<years>_N.json and Streaming_History_Video_<years>.json
# since 2023, endsong_N.json (and endvideo.json) before. Account data's last year: StreamingHistory_music_N.json and
# _podcast_N.json since 2023, StreamingHistoryN.json before.
SPOTIFY_EXTENDED = re.compile(r"Streaming_History.*\.json$|(endsong|endvideo)(_\d+)?\.json$")
SPOTIFY_ACCOUNT_PLAYS = re.compile(r"StreamingHistory.*\.json$")


def spotify(es, W, used):
    """Spotify's two downloads, which come separately: Extended streaming history (Streaming_History_*.json, every
    play) and Account data (the last year's plays in StreamingHistory*.json, playlists, your library, searches, and
    what Spotify inferred about you). With both, the last year's plays are in each, timed differently (Account data's to
    the minute, when the play ended): up to Extended history's last play they're read from it only, which has every one.
    Each file is read on its own: one cut short is listed as not read, and the rest is read."""
    plays = [e for e in es if SPOTIFY_EXTENDED.match(e.name) or SPOTIFY_ACCOUNT_PLAYS.match(e.name)]
    read, last = {id(e) for e in plays}, None
    for e in sorted(plays, key=lambda e: not SPOTIFY_EXTENDED.match(e.name)):  # Extended history first
        used.add(e.path)
        extended = bool(SPOTIFY_EXTENDED.match(e.name))
        end = guarded(e, used, spotify_plays, W("spotify"), None if extended else last)
        if extended and end and (last is None or end > last):
            last = end
    for e in es:
        n = e.name
        account = "spotify" in f"{e.origin}/{e.path}".lower() and n.endswith(".json")
        if id(e) in read:
            continue
        elif account and re.fullmatch(r"Playlist\d*\.json", n):
            used.add(e.path)
            guarded(e, used, spotify_playlists, W("spotify"))
        elif account and n == "YourLibrary.json":
            used.add(e.path)
            guarded(e, used, spotify_library, W("spotify"))
        elif account and n == "SearchQueries.json":
            used.add(e.path)
            guarded(e, used, spotify_searches, W("spotify"))
        elif account and n in ("Inferences.json", "Marquee.json"):
            used.add(e.path)
            guarded(e, used, spotify_inferences, W("spotify"))


def spotify_searches(e, w):
    for it in listish(e.json()):
        q = (it.get("searchQuery") or "").strip() if isinstance(it, dict) and isinstance(it.get("searchQuery"), str) else ""
        ts = parse_time(re.sub(r"\[.*\]$", "", str(it.get("searchTime") or ""))) if q else None
        key = rid("search", ts, q)
        if not q or w.has(key):
            continue
        w.add(id=key, kind="search", ts=ts, author="me", is_me=True, title=q[:300], text=q,
              meta={k: v for k, v in (("product", "Spotify"), ("platform", it.get("platform")),
                                      ("opened", it.get("searchInteractionURIs") or None)) if v})


def spotify_plays(e, w, after=None):
    """Each play of a song, an episode or an audiobook (only those after `after`, if given): the time of the last one.
    A podcast's episode is by its show, not an artist (meta.show), so it isn't counted as a song."""
    last = None
    for it in listish(e.json()):
        if not isinstance(it, dict):
            continue
        ms = number(it.get("ms_played", it.get("msPlayed", 0))) or 0
        book, chapter = it.get("audiobook_title"), it.get("audiobook_chapter_title")
        song = it.get("master_metadata_track_name") or it.get("trackName")
        episode = it.get("episode_name") or it.get("episodeName")
        track = song or episode or (f"{book} — {chapter}" if book and chapter and chapter != book else book or chapter)
        what = "song" if song else "episode" if episode else "audiobook" if track else None
        artist = (it.get("master_metadata_album_artist_name") or it.get("artistName")) if song else None
        show = (it.get("episode_show_name") or it.get("podcastName")) if what == "episode" else None
        end = it.get("endTime")
        ts = parse_time(it.get("ts")) or (parse_time(end + "+00:00", "%Y-%m-%d %H:%M%z") if isinstance(end, str) else None)
        key = rid(ts, track, int(ms) if ms == int(ms) else ms)
        if ts and (last is None or ts > last):
            last = ts
        if ms < 10_000 or not track or w.has(key) or (after and ts and ts <= after):
            continue
        album = it.get("master_metadata_album_album_name")
        # Where it was played (country), why it stopped, shuffle and private sessions: Extended history only. Its IP
        # address and device ids stay out.
        w.add(id=key, kind="media", ts=ts, author="me", is_me=True, title=str(track),
              text=" — ".join(str(x) for x in (track, artist or show, album) if x)
                   + {"audiobook": " (Spotify audiobook)", "episode": " (Spotify podcast)"}.get(what, " (Spotify)"),
              meta={k: v for k, v in (("artist", artist), ("show", show), ("album", album), ("audiobook", book), ("what", what),
                                      ("seconds", round(ms / 1000)), ("skipped", it.get("skipped")), ("platform", it.get("platform")),
                                      ("conn_country", it.get("conn_country")), ("reason_end", it.get("reason_end")),
                                      ("shuffle", it.get("shuffle")), ("incognito_mode", it.get("incognito_mode"))) if v})
    return last


def spotify_uri(uri):
    m = re.fullmatch(r"spotify:(track|episode|album|artist|show|playlist|audiobook|chapter):(\w+)", uri or "")
    return f"https://open.spotify.com/{m.group(1)}/{m.group(2)}" if m else None


def spotify_playlists(e, w):
    """Playlist1.json, Playlist2.json...: each playlist, and each thing on it with the day it was added."""
    d = e.json()
    for i, pl in enumerate((d or {}).get("playlists") or [] if isinstance(d, dict) else []):
        name = pl.get("name") or "A playlist"
        pid = rid(e.path, i, name)
        items = pl.get("items") or []
        if not w.has(pid):
            w.add(id=pid, kind="playlist", author="me", is_me=True, thread=pid, thread_name=name, title=name[:300],
                  text="\n".join(x for x in (f"Spotify playlist “{name}”", pl.get("description")) if x),
                  meta={k: v for k, v in (("modified", parse_time(pl.get("lastModifiedDate"))), ("items", len(items)),
                                          ("followers", pl.get("numberOfFollowers")),
                                          ("collaborators", pl.get("collaborators") or None)) if v})
        for j, it in enumerate(items):
            if not isinstance(it, dict):
                continue
            t, ep, book, local = (it.get(k) or {} for k in ("track", "episode", "audiobook", "localTrack"))
            title = t.get("trackName") or ep.get("episodeName") or book.get("audiobookName") or book.get("name") or local.get("uri")
            by = t.get("artistName") or ep.get("showName")
            uri = t.get("trackUri") or ep.get("episodeUri") or book.get("audiobookUri") or local.get("uri")
            key = f"{pid}:{j}"
            if not title or w.has(key):
                continue
            what = "song" if t else "episode" if ep else "audiobook" if book else "file"
            w.add(id=key, kind="saved", ts=parse_time(it.get("addedDate")), author="me", is_me=True, thread=pid, thread_name=name,
                  title=title[:300], text=" — ".join(x for x in (title, by, t.get("albumName")) if x) + f" (on “{name}”)",
                  url=spotify_uri(uri), meta={k: v for k, v in (("list", name), ("what", what), ("artist", by),
                                                                ("album", t.get("albumName")), ("uri", uri)) if v})


# YourLibrary.json's lists: key -> (kind, what, how it's said)
SPOTIFY_LIBRARY = {"tracks": ("saved", "song", "Liked"), "albums": ("saved", "album", "Saved"), "episodes": ("saved", "episode", "Saved"),
                   "artists": ("follow", "artist", "Followed"), "shows": ("subscription", "show", "Followed"),
                   "audiobooks": ("saved", "audiobook", "Saved"), "bannedTracks": ("saved", "song", "Hid"),
                   "bannedArtists": ("saved", "artist", "Hid")}


def spotify_library(e, w):
    """YourLibrary.json: liked songs, saved albums and episodes, artists and shows you follow, and what you hid."""
    d = e.json()
    for k, items in d.items() if isinstance(d, dict) else []:
        kind, what, verb = SPOTIFY_LIBRARY.get(k, ("saved", re.sub(r"s$", "", k), "Saved"))
        for it in items if isinstance(items, list) else []:
            if not isinstance(it, dict):
                continue
            name = it.get("track") or it.get("album") or it.get("name") or it.get("title")
            by = it.get("artist") or it.get("publisher") or it.get("show")
            key = rid(k, it.get("uri"), name, by)
            if not name or w.has(key):
                continue
            w.add(id=key, kind=kind, author="me", is_me=True, title=str(name)[:300],
                  text=f"{verb} on Spotify: " + " — ".join(str(x) for x in (name, by, it.get("album") if it.get("track") else None) if x),
                  url=spotify_uri(it.get("uri")),
                  meta={x: v for x, v in (("file", "YourLibrary.json"), ("list", k), ("what", what), ("artist", by),
                                          ("hidden", True if k.startswith("banned") else None), ("uri", it.get("uri"))) if v})


def spotify_inferences(e, w):
    """What Spotify decided about you: the ad segments it put you in (Inferences.json; "3P" ones come from its data
    partners), and the kind of listener you are of each artist, which artists can buy ads to reach (Marquee.json)."""
    d = e.json()
    if e.name == "Inferences.json":
        for raw in (d or {}).get("inferences") or [] if isinstance(d, dict) else []:
            raw = str(raw)
            value = re.sub(r"^(\d?P_)?(Custom_)?", "", raw).replace("_", " ").strip() or raw
            partner = raw.startswith("3P")
            inference(w, e.path, "Spotify", value, "segment", e.name,
                      f"Spotify put you in the ad segment “{value}”" + (" (from its data partners)" if partner else "") + ".",
                      extra={"raw": raw, **({"partner": True} if partner else {})})
    else:
        for it in d if isinstance(d, list) else []:
            if not isinstance(it, dict):
                continue
            artist, seg = (it.get("artistName") or "").strip(), (it.get("segment") or "").strip()
            if artist and seg:
                inference(w, e.path, "Spotify", f"{artist}: {seg}", "artist listener", e.name,
                          f"Spotify counts you among {artist}'s “{seg}”, a group the artist can reach with ads (Marquee).",
                          extra={"artist": artist, "segment": seg})


# A line of an exported chat that starts a message: its date and time as the phone's language and clock write them, in
# brackets on an iPhone ("[1/2/24, 3:04:05 PM] Bea: hi"), before " - " on Android ("1/2/24, 3:04 PM - Bea: hi"). The
# date 1/2/24, 02/01/2024, 02.01.24, 2024-01-02 or 2024. 01. 02.; the time 3:04 PM, 15:04, 15.04.05, 3:04 p. m. or
# 오후 3:04:05; older French Android puts "à" between them, Finnish "klo". Then who wrote it and what, or (Android) a
# line WhatsApp wrote itself.
WA_DATE = r"(\d{1,4}[./-]\s?\d{1,2}[./-]\s?\d{1,4})\.?"
WA_CLOCK = r"((?:[上下]午|午[前後]|오[전후])?\s?\d{1,2}[:.]\d{2}(?:[:.]\d{2})?(?:\s?[AaPp]\.?\s?[Mm]\.?)?)"
WA = [re.compile(rf"\[{WA_DATE},?\s+(?:(?:à|klo)\s+)?{WA_CLOCK}\]\s(.*)$"),
      re.compile(rf"{WA_DATE},?\s+(?:(?:à|klo)\s+)?{WA_CLOCK}\s[-–]\s(.*)$")]
LRM = "\u200e"  # the left-to-right mark an iPhone writes before its own lines and media: "Bea: <LRM>image omitted"
# Lines WhatsApp writes itself: the notice each chat starts with (in a few languages), and a group's changes, which an
# iPhone writes under the group's name (after an LRM) and Android without a name.
WA_NOTICE = re.compile(
    r"(Messages and calls are end-to-end encrypted|Messages (to this|you send to this) (group|chat)|"
    r"Your security code with .* changed|.*'s security code changed|This chat is with a business account|"
    r"Nachrichten und Anrufe sind Ende-zu-Ende-verschlüsselt|Los mensajes y las llamadas están cifrados de extremo a extremo|"
    r"Les messages et les appels sont chiffrés de bout en bout|As mensagens e as chamadas são protegidas com a criptografia|"
    r"I messaggi e le chiamate sono crittografati end-to-end|Berichten en gesprekken zijn end-to-end versleuteld)")
WA_EVENT = re.compile(
    r"(You|[^:\n]{1,80}?) (created group|created this group|added|removed|left|joined using|joined from the community|"
    r"changed the (subject|group|settings)|changed this group's|deleted this group's|changed their phone number|"
    r"changed to \+|turned (on|off) disappearing|set disappearing|now an admin|no longer an admin|reset this group's|"
    r"pinned a message|was added|were added|joined|blocked this contact|unblocked this contact)\b")
WA_DELETED = re.compile(r"(This message was deleted|You deleted this message|This message was deleted by admin .*|"
                        r"Diese Nachricht wurde gelöscht|Du hast diese Nachricht gelöscht|Se eliminó este mensaje|"
                        r"Eliminaste este mensaje|Ce message a été supprimé|Vous avez supprimé ce message|Mensagem apagada|"
                        r"Você apagou esta mensagem|Questo messaggio è stato eliminato|Hai eliminato questo messaggio)\.?$")
WA_EDITED = re.compile(r"\s*\u200e?<(This message was edited|Diese Nachricht wurde bearbeitet|Se editó este mensaje|"
                       r"Ce message a été modifié|Esta mensagem foi editada|Questo messaggio è stato modificato)>$")
# A file a chat exported with its media names: an iPhone's "<attached: 00000012-PHOTO-2024-01-02-15-04-05.jpg>" (before
# 2017 "2015-08-04-PHOTO-00004762.jpg <attached>"), Android's "IMG-20240102-WA0001.jpg (file attached)"; and in other
# languages.
WA_FILE = re.compile(r"<(?:attached|Anhang): ([^>\n]+)>|^(\S[^\n<]*?\.\w{1,5}) (?:<attached>|\((?:file attached|Datei angehängt|"
                     r"archivo adjunto|fichier joint|arquivo anexado|ficheiro anexado|file allegato|bestand bijgevoegd)\))", re.M)
# The chat's name in its file's: "WhatsApp Chat - Bea.zip" (iPhone), "WhatsApp Chat with Bea.txt" (Android), and in
# other languages; " (1)" after a name is the same chat downloaded again.
WA_NAME = re.compile(r"(?:WhatsApp[ -]Chat (?:with |- |mit )|WhatsApp-chat met |Chat de WhatsApp con |Discussion WhatsApp avec |"
                     r"Conversa (?:do|no) WhatsApp com |Chat WhatsApp con |Chat di WhatsApp con |Чат WhatsApp с (?:контактом )?)"
                     r"([^/]+?)(?: \(\d+\))?(?:\.zip|\.txt)?(?:/|$)", re.I)


def wa_match(line):
    """(date, time, the rest, from an iPhone?) of a line that starts a message, or None for a line going on the one
    before."""
    line = line.replace("\u202f", " ").lstrip("\ufeff" + LRM)
    for ios, rx in zip((True, False), WA):
        m = rx.match(line)
        if m:
            return m.group(1), m.group(2), m.group(3), ios
    return None


def local_utc(d):
    """A time written without a zone, as the clock on this Mac showed it (an exported chat, a floating calendar event):
    in UTC, as every other record's is (as leftover_time reads one)."""
    return iso(d.astimezone(timezone.utc)) if d else None


def wa_numbers(d):
    return [x.strip() for x in re.split(r"[./-]", d.strip())]


def wa_dayfirst(dates):
    """Whether a chat writes its dates day first (02/01/2024, the 2nd of January): a first number over 12 says so, a
    second one over 12 says not, dots always are; else the reading in which the messages go forward in time."""
    parts = [p for p in map(wa_numbers, dates) if len(p) == 3 and len(p[0]) <= 2 and all(x.isdigit() for x in p)]
    if not parts:
        return False
    if any(int(p[0]) > 12 for p in parts):
        return True
    if any(int(p[1]) > 12 for p in parts):
        return False
    if any("." in d for d in dates):
        return True

    def backwards(dayfirst):
        days = [(int(y), int(m), int(dd)) for p in parts for dd, m, y in [p if dayfirst else (p[1], p[0], p[2])]]
        return sum(a > b for a, b in zip(days, days[1:]))
    return backwards(True) < backwards(False)


def wa_time(d, t, dayfirst):
    """The export's local date and time (no zone in it), or None."""
    parts = wa_numbers(d)
    c = re.fullmatch(r"([上下]午|午[前後]|오[전후])?\s?(\d{1,2})[:.](\d{2})(?:[:.](\d{2}))?(?:\s?([AaPp])\.?\s?[Mm]\.?)?",
                     t.replace("\u202f", " ").replace("\xa0", " ").strip())
    if len(parts) != 3 or not all(x.isdigit() for x in parts) or not c:
        return None
    if len(parts[0]) == 4:
        y, m, dd = parts
    elif dayfirst:
        dd, m, y = parts
    else:
        m, dd, y = parts
    y = int(y) + (2000 if int(y) < 100 else 0)
    h = int(c.group(2))
    pm, am = c.group(5) in ("P", "p") or c.group(1) in ("下午", "午後", "오후"), c.group(5) in ("A", "a") or c.group(1) in ("上午", "午前", "오전")
    if pm or am:
        h = h % 12 + (12 if pm else 0)
    try:
        return datetime(y, int(m), int(dd), h, int(c.group(3)), int(c.group(4) or 0))
    except ValueError:
        return None


def wa_thread(e):
    """A chat's name, from its export's: else a _chat.txt's folder or zip, else the file's own name."""
    m = WA_NAME.search(e.origin + "/" + e.path)
    if m:
        return m.group(1)
    if e.name.lower() != "_chat.txt":
        return PurePosixPath(e.name).stem
    up = PurePosixPath(e.path).parent.name or PurePosixPath(e.origin).name
    return re.sub(r"(?: \(\d+\))?\.zip$", "", up, flags=re.I) or e.name


def wa_senders(heads):
    """How each line's rest splits into who wrote it and what: a name can have ": " in it ("Ana: Work: Dune"). An
    iPhone puts an LRM after the name on its own lines and media, which says where the name ends; else a name is the
    longer one when every line (three or more) of the shorter one goes on the same way."""
    sure = {r[:r.find(": " + LRM)] for _, _, r, ios in heads if ios and 0 < r.find(": " + LRM) <= 80}
    longer = collections.defaultdict(list)
    for _, _, r, _ in heads:
        i = r.find(": ")
        if 0 < i <= 80:
            j = r.find(": ", i + 2)
            longer[r[:i]].append(r[:j] if i < j <= 80 else None)
    longer = {k: v[0] for k, v in longer.items() if len(v) >= 3 and v[0] and v.count(v[0]) == len(v)}
    sure |= {v for k, v in longer.items() if k not in sure}
    colons = collections.defaultdict(list)  # a name with ": " in it, by what comes before its first one
    for name in sorted(sure, key=len, reverse=True):
        if ": " in name:
            colons[name[:name.find(": ")]].append(name)

    def split(rest):
        i = rest.find(": " + LRM)
        if 0 < i <= 80:
            return rest[:i], rest[i + 2:]
        i = rest.find(": ")
        if not 0 < i <= 80 or "\n" in rest[:i]:
            return None, rest
        name = next((n for n in colons.get(rest[:i], ()) if rest.startswith(n + ": ")), rest[:i])
        return name, rest[len(name) + 2:]
    return split


def whatsapp(es, W, used):
    """Exported chats (WhatsApp > a chat > Export chat), every one: each zip holds a _chat.txt, so an export is told
    apart by its archive and its path in it. A chat exported again ("WhatsApp Chat - Alice (1).zip") is the same chat:
    its thread is named without the " (1)", and a message's id is a hash of who sent it, when and what it said (and how
    many times before in that chat), so a message in both exports is kept once. The times are this Mac's clock's,
    written without a zone: kept in UTC. Lines WhatsApp wrote itself (the encryption notice, a group's changes) are
    events, not anyone's messages; a chat exported with its media has each file go with its message."""
    claimed, read = set(used), set()  # what another parser read, and the exports read here
    here = collections.defaultdict(dict)  # (export, folder) -> file name -> entry: a chat's media are beside it
    for e in es:
        here[(e.origin, posixpath.dirname(e.path))][e.name] = e
    for e in es:
        if not e.name.lower().endswith(".txt") or e.path in claimed or (e.origin, e.path) in read or e.size > 200 * 2**20:
            continue
        try:
            lines = e.text().splitlines()
        except DAMAGED as x:  # any .txt is looked at, a damaged one in a Takeout's Drive too
            unreadable(e, x, used)
            continue
        # A chat: three of its first lines start a message with a name, or it's named as an export is and starts with one
        # (a chat of two messages; one whose first message is a long one).
        first = next((l for l in lines if l.strip()), "")
        named = e.name.lower() == "_chat.txt" or "whatsapp" in f"{e.origin}/{e.path}".lower()
        # (Slack's export of one member as text writes "[2020-04-20 13:47:27] <jjordan> text": not a chat of WhatsApp's.)
        if sum(1 for l in lines[:200] if (h := wa_match(l)) and ": " in h[2] and not SLACK_LINE.match(l)) < 3 and \
                not (named and wa_match(first)):
            continue
        read.add((e.origin, e.path))
        used.add(e.path)
        thread = wa_thread(e)
        heads = []
        for l in lines:
            h = wa_match(l)
            if h:
                heads.append(list(h))
            elif heads:
                heads[-1][2] += "\n" + l
        dayfirst = wa_dayfirst([d for d, *_ in heads])
        split = wa_senders(heads)
        msgs = []
        for d, t, rest, ios in heads:
            sender, body = (None, rest) if not ios and (": " not in rest or WA_EVENT.match(rest)) else split(rest)
            plain = body.replace(LRM, "").strip()
            event = sender is None or WA_NOTICE.match(plain) or ios and body.startswith(LRM) and WA_EVENT.match(plain)
            msgs.append((d, t, None if event else sender.replace(LRM, "").strip(), plain, bool(event)))
        people = sorted({s for _, _, s, _, event in msgs if not event})
        folder = here[(e.origin, posixpath.dirname(e.path))]
        w = W("whatsapp_export")
        times = collections.Counter()
        for d, t, sender, text, event in msgs:
            me = is_me_name(sender)
            when = wa_time(d, t, dayfirst)
            edited = WA_EDITED.search(text)
            text = text[:edited.start()].rstrip() if edited else text
            mark = (sender, when.isoformat() if when else f"{d} {t}", text)
            times[mark] += 1
            key = f"{thread}:{rid(*mark)}" + (f"#{times[mark]}" if times[mark] > 1 else "")
            names = [a or b for a, b in WA_FILE.findall(text)] if not event else []
            media = [f for f in (folder.get(n.strip()) for n in names) if f and f is not e]
            used.update(f.path for f in media)  # its own, not other_files'
            if w.has(key):
                continue  # in an export of this chat read already
            dest = MEDIA / "whatsapp_export" / re.sub(r"[/:\\]", "-", thread)
            files = [x for x in (save_media(f, dest / f.name, local_utc(when)) for f in media) if x]
            meta = {"tier": "deleted" if not event and WA_DELETED.match(text) else None, "edited": True if edited else None,
                    "attachments": names or None, "files": files or None}
            w.add(id=key, kind="event" if event else "message", ts=local_utc(when), author=None if event else "me" if me else sender,
                  is_me=None if event else me, thread=thread, thread_name=thread, participants=people, text=text,
                  meta={k: v for k, v in meta.items() if v})


SLACK_DAY = re.compile(r"(^|/)[^/]+/\d{4}-\d{2}-\d{2}\.json$")  # <conversation>/<YYYY-MM-DD>.json
SLACK_USERS = ("users.json", "org_users.json")  # an Enterprise Grid org's export has org_users.json
# The conversations an export lists: what each is. A DM's folder is its id (D…), a group DM's its name (mpdm-a--b-1).
SLACK_LISTS = {"channels.json": "channel", "groups.json": "private channel", "dms.json": "dm", "mpims.json": "group dm"}
SLACK_SKIP = {"channel_join", "channel_leave", "group_join", "group_leave"}  # who came and went: the lists say who's in it
SLACK_EVENTS = {"channel_topic", "channel_purpose", "channel_name", "channel_archive", "channel_unarchive", "group_topic",
                "group_purpose", "group_name", "group_archive", "group_unarchive", "pinned_item", "unpinned_item",
                "channel_convert_to_private", "channel_convert_to_public", "reminder_add", "bot_add", "bot_remove"}
# Slack's export of one member's conversations as text (an Enterprise org's owner makes it): channels/<name>.txt and
# dms/<people>.txt, a line a message.
SLACK_LINE = re.compile(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] <([^<>\n]{1,80})> ?(.*)$")


TELEGRAM_GROUPS = {"private_group", "private_supergroup", "public_supergroup", "private_channel", "public_channel"}


def telegram_text(t):
    """A message's text: a string, or a list of strings and entities ({type, text}), as Telegram writes it."""
    if isinstance(t, str):
        return t
    return "".join(x if isinstance(x, str) else str(x.get("text") or "") if isinstance(x, dict) else "" for x in listish(t))


def telegram(es, W, used):
    """Telegram Desktop's export, as JSON (result.json): every chat (chats.list, and left_chats) or one chat's history,
    each message's sender, the message it replies to (reply_to_message_id, in the same chat) and what it said, the
    reactions on it (each person's, from reactions[].recent; past what's listed, by count), when it was edited, what
    came with it (copied out, like other exports' attachments); service messages (joins, renames, calls) as events."""
    by_path = {e.path: e for e in es}
    for e in es:
        if e.name != "result.json" or e.path in used:
            continue
        d = guarded(e, used, lambda e: e.json())
        if not isinstance(d, dict):
            continue
        chats = [c for k in ("chats", "left_chats") for c in listish((d.get(k) or {}).get("list") if isinstance(d.get(k), dict) else None)]
        if not chats and isinstance(d.get("messages"), list):
            chats = [d]  # one chat's export
        chats = [c for c in chats if isinstance(c, dict) and isinstance(c.get("messages"), list)]
        if not chats:
            continue
        used.add(e.path)
        me = (d.get("personal_information") or {}) if isinstance(d.get("personal_information"), dict) else {}
        me_id = f"user{me['user_id']}" if me.get("user_id") else None
        folder = posixpath.dirname(e.path)
        w = W("telegram")
        for c in chats:
            cid = str(c.get("id") or c.get("name") or "chat")
            group = c.get("type") in TELEGRAM_GROUPS
            said = {}
            people = sorted({str(m.get("from")) for m in c["messages"] if isinstance(m, dict) and m.get("from") and m.get("type") != "service"
                             and not ((me_id and m.get("from_id") == me_id) or is_me_name(m.get("from")))})
            for m in c["messages"]:
                if not isinstance(m, dict) or m.get("id") is None:
                    continue
                mine = (me_id is not None and m.get("from_id") == me_id) or (c.get("type") == "saved_messages")
                author = "me" if mine or is_me_name(m.get("from") or m.get("actor")) else m.get("from") or m.get("actor") or c.get("name")
                ts = from_unix(number(m.get("date_unixtime"))) or m.get("date")
                text = telegram_text(m.get("text"))
                files = []
                for k in ("photo", "file", "thumbnail"):
                    rel = m.get(k)
                    if isinstance(rel, str) and not rel.startswith("(") and k != "thumbnail":
                        f = by_path.get(posixpath.join(folder, rel) if folder else rel)
                        if f:
                            used.add(f.path)
                            saved = save_media(f, MEDIA / "telegram" / f.path, ts)
                            if saved:
                                files.append(saved)
                        what = m.get("media_type") or ("photo" if k == "photo" else "file")
                        text = "\n".join(x for x in (text, f"[{what.replace('_', ' ')}: {posixpath.basename(rel)}]") if x)
                if m.get("sticker_emoji") and not text:
                    text = f"[sticker {m['sticker_emoji']}]"
                if isinstance(m.get("poll"), dict):
                    text = f"[poll] {m['poll'].get('question') or ''}: " + " / ".join(str(a.get("text")) for a in listish(m["poll"].get("answers")) if isinstance(a, dict))
                key = f"{cid}:{m['id']}"
                said[m["id"]] = text
                reactions = []
                for r in listish(m.get("reactions")):
                    if not isinstance(r, dict):
                        continue
                    shown = r.get("emoji") or ("custom emoji" if r.get("type") == "custom_emoji" else "paid" if r.get("type") == "paid" else None)
                    recent = [x for x in listish(r.get("recent")) if isinstance(x, dict)]
                    for x in recent:
                        who = "me" if (me_id and x.get("from_id") == me_id) or is_me_name(x.get("from")) else x.get("from") or x.get("from_id")
                        reactions.append({k: v for k, v in {"who": who, "reaction": shown, "ts": x.get("date")}.items() if v})
                    reactions += [{"reaction": shown}] * max(0, int(number(r.get("count")) or 0) - len(recent))
                reply = m.get("reply_to_message_id")
                event = m.get("type") == "service"
                if event:
                    text = text or " ".join(x for x in (author, str(m.get("action") or "").replace("_", " "), m.get("title") or "") if x)
                meta = {"group": group or None, "chat_type": c.get("type"),
                        "reply_to": f"{cid}:{reply}" if reply is not None and not m.get("reply_to_peer_id") else None,
                        "reply_text": (said.get(reply) or "")[:200] or None if reply is not None else None,
                        "reactions": reactions or None, "edited": from_unix(number(m.get("edited_unixtime"))) or m.get("edited"),
                        "forwarded_from": m.get("forwarded_from"), "via_bot": m.get("via_bot"), "files": files or None,
                        "action": m.get("action") if event else None}
                if w.has(key):
                    continue
                w.add(id=key, kind="event" if event else "message", ts=ts, author=author, is_me=author == "me",
                      thread=cid, thread_name=c.get("name") or ("Saved Messages" if c.get("type") == "saved_messages" else cid),
                      participants=people if not group else None, text=text or "[empty message]",
                      meta={k: v for k, v in meta.items() if v is not None})


def slack(es, W, used):
    """Slack exports (a workspace admin's, or slackdump's): users.json (org_users.json in an Enterprise Grid org's) names
    its people; channels.json, groups.json (private channels), dms.json and mpims.json (group DMs) its conversations;
    each conversation's folder holds a file a day. Each export by itself, by the folder its lists are in: a Claude.ai
    export beside it has a users.json too, and two workspaces can sit side by side. A folder of days without any of
    them (one member's export, slackdump's) is read when its days are Slack's. Then one member's export as text."""
    lists = collections.defaultdict(dict)  # (export, folder) -> users.json, channels.json ... in it
    for e in es:
        if e.name in SLACK_USERS or e.name in SLACK_LISTS:
            lists[(e.origin, posixpath.dirname(e.path))][e.name] = e
    # slackdump's downloaded files: __uploads/<file id>/<name> (its default) or <conversation>/attachments/<file id>-<name>
    uploads = {(e.origin, m.group(1) or m.group(2)): e for e in es for m in [SLACK_UPLOAD.search(e.path)] if m}
    exports = collections.defaultdict(list)
    for e in es:
        if not SLACK_DAY.search(e.path):
            continue
        top = root = posixpath.dirname(posixpath.dirname(e.path))
        while root and (e.origin, root) not in lists:  # an org's lists can be further up
            root = posixpath.dirname(root)
        exports[(e.origin, root if (e.origin, root) in lists else top)].append(e)
    for (origin, root), days in sorted(exports.items()):
        found = dict(lists.get((origin, root), {}))
        up = root
        while up and not any(n in found for n in SLACK_USERS):  # an org's people can be listed above its workspaces'
            up = posixpath.dirname(up)
            found.update((n, x) for n, x in lists.get((origin, up), {}).items() if n in SLACK_USERS)
        if found or slack_days(days[0]):
            slack_workspace(found, days, W, used, uploads)
    slack_text(es, W, used)


def slack_days(e):
    """Whether a day's file is Slack's: a list of messages with their times (ts)."""
    try:
        d = e.json()
    except Exception:  # noqa: BLE001 - not JSON, or damaged: not taken for Slack's
        return False
    return isinstance(d, list) and any(isinstance(m, dict) and "ts" in m and m.get("type", "message") == "message" for m in d[:20])


def slack_list(e):
    return [x for x in listish(e.json()) if isinstance(x, dict)]


SLACK_UPLOAD = re.compile(r"(?:^|/)(?:__uploads/(F[A-Z0-9]{6,})/[^/]+|attachments/(F[A-Z0-9]{6,})-[^/]+)$")


def slack_workspace(found, days, W, used, uploads=None):
    users = {"USLACKBOT": "Slackbot"}
    for n in SLACK_USERS:
        if n in found:
            used.add(found[n].path)
            for u in guarded(found[n], used, slack_list) or []:
                p = u.get("profile") if isinstance(u.get("profile"), dict) else {}
                name = u.get("real_name") or p.get("real_name") or p.get("display_name") or u.get("name")
                if isinstance(u.get("id"), str) and name:
                    users.setdefault(u["id"], str(name))
    convs, names = {}, {}  # a conversation's folder -> (its name, what it is, who's in it); a channel's id -> its name
    for n, what in SLACK_LISTS.items():
        if n not in found:
            continue
        used.add(found[n].path)
        for c in guarded(found[n], used, slack_list) or []:
            folder = c.get("name") if what != "dm" else c.get("id")
            if not isinstance(folder, str) or not isinstance(c.get("id", ""), str):
                continue
            people = [users.get(u, u) for u in listish(c.get("members")) if isinstance(u, str)]
            # A DM or group DM is named after the others in it.
            name = ", ".join([p for p in people if not is_me_name(p)] or people) or folder if what in ("dm", "group dm") else f"#{folder}"
            convs[folder] = (name, what, people)
            if c.get("id"):
                names[c["id"]] = folder if what != "dm" else name
    w = W("slack")
    said = {}  # a message's record id -> its text, for the replies to it (a thread's first message comes first)
    for e in sorted(days, key=lambda e: e.path):
        used.add(e.path)
        guarded(e, used, slack_day, w, users, convs, names, said, uploads or {}, used)


def slack_markup(s, users, names):
    """Slack's markup as words: <@U01> a name, <#C01|general> a channel, <https://…|the doc> "the doc (https://…)",
    <!here> @here, and &amp; &lt; &gt; the characters."""
    def link(m):
        url, label = m.group(1), m.group(2)
        url = url[7:] if url.startswith("mailto:") else url
        return f"{label} ({url})" if label and label not in (url, re.sub(r"^\w+://", "", url)) else url
    s = s if isinstance(s, str) else "" if s is None else str(s)
    s = re.sub(r"<@([UWB][A-Z0-9]+)(?:\|([^>]*))?>", lambda m: "@" + (users.get(m.group(1)) or m.group(2) or m.group(1)), s)
    s = re.sub(r"<#([CGD][A-Z0-9]+)(?:\|([^>]*))?>", lambda m: "#" + (m.group(2) or names.get(m.group(1)) or m.group(1)), s)
    s = re.sub(r"<!subteam\^[A-Z0-9]+(?:\|([^>]*))?>", lambda m: m.group(1) or "@a group", s)
    s = re.sub(r"<!date\^[^|>]*\|([^>]*)>", r"\1", s)
    s = re.sub(r"<!(here|channel|everyone)(?:\|[^>]*)?>", r"@\1", s)
    s = re.sub(r"<((?:https?|ftp)://[^|>\s]+|mailto:[^|>\s]+|tel:[^|>\s]+)(?:\|([^>]*))?>", link, s)
    return html.unescape(s)


def slack_blocks(blocks, users, names):
    """A message's rich text (blocks), as words: what a message without text of its own says."""
    out = []

    def walk(x):
        if isinstance(x, list):
            for i in x:
                walk(i)
            return
        if not isinstance(x, dict):
            return
        t = x.get("type")
        if t == "text" and isinstance(x.get("text"), str):
            out.append(x["text"])
        elif t == "user":
            out.append("@" + users.get(x.get("user_id"), str(x.get("user_id"))))
        elif t == "channel":
            out.append("#" + names.get(x.get("channel_id"), str(x.get("channel_id"))))
        elif t == "link":
            url, label = x.get("url") or "", x.get("text")
            out.append(f"{label} ({url})" if label and label != url else url)
        elif t == "emoji":
            out.append(f":{x.get('name')}:")
        elif t == "broadcast":
            out.append(f"@{x.get('range')}")
        elif t in ("date", "usergroup"):
            out.append(x.get("fallback") or "")
        elif isinstance(x.get("text"), dict):  # a bot's section: {"type": "mrkdwn", "text": ...}
            out.append(slack_markup(x["text"].get("text"), users, names) + "\n")
        walk(x.get("elements"))
        walk(x.get("fields"))
        if t in ("rich_text_section", "rich_text_preformatted", "rich_text_quote") and out and not out[-1].endswith("\n"):
            out.append("\n")
    walk(blocks)
    return "".join(out).strip()


# Slack's names for the emoji most used as reactions; another (a workspace's own) stays :its-name:
SLACK_EMOJI = {"+1": "👍", "thumbsup": "👍", "-1": "👎", "thumbsdown": "👎", "heart": "❤️", "joy": "😂", "laughing": "😆",
               "tada": "🎉", "eyes": "👀", "fire": "🔥", "pray": "🙏", "white_check_mark": "✅", "heavy_check_mark": "✔️",
               "100": "💯", "raised_hands": "🙌", "clap": "👏", "smile": "😄", "slightly_smiling_face": "🙂", "rocket": "🚀",
               "thinking_face": "🤔", "ok_hand": "👌", "sob": "😭", "wave": "👋", "sweat_smile": "😅", "heart_eyes": "😍",
               "muscle": "💪", "pinched_fingers": "🤌", "saluting_face": "🫡", "skull": "💀", "x": "❌", "star": "⭐"}


def slack_emoji(name):
    base = name.split("::", 1)[0]  # "+1::skin-tone-3"
    return SLACK_EMOJI.get(base, f":{base}:")


def slack_day(e, w, users, convs, names, said=None, uploads=None, used=None):
    """One conversation's day: its messages, threads (thread_ts, and a reply's own), edits, files, reactions and bots'
    posts. Who joined or left isn't kept; a channel's new topic or a pin is an event; a deleted message whose replies
    stay (tombstone) is kept, tagged as deleted mail is."""
    folder = PurePosixPath(e.path).parent.name
    name, what, people = convs.get(folder, (f"#{folder}", None, []))
    for m in listish(e.json()):
        if not isinstance(m, dict):
            continue
        sub, ts, uid = (m.get(k) if isinstance(m.get(k), str) else None for k in ("subtype", "ts", "user"))
        if m.get("type", "message") != "message" or sub in SLACK_SKIP:
            continue
        key = f"{folder}:{ts}" if ts else f"{folder}:{rid(e.path, uid, m.get('text'))}"
        if w.has(key):
            continue
        profile = m.get("user_profile") if isinstance(m.get("user_profile"), dict) else {}
        bot = m.get("bot_profile") if isinstance(m.get("bot_profile"), dict) else {}
        is_bot = sub == "bot_message" or bool(m.get("bot_id") and not users.get(uid))
        author = users.get(uid) or profile.get("real_name") or profile.get("display_name") or m.get("username") or bot.get("name") or uid
        text = slack_markup(m.get("text"), users, names) or slack_blocks(m.get("blocks"), users, names)
        # A bot posts in attachments; a person's carry a shared message; the rest are previews of a link in the text.
        notes = ["\n".join(slack_markup(x, users, names) for x in (a.get("pretext"), a.get("title"), a.get("text") or a.get("fallback")) if x)
                 for a in listish(m.get("attachments"))
                 if isinstance(a, dict) and (is_bot or not text or a.get("is_share") or a.get("is_msg_unfurl"))]
        files = [f for f in listish(m.get("files")) or ([m["file"]] if isinstance(m.get("file"), dict) else []) if isinstance(f, dict)]
        shown = [f.get("title") or f.get("name") for f in files]
        saved = []
        for f in files:
            up = (uploads or {}).get((e.origin, f.get("id")))
            if up and (path := save_media(up, MEDIA / "slack" / up.path, from_unix(number(ts)))):
                used.add(up.path) if used is not None else None
                saved.append(path)
        text = "\n".join(x for x in (text, *notes, *(f"[file: {n}]" if n else "[a file Slack no longer keeps]" for n in shown)) if x)
        thread = m.get("thread_ts")
        edited = m.get("edited") if isinstance(m.get("edited"), dict) else {}
        # each person's, {who, reaction}, as every chat source keeps them; one with no users listed, once per count
        reactions = []
        for r in listish(m.get("reactions")):
            if isinstance(r, dict) and isinstance(r.get("name"), str):
                emoji = slack_emoji(r["name"])
                who = [u for u in listish(r.get("users")) if isinstance(u, str)]
                reactions += [{"who": "me" if is_me_name(users.get(u)) else users.get(u) or u, "reaction": emoji} for u in who] or \
                    [{"reaction": emoji}] * max(1, int(r.get("count") or 1))
        me = is_me_name(author) and not is_bot
        parent = f"{folder}:{thread}" if thread and thread != ts else None
        if said is not None:
            said[key] = text
        meta = {"thread_ts": thread, "reply_to": parent, "reply_text": (said or {}).get(parent, "")[:200] or None if parent else None,
                "replies": m.get("reply_count"), "edited": from_unix(number(edited.get("ts"))), "reactions": reactions or None,
                "attachments": [n for n in shown if n] or None, "files": saved or None,
                "bot": True if is_bot else None, "type": sub, "conversation": what,
                "tier": "deleted" if sub == "tombstone" else None}
        w.add(id=key, kind="event" if sub in SLACK_EVENTS else "message", ts=from_unix(number(ts)), author="me" if me else author,
              is_me=me, thread=folder, thread_name=name, participants=people if what in ("dm", "group dm") else None, text=text,
              meta={k: v for k, v in meta.items() if v})


def slack_text(es, W, used):
    """One member's export as text: channels/<name>.txt, dms/<people>.txt, "[2020-04-20 13:47:27] <jjordan> text" a
    message (lines after it go on with it). Its times are taken to be UTC, as Slack's own are."""
    for e in es:
        if e.path in used or not re.search(r"(^|/)(channels|dms)/[^/]+\.txt$", e.path, re.I):
            continue
        try:
            lines = e.text().splitlines()
        except DAMAGED as x:
            unreadable(e, x, used)
            continue
        if not SLACK_LINE.match(next((l for l in lines if l.strip()), "")):
            continue
        used.add(e.path)
        dm = PurePosixPath(e.path).parent.name.lower() == "dms"
        stem = PurePosixPath(e.name).stem
        msgs = []
        for l in lines:
            m = SLACK_LINE.match(l)
            if m:
                msgs.append(list(m.groups()))
            elif msgs:
                msgs[-1][2] += "\n" + l
        people = sorted({who for _, who, _ in msgs})
        w = W("slack")
        times = collections.Counter()
        for when, who, text in msgs:
            mark = (when, who, text.strip())
            times[mark] += 1
            key = f"{'dms' if dm else 'channels'}/{stem}:{rid(*mark)}" + (f"#{times[mark]}" if times[mark] > 1 else "")
            if w.has(key):
                continue
            me = is_me_name(who)
            w.add(id=key, kind="message", ts=parse_time(when + "+00:00"), author="me" if me else who, is_me=me, thread=stem,
                  thread_name=stem if dm else f"#{stem}", participants=people, text=text.strip(),
                  meta={"conversation": "dm" if dm else "channel"})


def chat_time(s):
    try:  # "Wednesday, June 8, 2016 at 3:55:41 AM UTC", with a narrow no-break space before AM/PM
        return iso(datetime.strptime(s.replace(" ", " "), "%A, %B %d, %Y at %I:%M:%S %p UTC").replace(tzinfo=timezone.utc))
    except (ValueError, AttributeError):
        # ISO, or as an account in another language writes it ("Mittwoch, 8. Juni 2016 um 04:00:00 UTC"), or British
        # English ("Tuesday, 7 February 2021 at 17:13:43 UTC")
        return parse_time(s) or loose_time(s)


def plain_file(e):
    """The file on disk an entry is, in an unzipped export; None for one inside a zip or tar."""
    if e.origin != e.path and not (IMPORTS / e.origin).is_dir():
        return None
    p = IMPORTS / e.path
    return p if p.is_file() and not p.is_symlink() else None


def clone_file(src, dest):
    """dest as an APFS clone of src: a file of its own that shares src's blocks, so it takes no space until one of
    them changes. False where the disk can't (another volume, not APFS)."""
    try:
        return ctypes.CDLL(None).clonefile(os.fsencode(src), os.fsencode(dest), 0) == 0
    except (OSError, AttributeError):
        return False


# Copies made before media from unzipped exports were cloned: each is made a clone once (.media-cloned, next to the
# manifest, says that's done).
_reclone = {}


# What reading a damaged zip member raises: a bad CRC, a broken deflate stream, a member cut short.
DAMAGED = (zipfile.BadZipFile, zlib.error, EOFError)


def save_media(e, dest, ts):
    """Copy an export's attachment out to corpus/media/ as a plain file (once), dated like its message. From an
    unzipped export it's a clone, so the file isn't on the disk twice. Returns its path, or None when the name would
    land outside corpus/media/ (a crafted export's ../ or absolute uri) or the file in the zip is damaged (said so)."""
    if not dest.resolve().is_relative_to(MEDIA.resolve()):
        print(f"[imports] skipped a file whose name points outside corpus/media: {str(dest)[-80:]}")
        return None
    if MEDIA not in _reclone:
        _reclone[MEDIA] = not common.MANIFEST.with_name(".media-cloned").exists()
    src = plain_file(e)
    have = dest.exists() and dest.stat().st_size == e.size
    if not have or (src and _reclone[MEDIA]):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.unlink(missing_ok=True)  # a clone is made only where there's no file
        try:
            if not (src and clone_file(src, dest)):
                with e.open() as f, open(dest, "wb") as out:
                    shutil.copyfileobj(f, out)
        except DAMAGED as x:  # no half a file left; the message, photo or page it's in is kept without it
            dest.unlink(missing_ok=True)
            print(f"[imports] couldn't copy {e.origin}: {e.path} ({type(x).__name__}: {str(x)[:120]})")
            return None
    if ts:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        os.utime(dest, (t, t))
    return str(dest.relative_to(CORPUS))


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
            try:
                info = e.json()
            except Exception as x:  # noqa: BLE001 - not JSON, or a damaged zip member
                unreadable(e, x, used)
                continue
            if not isinstance(info, dict):
                continue
            used.add(e.path)
            members[m.group(1)] = (info.get("name"), [p.get("name") or p.get("email") for p in listish(info.get("members")) if isinstance(p, dict)])
        elif not m.group(2).endswith(".json"):
            used.add(e.path)
            files[m.group(1)][m.group(2)] = e
    for e in es:
        m = re.search(r"Google Chat/Groups/([^/]+)/messages\.json$", e.path)
        if not m:
            continue
        try:
            msgs = e.json()
        except Exception as x:  # noqa: BLE001 - one conversation's file that's damaged: the others are read
            unreadable(e, x, used)
            continue
        if not isinstance(msgs, dict):
            continue
        used.add(e.path)
        group = m.group(1)
        space_name, people = members.get(group, (None, []))
        others = [p for p in people if p and not is_me_name(p)]
        thread_name = space_name or ", ".join(others) or group
        folder = MEDIA / "google_chat" / re.sub(r"[/:\\]", "-", f"{thread_name[:80]} [{group}]")
        w = W("google_chat")
        repeats = collections.Counter()
        for msg in listish(msgs.get("messages")):
            if not isinstance(msg, dict):
                continue
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
NOTION_ID = re.compile(r" ([0-9a-f]{32})(?:_all)?\.(md|csv|html)$")
NOTION_HTML_TIME = r'property-row-{}(?:(?!</tr>).)*?<time>([^<]+)</time>'  # a property's time in a page of the HTML export


def notion_time(v):
    """A time Notion wrote ("January 1, 2024 10:00 AM", "@January 1, 2024 10:00 AM" in a page of the HTML export), as
    the clock on this Mac showed it: in UTC. A date alone stays a date."""
    v = (v or "").strip().lstrip("@").strip()
    for f in ("%B %d, %Y %I:%M %p", "%B %d, %Y %H:%M"):
        try:
            return local_utc(datetime.strptime(v, f))
        except ValueError:
            continue
    return parse_time(v, "%B %d, %Y") if v else None


def notion_export(es, W, used):
    """Notion "Export all workspace content" (Markdown & CSV, folders for subpages; or HTML). One record per page, one
    per database table (CSV). Reads only the export: page files carry no dates (every zip entry is stamped with
    the export time), so ts comes from a "Created time" property (database rows), else the nearest parent page
    that has one, else stays empty; meta.ts_from says which. Attachments are copied to corpus/media/notion/ and
    listed in meta.files; PDFs and docs are also read by other_documents. A big workspace comes as one zip holding
    Export-<id>-Part-N.zip: a page, its subpages and their files can be in different parts. A workspace exported twice
    is read once (page ids)."""
    mine = [e for e in es if NOTION_EXPORT.search(f"{e.origin}/{e.path}")]
    if not mine:
        return
    rel = lambda path: path.split("/", 1)[1] if NOTION_EXPORT.match(path) else path  # drop the Export-<id>/ (or -Part-N.zip/) root
    by_path = {}
    for e in mine:  # by where it is in the export, whichever part it's in; this export's own first
        by_path.setdefault((e.origin, rel(e.path)), e)
        by_path.setdefault(rel(e.path), e)
    crumbs = lambda path: " › ".join(NOTION_ID.sub("", re.sub(r" [0-9a-f]{32}$", "", c)) for c in rel(path).split("/")[:-1])
    key = lambda path: re.sub(r" [0-9a-f]{32}(?=/|$)", "", path)  # a page's place, without the ids in its folders' names
    pages = {}  # path without " <id>.md" -> (page id, ts) so subpages can inherit a date
    for e in sorted((e for e in mine if e.path.endswith(".md") or e.path.endswith(".html") and NOTION_ID.search(e.path)),
                    key=lambda e: rel(e.path).count("/")):
        used.add(e.path)
        try:
            text = e.text()
        except DAMAGED as x:
            unreadable(e, x, used)
            continue
        page = e.path.endswith(".html")
        m = NOTION_ID.search(e.path)
        pid = m.group(1) if m else rid(e.path)
        if page:
            head = re.search(r'<h1[^>]*class="page-title"[^>]*>(.*?)</h1>', text, re.S) or re.search(r"<title>(.*?)</title>", text, re.S)
            title = html_to_text(head.group(1)) if head else None
            prop = lambda name: (re.search(NOTION_HTML_TIME.format(name), text, re.S) or [None, None])[1]
            ts, modified = notion_time(prop("created_time")), notion_time(prop("last_edited_time"))
            targets = re.findall(r'(?:src|href)="([^"]+)"', text)
            body = html_to_text(text)
        else:
            title = next((l[2:].strip() for l in text.splitlines()[:3] if l.startswith("# ")), None)
            prop = lambda name: (re.search(rf"^{name}: (.+)$", text[:2000], re.M) or [None, None])[1]
            ts, modified = notion_time(prop("Created(?: time)?")), notion_time(prop("Last edited time"))
            targets = re.findall(r"\]\(([^)]+)\)", text)
            body = re.sub(r"\[([^\]]*)\]\([^)]+\.(?:md|csv)\)", r"[\1]", text)  # links to other pages -> their titles
        title = title or NOTION_ID.sub("", PurePosixPath(e.path).name)
        ts_from = "created property" if ts else None
        if not ts:
            parent = pages.get(key(PurePosixPath(rel(e.path)).parent.as_posix()))
            ts, ts_from = (parent[1], "parent page") if parent and parent[1] else (None, None)
        pages.setdefault(key(NOTION_ID.sub("", rel(e.path))), (pid, ts))
        files, seen = [], W("notion_export").has(pid)  # a page exported twice: its files are the first one's
        for target in targets:
            target = unquote(html.unescape(target).split(" ")[0])
            if target.startswith(("http", "#", "mailto:")) or target.endswith((".md", ".csv", ".html")):
                continue
            path = posixpath.normpath(posixpath.join(PurePosixPath(rel(e.path)).parent.as_posix(), target))
            f = by_path.get((e.origin, path)) or by_path.get(path)
            if f and not seen and (saved := save_media(f, MEDIA / "notion" / path, ts)):
                files.append(saved)
            if f and PurePosixPath(f.name).suffix.lower() not in DOC_EXT:  # the page's (a PDF's text is read as a document too)
                used.add(f.path)
        if seen:
            continue
        W("notion_export").add(id=pid, kind="note", ts=ts, author="me", is_me=True, thread=rel(e.path).split("/")[0],
                               thread_name=crumbs(e.path) or None, title=title[:300], text=body[:200_000],
                               meta={"path": rel(e.path), "ts_from": ts_from, "modified": modified, "files": files or None})
    used.update(e.path for e in mine if rel(e.path) == "index.html")  # the HTML export's list of its pages
    tables = {}
    for e in mine:
        m = NOTION_ID.search(e.path)
        if e.path.endswith(".csv") and m and (m.group(1) not in tables or e.path.endswith("_all.csv")):
            tables[m.group(1)] = e  # Notion writes the current view and _all; keep _all
    for pid, e in tables.items():
        used.update(x.path for x in mine if x.path.endswith(".csv") and pid in x.path)
        try:
            text = e.text().lstrip("\ufeff")
        except DAMAGED as x:
            unreadable(e, x, used)
            continue
        if not W("notion_export").has(f"{pid}:table"):
            W("notion_export").add(id=f"{pid}:table", kind="database", author="me", is_me=True, thread=rel(e.path).split("/")[0],
                                   thread_name=crumbs(e.path) or None, title=NOTION_ID.sub("", PurePosixPath(e.path).name),
                                   text=text[:200_000], meta={"path": rel(e.path)})


# Fitbit's series by the reading: a minute's steps, distance, calories or floors, heart rate every few seconds, blood
# oxygen and skin temperature through the night, a run's pace by the second, in files of a day to a month named by the day
# they start. Years of them are millions of readings: each series is read as one record a day. Three kinds of file, all
# checked against a real Takeout (2025) that has the three for the same minutes:
# - the JSON series, [{"dateTime": "MM/DD/YY HH:MM:SS", "value": …}] (heart rate's value {bpm, confidence}), in the
#   account archive's Physical Activity/ (MyFitbitData/<you>/) and Takeout's Global Export Data/ (Takeout/Fitbit/, Google
#   Health/ since the rename); heartrate-… in older archives. Steps, distance (cm) and heart rate in UTC; calories and
#   altitude (feet) in the person's time.
# - Google's CSVs, Physical Activity_GoogleData/<family>_<date>.csv (in a folder a family since 2026): a timestamp in UTC,
#   the values (as the readme beside each says), and since 2026 a data source: the phone, the band and Health Connect each
#   count the same steps, so a day's total is the device that counted the most, never their sum.
# - the older CSVs beside them: Minute SpO2 (UTC), Heart Rate Variability Details (UTC, with no zone mark), Wrist
#   Temperature (against your usual), Active Zone Minutes and estimated_oxygen_variation (the person's time).
# The same day in two kinds (the JSON and Google's CSV of the same minutes) is read from the one first below.
_DAY = r"(?P<start>\d{4}-\d\d-\d\d)"
_JSON, _GOOGLE, _OLD = r"(^|/)(?:Physical Activity|Global Export Data)/", r"(^|/)Physical Activity_GoogleData/(?:[^/]+/)?", r"(^|/)(?:[^/]+/)?"
FITBIT_FILES = [(re.compile(where + name + r"$"), series, clock, cols, by) for where, name, series, clock, cols, by in (
    # where, its name, its series, its clock, its values as (column, part, times what), the column its readings group by
    (_JSON, rf"steps-{_DAY}\.json", "steps", "utc", [("value", "steps", 1)], None),
    (_JSON, rf"distance-{_DAY}\.json", "distance", "utc", [("value", "distance_cm", 1)], None),
    (_JSON, rf"calories-{_DAY}\.json", "calories", "local", [("value", "calories", 1)], None),
    (_JSON, rf"altitude-{_DAY}\.json", "altitude", "local", [("value", "feet", 1)], None),
    (_JSON, rf"heart_?rate-{_DAY}\.json", "heart_rate", "utc", [("value.bpm", "bpm", 1)], None),
    (_GOOGLE, rf"steps_{_DAY}\.csv", "steps", "utc", [("steps", "steps", 1)], None),
    (_GOOGLE, rf"distance_{_DAY}\.csv", "distance", "utc", [("distance", "distance_cm", 100)], None),  # metres
    (_GOOGLE, rf"calories_{_DAY}\.csv", "calories", "utc", [("calories", "calories", 1)], None),
    (_GOOGLE, rf"altitude_{_DAY}\.csv", "altitude", "utc", [("gain", "feet", 1 / 304.8)], None),  # millimetres
    (_GOOGLE, rf"heart_rate_{_DAY}\.csv", "heart_rate", "utc", [("beats per minute", "bpm", 1)], None),
    (_GOOGLE, rf"floors_{_DAY}\.csv", "floors", "utc", [("floors", "floors", 1)], None),
    (_GOOGLE, rf"active_minutes_{_DAY}\.csv", "active_minutes", "utc",
     [("light", "light", 1), ("moderate", "moderate", 1), ("very", "very", 1)], None),
    (_GOOGLE, rf"active_zone_minutes_{_DAY}\.csv", "active_zone_minutes", "utc", [("total minutes", "minutes", 1)], "heart rate zone"),
    (_OLD, rf"Active Zone Minutes - {_DAY}\.csv", "active_zone_minutes", "local", [("total_minutes", "minutes", 1)], "heart_zone_id"),
    (_GOOGLE, rf"calories_in_heart_rate_zone_{_DAY}\.csv", "calories_in_heart_rate_zone", "utc", [("kcal", "calories", 1)],
     "heart rate zone type"),
    (_GOOGLE, rf"activity_level_{_DAY}\.csv", "activity_level", "utc", [], "level"),
    (_GOOGLE, rf"live_pace_{_DAY}\.csv", "live_pace", "utc",
     [("steps", "steps", 1), ("distance millimeters", "distance_mm", 1), ("altitude gain millimeters", "altitude_gain_mm", 1)], None),
    (_GOOGLE, rf"cardio_load_{_DAY}\.csv", "cardio_load", "utc",
     [("total", "total", 1), ("workout", "workout", 1), ("background", "background", 1)], None),
    (_GOOGLE, rf"body_temperature_{_DAY}\.csv", "body_temperature", "utc", [("temperature celsius", "celsius", 1)], None),
    (_OLD, rf"Wrist Temperature - {_DAY}\.csv", "wrist_temperature", "local", [("temperature", "celsius", 1)], None),
    (_GOOGLE, rf"oxygen_saturation_{_DAY}\.csv", "oxygen_saturation", "utc", [("oxygen saturation percentage", "percent", 1)], None),
    (_OLD, rf"Minute SpO2 - {_DAY}\.csv", "oxygen_saturation", "utc", [("value", "percent", 1)], None),
    (_OLD, rf"estimated_oxygen_variation-{_DAY}\.csv", "oxygen_variation", "local", [("infrared to red signal ratio", "ratio", 1)], None),
    (_OLD, rf"Heart Rate Variability Details - {_DAY}\.csv", "heart_rate_variability", "utc",
     [("rmssd", "rmssd_ms", 1), ("coverage", "coverage", 1), ("low_frequency", "low_frequency", 1), ("high_frequency", "high_frequency", 1)], None),
    (_GOOGLE, rf"heart_rate_variability_{_DAY}\.csv", "heart_rate_variability", "utc",
     [("root mean square of successive differences milliseconds", "rmssd_ms", 1), ("standard deviation milliseconds", "deviation_ms", 1)], None),
    (_GOOGLE, rf"speed_{_DAY}\.csv", "speed", "utc", [("speed", "km_per_hour", 1)], None),
    (_GOOGLE, rf"cadence_{_DAY}\.csv", "cadence", "utc", [("steps per minute", "steps_per_minute", 1)], None),
    (_GOOGLE, rf"stride_length_{_DAY}\.csv", "stride_length", "utc", [("stride length", "cm", 1)], None),
    (_GOOGLE, rf"ground_contact_time_{_DAY}\.csv", "ground_contact_time", "utc", [("ground contact time", "ms", 1)], None),
    (_GOOGLE, rf"vertical_oscillation_{_DAY}\.csv", "vertical_oscillation", "utc", [("vertical oscillation", "cm", 1)], None),
    (_GOOGLE, rf"vertical_ratio_{_DAY}\.csv", "vertical_ratio", "utc", [("vertical ratio", "ratio", 1)], None),
)]
FITBIT_NAME = re.compile(r"\d{4}-\d\d-\d\d\.(json|csv)$")  # what every one of them ends with
# A day of each series: its title, how its readings add up ("sum": the day's total; "range": its lowest, average and
# highest; "count": how many of each value, a minute each), its parts as (part, how one is written, its unit), the first
# the day's figure, and for a series grouped by a column, what its groups are.
FITBIT_KINDS = {
    "steps": ("Steps", "sum", [("steps", "{:,.0f}", "")]),
    "distance": ("Distance", "sum", [("distance_cm", lambda v: f"{v / 1e5:.2f}", " km")]),
    "calories": ("Calories burned", "sum", [("calories", "{:,.0f}", "")]),
    "altitude": ("Altitude climbed", "sum", [("feet", lambda v: f"{v:,.0f} ft ({v * 0.3048:,.0f} m)", "")]),
    "floors": ("Floors climbed", "sum", [("floors", "{:,.0f}", "")]),
    "heart_rate": ("Heart rate", "range", [("bpm", "{:.0f}", " bpm")]),
    "active_minutes": ("Active minutes", "sum", [("light", "{:,.0f}", " light"), ("moderate", "{:,.0f}", " moderate"),
                                                 ("very", "{:,.0f}", " very active")]),
    "active_zone_minutes": ("Active Zone Minutes", "sum", [("minutes", "{:,.0f}", "")], "zones"),
    "calories_in_heart_rate_zone": ("Calories burned by heart rate zone", "sum", [("calories", "{:,.0f}", "")], "zones"),
    "activity_level": ("Activity level", "count", [], "levels"),
    "live_pace": ("Live pace", "sum", [("steps", "{:,.0f}", " steps"), ("distance_mm", lambda v: f"{v / 1e6:.2f}", " km"),
                                       ("altitude_gain_mm", lambda v: f"{v / 1e3:,.0f}", " m climbed")]),
    "cardio_load": ("Cardio load", "sum", [("total", "{:,.1f}", " in all"), ("workout", "{:,.1f}", " in workouts"),
                                           ("background", "{:,.1f}", " outside them")]),
    "body_temperature": ("Skin temperature", "range", [("celsius", "{:.1f}", " °C")]),
    "wrist_temperature": ("Wrist temperature against your usual", "range", [("celsius", "{:+.1f}", " °C")]),
    "oxygen_saturation": ("Blood oxygen", "range", [("percent", "{:.0f}", "%")]),
    "oxygen_variation": ("Estimated oxygen variation", "range", [("ratio", "{:g}", "")]),
    "heart_rate_variability": ("Heart rate variability", "range", [("rmssd_ms", "{:.0f}", " ms"), ("coverage", "{:g}", ""),
                                                                   ("low_frequency", "{:g}", ""), ("high_frequency", "{:g}", ""),
                                                                   ("deviation_ms", "{:g}", " ms")]),
    "speed": ("Speed", "range", [("km_per_hour", "{:.1f}", " km/h")]),
    "cadence": ("Cadence", "range", [("steps_per_minute", "{:.0f}", " steps a minute")]),
    "stride_length": ("Stride length", "range", [("cm", "{:.0f}", " cm")]),
    "ground_contact_time": ("Ground contact time", "range", [("ms", "{:.0f}", " ms")]),
    "vertical_oscillation": ("Vertical oscillation", "range", [("cm", "{:.1f}", " cm")]),
    "vertical_ratio": ("Vertical ratio", "range", [("ratio", "{:.1f}", "")]),
}
FITBIT_WRITTEN = set()  # the sources fitbit_days wrote this run
# Fitbit's routes: gps_location_<date>.csv in Google's Physical Activity_GoogleData/ (timestamp in UTC, latitude,
# longitude, altitude in metres: a point a second while a workout records its route, a file a UTC day; since 2026 maybe
# a data source too). Read as Location History's trips are, one record a route: where it started and ended, how far,
# how long, and its path thinned to FITBIT_PATH points (the rest counted, as Location History's raw points are). A route
# is a run of points without a gap of FITBIT_GAP, or a workout's (Health Fitness Data_GoogleData/UserExercises_*.csv,
# else Global Export Data/exercise-*.json) with its pauses, named by it.
FITBIT_ROUTE = re.compile(_GOOGLE + rf"gps_location_{_DAY}\.csv$")
FITBIT_GAP, FITBIT_PATH, FITBIT_SLACK = 300, 200, timedelta(minutes=2)  # seconds; points kept; a workout's ends, give or take


def fitbit_reads(path):
    """Whether fitbit_days reads a file: a series' (fitbit_file) or a route's."""
    return bool(fitbit_file(path) or FITBIT_ROUTE.search(path))


def fitbit_file(path):
    """The FITBIT_FILES entry a path is (its index, and the match), or None."""
    if FITBIT_NAME.search(path):
        for i, (pattern, *_) in enumerate(FITBIT_FILES):
            if m := pattern.search(path):
                return i, m
    return None


def fitbit_zone(es, roots):
    """The time zone in a Fitbit export's Profile.csv (Personal & Account/ in the archive, Your Profile/ in Takeout), next
    to where its series are; None when there's none that names one."""
    for e in es:
        if e.name != "Profile.csv" or not any(e.path.startswith(r) and e.path.count("/") == r.count("/") + 1 for r in roots):
            continue
        try:
            row = next(csv.DictReader(io.StringIO(e.text())), {})
            zone = next(v for k, v in row.items() if k and k.strip().lower() in ("timezone", "time_zone") and v and v.strip())
            return ZoneInfo(zone.strip())
        except Exception:  # noqa: BLE001 - no zone, or not one this Mac knows ("null", an offset): the next, or this Mac's
            continue
    return None


def fitbit_day(t, zone):
    """The day a reading at t ("03/01/24 08:00:00", or ISO) is on: its own date when zone is False (a series written in
    the person's time), else t's UTC time on the clock of zone (None: this Mac's)."""
    m = re.match(r"(\d\d)/(\d\d)/(\d\d) (\d\d):(\d\d)", t) or re.match(r"(\d{4})-(\d\d)-(\d\d)[T ](\d\d):(\d\d)", t)
    if not m:
        return None
    y, mo, d = (2000 + int(m[3]), int(m[1]), int(m[2])) if "/" in m[0] else (int(m[1]), int(m[2]), int(m[3]))
    try:
        dt = datetime(y, mo, d, int(m[4]), int(m[5]))
    except ValueError:
        return None
    if zone is False:
        return dt.date().isoformat()
    dt = dt.replace(tzinfo=timezone.utc)
    return (dt.astimezone(zone) if zone else dt.astimezone()).date().isoformat()


def fitbit_readings(e, cols, by):
    """(time, device, group, values) for each reading in a Fitbit series file: a JSON list of {dateTime, value}, or a CSV
    whose first column is the time (and, since 2026, with a data source). A value that isn't a number is None."""
    def number(v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        return v if v == v else None  # NaN
    if e.path.lower().endswith(".json"):
        def at(it, path):
            for k in path.split("."):
                it = it.get(k) if isinstance(it, dict) else None
            return it
        items = e.json()
        for it in items if isinstance(items, list) else []:
            if isinstance(it, dict):
                yield str(it.get("dateTime") or ""), "", None, [number(at(it, c)) for c, _, _ in cols]
        return
    with e.open() as f:  # read as it goes: a month of heart rate every 5 s is half a million rows
        rows = csv.reader(io.TextIOWrapper(f, encoding="utf-8-sig", errors="replace", newline=""))
        at = {h.strip().lower(): i for i, h in enumerate(next(rows, []))}
        idx, dev, grp = [at.get(c) for c, _, _ in cols], at.get("data source"), at.get(by) if by else None
        for r in rows:
            if r:
                cell = lambda i: r[i].strip() if i is not None and i < len(r) else None  # noqa: E731
                yield r[0].strip(), cell(dev) or "", cell(grp) if by else None, [number(cell(i)) for i in idx]


def fitbit_add(parts, part, v):
    a = parts.get(part)
    if a is None:
        parts[part] = [v, v, 1, v]  # lowest, total, readings, highest
    else:
        a[0], a[1], a[2], a[3] = min(a[0], v), a[1] + v, a[2] + 1, max(a[3], v)


def fitbit_merge(into, parts, groups):
    for k, a in parts.items():
        b = into[0].get(k)
        into[0][k] = list(a) if b is None else [min(a[0], b[0]), a[1] + b[1], a[2] + b[2], max(a[3], b[3])]
    for k, a in groups.items():
        b = into[1].setdefault(k, [0.0, 0])
        b[0], b[1] = b[0] + a[0], b[1] + a[1]


def fitbit_text(series, day, devs):
    """A day's record of one series: its text and meta, from what each device recorded ({device: [parts, groups]})."""
    title, how, parts, *group = FITBIT_KINDS[series]
    d = datetime.fromisoformat(day)
    on = f"{title} on {d:%A} {d.day} {d:%B %Y}: "
    num = lambda x: int(x) if x == int(x) else round(x, 1)  # noqa: E731
    say = lambda fmt, v: fmt(v) if callable(fmt) else fmt.format(v)  # noqa: E731
    if how == "range":  # every device's readings together
        both = [{}, {}]
        for p, g in devs.values():
            fitbit_merge(both, p, g)
        p = both[0]
        key, fmt, unit = parts[0]
        low, total, n, high = p[key]
        span = say(fmt, low) + unit if low == high else f"{say(fmt, low)} to {say(fmt, high)}{unit}, {say(fmt, total / n)} on average"
        return on + f"{span} ({n:,} reading{'s' if n != 1 else ''})", \
            {f"{key}_lowest": num(low), f"{key}_average": num(total / n), f"{key}_highest": num(high), "readings": n,
             **{f"{k}_average": num(p[k][1] / p[k][2]) for k, _, _ in parts[1:] if k in p}}
    # A total, or a count: the device that recorded the most. Each counts the same steps: added up, they'd be twice them.
    size = {dev: p[parts[0][0]][1] if parts else sum(c for _, c in g.values()) for dev, (p, g) in devs.items()
            if not parts or parts[0][0] in p}
    best = max(size, key=lambda dev: (size[dev], dev))
    p, g = devs[best]
    if how == "count":
        order = sorted(g.items(), key=lambda kv: (-kv[1][1], kv[0]))
        text = on + ", ".join(f"{c:,} {'minutes ' if i == 0 else ''}{k}" for i, (k, (_, c)) in enumerate(order))
        meta, fmt, unit = {group[0]: {k: c for k, (_, c) in order}, "readings": sum(c for _, c in g.values())}, "{:,.0f}", " minutes"
    else:
        text = on + ", ".join(say(fmt, p[k][1]) + unit for k, fmt, unit in parts if k in p)
        meta, (_, fmt, unit) = {k: num(p[k][1]) for k, _, _ in parts if k in p}, parts[0]
        if g:
            order = sorted(g.items(), key=lambda kv: (-kv[1][0], kv[0]))
            text += " (" + ", ".join(f"{k} {say(fmt, t)}" for k, (t, _) in order) + ")"
            meta[group[0]] = {k: num(t) for k, (t, _) in order}
        meta["readings"] = p[parts[0][0]][2]
    if len(size) > 1:
        text += " (by device: " + ", ".join(f"{dev or 'unnamed'} {say(fmt, v)}{unit}" for dev, v in
                                           sorted(size.items(), key=lambda kv: (-kv[1], kv[0]))) + ")"
        meta["by_device"] = {dev or "unnamed": num(v) for dev, v in size.items()}
    return text, {**meta, **({"device": best} if best else {})}


def fitbit_workouts(es, root):
    """(start, end, name, id) of the workouts in the Fitbit export at root, in UTC, by start: UserExercises' rows, else the
    exercise logs' (startTime, UTC, and duration in ms)."""
    def utc(v):  # "2025-07-19 20:32:00+0000"
        return datetime.fromisoformat(re.sub(r"([+-]\d\d)(\d\d)$", r"\1:\2", str(v or "").strip())).astimezone(timezone.utc)
    rows, logs = [], []
    for e in es:
        rest = e.path[len(root):] if e.path.startswith(root) else ""
        try:
            if re.fullmatch(r"Health Fitness Data_GoogleData/UserExercises_[^/]*\.csv", rest):
                for r in csv.DictReader(io.StringIO(e.text())):
                    try:
                        rows.append((utc(r.get("exercise_start")), utc(r.get("exercise_end")), r.get("activity_name") or None, r.get("exercise_id")))
                    except (TypeError, ValueError):
                        continue
            elif re.fullmatch(r"Global Export Data/exercise-\d+\.json", rest):
                for it in e.json():
                    try:
                        a = datetime.strptime(it["startTime"], "%m/%d/%y %H:%M:%S").replace(tzinfo=timezone.utc)
                        logs.append((a, a + timedelta(milliseconds=float(it.get("duration") or 0)), it.get("activityName"), str(it.get("logId"))))
                    except (KeyError, TypeError, ValueError, AttributeError):
                        continue
        except Exception:  # noqa: BLE001 - a file of them that can't be read: its routes aren't named, that's all
            continue
    return sorted(w for w in rows or logs if w[1] >= w[0])


def fitbit_meters(a, b):
    """The distance between two (lat, lon) points, in metres (haversine)."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371008.8 * math.asin(min(1.0, math.sqrt(h)))


def fitbit_routes(es, used, mapped):
    """(source, record, points not kept) for every route in the Fitbit exports' gps_location files (FITBIT_ROUTE)."""
    groups, mine = {}, set()  # (source, export root) -> {the day a file starts: its largest copy}
    for e in es:
        m = FITBIT_ROUTE.search(e.path)
        if not m or e.path in used and e.path not in mine:
            continue
        mine.add(e.path)
        key = leftover_source(e)
        source = key if key in mapped else f"{key}_other"
        AV.setdefault(source, other_avenue(key))
        files = groups.setdefault((source, e.path[:m.end(1)]), {})
        if m["start"] not in files or (e.size or 0) > (files[m["start"]].size or 0):
            files[m["start"]] = e
    used.update(mine)
    for (source, root), files in sorted(groups.items()):
        workouts = fitbit_workouts(es, root)
        starts = [w[0] for w in workouts]

        def workout(t, now=None):
            """The workout t is in: the one the route is on while it lasts (they overlap: an auto-detected walk in a
            workout), else one it's in, else one it's within FITBIT_SLACK of."""
            if now and now[0] - FITBIT_SLACK <= t <= now[1] + FITBIT_SLACK:
                return now
            i = bisect.bisect_right(starts, t + FITBIT_SLACK) - 1
            near = [workouts[j] for j in range(i, max(-1, i - 4), -1) if workouts[j][1] + FITBIT_SLACK >= t]
            return next((x for x in near if x[0] <= t <= x[1]), near[0] if near else None)

        def route(r):
            (t0, *p0), (t1, *p1) = r["points"][0], r["points"][-1]
            n = len(r["points"])  # FITBIT_PATH of them, evenly through it, its first and last among them
            path = [r["points"][round(i * (n - 1) / (min(n, FITBIT_PATH) - 1))] for i in range(min(n, FITBIT_PATH))] if n > 1 else r["points"]
            secs, alts = (t1 - t0).total_seconds(), [p[3] for p in r["points"] if p[3] is not None]
            name = r["workout"][2] if r["workout"] and r["workout"][2] else "Route"
            long = f"{secs // 3600:.0f} h {secs % 3600 // 60:.0f} min" if secs >= 3600 else f"{secs // 60:.0f} min" if secs >= 60 else f"{secs:.0f} s"
            far = f"{r['meters'] / 1000:.1f} km" if r["meters"] >= 100 else f"{r['meters']:.0f} m"
            at = lambda p: f"{p[0]:.5f}°, {p[1]:.5f}°"  # noqa: E731
            meta = {"activity": name if r["workout"] else None, "workout": r["workout"][3] if r["workout"] else None,
                    "meters": round(r["meters"]), "seconds": round(secs), "from": at(p0), "to": at(p1), "points": len(r["points"]),
                    "path": [[round(p[1], 5), round(p[2], 5)] for p in path], "altitude_lowest": min(alts, default=None),
                    "altitude_highest": max(alts, default=None), "device": r["device"] or None}
            return source, {"id": f"fitbit:route:{iso(t0)}" + (f":{r['device']}" if r["device"] else ""), "kind": "trip",
                            "ts": iso(t0), "ts_end": iso(t1), "author": "me", "is_me": True, "title": name,
                            "text": f"{name}: {far} in {long}, from {at(p0)} to {at(p1)}",
                            "meta": {k: v for k, v in meta.items() if v is not None}}, len(r["points"]) - len(path)
        on = {}  # device -> the route it's on
        for start in sorted(files):
            e = files[start]
            try:  # a day's file is small (a point a second while recording): read whole, so a damaged one adds nothing
                with e.open() as f:
                    rows = list(csv.reader(io.TextIOWrapper(f, encoding="utf-8-sig", errors="replace", newline="")))
            except Exception as x:  # noqa: BLE001 - damaged or cut short: said so, the catch-all has it, the others are read
                unreadable(e, x, used)
                continue
            at = {h.strip().lower(): i for i, h in enumerate(rows[0] if rows else [])}
            la, lo, al, dv = at.get("latitude"), at.get("longitude"), at.get("altitude"), at.get("data source")
            for row in rows[1:]:
                cell = lambda i: row[i].strip() if i is not None and i < len(row) else None  # noqa: E731
                try:
                    t = datetime.fromisoformat(row[0].strip().replace("Z", "+00:00")).astimezone(timezone.utc)
                    lat, lon = float(cell(la)), float(cell(lo))
                except (TypeError, ValueError, IndexError):
                    continue
                if not (-90 <= lat <= 90 and -180 <= lon <= 180) or abs(lat) < 0.01 and abs(lon) < 0.01:  # nowhere, or 0,0
                    continue
                try:
                    alt = float(cell(al))
                except (TypeError, ValueError):
                    alt = None
                dev = cell(dv) or ""
                r = on.get(dev)
                w = workout(t, r and r["workout"])
                if r and t <= r["points"][-1][0]:  # the same point again (a file's edge), or one out of order
                    continue
                if r and ((t - r["points"][-1][0]).total_seconds() > FITBIT_GAP and not (w and w is r["workout"]) or
                          w and r["workout"] and w is not r["workout"]):  # a gap, outside one workout; or the next workout
                    yield route(r)
                    r = None
                if r is None:
                    r = on[dev] = {"points": [], "meters": 0.0, "workout": w, "device": dev}
                elif w and not r["workout"]:
                    r["workout"] = w
                if r["points"]:
                    last = r["points"][-1]
                    d = fitbit_meters((last[1], last[2]), (lat, lon))
                    if d <= 100 * max(1.0, (t - last[0]).total_seconds()):  # faster than 360 km/h: GPS gone astray
                        r["meters"] += d
                r["points"].append((t, lat, lon, alt))
        for r in on.values():
            yield route(r)


def fitbit_days(es, W, used):
    """Fitbit's series by the reading (FITBIT_FILES), each as one record a day: the day's total steps, distance, calories,
    floors and the like, or its lowest, average and highest heart rate, temperature, blood oxygen and the like. A day is
    the person's: the UTC series are put on the clock of the zone in the export's Profile.csv (this Mac's when it has
    none), daylight saving and all. And each route a record (fitbit_routes). The records go where the export's others do:
    to the source of the folder's mapping (the Fitbit mapping the app ships), else to the catch-all's, <export>_other."""
    FITBIT_WRITTEN.clear()
    mapped = {folder_key(f) for f in load_mappings()}
    groups, roots, mine = {}, {}, set()  # (kind, source) -> {the day a file starts: its largest copy}; source -> folders
    for e in es:
        found = fitbit_file(e.path)
        if not found or e.path in used and e.path not in mine:
            continue
        (kind, m), key = found, leftover_source(e)
        mine.add(e.path)
        source = key if key in mapped else f"{key}_other"
        AV.setdefault(source, other_avenue(key))
        files = groups.setdefault((kind, source), {})
        if m["start"] not in files or (e.size or 0) > (files[m["start"]].size or 0):  # the same batch in two exports: once
            files[m["start"]] = e
        roots.setdefault(source, set()).add(e.path[:m.end(1)])
    used.update(mine)
    zones = {source: fitbit_zone(es, r) for source, r in roots.items()}
    days = {}  # (source, series) -> {day: (the kind of file it's read from, {device: [parts, groups]})}
    for (kind, source), files in sorted(groups.items()):  # in FITBIT_FILES' order: the first kind with a day has it
        _, series, clock, cols, by = FITBIT_FILES[kind]
        zone, have, seen = zones[source] if clock == "utc" else False, days.setdefault((source, series), {}), set()
        for start in sorted(files):
            e = files[start]
            before, seen, on, got = seen, set(), {}, {}
            try:
                for t, dev, grp, vals in fitbit_readings(e, cols, by):
                    if cols and (vals[0] is None or series == "heart_rate" and vals[0] <= 0):
                        continue
                    key = hash((t, dev, grp))  # (a number, not the strings: a month's readings are half a million)
                    if key in seen:
                        continue
                    seen.add(key)
                    if key in before:  # a batch repeats the readings at its edge that the one before it has
                        continue
                    minute = t[:14] if t[2:3] == "/" else t[:16]  # a minute's readings are on one day: worked out once
                    if minute not in on:
                        on[minute] = fitbit_day(t, zone)
                    if on[minute] is None:
                        continue
                    parts, sums = got.setdefault(on[minute], {}).setdefault(dev, [{}, {}])
                    for (_, part, times), v in zip(cols, vals):
                        if v is not None:
                            fitbit_add(parts, part, v * times)
                    if by:
                        g = sums.setdefault(re.sub(r"^heart rate zone type ", "", (grp or "unnamed").replace("_", " ").lower()), [0.0, 0])
                        g[0], g[1] = g[0] + (vals[0] * cols[0][2] if cols else 1), g[1] + 1
            except Exception as x:  # noqa: BLE001 - damaged or cut short: said so, the catch-all has it, the others are read
                unreadable(e, x, used)
                seen = before
                continue
            for day, devs in got.items():
                if have.setdefault(day, (kind, {}))[0] == kind:  # else an earlier kind of file has this day
                    for dev, (parts, sums) in devs.items():
                        fitbit_merge(have[day][1].setdefault(dev, [{}, {}]), parts, sums)
    for source, rec, dropped in fitbit_routes(es, used, mapped):
        w = W(source)
        FITBIT_WRITTEN.add(source)
        if not w.has(rec["id"]):
            w.add(**rec)
        if dropped:
            w.notes["raw_points_not_kept"] = w.notes.get("raw_points_not_kept", 0) + dropped
    for (source, series), have in sorted(days.items()):
        if not have:
            continue
        w = W(source)
        FITBIT_WRITTEN.add(source)
        for day, (kind, devs) in sorted(have.items()):
            text, meta = fitbit_text(series, day, devs)
            zone = zones[source] if FITBIT_FILES[kind][2] == "utc" else None
            w.add(id=f"fitbit:{series}:{day}", kind="activity", ts=f"{day}T00:00:00", author="me", is_me=True,
                  title=FITBIT_KINDS[series][0], text=text,
                  meta={"series": series, "day": day, **meta, **({"zone": zone.key} if zone else {})})


# Takeout's index of what's in it (archive_browser.html; Archiv_Übersicht.html in German): the one page at its top.
TAKEOUT_INDEX = re.compile(r"(^|/)Takeout(?: \d+)?/[^/]+\.html?$|(^|/)archive_browser\.html$")


def other_documents(es, W, used):
    from documents import iwork_text, pdf_text, pptx_text
    for e in es:
        ext = PurePosixPath(e.name).suffix.lower()
        if e.path in used or ext not in DOC_EXT or e.size > 60 * 2**20 or e.size == 0 or TAKEOUT_INDEX.search(e.path) or "Takeout/Keep/" in e.path:  # Keep has JSON twins
            continue
        try:
            data = e.read()
        except DAMAGED as x:
            unreadable(e, x, used)
            continue
        # One document is its place in the export and what it holds: the same Drive file in every Takeout since (or in
        # two zips of one) is kept once; a changed one, or another account's under the same name, is one of its own.
        w = W("imported_documents")
        key = f"{e.path}#{hashlib.sha1(data).hexdigest()[:12]}"
        if w.has(key):
            continue
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
        w.add(id=key, kind="document", author="me", title=title, text=re.sub(r"[ \t]+", " ", text).strip()[:200_000] or title,
              thread=e.origin, thread_name=str(PurePosixPath(e.path).parent), meta={"origin": e.origin, "path": e.path, "ext": ext})


# Leftovers nobody else read. Left out only: security files, viewer/app assets, mail indexes, other people's server art.
LEFTOVER_SECURITY = (r"login|logout|session|password|token|cookie|webhook|payment_source|reward_code|ip_address|"
                     r"ip.?audit|(^|[/_.])ip.?logs?\b|creation.?ip|registration|key.?registry|(^|/)sso\.|connected.?application|"
                     r"billing.?profile|security|device|authoriz|two_factor|recovery|credential|api_key")
LEFTOVER_OTHERS = META_SKIP + r"|(^|/)emoji(/|\.json$)"  # suggested people, other servers' custom emoji
LEFTOVER_NO_INFO = (r"(^|/)assets/|archive_browser|table_of_contents|(^|/)manifest\.js$|(^|/)emoji/|(^|/)icon\.[a-z]+$|(^|/)checkfile\.csv$|"
                    r"avatar\.[a-z]+$|Takeout/Keep/.*\.html$")
# Google Fit's files: its workouts are "sessions" and its data is by device, which aren't logins here.
FIT = re.compile(r"(^|/)Takeout(?: \d+)?/(?:Google )?Fit/")
# Fields inside a leftover record that are about the device or login, not the person: ad ids, IPs (TikTok's
# user_data_tiktok.json keeps them next to the watch history).
LEFTOVER_IDS = r"idfa|idfv|gaid|android.?id|advertis\w*.?id|(^|[._ ])ip($|[._ ])"
LEFTOVER_FIELDS = LEFTOVER_SECURITY + "|" + LEFTOVER_IDS
FILE_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".mp4", ".mov", ".m4a", ".aac", ".mp3", ".wav", ".svg")


def leftover_source(e):
    top = PurePosixPath(e.origin).parts[0] if e.origin else "imports"
    return re.sub(r"\W+", "_", "takeout" if top.lower().startswith("takeout") else top.lower())


def other_avenue(key):
    return f"Files in the {key} export that no specific parser reads, one record per item. {DROP}"


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
    """A date in a leftover field: ISO-like text (2024-01-13, or 2024/01/13), or Unix seconds/milliseconds, else None."""
    v = str(v).strip()
    if re.fullmatch(r"\d{10}(\.\d+)?", v):
        return from_unix(float(v))
    if re.fullmatch(r"\d{13}", v):
        return from_unix(int(v), "ms")
    # Goodreads writes 2024/01/13: the same date with slashes (or dots)
    v = re.sub(r"^(\d{4})[/.](\d{1,2})[/.](\d{1,2})\b", lambda d: f"{d[1]}-{int(d[2]):02d}-{int(d[3]):02d}", v)
    m = re.match(r"(\d{4}-\d{2}-\d{2})([T ]\d{2}:\d{2}(:\d{2})?)?", v)
    if m and 1900 <= int(v[:4]) <= 2100:
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
        if re.search(LEFTOVER_SECURITY, e.path, re.I) and not FIT.search(e.path) or re.search(LEFTOVER_NO_INFO, e.path) or \
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
            taken = tuple(".".join(p) + "." for p, _ in lists) + tuple(m + "." for m in MAPPED.get(e.path, ()))
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
        AV.setdefault(source, other_avenue(leftover_source(e)))
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


PARSERS = [ai_exports, google, youtube, google_chat, discord, meta, x_archive, csv_exports, spotify, whatsapp, slack, telegram, zoom,
           notion_export, mapped_exports, fitbit_days, other_documents, other_data, other_files]


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
    earlier run wrote and this one didn't (their files are now excluded or read by a real parser), and the sources of
    mappings taken out since (mapped_exports.SOURCES)."""
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
    for x in LEFT_OUT:  # what entries() didn't hand to the parsers: why, with the rest of its folder's
        folder = "/".join(PurePosixPath(x["path"]).parts[:-1][:4])
        g = groups.setdefault(f"{PurePosixPath(x['origin']).parts[0]} :: {folder}", {"files": 0, "bytes": 0, "examples": []})
        g["files"] += 1
        g["bytes"] += x["bytes"] or 0
        if x["why"] not in g.setdefault("left_out", []):
            g["left_out"].append(x["why"])
        if len(g["examples"]) < 3:
            g["examples"].append(PurePosixPath(x["path"] or x["origin"]).name)
    manifest = read_manifest()
    for source, m in list(manifest.items()):
        parser = str(m.get("parser", "")) if isinstance(m, dict) else ""
        # A catch-all (or one Fitbit's days went to) this run didn't write, or a mapping's source whose mapping was taken
        # out (its files are the catch-all's again: kept, they'd be counted twice). And a source of this Mac's or the
        # iPhone's that a mailbox replaced, before mail_source (one in imports/mail/ was read as Mail's mail): its file
        # holds only that mailbox, now read as <folder>_mail, so it goes, and its own connector reads it whole again.
        if parser.endswith((":other_data", ":other_files")) and source not in LEFTOVER_WRITTEN or \
                parser.endswith(":fitbit_days") and source not in FITBIT_WRITTEN or \
                parser.endswith(":mapped_exports") and source not in MAPPED_SOURCES or \
                parser == "connectors/imports.py:google" and (source in OTHER_SOURCES or source.startswith("phone_")):
            (CORPUS / "normalized" / f"{source}.jsonl").unlink(missing_ok=True)
            del manifest[source]
            print(f"[imports] removed {source}: no longer produced")
    manifest["_imports_unclaimed"] = [{"group": k, **g} for k, g in sorted(groups.items(), key=lambda kv: -kv[1]["bytes"])]
    remember_mailboxes(manifest)
    write_manifest(manifest)
    if _reclone.get(MEDIA) and MEDIA.is_dir():  # this run made the earlier copies clones
        common.MANIFEST.with_name(".media-cloned").write_text("1\n")
        _reclone[MEDIA] = False
    print(f"[imports] {sum(g['files'] for g in groups.values()):,} export files no parser read "
          f"({sum(g['bytes'] for g in groups.values()) / 1e6:,.0f} MB), listed in manifest.json _imports_unclaimed")


if __name__ == "__main__":
    main()
