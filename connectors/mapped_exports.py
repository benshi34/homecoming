"""Exports in formats no parser knows, read with a mapping: which files hold which kind of item, and which of
an item's fields are its time, text, title, author and thread.

A mapping is data, never code. The desktop app has Claude write one from the export's structure (field names
and shapes, plus example values only if the person allows it), runs it over the whole export to show what it
gets, and saves it once the person confirms: corpus/mappings/<folder>.json, for corpus/imports/<folder>/.
imports.py applies them before its catch-alls, so mapped files aren't also kept as generic records.

  {"service": "Wattpad", "version": 1, "items": [
     {"describe": "Stories you wrote", "file": "**/stories.json", "path": "stories", "kind": "post",
      "time": "createDate", "title": "title", "text": ["description", "tags"], "author": "me",
      "thread": "id", "url": "url", "id": "id"}]}

file: a glob matched against the path inside the export (and against the file name alone). path: dot path to
the list of items in the file ("" = the file itself; CSV files are lists of rows). author: a field, or "me"
for things the export's owner made. Any field can be a dot path ("user.name") and text takes a list. zone: "UTC"
when the export's times carry no zone but are UTC (TikTok's are); otherwise they're read as this Mac's time.
A rule with a path takes only that list: the rest of the file is still kept by imports.py's catch-all, so a
mapping that names a few lists loses nothing it doesn't name.

For CSV exports whose rows aren't all alike (the mappings the app ships, data/mappings/, use these):
  time: a list of fields, the first one filled in ("Date Read", then "Date Added"; a date of zeros, 0000-00-00, or with
    an unknown month or day, 2023-00-00, isn't). formats: strptime formats
    the time is in when it isn't ISO ("%Y/%m/%d"; Strava's "Jan 5, 2024, 3:12:45 PM").
  where / unless: {field: [values]}: only the rows whose field is (or isn't) one of them ("" for empty: Netflix's
    viewing that isn't a trailer). A file read without a
    path is taken whole, so the rules on it should leave no row out between them.
  header: the start of the line a CSV's header is on, quoted or not, for a file with more than one table (a
    Letterboxd list: the list, a blank line, then its films) or with lines before it (Venmo's statement). The table
    runs to the next blank line.
  omit: fields not kept in a record's meta.fields (Apple Music's IP address and device ids).
  html: fields whose values are markup (Evernote's note content): read as their words.
  needs: fields a row must have filled in (Venmo's balance rows have no ID: they aren't transactions).
  not: globs of paths the rule leaves to others (reviews.csv, but not likes/reviews.csv).
  "@file" as a field: the file's name without its extension (a list's films, by the list).
  mine: {field: [values]}: the rows that are yours though their author is a name (Snapchat's IsSender: True).
  path with "*": every value of an object or item of a list ("*" for Snapchat's chats, by friend;
    "chats.list.*.messages" for Telegram's), with "@key" and "@up.<field>" (a chat's name) as fields; "@root.<field>"
    is the file's. title, author, thread, thread_name, url and id take a list too: the first one filled in.
  deleted (on the mapping): globs of the paths whose items you deleted (Letterboxd's deleted/): meta.tier.
  overlap: true when the files can hold the same items (a bank's downloads, Jan-Mar then Feb-Apr). An item's id is then
    its rule's, its thread's and its id field's, not its file's (FITID is unique in its account), so one in two files
    is kept once (notes.in_another_file); a second in one file is another item (a bank that gave two one FITID).

XML files (MyAnimeList's list, Evernote's .enex) are read as JSON would be: an element is a dict of its children, a child's text as
the value, a tag that repeats a list ({"myinfo": {...}, "anime": [{...}, ...]}, so path "anime"). A .gz is read
unpacked (animelist_<time>_-_<id>.xml.gz), to no more than common.BOMB_RATIO times its size.

OFX, QFX and QBO files (a bank's or card's download for Quicken, QuickBooks or Money; OFX 1.x's SGML or 2.x's XML)
are read as {"BANKMSGSRSV1": [...], "CREDITCARDMSGSRSV1": [...]}: every STMTTRN in their statements, its fields as
the file names them (TRNTYPE, DTPOSTED, DTUSER, TRNAMT, FITID, NAME, MEMO, CHECKNUM...), with its statement's CURDEF
and "account", the account number's last four digits (the rest isn't kept). So path "BANKMSGSRSV1", id "FITID".
"""

