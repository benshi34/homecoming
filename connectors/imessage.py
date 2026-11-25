"""iMessage / SMS / RCS from the Messages app database: the Mac's chat.db, plus the iPhone's sms.db when
connectors/iphone_backup.py has extracted it from a local backup (same schema). The phone usually holds far
more history than the Mac ever downloaded from iCloud; a message present in both is kept once (by guid). A database
without who is in each chat, or without chats at all, is read all the same (the joins are LEFT, as iLEAPP's sms
module makes them); one that can't be read is noted (notes.unreadable), and the other copy is read."""

import plistlib
import sqlite3
from pathlib import Path

from common import CORPUS, LIB, Writer, columns, connect, from_apple, heard as heard_here, phone, select, snapshot_sqlite, tables
from contacts import Resolver

AVENUE = ("Local SQLite: ~/Library/Messages/chat.db (synced from iPhone via iCloud Messages), plus "
          "HomeDomain/Library/SMS/sms.db from an iPhone backup (connectors/iphone_backup.py). Needs Full Disk Access. Newer macOS stores many bodies only in message.attributedBody "
          "(NSAttributedString typedstream); decoded by reading the NSString payload.")

TAPBACKS = {2000: "loved", 2001: "liked", 2002: "disliked", 2003: "laughed at",
            2004: "emphasized", 2005: "questioned", 2006: "reacted to", 2007: "stickered",
            1000: "stickered"}  # 1000: a sticker placed on a message (iOS 10-16); 3000-3007 take a tapback back
# Send with effect, by the end of its id (com.apple.MobileSMS.expressivesend.impact, com.apple.messages.effect.CKLasersEffect).
EFFECTS = {"impact": "slam", "loud": "loud", "gentle": "gentle", "invisibleink": "invisible ink", "CKConfettiEffect": "confetti",
           "CKEchoEffect": "echo", "CKFireworksEffect": "fireworks", "CKLasersEffect": "lasers", "CKHappyBirthdayEffect": "balloons",
           "CKHeartEffect": "love", "CKSpotlightEffect": "spotlight", "CKShootingStarEffect": "celebration", "CKSparklesEffect": "celebration"}
# Messages' filtering of a conversation (chat.is_filtered): from someone not in your contacts, or junk.
FILTERED = {1: "unknown sender", 2: "junk"}


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
    if p >= len(blob):  # cut off where its length would be
        return None
    n = blob[p]
    if n == 0x81:
        n, p = int.from_bytes(blob[p + 1:p + 3], "little"), p + 3
    elif n == 0x82:
        n, p = int.from_bytes(blob[p + 1:p + 5], "little"), p + 5
    else:
        p += 1
    return blob[p:p + n].decode("utf-8", "replace")


def audio_transcription(blob):
    """What Apple's transcription of an audio message says (iOS 17 on): attributedBody's IMAudioTranscription attribute,
    a string after a few bytes naming its class, its length as message text's is. None when there's none, or it isn't
    clean text."""
    i = blob.find(b"IMAudioTranscription") if blob else -1
    if i < 0:
        return None
    p = i + len(b"IMAudioTranscription")
    for _ in range(8):  # past the object and class bytes (0x83 and up, apart from the two length markers)
        if p >= len(blob) or blob[p] < 0x83:
            break
        p += 1
    if p >= len(blob) or blob[p] == 0:
        return None
    n = blob[p]
    if n == 0x81:
        n, p = int.from_bytes(blob[p + 1:p + 3], "little"), p + 3
    elif n == 0x82:
        n, p = int.from_bytes(blob[p + 1:p + 5], "little"), p + 5
    else:
        p += 1
    try:
        text = blob[p:p + n].decode("utf-8").strip()
    except UnicodeDecodeError:
        return None
    return text if text and len(blob) >= p + n else None


def summary_info(blob):
    """message.message_summary_info (macOS 13 on): a binary plist of what became of each part of a message. "ec": part ->
    its versions as it was edited, oldest first ({"d": Apple seconds, "t": that version's attributedBody}); "rp": the
    parts unsent. An unsend leaves text and attributedBody empty; macOS 15 on, date_retracted stays 0 and date_edited
    has its time (as imessage-exporter and imessage-unsent read it)."""
    if not blob:
        return {}
    try:
        info = plistlib.loads(blob)
    except Exception:  # a plist this reader doesn't know
        return {}
    return info if isinstance(info, dict) else {}


