"""Read comments, replies and unaccepted tracked changes from Office files.

This module intentionally uses only the standard library.  Office packages are
ZIP files containing small XML parts, and each part is read independently so a
damaged optional part does not hide comments or changes that are still usable.
"""

from __future__ import annotations

import datetime as _dt
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
W15 = "http://schemas.microsoft.com/office/word/2012/wordml"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
XL = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P188 = "http://schemas.microsoft.com/office/powerpoint/2018/moderncomments"
ODF_OFFICE = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
ODF_TEXT = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
ODF_DC = "http://purl.org/dc/elements/1.1/"
ODF_LOEXT = "urn:org:documentfoundation:names:experimental:office:xmlns:loext:1.0"


def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _attr(el, name, *namespaces):
    """Get an attribute by local name, preferring the supplied namespaces."""
    for ns in namespaces:
        value = el.get(f"{{{ns}}}{name}")
        if value is not None:
            return value
    value = el.get(name)
    if value is not None:
        return value
    for key, value in el.attrib.items():
        if _local(key) == name:
            return value
    return None


def _date(value):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        when = _dt.datetime.fromisoformat(text)
    except (TypeError, ValueError, OverflowError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=_dt.timezone.utc)
    else:
        when = when.astimezone(_dt.timezone.utc)
    return when.isoformat().replace("+00:00", "Z")


def _truth(value):
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "resolved", "done"}:
        return True
    if text in {"0", "false", "no", "off", "active", "normal", "open"}:
        return False
    return None


def _record(identifier, author, date, text, anchor=None, resolved=None, initials=None, replies=False):
    result = {
        "id": "" if identifier is None else str(identifier),
        "author": "" if author is None else str(author),
        "date": date,
        "text": text or "",
        "anchor": anchor,
        "resolved": resolved,
    }
    if initials is not None:
        result["initials"] = initials
    if replies:
        result["replies"] = []
    return result


def _without_replies(record):
    return {key: value for key, value in record.items() if key != "replies"}


def _finish(comments=(), changes=()):
    result = {}
    if comments:
        result["comments"] = list(comments)
    if changes:
        result["changes"] = list(changes)
    return result or None


def _parse_xml(data):
    try:
        return ET.fromstring(data)
    except (ET.ParseError, ValueError, TypeError):
        return None


def _read_zip(path):
    try:
        return zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile, ValueError):
        return None


def _zip_names(z):
    try:
        return set(z.namelist())
    except (OSError, ValueError):
        return set()


def _zread(z, name):
    try:
        return z.read(name)
    except (KeyError, OSError, ValueError, RuntimeError, zipfile.BadZipFile):
        return None


def _element_text(el, paragraph_local=None):
    """Text of an XML element, with paragraph boundaries where useful."""
    if el is None:
        return ""
    if paragraph_local:
        paragraphs = [x for x in el.iter() if _local(x.tag) in paragraph_local]
        if paragraphs:
            return "\n".join("".join(x.itertext()) for x in paragraphs).strip()
    return "".join(el.itertext()).strip()


def _word_text(el):
    parts = []
    for child in el.iter():
        local = _local(child.tag)
        if local in {"t", "delText"}:
            parts.append(child.text or "")
        elif local in {"tab"}:
            parts.append("\t")
        elif local in {"br", "cr"}:
            parts.append("\n")
    return "".join(parts)


def _docx_anchors(root):
    anchors = {}
    active = []

    def visit(el):
        local = _local(el.tag)
        if local == "commentRangeStart":
            identifier = _attr(el, "id", W)
            if identifier is not None:
                active.append(str(identifier))
            return
        if local == "commentRangeEnd":
            identifier = str(_attr(el, "id", W)) if _attr(el, "id", W) is not None else None
            if identifier in active:
                # Remove the innermost matching range.  Word normally nests
                # ranges cleanly, but this is tolerant of malformed XML.
                for index in range(len(active) - 1, -1, -1):
                    if active[index] == identifier:
                        active.pop(index)
                        break
            return
        if local in {"t", "delText"}:
            text = el.text or ""
            for identifier in active:
                anchors.setdefault(identifier, []).append(text)
            return
        if local == "tab":
            for identifier in active:
                anchors.setdefault(identifier, []).append("\t")
            return
        if local in {"br", "cr"}:
            for identifier in active:
                anchors.setdefault(identifier, []).append("\n")
            return
        for child in list(el):
            visit(child)

    visit(root)
    return {key: "".join(value).strip() for key, value in anchors.items()}


