"""Signal Desktop on this Mac: its messages and calls, both sides, with who wrote each one in a group.

Signal keeps them in ~/Library/Application Support/Signal/sql/db.sqlite, encrypted with SQLCipher 4. Its key is in
config.json, itself encrypted (Electron's safeStorage) with the "Signal Safe Storage" password in the Keychain: macOS
asks once whether to let this read it. The database is decrypted page by page in memory (with `cryptography`, already
a dependency), its write-ahead log applied, and opened from there: no decrypted copy is written to disk. Signal
Desktop has only what reached it since it was linked to the phone (it doesn't sync older history), and attachments
stay encrypted in attachments.noindex: they're named, not read.

UMP_SIGNAL_KEY (the database key, 64 hex digits) skips the Keychain, for tests."""

import hashlib
import hmac
import json
import os
import sqlite3
import struct
import subprocess

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from common import LIB, Writer, from_unix

ROOT = LIB / "Application Support/Signal"
DB = ROOT / "sql/db.sqlite"
AVENUE = ("Local SQLCipher 4: ~/Library/Application Support/Signal/sql/db.sqlite (+ -wal), keyed by config.json's "
          "encryptedKey, decrypted with the Keychain's \"Signal Safe Storage\" (AES-128-CBC, PBKDF2-SHA1 saltysalt x1003). "
          "Pages decrypted in memory (AES-256-CBC, HMAC-SHA512 checked), never written out. messages (type incoming / "
          "outgoing; body, sent_at, sourceServiceId, json: attachments, quote, reactions, editHistory, "
          "deletedForEveryone, sticker), conversations (private / group; name, profileFullName, e164, serviceId, "
          "membersV2), message_attachments (names, not files: they stay encrypted), callsHistory. Only what Signal "
          "Desktop has had since it was linked.")

PAGE, RESERVE, IV, MAC = 4096, 80, 16, 64  # SQLCipher 4's defaults, Signal's settings
MESSAGES = ("incoming", "outgoing")


class SignalError(Exception):
    pass


def db_key():
    """The database key, hex: config.json's encryptedKey, decrypted with the Keychain's Signal Safe Storage."""
    if os.environ.get("UMP_SIGNAL_KEY"):
        return os.environ["UMP_SIGNAL_KEY"]
    try:
        enc = bytes.fromhex(json.loads((ROOT / "config.json").read_text())["encryptedKey"])
    except (OSError, ValueError, KeyError, TypeError):
        raise SignalError("no_key_in_config")
    if enc[:3] != b"v10":
        raise SignalError("unknown_key_format")
    r = subprocess.run(["security", "find-generic-password", "-ws", "Signal Safe Storage"], capture_output=True, timeout=120)
    if r.returncode != 0:
        raise SignalError("keychain_refused")  # not allowed in the dialog, or no such item
    kek = hashlib.pbkdf2_hmac("sha1", r.stdout.strip(), b"saltysalt", 1003, 16)
    d = Cipher(algorithms.AES(kek), modes.CBC(b" " * 16)).decryptor()
    u = padding.PKCS7(128).unpadder()
    try:
        key = (u.update(d.update(enc[3:]) + d.finalize()) + u.finalize()).decode("ascii")
    except ValueError:
        raise SignalError("key_not_decrypted")
    return key


def wal_checksum(data, endian, state=(0, 0)):
    """SQLite's rolling WAL checksum, over the header or one frame's first eight bytes and page."""
    a, b = state
    for x, y in struct.iter_unpack(endian + "II", data):
        a = (a + x + b) & 0xFFFFFFFF
        b = (b + y + a) & 0xFFFFFFFF
    return a, b


