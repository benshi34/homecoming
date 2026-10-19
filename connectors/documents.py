"""Personal documents on disk, in iCloud Drive and in cloud drives (OneDrive, Google Drive, Dropbox, Box), plus
Obsidian vaults kept anywhere: text from PDFs, Word/RTF, PowerPoint, Excel, CSV, web pages, Pages/Keynote/Numbers,
notebooks, Markdown/TeX/text; metadata-only records for creative projects (Ableton, GarageBand, MuseScore, Logic)
and Google Docs (only a link on disk). Skips code dependencies, datasets and build output."""

import json
import os
import plistlib
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path

from apple_notes import _fields, _varint
from common import HOME, LIB, NORM, RAW, ROOT, Writer, cloud_only, from_unix, ids_in, read_json, write_atomic
from email_parse import html_to_text

AVENUE = ("Filesystem walk of ~/Documents, ~/Desktop, ~/Downloads, ~/Library/Mobile Documents (iCloud Drive "
          "+ app containers like com~apple~Pages), each cloud drive's folder in ~/Library/CloudStorage (OneDrive, Google "
          "Drive, Dropbox, Box...) and ~/Dropbox, and the Obsidian vaults in ~/Library/Application Support/obsidian/"
          "obsidian.json that aren't inside those. A folder reached twice (~/Dropbox is often a link) is read once. "
          "Text: pypdf for PDF, macOS textutil for doc/docx/rtf/odt, zip+XML for pptx and xlsx (sheet names and cell "
          "text), IWA (snappy+protobuf) string walk for Pages/Keynote/Numbers, cell text for ipynb, tags stripped for "
          "html and webarchive. Heuristics drop dependencies, datasets (>5 .txt/.csv/.html per folder), exports and "
          "build output. Files only in the cloud (Optimize Mac Storage: .icloud placeholders before macOS 14, files "
          "flagged dataless since; cloud drives the same way) are listed but not read, so nothing is downloaded; one "
          "read before keeps what was read. A folder only in the cloud isn't walked. Google Docs/Sheets/Slides are only "
          "links on disk: name and dates. Left out as not yours: exports unzipped in Downloads (read from corpus/imports as "
          "exports) and Meta conversations anywhere, "
          "OneDrive's shared libraries, Google Drive's Shared drives and Other computers, and ~/Library under a vault set "
          "at the home folder. A spreadsheet whose header names passwords, one-time codes or secrets (a password "
          "manager's export) keeps only its name. A file unchanged since it was read (size, time: corpus/raw/documents/"
          "read.json) isn't read again: its record carries over.")

ROOTS = {"Documents": HOME / "Documents", "Desktop": HOME / "Desktop", "Downloads": HOME / "Downloads",
         "iCloud": HOME / "Library/Mobile Documents"}
CLOUD_STORAGE = HOME / "Library/CloudStorage"  # <Provider>-<account> folders, one per cloud drive app account
CLOUD_NAMES = {"OneDrive": "OneDrive", "GoogleDrive": "Google Drive", "Dropbox": "Dropbox", "Box": "Box",
               "ProtonDrive": "Proton Drive", "pCloud": "pCloud", "Nextcloud": "Nextcloud", "SynologyDrive": "Synology Drive"}
OBSIDIAN = HOME / "Library/Application Support/obsidian/obsidian.json"
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "env", "__pycache__", "site-packages", ".ipynb_checkpoints",
             "Library", ".Trash", "build", "dist", ".next", ".cache", "target", "DerivedData", "Pods", "_site",
             "Backup", "Samples", "Ableton Project Info", "imessage_export_mac", "babi_tasks", "LlamaFactory",
             "SWE-agent", "eval_output", "experiment_output", "train_output", "vendor", "third_party"}
VAULT_SKIP = {"node_modules"}  # a vault is notes: its "Library" or "Backup" folder is yours (.obsidian, .trash: hidden)
TEXT_EXT = {".pdf", ".docx", ".doc", ".rtf", ".odt", ".pptx", ".pages", ".key", ".numbers", ".ipynb", ".md",
            ".markdown", ".tex", ".txt", ".org", ".rst", ".xlsx", ".xlsm", ".csv", ".tsv", ".html", ".htm", ".webarchive"}