import collections
import csv
import gzip
import html
import io
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from fnmatch import fnmatch
from html.parser import HTMLParser
from pathlib import PurePosixPath

import common
from common import CORPUS

MAPPINGS = CORPUS / "mappings"
MAPPED = {}  # export path -> dot paths of the lists a mapping read there (the catch-all leaves those out)
SOURCES = set()  # the sources this run's mappings wrote: one whose mapping was taken out is removed (imports.py)
KINDS = {"post", "message", "comment", "note", "event", "reminder", "visit", "search", "purchase", "transaction",
         "trip", "media", "listen", "watch", "read", "review", "contact", "follow", "like", "photo", "document",
         "activity", "saved", "record"}
FIELDS = ("time", "title", "text", "author", "thread", "thread_name", "url", "id")


def folder_key(folder):
    """The source a folder's mapped records go to: what imports.py's catch-alls would prefix with."""
    return re.sub(r"\W+", "_", folder.lower())


def load():
    if not MAPPINGS.is_dir():
        return {}
    out = {}
    for p in sorted(MAPPINGS.glob("*.json")):
        try:
            out[p.stem] = validate(json.loads(p.read_text()))
        except (ValueError, OSError):
            continue
    return out


def validate(m):
    """The mapping, cleaned: unknown keys dropped, kinds limited to KINDS. Raises ValueError if unusable."""
    if not isinstance(m, dict) or not isinstance(m.get("items"), list) or not m["items"]:
        raise ValueError("a mapping needs a list of items")
    items = []
    for r in m["items"]:
        if not isinstance(r, dict) or not isinstance(r.get("file"), str) or not r["file"].strip():
            raise ValueError("each item needs a file pattern")
        clean = {"file": r["file"].strip(), "path": str(r.get("path") or ""), "describe": str(r.get("describe") or r["file"])[:120],
                 "kind": r.get("kind") if r.get("kind") in KINDS else "record"}
        if str(r.get("zone") or "").upper() == "UTC":
            clean["zone"] = "UTC"
        if isinstance(r.get("header"), str) and r["header"].strip():
            clean["header"] = r["header"].strip()
        if r.get("overlap") is True:
            clean["overlap"] = True
        for k in ("formats", "not", "needs", "html", "omit"):
            if strings(r.get(k)):
                clean[k] = strings(r[k])
        for k in ("where", "unless"):  # (and "mine", below); "" is a value: the field left empty
            if isinstance(r.get(k), dict):
                vals = lambda v: [x for x in ([v] if isinstance(v, str) else v if isinstance(v, list) else []) if isinstance(x, str)]
                cond = {f: vals(v) for f, v in r[k].items() if isinstance(f, str) and vals(v)}
                if cond:
                    clean[k] = cond
        for k in FIELDS:
            v = r.get(k)
            if k == "time" and isinstance(v, list):
                v = strings(v)
                if v:
                    clean[k] = v[0] if len(v) == 1 else v
            elif k == "text":
                v = [v] if isinstance(v, str) else [x for x in v if isinstance(x, str)] if isinstance(v, list) else []
                if v:
                    clean[k] = v
            elif strings(v):  # a field, or a list of them: the first one filled in
                clean[k] = strings(v)[0] if len(strings(v)) == 1 else strings(v)
        if isinstance(r.get("mine"), dict):
            cond = {f: strings(v) for f, v in r["mine"].items() if isinstance(f, str) and strings(v)}
            if cond:
                clean["mine"] = cond
        items.append(clean)
    out = {"service": str(m.get("service") or ""), "version": 1, "items": items}
    if strings(m.get("deleted")):
        out["deleted"] = strings(m["deleted"])
    return out


