"""Apple Contacts: the Mac's AddressBook (source contacts) and the iPhone's, from the decrypted backup
(source iphone_contacts). Also provides Resolver: phone/email -> contact name, used by the messaging, call
and mail connectors to join everything by person. The Resolver prefers the phone's address book, then vCards
dropped into corpus/imports/ (an iPhone export, Takeout Contacts), then the Mac's, which can lag far behind."""

import collections
import re
import zipfile

from common import CORPUS, LIB, Writer, connect, from_apple, phone, snapshot_sqlite

AB = LIB / "Application Support/AddressBook"
IMPORTS = CORPUS / "imports"
AVENUE = ("Local SQLite: ~/Library/Application Support/AddressBook/Sources/*/AddressBook-v22.abcddb "
          "(one DB per account). Needs Full Disk Access.")
PHONE_AB = phone("HomeDomain", "Library/AddressBook/AddressBook.sqlitedb")
PHONE_AVENUE = "iPhone backup (connectors/iphone_backup.py) → HomeDomain/Library/AddressBook/AddressBook.sqlitedb"
# ABMultiValue.property in the phone's AddressBook.sqlitedb
PHONE_PROPS = {3: "phones", 4: "emails", 5: "addresses", 13: "social", 22: "urls", 23: "related", 46: "social"}


def norm_phone(s):
    d = re.sub(r"\D", "", s or "")
    return d[-10:] if len(d) >= 10 else d or None


def norm_handle(s):
    s = (s or "").strip()
    if "@" in s:
        return s.lower()
    return norm_phone(s)


def _db_paths():
    return sorted(AB.glob("Sources/*/AddressBook-v22.abcddb")) + [AB / "AddressBook-v22.abcddb"]


def load_contacts(snapshot=False):
    contacts = []
    for i, path in enumerate(_db_paths()):
        if not path.exists():
            continue
        if snapshot:
            path = snapshot_sqlite(path, f"contacts/{i}_{path.parent.name}.abcddb")
        con = connect(path)
        multi = {}
        for table, col in (("ZABCDPHONENUMBER", "ZFULLNUMBER"), ("ZABCDEMAILADDRESS", "ZADDRESS"),
                           ("ZABCDSOCIALPROFILE", "ZUSERNAME"), ("ZABCDURLADDRESS", "ZURL"),
                           ("ZABCDRELATEDNAME", "ZNAME")):
            for r in con.execute(f"select ZOWNER, ZLABEL, {col} v from {table} where {col} is not null"):
                label = (r["ZLABEL"] or "").strip("_$!<>") or None
                multi.setdefault(r["ZOWNER"], {}).setdefault(table, []).append((label, r["v"]))
        addrs = {}
        for r in con.execute("select * from ZABCDPOSTALADDRESS"):
            parts = [r["ZSTREET"], r["ZCITY"], r["ZSTATE"], r["ZZIPCODE"], r["ZCOUNTRYNAME"]]
            addrs.setdefault(r["ZOWNER"], []).append(", ".join(p for p in parts if p))
        notes = {r["ZCONTACT"]: r["ZTEXT"] for r in con.execute("select ZCONTACT, ZTEXT from ZABCDNOTE")}
        rows = con.execute("""select Z_PK, ZUNIQUEID, ZFIRSTNAME, ZMIDDLENAME, ZLASTNAME, ZNICKNAME,
                                     ZORGANIZATION, ZJOBTITLE, ZDEPARTMENT, ZBIRTHDAY, ZCREATIONDATE,
                                     ZMODIFICATIONDATE, ZCONTAINERWHERECONTACTISME
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
                "modified": from_apple(r["ZMODIFICATIONDATE"]), "is_me": bool(r["ZCONTAINERWHERECONTACTISME"]),
                "phones": m.get("ZABCDPHONENUMBER", []), "emails": m.get("ZABCDEMAILADDRESS", []),
                "social": m.get("ZABCDSOCIALPROFILE", []), "urls": m.get("ZABCDURLADDRESS", []),
                "related": m.get("ZABCDRELATEDNAME", []), "addresses": addrs.get(r["Z_PK"], []),
                "note": notes.get(r["Z_PK"]),
            })
        con.close()
    return contacts


def load_phone_contacts():
    """The iPhone's AddressBook.sqlitedb (older ABPerson / ABMultiValue schema), same dicts as load_contacts."""
    if not PHONE_AB.exists():
        return []
    con = connect(PHONE_AB)
    labels = {r[0]: r[1] for r in con.execute("select ROWID, value from ABMultiValueLabel")}
    keys = {r[0]: r[1] for r in con.execute("select ROWID, value from ABMultiValueEntryKey")}
    entries = {}
    for r in con.execute("select parent_id, key, value from ABMultiValueEntry"):
        entries.setdefault(r["parent_id"], {})[keys.get(r["key"])] = r["value"]
    multi = {}
    for r in con.execute("select UID, record_id, property, label, value from ABMultiValue"):
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
    for r in con.execute("""select ROWID, guid, First, Middle, Last, Nickname, Organization, JobTitle, Department,
                                   Birthday, CreationDate, ModificationDate, Note from ABPerson"""):
        name = " ".join(x for x in (r["First"], r["Middle"], r["Last"]) if x) or r["Nickname"] or r["Organization"]
        m = multi.get(r["ROWID"], {})
        if not name and not m:
            continue
        bday = r["Birthday"]
        out.append({
            "uid": r["guid"] or f"row{r['ROWID']}", "name": name, "nickname": r["Nickname"], "org": r["Organization"],
            "job": r["JobTitle"], "department": r["Department"],
            "birthday": from_apple(float(bday)) if bday not in (None, "") else None,
            "created": from_apple(r["CreationDate"]), "modified": from_apple(r["ModificationDate"]), "is_me": False,
            "phones": m.get("phones", []), "emails": m.get("emails", []), "social": m.get("social", []),
            "urls": m.get("urls", []), "related": m.get("related", []), "addresses": m.get("addresses", []),
            "note": r["Note"],
        })
    con.close()
    return out


def parse_vcards(text):
    """vCard 3/4 text -> one {FIELD: [values]} dict per card (FN, N, TEL, EMAIL, ORG, BDAY, ...)."""
    body = re.sub(r"\r?\n[ \t]", "", text)  # unfold continuation lines
    cards = []
    for block in re.findall(r"BEGIN:VCARD\r?\n(.*?)END:VCARD", body, re.S):
        d = collections.defaultdict(list)
        for line in block.splitlines():
            if ":" in line:
                key, val = line.split(":", 1)
                d[key.split(";")[0].split(".")[-1].upper()].append(
                    val.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";"))
        cards.append(d)
    return cards


