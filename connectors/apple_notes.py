"""Apple Notes from NoteStore.sqlite (note bodies are gzipped protobufs)."""

import gzip
import zlib

from common import LIB, Writer, columns, connect, from_apple, snapshot_sqlite, tables

AVENUE = ("Local SQLite: ~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite. "
          "Needs Full Disk Access. Body = ZICNOTEDATA.ZDATA, gzip -> protobuf field path 2.3.2. "
          "Locked (password) notes are encrypted: kept by their title, the body not read; tables/drawings are "
          "attachments. Notes in Recently Deleted (a folder of ZFOLDERTYPE 1) or marked for deletion are kept with "
          "meta.tier = \"deleted\".")


def _varint(buf, i):
    shift = result = 0
    while True:
        b = buf[i]
        result |= (b & 0x7F) << shift
        i += 1
        if not b & 0x80:
            return result, i
        shift += 7


def _fields(buf):
    """Yield (field_number, wire_type, value) for a protobuf message."""
    i = 0
    while i < len(buf):
        key, i = _varint(buf, i)
        field, wt = key >> 3, key & 7
        if wt == 0:
            v, i = _varint(buf, i)
        elif wt == 1:
            v, i = buf[i:i + 8], i + 8
        elif wt == 2:
            n, i = _varint(buf, i)
            v, i = buf[i:i + n], i + n
        elif wt == 5:
            v, i = buf[i:i + 4], i + 4
        else:
            return
        yield field, wt, v


def _get(buf, path):
    for field in path:
        buf = next((v for f, wt, v in _fields(buf) if f == field and wt == 2), None)
        if buf is None:
            return None
    return buf


def note_text(zdata):
    if not zdata:
        return None
    try:
        raw = gzip.decompress(zdata)
    except (OSError, EOFError, zlib.error):
        raw = zdata
    try:
        text = _get(raw, (2, 3, 2))
    except (IndexError, ValueError):
        return None
    return text.decode("utf-8", "replace") if text is not None else None


def main():
    db = snapshot_sqlite(LIB / "Group Containers/group.com.apple.notes/NoteStore.sqlite", "apple_notes/NoteStore.sqlite")
    with Writer("apple_notes", AVENUE) as w:
        if not db.exists():
            return
        con = connect(db)
        if not {"ZICCLOUDSYNCINGOBJECT", "Z_PRIMARYKEY"} <= tables(con):  # made, never written to
            w.notes["empty"] = 1
            return
        read(con, w)


def read(con, w):
    cols = columns(con, "ZICCLOUDSYNCINGOBJECT")
    # Each column only if this version of Notes has it: older ones lack the folder's type, the lock, pinning, deletion
    # and the newer creation date (ZCREATIONDATE3, macOS 13 on); one missing mustn't lose every note.
    opt = lambda c: c if c in cols else f"null {c}"  # noqa: E731
    note = lambda c, name=None: f"n.{c} {name or c}" if c in cols else f"null {name or c}"  # noqa: E731
    created = "coalesce(n.ZCREATIONDATE3, n.ZCREATIONDATE1)" if "ZCREATIONDATE3" in cols else "n.ZCREATIONDATE1"

    def ent(name):
        row = con.execute("select Z_ENT from Z_PRIMARYKEY where Z_NAME=?", (name,)).fetchone()
        return row[0] if row else None

    folders = {r["Z_PK"]: (r["ZTITLE2"], r["ZFOLDERTYPE"]) for r in con.execute(
        f"select Z_PK, {opt('ZTITLE2')}, {opt('ZFOLDERTYPE')} from ZICCLOUDSYNCINGOBJECT where Z_ENT=?", (ent("ICFolder"),))}
    attachments = {}
    # With the text Notes recognized in each one (a scan's pages, a photo of a whiteboard, handwriting) and what it
    # saw in pictures, where this version of Notes keeps them.
    for r in con.execute(f"""select ZNOTE, {opt("ZTYPEUTI")}, {opt("ZTITLE")}, {opt("ZURLSTRING")}, {opt("ZOCRSUMMARY")},
                                     {opt("ZHANDWRITINGSUMMARY")}, {opt("ZIMAGECLASSIFICATIONSUMMARY")}
                              from ZICCLOUDSYNCINGOBJECT where Z_ENT=? and ZNOTE is not null""" if "ZNOTE" in cols else "select 1 where 0",
                         (ent("ICAttachment"),) if "ZNOTE" in cols else ()):
        seen = " ".join(x.strip() for x in (r["ZOCRSUMMARY"], r["ZHANDWRITINGSUMMARY"]) if x and x.strip())
        attachments.setdefault(r["ZNOTE"], []).append(
            {k: v for k, v in (("type", r["ZTYPEUTI"]), ("title", r["ZTITLE"]), ("url", r["ZURLSTRING"]), ("text", seen[:5000]),
                               ("shows", (r["ZIMAGECLASSIFICATIONSUMMARY"] or "").strip())) if v})

    data = "d.ZDATA" if "ZICNOTEDATA" in tables(con) else "null ZDATA"
    rows = con.execute(f"""select n.Z_PK, {note("ZIDENTIFIER")}, {note("ZTITLE1")}, {note("ZSNIPPET")}, {note("ZFOLDER")},
                                  {note("ZISPASSWORDPROTECTED")}, {note("ZISPINNED", "pinned")}, {note("ZMARKEDFORDELETION")},
                                  {created} created, {note("ZMODIFICATIONDATE1", "modified")}, {data}
                           from ZICCLOUDSYNCINGOBJECT n {"left join ZICNOTEDATA d on d.ZNOTE = n.Z_PK" if data == "d.ZDATA" else ""}
                           where n.Z_ENT=?""", (ent("ICNote"),))
    for r in rows:
        folder, ftype = folders.get(r["ZFOLDER"], (None, None))
        deleted = bool(r["ZMARKEDFORDELETION"]) or ftype == 1  # 1: Recently Deleted
        locked = bool(r["ZISPASSWORDPROTECTED"])
        text = None if locked else note_text(r["ZDATA"])
        text = (text or r["ZSNIPPET"] or "").replace("￼", "").strip()
        atts = attachments.get(r["Z_PK"])
        if atts:
            text += "\n" + "\n".join(f"[attachment: {a.get('title') or a.get('url') or a.get('type') or 'scanned page'}]"
                                     + (f"\nText in it: {a['text']}" if a.get("text") else "")
                                     + (f"\nShows: {a['shows']}" if a.get("shows") else "") for a in atts)
        w.add(id=r["ZIDENTIFIER"] or r["Z_PK"], kind="note", ts=from_apple(r["created"]),
              ts_end=from_apple(r["modified"]),  # last edit: the text below is this version, not the first
              author="me", is_me=True, thread=folder, thread_name=folder, title=r["ZTITLE1"], text=text,
              meta={k: v for k, v in (("modified", from_apple(r["modified"])), ("locked", locked or None),
                                      ("deleted", deleted or None), ("tier", "deleted" if deleted else None),
                                      ("pinned", bool(r["pinned"]) or None),
                                      ("attachments", [{k: v for k, v in a.items() if k != "text"} for a in atts or []])) if v})


if __name__ == "__main__":
    main()
