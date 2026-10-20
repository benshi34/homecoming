"""Apple Contacts: the Mac's AddressBook (source contacts) and the iPhone's, from the decrypted backup
(source iphone_contacts). Also provides Resolver: phone/email -> contact name, used by the messaging, call
and mail connectors to join everything by person. The Resolver prefers the phone's address book, then vCards
dropped into corpus/imports/ (an iPhone export, Takeout Contacts), then the Mac's, which can lag far behind."""

import collections
import quopri
import re
import sqlite3
import zipfile

from common import CORPUS, LIB, Writer, columns, connect, from_apple, phone, select, snapshot_sqlite
from phones import e164

AB = LIB / "Application Support/AddressBook"
IMPORTS = CORPUS / "imports"
AVENUE = ("Local SQLite: ~/Library/Application Support/AddressBook/Sources/*/AddressBook-v22.abcddb "
          "(one DB per account). Needs Full Disk Access.")
PHONE_AB = phone("HomeDomain", "Library/AddressBook/AddressBook.sqlitedb")
PHONE_AVENUE = "iPhone backup (connectors/iphone_backup.py) → HomeDomain/Library/AddressBook/AddressBook.sqlitedb"
# ABMultiValue.property in the phone's AddressBook.sqlitedb
PHONE_PROPS = {3: "phones", 4: "emails", 5: "addresses", 13: "social", 22: "urls", 23: "related", 46: "social"}


def norm_phone(s):
    """+<country code><number>, a number without its country code read in this Mac's region (phones.py)."""
    return e164(s) or (re.sub(r"\D", "", s or "") or None)


def norm_handle(s):
    s = (s or "").strip()
    if "@" in s:
        return s.lower()
    return norm_phone(s)


def tail(s):
    """A number's last nine digits: matches a friend abroad saved without their country code, when the full number
    doesn't, and only one number in your contacts ends this way (Resolver.name)."""
    d = re.sub(r"\D", "", s or "")
    return d[-9:] if "@" not in (s or "") and len(d) >= 9 else None


def _db_paths():
    return sorted(AB.glob("Sources/*/AddressBook-v22.abcddb")) + [AB / "AddressBook-v22.abcddb"]


# Every file is named AddressBook-v22.abcddb, but what's in it depends on the macOS that last wrote it, and one Mac
# can keep both kinds (an old account's beside a new one's). Your own card is marked by a container in newer files and
# by a source in ones last written around 2018 (thanks to a tester's report, homecoming#1); the other fields are read
# where the file has them.
ME_COLUMNS = ("ZCONTAINERWHERECONTACTISME", "ZSOURCEWHERECONTACTISME")
RECORD_COLUMNS = ("ZFIRSTNAME", "ZMIDDLENAME", "ZLASTNAME", "ZNICKNAME", "ZORGANIZATION", "ZJOBTITLE", "ZDEPARTMENT",
                  "ZBIRTHDAY", "ZCREATIONDATE", "ZMODIFICATIONDATE")
MULTI = (("ZABCDPHONENUMBER", "ZFULLNUMBER"), ("ZABCDEMAILADDRESS", "ZADDRESS"), ("ZABCDSOCIALPROFILE", "ZUSERNAME"),
         ("ZABCDURLADDRESS", "ZURL"), ("ZABCDRELATEDNAME", "ZNAME"))
ADDRESS = ("ZSTREET", "ZCITY", "ZSTATE", "ZZIPCODE", "ZCOUNTRYNAME")


def _tables(con):
    return {r[0] for r in con.execute("select name from sqlite_master where type = 'table'")}


def load_contacts(snapshot=False):
    contacts = []
    for i, path in enumerate(_db_paths()):
        if not path.exists():
            continue
        if snapshot:
            path = snapshot_sqlite(path, f"contacts/{i}_{path.parent.name}.abcddb")
        con = connect(path)
        # One file it can't make sense of is left out, said so, and the rest are read: Messages, calls and mail
        # look up names here, and one old account's file mustn't stop them all.
        try:
            contacts += _address_book(con)
        except sqlite3.Error as e:
            print(f"[contacts] couldn't read the address book in {path.parent.name} ({e}); the others are read")
        finally:
            con.close()
    return contacts


