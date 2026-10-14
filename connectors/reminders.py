"""Apple Reminders (one Core Data store per account)."""

from common import LIB, Writer, connect, from_apple, snapshot_sqlite

AVENUE = ("Local SQLite: ~/Library/Group Containers/group.com.apple.reminders/Container_v1/Stores/Data-*.sqlite "
          "(one per account). Needs Full Disk Access.")


def main():
    stores = sorted((LIB / "Group Containers/group.com.apple.reminders/Container_v1/Stores").glob("Data-*.sqlite"))
    with Writer("reminders", AVENUE) as w:
        for path in stores:
            con = connect(snapshot_sqlite(path, f"reminders/{path.name}"))
            lists = {r["Z_PK"]: r["ZNAME"] for r in con.execute("select Z_PK, ZNAME from ZREMCDBASELIST")}
            for r in con.execute("""select Z_PK, ZIDENTIFIER, ZTITLE, ZNOTES, ZCOMPLETED, ZCOMPLETIONDATE, ZCREATIONDATE,
                                           ZDUEDATE, ZFLAGGED, ZPRIORITY, ZLIST, ZPARENTREMINDER, ZLASTMODIFIEDDATE
                                    from ZREMCDREMINDER where ZMARKEDFORDELETION is not 1"""):
                if not (r["ZTITLE"] or r["ZNOTES"]):
                    continue
                meta = {"completed": bool(r["ZCOMPLETED"]), "completed_at": from_apple(r["ZCOMPLETIONDATE"]),
                        "due": from_apple(r["ZDUEDATE"]), "flagged": bool(r["ZFLAGGED"]) or None,
                        "priority": r["ZPRIORITY"] or None, "modified": from_apple(r["ZLASTMODIFIEDDATE"]),
                        "subtask_of": r["ZPARENTREMINDER"]}
                w.add(id=r["ZIDENTIFIER"] or f"{path.stem}:{r['Z_PK']}", kind="reminder",
                      ts=from_apple(r["ZCREATIONDATE"]), author="me", is_me=True,
                      thread=lists.get(r["ZLIST"]), thread_name=lists.get(r["ZLIST"]), title=r["ZTITLE"],
                      text="\n".join(x for x in (r["ZTITLE"], r["ZNOTES"]) if x),
                      meta={k: v for k, v in meta.items() if v is not None})


if __name__ == "__main__":
    main()
