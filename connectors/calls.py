"""Phone and FaceTime call history: the Mac's CallHistory.storedata (synced from the iPhone, pruned to
recent months) plus the iPhone's own copy from a local backup (connectors/iphone_backup.py), which reaches
further back. Same schema, but the two copies give the same call different ZUNIQUE_IDs, so a call is dropped
when the other copy already has one with the same number within 5 seconds (117 of 124 Mac calls here). The
iPhone's copy wins. That holds for calls kept from earlier runs too: a call the Mac has pruned since, kept from
its last read, is the same call as the iPhone's copy of it, not a second one.

The phone's CallHistoryTemp.storedata is read too, as part of its copy: calls made while the phone was locked wait there
until it's unlocked (iLEAPP's callHistory reads it as well). A call with no ZUNIQUE_ID is kept as "<copy>:<Z_PK>". A
copy that can't be read (damaged) is noted (notes.unreadable) and the other one is read all the same."""

import json
import sqlite3
from datetime import datetime

from common import (APPLE_EPOCH, LIB, NORM, Writer, columns, connect, from_apple, phone, phone_unencrypted, select,
                    snapshot_sqlite, tables)
from contacts import Resolver, norm_handle

AVENUE = ("Local SQLite: ~/Library/Application Support/CallHistoryDB/CallHistory.storedata, plus "
          "HomeDomain/Library/CallHistoryDB/CallHistory.storedata from an iPhone backup. Needs Full Disk Access. "
          "Both copies prune old calls, so run daily to keep history.")

CALL_TYPES = {1: "phone", 8: "facetime video", 16: "facetime audio"}
# ZSERVICE_PROVIDER: the app a call was made in, when it isn't the phone or FaceTime (ZCALLTYPE 0: an app's own calls,
# through CallKit). Others are named by the end of their bundle id.
APPS = {"net.whatsapp.WhatsApp": "WhatsApp", "net.whatsapp.WhatsAppSMB": "WhatsApp Business", "com.facebook.Messenger": "Messenger",
        "ph.telegra.Telegraph": "Telegram", "org.whispersystems.signal": "Signal", "com.skype.skype": "Skype",
        "com.microsoft.skype.teams": "Teams", "us.zoom.videomeetings": "Zoom", "com.google.Duo": "Google Meet",
        "com.tencent.xin": "WeChat", "com.viber": "Viber", "jp.naver.line": "LINE", "com.hammerandchisel.discord": "Discord",
        "com.burbn.instagram": "Instagram", "com.tinyspeck.chatlyio": "Slack"}
SAME_CALL = 5  # seconds apart in the two copies


def kept_calls():
    """The calls an earlier run wrote, which the copies may have pruned since: who -> [(Apple time, copy, id)]. Who is
    the number (meta.handle), or for records written before that was kept, the name shown (thread)."""
    out = {}
    try:
        lines = (NORM / "calls.jsonl").open(encoding="utf-8", errors="replace")
    except OSError:
        return out
    with lines:
        for line in lines:
            try:
                r = json.loads(line)
                t = (datetime.fromisoformat(r["ts"].replace("Z", "+00:00")) - APPLE_EPOCH).total_seconds()
            except (ValueError, KeyError, AttributeError, TypeError):
                continue
            meta = r.get("meta") or {}
            out.setdefault(meta.get("handle") or r.get("thread"), []).append((t, meta.get("copy"), str(r.get("id"))))
    return out


def main():
    names = Resolver()
    mac = snapshot_sqlite(LIB / "Application Support/CallHistoryDB/CallHistory.storedata", "calls/CallHistory.storedata")
    sources = [("iphone", None, phone("HomeDomain", "Library/CallHistoryDB/CallHistory.storedata")),
               ("iphone", "temp", phone("HomeDomain", "Library/CallHistoryDB/CallHistoryTemp.storedata")), ("mac", None, mac)]
    written = {}  # handle -> [(call time, copy)] for calls already written
    kept = kept_calls()
    if not sources[0][2].exists() and phone_unencrypted():
        print("[calls] this iPhone backup isn't encrypted, and Finder leaves call history out of those: the Mac's copy is read")
    with Writer("calls", AVENUE) as w:
        for copy, store, db in sources:
            if not db.exists():
                continue
            con = connect(db)
            try:
                add_calls(con, names, w, copy, written, kept, store=store)
            except sqlite3.DatabaseError as e:
                print(f"[calls] the {copy} copy ({db.name}) can't be read ({e}); the other is read all the same")
                if copy not in w.notes.get("unreadable", []):
                    w.notes.setdefault("unreadable", []).append(copy)
            finally:
                con.close()