def _address_book(con):
    contacts = []
    tables = _tables(con)
    multi = {}
    for table, col in MULTI:
        if table not in tables or not {"ZOWNER", "ZLABEL", col} <= columns(con, table):
            continue
        for r in con.execute(f"select ZOWNER, ZLABEL, {col} v from {table} where {col} is not null"):
            label = (r["ZLABEL"] or "").strip("_$!<>") or None
            multi.setdefault(r["ZOWNER"], {}).setdefault(table, []).append((label, r["v"]))
    addrs = {}
    if "ZABCDPOSTALADDRESS" in tables:
        have = columns(con, "ZABCDPOSTALADDRESS")
        for r in con.execute("select * from ZABCDPOSTALADDRESS"):
            parts = [r[c] for c in ADDRESS if c in have]
            addrs.setdefault(r["ZOWNER"], []).append(", ".join(p for p in parts if p))
    notes = {r["ZCONTACT"]: r["ZTEXT"] for r in con.execute("select ZCONTACT, ZTEXT from ZABCDNOTE")} if "ZABCDNOTE" in tables else {}
    have = columns(con, "ZABCDRECORD")
    me = next((c for c in ME_COLUMNS if c in have), "0")
    fields = ", ".join(c if c in have else f"null as {c}" for c in RECORD_COLUMNS)
    rows = con.execute(f"""select Z_PK, ZUNIQUEID, {fields}, {me} as is_me
                           from ZABCDRECORD where Z_ENT = (select Z_ENT from Z_PRIMARYKEY where Z_NAME='ABCDContact')""")
    for r in rows:
        name = " ".join(p for p in (r["ZFIRSTNAME"], r["ZMIDDLENAME"], r["ZLASTNAME"]) if p)
        name = name or r["ZNICKNAME"] or r["ZORGANIZATION"]
        m = multi.get(r["Z_PK"], {})
        if not name and not m:
            continue
        contacts.append({
            "uid": r["ZUNIQUEID"], "name": name, "nickname": r["ZNICKNAME"],
            "org": r["ZORGANIZATION"], "job": r["ZJOBTITLE"], "department": r["ZDEPARTMENT"],
            "birthday": from_apple(r["ZBIRTHDAY"]), "created": from_apple(r["ZCREATIONDATE"]),
            "modified": from_apple(r["ZMODIFICATIONDATE"]), "is_me": bool(r["is_me"]),
            "phones": m.get("ZABCDPHONENUMBER", []), "emails": m.get("ZABCDEMAILADDRESS", []),
            "social": m.get("ZABCDSOCIALPROFILE", []), "urls": m.get("ZABCDURLADDRESS", []),
            "related": m.get("ZABCDRELATEDNAME", []), "addresses": addrs.get(r["Z_PK"], []),
            "note": notes.get(r["Z_PK"]),
        })
    return contacts


# ABPerson's columns read; a version without one has it as null (iLEAPP's addressBook reads the same, and DisplayName).
PERSON = ("ROWID", "guid", "First", "Middle", "Last", "Nickname", "Organization", "DisplayName", "JobTitle", "Department",
          "Birthday", "CreationDate", "ModificationDate", "Note")


def load_phone_contacts():
    """The iPhone's AddressBook.sqlitedb (older ABPerson / ABMultiValue schema), same dicts as load_contacts. Any table
    but ABPerson may be missing (labels, entry keys: an address book with no addresses), and any column but ROWID; a
    file with no ABPerson has no contacts. Birthday is text holding Apple seconds ("-31579200.000000"), else none."""
    if not PHONE_AB.exists():
        return []
    con = connect(PHONE_AB)
    try:
        return _phone_contacts(con)
    finally:
        con.close()


