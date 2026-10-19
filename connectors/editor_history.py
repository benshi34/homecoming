"""Files you edited in VS Code, Cursor and other VS Code-family editors, and when: the editor's local history
keeps a copy each time a file is saved. Only the file and the time are kept, not the file's contents (the
code itself is in Documents and in git)."""

import json
from urllib.parse import unquote, urlparse

from common import LIB, Writer, from_unix
from ai_coding import VSCODE_FAMILY

AVENUE = ("Local JSON: ~/Library/Application Support/<Code|Cursor|VSCodium|Windsurf>/User/History/<id>/entries.json "
          "= {resource: file URI, entries: [{id, timestamp ms, source?}]}, one entry per saved version.")


def main():
    with Writer("editor_history", AVENUE) as w:
        for editor, folder in VSCODE_FAMILY.items():
            for f in sorted((LIB / "Application Support" / folder / "User/History").glob("*/entries.json")):
                try:
                    d = json.loads(f.read_text())
                except (ValueError, OSError):
                    continue
                if not isinstance(d, dict):  # not a history of a file
                    continue
                resource = d.get("resource") if isinstance(d.get("resource"), str) else ""
                uri = urlparse(resource)
                path = unquote(uri.path) if uri.scheme in ("file", "vscode-remote", "") else resource
                name = path.rsplit("/", 1)[-1] if path else None
                for e in d.get("entries") if isinstance(d.get("entries"), list) else []:
                    when = e.get("timestamp") if isinstance(e, dict) else None
                    try:
                        ts = from_unix(float(when), "ms") if when else None
                    except (TypeError, ValueError):  # a time that isn't one
                        ts = None
                    rid = f"{editor}:{f.parent.name}:{e.get('id') if isinstance(e, dict) else None}"
                    if not ts or w.has(rid):  # and a version listed twice is one
                        continue
                    w.add(id=rid, kind="file_edit", ts=ts,
                          author="me", is_me=True, title=name, thread=path, thread_name=name, text=f"Edited {path}",
                          meta={"editor": editor, "path": path, "how": e.get("source")})


if __name__ == "__main__":
    main()