def vcard_name(d):
    return (d.get("FN") or [" ".join(reversed((d.get("N") or [""])[0].split(";")[:2])).strip()])[0].strip()


def imported_vcards():
    """Text of every .vcf in corpus/imports/: loose files first (e.g. an AirDropped iPhone export), then inside zips."""
    if not IMPORTS.exists():
        return []
    files = sorted(IMPORTS.rglob("*"))
    texts = [p.read_text(errors="replace") for p in files if p.suffix.lower() == ".vcf"]
    for p in files:
        if p.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(p) as z:
                    texts += [z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.lower().endswith(".vcf")]
            except zipfile.BadZipFile:
                pass
    return texts


class Resolver:
    """Maps a phone number or email address to a contact name. The phone's address book wins, then
    imported vCards, then the Mac's AddressBook."""

    def __init__(self):
        self.by_handle = {}
        for c in load_phone_contacts():
            for _, v in c["phones"] + c["emails"]:
                key = norm_handle(v)
                if key and c["name"]:
                    self.by_handle.setdefault(key, c["name"])
        for text in imported_vcards():
            for d in parse_vcards(text):
                name = vcard_name(d)
                for v in d.get("TEL", []) + d.get("EMAIL", []):
                    key = norm_handle(v)
                    if key and name:
                        self.by_handle.setdefault(key, name)
        for c in load_contacts():
            for _, v in c["phones"] + c["emails"]:
                key = norm_handle(v)
                if key and c["name"]:
                    self.by_handle.setdefault(key, c["name"])

    def name(self, handle):
        return self.by_handle.get(norm_handle(handle))

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
    with Writer("iphone_contacts", PHONE_AVENUE, accumulate=False) as w:
        write_contacts(w, load_phone_contacts())


def main():
    mac_contacts()
    iphone_contacts()


if __name__ == "__main__":
    main()
