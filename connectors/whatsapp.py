"""WhatsApp on this Mac: the WhatsApp app's ChatStorage.sqlite, the same database (and schema) as the iPhone app's.
Both sides of every chat it has, who wrote each message in a group, and what kind of attachment a message had.

The iPhone backup's WhatsApp comes in through iLEAPP as phone_whatsapp. A message both copies have (same stanza id,
WhatsApp's own message id) is kept there and skipped here, so it's counted once; the Mac adds only what the phone's
copy doesn't have. iLEAPP names a group message's sender after the group (ILEAPP.md #25): ileapp.py takes who wrote it
from these databases instead (group_senders)."""

import datetime as dt
import json
import sqlite3

from common import APPLE_EPOCH, LIB, MANIFEST, Writer, columns, connect, from_apple, phone, snapshot_sqlite
from contacts import Resolver

CONTAINER = LIB / "Group Containers/group.net.whatsapp.WhatsApp.shared"
DB = CONTAINER / "ChatStorage.sqlite"
PHONE_DB = ("AppDomainGroup-group.net.whatsapp.WhatsApp.shared", "ChatStorage.sqlite")
AVENUE = ("Local SQLite: ~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite (WhatsApp for "
          "Mac, the same schema as the iPhone app's). ZWAMESSAGE = messages (ZISFROMME, ZMESSAGEDATE, ZTEXT, ZSTANZAID, "
          "ZMESSAGETYPE, ZGROUPMEMBER), ZWACHATSESSION = chats (ZCONTACTJID, ZPARTNERNAME), ZWAGROUPMEMBER = who is in a "
          "group, ZWAPROFILEPUSHNAME = the names people gave themselves, ZWAMEDIAITEM = attachments. Names from Contacts "
          "first. Messages the iPhone backup's copy also has (by ZSTANZAID) are left to phone_whatsapp. Written against "
          "the documented iOS schema; not yet run on a Mac with WhatsApp.")

# ZMESSAGETYPE, as forensic write-ups of the iOS app describe it (not confirmed on the Mac app).
TYPES = {1: "photo", 2: "video", 3: "audio message", 4: "contact card", 5: "location", 7: "link", 8: "file",
         11: "GIF", 15: "sticker"}
DELETED = 14
SYSTEM = 6
STATUS = "status@broadcast"  # people's status updates, not a chat
APPLE = 978307200  # 2001-01-01 in Unix seconds: WhatsApp keeps Apple time


def number(jid):
    """'14155550100@s.whatsapp.net' -> '+14155550100'; group and other ids have no number."""
    user, _, server = (jid or "").partition("@")
    return f"+{user}" if server in ("s.whatsapp.net", "c.us") and user.isdigit() else None


def pick(con, table, wanted):
    """The columns of `table` this copy of the schema has, the rest as nulls."""
    have = columns(con, table)
    return ", ".join(f"{table}.{c}" if c in have else f"null {c}" for c in wanted)


def phone_stanzas():
    """Stanza ids in the iPhone backup's WhatsApp that phone_whatsapp brought in: none if it hasn't, and none newer
    than its newest message (a backup decrypted since, whose iLEAPP read didn't finish, isn't in it yet)."""
    try:
        entry = json.loads(MANIFEST.read_text()).get("phone_whatsapp") or {}
        last = dt.datetime.fromisoformat(entry["last"].replace("Z", "+00:00"))
    except (OSError, ValueError, KeyError, AttributeError, TypeError):
        return set()
    db = phone(*PHONE_DB)
    if not (entry.get("kinds") or {}).get("message") or not db.exists():
        return set()
    con = connect(db)
    try:
        return {s for (s,) in con.execute("select ZSTANZAID from ZWAMESSAGE where ZSTANZAID is not null and ZMESSAGEDATE <= ?",
                                          ((last - APPLE_EPOCH).total_seconds() + 1,))}
    except sqlite3.Error:  # no messages table in it (or not readable): nothing the Mac's copy need leave to it
        return set()
    finally:
        con.close()