def strings(v):
    """A string or a list of them, as a list of the non-empty ones."""
    v = [v] if isinstance(v, str) else v if isinstance(v, list) else []
    return [x for x in v if isinstance(x, str) and x.strip()]


def get(obj, path):
    if isinstance(obj, dict) and path in obj:  # a name with a dot in it: Capital One's "Card No."
        return obj[path]
    for part in (path or "").split("."):
        if part == "":
            continue
        if isinstance(obj, dict):
            obj = obj.get(part)
        elif isinstance(obj, list) and part.isdigit() and int(part) < len(obj):
            obj = obj[int(part)]
        else:
            return None
    return obj


def csv_text(e):
    """A CSV's text: UTF-8, else Windows-1252 (IMDb wrote that from 2018 to 2023)."""
    if not hasattr(e, "read"):
        return e.text()
    raw = e.read()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", "replace")


def unpacked(e):
    """A .gz's text, unpacked: no more than BOMB_RATIO times its packed size (at least 64 MB), or ValueError."""
    raw = e.read() if hasattr(e, "read") else e.text().encode("latin-1")
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as f:
        room = max(common.BOMB_RATIO * len(raw), 64 << 20)
        out = f.read(room + 1)
    if len(out) > room:
        raise ValueError("unpacks to many times its size")
    return out.decode("utf-8-sig", "replace")


def xml_data(text):
    """An XML file as dicts and lists: an element's children by tag (a repeated tag a list), a leaf its text."""
    # A DOCTYPE that only names its DTD (Evernote's <!DOCTYPE en-export SYSTEM "...dtd">) is fine: it isn't fetched.
    # One with declarations of its own ([...]) or any entity isn't read: no billion laughs.
    root = re.search(r"<[^?!]", text)  # where the root element starts: declarations can only come before it
    if re.search(r"<!DOCTYPE[^>]*\[|<!ENTITY", text[:root.start() if root else len(text)], re.I):
        raise ValueError("XML that declares entities isn't read")

    def conv(el):
        if not len(el):
            return (el.text or "").strip()
        out = {}
        for c in el:
            out.setdefault(c.tag, []).append(conv(c))
        return {k: v[0] if len(v) == 1 else v for k, v in out.items()}
    try:
        return conv(ET.fromstring(text.lstrip("\ufeff").encode("utf-8")))
    except ET.ParseError as x:
        raise ValueError(str(x)) from x


# Where an OFX file's transactions are: (message set, its statements, the account they're of).
OFX_STATEMENTS = (("BANKMSGSRSV1", "STMTTRNRS.STMTRS", "BANKACCTFROM"), ("CREDITCARDMSGSRSV1", "CCSTMTTRNRS.CCSTMTRS", "CCACCTFROM"))


def ofx_text(e):
    """An OFX file's text: Windows-1252 when its 1.x header says CHARSET:1252 (and not ENCODING:UTF-8), else UTF-8
    (2.x's always is), else Windows-1252."""
    if not hasattr(e, "read"):
        return e.text()
    raw = e.read()
    start = re.search(rb"<OFX[\s>]", raw, re.I)
    head = raw[:start.start() if start else 2000]
    if re.search(rb"CHARSET:\s*1252", head, re.I) and not re.search(rb"ENCODING:\s*UTF-?8", head, re.I):
        return raw.decode("cp1252", "replace")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", "replace")


