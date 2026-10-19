"""Notion pages from the desktop app's local cache (only pages opened on this device)."""

import json

from common import LIB, Writer, columns, connect, from_unix, select, snapshot_sqlite, tables

AVENUE = ("Local SQLite cache of the Notion desktop app: ~/Library/Application Support/Notion/notion.db "
          "(block table: properties.title rich text, content = ordered child ids). Partial: only pages "
          "this device has opened. Full coverage: Notion Settings > Export all workspace content "
          "(Markdown & CSV), or the Notion API with an integration token.")

PAGE_TYPES = {"page", "collection_view_page", "personal_home_page"}
PREFIX = {"bulleted_list": "- ", "numbered_list": "1. ", "to_do": "[ ] ", "header": "# ", "sub_header": "## ",
          "sub_sub_header": "### ", "header_4": "#### ", "quote": "> ", "callout": "> ", "code": "    "}


def rich(value):
    """Notion rich text [[text, annotations], ...] -> plain string."""
    if not isinstance(value, list):
        return ""
    return "".join(seg[0] for seg in value if isinstance(seg, list) and seg and isinstance(seg[0], str)).replace("‣", "")


def loads(v, empty):
    """A JSON column as the type it should be ({} or []): one that's null, cut off or of another shape is empty."""
    try:
        x = json.loads(v) if v else empty
    except (ValueError, TypeError):
        return empty
    return x if isinstance(x, type(empty)) else empty


def main():
    db = snapshot_sqlite(LIB / "Application Support/Notion/notion.db", "notion/notion.db")
    with Writer("notion", AVENUE) as w:
        if not db.exists():
            return
        con = connect(db)
        if "block" not in tables(con):  # made, never written to
            w.notes["empty"] = 1
            return
        read(con, w)


def read(con, w):
    blocks = {}
    alive = "alive" in columns(con, "block")  # a version without the column: every block is
    # Each column but the block's id only if this version of the app has it.
    for r in con.execute(select(con, "block", ("id", "type", "properties", "content", "parent_id", "parent_table", "alive",
                                               "created_time", "last_edited_time"))):
        b = dict(r)
        b["properties"] = loads(b["properties"], {})
        b["content"] = [c for c in loads(b["content"], []) if isinstance(c, str)]
        b["alive"] = b["alive"] if alive else True
        blocks[b["id"]] = b

    def render(bid, depth=0, seen=None):
        seen = seen if seen is not None else set()
        b = blocks.get(bid)
        if not b or bid in seen or not b["alive"]:
            return []
        seen.add(bid)
        lines = []
        if depth > 0:
            if b["type"] in PAGE_TYPES:
                return [f"{'  ' * (depth - 1)}[page: {rich(b['properties'].get('title'))}]"]
            if b["type"] == "table_row":
                cells = [rich(v) for v in b["properties"].values()]
                text = " | ".join(c for c in cells if c)
            else:
                text = rich(b["properties"].get("title"))
                if b["type"] == "to_do" and b["properties"].get("checked") == [["Yes"]]:
                    text = "[x] " + text
                elif text:
                    text = PREFIX.get(b["type"], "") + text
            if text:
                lines.append("  " * (depth - 1) + text)
        for child in b["content"]:
            lines.extend(render(child, depth + 1, seen))
        return lines

    def path(b):
        names, p, hops = [], b, 0
        while p and p.get("parent_table") == "block" and hops < 20:
            p = blocks.get(p["parent_id"])
            if p and p["type"] in PAGE_TYPES:
                names.append(rich(p["properties"].get("title")))
            hops += 1
        return " / ".join(reversed([n for n in names if n])) or None

    for b in blocks.values():
        if b["type"] not in PAGE_TYPES or not b["alive"]:
            continue
        title = rich(b["properties"].get("title"))
        body = "\n".join(render(b["id"]))
        if not title and not body:
            continue
        w.add(id=b["id"], kind="note", ts=from_unix(b["created_time"], "ms"), author="me", is_me=True,
              thread=path(b), thread_name=path(b), title=title or "(untitled)",
              text="\n".join(x for x in (title, body) if x),
              meta={"modified": from_unix(b["last_edited_time"], "ms"), "type": b["type"]})


if __name__ == "__main__":
    main()