CREATIVE_EXT = {".als": "Ableton Live set", ".band": "GarageBand project", ".mscz": "MuseScore score",
                ".mscx": "MuseScore score", ".logicx": "Logic project", ".ptx": "Pro Tools session",
                ".flp": "FL Studio project", ".epub": "e-book"}
# Google Drive keeps a Google Doc as a small link file; what it says is online.
ONLINE_EXT = {".gdoc": "Google Docs document", ".gsheet": "Google Sheets spreadsheet",
              ".gslides": "Google Slides presentation", ".gdraw": "Google Drawings drawing", ".gform": "Google Forms form"}
# Plain text by the folderful is a dataset or a website, not something written: these are read only when a folder
# has 5 or fewer of them, and up to this size.
FEW_PER_FOLDER = {".txt": 2**20, ".csv": 2**20, ".tsv": 2**20, ".html": 5 * 2**20, ".htm": 5 * 2**20}
BOILERPLATE = re.compile(r"^(readme|license|licence|changelog|contributing|code_of_conduct|security|authors|notice|history)",
                         re.I)
MAX_BYTES = 60 * 2**20
MAX_CHARS = 200_000
# A password manager's or an authenticator's export (Chrome's Passwords.csv, 1Password's, Google Authenticator's):
# a header naming passwords, one-time codes or secrets. Only its name is kept, never what's in it.
SECRET_COLUMNS = re.compile(r"pass(word|wd|code)|otpauth|secret|totp|\b2fa\b|\bmfa\b", re.I)
# An export unzipped in Downloads, where it was downloaded (Safari unzips "safe" downloads): it's read as the export it
# is, from corpus/imports/, not as documents of yours. The same marks as desktop/src/main/downloads.ts looksLikeExport:
# what's at the top of one, and the names exports' folders have.
EXPORT_INSIDE = {"conversations.json", "your_instagram_activity", "your_facebook_activity", "channels.json", "Takeout",
                 "StreamingHistory_music_0.json", "Connections.csv", "tweets.js", "account.js"}
EXPORT_NAMES = re.compile(r"^(takeout\b|takeout-|instagram-|facebook-|export-|twitter-|discord|package|my_spotify_data|"
                          r"spotify (account data|extended streaming history)|mydata$|complete_linkedindataexport|"
                          r"basic_linkedindataexport|export_|whatsapp chat)", re.I)
MESSAGE_FILE = re.compile(r"^message_\d+\.(html|json)$")  # a Facebook or Instagram conversation, wherever it's put
# A cloud drive's folders that are other people's, not yours: OneDrive's and SharePoint's shared libraries (a folder
# of their own in CloudStorage), Google Drive's shared drives and the other computers it backs up.
SHARED_DRIVE = re.compile(r"-SharedLibraries-", re.I)
GOOGLE_NOT_MINE = ("Shared drives", "Other computers")
# Text read before, by path: its size and time then. A file unchanged since isn't read again; its record carries over.
READ = RAW / "documents" / "read.json"
READER = "1"


def snappy(data):
    """Raw snappy decompression (no framing)."""
    n, pos = _varint(data, 0)
    out = bytearray()
    while pos < len(data) and len(out) < n:
        tag = data[pos]
        pos += 1
        kind = tag & 3
        if kind == 0:
            ln = tag >> 2
            if ln >= 60:
                nb = ln - 59
                ln = int.from_bytes(data[pos:pos + nb], "little")
                pos += nb
            ln += 1
            out += data[pos:pos + ln]
            pos += ln
            continue
        if kind == 1:
            ln, off = ((tag >> 2) & 7) + 4, ((tag >> 5) << 8) | data[pos]
            pos += 1
        elif kind == 2:
            ln, off = (tag >> 2) + 1, int.from_bytes(data[pos:pos + 2], "little")
            pos += 2
        else:
            ln, off = (tag >> 2) + 1, int.from_bytes(data[pos:pos + 4], "little")
            pos += 4
        for _ in range(ln):
            out.append(out[-off])
    return bytes(out)


def _iwa_strings(buf, depth=0, out=None):
    out = [] if out is None else out
    try:
        for _, wt, v in _fields(buf):
            if wt != 2 or not v:
                continue
            try:
                s = v.decode("utf-8")
                if len(s) >= 3 and sum(c.isprintable() or c in "\n  \t" for c in s) / len(s) > 0.97 \
                        and (" " in s or len(s) > 20):
                    out.append(s)
                    continue
            except UnicodeDecodeError:
                pass
            if depth < 4:
                _iwa_strings(v, depth + 1, out)
    except (IndexError, ValueError):
        pass
    return out


