"""RFC 822 email -> normalized record fields. Shared by Mail.app (.emlx) and Takeout (.mbox)."""

import csv
import datetime as dt
import email
import email.message
import email.policy
import email.utils
import hashlib
import html
import re
from xml.etree import ElementTree

from identity import is_me_email

# Mail folders, by name (Mail.app's own and a mailbox export's): mail in these is the user's own...
SENT_FOLDERS = {"sent", "sent items", "sent messages", "sent mail"}
# ...and mail in these is kept, but tagged meta.tier so searches can leave it out: junk can hide real mail, and
# deleted mail is mail the user received or wrote.
SKIP_FOLDERS = {"junk", "junk email", "spam", "trash", "deleted items", "deleted messages", "outbox"}
TIER_OF_FOLDER = {"junk": "spam", "junk email": "spam", "spam": "spam", "trash": "deleted", "deleted items": "deleted",
                  "deleted messages": "deleted", "outbox": "unsent"}

# Gmail's own labels (X-Gmail-Labels) that say a mail is yours, in the bin or spam. A Takeout writes them in the
# account's language, as Gmail shows them ("Messages envoyés"): English (Bin in British English), German, Spanish,
# French, Italian, Portuguese, Dutch, Japanese.
SENT_LABELS = {"Sent", "Gesendet", "Enviados", "Messages envoyés", "Posta inviata", "E-mails enviados", "Verzonden", "送信済みメール"}
TRASH_LABELS = {"Trash", "Bin", "Papierkorb", "Papelera", "Corbeille", "Cestino", "Lixeira", "Lixo", "Prullenbak", "ゴミ箱"}
SPAM_LABELS = {"Spam", "迷惑メール"}

QUOTE_START = re.compile(r"^(On .{5,200} wrote:|-----Original Message-----|From: .+\nSent: |_{20,})", re.M)


