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
                uri = urlparse(d.get("resource") or "")
                path = unquote(uri.path) if uri.scheme in ("file", "vscode-remote", "") else d.get("resource")
                name = path.rsplit("/", 1)[-1] if path else None
                for e in d.get("entries") or []:
                    if not e.get("timestamp"):
                        continue
                    w.add(id=f"{editor}:{f.parent.name}:{e.get('id')}", kind="file_edit", ts=from_unix(e["timestamp"], "ms"),
                          author="me", is_me=True, title=name, thread=path, thread_name=name, text=f"Edited {path}",
                          meta={"editor": editor, "path": path, "how": e.get("source")})


if __name__ == "__main__":
    main()