def ofx_time(v):
    """An OFX date as ISO: 20260305 -> 2026-03-05, 20260305120000.000[-5:EST] -> 2026-03-05T12:00:00-05:00. A time
    with no zone stays zoneless, this Mac's time: the spec says GMT, but a bank's 050000 is often midnight in New
    York, so the day stays the day. A time of 00:00:00 is a day too: a bank writing one, which read in its zone
    would be the evening before west of it. Anything else as it is."""
    m = re.fullmatch(r"(\d{4})(\d\d)(\d\d)(?:(\d\d)(\d\d)(\d\d)?)?(?:[.:]\d+)?\s*(?:\[\s*(?:([+-]?)(\d+)(?:\.(\d+))?)?\s*(?::[^\]]*)?\])?",
                     str(v).strip())
    if not m:
        return v
    y, mo, d, h, mi, s, sign, oh, om = m.groups()
    if not h or h + mi + (s or "00") == "000000":
        return f"{y}-{mo}-{d}"
    t = f"{y}-{mo}-{d}T{h}:{mi}:{s or '00'}"
    if oh is None:
        return t
    return t + f"{sign or '+'}{int(oh):02}:{int(om or 0):02}"  # [-5:EST], [0:GMT], [+5.30:IST], [+5.45:NPT]


def ofx_data(text):
    """An OFX, QFX or QBO file's transactions, by message set (see the top). The header before <OFX> (OFXHEADER:100
    and its lines, or <?xml?><?OFX?>) is passed over. In 1.x's SGML a leaf's value runs to the next tag and its end
    tag may be left out; an aggregate's end tag isn't. A tag with no value that's never closed (a bank's empty <MEMO>)
    is an empty leaf: what came after it goes back beside it."""
    start = re.search(r"<OFX[\s>]", text, re.I)
    if not start:
        raise ValueError("not an OFX file")
    body = re.sub(r"<!--.*?-->", "", text[start.start():], flags=re.S)
    body = re.sub(r"<!\[CDATA\[(.*?)\]\]>", lambda m: html.escape(m.group(1), quote=False), body, flags=re.S)
    top = []
    stack = [("", top)]  # the aggregates open: (tag, its children, each (tag, value) or (tag, children))
    opened = collections.Counter()  # how many of each tag are open in stack: an end tag's check, without a walk down it
    # [^<>], not [^>]: a "<" that's never closed is passed over, not looked past to the end of the file at every one
    for end, tag, closed, value in re.findall(r"<(/?)([\w.]+)[^<>]*?(/?)>([^<]*)", body):
        tag = tag.upper()
        if end:
            if opened[tag]:  # (else a leaf's end tag: 2.x's, or 1.x's when it has them)
                while stack[-1][0] != tag:
                    t, kids = stack.pop()
                    opened[t] -= 1
                    stack[-1][1][-1] = (t, "")
                    stack[-1][1].extend(kids)
                stack.pop()
                opened[tag] -= 1
        elif closed or value.strip():
            stack[-1][1].append((tag, html.unescape(value.strip())))
        else:
            stack[-1][1].append((tag, []))
            stack.append((tag, stack[-1][1][-1][1]))
            opened[tag] += 1

    def conv(kids):
        out = {}
        for t, v in kids:
            out.setdefault(t, []).append(v if isinstance(v, str) else conv(v) if v else "")
        return {k: v[0] if len(v) == 1 else v for k, v in out.items()}

    def under(x, path):  # every aggregate at a dot path, any step of it repeated (two accounts' STMTTRNRS)
        xs = [x]
        for part in path.split("."):
            xs = [y for x in xs if isinstance(x, dict) for y in (x[part] if isinstance(x.get(part), list) else [x.get(part)])]
        return [x for x in xs if isinstance(x, dict)]
    tree, out = conv(top), {}
    for msgs, statements, acct in OFX_STATEMENTS:
        for st in under(tree, f"OFX.{msgs}.{statements}"):
            last4 = re.sub(r"\D", "", str(get(st, f"{acct}.ACCTID") or ""))[-4:]
            for t in under(st, "BANKTRANLIST.STMTTRN"):
                out.setdefault(msgs, []).append({**{k: ofx_time(v) if k.startswith("DT") else v for k, v in t.items()},
                                                 **({"CURDEF": st["CURDEF"]} if st.get("CURDEF") else {}),
                                                 **({"account": last4} if last4 else {})})
    return out


