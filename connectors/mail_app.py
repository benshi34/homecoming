"""Apple Mail: every account added to Mail on this Mac (Gmail, Exchange and Outlook.com, iCloud, school and work IMAP),
read where Mail keeps it, so no mailbox has to be exported by hand."""

import hashlib
import json
import re
import sqlite3

from common import ID_AT_START, LIB, NORM, RAW, Writer, connect, from_unix, snapshot_sqlite, write_atomic
from email_parse import SENT_FOLDERS, SKIP_FOLDERS, TIER_OF_FOLDER, parse
from identity import ME

AVENUE = ("Local: ~/Library/Mail/V*/<account>/<mailbox>.mbox/**/Messages/*.emlx (first line = byte count, then the "
          "RFC 822 message, then a plist; .partial.emlx when Mail hasn't downloaded the attachments). Needs Full Disk "
          "Access, plus the account added in System Settings > Internet Accounts with Mail on and Mail left open to "
          "download messages. Accounts are named from ~/Library/Accounts. Sent mailboxes are read first, so a message "
          "in Sent and in All Mail counts as sent. The same message in a mailbox export is kept once in the index "
          "(build_index.py). A message file unchanged since the last run, which Mail hasn't marked read, flagged or sorted "
          "since, isn't read again (corpus/raw/mail/read.json): its record is carried over, in its place among the rest.")

# What a message file held when it was last read: its size and time, the email's id, and what Mail said of it (read,
# flagged, its category). Kept until the reader or the user's addresses (which decide what's theirs) change.
READ = RAW / "mail" / "read.json"
READER = "4"  # 4: what Mail says of each message (read, flagged, category) is part of what a file is


def mail_root():
    """Mail's newest data folder (V10 on macOS 14 and later)."""
    root = LIB / "Mail"
    found = sorted(root.glob("V[0-9]*"), key=lambda p: int(re.sub(r"\D", "", p.name) or 0)) if root.exists() else []
    return found[-1] if found else None


def account_names():
    """Mail's account folder (a UUID) -> the account's address or name, from Internet Accounts (a Mail account's own
    row can be a child of the one holding the address)."""
    db = LIB / "Accounts/Accounts4.sqlite"
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
        try:
            rows = con.execute("select Z_PK, ZIDENTIFIER, coalesce(ZUSERNAME, ZACCOUNTDESCRIPTION), ZPARENTACCOUNT from ZACCOUNT").fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return {}
    by_pk = {pk: name for pk, _, name, _ in rows}
    return {ident: name or by_pk.get(parent) for _, ident, name, parent in rows if ident and (name or by_pk.get(parent))}


def mailbox_of(path, account_dir):
    """"Inbox", "[Gmail]/Sent Mail": the .mbox folders between the account and the message."""
    parts = path.relative_to(account_dir).parts
    return "/".join(p[:-5] for p in parts if p.endswith(".mbox")) or None


def order(item):
    """Sent first (a message there is the user's own), then everything else, junk and trash last."""
    base = (item[2] or "").rsplit("/", 1)[-1].lower()
    return (0 if base in SENT_FOLDERS else 2 if base in SKIP_FOLDERS else 1, str(item[0]))


# Mail's own sorting of a message (message_global_data.model_category): Primary, then the ones it sorts as automatic.
# 0 is Primary for certain (on one Mac: 81% read, no no-reply senders); the order of the other three is Mail's tabs'
# (unconfirmed which is which, but all three are mail sent by machines).
CATEGORIES = {0: "primary", 1: "transactions", 2: "updates", 3: "promotions"}


def envelope(root):
    """Message row id (an .emlx file's name) -> whether it was read, flagged, when last viewed, and Mail's category."""
    db = root / "MailData/Envelope Index"
    if not db.exists():
        return {}
    try:
        con = connect(snapshot_sqlite(db, "mail/envelope.sqlite"))
        cols = {r[1] for r in con.execute("pragma table_info(message_global_data)")}
        cat = "g.model_category" if "model_category" in cols else "null"
        rows = con.execute(f"""select m.ROWID id, m.read, m.flagged, m.date_last_viewed viewed, {cat} category
                               from messages m left join message_global_data g on g.ROWID = m.global_message_id""").fetchall()
    except sqlite3.Error:
        return {}
    return {r["id"]: {"read": bool(r["read"]), "flagged": bool(r["flagged"]) or None, "viewed": from_unix(r["viewed"]),
                      "category": CATEGORIES.get(r["category"])} for r in rows}


