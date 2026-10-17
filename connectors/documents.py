"""Personal documents on disk and in iCloud Drive: text from PDFs, Word/RTF, PowerPoint,
Pages/Keynote, notebooks, Markdown/TeX/text; metadata-only records for creative projects
(Ableton, GarageBand, MuseScore, Logic). Skips code dependencies, datasets and build output."""

import json
import os
import re
import subprocess
import zipfile
from pathlib import Path

from apple_notes import _fields, _varint
from common import HOME, NORM, ROOT, Writer, cloud_only, from_unix

AVENUE = ("Filesystem walk of ~/Documents, ~/Desktop, ~/Downloads and ~/Library/Mobile Documents (iCloud Drive "
          "+ app containers like com~apple~Pages). Text: pypdf for PDF, macOS textutil for doc/docx/rtf/odt, "
          "zip+XML for pptx, IWA (snappy+protobuf) string walk for Pages/Keynote/Numbers, cell text for ipynb. "
          "Heuristics drop dependencies, datasets (>5 .txt per folder), exports and build output. "
          "iCloud files that are only in iCloud (Optimize Mac Storage: .icloud placeholders before macOS 14, files "
          "flagged dataless since) are listed but not read, so nothing is downloaded; one read before keeps what was "
          "read.")

ROOTS = {"Documents": HOME / "Documents", "Desktop": HOME / "Desktop", "Downloads": HOME / "Downloads",
         "iCloud": HOME / "Library/Mobile Documents"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "env", "__pycache__", "site-packages", ".ipynb_checkpoints",
             "Library", ".Trash", "build", "dist", ".next", ".cache", "target", "DerivedData", "Pods", "_site",
             "Backup", "Samples", "Ableton Project Info", "imessage_export_mac", "babi_tasks", "LlamaFactory",
             "SWE-agent", "eval_output", "experiment_output", "train_output", "vendor", "third_party"}
TEXT_EXT = {".pdf", ".docx", ".doc", ".rtf", ".odt", ".pptx", ".pages", ".key", ".numbers", ".ipynb", ".md",
            ".markdown", ".tex", ".txt", ".org", ".rst"}
CREATIVE_EXT = {".als": "Ableton Live set", ".band": "GarageBand project", ".mscz": "MuseScore score",
                ".mscx": "MuseScore score", ".logicx": "Logic project", ".ptx": "Pro Tools session",
                ".flp": "FL Studio project", ".epub": "e-book"}
BOILERPLATE = re.compile(r"^(readme|license|licence|changelog|contributing|code_of_conduct|security|authors|notice|history)",
                         re.I)
MAX_BYTES = 60 * 2**20
MAX_CHARS = 200_000


def snappy(data):
    """Raw snappy decompression (no framing)."""
    n, pos = _varint(data, 0)
    out = bytearray()
    while pos < len(data) and len(out) < n:
        tag = data[pos]
        pos += 1
        kind = tag & 3
        if kind == 0:
            ln = tag >> 2
            if ln >= 60:
                nb = ln - 59
                ln = int.from_bytes(data[pos:pos + nb], "little")
                pos += nb
            ln += 1
            out += data[pos:pos + ln]
            pos += ln
            continue
        if kind == 1:
            ln, off = ((tag >> 2) & 7) + 4, ((tag >> 5) << 8) | data[pos]
            pos += 1
        elif kind == 2:
            ln, off = (tag >> 2) + 1, int.from_bytes(data[pos:pos + 2], "little")
            pos += 2
        else:
            ln, off = (tag >> 2) + 1, int.from_bytes(data[pos:pos + 4], "little")
            pos += 4
        for _ in range(ln):
            out.append(out[-off])
    return bytes(out)


def _iwa_strings(buf, depth=0, out=None):
    out = [] if out is None else out
    try:
        for _, wt, v in _fields(buf):
            if wt != 2 or not v:
                continue
            try:
                s = v.decode("utf-8")
                if len(s) >= 3 and sum(c.isprintable() or c in "\n  \t" for c in s) / len(s) > 0.97 \
                        and (" " in s or len(s) > 20):
                    out.append(s)
                    continue
            except UnicodeDecodeError:
                pass
            if depth < 4:
                _iwa_strings(v, depth + 1, out)
    except (IndexError, ValueError):
        pass
    return out


def iwork_text(path):
    """Best-effort body text of a Pages/Keynote/Numbers file (zip of .iwa protobuf streams)."""
    texts = []
    with zipfile.ZipFile(path) as z:
        for name in sorted(n for n in z.namelist() if n.endswith(".iwa") and "Stylesheet" not in n
                           and "Metadata" not in n and "ViewState" not in n):
            raw, pos, data = z.read(name), 0, bytearray()
            while pos + 4 <= len(raw):
                ln = int.from_bytes(raw[pos + 1:pos + 4], "little")
                data += snappy(raw[pos + 4:pos + 4 + ln])
                pos += 4 + ln
            pos = 0
            while pos < len(data):
                n, pos = _varint(data, pos)
                info, pos = bytes(data[pos:pos + n]), pos + n
                for f, wt, mi in _fields(info):
                    if f == 2 and wt == 2:
                        length = next((v for ff, wtt, v in _fields(mi) if ff == 3 and wtt == 0), 0)
                        texts += _iwa_strings(bytes(data[pos:pos + length]))
                        pos += length
    return "\n".join(t.replace(" ", "\n") for t in dict.fromkeys(texts))


