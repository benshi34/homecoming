"""WhatsApp on this Mac: the WhatsApp app's ChatStorage.sqlite, the same database (and schema) as the iPhone app's.
Both sides of every chat it has, who wrote each message in a group, and what kind of attachment a message had.

The iPhone backup's WhatsApp comes in through iLEAPP as phone_whatsapp. A message both copies have (same stanza id,
WhatsApp's own message id) is kept there and skipped here, so it's counted once; the Mac adds only what the phone's
copy doesn't have. iLEAPP names a group message's sender after the group (ILEAPP.md #25): ileapp.py takes who wrote it
from these databases instead (group_senders)."""

import datetime as dt
import json
import sqlite3

from common import APPLE_EPOCH, LIB, MANIFEST, Writer, columns, connect, from_apple, from_unix, phone, snapshot_sqlite
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


def protobuf(b):
    """A protobuf message's fields, [(number, value)]: an int for a varint, bytes for anything length-delimited or
    fixed-width; [] for bytes that aren't one. WhatsApp keeps a message's quote and its reactions this way."""
    out, i = [], 0
    try:
        while i < len(b):
            key, i = _varint(b, i)
            kind = key & 7
            if kind == 0:
                v, i = _varint(b, i)
            elif kind == 2:
                n, i = _varint(b, i)
                v, i = b[i:i + n], i + n
            elif kind in (1, 5):
                n = 8 if kind == 1 else 4
                v, i = b[i:i + n], i + n
            else:
                return []
            if i > len(b):
                return []
            out.append((key >> 3, v))
    except IndexError:
        return []
    return out


def _varint(b, i):
    n = shift = 0
    while True:
        c = b[i]
        i += 1
        n |= (c & 0x7F) << shift
        shift += 7
        if c < 0x80:
            return n, i


def first(fields, number):
    return next((v for f, v in fields if f == number), None)


def text_of(b):
    """What a quoted message (ZMETADATA's field 19, a message of WhatsApp's own) said: its text (1), a link's or a
    formatted message's (6.1), a picture's or video's caption (3.3, 4.7 by forensic write-ups); else nothing."""
    fields = protobuf(b or b"")
    for path in ((1,), (6, 1), (3, 3), (4, 7)):
        v = first(fields, path[0])
        for p in path[1:]:
            v = first(protobuf(v), p) if isinstance(v, bytes) else None
        if isinstance(v, bytes) and v:
            return v.decode("utf-8", "replace")
    return None


def reactions_of(blob):
    """A message's reactions, from ZWAMESSAGEINFO.ZRECEIPTINFO's field 7: each (1) with its own id (1), who (2, a jid;
    none and 6 set: yours), the emoji (3) and when, in ms (4). One with no emoji is a reaction taken back; a person's
    newest is the one that counts. -> [(jid or None, emoji or None, Unix ms)]."""
    out = []
    for f, v in protobuf(blob or b""):
        if f != 7 or not isinstance(v, bytes):
            continue
        for g, e in protobuf(v):
            d = dict(protobuf(e)) if g == 1 and isinstance(e, bytes) else {}
            if not d:
                continue
            emoji = d.get(3).decode("utf-8", "replace") if isinstance(d.get(3), bytes) else None
            jid = d.get(2).decode("utf-8", "replace") if isinstance(d.get(2), bytes) else None
            out.append((jid, emoji or None, d.get(4) if isinstance(d.get(4), int) else 0))
    return out


def standing(entries, name):
    """A message's reactions as they stand, from reactions_of: each person's newest, {who, reaction, ts} (yours, "me"),
    and the ones taken back, {who, ts}."""
    latest = {}
    for jid, emoji, at in sorted(entries, key=lambda x: x[2]):
        latest[jid] = (emoji, at)
    out = ([], [])
    for j, (e, at) in latest.items():
        x = {"who": "me" if j is None else name(j), "reaction": e, "ts": from_unix(at, "ms")}
        out[0 if e else 1].append({k: v for k, v in x.items() if v})
    return out


