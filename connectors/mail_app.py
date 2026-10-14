"""Apple Mail: every account added to Mail.app (Gmail, Exchange/Office 365, iCloud, IMAP)."""

from common import LIB, Writer
from email_parse import parse

AVENUE = ("Local: ~/Library/Mail/V10/<account>/<mailbox>.mbox/**/Messages/*.emlx (first line = byte count, "
          "then the RFC 822 message, then a plist). Needs Full Disk Access, plus the account added in System "
          "Settings > Internet Accounts with Mail enabled and Mail.app left open to download messages.")


def main():
    root = LIB / "Mail"
    files = sorted(root.glob("V*/*/*.mbox/**/Messages/*.emlx")) if root.exists() else []
    with Writer("mail", AVENUE) as w:
        for path in files:
            try:
                data = path.read_bytes()
                n, _, rest = data.partition(b"\n")
                rec = parse(rest[:int(n)] if n.strip().isdigit() else rest)
            except (OSError, ValueError):
                continue
            if "Spam" in rec["_labels"] or "Junk" in str(path) or "Trash" in str(path) or w.has(rec["id"]):
                continue
            rec.pop("_labels")
            rec["meta"]["mailbox"] = path.parts[path.parts.index("Mail") + 3] if "Mail" in path.parts else None
            w.add(kind="email", **rec)


if __name__ == "__main__":
    main()
