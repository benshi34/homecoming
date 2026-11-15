"""macOS Notification Center records, retained before the short-lived database clears them."""

import os
import plistlib
import re
from pathlib import Path

from common import HOME, Writer, notification_apps, notification_db, notification_records


AVENUE = ("Local SQLite: ~/Library/Group Containers/group.com.apple.usernoted/db2/db (macOS 15+, with the older "
          "DARWIN_USER_DIR location before that). Needs Full Disk Access. Notification Center keeps roughly a week, "
          "so Homecoming reads it while it is open. One record per notification; verification codes are replaced.")
FDA_NOTE = "macOS keeps notifications behind Full Disk Access: turn it on for this app, then try again."

CODE_WORD = re.compile(r"\b(?:code|verification|passcode|otp|2fa|security)\b", re.I)
CODE_TOKEN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9]{4,8}(?![A-Za-z0-9])")


def redact_code(text):
    """Replace a short token near a sign-in-code phrase, leaving ordinary numbers alone."""
    if not text or not CODE_WORD.search(text):
        return text
    spans = []
    for token in CODE_TOKEN.finditer(text):
        value = token.group(0)
        if not any(ch.isdigit() for ch in value):
            continue
        if any(abs(token.start() - word.start()) <= 80 for word in CODE_WORD.finditer(text)):
            spans.append(token.span())
    for start, end in reversed(spans):
        text = text[:start] + "[code]" + text[end:]
    return text


def _installed_app_names():
    roots = [Path(os.environ.get("UMP_APPLICATIONS") or "/Applications"), Path("/System/Applications"), HOME / "Applications"]
    names = {}
    seen = set()
    for root in roots:
        if not root.exists():
            continue
        for app in [*root.glob("*.app"), *root.glob("*/*.app")]:
            if app in seen:
                continue
            seen.add(app)
            try:
                info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
            except (OSError, ValueError, plistlib.InvalidFileException):
                continue
            bundle = info.get("CFBundleIdentifier")
            name = info.get("CFBundleDisplayName") or info.get("CFBundleName")
            if bundle and name:
                names[str(bundle).lower()] = str(name)
    return names


def _author(bundle, app_names, known):
    """(who it's from, whether it came from your iPhone). The database keeps bundle ids lowercased; macOS's own
    services are "_system_center_:<id>"."""
    b = (bundle or "").lower()
    if b.startswith("_system_center_:"):
        return "macOS", False
    k = known.get(b) or {}
    name = k.get("name") or app_names.get(b)
    return name or (b.rsplit(".", 1)[-1] if b else "Unknown"), bool(k.get("iphone"))


def main():
    with Writer("notifications", AVENUE) as w:
        db = notification_db()
        if not db.exists():
            return
        rows = notification_records()
        if rows is None:
            w.notes["not_read"] = FDA_NOTE
            return
        app_names, known = _installed_app_names(), notification_apps()
        for row in rows:
            if w.has(row["id"]):
                w.notes["duplicates"] = w.notes.get("duplicates", 0) + 1
                w.skip(row["id"])
                continue
            author, from_iphone = _author(row["bundle"], app_names, known)
            parts = [row["title"], row["subtitle"], row["body"]]
            text = redact_code("\n".join(p for p in parts if p))
            meta = {"bundle": row["bundle"]}
            # How it was delivered: a banner or an alert is put on screen; "none" goes only to Notification Center.
            # (record.presented isn't this: it's 0 on every row of a real database.)
            if row.get("style") is not None:
                meta["style"] = row["style"]
                meta["shown"] = row["style"] in ("banner", "alert")
            if row.get("thread_id") is not None:
                meta["thread_id"] = row["thread_id"]
            if row.get("category_id") is not None:
                meta["category_id"] = row["category_id"]
            if from_iphone:
                meta["from_iphone"] = True
            w.add(id=row["id"], kind="notification", ts=row["when"].isoformat(), author=author,
                  title=redact_code(row["title"]), text=text, meta=meta)


if __name__ == "__main__":
    main()
