"""Zotero: the papers, books and pages you saved, your notes on them and your highlights in their PDFs.

Read from the Zotero app's database on this Mac (zotero.sqlite in its data folder): your library and every group the
app syncs. Nothing is fetched from zotero.org: a library kept only there comes in once the Zotero app has synced it
here. An item is "<library>:<key>" (user, or group:<id>), Zotero's own key."""

import os
import re
import sqlite3

from common import HOME, LIB, Writer, connect, snapshot_sqlite
from email_parse import html_to_text

AVENUE = ("The Zotero app's zotero.sqlite (data folder from prefs.js's extensions.zotero.dataDir, else ~/Zotero), read "
          "from a snapshot: libraries and groups, items + itemData/fieldsCombined, creators, collections, tags, "
          "itemNotes, itemAnnotations (deletedItems left out). Items: kind reference; notes: note; PDF highlights and "
          "comments: highlight. Attachments aren't records: a PDF's highlights name the item it's attached to. "
          "Nothing from zotero.org's API.")

ANNOTATION_TYPES = {1: "highlight", 2: "note", 3: "image", 4: "ink", 5: "underline", 6: "text"}
SKIP_TYPES = {"attachment"}


# ---------------------------------------------------------------- the app's database

def data_dir():
    """The Zotero app's data folder: where its prefs.js says, else ~/Zotero."""
    for prefs in (LIB / "Application Support/Zotero/Profiles").glob("*/prefs.js"):
        m = re.search(r'user_pref\("extensions\.zotero\.dataDir",\s*"([^"]+)"\)', prefs.read_text(errors="replace"))
        if m:
            return os.path.expanduser(m.group(1))
    return str(HOME / "Zotero")


def from_app(db):
    """(library id, its name, its collections, its items) for each library in zotero.sqlite: items in the shape of
    Zotero's API (its data objects), the trash left out."""
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
    """Zotero's times: "2024-01-13 10:00:00", UTC, in the app's database (or ISO already)."""
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
        db = os.path.join(data_dir(), "zotero.sqlite")
        if os.path.exists(db):
            try:
                for lib in from_app(db):
                    write(w, *lib)
            except sqlite3.Error as e:
                w.notes["app"] = f"not read: {e}"


if __name__ == "__main__":
    main()
