"""iMessage / SMS / RCS from the Messages app database: the Mac's chat.db, plus the iPhone's sms.db when
connectors/iphone_backup.py has extracted it from a local backup (same schema). The phone usually holds far
more history than the Mac ever downloaded from iCloud; a message present in both is kept once (by guid)."""

from pathlib import Path

from common import CORPUS, LIB, Writer, connect, from_apple, phone, snapshot_sqlite
from contacts import Resolver

AVENUE = ("Local SQLite: ~/Library/Messages/chat.db (synced from iPhone via iCloud Messages), plus "
          "HomeDomain/Library/SMS/sms.db from an iPhone backup (connectors/iphone_backup.py). Needs Full Disk Access. Newer macOS stores many bodies only in message.attributedBody "
          "(NSAttributedString typedstream); decoded by reading the NSString payload.")

TAPBACKS = {2000: "loved", 2001: "liked", 2002: "disliked", 2003: "laughed at",
            2004: "emphasized", 2005: "questioned", 2006: "reacted to", 2007: "stickered"}


def decode_attributed_body(blob):
    """Extract the plain string from an NSAttributedString typedstream blob."""
    if not blob:
        return None
    i = blob.find(b"NSString")
    if i < 0:
        return None
    j = blob.find(b"+", i, i + 20)
    if j < 0:
        return None
    p = j + 1
    n = blob[p]
    if n == 0x81:
        n, p = int.from_bytes(blob[p + 1:p + 3], "little"), p + 3
    elif n == 0x82:
        n, p = int.from_bytes(blob[p + 1:p + 5], "little"), p + 5
    else:
        p += 1
    return blob[p:p + n].decode("utf-8", "replace")


def attachment_file(path, copy):
    """Where an attachment's bytes are (relative to the repo, like imports.save_media), if this copy of the database has them: the phone's
    are in the backup mirror (only ~1k of 30k; the rest were offloaded to iCloud), the Mac's in ~/Library/Messages."""
    if not path:
        return None
    if copy == "iphone" and path.startswith("~/Library/SMS/"):
        f = phone("MediaDomain", path[2:])
        return str(f.relative_to(CORPUS.parent)) if f.exists() else None
    if copy == "mac":
        f = Path(path).expanduser()
        return str(f) if f.exists() else None


def system_event(r, handles, names):
    """Text for a message row that is a chat event rather than a message (item_type != 0). Codes as observed in
    sms.db; the ones not pinned down keep their raw numbers in the text."""
    who = "I" if r["is_from_me"] else names.label(handles.get(r["handle_id"], "someone"))
    other = names.label(handles.get(r["other_handle"], "someone")) if r["other_handle"] else "someone"
    t, g = r["item_type"], r["group_action_type"] or 0
    if t == 1:
        return f"{who} {'removed' if g == 1 else 'added'} {other} {'from' if g == 1 else 'to'} the group"
    if t == 2:
        return f"{who} renamed the group to \"{r['group_title']}\"" if r["group_title"] else f"{who} removed the group name"
    if t == 3:
        return f"{who} left the conversation" if g == 0 else f"{who} changed the group photo (event 3/{g})"
    if t == 4:
        return f"{who} shared or stopped sharing location"
    if t == 5:
        return f"{who} kept an audio message"
    if t == 6:
        return f"FaceTime or SharePlay event by {who}"
    return f"chat event {t}/{g} by {who}"