def _docx_changes(root):
    changes = []

    def visit(el, inside=False):
        local = _local(el.tag)
        if local in {"ins", "del"} and not inside:
            text = _word_text(el)
            if text:
                changes.append({
                    "kind": "insert" if local == "ins" else "delete",
                    "author": _attr(el, "author", W) or "",
                    "date": _date(_attr(el, "date", W)),
                    "text": text,
                })
            return
        for child in list(el):
            visit(child, inside or local in {"ins", "del"})

    visit(root)
    return changes


def _docx(path):
    z = _read_zip(path)
    if z is None:
        return None
    try:
        names = _zip_names(z)
        comments = []
        comments_root = _parse_xml(_zread(z, "word/comments.xml")) if "word/comments.xml" in names else None
        document_root = _parse_xml(_zread(z, "word/document.xml")) if "word/document.xml" in names else None
        anchors = _docx_anchors(document_root) if document_root is not None else {}
        changes = _docx_changes(document_root) if document_root is not None else []

        by_para = {}
        raw = []
        if comments_root is not None:
            for comment in comments_root.iter():
                if _local(comment.tag) != "comment":
                    continue
                paragraphs = [p for p in comment.iter() if _local(p.tag) == "p"]
                para_id = None
                if paragraphs:
                    para_id = _attr(paragraphs[-1], "paraId", W14)
                record = _record(
                    _attr(comment, "id", W),
                    _attr(comment, "author", W) or "",
                    _date(_attr(comment, "date", W)),
                    _element_text(comment, {"p"}) if paragraphs else _word_text(comment),
                    anchors.get(str(_attr(comment, "id", W))) if _attr(comment, "id", W) is not None else None,
                    None,
                    _attr(comment, "initials", W),
                    replies=True,
                )
                raw.append((record, str(para_id) if para_id is not None else None))
                if para_id is not None:
                    by_para[str(para_id)] = record

        extended = None
        ext_data = _zread(z, "word/commentsExtended.xml") if "word/commentsExtended.xml" in names else None
        if ext_data is not None:
            extended = _parse_xml(ext_data)
        extensions = {}
        if extended is not None:
            for item in extended.iter():
                if _local(item.tag) != "commentEx":
                    continue
                para_id = _attr(item, "paraId", W15)
                if para_id is None:
                    continue
                extensions[str(para_id)] = (
                    str(_attr(item, "paraIdParent", W15)) if _attr(item, "paraIdParent", W15) is not None else None,
                    _truth(_attr(item, "done", W15)),
                )
        for record, para_id in raw:
            if para_id in extensions:
                record["resolved"] = extensions[para_id][1]

        if extensions:
            # First identify roots, then attach replies.  The separate pass
            # also handles an export that happens to list a reply before its
            # parent, and keeps malformed nested replies one level deep.
            roots = []
            root_paras = set()
            for record, para_id in raw:
                parent = extensions.get(para_id, (None, None))[0]
                if parent is None or parent not in by_para:
                    roots.append(record)
                    if para_id is not None:
                        root_paras.add(para_id)

            def root_for(para_id):
                seen = set()
                current = para_id
                while current in extensions and current not in seen:
                    seen.add(current)
                    parent = extensions[current][0]
                    if parent is None or parent not in by_para:
                        return by_para.get(current)
                    current = parent
                return by_para.get(current) if current in root_paras else None

            for record, para_id in raw:
                if para_id in root_paras or para_id is None:
                    continue
                root = root_for(para_id)
                if root is None:
                    roots.append(record)
                else:
                    record["anchor"] = None
                    root["replies"].append(_without_replies(record))
            comments = roots
        else:
            comments = [record for record, _ in raw]
        return _finish(comments, changes)
    finally:
        z.close()