def namer(con, names):
    """who(jid, fallback): a person by their WhatsApp id: their name in Contacts, else what WhatsApp calls them, else
    the number."""
    tables = {r[0] for r in con.execute("select name from sqlite_master where type = 'table'")}
    push = {}
    if "ZWAPROFILEPUSHNAME" in tables:
        push = {r["ZJID"]: r["ZPUSHNAME"] for r in con.execute(
            f"select {pick(con, 'ZWAPROFILEPUSHNAME', ('ZJID', 'ZPUSHNAME'))} from ZWAPROFILEPUSHNAME") if r["ZPUSHNAME"]}

    def who(jid, fallback=None):
        n = number(jid)
        return (n and names.name(n)) or fallback or push.get(jid) or n or jid
    return who


def group_senders():
    """Who wrote each message from someone else in a group, as WhatsApp's own database says (ZGROUPMEMBER): (group id,
    text) -> [(Unix time, name)]. iLEAPP's WhatsApp module names the group instead (ILEAPP.md #25), so phone_whatsapp
    takes the sender from here: the iPhone backup's copy of the database (the one iLEAPP read), then this Mac's."""
    out, names = {}, None
    for db in (phone(*PHONE_DB), DB):
        if not db.exists():
            continue
        try:
            con = connect(db if db != DB else snapshot_sqlite(DB, "whatsapp/ChatStorage.sqlite"))
            names = names or Resolver()
            who = namer(con, names)
            jids = {r["Z_PK"]: r["ZCONTACTJID"] or "" for r in con.execute("select Z_PK, ZCONTACTJID from ZWACHATSESSION")}
            members = {r["Z_PK"]: who(r["ZMEMBERJID"], r["ZCONTACTNAME"]) for r in con.execute(
                f"select Z_PK, {pick(con, 'ZWAGROUPMEMBER', ('ZMEMBERJID', 'ZCONTACTNAME'))} from ZWAGROUPMEMBER")}
            for r in con.execute("select ZMESSAGEDATE, ZCHATSESSION, ZTEXT, ZGROUPMEMBER from ZWAMESSAGE "
                                 "where ZISFROMME = 0 and ZGROUPMEMBER is not null and ZMESSAGEDATE is not null"):
                jid = jids.get(r["ZCHATSESSION"], "")
                if jid.endswith("@g.us") and members.get(r["ZGROUPMEMBER"]):
                    out.setdefault((jid, r["ZTEXT"] or ""), []).append((r["ZMESSAGEDATE"] + APPLE, members[r["ZGROUPMEMBER"]]))
            con.close()
        except (sqlite3.Error, OSError):
            continue
    return out


def group_sender(senders, jid, text, t):
    """The one sender of a group message at about this time (within a second) with this text, or None."""
    try:
        t = float(t)
    except (TypeError, ValueError):
        return None
    found = {name for u, name in senders.get((jid, text or ""), ()) if abs(u - t) < 1}
    return found.pop() if len(found) == 1 else None


