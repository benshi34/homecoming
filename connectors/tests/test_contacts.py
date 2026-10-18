"""Mac AddressBook files from different years use different names for the "me" card.

Run: python3 -m unittest connectors.tests.test_contacts
"""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import contacts


def address_book(path, me_column):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    me = f", {me_column} integer" if me_column else ""
    con.executescript(f"""
        create table Z_PRIMARYKEY (Z_ENT integer, Z_NAME text);
        insert into Z_PRIMARYKEY values (1, 'ABCDContact');
        create table ZABCDRECORD (
            Z_PK integer, Z_ENT integer, ZUNIQUEID text, ZFIRSTNAME text, ZMIDDLENAME text, ZLASTNAME text,
            ZNICKNAME text, ZORGANIZATION text, ZJOBTITLE text, ZDEPARTMENT text, ZBIRTHDAY real,
            ZCREATIONDATE real, ZMODIFICATIONDATE real{me});
        create table ZABCDPHONENUMBER (ZOWNER integer, ZLABEL text, ZFULLNUMBER text);
        create table ZABCDEMAILADDRESS (ZOWNER integer, ZLABEL text, ZADDRESS text);
        create table ZABCDSOCIALPROFILE (ZOWNER integer, ZLABEL text, ZUSERNAME text);
        create table ZABCDURLADDRESS (ZOWNER integer, ZLABEL text, ZURL text);
        create table ZABCDRELATEDNAME (ZOWNER integer, ZLABEL text, ZNAME text);
        create table ZABCDPOSTALADDRESS (ZOWNER integer, ZSTREET text, ZCITY text, ZSTATE text, ZZIPCODE text, ZCOUNTRYNAME text);
        create table ZABCDNOTE (ZCONTACT integer, ZTEXT text);
    """)
    return con


class LoadContactsTests(unittest.TestCase):
    def test_both_address_book_schemas(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            newer = address_book(root / "Sources" / "new" / "AddressBook-v22.abcddb", "ZCONTAINERWHERECONTACTISME")
            newer.execute("insert into ZABCDRECORD (Z_PK, Z_ENT, ZUNIQUEID, ZFIRSTNAME, ZCONTAINERWHERECONTACTISME) values (1, 1, 'ada', 'Ada', 1)")
            newer.execute("insert into ZABCDPHONENUMBER values (1, '_$!<Mobile>!$_', '4155550100')")
            newer.commit()
            newer.close()
            older = address_book(root / "Sources" / "old" / "AddressBook-v22.abcddb", "ZSOURCEWHERECONTACTISME")
            older.execute("insert into ZABCDRECORD (Z_PK, Z_ENT, ZUNIQUEID, ZFIRSTNAME, ZSOURCEWHERECONTACTISME) values (1, 1, 'grace', 'Grace', 1)")
            older.execute("insert into ZABCDRECORD (Z_PK, Z_ENT, ZUNIQUEID, ZFIRSTNAME, ZSOURCEWHERECONTACTISME) values (2, 1, 'bob', 'Bob', 0)")
            older.commit()
            older.close()
            plain = address_book(root / "AddressBook-v22.abcddb", None)
            plain.execute("insert into ZABCDRECORD (Z_PK, Z_ENT, ZUNIQUEID, ZFIRSTNAME) values (1, 1, 'lin', 'Lin')")
            plain.commit()
            plain.close()
            with mock.patch.object(contacts, "AB", root):
                found = {c["uid"]: c for c in contacts.load_contacts()}
        self.assertEqual(set(found), {"ada", "grace", "bob", "lin"})
        self.assertTrue(found["ada"]["is_me"])
        self.assertTrue(found["grace"]["is_me"])
        self.assertFalse(found["bob"]["is_me"])
        self.assertFalse(found["lin"]["is_me"])
        self.assertEqual(found["ada"]["phones"], [("Mobile", "4155550100")])


if __name__ == "__main__":
    unittest.main()