def messages(con, names, copy):
    """Yield one record (as Writer.add kwargs) per message in an open Messages database."""
    handles = {r["ROWID"]: r["id"] for r in con.execute("select ROWID, id from handle")}
    members = {}
    for r in con.execute("select chat_id, handle_id from chat_handle_join"):
        members.setdefault(r["chat_id"], []).append(names.label(handles.get(r["handle_id"], "?")))
    chats = {}
    for r in con.execute("select ROWID, guid, style, display_name, chat_identifier from chat"):
        people = sorted(members.get(r["ROWID"], []))
        chats[r["ROWID"]] = {
            "guid": r["guid"], "group": r["style"] == 43, "people": people,
            "name": r["display_name"] or ", ".join(people) or names.label(r["chat_identifier"]),
        }
    msg_chat = {}
    for r in con.execute("select message_id, min(chat_id) chat_id from chat_message_join group by message_id"):
        msg_chat[r["message_id"]] = r["chat_id"]
    attachments = {}
    for r in con.execute("""select j.message_id, a.transfer_name, a.mime_type, a.filename, a.total_bytes
                            from message_attachment_join j join attachment a on a.ROWID = j.attachment_id"""):
        attachments.setdefault(r["message_id"], []).append(
            {"name": r["transfer_name"], "mime": r["mime_type"], "path": r["filename"], "bytes": r["total_bytes"],
             "file": attachment_file(r["filename"], copy)})
    cols = {r[1] for r in con.execute("pragma table_info(message)")}
    edited = "date_edited" if "date_edited" in cols else "null"
    retracted = "date_retracted" if "date_retracted" in cols else "null"
    group = ", ".join(c if c in cols else f"null {c}" for c in ("group_action_type", "group_title", "other_handle"))

    for r in con.execute(f"""select ROWID, guid, text, attributedBody, handle_id, is_from_me, date, service,
                                    item_type, associated_message_type, associated_message_guid,
                                    thread_originator_guid, is_audio_message, balloon_bundle_id,
                                    {edited} date_edited, {retracted} date_retracted, {group}
                             from message order by date"""):
        text = r["text"] or decode_attributed_body(r["attributedBody"]) or ""
        text = text.replace("\ufffc", "").strip()
        atts = attachments.get(r["ROWID"], [])
        if atts:
            text = (text + "\n" if text else "") + "\n".join(
                f"[attachment: {a['name'] or 'file'} ({a['mime'] or '?'})]" for a in atts)
        if not text and r["item_type"] != 0:
            event = system_event(r, handles, names)
            if not event:
                continue
            chat = chats.get(msg_chat.get(r["ROWID"]), {})
            me = bool(r["is_from_me"])
            yield dict(id=r["guid"], kind="event", ts=from_apple(r["date"]), is_me=me,
                       author="me" if me else names.label(handles.get(r["handle_id"], "?")),
                       thread=chat.get("guid"), thread_name=chat.get("name"), participants=chat.get("people"),
                       text=event, meta={"system": r["item_type"], "group_action": r["group_action_type"], "copy": copy})
            continue
        chat = chats.get(msg_chat.get(r["ROWID"]), {})
        me = bool(r["is_from_me"])
        amt = r["associated_message_type"] or 0
        kind = "reaction" if 2000 <= amt < 4000 else "message"
        meta = {"service": r["service"], "group": chat.get("group"),
                "reply_to": r["thread_originator_guid"],
                "reaction": TAPBACKS.get(amt) or (f"removed {TAPBACKS.get(amt - 1000, '')}".strip()
                                                  if 3000 <= amt < 4000 else None),
                "reacts_to": r["associated_message_guid"] if kind == "reaction" else None,
                "audio": bool(r["is_audio_message"]) or None, "app": r["balloon_bundle_id"],
                "edited": from_apple(r["date_edited"]), "unsent": from_apple(r["date_retracted"]),
                "attachments": [{k: a[k] for k in ("name", "mime", "path", "bytes")} for a in atts] or None,
                "files": [a["file"] for a in atts if a["file"]] or None,
                "system": r["item_type"] or None, "copy": copy}
        yield dict(id=r["guid"], kind=kind, ts=from_apple(r["date"]),
                   author="me" if me else names.label(handles.get(r["handle_id"], "?")), is_me=me,
                   thread=chat.get("guid"), thread_name=chat.get("name"), participants=chat.get("people"),
                   text=text, meta={k: v for k, v in meta.items() if v is not None})


def main():
    names = Resolver()
    sources = [("iphone", phone("HomeDomain", "Library/SMS/sms.db")), ("mac", snapshot_sqlite(LIB / "Messages/chat.db", "imessage/chat.db"))]
    with Writer("imessage", AVENUE) as w:
        for copy, db in sources:  # phone first: it has the most history; the Mac adds anything newer
            if not db.exists():
                continue
            added = 0
            con = connect(db)
            for rec in messages(con, names, copy):
                if not w.has(rec["id"]):
                    w.add(**rec)
                    added += 1
            con.close()
            print(f"[imessage] {added:,} messages from the {copy} copy")


if __name__ == "__main__":
    main()