def versions(info):
    """Each edited part's versions, oldest first, as (Apple time, text): the last is what it says now. A part since
    unsent isn't one."""
    ec, rp = info.get("ec"), info.get("rp")
    gone = {str(x) for x in rp} if isinstance(rp, list) else set()
    out = []
    for part in sorted(ec, key=lambda k: int(k) if str(k).isdigit() else 0) if isinstance(ec, dict) else []:
        events = ec[part] if isinstance(ec[part], list) and str(part) not in gone else []
        said = [(e.get("d"), decode_attributed_body(e["t"]) if isinstance(e.get("t"), bytes) else None) for e in events if isinstance(e, dict)]
        said = [(d if isinstance(d, (int, float)) else None, t.replace("\ufffc", "").strip()) for d, t in said if t]
        out.append([(d, t) for d, t in said if t])
    return [v for v in out if v]


def reacted_to(guid):
    """The message a tapback is on, by its guid (which is its record's id): associated_message_guid is "p:<part>/<guid>"
    for a part of it, "bp:<guid>" for the whole bubble."""
    if not guid:
        return None
    if guid.startswith("p:") and "/" in guid:
        return guid.split("/", 1)[1]
    return guid[3:] if guid.startswith("bp:") else guid


def attachment_file(path, copy):
    """Where an attachment's bytes are (relative to the repo, like imports.save_media), if this copy of the database has them: the phone's
    are in the backup mirror (only ~1k of 30k; the rest were offloaded to iCloud), the Mac's in ~/Library/Messages."""
    if not path:
        return None
    if copy == "iphone" and "Library/SMS/" in path:  # ~/Library/SMS/..., or /var/mobile/Library/SMS/... in older ones
        f = phone("MediaDomain", path[path.index("Library/SMS/"):])
        return str(f.relative_to(CORPUS)) if f.exists() else None
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


def effect(style):
    if not style:
        return None
    end = style.rsplit(".", 1)[-1]
    return EFFECTS.get(end, end)