def iwork_text(path):
    """Best-effort body text of a Pages/Keynote/Numbers file (zip of .iwa protobuf streams)."""
    texts = []
    with zipfile.ZipFile(path) as z:
        for name in sorted(n for n in z.namelist() if n.endswith(".iwa") and "Stylesheet" not in n
                           and "Metadata" not in n and "ViewState" not in n):
            raw, pos, data = z.read(name), 0, bytearray()
            while pos + 4 <= len(raw):
                ln = int.from_bytes(raw[pos + 1:pos + 4], "little")
                data += snappy(raw[pos + 4:pos + 4 + ln])
                pos += 4 + ln
            pos = 0
            while pos < len(data):
                n, pos = _varint(data, pos)
                info, pos = bytes(data[pos:pos + n]), pos + n
                for f, wt, mi in _fields(info):
                    if f == 2 and wt == 2:
                        length = next((v for ff, wtt, v in _fields(mi) if ff == 3 and wtt == 0), 0)
                        texts += _iwa_strings(bytes(data[pos:pos + length]))
                        pos += length
    return "\n".join(t.replace(" ", "\n") for t in dict.fromkeys(texts))


def pdf_text(path):
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    parts = []
    for page in reader.pages[:60]:
        parts.append(page.extract_text() or "")
        if sum(map(len, parts)) > MAX_CHARS:
            break
    return "\n".join(parts)


def pptx_text(path):
    with zipfile.ZipFile(path) as z:
        slides = sorted((n for n in z.namelist() if re.match(r"ppt/(slides|notesSlides)/\w+\.xml$", n)),
                        key=lambda n: (n.split("/")[1], int(re.sub(r"\D", "", n) or 0)))
        return "\n".join(" ".join(re.findall(r"<a:t(?:\s[^>]*)?>([^<]*)</a:t>", z.read(n).decode("utf-8", "ignore"))) for n in slides)


def ipynb_text(path):
    nb = json.loads(path.read_text(errors="ignore"))
    cells = nb.get("cells") or []
    return "\n\n".join("".join(c.get("source", [])) for c in cells if c.get("cell_type") in ("markdown", "code"))


XL = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
XL_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def xlsx_text(path):
    """Each sheet's name, then its rows, cells joined by " | " (shared and inline strings, numbers and formula results
    as stored: a date is Excel's day number)."""
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        shared = []
        if "xl/sharedStrings.xml" in names:
            for _, el in ET.iterparse(z.open("xl/sharedStrings.xml")):
                if el.tag == XL + "si":
                    shared.append("".join(t.text or "" for t in el.iter(XL + "t")))
                    el.clear()
                    if len(shared) > 100_000:  # far more than the text kept: a data table, not a document
                        break
        targets = {}
        if "xl/_rels/workbook.xml.rels" in names:
            for r in ET.parse(z.open("xl/_rels/workbook.xml.rels")).getroot():
                t = r.get("Target") or ""
                targets[r.get("Id")] = t.lstrip("/") if t.startswith("/") else "xl/" + t
        out, size = [], 0
        for sheet in ET.parse(z.open("xl/workbook.xml")).getroot().iter(XL + "sheet"):
            part = targets.get(sheet.get(XL_REL))
            if part not in names or size > MAX_CHARS:
                continue
            out.append(f"Sheet: {sheet.get('name')}")
            for _, el in ET.iterparse(z.open(part)):
                if el.tag != XL + "row":
                    continue
                cells = []
                for c in el.iter(XL + "c"):
                    t, v = c.get("t"), c.find(XL + "v")
                    if t == "inlineStr":
                        cells.append("".join(x.text or "" for x in c.iter(XL + "t")))
                    elif v is None or v.text is None:
                        continue
                    elif t == "s":
                        i = int(v.text) if v.text.isdigit() else -1
                        cells.append(shared[i] if 0 <= i < len(shared) else "")
                    elif t == "b":
                        cells.append("TRUE" if v.text == "1" else "FALSE")
                    else:
                        cells.append(v.text)
                el.clear()
                line = " | ".join(x.strip() for x in cells if x and x.strip())
                if line:
                    out.append(line)
                    size += len(line)
                if size > MAX_CHARS:
                    break
        return "\n".join(out)