def pdf_text(path):
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    parts = []
    for page in reader.pages[:60]:
        parts.append(page.extract_text() or "")
        if sum(map(len, parts)) > MAX_CHARS:
            break
    return "\n".join(parts)


def pptx_text(path):
    with zipfile.ZipFile(path) as z:
        slides = sorted((n for n in z.namelist() if re.match(r"ppt/(slides|notesSlides)/\w+\.xml$", n)),
                        key=lambda n: (n.split("/")[1], int(re.sub(r"\D", "", n) or 0)))
        return "\n".join(" ".join(re.findall(r"<a:t(?:\s[^>]*)?>([^<]*)</a:t>", z.read(n).decode("utf-8", "ignore"))) for n in slides)


def ipynb_text(path):
    nb = json.loads(path.read_text(errors="ignore"))
    cells = nb.get("cells") or []
    return "\n\n".join("".join(c.get("source", [])) for c in cells if c.get("cell_type") in ("markdown", "code"))


def extract(path, ext):
    if ext == ".pdf":
        return pdf_text(path)
    if ext in (".docx", ".doc", ".rtf", ".odt"):
        return subprocess.run(["textutil", "-convert", "txt", "-stdout", str(path)], capture_output=True,
                              text=True, timeout=60).stdout
    if ext == ".pptx":
        return pptx_text(path)
    if ext in (".pages", ".key", ".numbers"):
        return iwork_text(path)
    if ext == ".ipynb":
        return ipynb_text(path)
    return path.read_text(errors="ignore")


def walk(root):
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith(".")
                  and not d.endswith((".app", ".photoslibrary", ".framework", ".bundle", ".xcodeproj", ".logicx"))
                  and not (Path(dp, d) == ROOT / "corpus")]
        if "package.json" in fns and len(Path(dp).relative_to(root).parts) > 1:
            dns[:] = []  # a JavaScript package: skip its docs and dependencies
            continue
        txt_count = sum(f.lower().endswith(".txt") for f in fns)
        for f in fns:
            yield Path(dp, f), txt_count
        for d in list(dns):  # .logicx / package-style projects appear as directories
            if d.endswith(".logicx"):
                yield Path(dp, d), 0


def main():
    # Files an earlier run read: one now only in iCloud keeps that record rather than becoming a name.
    try:
        before = {json.loads(line).get("id") for line in (NORM / "documents.jsonl").open()}
    except (OSError, ValueError):
        before = set()
    with Writer("documents", AVENUE) as w:
        for label, root in ROOTS.items():
            for path, txt_count in walk(root):
                name = path.name
                if name.endswith(".icloud"):  # not downloaded: ".Name.ext.icloud"
                    real = name[1:-len(".icloud")] if name.startswith(".") else name[:-len(".icloud")]
                    ext = os.path.splitext(real)[1].lower()
                    if ext in TEXT_EXT or ext in CREATIVE_EXT:
                        st = path.stat()
                        w.add(id=str(path), kind="document", ts=from_unix(st.st_mtime), author="me", title=real,
                              text=f"{real} (in iCloud, not downloaded)", thread=label, thread_name=str(path.parent),
                              meta={"root": label, "path": str(path.parent / real), "downloaded": False})
                    continue
                ext = path.suffix.lower()
                try:
                    st = path.stat()  # only the file's details: this doesn't download it
                except OSError:
                    continue
                if cloud_only(path):  # reading it would download it: its name and dates only
                    if (ext in TEXT_EXT or ext in CREATIVE_EXT) and str(path) not in before:
                        w.add(id=str(path), kind="document", ts=from_unix(st.st_mtime), author="me", title=name,
                              text=f"{name} (in iCloud, not downloaded)", thread=label, thread_name=str(path.parent),
                              meta={"root": label, "path": str(path), "downloaded": False, "bytes": st.st_size})
                    w.notes["in_icloud_only"] = w.notes.get("in_icloud_only", 0) + 1
                    continue
                if ext in CREATIVE_EXT:
                    w.add(id=str(path), kind="document", ts=from_unix(st.st_mtime), author="me", is_me=True,
                          title=path.stem, text=f"{CREATIVE_EXT[ext]}: {path.stem}\nFolder: {path.parent.name}",
                          thread=label, thread_name=str(path.parent),
                          meta={"root": label, "path": str(path), "type": CREATIVE_EXT[ext], "bytes": st.st_size,
                                "created": from_unix(getattr(st, "st_birthtime", 0))})
                    continue
                if ext not in TEXT_EXT or st.st_size > MAX_BYTES or st.st_size == 0:
                    continue
                if ext == ".txt" and (txt_count > 5 or st.st_size > 2**20):
                    continue
                if ext in (".md", ".markdown", ".txt", ".rst") and BOILERPLATE.match(name) and label != "Documents":
                    continue
                try:
                    text = extract(path, ext) or ""
                except Exception as e:  # unreadable / encrypted / malformed file: keep metadata only
                    text, err = "", type(e).__name__
                else:
                    err = None
                text = re.sub(r"[ \t]+", " ", text).strip()[:MAX_CHARS]
                w.add(id=str(path), kind="document", ts=from_unix(st.st_mtime), author="me", title=name,
                      text=text or name, thread=label, thread_name=str(path.parent),
                      meta={k: v for k, v in (("root", label), ("path", str(path)), ("ext", ext), ("bytes", st.st_size),
                                              ("created", from_unix(getattr(st, "st_birthtime", 0))),
                                              ("error", err), ("chars", len(text))) if v})


if __name__ == "__main__":
    main()