def main():
    with Writer("whatsapp", AVENUE) as w:
        if not DB.exists():
            return
        con = connect(snapshot_sqlite(DB, "whatsapp/ChatStorage.sqlite"))
        names = Resolver()
        tables = {r[0] for r in con.execute("select name from sqlite_master where type = 'table'")}
        if "ZWAMESSAGE" not in tables:  # made, never written to (WhatsApp installed, not signed in)
            w.notes["empty"] = 1
            return
        who = namer(con, names)
        none = "select 1 where 0"

        chats = {}
        for r in con.execute(f"select Z_PK, {pick(con, 'ZWACHATSESSION', ('ZCONTACTJID', 'ZPARTNERNAME', 'ZSESSIONTYPE'))} "
                             "from ZWACHATSESSION" if "ZWACHATSESSION" in tables else none):
            jid = r["ZCONTACTJID"] or ""
            group = jid.endswith("@g.us") or r["ZSESSIONTYPE"] == 1
            name = "Status updates" if jid == STATUS else r["ZPARTNERNAME"] if group else who(jid, r["ZPARTNERNAME"])
            chats[r["Z_PK"]] = {"jid": jid, "group": group, "name": name, "people": []}
        members = {}
        for r in con.execute(f"select Z_PK, {pick(con, 'ZWAGROUPMEMBER', ('ZCHATSESSION', 'ZMEMBERJID', 'ZCONTACTNAME'))} "
                             "from ZWAGROUPMEMBER" if "ZWAGROUPMEMBER" in tables else none):
            members[r["Z_PK"]] = name = who(r["ZMEMBERJID"], r["ZCONTACTNAME"])
            if r["ZCHATSESSION"] in chats and name:
                chats[r["ZCHATSESSION"]]["people"].append(name)
        for c in chats.values():
            c["people"] = sorted(set(c["people"])) if c["group"] else [] if c["jid"] == STATUS else [c["name"]]
        media = {}
        if "ZWAMEDIAITEM" in tables:
            cols = ("ZMESSAGE", "ZMEDIALOCALPATH", "ZTITLE", "ZFILESIZE", "ZLATITUDE", "ZLONGITUDE", "ZVCARDNAME")
            for r in con.execute(f"select {pick(con, 'ZWAMEDIAITEM', cols)} from ZWAMEDIAITEM where ZMESSAGE is not null"):
                media[r["ZMESSAGE"]] = r

        on_phone = phone_stanzas()
        wanted = ("ZCHATSESSION", "ZISFROMME", "ZMESSAGEDATE", "ZTEXT", "ZSTANZAID", "ZMESSAGETYPE", "ZGROUPMEMBER",
                  "ZGROUPEVENTTYPE", "ZFROMJID", "ZSTARRED")
        for r in con.execute(f"select Z_PK, {pick(con, 'ZWAMESSAGE', wanted)} from ZWAMESSAGE order by ZMESSAGEDATE"):
            rid = r["ZSTANZAID"] or f"pk:{r['Z_PK']}"
            if w.has(rid):
                rid = f"{rid}:{r['Z_PK']}"
            if r["ZSTANZAID"] and r["ZSTANZAID"] in on_phone:
                w.skip(rid)  # the iPhone backup's copy has it (phone_whatsapp)
                w.notes["in_the_iphone_backup"] = w.notes.get("in_the_iphone_backup", 0) + 1
                continue
            chat = chats.get(r["ZCHATSESSION"]) or {"jid": None, "group": False, "name": None, "people": []}
            me = bool(r["ZISFROMME"])
            if chat["jid"] == STATUS and not me:
                w.notes["others_status_updates"] = w.notes.get("others_status_updates", 0) + 1
                continue
            if me:
                author = "me"
            elif chat["group"]:  # in a group, the message's sender is one of its members
                author = members.get(r["ZGROUPMEMBER"]) or "someone in the group"
            else:
                author = chat["name"] or who(r["ZFROMJID"]) or "someone"
            kind_no, m = r["ZMESSAGETYPE"] or 0, media.get(r["Z_PK"])
            text = (r["ZTEXT"] or "").strip()
            attachment = TYPES.get(kind_no)
            if attachment:  # its caption, a file's name or a contact card's name, after what it is
                caption = text or (m and (m["ZVCARDNAME"] if kind_no == 4 else m["ZTITLE"])) or ""
                text = f"[{attachment}] {caption}".strip()
            files = [str(f) for f in (CONTAINER / "Message" / m["ZMEDIALOCALPATH"], CONTAINER / m["ZMEDIALOCALPATH"])
                     if f.is_file()][:1] if m and m["ZMEDIALOCALPATH"] else []
            # a system row is the event; ZGROUPEVENTTYPE is set on ordinary messages too (2 on nearly every one)
            if kind_no == SYSTEM:
                kind, text = "event", text or "A change to the group: who is in it, its name or its picture"
            elif chat["jid"] == STATUS:
                kind, text = "post", text or "[status update]"
            else:
                kind, text = "message", text or ("[deleted message]" if kind_no == DELETED else "[empty message]" if not kind_no
                                                 else f"[message of type {kind_no}]")
            meta = {"group": chat["group"] or None, "type": attachment, "tier": "deleted" if kind_no == DELETED else None,
                    "starred": bool(r["ZSTARRED"]) or None, "chat": chat["jid"],
                    "lat": m["ZLATITUDE"] if m and kind_no == 5 else None, "lon": m["ZLONGITUDE"] if m and kind_no == 5 else None,
                    "attachment": m["ZMEDIALOCALPATH"] if m else None, "bytes": m["ZFILESIZE"] if m else None,
                    "files": files or None, "group_event": (r["ZGROUPEVENTTYPE"] or None) if kind_no == SYSTEM else None}
            w.add(id=rid, kind=kind, ts=from_apple(r["ZMESSAGEDATE"]), author=author, is_me=me, thread=chat["jid"],
                  thread_name=chat["name"], participants=chat["people"], text=text,
                  meta={k: v for k, v in meta.items() if v is not None})


if __name__ == "__main__":
    main()
