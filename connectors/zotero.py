"""Zotero: the papers, books and pages you saved, your notes on them and your highlights in their PDFs.

Two ways in, read the same way:
  - zotero.org's API, with a key (zotero.org/settings/keys): your library and every group the key can read, whether or
    not the Zotero app is on this Mac. The key comes from UMP_ZOTERO_KEY, else the Keychain item "Homecoming Zotero".
  - the Zotero app's database on this Mac (zotero.sqlite in its data folder), for a library that isn't synced.
An item is "<library>:<key>" either way (user, or group:<id>), so a library read both ways is kept once, the API's
copy first: it says who added an item to a group."""

import json
import os
import re
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request

from common import HOME, LIB, Writer, connect, snapshot_sqlite
from email_parse import html_to_text

API = "https://api.zotero.org"
KEYCHAIN = "Homecoming Zotero"
AVENUE = ("zotero.org's API (v3) with a read key from UMP_ZOTERO_KEY or the Keychain item \"Homecoming Zotero\": "
          "/keys/current says whose key it is and which libraries it reads; /users/<id>/items and /groups/<id>/items "
          "(100 at a time), /collections, /users/<id>/groups for groups' names; meta.createdByUser says who added a "
          "group's item. Else, or as well, the Zotero app's zotero.sqlite (data folder from prefs.js's "
          "extensions.zotero.dataDir, else ~/Zotero): items + itemData/fieldsCombined, creators, collections, tags, "
          "itemNotes, itemAnnotations (deletedItems left out). Items: kind reference; notes: note; PDF highlights and "
          "comments: highlight. Attachments aren't records: a PDF's highlights name the item it's attached to.")

ANNOTATION_TYPES = {1: "highlight", 2: "note", 3: "image", 4: "ink", 5: "underline", 6: "text"}
SKIP_TYPES = {"attachment"}


# ---------------------------------------------------------------- the API

