"""Exports in formats no parser knows, read with a mapping: which files hold which kind of item, and which of
an item's fields are its time, text, title, author and thread.

A mapping is data, never code. The desktop app has Claude write one from the export's structure (field names
and shapes, plus example values only if the person allows it), runs it over the whole export to show what it
gets, and saves it once the person confirms: corpus/mappings/<folder>.json, for corpus/imports/<folder>/.
imports.py applies them before its catch-alls, so mapped files aren't also kept as generic records.

  {"service": "Wattpad", "version": 1, "items": [
     {"describe": "Stories you wrote", "file": "**/stories.json", "path": "stories", "kind": "post",
      "time": "createDate", "title": "title", "text": ["description", "tags"], "author": "me",
      "thread": "id", "url": "url", "id": "id"}]}

file: a glob matched against the path inside the export (and against the file name alone). path: dot path to
the list of items in the file ("" = the file itself; CSV files are lists of rows). author: a field, or "me"
for things the export's owner made. Any field can be a dot path ("user.name") and text takes a list. zone: "UTC"
when the export's times carry no zone but are UTC (TikTok's are); otherwise they're read as this Mac's time.
A rule with a path takes only that list: the rest of the file is still kept by imports.py's catch-all, so a
mapping that names a few lists loses nothing it doesn't name.
"""

import csv
import io
import json
import re
from fnmatch import fnmatch
from pathlib import PurePosixPath

from common import CORPUS

MAPPINGS = CORPUS / "mappings"
MAPPED = {}  # export path -> dot paths of the lists a mapping read there (the catch-all leaves those out)
SOURCES = set()  # the sources this run's mappings wrote: one whose mapping was taken out is removed (imports.py)
KINDS = {"post", "message", "comment", "note", "event", "reminder", "visit", "search", "purchase", "transaction",
         "trip", "media", "listen", "watch", "read", "review", "contact", "follow", "like", "photo", "document",
         "activity", "record"}
FIELDS = ("time", "title", "text", "author", "thread", "thread_name", "url", "id")


def folder_key(folder):
    """The source a folder's mapped records go to: what imports.py's catch-alls would prefix with."""
    return re.sub(r"\W+", "_", folder.lower())


def load():
    if not MAPPINGS.is_dir():
        return {}
    out = {}
    for p in sorted(MAPPINGS.glob("*.json")):
        try:
            out[p.stem] = validate(json.loads(p.read_text()))
        except (ValueError, OSError):
            continue
    return out


def validate(m):
    """The mapping, cleaned: unknown keys dropped, kinds limited to KINDS. Raises ValueError if unusable."""
    if not isinstance(m, dict) or not isinstance(m.get("items"), list) or not m["items"]:
        raise ValueError("a mapping needs a list of items")
    items = []
    for r in m["items"]:
        if not isinstance(r, dict) or not isinstance(r.get("file"), str) or not r["file"].strip():
            raise ValueError("each item needs a file pattern")
        clean = {"file": r["file"].strip(), "path": str(r.get("path") or ""), "describe": str(r.get("describe") or r["file"])[:120],
                 "kind": r.get("kind") if r.get("kind") in KINDS else "record"}
        if str(r.get("zone") or "").upper() == "UTC":
            clean["zone"] = "UTC"
        for k in FIELDS:
            v = r.get(k)
            if k == "text":
                v = [v] if isinstance(v, str) else [x for x in v if isinstance(x, str)] if isinstance(v, list) else []
                if v:
                    clean[k] = v
            elif isinstance(v, str) and v:
                clean[k] = v
        items.append(clean)
    return {"service": str(m.get("service") or ""), "version": 1, "items": items}


def get(obj, path):
    for part in (path or "").split("."):
        if part == "":
            continue
        if isinstance(obj, dict):
            obj = obj.get(part)
        elif isinstance(obj, list) and part.isdigit() and int(part) < len(obj):
            obj = obj[int(part)]
        else:
            return None
    return obj


def parse(e):
    name = e.path.lower()
    if name.endswith(".csv"):
        return list(csv.DictReader(io.StringIO(e.text())))
    text = e.text()
    if name.endswith(".js"):  # window.YTD.x.part0 = [...] and friends
        text = text[text.find("=") + 1:] if re.match(r"^\s*[\w.$\[\]'\"]+\s*=", text) else text
    return json.loads(text)


def scalar(v):
    if isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, list) and all(isinstance(x, (str, int, float)) for x in v):
        return ", ".join(str(x) for x in v[:30])
    return None