def parse(e, header=None):
    name = e.path.lower()
    text = None
    if name.endswith(".gz"):
        name, text = name[:-3], unpacked(e)
    if name.endswith((".ofx", ".qfx", ".qbo")):
        return ofx_data(text if text is not None else ofx_text(e))
    if name.endswith((".xml", ".enex")):
        return xml_data(text if text is not None else e.text())
    if name.endswith(".csv"):
        text = (text if text is not None else csv_text(e)).lstrip("\ufeff")
        if header:  # one table of several: from its header line to the next blank line
            lines = text.splitlines()
            start = next((i for i, x in enumerate(lines) if x.replace('"', "").lstrip().startswith(header.replace('"', "").lstrip())), None)
            if start is None:
                return []
            end = next((i for i in range(start + 1, len(lines)) if not lines[i].strip()), len(lines))
            text = "\n".join(lines[start:end])
        return list(csv.DictReader(io.StringIO(text)))
    text = text if text is not None else e.text()
    if name.endswith(".js"):  # window.YTD.x.part0 = [...] and friends
        text = text[text.find("=") + 1:] if re.match(r"^\s*[\w.$\[\]'\"]+\s*=", text) else text
    return json.loads(text)


def scalar(v):
    if isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, list) and all(isinstance(x, (str, int, float)) for x in v):
        return ", ".join(str(x) for x in v[:30])
    if isinstance(v, list) and v and all(isinstance(x, str) or isinstance(x, dict) and isinstance(x.get("text"), str) for x in v):
        return "".join(x if isinstance(x, str) else x["text"] for x in v)  # Telegram's text: plain parts and {type, text} ones
    return None