def phone_extras():
    """What the iPhone backup's WhatsApp says of each message beyond what iLEAPP reads: its reactions (as they stand,
    and the ones taken back) and what the message it replies to said. (chat jid, text) -> [(Unix time, meta)], for
    ileapp.py to find a phone_whatsapp message's by its chat, text and time, as it finds a group message's sender."""
    db = phone(*PHONE_DB)
    if not db.exists():
        return {}
    out = {}
    try:
        con = connect(db)
        tables = {r[0] for r in con.execute("select name from sqlite_master where type = 'table'")}
        if not {"ZWAMESSAGE", "ZWACHATSESSION"} <= tables:
            return {}
        who = namer(con, Resolver())
        by_jid = {r[0]: r[1] for r in con.execute("select ZMEMBERJID, ZCONTACTNAME from ZWAGROUPMEMBER where ZCONTACTNAME is not null")} \
            if "ZWAGROUPMEMBER" in tables else {}
        reacted = {r[0]: reactions_of(r[1]) for r in con.execute(
            f"select {pick(con, 'ZWAMESSAGEINFO', ('ZMESSAGE', 'ZRECEIPTINFO'))} from ZWAMESSAGEINFO") if r[0] and r[1]} \
            if "ZWAMESSAGEINFO" in tables else {}
        quotes = {r[0]: protobuf(r[1]) for r in con.execute(
            f"select {pick(con, 'ZWAMEDIAITEM', ('ZMESSAGE', 'ZMETADATA'))} from ZWAMEDIAITEM") if r[0] and r[1]} \
            if "ZWAMEDIAITEM" in tables else {}
        jids = {r[0]: r[1] or "" for r in con.execute("select Z_PK, ZCONTACTJID from ZWACHATSESSION")}
        said = {}
        for pk, chat, text, t, stanza in con.execute("select Z_PK, ZCHATSESSION, ZTEXT, ZMESSAGEDATE, ZSTANZAID from ZWAMESSAGE order by ZMESSAGEDATE"):
            if stanza and text:
                said[stanza] = text
            q = quotes.get(pk) or []
            quoted = first(q, 5).decode("utf-8", "replace") if isinstance(first(q, 5), bytes) else None
            reactions, taken_back = standing(reacted.get(pk, []), lambda j: by_jid.get(j) or who(j))
            meta = {k: v for k, v in (("reply_text", ((said.get(quoted) or text_of(first(q, 19)) or "")[:200] or None) if quoted else None),
                                      ("reactions", reactions), ("reactions_taken_back", taken_back)) if v}
            if meta and t is not None:
                out.setdefault((jids.get(chat, ""), text or ""), []).append((t + APPLE, meta))
        con.close()
    except (sqlite3.Error, OSError):
        return out
    return out


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

    # A newer jid is an account id, "<n>@lid", not a number: LID.sqlite has the number most have
    lids = {}
    if (CONTAINER / "LID.sqlite").exists():
        try:
            lcon = connect(snapshot_sqlite(CONTAINER / "LID.sqlite", "whatsapp/LID.sqlite"))
            lids = {r[0]: r[1] for r in lcon.execute("select ZIDENTIFIER, ZPHONENUMBER from ZWAZACCOUNT "
                                                       "where ZIDENTIFIER is not null and ZPHONENUMBER is not null")}
            lcon.close()
        except (sqlite3.Error, OSError):
            pass

    def who(jid, fallback=None):
        if jid and jid.endswith("@lid") and str(lids.get(jid) or "").isdigit():
            return who(f"{lids[jid]}@s.whatsapp.net", fallback or push.get(jid))
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
        members, by_jid = {}, {}
        for r in con.execute(f"select Z_PK, {pick(con, 'ZWAGROUPMEMBER', ('ZCHATSESSION', 'ZMEMBERJID', 'ZCONTACTNAME'))} "
                             "from ZWAGROUPMEMBER" if "ZWAGROUPMEMBER" in tables else none):
            members[r["Z_PK"]] = name = who(r["ZMEMBERJID"], r["ZCONTACTNAME"])
            if r["ZMEMBERJID"] and name:
                by_jid.setdefault(r["ZMEMBERJID"], name)
            if r["ZCHATSESSION"] in chats and name:
                chats[r["ZCHATSESSION"]]["people"].append(name)
        for c in chats.values():
            c["people"] = sorted(set(c["people"])) if c["group"] else [] if c["jid"] == STATUS else [c["name"]]
        media = {}
        if "ZWAMEDIAITEM" in tables:
            cols = ("ZMESSAGE", "ZMEDIALOCALPATH", "ZTITLE", "ZFILESIZE", "ZLATITUDE", "ZLONGITUDE", "ZVCARDNAME", "ZMETADATA")
            for r in con.execute(f"select {pick(con, 'ZWAMEDIAITEM', cols)} from ZWAMEDIAITEM where ZMESSAGE is not null"):
                media[r["ZMESSAGE"]] = r

        # each message's reactions, by its Z_PK
        reacted = {}
        if "ZWAMESSAGEINFO" in tables:
            for r in con.execute(f"select {pick(con, 'ZWAMESSAGEINFO', ('ZMESSAGE', 'ZRECEIPTINFO'))} from ZWAMESSAGEINFO"):
                if r["ZMESSAGE"] and r["ZRECEIPTINFO"]:
                    reacted[r["ZMESSAGE"]] = reactions_of(r["ZRECEIPTINFO"])
        said, ids = {}, {}  # stanza id -> what it said, and its record's id: a quote names the message it quotes by it
        on_phone = phone_stanzas()
        wanted = ("ZCHATSESSION", "ZISFROMME", "ZMESSAGEDATE", "ZTEXT", "ZSTANZAID", "ZMESSAGETYPE", "ZGROUPMEMBER",
                  "ZGROUPEVENTTYPE", "ZFROMJID", "ZSTARRED")
        for r in con.execute(f"select Z_PK, {pick(con, 'ZWAMESSAGE', wanted)} from ZWAMESSAGE order by ZMESSAGEDATE"):
            rid = r["ZSTANZAID"] or f"pk:{r['Z_PK']}"
            if w.has(rid):
                rid = f"{rid}:{r['Z_PK']}"
            if r["ZSTANZAID"]:
                ids.setdefault(r["ZSTANZAID"], rid)
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
            if r["ZSTANZAID"] and text:
                said.setdefault(r["ZSTANZAID"], text)
            # a reply: the quoted message's stanza id (5) and what it said (19) in its media item's metadata
            q = protobuf(m["ZMETADATA"]) if m and m["ZMETADATA"] else []
            quoted = first(q, 5).decode("utf-8", "replace") if isinstance(first(q, 5), bytes) else None
            reply_text = (said.get(quoted) or text_of(first(q, 19))) if quoted else None
            reactions, taken_back = standing(reacted.get(r["Z_PK"], []), lambda j: by_jid.get(j) or who(j))
            meta = {"group": chat["group"] or None, "type": attachment, "tier": "deleted" if kind_no == DELETED else None,
                    "starred": bool(r["ZSTARRED"]) or None, "chat": chat["jid"],
                    "lat": m["ZLATITUDE"] if m and kind_no == 5 else None, "lon": m["ZLONGITUDE"] if m and kind_no == 5 else None,
                    "attachment": m["ZMEDIALOCALPATH"] if m else None, "bytes": m["ZFILESIZE"] if m else None,
                    "files": files or None, "group_event": (r["ZGROUPEVENTTYPE"] or None) if kind_no == SYSTEM else None,
                    "reply_to": ids.get(quoted, quoted) if quoted else None, "reply_text": (reply_text or "")[:200] or None,
                    "reactions": reactions or None, "reactions_taken_back": taken_back or None}
            w.add(id=rid, kind=kind, ts=from_apple(r["ZMESSAGEDATE"]), author=author, is_me=me, thread=chat["jid"],
                  thread_name=chat["name"], participants=chat["people"], text=text,
                  meta={k: v for k, v in meta.items() if v is not None})


if __name__ == "__main__":
    main()