def html_to_text(s):
    s = re.sub(r"(?is)<(script|style|head).*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"[ \t\xa0]+", " ", re.sub(r"\n\s*\n+", "\n\n", s)).strip()


def decode(b):
    """Bytes of text whose charset isn't known (or is wrong): UTF-8, else Windows' Latin-1, as most such mail is."""
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("cp1252", "replace")


def body_text(msg):
    try:
        part = msg.get_body(preferencelist=("plain", "html"))
        if part is None:
            return ""
    except (KeyError, LookupError, ValueError, AssertionError):
        part = msg
    try:
        text = part.get_content()
        if part.get_content_charset() in (None, "us-ascii") and "\ufffd" in text:
            # 8-bit text that never said its charset (old mail, Windows' mostly): read as ASCII, each é was lost
            payload = part.get_payload(decode=True)
            text = decode(payload) if isinstance(payload, bytes) else text
    except (KeyError, LookupError, ValueError, AssertionError):  # a charset Python doesn't know: the part's own bytes
        payload = part.get_payload(decode=True) or b""
        text = decode(payload) if isinstance(payload, bytes) else str(payload)
    if part.get_content_type() == "text/html":
        text = html_to_text(text)
    m = QUOTE_START.search(text)
    if m and m.start() > 0:
        text = text[:m.start()]
    text = "\n".join(l for l in text.splitlines() if not l.startswith(">"))
    return text.strip()[:30_000]


def forwarded(msg):
    """A mail forwarded as an attachment (message/rfc822, what Outlook and Mail's "Forward as Attachment" send): who
    wrote it, its subject and its words, which are in no other part. Not a bounce's copy of the mail that bounced."""
    if msg.get_content_type() == "multipart/report":
        return ""
    for p in msg.walk() if msg.is_multipart() else ():
        if p.get_content_type() != "message/rfc822":
            continue
        try:
            inner = p.get_content()
            head = [f"Forwarded: {inner.get('From') or ''} {inner.get('Subject') or ''}".strip()]
            return "\n".join([*head, body_text(inner)]).strip()
        except (KeyError, LookupError, ValueError, AssertionError, AttributeError, TypeError, IndexError):
            continue
    return ""


def olm_message(raw):
    """A message in an Outlook for Mac archive (.olm, a zip): an XML file of its own (<emails><email>...), as RFC 822
    bytes for parse(): who it's from and to, its subject, its time (written without a zone, taken as UTC), its body
    (HTML, or plain text) and its attachments' names."""
    root = ElementTree.fromstring(raw)
    m = root if root.tag == "email" else root.find("email")
    if m is None:
        raise ValueError("no <email> in it")
    one = lambda s: re.sub(r"[\r\n]+", " ", s or "").strip()  # noqa: E731 - a header is one line

    def people(tag):
        return ", ".join(email.utils.formataddr((one(a.get("OPFContactEmailAddressName")), one(a.get("OPFContactEmailAddressAddress"))))
                         for a in m.iterfind(f"{tag}/emailAddress") if a.get("OPFContactEmailAddressAddress"))
    msg = email.message.EmailMessage()
    for header, tag in (("From", "OPFMessageCopyFromAddresses"), ("To", "OPFMessageCopyToAddresses"),
                        ("Cc", "OPFMessageCopyCCAddresses"), ("Message-ID", "OPFMessageCopyMessageID"),
                        ("Subject", "OPFMessageCopySubject")):
        v = people(tag) if tag.endswith("Addresses") else one(m.findtext(tag))
        if v:
            msg[header] = v
    if "From" not in msg and people("OPFMessageCopySenderAddress"):
        msg["From"] = people("OPFMessageCopySenderAddress")
    try:
        when = dt.datetime.fromisoformat(one(m.findtext("OPFMessageCopySentTime") or m.findtext("OPFMessageCopyReceivedTime")))
        msg["Date"] = email.utils.format_datetime(when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc))
    except ValueError:
        pass
    body, plain = m.findtext("OPFMessageCopyHTMLBody") or "", m.findtext("OPFMessageCopyBody") or ""
    html_body = body or (plain if re.search(r"<(html|body|div|p|br)\b", plain, re.I) else "")
    msg.set_content(html_body or plain, subtype="html" if html_body else "plain")
    for a in m.iterfind("OPFMessageCopyAttachmentList/messageAttachment"):
        kind = (a.get("OPFAttachmentContentType") or "application/octet-stream").split("/", 1)
        msg.add_attachment(b"", maintype=kind[0], subtype=kind[1] if len(kind) > 1 else "octet-stream",
                           filename=one(a.get("OPFAttachmentName")) or "attachment")
    return msg.as_bytes()


def gmail_labels(s):
    """X-Gmail-Labels as a list: names separated by commas, one with a comma in it in quotes."""
    return [x.strip() for x in next(csv.reader([s], skipinitialspace=True), []) if x.strip()] if s else []


def eight_bit_headers(raw):
    """Headers written in raw 8-bit, not encoded (old mail): Python reads them as UTF-8, so headers that aren't are
    turned from Windows' Latin-1 into UTF-8 first. The body is left as it is."""
    probe = raw[:1 << 20]  # the headers end well before (a body's attachment can be MBs)
    end = min((i for i in (probe.find(b"\r\n\r\n"), probe.find(b"\n\n")) if i >= 0), default=len(probe))
    head = raw[:end]
    if head.isascii():
        return raw
    try:
        head.decode("utf-8")
        return raw
    except UnicodeDecodeError:
        return head.decode("cp1252", "replace").encode("utf-8") + raw[end:]


def mail_time(msg):
    """When a mail was sent, in UTC: its Date, else when it arrived (the first Received line). A Date at -0000 is UTC
    (RFC 5322); one with no zone at all stays as written."""
    def when(v):
        try:
            date = email.utils.parsedate_to_datetime(str(v).strip())
        except (TypeError, ValueError, IndexError):
            return None
        if not date.tzinfo and "-0000" in str(v):
            date = date.replace(tzinfo=dt.timezone.utc)
        return date.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z") if date.tzinfo else date.isoformat()
    ts = when(msg.get("Date"))
    if ts:
        return ts
    received = next((str(r) for r in msg.get_all("Received") or [] if ";" in str(r)), None)
    return when(received.rsplit(";", 1)[-1]) if received else None