def messages(con, names, copy):
    """Yield one record (as Writer.add kwargs) per message in an open Messages database."""
    have = tables(con)
    none = "select 1 where 0"
    handles = {r["ROWID"]: r["id"] for r in con.execute("select ROWID, id from handle" if "handle" in have else none)}
    members = {}
    for r in con.execute("select chat_id, handle_id from chat_handle_join" if "chat_handle_join" in have else none):
        members.setdefault(r["chat_id"], []).append(names.label(handles.get(r["handle_id"], "?")))
    chats = {}
    want = ("ROWID", "guid", "style", "display_name", "chat_identifier", "is_filtered")
    for r in con.execute(select(con, "chat", want) if "chat" in have else none):
        people = sorted(members.get(r["ROWID"], []))
        chats[r["ROWID"]] = {
            "guid": r["guid"], "group": r["style"] == 43, "people": people,
            "name": r["display_name"] or ", ".join(people) or (names.label(r["chat_identifier"]) if r["chat_identifier"] else None),
            "filtered": FILTERED.get(r["is_filtered"]),
        }
    msg_chat = {}
    for r in con.execute("select message_id, min(chat_id) chat_id from chat_message_join group by message_id"
                         if "chat_message_join" in have else none):
        msg_chat[r["message_id"]] = r["chat_id"]
    attachments = {}
    for r in con.execute("""select j.message_id, a.transfer_name, a.mime_type, a.filename, a.total_bytes
                            from message_attachment_join j join attachment a on a.ROWID = j.attachment_id"""
                         if {"message_attachment_join", "attachment"} <= have else "select 1 where 0"):
        attachments.setdefault(r["message_id"], []).append(
            {"name": r["transfer_name"], "mime": r["mime_type"], "path": r["filename"], "bytes": r["total_bytes"],
             "file": attachment_file(r["filename"], copy)})
    # Every column but these few only if this database has it: older ones (macOS 10.12 and before, an old iPhone's sms.db)
    # lack the body blob, tapbacks, replies and the rest; when it was delivered and read (yours: when they read it, with
    # read receipts on), a custom emoji reaction's emoji, the effect it was sent with, its subject line, its edits.
    cols = columns(con, "message")
    more = ", ".join(c if c in cols else f"null {c}" for c in (
        "attributedBody", "service", "item_type", "associated_message_type", "associated_message_guid", "thread_originator_guid",
        "is_audio_message", "balloon_bundle_id", "date_edited", "date_retracted", "message_summary_info", "group_action_type",
        "group_title", "other_handle", "date_read", "date_delivered", "associated_message_emoji", "expressive_send_style_id", "subject"))

    for r in con.execute(f"select ROWID, guid, text, handle_id, is_from_me, date, {more} from message order by date"):
        info = summary_info(r["message_summary_info"])
        text = (r["text"] or decode_attributed_body(r["attributedBody"]) or "").replace("\ufffc", "").strip()
        atts = attachments.get(r["ROWID"], [])
        unsent_parts = info.get("rp") if isinstance(info.get("rp"), list) else []
        # Unsent: nothing of it left. What it said, before an edit too, is gone as its sender meant.
        unsent = (from_apple(r["date_retracted"]) or from_apple(r["date_edited"]) or True
                  if not text and not atts and (unsent_parts or r["date_retracted"]) else None)
        edits = [] if unsent else versions(info)
        text = "[unsent message]" if unsent else text or "\n".join(v[-1][1] for v in edits)  # edited: its last version
        heard = audio_transcription(r["attributedBody"]) if r["is_audio_message"] and not unsent else None
        # none of Apple's: what transcribe.py heard in its audio on this Mac, if it has
        here = next((h for a in atts for h in [heard_here(a["path"])] if h), None) if r["is_audio_message"] and not heard else None
        heard = heard or here
        if heard:  # an audio message says what Apple heard in it
            text = (text + "\n" if text else "") + heard
        if atts:
            text = (text + "\n" if text else "") + "\n".join(
                f"[attachment: {a['name'] or 'file'} ({a['mime'] or '?'})]" for a in atts)
        if not text and (r["item_type"] or 0) != 0:
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
        kind = "reaction" if 2000 <= amt < 4000 or amt == 1000 else "message"
        meta = {"service": r["service"], "group": chat.get("group"),
                "reply_to": r["thread_originator_guid"],
                "reaction": TAPBACKS.get(amt) or (f"removed {TAPBACKS.get(amt - 1000, '')}".strip()
                                                  if 3000 <= amt < 4000 else None),
                "reacts_to": reacted_to(r["associated_message_guid"]) if kind == "reaction" else None,
                "audio": bool(r["is_audio_message"]) or None, "transcribed": True if heard else None, "transcribed_on": "this Mac" if here else None, "app": r["balloon_bundle_id"],
                "edited": None if unsent else from_apple(r["date_edited"]), "unsent": unsent,
                "edits": [{"at": from_apple(d), "text": t} for part in edits for d, t in part[:-1]] or None,
                "unsent_parts": len(unsent_parts) if unsent_parts and not unsent else None,
                "read": from_apple(r["date_read"]), "delivered": from_apple(r["date_delivered"]),
                "emoji": r["associated_message_emoji"] if kind == "reaction" else None,
                "effect": effect(r["expressive_send_style_id"]), "subject": r["subject"] or None,
                "filtered": chat.get("filtered"),
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
            try:
                if "message" not in tables(con):  # made, never written to
                    w.notes.setdefault("empty", []).append(copy)
                    continue
                for rec in messages(con, names, copy):
                    if not w.has(rec["id"]):
                        w.add(**rec)
                        added += 1
            except sqlite3.DatabaseError as e:
                print(f"[imessage] the {copy} copy can't be read ({e}); the other is read all the same")
                w.notes.setdefault("unreadable", []).append(copy)
            finally:
                con.close()
            print(f"[imessage] {added:,} messages from the {copy} copy")


if __name__ == "__main__":
    main()