def api_key():
    if os.environ.get("UMP_ZOTERO_KEY"):
        return os.environ["UMP_ZOTERO_KEY"].strip()
    try:
        r = subprocess.run(["security", "find-generic-password", "-w", "-s", KEYCHAIN], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() or None if r.returncode == 0 else None


def get(path, key):
    """One API call, as (JSON, headers). Waits out a Backoff or Retry-After, as the API asks."""
    base = os.environ.get("UMP_ZOTERO_API") or API
    for attempt in range(4):
        req = urllib.request.Request(base + path, headers={"Zotero-API-Version": "3", "Zotero-API-Key": key})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body, headers = json.loads(r.read().decode() or "null"), r.headers
            wait = headers.get("Backoff")
            if wait:
                time.sleep(min(float(wait), 60))
            return body, headers
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < 3:
                time.sleep(min(float(e.headers.get("Retry-After") or 5), 60))
                continue
            raise


def pages(path, key):
    """Every item of a list the API gives 100 at a time."""
    start = 0
    while True:
        sep = "&" if "?" in path else "?"
        items, headers = get(f"{path}{sep}limit=100&start={start}", key)
        yield from items or []
        start += len(items or [])
        if not items or start >= int(headers.get("Total-Results") or 0):
            return


def from_api(key, w):
    """(library id, its name, mine?) -> its items, as the API's data objects with who added each."""
    info, _ = get("/keys/current", key)
    user = info.get("userID")
    access = info.get("access") or {}
    libraries = []
    if (access.get("user") or {}).get("library"):
        libraries.append(("user", f"/users/{user}", "My Library"))
    groups = access.get("groups") or {}
    if groups:
        names = {}
        try:
            names = {str(g["id"]): (g.get("data") or {}).get("name") for g in pages(f"/users/{user}/groups", key)}
        except urllib.error.HTTPError:
            pass  # a key that reads groups but can't list them: their ids name them
        ids = list(names) if "all" in groups else [g for g in groups if (groups[g] or {}).get("library")]
        libraries += [(f"group:{g}", f"/groups/{g}", names.get(g) or f"Zotero group {g}") for g in ids]
    out = []
    for lib, path, name in libraries:
        try:
            collections = {c["key"]: (c.get("data") or {}).get("name") for c in pages(f"{path}/collections", key)}
            items = []
            for it in pages(f"{path}/items", key):
                d = dict(it.get("data") or {})
                by = ((it.get("meta") or {}).get("createdByUser") or {})
                d["_by"] = by.get("username") if lib != "user" else None
                d["_mine"] = lib == "user" or (user is not None and by.get("id") == user)
                items.append(d)
        except urllib.error.HTTPError as e:
            w.notes.setdefault("not_read", {})[lib] = f"HTTP {e.code}"
            continue
        out.append((lib, name, collections, items))
    return out


# ---------------------------------------------------------------- the app's database

def data_dir():
    """The Zotero app's data folder: where its prefs.js says, else ~/Zotero."""
    for prefs in (LIB / "Application Support/Zotero/Profiles").glob("*/prefs.js"):
        m = re.search(r'user_pref\("extensions\.zotero\.dataDir",\s*"([^"]+)"\)', prefs.read_text(errors="replace"))
        if m:
            return os.path.expanduser(m.group(1))
    return str(HOME / "Zotero")


def from_app(db):
    """The same as from_api, from zotero.sqlite: items in the API's shape, the trash left out."""
    con = connect(snapshot_sqlite(db, "zotero/zotero.sqlite"))
    have = {r[0] for r in con.execute("select name from sqlite_master")}
    types = "itemTypesCombined" if "itemTypesCombined" in have else "itemTypes"
    fields = "fieldsCombined" if "fieldsCombined" in have else "fields"
    libs = {}
    for r in con.execute("select libraryID, type from libraries"):
        libs[r["libraryID"]] = ("user", "My Library") if r["type"] == "user" else None
    if "groups" in have:
        for r in con.execute("select groupID, libraryID, name from groups"):
            libs[r["libraryID"]] = (f"group:{r['groupID']}", r["name"])
    deleted = {r[0] for r in con.execute("select itemID from deletedItems")} if "deletedItems" in have else set()
    rows = {r["itemID"]: r for r in con.execute(f"select i.itemID, i.key, i.libraryID, i.dateAdded, i.dateModified, t.typeName "
                                                f"from items i join {types} t using (itemTypeID)")}
    keys = {i: r["key"] for i, r in rows.items()}
    data = {i: {"key": r["key"], "itemType": r["typeName"], "dateAdded": r["dateAdded"], "dateModified": r["dateModified"],
                "creators": [], "tags": [], "collections": []} for i, r in rows.items()}
    for r in con.execute(f"select d.itemID, f.fieldName, v.value from itemData d join {fields} f using (fieldID) "
                         "join itemDataValues v using (valueID)"):
        if r["itemID"] in data:
            data[r["itemID"]][r["fieldName"]] = r["value"]
    for r in con.execute("select ic.itemID, c.firstName, c.lastName, c.fieldMode, ct.creatorType from itemCreators ic "
                         "join creators c using (creatorID) join creatorTypes ct using (creatorTypeID) order by ic.itemID, ic.orderIndex"):
        if r["itemID"] in data:
            data[r["itemID"]]["creators"].append({"name": r["lastName"], "creatorType": r["creatorType"]} if r["fieldMode"] == 1 else
                                                 {"firstName": r["firstName"], "lastName": r["lastName"], "creatorType": r["creatorType"]})
    for r in con.execute("select it.itemID, t.name from itemTags it join tags t using (tagID)"):
        if r["itemID"] in data:
            data[r["itemID"]]["tags"].append({"tag": r["name"]})
    collections = {}
    for r in con.execute("select c.collectionID, c.key, c.collectionName, c.libraryID from collections c"):
        collections[r["collectionID"]] = (r["key"], r["collectionName"])
    for r in con.execute("select collectionID, itemID from collectionItems"):
        if r["itemID"] in data and r["collectionID"] in collections:
            data[r["itemID"]]["collections"].append(collections[r["collectionID"]][0])
    for r in con.execute("select itemID, parentItemID, note from itemNotes"):
        if r["itemID"] in data:
            data[r["itemID"]].update(note=r["note"], parentItem=keys.get(r["parentItemID"]))
    for r in con.execute("select itemID, parentItemID from itemAttachments"):
        if r["itemID"] in data and r["parentItemID"]:
            data[r["itemID"]]["parentItem"] = keys.get(r["parentItemID"])
    if "itemAnnotations" in have:
        for r in con.execute("select itemID, parentItemID, type, text, comment, color, pageLabel from itemAnnotations"):
            if r["itemID"] in data:
                data[r["itemID"]].update(parentItem=keys.get(r["parentItemID"]), annotationType=ANNOTATION_TYPES.get(r["type"], "highlight"),
                                         annotationText=r["text"], annotationComment=r["comment"], annotationColor=r["color"],
                                         annotationPageLabel=r["pageLabel"])
    con.close()
    out = {}
    for i, d in data.items():
        lib = libs.get(rows[i]["libraryID"])
        if not lib or i in deleted:
            continue
        d["_mine"], d["_by"] = lib[0] == "user", None
        out.setdefault(lib, []).append(d)
    names = {k: n for k, n in collections.values()}
    return [(lib, name, names, items) for (lib, name), items in out.items()]


# ---------------------------------------------------------------- records

def note_text(html):
    """A note's text: Zotero writes headings and quotes as their own blocks, which html_to_text runs together."""
    text = html_to_text(re.sub(r"(?i)</(h[1-6]|blockquote|pre)>", "\n", html or ""))
    return "\n".join(line.strip() for line in text.split("\n"))


def person(c):
    return c.get("name") or " ".join(x for x in (c.get("firstName"), c.get("lastName")) if x)


def zotero_time(s):
    """Zotero's times: ISO (the API) or "2024-01-13 10:00:00", UTC (the app's database)."""
    if not s:
        return None
    s = str(s)
    return s if "T" in s else s.replace(" ", "T") + "Z"


def write(w, lib, name, collections, items):
    by_key = {d["key"]: d for d in items}

    def top(d):  # an annotation's parent is the PDF; the PDF's, the item
        seen = 0
        while d and d.get("parentItem") and seen < 3:
            d, seen = by_key.get(d["parentItem"]), seen + 1
        return d

    thread = f"zotero:{lib}"
    for d in items:
        t, rid = d.get("itemType"), f"{lib}:{d.get('key')}"
        if t in SKIP_TYPES or not d.get("key") or w.has(rid):
            w.notes["attachments"] = w.notes.get("attachments", 0) + (t == "attachment")
            continue
        common = dict(id=rid, ts=zotero_time(d.get("dateAdded")), author="me" if d["_mine"] else d.get("_by") or "someone",
                      is_me=d["_mine"], thread=thread, thread_name=name)
        if t == "note":
            parent = top(d)
            title = (parent or {}).get("title")
            w.add(kind="note", title=f"Note on {title}" if title else "Zotero note", text=note_text(d.get("note")),
                  meta={k: v for k, v in (("library", name), ("on", parent.get("key") if parent else None)) if v}, **common)
        elif t == "annotation":
            parent = top(d)
            text = "\n".join(x for x in (d.get("annotationText"), d.get("annotationComment")) if x)
            w.add(kind="highlight", title=(parent or {}).get("title") or "Zotero annotation", text=text or f"[{d.get('annotationType')}]",
                  meta={k: v for k, v in (("library", name), ("on", parent.get("key") if parent else None),
                                          ("type", d.get("annotationType")), ("comment", d.get("annotationComment")),
                                          ("color", d.get("annotationColor")), ("page", d.get("annotationPageLabel"))) if v}, **common)
        else:
            authors = [person(c) for c in d.get("creators") or [] if person(c)]
            venue = d.get("publicationTitle") or d.get("bookTitle") or d.get("proceedingsTitle") or d.get("websiteTitle") or d.get("publisher")
            year = (re.search(r"\b(1[5-9]\d\d|2\d{3})\b", d.get("date") or "") or [None, None])[1]
            tags = [x.get("tag") for x in d.get("tags") or [] if isinstance(x, dict) and x.get("tag")]
            line = " · ".join(x for x in (", ".join(authors[:6]) + (" et al." if len(authors) > 6 else ""), venue, year) if x)
            text = "\n".join(x for x in (d.get("title"), line, d.get("abstractNote"), "Tags: " + ", ".join(tags) if tags else None) if x)
            url = d.get("url") or (f"https://doi.org/{d['DOI']}" if d.get("DOI") else None)
            w.add(kind="reference", title=d.get("title") or "(untitled)", text=text, url=url,
                  meta={k: v for k, v in (("library", name), ("type", t), ("authors", authors or None), ("published", d.get("date")),
                                          ("venue", venue), ("doi", d.get("DOI")), ("tags", tags or None),
                                          ("collections", [collections.get(c) for c in d.get("collections") or [] if collections.get(c)] or None),
                                          ("added_by", d.get("_by"))) if v}, **common)


def main():
    with Writer("zotero", AVENUE) as w:
        key = api_key()
        if key:
            try:
                for lib in from_api(key, w):
                    write(w, *lib)
            except (urllib.error.URLError, OSError, ValueError) as e:  # offline, a key revoked: what was read before stays
                w.notes["api"] = f"not read: {getattr(e, 'code', None) or type(e).__name__}"
        db = os.path.join(data_dir(), "zotero.sqlite")
        if os.path.exists(db):
            try:
                for lib in from_app(db):
                    write(w, *lib)
            except sqlite3.Error as e:
                w.notes["app"] = f"not read: {e}"


if __name__ == "__main__":
    main()
