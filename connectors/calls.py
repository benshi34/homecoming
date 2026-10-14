"""Phone and FaceTime call history: the Mac's CallHistory.storedata (synced from the iPhone, pruned to
recent months) plus the iPhone's own copy from a local backup (connectors/iphone_backup.py), which reaches
further back. Same schema, but the two copies give the same call different ZUNIQUE_IDs, so a call is dropped
when the other copy already has one with the same number within 5 seconds (117 of 124 Mac calls here)."""

from common import LIB, Writer, connect, from_apple, phone, snapshot_sqlite
from contacts import Resolver, norm_handle

AVENUE = ("Local SQLite: ~/Library/Application Support/CallHistoryDB/CallHistory.storedata, plus "
          "HomeDomain/Library/CallHistoryDB/CallHistory.storedata from an iPhone backup. Needs Full Disk Access. "
          "Both copies prune old calls, so run daily to keep history.")

CALL_TYPES = {1: "phone", 8: "facetime video", 16: "facetime audio"}


def main():
    names = Resolver()
    mac = snapshot_sqlite(LIB / "Application Support/CallHistoryDB/CallHistory.storedata", "calls/CallHistory.storedata")
    sources = [("iphone", phone("HomeDomain", "Library/CallHistoryDB/CallHistory.storedata")), ("mac", mac)]
    written = {}  # handle -> [(call time, copy)] for calls already written
    with Writer("calls", AVENUE) as w:
        for copy, db in sources:
            if db.exists():
                add_calls(connect(db), names, w, copy, written)


def add_calls(con, names, w, copy, written):
    for r in con.execute("""select ZUNIQUE_ID, ZDATE, ZDURATION, ZADDRESS, ZNAME, ZORIGINATED, ZANSWERED,
                                   ZCALLTYPE, ZLOCATION from ZCALLRECORD"""):
        if w.has(r["ZUNIQUE_ID"]):
            continue
        handle, t = norm_handle(r["ZADDRESS"]) or r["ZNAME"], r["ZDATE"] or 0
        if any(c != copy and abs(t - u) <= 5 for u, c in written.get(handle, ())):
            w.skip(r["ZUNIQUE_ID"])  # the same call in the other copy, under another id
            w.notes["same_call_in_both_copies"] = w.notes.get("same_call_in_both_copies", 0) + 1
            continue
        written.setdefault(handle, []).append((t, copy))
        who = r["ZNAME"] or names.label(r["ZADDRESS"]) or "unknown"
        direction = "outgoing" if r["ZORIGINATED"] else ("incoming" if r["ZANSWERED"] else "missed")
        kind = CALL_TYPES.get(r["ZCALLTYPE"], "call")
        mins = round((r["ZDURATION"] or 0) / 60, 1)
        w.add(id=r["ZUNIQUE_ID"], kind="call", ts=from_apple(r["ZDATE"]), is_me=bool(r["ZORIGINATED"]),
              author="me" if r["ZORIGINATED"] else who, participants=[who], thread=who, thread_name=who,
              text=f"{direction} {kind} call with {who}, {mins} min",
              meta={"direction": direction, "type": kind, "seconds": r["ZDURATION"], "location": r["ZLOCATION"],
                    "copy": copy})


if __name__ == "__main__":
    main()