def _source_from_rels_path(rels_path):
    directory, filename = posixpath.split(rels_path)
    if directory.endswith("/_rels"):
        directory = directory[:-5]
    if filename.endswith(".rels"):
        filename = filename[:-5]
    return posixpath.normpath(posixpath.join(directory, filename))


def _target(source, target):
    if not target:
        return None
    if target.startswith("/"):
        return posixpath.normpath(target[1:])
    return posixpath.normpath(posixpath.join(posixpath.dirname(source), target))


def _rels(z, rels_path):
    root = _parse_xml(_zread(z, rels_path))
    if root is None:
        return []
    source = _source_from_rels_path(rels_path)
    out = []
    for rel in root.iter():
        if _local(rel.tag) != "Relationship":
            continue
        out.append((_target(source, rel.get("Target")), rel.get("Type") or "", rel.get("Id") or ""))
    return out


def _xlsx_sheets(z):
    names = _zip_names(z)
    workbook = _parse_xml(_zread(z, "xl/workbook.xml")) if "xl/workbook.xml" in names else None
    wb_rels = dict((rid, target) for target, _type, rid in _rels(z, "xl/_rels/workbook.xml.rels"))
    sheets = {}
    if workbook is None:
        return sheets
    for sheet in workbook.iter():
        if _local(sheet.tag) != "sheet":
            continue
        name = sheet.get("name") or ""
        rid = _attr(sheet, "id", R)
        source = wb_rels.get(rid)
        if not source:
            continue
        rels_path = posixpath.join(posixpath.dirname(source), "_rels", posixpath.basename(source) + ".rels")
        for part, typ, _ in _rels(z, rels_path):
            if part and ("comments" in typ.lower() or "threadedcomment" in typ.lower()):
                sheets[part] = name
    return sheets


def _xlsx_persons(z):
    persons = {}
    for name in _zip_names(z):
        if name.startswith("xl/persons/") and name.endswith(".xml"):
            root = _parse_xml(_zread(z, name))
            if root is None:
                continue
            for person in root.iter():
                if _local(person.tag) == "person":
                    identifier = _attr(person, "id")
                    if identifier is not None:
                        persons[str(identifier)] = person.get("displayName") or person.get("name") or ""
    return persons


def _xlsx(path):
    z = _read_zip(path)
    if z is None:
        return None
    try:
        sheet_for = _xlsx_sheets(z)
        comments = []
        names = _zip_names(z)
        # Legacy notes.
        for part in sorted(n for n in names if re.match(r"xl/comments[^/]*\.xml$", n, re.I)):
            root = _parse_xml(_zread(z, part))
            if root is None:
                continue
            authors = []
            for el in root.iter():
                if _local(el.tag) == "author":
                    authors.append("".join(el.itertext()))
            for comment in root.iter():
                if _local(comment.tag) != "comment":
                    continue
                ref = _attr(comment, "ref") or ""
                author_id = _attr(comment, "authorId")
                try:
                    author = authors[int(author_id)] if author_id is not None and int(author_id) < len(authors) else ""
                except (ValueError, TypeError):
                    author = ""
                sheet = sheet_for.get(part)
                anchor = f"{sheet}!{ref}" if sheet else ref or None
                comments.append(_record(ref, author, None, _element_text(comment, {"text"}), anchor, None, replies=True))

        # Threaded comments.
        persons = _xlsx_persons(z)
        for part in sorted(n for n in names if n.startswith("xl/threadedComments/") and n.endswith(".xml")):
            root = _parse_xml(_zread(z, part))
            if root is None:
                continue
            nodes = []
            for item in root.iter():
                if _local(item.tag) != "threadedComment":
                    continue
                identifier = _attr(item, "id") or ""
                parent = _attr(item, "parentId")
                ref = _attr(item, "ref") or ""
                sheet = sheet_for.get(part)
                anchor = f"{sheet}!{ref}" if sheet else ref or None
                nodes.append((
                    _record(identifier, persons.get(str(_attr(item, "personId")), ""), _date(_attr(item, "dT")),
                            _element_text(item, {"text"}), anchor, _truth(_attr(item, "done")), replies=True),
                    str(parent) if parent else None,
                ))
            by_id = {record["id"]: record for record, _ in nodes}
            roots = []
            for record, parent in nodes:
                if parent and parent in by_id:
                    by_id[parent]["replies"].append(_without_replies(record))
                else:
                    roots.append(record)
            comments.extend(roots)
        return _finish(comments)
    finally:
        z.close()


