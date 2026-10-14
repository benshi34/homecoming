"""Apple Notes from NoteStore.sqlite (note bodies are gzipped protobufs)."""

import gzip
import zlib

from common import LIB, Writer, columns, connect, from_apple, snapshot_sqlite

AVENUE = ("Local SQLite: ~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite. "
          "Needs Full Disk Access. Body = ZICNOTEDATA.ZDATA, gzip -> protobuf field path 2.3.2. "
          "Locked (password) notes are encrypted and skipped; tables/drawings are attachments.")


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
    con = connect(db)
    cols = columns(con, "ZICCLOUDSYNCINGOBJECT")
    created = "coalesce(n.ZCREATIONDATE3, n.ZCREATIONDATE1)" if "ZCREATIONDATE3" in cols else "n.ZCREATIONDATE1"
    ent = lambda name: con.execute("select Z_ENT from Z_PRIMARYKEY where Z_NAME=?", (name,)).fetchone()[0]

    folders = {r["Z_PK"]: (r["ZTITLE2"], r["ZFOLDERTYPE"]) for r in con.execute(
        "select Z_PK, ZTITLE2, ZFOLDERTYPE from ZICCLOUDSYNCINGOBJECT where Z_ENT=?", (ent("ICFolder"),))}
    attachments = {}
    for r in con.execute("select ZNOTE, ZTYPEUTI, ZTITLE, ZURLSTRING from ZICCLOUDSYNCINGOBJECT where Z_ENT=? and ZNOTE is not null"
                         if "ZURLSTRING" in cols else
                         "select ZNOTE, ZTYPEUTI, ZTITLE, null ZURLSTRING from ZICCLOUDSYNCINGOBJECT where Z_ENT=? and ZNOTE is not null",
                         (ent("ICAttachment"),)):
        attachments.setdefault(r["ZNOTE"], []).append(
            {k: v for k, v in (("type", r["ZTYPEUTI"]), ("title", r["ZTITLE"]), ("url", r["ZURLSTRING"])) if v})

    rows = con.execute(f"""select n.Z_PK, n.ZIDENTIFIER, n.ZTITLE1, n.ZSNIPPET, n.ZFOLDER, n.ZISPASSWORDPROTECTED,
                                  n.ZMARKEDFORDELETION, {created} created, n.ZMODIFICATIONDATE1 modified, d.ZDATA
                           from ZICCLOUDSYNCINGOBJECT n left join ZICNOTEDATA d on d.ZNOTE = n.Z_PK
                           where n.Z_ENT=?""", (ent("ICNote"),))
    with Writer("apple_notes", AVENUE) as w:
        for r in rows:
            folder, ftype = folders.get(r["ZFOLDER"], (None, None))
            deleted = bool(r["ZMARKEDFORDELETION"]) or ftype == 1
            locked = bool(r["ZISPASSWORDPROTECTED"])
            text = None if locked else note_text(r["ZDATA"])
            text = (text or r["ZSNIPPET"] or "").replace("￼", "").strip()
            atts = attachments.get(r["Z_PK"])
            if atts:
                text += "\n" + "\n".join(f"[attachment: {a.get('title') or a.get('url') or a.get('type')}]" for a in atts)
            w.add(id=r["ZIDENTIFIER"] or r["Z_PK"], kind="note", ts=from_apple(r["created"]),
                  ts_end=from_apple(r["modified"]),  # last edit: the text below is this version, not the first
                  author="me", is_me=True, thread=folder, thread_name=folder, title=r["ZTITLE1"], text=text,
                  meta={k: v for k, v in (("modified", from_apple(r["modified"])), ("locked", locked or None),
                                          ("deleted", deleted or None), ("attachments", atts)) if v})


if __name__ == "__main__":
    main()
