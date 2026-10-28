"""Office comments and tracked changes, from minimal in-memory packages.

Run: cd connectors && python3 -m unittest tests.test_office_notes
"""

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

CONNECTORS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONNECTORS))
import office_notes  # noqa: E402


def package(path, parts):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return path


class OfficeNotesTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def file(self, name, parts):
        return package(self.root / name, parts)

    def test_docx_comments_replies_anchor_resolution_and_changes(self):
        path = self.file("thread.docx", {
            "word/comments.xml": '''
                <w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
                  xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml">
                  <w:comment w:id="0" w:author="Ada" w:initials="AL" w:date="2026-01-02T03:04:05+02:00">
                    <w:p w14:paraId="p0"><w:r><w:t>Root 🌱</w:t></w:r></w:p>
                  </w:comment>
                  <w:comment w:id="1" w:author="Bea" w:date="2026-01-02T02:05:05Z">
                    <w:p w14:paraId="p1"><w:r><w:t>Reply one</w:t></w:r></w:p>
                  </w:comment>
                  <w:comment w:id="2" w:author="Cé" w:date="2026-01-02T02:06:05Z">
                    <w:p w14:paraId="p2"><w:r><w:t>Reply two</w:t></w:r></w:p>
                  </w:comment>
                </w:comments>
            ''',
            "word/commentsExtended.xml": '''
                <w15:commentsEx xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml">
                  <w15:commentEx w15:paraId="p0" w15:done="1"/>
                  <w15:commentEx w15:paraId="p1" w15:paraIdParent="p0"/>
                  <w15:commentEx w15:paraId="p2" w15:paraIdParent="p0"/>
                </w15:commentsEx>
            ''',
            "word/document.xml": '''
                <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                  <w:body><w:p>
                    <w:commentRangeStart w:id="0"/><w:r><w:t>anchor 🌍</w:t></w:r><w:commentRangeEnd w:id="0"/>
                    <w:ins w:author="Eve" w:date="2026-01-03T00:00:00-05:00"><w:r><w:t>new</w:t></w:r></w:ins>
                    <w:del w:author="Finn" w:date="2026-01-03T00:00:01Z"><w:r><w:delText>old</w:delText></w:r></w:del>
                  </w:p></w:body>
                </w:document>
            ''',
        })
        got = office_notes.notes(path)
        self.assertIsNotNone(got)
        root = got["comments"][0]
        self.assertEqual((root["id"], root["author"], root["initials"], root["text"]), ("0", "Ada", "AL", "Root 🌱"))
        self.assertEqual(root["anchor"], "anchor 🌍")
        self.assertIs(root["resolved"], True)
        self.assertEqual([(r["author"], r["text"]) for r in root["replies"]], [("Bea", "Reply one"), ("Cé", "Reply two")])
        self.assertEqual(got["changes"], [
            {"kind": "insert", "author": "Eve", "date": "2026-01-03T05:00:00Z", "text": "new"},
            {"kind": "delete", "author": "Finn", "date": "2026-01-03T00:00:01Z", "text": "old"},
        ])

    def test_docx_google_flat_comments_and_bad_optional_part(self):
        flat = self.file("flat.docx", {
            "word/comments.xml": '''<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:comment w:id="a" w:author="Ada"><w:p><w:r><w:t>Flat ✓</w:t></w:r></w:p></w:comment>
              <w:comment w:id="b" w:author="Bea"><w:p><w:r><w:t>Another</w:t></w:r></w:p></w:comment>
            </w:comments>''',
        })
        got = office_notes.notes(flat)
        self.assertEqual([c["id"] for c in got["comments"]], ["a", "b"])
        self.assertTrue(all(c["resolved"] is None and c["replies"] == [] for c in got["comments"]))

        damaged = self.file("damaged.docx", {
            "word/comments.xml": b"<broken",
            "word/document.xml": '''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body><w:p><w:ins w:author="Ada"><w:r><w:t>kept</w:t></w:r></w:ins></w:p></w:body></w:document>''',
        })
        self.assertEqual(office_notes.notes(damaged)["changes"][0]["text"], "kept")

    def test_xlsx_legacy_and_threaded_comments(self):
        path = self.file("sheet.xlsx", {
            "xl/workbook.xml": '''<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
              xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
              <sheets><sheet name="Sheet One" sheetId="1" r:id="rId1"/></sheets></workbook>''',
            "xl/_rels/workbook.xml.rels": '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
              <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>''',
            "xl/worksheets/sheet1.xml": "<worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\"/>",
            "xl/worksheets/_rels/sheet1.xml.rels": '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
              <Relationship Id="c" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="../comments1.xml"/>
              <Relationship Id="t" Type="http://schemas.microsoft.com/office/2017/10/relationships/threadedComment" Target="../threadedComments/threadedComment1.xml"/></Relationships>''',
            "xl/comments1.xml": '''<comments xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
              <authors><author>Ada</author></authors><commentList><comment ref="B2" authorId="0"><text><r><t>Legacy 🧪</t></r></text></comment></commentList></comments>''',
            "xl/persons/person.xml": '''<personList xmlns="http://schemas.microsoft.com/office/spreadsheetml/2018/threadedcomments">
              <person id="p1" displayName="Ada"/><person id="p2" displayName="Bea"/></personList>''',
            "xl/threadedComments/threadedComment1.xml": '''<ThreadedComments xmlns="http://schemas.microsoft.com/office/spreadsheetml/2018/threadedcomments">
              <threadedComment id="t1" ref="B2" personId="p1" dT="2026-02-03T04:05:06-05:00" done="1"><text>Thread 🌈</text></threadedComment>
              <threadedComment id="t2" ref="B2" personId="p2" parentId="t1" dT="2026-02-03T09:06:06Z"><text>Reply</text></threadedComment>
            </ThreadedComments>''',
        })
        got = office_notes.notes(path)
        self.assertEqual(len(got["comments"]), 2)
        legacy, thread = got["comments"]
        self.assertEqual((legacy["id"], legacy["anchor"], legacy["text"]), ("B2", "Sheet One!B2", "Legacy 🧪"))
        self.assertEqual((thread["author"], thread["resolved"], thread["anchor"]), ("Ada", True, "Sheet One!B2"))
        self.assertEqual(thread["replies"][0]["text"], "Reply")

    def test_xlsx_bad_part_and_no_comments(self):
        damaged = self.file("bad.xlsx", {
            "xl/comments1.xml": b"not xml",
            "xl/threadedComments/threadedComment1.xml": '''<ThreadedComments xmlns="http://schemas.microsoft.com/office/spreadsheetml/2018/threadedcomments">
              <threadedComment id="t" ref="A1" personId="p"/></ThreadedComments>''',
            "xl/persons/person.xml": '<personList><person id="p" displayName="Ada"/></personList>',
        })
        self.assertEqual(office_notes.notes(damaged)["comments"][0]["id"], "t")
        empty = self.file("empty.xlsx", {"xl/workbook.xml": "<workbook/>"})
        self.assertIsNone(office_notes.notes(empty))

    def test_pptx_legacy_modern_replies_resolution_and_anchor(self):
        path = self.file("slides.pptx", {
            "ppt/slides/_rels/slide1.xml.rels": '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
              <Relationship Id="c" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="../comments/comment1.xml"/>
              <Relationship Id="m" Type="http://schemas.microsoft.com/office/2018/08/relationships/modernComment" Target="../comments/modernComment_1.xml"/></Relationships>''',
            "ppt/commentAuthors.xml": '''<p:cmAuthorLst xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
              <p:cmAuthor id="1" name="Ada" initials="AL"/></p:cmAuthorLst>''',
            "ppt/authors.xml": '''<p188:authors xmlns:p188="http://schemas.microsoft.com/office/powerpoint/2018/moderncomments">
              <p188:author id="a1" name="Bea" initials="BR"/><p188:author id="a2" name="Cé"/></p188:authors>''',
            "ppt/comments/comment1.xml": '''<p:cmLst xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
              xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cm idx="7" authorId="1" dt="2026-03-04T01:02:03Z"><p:text><a:p><a:r><a:t>Legacy 🖼️</a:t></a:r></a:p></p:text></p:cm></p:cmLst>''',
            "ppt/comments/modernComment_1.xml": '''<p188:cmLst xmlns:p188="http://schemas.microsoft.com/office/powerpoint/2018/moderncomments"
              xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p188:cm id="m1" authorId="a1" created="2026-03-04T02:02:03-02:00" status="resolved"><p188:text><a:p><a:r><a:t>Modern 🌟</a:t></a:r></a:p></p188:text><p188:replyLst><p188:reply id="r1" authorId="a2" created="2026-03-04T04:03:03Z"><p188:text><a:p><a:r><a:t>Reply</a:t></a:r></a:p></p188:text></p188:reply></p188:replyLst></p188:cm></p188:cmLst>''',
        })
        got = office_notes.notes(path)
        legacy, modern = got["comments"]
        self.assertEqual((legacy["id"], legacy["author"], legacy["anchor"], legacy["resolved"]), ("7", "Ada", "slide 1", None))
        self.assertEqual((modern["author"], modern["text"], modern["resolved"], modern["anchor"]), ("Bea", "Modern 🌟", True, "slide 1"))
        self.assertEqual((modern["replies"][0]["author"], modern["replies"][0]["text"]), ("Cé", "Reply"))

        damaged = self.file("damaged.pptx", {
            "ppt/comments/comment1.xml": b"<broken",
            "ppt/comments/modernComment_1.xml": '''<p188:cmLst xmlns:p188="http://schemas.microsoft.com/office/powerpoint/2018/moderncomments"><p188:cm id="m" authorId="a"><p188:text>kept</p188:text></p188:cm></p188:cmLst>''',
            "ppt/authors.xml": '<p188:authors xmlns:p188="http://schemas.microsoft.com/office/powerpoint/2018/moderncomments"><p188:author id="a" name="Ada"/></p188:authors>',
        })
        self.assertEqual(office_notes.notes(damaged)["comments"][0]["text"], "kept")
        self.assertIsNone(office_notes.notes(self.file("empty.pptx", {"ppt/comments/comment1.xml": "<p:cmLst xmlns:p=\"urn:p\"/>"})))

    def odf_parts(self):
        return {
            "content.xml": '''<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
              xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:dc="http://purl.org/dc/elements/1.1/"
              xmlns:loext="urn:org:documentfoundation:names:experimental:office:xmlns:loext:1.0">
              <office:body><office:text><text:p><office:annotation office:name="n1" loext:resolved="true"><dc:creator>Ada</dc:creator><dc:date>2026-04-05T01:02:03-04:00</dc:date><text:p>Note 📝</text:p></office:annotation>Marked 🌻<office:annotation-end office:name="n1"/></text:p>
                <office:annotation office:name="n2" loext:parent-name="n1"><dc:creator>Bea</dc:creator><text:p>Reply</text:p></office:annotation>
                <office:tracked-changes><text:changed-region text:id="i1"><text:insertion><office:change-info><dc:creator>Cé</dc:creator><dc:date>2026-04-05T05:00:00Z</dc:date></office:change-info></text:insertion></text:changed-region>
                  <text:changed-region text:id="d1"><text:deletion><office:change-info><dc:creator>Dan</dc:creator><dc:date>2026-04-05T06:00:00Z</dc:date></office:change-info><text:p>gone ❌</text:p></text:deletion></text:changed-region></office:tracked-changes>
                <text:p>before <text:change-start text:change-id="i1"/>added ✅<text:change-end text:change-id="i1"/></text:p>
              </office:text></office:body></office:document-content>'''
        }

    def test_odf_comments_replies_anchor_resolution_and_changes_all_extensions(self):
        for extension in ("odt", "ods", "odp"):
            with self.subTest(extension=extension):
                got = office_notes.notes(self.file(f"notes.{extension}", self.odf_parts()))
                root = got["comments"][0]
                self.assertEqual((root["author"], root["text"], root["resolved"], root["anchor"]), ("Ada", "Note 📝", True, "Marked 🌻"))
                self.assertEqual(root["replies"][0]["text"], "Reply")
                self.assertEqual({c["kind"] for c in got["changes"]}, {"insert", "delete"})
                self.assertIn("added ✅", next(c["text"] for c in got["changes"] if c["kind"] == "insert"))

    def test_odf_bad_content_and_no_comments(self):
        self.assertIsNone(office_notes.notes(self.file("bad.odt", {"content.xml": b"<broken"})))
        self.assertIsNone(office_notes.notes(self.file("empty.odt", {"mimetype": "application/vnd.oasis.opendocument.text"})))

    def test_bad_file_and_unsupported_extension_never_raise(self):
        bad = self.root / "bad.docx"
        bad.write_bytes(b"not a zip")
        self.assertIsNone(office_notes.notes(bad))
        txt = self.root / "notes.txt"
        txt.write_text("hello")
        self.assertIsNone(office_notes.notes(txt))


if __name__ == "__main__":
    unittest.main()