def _ppt_sheets(z):
    result = {}
    for rels_path in _zip_names(z):
        match = re.fullmatch(r"ppt/slides/_rels/slide(\d+)\.xml\.rels", rels_path, re.I)
        if not match:
            continue
        anchor = f"slide {int(match.group(1))}"
        for part, typ, _ in _rels(z, rels_path):
            if part and "comment" in typ.lower():
                result[part] = anchor
    return result


def _ppt_authors(z, names):
    authors = {}
    for filename in ("ppt/commentAuthors.xml", "ppt/authors.xml"):
        if filename not in names:
            continue
        root = _parse_xml(_zread(z, filename))
        if root is None:
            continue
        for item in root.iter():
            local = _local(item.tag)
            if local not in {"cmAuthor", "author"}:
                continue
            identifier = _attr(item, "id")
            if identifier is not None:
                authors[str(identifier)] = (item.get("name") or item.get("displayName") or "", item.get("initials"))
    return authors


def _ppt_text(el):
    # A modern comment contains its replies below replyLst; those belong in
    # ``replies`` and must not be folded into the parent's text.
    def descendants_without_replies(node):
        for child in node:
            if _local(child.tag) == "replyLst":
                continue
            yield child
            yield from descendants_without_replies(child)

    def text_without_replies(node):
        parts = [node.text or ""]
        for child in node:
            if _local(child.tag) == "replyLst":
                continue
            parts.extend(text_without_replies(child))
            parts.append(child.tail or "")
        return parts

    all_nodes = [el, *descendants_without_replies(el)]
    paragraphs = [x for x in all_nodes if _local(x.tag) == "p" and any(_local(y.tag) == "t" for y in descendants_without_replies(x))]
    if paragraphs:
        return "\n".join("".join(text_without_replies(p)).strip() for p in paragraphs).strip()
    return "".join(text_without_replies(el)).strip()


def _ppt(path):
    z = _read_zip(path)
    if z is None:
        return None
    try:
        names = _zip_names(z)
        sheet_for = _ppt_sheets(z)
        authors = _ppt_authors(z, names)
        comments = []
        for part in sorted(n for n in names if re.match(r"ppt/comments/comment[^/]*\.xml$", n, re.I)):
            root = _parse_xml(_zread(z, part))
            if root is None:
                continue
            for item in root.iter():
                if _local(item.tag) != "cm":
                    continue
                identifier = _attr(item, "idx") or _attr(item, "id") or ""
                author, initials = authors.get(str(_attr(item, "authorId")), ("", None))
                comments.append(_record(identifier, author, _date(_attr(item, "dt")), _ppt_text(item),
                                        sheet_for.get(part), None, initials, replies=True))

        modern = []
        for part in sorted(n for n in names if re.match(r"ppt/comments/modernComment_[^/]*\.xml$", n, re.I)):
            root = _parse_xml(_zread(z, part))
            if root is None:
                continue
            for item in root.iter():
                if _local(item.tag) != "cm":
                    continue
                identifier = _attr(item, "id") or _attr(item, "idx") or ""
                author, initials = authors.get(str(_attr(item, "authorId")), ("", None))
                resolved = _truth(_attr(item, "status"))
                record = _record(identifier, author, _date(_attr(item, "created")), _ppt_text(item),
                                 sheet_for.get(part), resolved, initials, replies=True)
                reply_list = next((x for x in item if _local(x.tag) == "replyLst"), None)
                if reply_list is not None:
                    for reply in reply_list:
                        if _local(reply.tag) != "reply":
                            continue
                        reply_author, reply_initials = authors.get(str(_attr(reply, "authorId")), ("", None))
                        record["replies"].append(_record(
                            _attr(reply, "id") or _attr(reply, "idx") or "",
                            reply_author,
                            _date(_attr(reply, "created") or _attr(reply, "dt")),
                            _ppt_text(reply),
                            sheet_for.get(part),
                            _truth(_attr(reply, "status")),
                            reply_initials,
                            replies=False,
                        ))
                modern.append(record)
        comments.extend(modern)
        return _finish(comments)
    finally:
        z.close()