def field(it, f, path, ctx=None):
    """An item's field, by dot path. "@file": the name of the file it's in; "@key": the key or place its list had
    where the path has a "*"; "@up.<field>": the item that list is in (a Telegram chat); "@root.<field>": the file's."""
    ctx = ctx or {}
    if f == "@file":
        return PurePosixPath(path).stem
    if f == "@key":
        return ctx.get("key")
    for prefix, obj in (("@up.", ctx.get("up")), ("@root.", ctx.get("root"))):
        if f.startswith(prefix):
            return get(obj, f[len(prefix):])
    return get(it, f)


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []

    def handle_starttag(self, tag, attrs):
        if tag in ("br", "div", "p", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"):
            self.out.append("\n")

    def handle_data(self, data):
        self.out.append(data)


def html_text(v):
    """A field that's a page or a note's markup (Evernote's ENML), as its words: tags out, &nbsp; and friends read."""
    if not isinstance(v, str) or "<" not in v:
        return v
    p = _Text()
    try:
        p.feed(re.sub(r"<\?xml[^>]*\?>|<!DOCTYPE[^>]*>", "", v))
        p.close()
    except Exception:  # noqa: BLE001 - markup too broken to read: as it was
        return v
    return re.sub(r"[ \t\xa0]+", " ", re.sub(r"\s*\n\s*", "\n", "".join(p.out))).strip()


def value(it, f, path, ctx, rule):
    """A field's scalar value, its markup read as words when the rule says it's HTML."""
    v = scalar(field(it, f, path, ctx))
    return html_text(v) if f in rule.get("html", ()) else v


def first(it, fs, path, ctx, rule=None):
    """The first of the fields (one or a list) filled in, as a scalar."""
    for f in [fs] if isinstance(fs, str) else fs or []:
        v = value(it, f, path, ctx, rule or {})
        if v not in (None, ""):
            return v
    return None


def items_at(data, path):
    """(item, context) for every item at a dot path. A "*" part is every value of an object (Snapchat's chats, by
    friend) or every item of a list (Telegram's chats, each with its messages): the items under each have its key as
    "@key" and it as "@up"."""
    def walk(obj, parts, ctx):
        if not parts:
            scalar_under_star = "key" in ctx and obj not in (None, "") and not isinstance(obj, (list, dict))
            for x in obj if isinstance(obj, list) else [obj] if isinstance(obj, dict) or scalar_under_star else []:
                yield x, ctx  # a plain value under a "*" (Tinder's opens by day: {"2024-01-05": 3}) is an item, "value"
            return
        if parts[0] != "*":
            yield from walk(get(obj, parts[0]), parts[1:], ctx)
            return
        pairs = obj.items() if isinstance(obj, dict) else enumerate(obj) if isinstance(obj, list) else ()
        for k, v in pairs:
            yield from walk(v, parts[1:], {**ctx, "key": str(k), "up": v if isinstance(v, dict) else obj})
    yield from walk(data, [x for x in (path or "").split(".") if x], {"root": data})


def picked(rule, it, path, ctx=None, keys=("needs", "where", "unless")):
    """Whether a row is one of the rule's: its needs, where and unless (or, with keys=("mine",), whether it's yours)."""
    norm = lambda f: str(scalar(field(it, f, path, ctx)) if scalar(field(it, f, path, ctx)) is not None else "").strip()
    if keys == ("mine",):
        return bool(rule.get("mine")) and all(norm(f) in v for f, v in rule["mine"].items())
    return all(norm(f) for f in rule.get("needs", [])) and all(norm(f) in v for f, v in rule.get("where", {}).items()) and \
        not any(norm(f) in v for f, v in rule.get("unless", {}).items())


def time_of(rule, it, path, ctx=None):
    """The first of the rule's time fields filled in, in the rule's formats when it isn't ISO, marked UTC if the
    export's times are."""
    for f in ([rule["time"]] if isinstance(rule["time"], str) else rule["time"]):
        v = field(it, f, path, ctx)
        if v in (None, "") or re.fullmatch(r"\d{4}-\d\d-00|\d{4}-00-\d\d|0000-.*", str(v).strip()):  # MyAnimeList's unset or partial dates
            continue
        for fmt in rule.get("formats", []):
            try:
                t = datetime.strptime(re.sub(r"\s+", " ", str(v)).strip(), fmt)  # Strava's narrow space before PM too
            except ValueError:
                continue
            v = t.isoformat() if re.search(r"%[HIMSp]", fmt) else t.date().isoformat()
            break
        return utc(v) if rule.get("zone") == "UTC" else v
    return None


def matches(rule, path):
    return (fnmatch(path, rule["file"]) or fnmatch(PurePosixPath(path).name, rule["file"]) or fnmatch(path, f"*/{rule['file']}")) \
        and not any(fnmatch(path, g) or fnmatch(path, f"*/{g}") for g in rule.get("not", []))


def utc(v):
    """A zoneless time marked UTC ("2026-06-13 07:51:55" -> "2026-06-13 07:51:55 UTC"); anything else as it is."""
    if isinstance(v, str) and re.match(r"\d{4}-\d\d-\d\d[T ]\d\d:\d\d", v.strip()) and \
            not re.search(r"(Z|[+-]\d\d:?\d\d|UTC|GMT)$", v.strip(), re.I):
        return v.strip() + " UTC"
    return v


def records(mapping, entries, when=None, is_me=None):
    """(rule index, entry, record) for every item a mapping finds. when(value) -> ISO time or None;
    is_me(value) -> whether an author value is the export's owner."""
    when = when or (lambda v: None)
    is_me = is_me or (lambda v: False)
    for e in entries:
        rules = [(i, r) for i, r in enumerate(mapping["items"]) if matches(r, e.path)]
        if not rules:
            continue
        parsed = {}
        deleted = any(fnmatch(e.path, g) for g in mapping.get("deleted", []))
        for i, r in rules:
            try:
                if r.get("header") not in parsed:
                    parsed[r.get("header")] = parse(e, r.get("header"))
            except Exception:  # noqa: BLE001 - not what its name says, damaged, too deep (RecursionError) or a CSV field
                break              # too long (csv.Error): the catch-all has it, and no other export is stopped by it
            data = parsed[r.get("header")]
            here = {}  # (overlap) how many items this file has given each id so far
            for n, (it, ctx) in enumerate(items_at(data, r["path"])):
                it = it if isinstance(it, dict) else {"value": it}
                if not picked(r, it, e.path, ctx):
                    continue
                one = lambda k: first(it, r.get(k), e.path, ctx, r)
                text = "\n".join(str(v) for f in r.get("text", []) for v in [value(it, f, e.path, ctx, r)] if v not in (None, ""))
                title, ident = one("title"), one("id")
                rid = f"{e.path}#{r['path'] or r.get('header', '')}#{ident if ident not in (None, '') else n}"
                if r.get("overlap") and ident not in (None, ""):
                    rid = f"{r['path'] or r.get('header', '')}#{one('thread') or ''}#{ident}"
                    here[rid] = here.get(rid, 0) + 1
                    rid += f"#{here[rid]}" if here[rid] > 1 else ""
                author = "me" if r.get("author") == "me" else one("author")
                fields = {k: scalar(v) for k, v in it.items() if k is not None and k not in r.get("omit", ()) and scalar(v) not in (None, "")}
                rec = {"id": rid, "kind": r["kind"],
                       "ts": when(time_of(r, it, e.path, ctx)) if r.get("time") else None,
                       "title": str(title)[:300] if title not in (None, "") else None,
                       "text": text or (str(title) if title else "; ".join(f"{k}: {v}" for k, v in list(fields.items())[:20])),
                       "author": str(author) if author not in (None, "") else None,
                       "is_me": author == "me" or picked(r, it, e.path, ctx, ("mine",)) or (author is not None and is_me(str(author))),
                       "thread": str(one("thread")) if one("thread") is not None else None,
                       "thread_name": str(one("thread_name")) if one("thread_name") is not None else None,
                       "url": str(one("url")) if one("url") else None,
                       "meta": {"file": e.path, "mapped": r["describe"], "fields": dict(list(fields.items())[:40]),
                                **({"tier": "deleted"} if deleted else {})}}
                yield i, e, {k: v for k, v in rec.items() if v is not None}


def mapped_exports(es, W, used):
    """imports.py parser: every corpus/imports/<folder>/ with a mapping -> source <folder>. An item whose id another
    one has already (a mapping that names a field that isn't unique) is skipped and counted, not a failure: one
    mapping's mistake mustn't stop the others. With overlap, that's the same item in another file: counted apart."""
    SOURCES.clear()
    maps = load()
    if not maps:
        return
    from identity import is_me_email, is_me_name
    from imports import AV, DROP, leftover_time
    for folder, m in maps.items():
        mine = [e for e in es if e.path not in used and (PurePosixPath(e.origin).parts[:1] == (folder,) if e.origin else False)]
        source = folder_key(folder)
        SOURCES.add(source)
        AV.setdefault(source, f"The {m['service'] or folder} export in corpus/imports/{folder}/, read with the mapping in "
                              f"corpus/mappings/{folder}.json. {DROP}")
        for i, e, rec in records(m, mine, when=leftover_time, is_me=lambda a: is_me_name(a) or is_me_email(a)):
            w = W(source)
            if w.has(rec["id"]):
                note = "in_another_file" if m["items"][i].get("overlap") else "same_id_as_another"
                w.notes[note] = w.notes.get(note, 0) + 1
            else:
                w.add(**rec)
            path = m["items"][i]["path"].split("*")[0].rstrip(".")  # chats.list.*.messages: the catch-all leaves chats.list
            if path and e.path.lower().endswith((".json", ".csv", ".js")):
                MAPPED.setdefault(e.path, set()).add(path)
            else:  # the whole file ("", or "*": every list in it), or one the catch-all can't read (XML)
                used.add(e.path)