def decode(data):
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", "replace")


def webarchive_text(path):
    """Safari's saved page: a plist whose main resource is the page's HTML."""
    main = plistlib.loads(path.read_bytes()).get("WebMainResource") or {}
    data = main.get("WebResourceData") or b""
    try:
        html = data.decode(main.get("WebResourceTextEncodingName") or "utf-8")
    except (LookupError, UnicodeDecodeError):
        html = decode(data)
    return html_to_text(html)


def extract(path, ext):
    if ext == ".pdf":
        return pdf_text(path)
    if ext in (".docx", ".doc", ".rtf", ".odt"):
        return subprocess.run(["textutil", "-convert", "txt", "-stdout", str(path)], capture_output=True,
                              text=True, timeout=60).stdout
    if ext == ".pptx":
        return pptx_text(path)
    if ext in (".xlsx", ".xlsm"):
        return xlsx_text(path)
    if ext in (".pages", ".key", ".numbers"):
        return iwork_text(path)
    if ext == ".ipynb":
        return ipynb_text(path)
    if ext in (".html", ".htm"):
        return html_to_text(decode(path.read_bytes()))
    if ext == ".webarchive":
        return webarchive_text(path)
    return path.read_text(errors="ignore")


def cloud_drives():
    """(name, folder) for each cloud drive: ~/Library/CloudStorage/<Provider>-<account>, and ~/Dropbox (or "Dropbox
    (Personal)") from before Dropbox moved there, now often a link to it."""
    try:
        found = sorted(CLOUD_STORAGE.iterdir())
    except OSError:
        found = []
    out = []
    for p in [*found, *sorted(HOME.glob("Dropbox*"))]:
        if p.is_dir() and not SHARED_DRIVE.search(p.name):  # a shared library is other people's files
            provider = p.name.split("-", 1)[0].split(" (", 1)[0]
            out.append((CLOUD_NAMES.get(provider, provider), p))
    return out


def not_mine(label, root):
    """A drive's folders of other people's files, left out: Google Drive's shared drives and other computers."""
    return {Path(root) / d for d in GOOGLE_NOT_MINE} if label == "Google Drive" else set()


def secret_columns(text, ext):
    """Whether a table's header (each sheet's first row) names passwords, one-time codes or secrets."""
    lines = text.splitlines()
    heads = lines[:1] if ext in (".csv", ".tsv") else [lines[i + 1] for i, x in enumerate(lines[:-1]) if x.startswith("Sheet: ")]
    return any(SECRET_COLUMNS.search(h) for h in heads) or "otpauth://" in text[:50_000]


def looks_like_export(dp, dns, fns, downloads):
    """An unzipped export: a Meta conversation anywhere; in Downloads, where exports land, also what's at the top of one,
    or its folder's name. (Elsewhere a folder holding, say, a Takeout folder may hold your own files too.)"""
    if any(MESSAGE_FILE.match(f) for f in fns):
        return True
    if not downloads:
        return False
    if (set(dns) | set(fns)) & EXPORT_INSIDE or any(n.startswith(("Streaming_History", "StreamingHistory")) for n in fns):
        return True
    if EXPORT_NAMES.match(os.path.basename(dp)):
        return True
    if "data" in dns:
        try:
            return bool({"tweets.js", "account.js"} & set(os.listdir(os.path.join(dp, "data"))))
        except OSError:
            return False
    return False


def obsidian_vaults():
    """The vault folders Obsidian knows (obsidian.json), wherever they are."""
    try:
        vaults = json.loads(OBSIDIAN.read_text()).get("vaults") or {}
    except (OSError, ValueError, AttributeError):
        return []
    return [Path(v["path"]).expanduser() for v in vaults.values() if isinstance(v, dict) and v.get("path")]


def roots(notes=None):
    """(label, folder) for every folder read: the usual ones, each cloud drive, then Obsidian vaults; and their real
    paths. A folder that is another one, or inside one (a vault in Documents, ~/Dropbox linking to CloudStorage),
    isn't read again."""
    notes = {} if notes is None else notes
    out, real = [], []
    for label, p in [*ROOTS.items(), *cloud_drives(), *(("Obsidian", v) for v in obsidian_vaults())]:
        r = Path(os.path.realpath(p))
        if label == "Obsidian" and r.parts[1:2] == ("Volumes",):  # another disk: macOS would ask first
            notes["vaults_on_other_disks"] = notes.get("vaults_on_other_disks", 0) + 1
            continue
        if not r.is_dir() or any(r == q or q in r.parents for q in real):
            continue
        real.append(r)
        out.append((label, p))
    return out, set(real)


