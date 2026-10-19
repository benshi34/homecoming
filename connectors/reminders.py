"""Apple Reminders (one Core Data store per account)."""

import sqlite3
import uuid

from common import LIB, Writer, columns, connect, from_apple, select, snapshot_sqlite, tables

AVENUE = ("Local SQLite: ~/Library/Group Containers/group.com.apple.reminders/Container_v1/Stores/Data-*.sqlite "
          "(one per account, and Data-local for On My Mac). Needs Full Disk Access. ZREMCDREMINDER.ZIDENTIFIER is the "
          "reminder's UUID as 16 bytes, written as its UUID string. A store without reminders, or one that can't be read, "
          "is counted in the manifest and the others are read; each column but the title only if the store has it.")


def ident(value, path, pk):
    """A reminder's id: its UUID (ZIDENTIFIER, 16 bytes), else the store and row."""
    if isinstance(value, bytes) and len(value) == 16:
        return str(uuid.UUID(bytes=value)).upper()
    return value if isinstance(value, str) and value else f"{path.stem}:{pk}"


def main():
    stores = sorted((LIB / "Group Containers/group.com.apple.reminders/Container_v1/Stores").glob("Data-*.sqlite"))
    with Writer("reminders", AVENUE) as w:
        for path in stores:
            try:
                con = connect(snapshot_sqlite(path, f"reminders/{path.name}"))
                if "ZREMCDREMINDER" not in tables(con):  # Data-local before anything was put on this Mac, a store being made
                    w.notes["stores_without_reminders"] = w.notes.get("stores_without_reminders", 0) + 1
                    continue
                read(con, path, w)
            except sqlite3.DatabaseError:
                w.notes.setdefault("unreadable", []).append(path.name)


def read(con, path, w):
    lists = {r["Z_PK"]: r["ZNAME"] for r in con.execute(
        select(con, "ZREMCDBASELIST", ("Z_PK", "ZNAME")) if "ZREMCDBASELIST" in tables(con) else "select 1 where 0")}
    cols = columns(con, "ZREMCDREMINDER")
    # A subtask's parent, by the id its record has (ZPARENTREMINDER is the parent's row number).
    ids = {r["Z_PK"]: ident(r["ZIDENTIFIER"], path, r["Z_PK"]) for r in con.execute(select(con, "ZREMCDREMINDER", ("Z_PK", "ZIDENTIFIER")))}
    want = ("Z_PK", "ZIDENTIFIER", "ZTITLE", "ZNOTES", "ZCOMPLETED", "ZCOMPLETIONDATE", "ZCREATIONDATE", "ZDUEDATE", "ZFLAGGED",
            "ZPRIORITY", "ZLIST", "ZPARENTREMINDER", "ZLASTMODIFIEDDATE")
    where = " where ZMARKEDFORDELETION is not 1" if "ZMARKEDFORDELETION" in cols else ""
    for r in con.execute(select(con, "ZREMCDREMINDER", want) + where):
        if not (r["ZTITLE"] or r["ZNOTES"]):
            continue
        if isinstance(r["ZIDENTIFIER"], bytes):
            w.skip(str(r["ZIDENTIFIER"]))  # an earlier run's id for it: the bytes as Python printed them
        meta = {"completed": bool(r["ZCOMPLETED"]), "completed_at": from_apple(r["ZCOMPLETIONDATE"]),
                "due": from_apple(r["ZDUEDATE"]), "flagged": bool(r["ZFLAGGED"]) or None,
                "priority": r["ZPRIORITY"] or None, "modified": from_apple(r["ZLASTMODIFIEDDATE"]),
                "subtask_of": ids.get(r["ZPARENTREMINDER"]) if r["ZPARENTREMINDER"] else None}
        w.add(id=ids[r["Z_PK"]], kind="reminder",
              ts=from_apple(r["ZCREATIONDATE"]), author="me", is_me=True,
              thread=lists.get(r["ZLIST"]), thread_name=lists.get(r["ZLIST"]), title=r["ZTITLE"],
              text="\n".join(x for x in (r["ZTITLE"], r["ZNOTES"]) if x),
              meta={k: v for k, v in meta.items() if v is not None})


if __name__ == "__main__":
    main()