def _phone_contacts(con):
    have = _tables(con)
    if "ABPerson" not in have:
        return []
    def rows(table, want):
        return con.execute(select(con, table, want)) if table in have else []
    labels = {r[0]: r[1] for r in rows("ABMultiValueLabel", ("ROWID", "value"))}
    keys = {r[0]: r[1] for r in rows("ABMultiValueEntryKey", ("ROWID", "value"))}
    entries = {}
    for r in rows("ABMultiValueEntry", ("parent_id", "key", "value")):
        entries.setdefault(r["parent_id"], {})[keys.get(r["key"])] = r["value"]
    multi = {}
    for r in rows("ABMultiValue", ("UID", "record_id", "property", "label", "value")):
        field = PHONE_PROPS.get(r["property"])
        if not field:
            continue
        v = r["value"]
        if v is None and r["UID"] in entries:
            e = entries[r["UID"]]
            v = ", ".join(e[k] for k in ("Street", "City", "State", "ZIP", "Country") if e.get(k)) if field == "addresses" \
                else " ".join(x for x in (e.get("service"), e.get("username") or e.get("url")) if x)
        if v:
            label = (labels.get(r["label"]) or "").strip("_$!<>") or None
            multi.setdefault(r["record_id"], {}).setdefault(field, []).append(v if field == "addresses" else (label, v))
    out = []
    for r in con.execute(select(con, "ABPerson", PERSON)):
        name = (" ".join(x for x in (r["First"], r["Middle"], r["Last"]) if x) or r["Nickname"] or r["Organization"]
                or r["DisplayName"])
        m = multi.get(r["ROWID"], {})
        if not name and not m:
            continue
        try:
            bday = from_apple(float(r["Birthday"])) if r["Birthday"] not in (None, "") else None
        except (TypeError, ValueError):
            bday = None
        out.append({
            "uid": r["guid"] or f"row{r['ROWID']}", "name": name, "nickname": r["Nickname"], "org": r["Organization"],
            "job": r["JobTitle"], "department": r["Department"], "birthday": bday,
            "created": from_apple(r["CreationDate"]), "modified": from_apple(r["ModificationDate"]), "is_me": False,
            "phones": m.get("phones", []), "emails": m.get("emails", []), "social": m.get("social", []),
            "urls": m.get("urls", []), "related": m.get("related", []), "addresses": m.get("addresses", []),
            "note": r["Note"],
        })
    return out