def parse(raw):
    """bytes -> dict of record fields (id, ts, author, is_me, participants, title, text, thread, meta)."""
    msg = email.message_from_bytes(eight_bit_headers(raw), policy=email.policy.default)
    try:
        frm = email.utils.getaddresses([str(msg.get("From", ""))])
        to = email.utils.getaddresses([str(msg.get("To", "")), str(msg.get("Cc", ""))])
    except (TypeError, ValueError, IndexError):
        frm, to = [], []
    sender_name, sender = (frm[0] if frm else ("", ""))
    ts = mail_time(msg)
    subject = str(msg.get("Subject", "") or "").strip()
    labels = str(msg.get("X-Gmail-Labels", "") or "")
    mid = str(msg.get("Message-ID", "") or "").strip() or hashlib.sha1(raw[:4096]).hexdigest()
    thread = str(msg.get("X-GM-THRID", "") or "") or re.sub(r"^(re|fwd?|aw):\s*", "", subject, flags=re.I).lower()
    me = is_me_email(sender) or bool(SENT_LABELS & set(gmail_labels(labels)))
    to = [(n, a) for n, a in to if a]
    people = [n or a for n, a in to]
    return {
        "id": mid, "ts": ts, "author": "me" if me else (sender_name or sender), "is_me": me,
        "participants": people[:30] or None, "title": subject, "thread": thread, "thread_name": subject,
        "text": "\n".join(x for x in (subject, body_text(msg), forwarded(msg)) if x)[:40_000],
        "meta": {k: v for k, v in (("from", sender), ("to", [a for _, a in to][:30]), ("labels", labels or None),
                                    ("attachments", [p.get_filename() for p in msg.iter_attachments() if p.get_filename()][:20]
                                     if msg.is_multipart() else None)) if v},
        "_labels": labels,
    }


# The line an mbox starts each message with: "From ", who or what sent it, and when, as mbox writers put it (Takeout:
# "From 1788000000000000001@xxx Sat Jan 13 18:57:09 +0000 2024"; Mail.app: "From a@b.com Mon Jan  1 00:00:00 2024").
SEPARATOR = re.compile(rb"From \S*\s+(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*,?\s+(?:\d{1,2}\s+)?"
                       rb"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+(?:\d{1,4}\s+)?\d{1,2}:\d{2}")
# The headers a message starts with, for a separator dated some other way.
FIRST_HEADER = re.compile(rb"(?:Received|Return-Path|Delivered-To|Message-ID|MIME-Version|Date|From|X-[\w-]+):", re.I)
QUOTED_FROM = re.compile(rb">+From ")


def iter_mbox(fobj):
    """Stream messages (bytes) out of an mbox file object opened in binary mode. A body's own "From " lines aren't
    always quoted (">From "): only one like a separator starts a message, or one after a blank line that headers
    follow."""
    buf, pending, blank = None, None, True
    for line in fobj:
        if pending is not None:  # an undated "From " line after a blank one: a separator if headers follow it
            if FIRST_HEADER.match(line):
                if buf:
                    yield b"".join(buf)
                buf = []
            else:
                buf.append(pending)
            pending = None
        if line.startswith(b"From "):
            if buf is None or SEPARATOR.match(line):
                if buf:
                    yield b"".join(buf)
                buf, blank = [], False
                continue
            if blank:
                pending = line
                continue
        if buf is not None:
            buf.append(line[1:] if line.startswith(b">") and QUOTED_FROM.match(line) else line)
        blank = line.isspace()
    if pending is not None:
        buf.append(pending)
    if buf:
        yield b"".join(buf)
