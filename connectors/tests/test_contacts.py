"""The Mac's AddressBook files from different years: your own card under either name, fields a file doesn't have, and
one file that can't be read. After a tester's report and fix (benshi34/homecoming#1): an AddressBook last written around
2018 marks your card by a source, not a container, and the query for the newer name stopped Contacts, and Messages and
calls with it (they look names up here). Synthetic files in a made-up home folder only.

Run: python3 -m unittest discover -s connectors/tests -p 'test_*.py'
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CONNECTORS = Path(__file__).resolve().parents[1]

RECORD = ("Z_PK integer, Z_ENT integer, ZUNIQUEID text, ZFIRSTNAME text, ZMIDDLENAME text, ZLASTNAME text, ZNICKNAME text, "
          "ZORGANIZATION text, ZJOBTITLE text, ZDEPARTMENT text, ZBIRTHDAY real, ZCREATIONDATE real, ZMODIFICATIONDATE real")
MULTI = {"ZABCDPHONENUMBER": "ZFULLNUMBER", "ZABCDEMAILADDRESS": "ZADDRESS", "ZABCDSOCIALPROFILE": "ZUSERNAME",
         "ZABCDURLADDRESS": "ZURL", "ZABCDRELATEDNAME": "ZNAME"}


def address_book(path, me_column, record=RECORD, without=()):
    """An AddressBook-v22.abcddb with the tables load_contacts reads, your card marked by me_column (or not at all),
    and the tables in `without` left out, as an older file might."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("create table Z_PRIMARYKEY (Z_ENT integer, Z_NAME text)")
    con.execute("insert into Z_PRIMARYKEY values (1, 'ABCDContact')")
    con.execute(f"create table ZABCDRECORD ({record}{f', {me_column} integer' if me_column else ''})")
    for table, col in MULTI.items():
        if table not in without:
            con.execute(f"create table {table} (ZOWNER integer, ZLABEL text, {col} text)")
    if "ZABCDPOSTALADDRESS" not in without:
        con.execute("create table ZABCDPOSTALADDRESS (ZOWNER integer, ZSTREET text, ZCITY text, ZSTATE text, ZZIPCODE text, ZCOUNTRYNAME text)")
    if "ZABCDNOTE" not in without:
        con.execute("create table ZABCDNOTE (ZCONTACT integer, ZTEXT text)")
    return con