def vcard_text(b):
    """A .vcf's bytes as text: UTF-8 as most are, UTF-16 (an old Mac's Address Book wrote that, with or without a byte
    order mark), else Windows' Latin-1 (a 2.1 card from an old phone or Outlook, 8-bit without saying so)."""
    for bom, enc in ((b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16")):
        if b.startswith(bom):
            return b.decode(enc, "replace")
    if b[:1] == b"\x00" or b[1:2] == b"\x00":  # "\x00B\x00E..." / "B\x00E\x00...": BEGIN in UTF-16 without a mark
        return b.decode("utf-16-be" if b[:1] == b"\x00" else "utf-16-le", "replace")
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("cp1252", "replace")


def vcard_value(val):
    """A value with its escapes undone: \\n a new line, and \\, \\; \\: \\\\ the character itself (Google writes
    "http\\://")."""
    return re.sub(r"\\(.)", lambda m: "\n" if m.group(1) in "nN" else m.group(1), val)


def parse_vcards(text):
    """vCard 2.1/3/4 text -> one {FIELD: [values]} dict per card (FN, N, TEL, EMAIL, ORG, BDAY, ...). A 2.1 card (an
    Android phone's export) writes a value that isn't ASCII as quoted-printable, its lines ending in "=" going on. A 4.0
    card can write a number or an address as a link (tel:+1..., mailto:...): kept as the number or address."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")  # an old Mac's Address Book ended its lines with CR alone
    body = re.sub(r"\n[ \t]", "", text)  # unfold continuation lines
    cards = []
    for block in re.findall(r"BEGIN:VCARD\r?\n(.*?)END:VCARD", body, re.S | re.I):
        d = collections.defaultdict(list)
        lines = iter(block.splitlines())
        for line in lines:
            if ":" in line:
                key, val = line.split(":", 1)
                params = key.upper().split(";")
                if "ENCODING=QUOTED-PRINTABLE" in params or "QUOTED-PRINTABLE" in params:
                    while val.endswith("="):  # a soft line break
                        val = val[:-1] + next(lines, "")
                    charset = next((x[8:] for x in params if x.startswith("CHARSET=")), "UTF-8")
                    raw = quopri.decodestring(val.encode("utf-8"))
                    try:
                        val = raw.decode(charset, "replace")
                    except LookupError:
                        val = raw.decode("utf-8", "replace")
                field = params[0].split(".")[-1]
                val = vcard_value(val)
                if field in ("TEL", "EMAIL"):
                    val = re.sub(r"^(tel|mailto):", "", val.strip(), flags=re.I)
                d[field].append(val)
        cards.append(d)
    return cards


def vcard_name(d):
    """A card's name: its FN, else its N, else a nickname or the company (a plumber saved by firm name)."""
    n = " ".join(reversed((d.get("N") or [""])[0].split(";")[:2])).strip()
    names = [*(d.get("FN") or []), n, *(d.get("NICKNAME") or []), *(x.split(";")[0] for x in d.get("ORG") or [])]
    return next((x.strip() for x in names if x.strip()), "")


def imported_vcards():
    """Text of every .vcf in corpus/imports/: loose files first (e.g. an AirDropped iPhone export), then inside zips."""
    if not IMPORTS.exists():
        return []
    files = sorted(IMPORTS.rglob("*"))
    texts = [vcard_text(p.read_bytes()) for p in files if p.suffix.lower() == ".vcf"]
    for p in files:
        if p.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(p) as z:
                    texts += [vcard_text(z.read(n)) for n in z.namelist() if n.lower().endswith(".vcf")]
            except zipfile.BadZipFile:
                pass
    return texts


class Resolver:
    """Maps a phone number or email address to a contact name. The phone's address book wins, then
    imported vCards, then the Mac's AddressBook."""

    def __init__(self):
        self.by_handle, self.by_tail = {}, {}
        try:
            phone_book = load_phone_contacts()
        except sqlite3.DatabaseError as e:  # damaged: names come from the others, and messages and calls are still read
            print(f"[contacts] the iPhone's address book can't be read ({e}); names come from the others")
            phone_book = []
        for c in phone_book:
            for _, v in c["phones"] + c["emails"]:
                self.add(v, c["name"])
        for text in imported_vcards():
            for d in parse_vcards(text):
                name = vcard_name(d)
                for v in d.get("TEL", []) + d.get("EMAIL", []):
                    self.add(v, name)
        for c in load_contacts():
            for _, v in c["phones"] + c["emails"]:
                self.add(v, c["name"])

    def add(self, handle, name):
        key = norm_handle(handle)
        if key and name:
            self.by_handle.setdefault(key, name)
            if tail(handle):
                self.by_tail.setdefault(tail(handle), {}).setdefault(key, name)  # each number that ends this way

    def name(self, handle):
        """The contact for a number or address: exactly, else by its last nine digits when only one number in your
        contacts ends with them (a UK and a German number that end alike are no one's)."""
        exact = self.by_handle.get(norm_handle(handle))
        if exact or not tail(handle):
            return exact
        same = self.by_tail.get(tail(handle), {})
        return next(iter(same.values())) if len(same) == 1 else None

    def label(self, handle):
        """Contact name if known, else the raw handle."""
        return self.name(handle) or handle


def write_contacts(w, contacts):
    for c in contacts:
        if (c["birthday"] or "").startswith("1604-"):  # Apple's year for a birthday saved without one
            c["birthday"] = "--" + c["birthday"][5:10]
        elif c["birthday"]:
            c["birthday"] = c["birthday"][:10]
        lines = [c["name"] or ""]
        for key in ("nickname", "org", "job", "department", "birthday", "note"):
            if c[key]:
                lines.append(f"{key}: {c[key]}")
        for key in ("phones", "emails", "social", "urls", "related"):
            for label, v in c[key]:
                lines.append(f"{key[:-1]}{f' ({label})' if label else ''}: {v}")
        for a in c["addresses"]:
            lines.append(f"address: {a}")
        w.add(id=c["uid"], kind="contact", ts=c["created"], title=c["name"],
              text="\n".join(lines), is_me=c["is_me"] or None,
              meta={k: c[k] for k in ("org", "birthday", "modified") if c[k]})


def mac_contacts():
    with Writer("contacts", AVENUE) as w:
        write_contacts(w, load_contacts(snapshot=True))


def iphone_contacts():
    if not PHONE_AB.exists():
        print(f"[iphone_contacts] no {PHONE_AB}")
        return
    # Read whole before writing: the source is rewritten each time, so a file that can't be read, or has no ABPerson
    # (made, never written to), leaves the contacts read before as they are.
    try:
        con = connect(PHONE_AB)
        try:
            readable = "ABPerson" in _tables(con)
        finally:
            con.close()
        found = load_phone_contacts() if readable else None
    except sqlite3.DatabaseError as e:
        print(f"[iphone_contacts] {PHONE_AB.name} can't be read ({e}); the contacts read before stay")
        return
    if found is None:
        print(f"[iphone_contacts] no contacts table in {PHONE_AB.name}; the contacts read before stay")
        return
    with Writer("iphone_contacts", PHONE_AVENUE, accumulate=False) as w:
        write_contacts(w, found)


def main():
    mac_contacts()
    iphone_contacts()


if __name__ == "__main__":
    main()