def _odf_text(annotation):
    paragraphs = [x for x in annotation.iter() if _local(x.tag) == "p"]
    if paragraphs:
        return "\n".join("".join(x.itertext()) for x in paragraphs).strip()
    return "".join(annotation.itertext()).strip()


def _odf_info(annotation, local):
    for item in annotation.iter():
        if _local(item.tag) == local and (_local(item.tag) in {"creator", "date"}):
            return "".join(item.itertext()).strip()
    return ""


def _odf_anchors(root, reply_names=()):
    anchors = {}

    def add(text, active):
        if text:
            for name in active:
                anchors.setdefault(name, []).append(text)

    def visit(el, active):
        local = _local(el.tag)
        if local == "annotation":
            name = _attr(el, "name", ODF_OFFICE)
            # The annotation's own children are its note, not the marked text.
            if name is not None and str(name) not in reply_names:
                return active + [str(name)]
            return active
        if local == "annotation-end":
            name = _attr(el, "name", ODF_OFFICE)
            current = list(active)
            if name is not None:
                for index in range(len(current) - 1, -1, -1):
                    if current[index] == str(name):
                        current.pop(index)
                        break
            return current
        if el.text:
            add(el.text, active)
        current = active
        for child in list(el):
            current = visit(child, current)
            if child.tail:
                add(child.tail, current)
        return current

    visit(root, [])
    return {name: "".join(text).strip() for name, text in anchors.items()}


def _odf_changes(root):
    definitions = {}
    definition_order = []
    tracked = next((x for x in root.iter() if _local(x.tag) == "tracked-changes"), None)
    if tracked is not None:
        for region in tracked.iter():
            if _local(region.tag) != "changed-region":
                continue
            identifier = _attr(region, "id", ODF_TEXT) or _attr(region, "id") or ""
            kind = None
            body = None
            for child in region:
                if _local(child.tag) in {"insertion", "deletion"}:
                    kind = "insert" if _local(child.tag) == "insertion" else "delete"
                    body = child
                    break
            if kind is None:
                continue
            info = next((x for x in region.iter() if _local(x.tag) == "change-info"), None)
            author = ""
            date = None
            if info is not None:
                for item in info.iter():
                    if _local(item.tag) == "creator":
                        author = "".join(item.itertext()).strip()
                    elif _local(item.tag) == "date":
                        date = _date("".join(item.itertext()).strip())
            text = "" if kind == "insert" else _element_text(body, {"p"})
            definitions[str(identifier)] = {"kind": kind, "author": author, "date": date, "text": text}
            definition_order.append(str(identifier))

    insertion_text = {}
    body_root = next((x for x in root.iter() if _local(x.tag) == "body"), None)
    active = []
    insertion_order = []

    def visit(el):
        local = _local(el.tag)
        if local == "change-start":
            identifier = _attr(el, "change-id", ODF_TEXT) or _attr(el, "change-id")
            if identifier is not None:
                active.append(str(identifier))
                insertion_order.append(str(identifier))
            return
        if local == "change-end":
            identifier = _attr(el, "change-id", ODF_TEXT) or _attr(el, "change-id")
            if identifier is not None and str(identifier) in active:
                active.remove(str(identifier))
            return
        if el.text:
            for identifier in active:
                insertion_text.setdefault(identifier, []).append(el.text)
        for child in list(el):
            visit(child)
            if child.tail:
                for identifier in active:
                    insertion_text.setdefault(identifier, []).append(child.tail)

    if body_root is not None:
        visit(body_root)
    changes = []
    seen = set()
    for identifier in definition_order + insertion_order:
        if identifier in seen:
            continue
        seen.add(identifier)
        definition = definitions.get(identifier)
        if definition is None:
            continue
        text = "".join(insertion_text.get(identifier, [])) if definition["kind"] == "insert" else definition["text"]
        if text:
            changes.append({**definition, "text": text.strip()})
    return changes


