"""Apple Mail: every account added to Mail on this Mac (Gmail, Exchange and Outlook.com, iCloud, school and work IMAP),
read where Mail keeps it, so no mailbox has to be exported by hand."""

import hashlib
import json
import re
import sqlite3

from common import LIB, NORM, RAW, Writer
from email_parse import SENT_FOLDERS, SKIP_FOLDERS, TIER_OF_FOLDER, parse
from identity import ME

AVENUE = ("Local: ~/Library/Mail/V*/<account>/<mailbox>.mbox/**/Messages/*.emlx (first line = byte count, then the "
          "RFC 822 message, then a plist; .partial.emlx when Mail hasn't downloaded the attachments). Needs Full Disk "
          "Access, plus the account added in System Settings > Internet Accounts with Mail on and Mail left open to "
          "download messages. Accounts are named from ~/Library/Accounts. Sent mailboxes are read first, so a message "
          "in Sent and in All Mail counts as sent. The same message in a mailbox export is kept once in the index "
          "(build_index.py). A message file unchanged since the last run isn't read again (corpus/raw/mail/read.json): "
          "its record is carried over.")

# What a message file held when it was last read: its size and time, and the email's id. Kept until the reader or
# the user's addresses (which decide what's theirs) change.
READ = RAW / "mail" / "read.json"
READER = "2"


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


def main():
    root = mail_root()
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
    except (OSError, ValueError, KeyError):
        before = {}
    files = {}
    with Writer("mail", AVENUE) as w:
        for path, account, mailbox in found:
            rel = str(path.relative_to(root))
            try:
                st = path.stat()
            except OSError:
                continue
            was = before.get(rel)
            if was and was[:2] == [st.st_size, st.st_mtime_ns]:
                files[rel] = was  # unchanged: its record carries over from the last run
                continue
            try:
                data = path.read_bytes()
                n, _, rest = data.partition(b"\n")
                rec = parse(rest[:int(n)] if n.strip().isdigit() else rest)
            except (OSError, ValueError):
                continue
            files[rel] = [st.st_size, st.st_mtime_ns, rec["id"]]
            labels = rec.pop("_labels")
            if w.has(rec["id"]):
                continue
            base = (mailbox or "").rsplit("/", 1)[-1].lower()
            if base in SKIP_FOLDERS or "Spam" in labels.split(","):
                rec["meta"]["tier"] = TIER_OF_FOLDER.get(base, "spam")
            if base in SENT_FOLDERS or base in ("drafts", "outbox"):
                rec["is_me"], rec["author"] = True, "me"
            rec["meta"].update({"folder": mailbox, "account": names.get(account) or account})
            w.add(kind="email", **rec)
        w.notes["read_again"] = len(files) - sum(1 for r, v in files.items() if before.get(r) == v)
    READ.parent.mkdir(parents=True, exist_ok=True)
    READ.write_text(json.dumps({"key": key, "files": files}))


if __name__ == "__main__":
    main()