class LastRun:
    """The last run's records in mail.jsonl, found by id where each line starts: only the ones carried over are read."""

    def __init__(self, path):
        self.at = {}
        try:
            self.f = open(path, "rb")
        except OSError:
            self.f = None
            return
        pos = 0
        for line in self.f:
            m = ID_AT_START.match(line)
            if m:
                self.at[json.loads(m.group(1))] = pos
            pos += len(line)

    def get(self, rid):
        if self.f is None or rid not in self.at:
            return None
        self.f.seek(self.at[rid])
        try:
            rec = json.loads(self.f.readline())
        except ValueError:
            return None
        return rec if isinstance(rec, dict) and rec.get("id") == rid else None

    def close(self):
        if self.f:
            self.f.close()


def main():
    root = mail_root()
    state = envelope(root) if root else {}
    names = account_names()
    found = []
    if root:
        for account in sorted(p for p in root.iterdir() if p.is_dir() and p.name != "MailData"):
            for path in account.glob("**/Messages/*.emlx"):
                found.append((path, account.name, mailbox_of(path, account)))
    found.sort(key=order)
    key = hashlib.sha1(json.dumps([READER, sorted(ME["emails_l"])]).encode()).hexdigest()[:12]
    try:
        cache = json.loads(READ.read_text())
        before = cache["files"] if cache.get("key") == key and (NORM / "mail.jsonl").exists() else {}
    except (OSError, ValueError, KeyError, TypeError):
        before = {}
    last = LastRun(NORM / "mail.jsonl")
    files = {}
    try:
        with Writer("mail", AVENUE) as w:
            for path, account, mailbox in found:
                rel = str(path.relative_to(root))
                try:
                    st = path.stat()
                except OSError:
                    continue
                # As Mail has it: read or not, flagged, last viewed, and its own category (123.emlx is message row 123).
                # Part of what the file is: a message read since is read again, though its file didn't change.
                row = path.name.split(".", 1)[0]
                seen = state.get(int(row)) if row.isdigit() else None
                now = [st.st_size, st.st_mtime_ns, None, hashlib.sha1(json.dumps(seen, sort_keys=True).encode()).hexdigest()[:8]]
                was = before.get(rel)
                old = last.get(was[2]) if isinstance(was, list) and len(was) == 4 and [*was[:2], was[3]] == [*now[:2], now[3]] else None
                if old is not None:
                    # Unchanged: its record carries over, here, in the same order as one read again (Sent first), so
                    # the copy in Sent stays the one kept.
                    files[rel] = was
                    if not w.has(old["id"]):
                        w.add(**old)
                    continue
                try:
                    data = path.read_bytes()
                    n, _, rest = data.partition(b"\n")
                    rec = parse(rest[:int(n)] if n.strip().isdigit() else rest)
                except (OSError, ValueError):
                    continue
                now[2] = rec["id"]
                files[rel] = now
                labels = rec.pop("_labels")
                if w.has(rec["id"]):
                    continue
                base = (mailbox or "").rsplit("/", 1)[-1].lower()
                if base in SKIP_FOLDERS or "Spam" in labels.split(","):
                    rec["meta"]["tier"] = TIER_OF_FOLDER.get(base, "spam")
                if base in SENT_FOLDERS or base in ("drafts", "outbox"):
                    rec["is_me"], rec["author"] = True, "me"
                rec["meta"].update({"folder": mailbox, "account": names.get(account) or account})
                if seen:
                    rec["meta"].update({k: v for k, v in seen.items() if v is not None})
                w.add(kind="email", **rec)
            w.notes["read_again"] = len(files) - sum(1 for r, v in files.items() if before.get(r) == v)
    finally:
        last.close()
    write_atomic(READ, json.dumps({"key": key, "files": files}))


if __name__ == "__main__":
    main()