def same_call(w):
    w.notes["same_call_in_both_copies"] = w.notes.get("same_call_in_both_copies", 0) + 1


def text_of(v):
    """ZADDRESS as a string: some stores keep it as bytes (APOLLO reads it with CAST(ZADDRESS AS TEXT))."""
    if isinstance(v, bytes):
        v = v.decode("utf-8", "replace").strip("\x00")
    return v.strip() if isinstance(v, str) and v.strip() else None


def on_the_call(con):
    """Call row -> the people on a group call (FaceTime with several), from ZHANDLE through the join table Core Data
    names after its entities' numbers (Z_2REMOTEPARTICIPANTHANDLES: Z_2REMOTEPARTICIPANTCALLS, Z_4REMOTEPARTICIPANTHANDLES)."""
    have = tables(con)
    join = next((t for t in sorted(have) if t.startswith("Z_") and t.endswith("REMOTEPARTICIPANTHANDLES")), None)
    if not join or "ZHANDLE" not in have:
        return {}
    cols = columns(con, join)
    ccol = next((c for c in cols if c.endswith("REMOTEPARTICIPANTCALLS")), None)
    hcol = next((c for c in cols if c.endswith("REMOTEPARTICIPANTHANDLES")), None)
    if not ccol or not hcol or "ZVALUE" not in columns(con, "ZHANDLE"):
        return {}
    out = {}
    for r in con.execute(f"select j.{ccol} call, h.ZVALUE value from {join} j join ZHANDLE h on h.Z_PK = j.{hcol}"):
        value = text_of(r["value"])
        if value and value not in out.setdefault(r["call"], []):
            out[r["call"]].append(value)
    return out


def add_calls(con, names, w, copy, written, kept=None, store=None):
    kept = kept or {}
    if "ZCALLRECORD" not in tables(con):  # made, never written to
        if not store:
            w.notes.setdefault("empty", []).append(copy)
        return
    group = on_the_call(con)
    # Each column but the call's id only if this store has it (older ones have no location or provider).
    for r in con.execute(select(con, "ZCALLRECORD", ("Z_PK", "ZUNIQUE_ID", "ZDATE", "ZDURATION", "ZADDRESS", "ZNAME", "ZORIGINATED",
                                                     "ZANSWERED", "ZCALLTYPE", "ZLOCATION", "ZSERVICE_PROVIDER"))):
        uid = r["ZUNIQUE_ID"] or f"{copy}{'-' + store if store else ''}:{r['Z_PK']}"
        if w.has(uid):
            continue
        address = text_of(r["ZADDRESS"])
        handle, t = norm_handle(address) or r["ZNAME"], r["ZDATE"] or 0
        if any(c != copy and abs(t - u) <= SAME_CALL for u, c in written.get(handle, ())):
            w.skip(uid)  # the same call in the other copy, under another id
            same_call(w)
            continue
        everyone = sorted(names.label(h) for h in group.get(r["Z_PK"], []))
        who = r["ZNAME"] or (names.label(address) if address else None) or ", ".join(everyone) or "unknown"
        # The same call kept from an earlier run of the other copy, which no longer has it: the iPhone's is kept.
        earlier = [(u, c, i) for key in {handle, who} for u, c, i in kept.get(key, ())
                   if c and c != copy and abs(t - u) <= SAME_CALL and not w.has(i)]
        if earlier and any(c == "iphone" for _, c, _ in earlier):
            w.skip(uid)
            same_call(w)
            continue
        for _, _, i in earlier:
            w.skip(i)
            same_call(w)
        written.setdefault(handle, []).append((t, copy))
        direction = "outgoing" if r["ZORIGINATED"] else ("incoming" if r["ZANSWERED"] else "missed")
        provider = text_of(r["ZSERVICE_PROVIDER"])
        provider = None if not provider or provider.startswith("com.apple.") else provider  # the phone, FaceTime: by ZCALLTYPE
        kind = (APPS.get(provider) or provider.rsplit(".", 1)[-1]) if provider else CALL_TYPES.get(r["ZCALLTYPE"])
        mins = round((r["ZDURATION"] or 0) / 60, 1)
        w.add(id=uid, kind="call", ts=from_apple(r["ZDATE"]), is_me=bool(r["ZORIGINATED"]),
              author="me" if r["ZORIGINATED"] else who, participants=everyone or [who], thread=who, thread_name=who,
              text=f"{direction} {kind + ' ' if kind else ''}call with {who}, {mins} min",
              meta={"direction": direction, "type": kind or "call", "seconds": r["ZDURATION"], "location": r["ZLOCATION"],
                    **({"app": provider} if provider else {}), "copy": copy, "handle": handle})


if __name__ == "__main__":
    main()