def walk(root, skip=SKIP_DIRS, others=(), notes=None, left=None, downloads=False):
    """Every file under root, with how many of each kind its folder has. A folder that is another root (OneDrive
    holding Documents) is left to that one. Not walked: a folder only in the cloud (listing it would download the list,
    and its files aren't here to read), and an unzipped export (left, with its path, in `left`)."""
    notes = {} if notes is None else notes
    left = [] if left is None else left
    if cloud_only(root):
        notes["folders_in_the_cloud_only"] = notes.get("folders_in_the_cloud_only", 0) + 1
        return
    for dp, dns, fns in os.walk(root):
        if dp != str(root) and looks_like_export(dp, dns, fns, downloads):
            left.append(dp)
            notes["unzipped_exports"] = notes.get("unzipped_exports", 0) + 1
            dns[:] = []
            continue
        dns[:] = [d for d in dns if d not in skip and not d.startswith(".")
                  and not d.endswith((".app", ".photoslibrary", ".framework", ".bundle", ".xcodeproj", ".logicx"))
                  and not (d.endswith("_files") and {d[:-6] + ".html", d[:-6] + ".htm"} & set(fns))  # a saved page's parts
                  and not (Path(dp, d) == ROOT / "corpus") and Path(dp, d) not in others]
        for d in [d for d in dns if cloud_only(os.path.join(dp, d))]:
            dns.remove(d)
            notes["folders_in_the_cloud_only"] = notes.get("folders_in_the_cloud_only", 0) + 1
        if "package.json" in fns and len(Path(dp).relative_to(root).parts) > 1:
            dns[:] = []  # a JavaScript package: skip its docs and dependencies
            continue
        counts = Counter(os.path.splitext(f[:-len(".icloud")] if f.endswith(".icloud") else f)[1].lower() for f in fns)
        for f in fns:
            yield Path(dp, f), counts
        for d in list(dns):  # .logicx / package-style projects appear as directories
            if d.endswith(".logicx"):
                yield Path(dp, d), counts