def matches(rule, path):
    return fnmatch(path, rule["file"]) or fnmatch(PurePosixPath(path).name, rule["file"]) or \
        fnmatch(path, f"*/{rule['file']}")


def utc(v):
    """A zoneless time marked UTC ("2026-06-13 07:51:55" -> "2026-06-13 07:51:55 UTC"); anything else as it is."""
    if isinstance(v, str) and re.match(r"\d{4}-\d\d-\d\d[T ]\d\d:\d\d", v.strip()) and \
            not re.search(r"(Z|[+-]\d\d:?\d\d|UTC|GMT)$", v.strip(), re.I):
        return v.strip() + " UTC"
    return v


def records(mapping, entries, when=None, is_me=None):
    """(rule index, entry, record) for every item a mapping finds. when(value) -> ISO time or None;
    is_me(value) -> whether an author value is the export's owner."""
    when = when or (lambda v: None)
    is_me = is_me or (lambda v: False)
    for e in entries:
        rules = [(i, r) for i, r in enumerate(mapping["items"]) if matches(r, e.path)]
        if not rules:
            continue
        try:
            data = parse(e)
        except (ValueError, UnicodeDecodeError):
            continue
        for i, r in rules:
            items = get(data, r["path"]) if r["path"] else data
            if isinstance(items, dict):
                items = [items]
            if not isinstance(items, list):
                continue
            for n, it in enumerate(items):
                it = it if isinstance(it, dict) else {"value": it}
                text = "\n".join(str(scalar(get(it, f))) for f in r.get("text", []) if scalar(get(it, f)) not in (None, ""))
                title = scalar(get(it, r["title"])) if r.get("title") else None
                author = "me" if r.get("author") == "me" else scalar(get(it, r["author"])) if r.get("author") else None
                ident = scalar(get(it, r["id"])) if r.get("id") else None
                fields = {k: scalar(v) for k, v in it.items() if scalar(v) not in (None, "")}
                rec = {"id": f"{e.path}#{r['path']}#{ident if ident not in (None, '') else n}", "kind": r["kind"],
                       "ts": when(utc(get(it, r["time"])) if r.get("zone") == "UTC" else get(it, r["time"])) if r.get("time") else None,
                       "title": str(title)[:300] if title not in (None, "") else None,
                       "text": text or (str(title) if title else "; ".join(f"{k}: {v}" for k, v in list(fields.items())[:20])),
                       "author": str(author) if author not in (None, "") else None,
                       "is_me": author == "me" or (author is not None and is_me(str(author))),
                       "thread": str(scalar(get(it, r["thread"]))) if r.get("thread") and scalar(get(it, r["thread"])) is not None else None,
                       "thread_name": str(scalar(get(it, r["thread_name"]))) if r.get("thread_name") and scalar(get(it, r["thread_name"])) is not None else None,
                       "url": str(scalar(get(it, r["url"]))) if r.get("url") and scalar(get(it, r["url"])) else None,
                       "meta": {"file": e.path, "mapped": r["describe"], "fields": dict(list(fields.items())[:40])}}
                yield i, e, {k: v for k, v in rec.items() if v is not None}


def mapped_exports(es, W, used):
    """imports.py parser: every corpus/imports/<folder>/ with a mapping -> source <folder>. An item whose id another
    one has already (a mapping that names a field that isn't unique) is skipped and counted, not a failure: one
    mapping's mistake mustn't stop the others."""
    SOURCES.clear()
    maps = load()
    if not maps:
        return
    from identity import is_me_email, is_me_name
    from imports import AV, DROP, leftover_time
    for folder, m in maps.items():
        mine = [e for e in es if e.path not in used and (PurePosixPath(e.origin).parts[:1] == (folder,) if e.origin else False)]
        source = folder_key(folder)
        SOURCES.add(source)
        AV.setdefault(source, f"The {m['service'] or folder} export in corpus/imports/{folder}/, read with the mapping in "
                              f"corpus/mappings/{folder}.json. {DROP}")
        for i, e, rec in records(m, mine, when=leftover_time, is_me=lambda a: is_me_name(a) or is_me_email(a)):
            w = W(source)
            if w.has(rec["id"]):
                w.notes["same_id_as_another"] = w.notes.get("same_id_as_another", 0) + 1
            else:
                w.add(**rec)
            if m["items"][i]["path"]:
                MAPPED.setdefault(e.path, set()).add(m["items"][i]["path"])
            else:
                used.add(e.path)