def decrypted(db, wal, key_hex):
    """The plain SQLite file, as bytes: every page of `db` (and, after it, every committed page of its write-ahead log)
    decrypted. A page whose HMAC doesn't match is a wrong key or a damaged file: an error, not a guess."""
    key = bytes.fromhex(key_hex)
    if len(db) < PAGE or len(db) % PAGE:
        raise SignalError("not_a_database")
    mac_key = hashlib.pbkdf2_hmac("sha512", key, bytes(b ^ 0x3A for b in db[:16]), 2, 32)

    def page(n, raw):
        start = 16 if n == 1 else 0  # page 1 begins with the file's salt
        body, iv = raw[start:PAGE - RESERVE], raw[PAGE - RESERVE:PAGE - RESERVE + IV]
        tag = raw[PAGE - RESERVE + IV:PAGE - RESERVE + IV + MAC]
        if not hmac.compare_digest(hmac.new(mac_key, body + iv + struct.pack("<I", n), hashlib.sha512).digest(), tag):
            raise SignalError("wrong_key_or_damaged")
        d = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        return (b"SQLite format 3\x00" if n == 1 else b"") + d.update(body) + d.finalize() + bytes(RESERVE)

    pages = {n + 1: db[n * PAGE:(n + 1) * PAGE] for n in range(len(db) // PAGE)}
    size = len(pages)
    # The write-ahead log: a 32-byte header, then frames (a 24-byte header, then a page). A frame belongs to it while
    # its salts and rolling checksum are valid; only through its last valid commit counts. The page HMAC alone
    # doesn't authenticate the frame's commit marker or its place in the transaction.
    if len(wal) >= 32:
        magic, version, page_size = struct.unpack(">III", wal[:12])
        if magic not in (0x377F0682, 0x377F0683) or version != 3007000 or page_size != PAGE:
            raise SignalError("invalid_wal_header")
        endian = "<" if magic == 0x377F0682 else ">"
        checksum = wal_checksum(wal[:24], endian)
        if checksum != struct.unpack(">II", wal[24:32]):
            raise SignalError("invalid_wal_header")
        salts, pending, at = wal[16:24], {}, 32
        while at + 24 + PAGE <= len(wal):
            n, commit = struct.unpack(">II", wal[at:at + 8])
            if wal[at + 8:at + 16] != salts:
                break
            raw = wal[at + 24:at + 24 + PAGE]
            checksum = wal_checksum(wal[at:at + 8] + raw, endian, checksum)
            if not n or checksum != struct.unpack(">II", wal[at + 16:at + 24]):
                break  # a torn or stale tail isn't part of a committed transaction
            pending[n] = raw
            if commit:
                pages.update(pending)
                pending, size = {}, commit
            at += 24 + PAGE
    return b"".join(page(n, pages[n]) for n in range(1, size + 1))


def open_db():
    """Signal's database, decrypted, as an in-memory SQLite connection."""
    db = DB.read_bytes()
    wal = DB.with_name("db.sqlite-wal")
    plain = bytearray(decrypted(db, wal.read_bytes() if wal.exists() else b"", db_key()))
    plain[18:20] = b"\x01\x01"  # its log is already applied: opened as a plain file, not one in WAL mode
    con = sqlite3.connect(":memory:")
    con.deserialize(bytes(plain))
    con.row_factory = sqlite3.Row
    return con


def name_of(c):
    """A person as you'd know them: your name for them (from your phone's contacts), their profile name, their number."""
    j = json.loads(c["json"] or "{}")
    profile = " ".join(x for x in (j.get("profileName"), j.get("profileFamilyName")) if x)
    return c["name"] or j.get("name") or c["profileFullName"] or profile or c["e164"] or j.get("e164")


def attachment_text(a):
    kind = (a["contentType"] or "").split("/")[0]
    label = a["fileName"] or {"image": "photo", "video": "video", "audio": "audio"}.get(kind, "file")
    return f"[attachment: {label} ({a['contentType']})]" if a["contentType"] else f"[attachment: {label}]"


def main():
    with Writer("signal", AVENUE) as w:
        if not DB.exists():
            return
        try:
            con = open_db()
        except SignalError as e:
            w.notes["not_read"] = str(e)
            return
        except (OSError, sqlite3.Error):
            w.notes["not_read"] = "unreadable"
            return
        me = None
        for r in con.execute("select json from items where id = 'uuid_id'"):
            me = (json.loads(r["json"]).get("value") or "").split(".")[0] or None
        cols = {r[1] for r in con.execute("pragma table_info(conversations)")}
        pick = ", ".join(c if c in cols else f"null {c}" for c in ("id", "json", "type", "name", "profileFullName", "e164", "serviceId", "groupId"))
        convs = {r["id"]: r for r in con.execute(f"select {pick} from conversations")}
        person = {c["serviceId"]: name_of(c) for c in convs.values() if c["serviceId"]}
        mine_conv = next((cid for cid, c in convs.items() if me and c["serviceId"] == me), None)  # Note to Self
        chats = {}
        for cid, c in convs.items():
            group = c["type"] == "group"
            if group:
                members = [m.get("aci") for m in json.loads(c["json"] or "{}").get("membersV2") or [] if isinstance(m, dict)]
                people = sorted({person.get(a) or "someone" for a in members if a and a != me})
                name = c["name"] or ", ".join(people) or "Signal group"
            else:
                name = name_of(c)
                people = [name] if name else []
            chats[cid] = {"group": group, "name": name, "people": people, "group_id": c["groupId"]}
        files = {}
        if "message_attachments" in {r[0] for r in con.execute("select name from sqlite_master where type = 'table'")}:
            for a in con.execute("select messageId, fileName, contentType from message_attachments "
                                 "where attachmentType = 'attachment' and editHistoryIndex = -1 order by orderInMessage"):
                files.setdefault(a["messageId"], []).append(a)

        skipped = {}
        # A reply's quote names the message it quotes by when that was sent (ms) and who wrote it, not by its id:
        # the messages so far by (conversation, sent_at), each with its sender (none: yours)
        sent = {}
        for r in con.execute("select id, conversationId, type, body, sent_at, sourceServiceId, json, isViewOnce, isErased "
                             "from messages order by sent_at"):
            if r["type"] not in MESSAGES:
                skipped[r["type"] or "none"] = skipped.get(r["type"] or "none", 0) + 1
                continue
            sent.setdefault((r["conversationId"], r["sent_at"]), []).append((r["id"], r["sourceServiceId"]))
            if w.has(r["id"]):
                continue
            j = json.loads(r["json"] or "{}")
            chat = chats.get(r["conversationId"]) or {"group": False, "name": None, "people": []}
            mine = r["type"] == "outgoing"
            author = "me" if mine else person.get(r["sourceServiceId"]) or (None if chat["group"] else chat["name"]) or "someone"
            deleted = bool(j.get("deletedForEveryone") or r["isErased"])
            parts = [r["body"] or ""]
            if j.get("sticker"):
                parts.append(f"[sticker {j['sticker'].get('emoji') or ''}]".replace(" ]", "]"))
            poll = j.get("poll") if isinstance(j.get("poll"), dict) else None
            if poll:
                parts.append(f"[poll] {poll.get('question') or ''}: " + " / ".join(str(o) for o in poll.get("options") or []))
            for card in j.get("contact") or []:
                n = card.get("name") if isinstance(card, dict) and isinstance(card.get("name"), dict) else {}
                parts.append(f"[contact card] {' '.join(x for x in (n.get('givenName'), n.get('familyName')) if x)}".strip())
            parts += [attachment_text(a) for a in files.get(r["id"], [])]
            text = "\n".join(p for p in parts if p).strip() or ("[deleted message]" if deleted else "[view-once message]"
                                                                if r["isViewOnce"] else "[empty message]")
            quote = j.get("quote") if isinstance(j.get("quote"), dict) else {}
            reply_to = None
            if quote.get("id"):
                same = sent.get((r["conversationId"], quote["id"])) or []
                by = quote.get("authorAci") or quote.get("author")
                pick_ = [x for x in same if by and x[1] == by] or [x for x in same if x[1] is None] or same
                reply_to = pick_[0][0] if pick_ and pick_[0][0] != r["id"] else None
            # A reaction's fromId is the reacting person's own conversation; yours is Note to Self.
            reactions = [{"emoji": x.get("emoji"), "from": "me" if x.get("fromId") == mine_conv else
                          name_of(convs[x["fromId"]]) if x.get("fromId") in convs else None}
                         for x in j.get("reactions") or [] if isinstance(x, dict)]
            meta = {"group": chat["group"] or None, "tier": "deleted" if deleted else None,
                    "edits": len(j["editHistory"]) - 1 if isinstance(j.get("editHistory"), list) and len(j["editHistory"]) > 1 else None,
                    "reply_to": reply_to,
                    "reply_text": (str(quote.get("text") or "")[:200] or None) if quote else None, "reactions": reactions or None, "view_once": bool(r["isViewOnce"]) or None}
            w.add(id=r["id"], kind="message", ts=from_unix(r["sent_at"], "ms"), author=author, is_me=mine, thread=r["conversationId"],
                  thread_name=chat["name"], participants=chat["people"], text=text,
                  meta={k: v for k, v in meta.items() if v is not None})
        w.notes["not_messages"] = skipped  # keys changing, profile changes, group changes, stories, calls' own rows

        # Calls: with a person (peerId is their service id) or in a group (its group id).
        by_group = {c["group_id"]: cid for cid, c in chats.items() if c["group_id"]}
        by_person = {c["serviceId"]: cid for cid, c in convs.items() if c["serviceId"]}
        if "callsHistory" in {r[0] for r in con.execute("select name from sqlite_master where type = 'table'")}:
            for c in con.execute("select callId, peerId, ringerId, mode, type, direction, status, timestamp, endedTimestamp from callsHistory"):
                rid = f"call:{c['callId']}"
                if w.has(rid):
                    continue
                cid = by_group.get(c["peerId"]) or by_person.get(c["peerId"])
                chat = chats.get(cid) or {"group": c["mode"] == "Group", "name": None, "people": []}
                out = c["direction"] == "Outgoing"
                kind = "video" if c["type"] == "Video" else "group" if c["mode"] == "Group" else "audio"
                seconds = (c["endedTimestamp"] - c["timestamp"]) / 1000 if c["endedTimestamp"] and c["timestamp"] else None
                w.add(id=rid, kind="call", ts=from_unix(c["timestamp"], "ms"), author="me" if out else person.get(c["ringerId"]) or chat["name"] or "someone",
                      is_me=out, thread=cid, thread_name=chat["name"], participants=chat["people"],
                      text=f"{c['direction']} {kind} call on Signal: {(c['status'] or '').lower()}",
                      meta={k: v for k, v in (("status", c["status"]), ("mode", c["mode"]), ("type", c["type"]),
                                              ("seconds", seconds), ("group", chat["group"] or None)) if v is not None})
        con.close()


if __name__ == "__main__":
    main()
