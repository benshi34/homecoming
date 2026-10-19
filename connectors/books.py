"""Apple Books: the books in your library (how far you got, when you finished), and your highlights and notes.

The library and the highlights are two databases in the Books app's container, joined by the book's asset id. Books
syncs them through iCloud, so the Mac's copy has what you read on the iPhone too."""

from common import LIB, Writer, columns, connect, from_apple, snapshot_sqlite, tables

DOCS = LIB / "Containers/com.apple.iBooksX/Data/Documents"
AVENUE = ("Local SQLite: ~/Library/Containers/com.apple.iBooksX/Data/Documents/BKLibrary/BKLibrary-*.sqlite "
          "(ZBKLIBRARYASSET: ZASSETID, ZTITLE, ZAUTHOR, ZREADINGPROGRESS 0-1, ZDATEFINISHED, ZLASTOPENDATE, "
          "ZCREATIONDATE) and AEAnnotation/AEAnnotation*.sqlite (ZAEANNOTATION: ZANNOTATIONASSETID, "
          "ZANNOTATIONSELECTEDTEXT, ZANNOTATIONNOTE, ZANNOTATIONCREATIONDATE, ZANNOTATIONMODIFICATIONDATE, "
          "ZANNOTATIONDELETED, ZFUTUREPROOFING5 = chapter). Highlights are the annotations with text or a note; deleted "
          "ones are kept with meta.tier = \"deleted\", bookmarks (no text) are counted. Written against the schema the "
          "Books highlight exporters use; not yet run on a Mac with Books data.")


def newest(folder, pattern):
    """The database in folder (Books names it with a schema version), the newest if there are several."""
    found = sorted(folder.glob(pattern), key=lambda p: p.stat().st_mtime)
    return found[-1] if found else None


def select(con, table, want):
    have = columns(con, table)
    return f"select {', '.join(c if c in have else f'null {c}' for c in want)} from {table}"


def clean(pairs):
    return {k: v for k, v in pairs if v is not None}


def main():
    with Writer("books", AVENUE) as w:
        lib, notes = newest(DOCS / "BKLibrary", "BKLibrary*.sqlite"), newest(DOCS / "AEAnnotation", "AEAnnotation*.sqlite")
        books = {}
        if lib:
            con = connect(snapshot_sqlite(lib, "books/BKLibrary.sqlite"))
            if "ZBKLIBRARYASSET" not in tables(con):  # made, never written to
                w.notes["empty_library"] = 1
                lib = None
        if lib:
            want = ("ZASSETID", "ZTITLE", "ZAUTHOR", "ZGENRE", "ZREADINGPROGRESS", "ZDATEFINISHED", "ZISFINISHED",
                    "ZLASTOPENDATE", "ZCREATIONDATE", "ZPURCHASEDATE", "ZISSAMPLE", "ZPAGECOUNT", "ZCONTENTTYPE")
            for r in con.execute(select(con, "ZBKLIBRARYASSET", want)):
                if not r["ZASSETID"]:
                    continue
                books[r["ZASSETID"]] = r
                title, by = r["ZTITLE"], f" by {r['ZAUTHOR']}" if r["ZAUTHOR"] else ""
                progress = r["ZREADINGPROGRESS"] or 0
                finished = from_apple(r["ZDATEFINISHED"])
                state = ("finished" if finished or r["ZISFINISHED"] else f"{round(progress * 100)}% read" if progress
                         else "not started")
                w.add(id=f"book:{r['ZASSETID']}", kind="book", ts=from_apple(r["ZCREATIONDATE"] or r["ZPURCHASEDATE"]),
                      ts_end=from_apple(r["ZLASTOPENDATE"]), author="me", is_me=True, title=title,
                      thread=r["ZASSETID"], thread_name=title,
                      text=f"{title or 'A book'}{by}, in your Books library: {state}" + (" (a sample)" if r["ZISSAMPLE"] else ""),
                      meta=clean((("author", r["ZAUTHOR"]), ("genre", r["ZGENRE"]),
                                  ("progress", round(progress, 3) if progress else None), ("finished", finished),
                                  ("last_opened", from_apple(r["ZLASTOPENDATE"])), ("purchased", from_apple(r["ZPURCHASEDATE"])),
                                  ("pages", r["ZPAGECOUNT"]), ("sample", bool(r["ZISSAMPLE"]) or None),
                                  ("content_type", r["ZCONTENTTYPE"]))))
                if finished:
                    w.add(id=f"finished:{r['ZASSETID']}", kind="read", ts=finished, author="me", is_me=True, title=title,
                          thread=r["ZASSETID"], thread_name=title, text=f"Finished reading {title or 'a book'}{by}",
                          meta=clean((("author", r["ZAUTHOR"]),)))
            con.close()
        if notes:
            con = connect(snapshot_sqlite(notes, "books/AEAnnotation.sqlite"))
            if "ZAEANNOTATION" not in tables(con):
                w.notes["empty_annotations"] = 1
                notes = None
        if notes:
            want = ("Z_PK", "ZANNOTATIONUUID", "ZANNOTATIONASSETID", "ZANNOTATIONSELECTEDTEXT", "ZANNOTATIONNOTE",
                    "ZANNOTATIONCREATIONDATE", "ZANNOTATIONMODIFICATIONDATE", "ZANNOTATIONDELETED", "ZANNOTATIONSTYLE",
                    "ZFUTUREPROOFING5", "ZANNOTATIONLOCATION")
            for r in con.execute(select(con, "ZAEANNOTATION", want)):
                quote, note = (r["ZANNOTATIONSELECTEDTEXT"] or "").strip(), (r["ZANNOTATIONNOTE"] or "").strip()
                if not (quote or note):  # a bookmark or the place you're up to: no text
                    w.notes["bookmarks_and_places"] = w.notes.get("bookmarks_and_places", 0) + 1
                    continue
                book = books.get(r["ZANNOTATIONASSETID"])
                title = book["ZTITLE"] if book else None
                text = "\n".join(x for x in (quote and f"“{quote}”", note and f"Your note: {note}") if x)
                w.add(id=r["ZANNOTATIONUUID"] or f"pk:{r['Z_PK']}", kind="highlight",
                      ts=from_apple(r["ZANNOTATIONCREATIONDATE"]), ts_end=from_apple(r["ZANNOTATIONMODIFICATIONDATE"]),
                      author="me", is_me=True, title=title, thread=r["ZANNOTATIONASSETID"], thread_name=title, text=text,
                      meta=clean((("book_author", book["ZAUTHOR"] if book else None), ("chapter", r["ZFUTUREPROOFING5"]),
                                  ("note", note or None), ("color", r["ZANNOTATIONSTYLE"]),
                                  ("location", r["ZANNOTATIONLOCATION"]),
                                  ("tier", "deleted" if r["ZANNOTATIONDELETED"] else None))))


if __name__ == "__main__":
    main()
