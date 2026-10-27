"""Audio Apple left without words, transcribed on this Mac: voice memos it didn't transcribe, audio messages in
Messages, voicemails from the iPhone with no transcript. Off unless asked for (UMP_TRANSCRIBE=1: the app's "Transcribe
audio on this Mac"). Apple's own speech recognition does it (SpeechTranscriber, macOS 26 on, through hear.swift,
compiled here once): nothing leaves the Mac.

Each file is heard in each language you use (UMP_TRANSCRIBE_LANGS, "en-US,zh-CN"; else the Mac's preferred languages)
and the hearing Apple is surest of is kept. What it heard is kept in raw/transcripts.json, by the file's path, size and
time; the readers (voice_memos.py, imessage.py, ileapp.py's voicemail) take their text from there when Apple's own is
missing, the next time they run. A file in which nothing was heard (music, silence) isn't tried again; one that
couldn't be read is, next time. Newest first, for at most UMP_TRANSCRIBE_SECONDS a run (600): the rest wait for the
next. main() returns the sources that have new words, for the app to read again (bridge.py)."""

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from common import CORPUS, HOME, NORM, TRANSCRIPTS, audio_key, read_json, write_atomic

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "hear.swift"
TOOLS = HOME / "Library/Application Support/q1_user_model/tools"
AUDIO = (".caf", ".amr", ".m4a", ".mp3", ".wav", ".aac", ".opus", ".ogg")


def languages():
    if os.environ.get("UMP_TRANSCRIBE_LANGS"):
        return os.environ["UMP_TRANSCRIBE_LANGS"]
    try:  # the Mac's preferred languages, as System Settings lists them ("en-US", "zh-Hans-CN")
        out = subprocess.run(["defaults", "read", "-g", "AppleLanguages"], capture_output=True, text=True, timeout=10).stdout
        langs = [x.strip().strip('",') for x in out.strip("()\n ").splitlines() if x.strip().strip('",')]
    except (OSError, subprocess.SubprocessError):
        langs = []
    return ",".join(dict.fromkeys(langs)) or "en-US"


def hearer():
    """The compiled hear.swift (UMP_HEAR, for the tests): built once a version, here, with the Mac's own swiftc."""
    if os.environ.get("UMP_HEAR"):
        return os.environ["UMP_HEAR"]
    tag = hashlib.sha1(SOURCE.read_bytes()).hexdigest()[:10]
    exe = TOOLS / f"hear-{tag}"
    if not exe.exists():
        TOOLS.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["swiftc", "-O", str(SOURCE), "-o", str(exe)], capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(f"couldn't build the transcriber (needs the Xcode command line tools): {r.stderr.strip()[-300:]}")
    return str(exe)


def records(source):
    p = NORM / f"{source}.jsonl"
    if not p.exists():
        return
    with open(p, encoding="utf-8") as f:
        for line in f:
            try:
                yield json.loads(line)
            except ValueError:
                continue


def wanted():
    """(time, path, source) of each audio file that has no transcript of Apple's."""
    for r in records("voice_memos"):
        m = r.get("meta") or {}
        if not m.get("transcribed") and m.get("path"):
            yield r.get("ts") or "", m["path"], "voice_memos"
    for src in ("imessage", "imessage@phone"):
        for r in records(src):
            m = r.get("meta") or {}
            if m.get("audio") and not m.get("transcribed"):
                for a in m.get("attachments") or []:
                    if isinstance(a, dict) and str(a.get("path") or "").lower().endswith(AUDIO):
                        yield r.get("ts") or "", a["path"], src
    for r in records("phone_voicemail"):
        m = r.get("meta") or {}
        if r.get("kind") == "voicemail" and str(r.get("text") or "").startswith("[voicemail"):
            for f in m.get("files") or []:
                yield r.get("ts") or "", str(f if os.path.isabs(f) else CORPUS / f), "phone_voicemail"


def main():
    if os.environ.get("UMP_TRANSCRIBE") != "1":
        print("[transcribe] off (UMP_TRANSCRIBE=1, or Transcribe audio on this Mac in the app)")
        return []
    if sys.platform != "darwin":
        print("[transcribe] needs a Mac (Apple's on-device speech recognition)")
        return []
    done = read_json(TRANSCRIPTS, {}) or {}
    todo, seen = [], set()
    for ts, path, source in sorted(wanted(), reverse=True):
        k = audio_key(path)
        if not k or k in seen or (k in done and "text" in done[k]):
            continue
        seen.add(k)
        todo.append((k, os.path.expanduser(path), source))
    if not todo:
        print(f"[transcribe] nothing new to hear ({len(done)} heard before)")
        return []
    keys = {p: (k, src) for k, p, src in todo}
    budget = float(os.environ.get("UMP_TRANSCRIBE_SECONDS") or 600)
    t, n, empty, failed, worded = time.time(), 0, 0, 0, set()
    p = subprocess.Popen([hearer(), languages()], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    p.stdin.write("".join(path + "\n" for _, path, _ in todo))
    p.stdin.close()
    for line in p.stdout:
        try:
            got = json.loads(line)
        except ValueError:
            continue
        k, src = keys.get(got.get("path"), (None, None))
        if not k:
            continue
        if got.get("error"):
            failed += 1
            done[k] = {"error": str(got["error"])[:300]}
        else:
            n += 1
            empty += not got.get("text")
            if got.get("text"):
                worded.add(src)
            done[k] = {"text": got.get("text") or "", "locale": got.get("locale"), "confidence": got.get("confidence"),
                       "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        if (n + failed) % 25 == 0:
            write_atomic(TRANSCRIPTS, json.dumps(done))  # a long run cut short keeps what it heard
        if time.time() - t > budget:
            p.kill()  # the rest next run
            break
    p.wait()
    write_atomic(TRANSCRIPTS, json.dumps(done))
    print(f"[transcribe] heard {n} of {len(todo)} ({empty} with no speech, {failed} unreadable) in {time.time() - t:.0f}s; "
          f"{'the rest next run; ' if n + failed < len(todo) else ''}their readers take the text next time they run")
    return sorted(worded)


if __name__ == "__main__":
    main()
