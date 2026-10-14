"""Voice Memos: recording metadata plus the on-device transcript Apple embeds in each .m4a
(iOS/macOS 18+, stored in a 'tsrp' atom as JSON). Recordings without a transcript are listed
so they can be transcribed later (e.g. local Whisper)."""

import json
import re

from common import LIB, Writer, connect, from_apple, snapshot_sqlite

ROOT = LIB / "Group Containers/group.com.apple.VoiceMemos.shared/Recordings"
AVENUE = ("Local: ~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/CloudRecordings.db "
          "+ *.m4a (appears only after opening Voice Memos on the Mac with iCloud > Voice Memos enabled). "
          "Needs Full Disk Access. Transcript = JSON in the m4a's 'tsrp' atom. Not yet verified on this Mac "
          "(no recordings synced).")


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
        con = connect(snapshot_sqlite(db, "voice_memos/CloudRecordings.db"))
        cols = {r[1] for r in con.execute("pragma table_info(ZCLOUDRECORDING)")}
        title = "coalesce(ZENCRYPTEDTITLE, ZCUSTOMLABEL)" if "ZENCRYPTEDTITLE" in cols else "ZCUSTOMLABEL"
        for r in con.execute(f"select Z_PK, ZUNIQUEID, ZDATE, ZDURATION, ZPATH, {title} title from ZCLOUDRECORDING"):
            path = ROOT / (r["ZPATH"] or "")
            transcript = embedded_transcript(path) if r["ZPATH"] else None
            w.add(id=r["ZUNIQUEID"] or r["Z_PK"], kind="voice_memo", ts=from_apple(r["ZDATE"]), author="me", is_me=True,
                  title=r["title"], text="\n".join(x for x in (r["title"], transcript) if x),
                  meta={"seconds": round(r["ZDURATION"] or 0), "path": str(path), "transcribed": bool(transcript)})


if __name__ == "__main__":
    main()