def _odf(path):
    z = _read_zip(path)
    if z is None:
        return None
    try:
        names = _zip_names(z)
        root = _parse_xml(_zread(z, "content.xml")) if "content.xml" in names else None
        if root is None:
            return None
        comments = []
        annotations = []
        for annotation in root.iter():
            if _local(annotation.tag) != "annotation":
                continue
            name = _attr(annotation, "name", ODF_OFFICE)
            identifier = str(name) if name is not None else str(len(annotations))
            parent = _attr(annotation, "parent-name", ODF_LOEXT, ODF_OFFICE)
            record = _record(identifier,
                             _odf_info(annotation, "creator"),
                             _date(_odf_info(annotation, "date")),
                             _odf_text(annotation),
                             None,
                             _truth(_attr(annotation, "resolved", ODF_LOEXT)),
                             None,
                             replies=True)
            annotations.append((record, str(parent) if parent is not None else None))
        reply_names = {record["id"] for record, parent in annotations if parent}
        anchors = _odf_anchors(root, reply_names)
        for record, _ in annotations:
            record["anchor"] = anchors.get(record["id"])
        by_id = {record["id"]: record for record, _ in annotations}
        for record, parent in annotations:
            if parent and parent in by_id:
                by_id[parent]["replies"].append(_without_replies(record))
            else:
                comments.append(record)
        return _finish(comments, _odf_changes(root))
    finally:
        z.close()


def notes(path):
    """Return comments/replies and unaccepted tracked changes from *path*.

    Bad files and files with no supported notes return ``None``.  Individual
    optional XML parts are best-effort, so readable comments can survive a
    damaged changes part and vice versa.
    """
    try:
        suffix = Path(path).suffix.lower()
        if suffix == ".docx":
            return _docx(path)
        if suffix == ".xlsx":
            return _xlsx(path)
        if suffix == ".pptx":
            return _ppt(path)
        if suffix in {".odt", ".ods", ".odp"}:
            return _odf(path)
    except (OSError, ValueError, TypeError, KeyError, IndexError, ET.ParseError, zipfile.BadZipFile):
        return None
    return None


__all__ = ["notes"]


OFFICE_EXT = (".docx", ".docm", ".xlsx", ".xlsm", ".pptx", ".odt", ".ods", ".odp")


def as_text(found):
    """Comments, their replies and tracked changes as lines to search by, after a document's own text."""
    if not found:
        return ""
    lines = []
    for c in found.get("comments", []):
        on = f' (on "{c["anchor"][:80]}")' if c.get("anchor") else ""
        lines.append(f"Comment, {c.get('author') or 'someone'}{on}{' [resolved]' if c.get('resolved') else ''}: {c.get('text') or ''}")
        lines += [f"  Reply, {r.get('author') or 'someone'}: {r.get('text') or ''}" for r in c.get("replies", [])]
    lines += [f"{'Inserted' if x.get('kind') == 'insert' else 'Deleted'} by {x.get('author') or 'someone'}: {x.get('text') or ''}"
              for x in found.get("changes", [])]
    return "\n".join(lines)


def counts(found):
    """How many comments, replies and tracked changes, for a record's meta (none: nothing)."""
    if not found:
        return {}
    cs = found.get("comments", [])
    return {k: v for k, v in (("comments", len(cs)), ("replies", sum(len(c.get("replies", [])) for c in cs)),
                              ("tracked_changes", len(found.get("changes", [])))) if v}
