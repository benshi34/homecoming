"""Voice Memos: recording metadata plus the on-device transcript Apple embeds in each .m4a
(iOS/macOS 18+, stored in a 'tsrp' atom as JSON). Recordings without a transcript are listed
so they can be transcribed later (e.g. local Whisper)."""

import json
import re

from common import LIB, Writer, connect, from_apple, heard, select, snapshot_sqlite, tables

ROOT = LIB / "Group Containers/group.com.apple.VoiceMemos.shared/Recordings"
AVENUE = ("Local: ~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/CloudRecordings.db "
          "+ *.m4a (appears only after opening Voice Memos on the Mac with iCloud > Voice Memos enabled). "
          "Needs Full Disk Access. Transcript = JSON in the m4a's 'tsrp' atom. One in Recently Deleted (ZEVICTIONDATE "
          "set) is kept with meta.tier = \"deleted\". Not yet verified on this Mac (no recordings synced).")


def embedded_transcript(path):
    try:
        data = path.read_bytes()
    except OSError:
        return None
    i = data.find(b"tsrp")
    if i < 4:
        return None
    size = int.from_bytes(data[i - 4:i], "big")
    blob = data[i + 4:i - 4 + size] if size > 8 else data[i + 4:]
    try:
        doc = json.loads(blob.decode("utf-8", "ignore"))
        runs = doc.get("attributedString", {}).get("runs", [])
        return re.sub(r"\s+", " ", "".join(x for x in runs if isinstance(x, str))).strip() or None
    except (ValueError, AttributeError):
        return None


def main():
    db = ROOT / "CloudRecordings.db"
    with Writer("voice_memos", AVENUE) as w:
        if not db.exists():
            return
        con = connect(snapshot_sqlite(db, "voice_memos/CloudRecordings.db"))  # the app holds it locked while open
        if "ZCLOUDRECORDING" not in tables(con):  # made, never written to
            w.notes["empty"] = 1
            return
        # Each column but the row's own only if this version has it: the title in ZENCRYPTEDTITLE (newer) or ZCUSTOMLABEL,
        # and ZEVICTIONDATE, set when one is put in Recently Deleted.
        for r in con.execute(select(con, "ZCLOUDRECORDING", ("Z_PK", "ZUNIQUEID", "ZDATE", "ZDURATION", "ZPATH", "ZENCRYPTEDTITLE",
                                                             "ZCUSTOMLABEL", "ZEVICTIONDATE"))):
            title = r["ZENCRYPTEDTITLE"] or r["ZCUSTOMLABEL"]
            path = ROOT / (r["ZPATH"] or "")
            transcript = embedded_transcript(path) if r["ZPATH"] else None
            here = None if transcript or not r["ZPATH"] else heard(path)  # transcribe.py's, when Apple made none
            transcript = transcript or here
            deleted = bool(r["ZEVICTIONDATE"])
            w.add(id=r["ZUNIQUEID"] or r["Z_PK"], kind="voice_memo", ts=from_apple(r["ZDATE"]), author="me", is_me=True,
                  title=title, text="\n".join(x for x in (title, transcript) if x),
                  meta={"seconds": round(r["ZDURATION"] or 0), "path": str(path), "transcribed": bool(transcript),
                        **({"transcribed_on": "this Mac"} if here else {}),
                        **({"deleted": True, "tier": "deleted", "deleted_at": from_apple(r["ZEVICTIONDATE"])} if deleted else {})})


if __name__ == "__main__":
    main()