class Mac(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.home, self.corpus = Path(t.name) / "home", Path(t.name) / "corpus"
        self.corpus.mkdir(parents=True)
        self.ab = self.home / "Library/Application Support/AddressBook"

    def run_py(self, code):
        env = {**os.environ, "HOME": str(self.home), "CORPUS_DIR": str(self.corpus), "UMP_PHONE_REGION": "US"}
        r = subprocess.run([sys.executable, "-c", code], cwd=CONNECTORS, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def contacts(self):
        out = self.run_py("import contacts, json; print(json.dumps(contacts.load_contacts()))")
        lines = out.strip().splitlines()
        return {c["uid"]: c for c in json.loads(lines[-1])}, lines[:-1]


class LoadContactsTests(Mac):
    def test_your_card_under_either_name_and_a_file_without_one(self):
        newer = address_book(self.ab / "Sources/new/AddressBook-v22.abcddb", "ZCONTAINERWHERECONTACTISME")
        newer.execute("insert into ZABCDRECORD (Z_PK, Z_ENT, ZUNIQUEID, ZFIRSTNAME, ZCONTAINERWHERECONTACTISME) values (1, 1, 'ada', 'Ada', 1)")
        newer.execute("insert into ZABCDPHONENUMBER values (1, '_$!<Mobile>!$_', '4155550100')")
        newer.commit()
        older = address_book(self.ab / "Sources/old/AddressBook-v22.abcddb", "ZSOURCEWHERECONTACTISME")
        older.execute("insert into ZABCDRECORD (Z_PK, Z_ENT, ZUNIQUEID, ZFIRSTNAME, ZSOURCEWHERECONTACTISME) values (1, 1, 'grace', 'Grace', 1)")
        older.execute("insert into ZABCDRECORD (Z_PK, Z_ENT, ZUNIQUEID, ZFIRSTNAME, ZSOURCEWHERECONTACTISME) values (2, 1, 'bob', 'Bob', 0)")
        older.commit()
        plain = address_book(self.ab / "AddressBook-v22.abcddb", None)
        plain.execute("insert into ZABCDRECORD (Z_PK, Z_ENT, ZUNIQUEID, ZFIRSTNAME) values (1, 1, 'lin', 'Lin')")
        plain.commit()
        found, said = self.contacts()
        self.assertEqual(set(found), {"ada", "grace", "bob", "lin"})
        self.assertEqual({u: c["is_me"] for u, c in found.items()}, {"ada": True, "grace": True, "bob": False, "lin": False})
        self.assertEqual(found["ada"]["phones"], [["Mobile", "4155550100"]])
        self.assertEqual(said, [], "nothing to say")

    def test_an_older_file_without_some_fields_or_tables(self):
        record = ("Z_PK integer, Z_ENT integer, ZUNIQUEID text, ZFIRSTNAME text, ZLASTNAME text, ZORGANIZATION text, "
                  "ZCREATIONDATE real, ZMODIFICATIONDATE real")
        old = address_book(self.ab / "Sources/old/AddressBook-v22.abcddb", "ZSOURCEWHERECONTACTISME", record=record,
                           without=("ZABCDSOCIALPROFILE", "ZABCDRELATEDNAME", "ZABCDNOTE"))
        old.execute("insert into ZABCDRECORD (Z_PK, Z_ENT, ZUNIQUEID, ZFIRSTNAME, ZLASTNAME, ZSOURCEWHERECONTACTISME) values (1, 1, 'grace', 'Grace', 'Hopper', 0)")
        old.execute("insert into ZABCDEMAILADDRESS values (1, '_$!<Work>!$_', 'grace@navy.example')")
        old.execute("insert into ZABCDPOSTALADDRESS values (1, '1 Main St', 'Arlington', 'VA', '22201', NULL)")
        old.commit()
        found, said = self.contacts()
        g = found["grace"]
        self.assertEqual((g["name"], g["emails"], g["addresses"]), ("Grace Hopper", [["Work", "grace@navy.example"]], ["1 Main St, Arlington, VA, 22201"]))
        self.assertEqual((g["nickname"], g["department"], g["social"], g["note"]), (None, None, [], None), "what it doesn't have: empty")
        self.assertEqual(said, [])

    def test_a_file_it_cant_read_is_left_out_and_the_rest_are_read(self):
        good = address_book(self.ab / "Sources/good/AddressBook-v22.abcddb", "ZCONTAINERWHERECONTACTISME")
        good.execute("insert into ZABCDRECORD (Z_PK, Z_ENT, ZUNIQUEID, ZFIRSTNAME) values (1, 1, 'ada', 'Ada')")
        good.commit()
        odd = self.ab / "Sources/odd/AddressBook-v22.abcddb"
        odd.parent.mkdir(parents=True)
        sqlite3.connect(odd).execute("create table something_else (x integer)").connection.commit()
        found, said = self.contacts()
        self.assertEqual(set(found), {"ada"})
        self.assertEqual(len(said), 1)
        self.assertRegex(said[0], r"^\[contacts\] couldn't read the address book in odd \(.*\); the others are read$")


class ResolverTests(Mac):
    def test_messages_and_calls_find_names_in_an_older_file(self):
        old = address_book(self.ab / "Sources/old/AddressBook-v22.abcddb", "ZSOURCEWHERECONTACTISME")
        old.execute("insert into ZABCDRECORD (Z_PK, Z_ENT, ZUNIQUEID, ZFIRSTNAME, ZLASTNAME, ZSOURCEWHERECONTACTISME) values (1, 1, 'grace', 'Grace', 'Hopper', 0)")
        old.execute("insert into ZABCDPHONENUMBER values (1, '_$!<Mobile>!$_', '(415) 555-0100')")
        old.commit()
        out = self.run_py("import contacts; print(contacts.Resolver().name('+14155550100'))")
        self.assertEqual(out.strip().splitlines()[-1], "Grace Hopper")


if __name__ == "__main__":
    unittest.main()