def main():
    # Files an earlier run read: one now only in iCloud keeps that record rather than becoming a name, and one unchanged
    # since isn't read again (READ): its record carries over.
    before = ids_in(NORM / "documents.jsonl")
    cache = read_json(READ, {})
    was = (cache.get("files") or {}) if isinstance(cache, dict) and cache.get("reader") == READER else {}
    files = {}  # text read this time: its size and time
    # Folders not walked because what's in them isn't yours: unzipped exports, other people's shared folders, ~/Library
    # under a vault set at your home folder. An earlier run's records of files in them aren't kept.
    left = [str(p) for p in (sorted(CLOUD_STORAGE.iterdir()) if CLOUD_STORAGE.is_dir() else []) if SHARED_DRIVE.search(p.name)]
    forget = lambda rec: any(str((rec.get("meta") or {}).get("path") or rec.get("id") or "").startswith(d.rstrip("/") + "/")  # noqa: E731
                             for d in left)
    with Writer("documents", AVENUE, forget=forget) as w:
        folders, real = roots(w.notes)
        real |= {Path(p) for _, p in folders}  # each root as found too: a walk meets them by that path, not the real one
        for label, root in folders:
            drive = label not in ROOTS and label != "Obsidian"  # a cloud drive's folder
            away = label if drive else "iCloud" if label in ROOTS else "the cloud"  # where a file not downloaded is
            only = "in_cloud_drive_only" if drive else "in_icloud_only"
            vault = {"vault": Path(root).name} if label == "Obsidian" else {}
            others = real - {Path(os.path.realpath(root)), Path(root)} | not_mine(label, root)
            if label == "Obsidian" and LIB.is_relative_to(Path(root)):
                others |= {LIB}  # a vault set at your home folder: never ~/Library
            left += [str(p) for p in others - real]
            for path, counts in walk(root, VAULT_SKIP if label == "Obsidian" else SKIP_DIRS, others, w.notes, left,
                                     downloads=label == "Downloads"):
                name = path.name
                if name.endswith(".icloud"):  # not downloaded: ".Name.ext.icloud"
                    real_name = name[1:-len(".icloud")] if name.startswith(".") else name[:-len(".icloud")]
                    ext = os.path.splitext(real_name)[1].lower()
                    if (ext in TEXT_EXT or ext in CREATIVE_EXT) and not (ext in FEW_PER_FOLDER and counts[ext] > 5):
                        st = path.stat()
                        w.add(id=str(path), kind="document", ts=from_unix(st.st_mtime), author="me", title=real_name,
                              text=f"{real_name} (in iCloud, not downloaded)", thread=label, thread_name=str(path.parent),
                              meta={"root": label, "path": str(path.parent / real_name), "downloaded": False, **vault})
                    continue
                ext = path.suffix.lower()
                try:
                    st = path.stat()  # only the file's details: this doesn't download it
                except OSError:
                    continue
                if ext in ONLINE_EXT:  # the document itself is online: on disk, only a link to it (not opened)
                    w.add(id=str(path), kind="document", ts=from_unix(st.st_mtime), author="me", title=path.stem,
                          text=f"{ONLINE_EXT[ext]}: {path.stem}\nFolder: {path.parent.name}", thread=label,
                          thread_name=str(path.parent),
                          meta={"root": label, "path": str(path), "type": ONLINE_EXT[ext], "online": True,
                                "created": from_unix(getattr(st, "st_birthtime", 0))})
                    continue
                if cloud_only(path):  # reading it would download it: its name and dates only
                    if (ext in TEXT_EXT or ext in CREATIVE_EXT) and str(path) not in before \
                            and not (ext in FEW_PER_FOLDER and counts[ext] > 5):
                        w.add(id=str(path), kind="document", ts=from_unix(st.st_mtime), author="me", title=name,
                              text=f"{name} (in {away}, not downloaded)", thread=label, thread_name=str(path.parent),
                              meta={"root": label, "path": str(path), "downloaded": False, "bytes": st.st_size, **vault})
                    w.notes[only] = w.notes.get(only, 0) + 1
                    continue
                if ext in CREATIVE_EXT:
                    w.add(id=str(path), kind="document", ts=from_unix(st.st_mtime), author="me", is_me=True,
                          title=path.stem, text=f"{CREATIVE_EXT[ext]}: {path.stem}\nFolder: {path.parent.name}",
                          thread=label, thread_name=str(path.parent),
                          meta={"root": label, "path": str(path), "type": CREATIVE_EXT[ext], "bytes": st.st_size,
                                "created": from_unix(getattr(st, "st_birthtime", 0))})
                    continue
                if ext not in TEXT_EXT or st.st_size > MAX_BYTES or st.st_size == 0:
                    continue
                if ext in FEW_PER_FOLDER and (counts[ext] > 5 or st.st_size > FEW_PER_FOLDER[ext]):
                    continue
                if ext in (".md", ".markdown", ".txt", ".rst") and BOILERPLATE.match(name) \
                        and label not in ("Documents", "Obsidian"):
                    continue
                sig = [st.st_size, st.st_mtime_ns]
                files[str(path)] = sig
                if was.get(str(path)) == sig and str(path) in before:
                    continue  # unchanged since it was read: its record carries over
                try:
                    text = extract(path, ext) or ""
                except Exception as e:  # unreadable / encrypted / malformed file: keep metadata only
                    text, err = "", type(e).__name__
                else:
                    err = None
                secret = ext in (".csv", ".tsv", ".xlsx", ".xlsm") and secret_columns(text, ext)
                if secret:  # passwords or one-time codes: only that the file is there
                    text = ""
                    w.notes["password_files"] = w.notes.get("password_files", 0) + 1
                text = re.sub(r"[ \t]+", " ", text).strip()[:MAX_CHARS]
                w.add(id=str(path), kind="document", ts=from_unix(st.st_mtime), author="me", title=name,
                      text=text or name, thread=label, thread_name=str(path.parent),
                      meta={k: v for k, v in (("root", label), ("path", str(path)), ("ext", ext), ("bytes", st.st_size),
                                              ("created", from_unix(getattr(st, "st_birthtime", 0))),
                                              ("error", err), ("chars", len(text)),
                                              ("left_out", "passwords or codes: only its name is kept" if secret else None),
                                              *vault.items()) if v})
    write_atomic(READ, json.dumps({"reader": READER, "files": files}))


if __name__ == "__main__":
    main()
