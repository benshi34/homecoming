"""RFC 822 email -> normalized record fields. Shared by Mail.app (.emlx) and Takeout (.mbox)."""

import datetime as dt
import email
import email.policy
import email.utils
import hashlib
import html
import re

from identity import is_me_email

# Mail folders, by name (Mail.app's own and a mailbox export's): mail in these is the user's own...
SENT_FOLDERS = {"sent", "sent items", "sent messages", "sent mail"}
# ...and mail in these is kept, but tagged meta.tier so searches can leave it out: junk can hide real mail, and
# deleted mail is mail the user received or wrote.
SKIP_FOLDERS = {"junk", "junk email", "spam", "trash", "deleted items", "deleted messages", "outbox"}
TIER_OF_FOLDER = {"junk": "spam", "junk email": "spam", "spam": "spam", "trash": "deleted", "deleted items": "deleted",
                  "deleted messages": "deleted", "outbox": "unsent"}

QUOTE_START = re.compile(r"^(On .{5,200} wrote:|-----Original Message-----|From: .+\nSent: |_{20,})", re.M)


def html_to_text(s):
    s = re.sub(r"(?is)<(script|style|head).*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"[ \t\xa0]+", " ", re.sub(r"\n\s*\n+", "\n\n", s)).strip()


def body_text(msg):
    try:
        part = msg.get_body(preferencelist=("plain", "html"))
        if part is None:
            return ""
        text = part.get_content()
        if part.get_content_type() == "text/html":
            text = html_to_text(text)
    except (KeyError, LookupError, ValueError, AssertionError):
        payload = msg.get_payload(decode=True) or b""
        text = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else str(payload)
    m = QUOTE_START.search(text)
    if m and m.start() > 0:
        text = text[:m.start()]
    text = "\n".join(l for l in text.splitlines() if not l.startswith(">"))
    return text.strip()[:30_000]


def parse(raw):
    """bytes -> dict of record fields (id, ts, author, is_me, participants, title, text, thread, meta)."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    try:
        frm = email.utils.getaddresses([str(msg.get("From", ""))])
        to = email.utils.getaddresses([str(msg.get("To", "")), str(msg.get("Cc", ""))])
    except (TypeError, ValueError, IndexError):
        frm, to = [], []
    sender_name, sender = (frm[0] if frm else ("", ""))
    try:
        date = email.utils.parsedate_to_datetime(str(msg.get("Date")))
        ts = date.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z") if date.tzinfo else date.isoformat()
    except (TypeError, ValueError, IndexError):
        ts = None
    subject = str(msg.get("Subject", "") or "").strip()
    labels = str(msg.get("X-Gmail-Labels", "") or "")
    mid = str(msg.get("Message-ID", "") or "").strip() or hashlib.sha1(raw[:4096]).hexdigest()
    thread = str(msg.get("X-GM-THRID", "") or "") or re.sub(r"^(re|fwd?|aw):\s*", "", subject, flags=re.I).lower()
    me = is_me_email(sender) or "Sent" in labels.split(",")
    people = [n or a for n, a in to if a]
    return {
        "id": mid, "ts": ts, "author": "me" if me else (sender_name or sender), "is_me": me,
        "participants": people[:30] or None, "title": subject, "thread": thread, "thread_name": subject,
        "text": "\n".join(x for x in (subject, body_text(msg)) if x),
        "meta": {k: v for k, v in (("from", sender), ("to", [a for _, a in to][:30]), ("labels", labels or None),
                                    ("attachments", [p.get_filename() for p in msg.iter_attachments() if p.get_filename()][:20]
                                     if msg.is_multipart() else None)) if v},
        "_labels": labels,
    }


def iter_mbox(fobj):
    """Stream messages (bytes) out of an mbox file object opened in binary mode."""
    buf = None
    for line in fobj:
        if line.startswith(b"From "):
            if buf:
                yield b"".join(buf)
            buf = []
            continue
        if buf is not None:
            buf.append(line[1:] if line.startswith(b">From ") else line)
    if buf:
        yield b"".join(buf)
