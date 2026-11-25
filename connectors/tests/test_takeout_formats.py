"""Google Takeout as it comes: every product in the shapes Google has written it, in English and in other languages
(Takeout names its folders and files in the account's language), My Activity and YouTube history as JSON and as the
default HTML, Mail's mbox with what real mail has in it, the three generations of Location History, Keep, Calendar,
Contacts, Tasks, Google Chat and Fit, and exports in zip or .tgz parts, unzipped by hand, or cut short. Exports are made
up here; the importer runs as the app runs it.

Run: python3 -m unittest discover -s connectors/tests -p 'test_takeout_formats.py'
"""
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

CONNECTORS = Path(__file__).resolve().parents[1]
TK = "takeout-20261001T000000Z/Takeout/"  # where the app puts an unzipped Takeout's files


def data(x):
    return x if isinstance(x, (str, bytes)) else json.dumps(x)


class Base(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.home, self.corpus = Path(t.name) / "home", Path(t.name) / "corpus"
        self.imports = self.corpus / "imports"
        self.home.mkdir()
        self.imports.mkdir(parents=True)
        (self.corpus / "identity.json").write_text(json.dumps({"names": ["Ada Lovelace"], "emails": ["ada@example.com"], "usernames": []}))

    def files(self, files, root=TK):
        for name, x in files.items():
            p = self.imports / root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            x = data(x)
            p.write_bytes(x if isinstance(x, bytes) else x.encode())

    def zip(self, rel, files):
        p = self.imports / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(p, "w") as z:
            for name, x in files.items():
                z.writestr(name, data(x))
        return p

    def tgz(self, rel, files):
        p = self.imports / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(p, "w:gz") as t:
            for name, x in files.items():
                x = data(x)
                b = x if isinstance(x, bytes) else x.encode()
                info = tarfile.TarInfo(name)
                info.size = len(b)
                t.addfile(info, io.BytesIO(b))
        return p

    def run_import(self):
        # Times written without a zone are this Mac's clock: one zone for every run of the tests.
        env = {**os.environ, "HOME": str(self.home), "CORPUS_DIR": str(self.corpus), "TZ": "America/New_York"}
        r = subprocess.run([sys.executable, str(CONNECTORS / "imports.py")], cwd=CONNECTORS, env=env,
                           capture_output=True, text=True, timeout=300)
        self.out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, self.out[-3000:])
        self.recs = {f.stem: [json.loads(line) for line in f.read_text().splitlines()]
                     for f in (self.corpus / "normalized").glob("*.jsonl")}
        self.manifest = json.loads((self.corpus / "manifest.json").read_text())
        return self.recs

    def of(self, source, kind=None):
        return [r for r in self.recs.get(source, []) if kind is None or r["kind"] == kind]

    def unclaimed(self):
        """The export files no parser read, by name."""
        return {x for g in self.manifest.get("_imports_unclaimed", []) for x in g["examples"]}


# ---------------------------------------------------------------- Google AI Studio and small Takeout gaps

class AIStudioTests(Base):
    def test_ai_studio_chats_builds_applets_and_attachments(self):
        inner = io.BytesIO()
        with zipfile.ZipFile(inner, "w") as z:
            z.writestr("metadata.json", json.dumps({"name": "Tide app", "description": "A small tide dashboard."}))
            z.writestr("index.tsx", "export default function App() { return null }")
            z.writestr("README.md", "Tide dashboard")
        odd = json.dumps([{"id": "m1", "author": "user", "payload": {"type": "text", "text": "decoded prompt"}},
                          {"id": "m2", "author": "model", "payload": {"type": "text", "text": "decoded answer"}}])
        self.zip("ai-studio.zip", {
            TK + "Drive/Google AI Studio/First chat": {
                "runSettings": {"model": "models.gemini-test", "temperature": 0.2},
                "systemInstruction": {"parts": [{"text": "Use short answers."}]},
                "citations": [{"uri": "https://example.test/source"}],
                "chunkedPrompt": {"chunks": [
                    {"role": "user", "text": "show the tide", "driveImage": {"name": "diagram.png"}},
                    {"role": "model", "text": "private thought", "isThought": True},
                    {"role": "model", "text": "Here is the tide."},
                ]},
            },
            TK + "Drive/Google AI Studio/Second chat": {"chunkedPrompt": {"chunks": [{"role": "user", "text": odd}]}},
            TK + "Drive/Google AI Studio/applet_access_history.json": {
                "applets": [{"id": "app-1", "name": "Canvas", "firstAccessTime": "2026-10-01T10:00:00Z",
                              "lastAccessTime": "2026-10-02T11:00:00Z"}]},
            TK + "Drive/Google AI Studio/diagram.png": b"fake image",
            TK + "Drive/Google AI Studio/notes.pdf": b"%PDF-1.4 fake attachment",
            TK + "Drive/Google AI Studio/Build.zip": inner.getvalue(),
        })
        self.run_import()
        turns = self.of("ai_studio", "ai_turn")
        self.assertEqual(len(turns), 4)
        first = next(r for r in turns if r["thread_name"] == "First chat" and r["is_me"])
        self.assertIn("show the tide", first["text"])
        self.assertEqual(first["meta"]["model"], "models.gemini-test")
        self.assertEqual(first["meta"]["system_instruction"], "Use short answers.")
        self.assertEqual(first["meta"]["citations"][0]["uri"], "https://example.test/source")
        self.assertTrue(first["meta"]["attachments"][0]["path"].endswith("diagram.png"))
        self.assertFalse(any("private thought" in r["text"] for r in turns))
        self.assertTrue(any("decoded prompt" in r["text"] and r["is_me"] for r in turns))
        [project] = self.of("ai_studio", "project")
        self.assertEqual((project["title"], project["meta"]["build"]), ("Tide app", True))
        self.assertEqual(len(self.of("ai_studio", "activity")), 1)
        self.assertTrue(any(r["title"] == "notes.pdf" for r in self.of("imported_documents")))
        self.assertEqual(self.unclaimed(), set())

    def test_a_build_app_saved_without_zip_on_its_name(self):
        # How real Takeouts carry a Build app: a zip named for the app, no extension, beside the chats
        inner = io.BytesIO()
        with zipfile.ZipFile(inner, "w") as z:
            z.writestr("metadata.json", json.dumps({"name": "Tide app", "description": "A small tide dashboard."}))
            z.writestr("index.tsx", "export default function App() { return null }")
        self.zip("ai-studio.zip", {TK + "Drive/Google AI Studio/Tide Dashboard": inner.getvalue()})
        self.run_import()
        [project] = self.of("ai_studio", "project")
        self.assertEqual(project["title"], "Tide app")
        self.assertIn("index.tsx", project["text"])
        self.assertEqual(self.unclaimed(), set())

    def test_a_build_mode_chat_with_a_title_cut_short(self):
        # Google cuts a long title to end in ".._"; Build-mode chats are one chunk holding the messages as a JSON string
        msgs = [{"id": "1", "author": "user", "payload": {"type": "text", "text": "make a tide app"},
                 "createdTimestamp": {"seconds": 1767225600}},
                {"id": "2", "author": "model", "payload": {"type": "thinking", "text": "weighing layouts"},
                 "createdTimestamp": {"seconds": 1767225601}},
                {"id": "3", "author": "model", "payload": {"type": "text", "text": "Here is a tide app."},
                 "createdTimestamp": {"seconds": 1767225660}}]
        self.zip("ai-studio.zip", {TK + "Drive/Google AI Studio/make a tide app that shows the next high tide for a.._":
                                   {"chunkedPrompt": {"chunks": [{"role": "user", "text": json.dumps(msgs)}]}}})
        self.run_import()
        turns = sorted(self.of("ai_studio", "ai_turn"), key=lambda r: r["ts"])
        self.assertEqual([r["text"] for r in turns], ["make a tide app", "Here is a tide app."])
        self.assertTrue(turns[0]["ts"].startswith("2026-01-01T00:00:00"))
        self.assertEqual(self.unclaimed(), set())

    def test_drive_notebooks_without_ipynb_spreadsheets_and_empty_files(self):
        nb = {"nbformat": 4, "nbformat_minor": 0, "metadata": {}, "cells": [{"cell_type": "code", "source": ["import tides\n"]}]}
        sheet = io.BytesIO()
        with zipfile.ZipFile(sheet, "w") as z:
            z.writestr("[Content_Types].xml", "<Types/>")
            z.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheets><sheet name="Budget" sheetId="1"/></sheets></workbook>')
            z.writestr("xl/sharedStrings.xml", '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>Rent</t></si></sst>')
            z.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c></row></sheetData></worksheet>')
        self.files({"Drive/Colab Notebooks/Tide model": nb, "Drive/Budget.xlsx": sheet.getvalue(), "Chrome/Dictionary.csv": b""})
        self.run_import()
        docs = {r["title"]: r for r in self.of("imported_documents")}
        self.assertIn("import tides", docs["Tide model"]["text"])
        self.assertIn("Budget", docs)
        self.assertEqual(self.unclaimed(), set())

    def test_small_takeout_leftovers_are_claimed_or_documents(self):
        self.files({
            "My Activity/Gemini Apps/reference.pdf": b"%PDF-1.4 Gemini attachment",
            "Google Wallet/Boarding passes, event tickets and other passes/boarding.pdf": b"%PDF-1.4 boarding pass",
            "Chrome/Dictionary.csv": "tide\nmodel\n",
            "Chrome/Device Information.json": {"device": "made-up tablet"},
            "Google Account/2026.ChangeHistory.html": "<html>change history</html>",
            "Google Account/2026.SubscriberInfo.html": "<html>subscriber info</html>",
            "News/empty.txt": b"",
            "Gemini/empty.html": "<html></html>",
            "Maps/Requests for services/request.json": "{}",
            "Home App/SecurityAlarmClips.json": "{}",
            "Google Workspace Marketplace/README": "",
        })
        self.run_import()
        self.assertEqual(self.unclaimed(), set())
        titles = {r["title"] for r in self.of("imported_documents")}
        self.assertTrue({"reference", "boarding", "2026.ChangeHistory", "2026.SubscriberInfo"} <= titles)
        self.assertTrue(any("Dictionary.csv" in r["meta"]["file"] for r in self.of("takeout_other")))


# ---------------------------------------------------------------- Mail

def takeout_sep(n, when="Sat Jan 13 18:57:09 +0000 2024"):
    """The line Takeout starts each message with."""
    return f"From 17880000000000000{n:02d}@xxx {when}\r\n"


def mail(n, subject="Hello", body="Hi Ada.", frm="Grace Hopper <grace@example.com>", labels="Inbox,Opened",
         date="Sat, 13 Jan 2024 18:57:09 +0000", headers="", ctype="text/plain; charset=UTF-8"):
    head = f"X-GM-THRID: 17{n:017d}\r\nX-Gmail-Labels: {labels}\r\n" if labels is not None else ""
    head += f"Message-ID: <m{n}@example.com>\r\nFrom: {frm}\r\nTo: Ada Lovelace <ada@example.com>\r\nSubject: {subject}\r\n"
    head += f"Date: {date}\r\n" if date else ""
    return head + headers + f"MIME-Version: 1.0\r\nContent-Type: {ctype}\r\n\r\n" + body + "\r\n\r\n"


def mbox(*messages):
    return "".join(takeout_sep(i) + m for i, m in enumerate(messages, 1)).encode()


class MailTests(Base):
    def by_id(self):
        return {r["id"]: r for r in self.of("gmail")}

    def test_mail_in_other_languages_is_gmail(self):
        # Takeout names the folder and the mbox in the account's language (German: Gmail/).
        self.files({"Gmail/Alle E-Mails einschließlich Spam und Papierkorb.mbox": mbox(mail(1))})
        self.files({"Mail/Todo el correo, incluido Spam y Papelera-067.mbox": mbox(mail(2))}, root="takeout-20261002T000000Z/Takeout/")
        self.run_import()
        self.assertEqual(sorted(self.by_id()), ["<m1@example.com>", "<m2@example.com>"])

    def test_from_at_the_start_of_a_line_in_a_body_is_not_a_new_message(self):
        # Not every mbox writer quotes a body's "From " lines (Takeout writes ">From "): only a line like a separator
        # starts a message.
        body = "Hi Ada.\r\n\r\nFrom here on, the plan changes.\r\n>From the archive, quoted.\r\nFrom: someone, in prose\r\n\r\nGrace"
        self.files({"Mail/All mail Including Spam and Trash.mbox": mbox(mail(1, body=body), mail(2, subject="Second"))})
        self.run_import()
        got = self.by_id()
        self.assertEqual(sorted(got), ["<m1@example.com>", "<m2@example.com>"], "two messages, no third made of a body's tail")
        text = got["<m1@example.com>"]["text"]
        for line in ("From here on, the plan changes.", "From the archive, quoted.", "Grace"):
            self.assertIn(line, text)

    def test_lf_mbox_and_a_mail_app_style_separator(self):
        # A mailbox from another tool: LF line ends, the classic separator with a two-space day.
        box = ("From grace@example.com Mon Jan  1 00:00:00 2024\n" + mail(1).replace("\r\n", "\n")
               + "From MAILER-DAEMON Tue Jan  2 00:00:00 2024\n" + mail(2, subject="Two").replace("\r\n", "\n"))
        self.files({"Mail/All mail Including Spam and Trash.mbox": box})
        self.run_import()
        self.assertEqual([r["title"] for r in sorted(self.of("gmail"), key=lambda r: r["id"])], ["Hello", "Two"])

    def test_encoded_headers_and_charsets(self):
        self.files({"Mail/All mail Including Spam and Trash.mbox": mbox(
            mail(1, subject="=?UTF-8?Q?Caf=C3=A9_=F0=9F=8E=89?=", frm="=?ISO-8859-1?Q?Jos=E9_Mart=ED?= <jose@example.com>"),
            mail(2, subject="=?ISO-2022-JP?B?GyRCRnxLXDhsGyhC?=", ctype="text/plain; charset=ISO-2022-JP",
                 body="\x1b$BF|K\\8l\x1b(B"),
            mail(3, ctype="text/plain; charset=windows-1252", body="Caf\xe9 \x93quoted\x94"),
        ).replace("Caf\xe9 \x93quoted\x94".encode(), "Café “quoted”".encode("cp1252"))})  # the body in its own charset
        self.run_import()
        got = self.by_id()
        self.assertEqual((got["<m1@example.com>"]["title"], got["<m1@example.com>"]["author"]), ("Café 🎉", "José Martí"))
        self.assertEqual(got["<m2@example.com>"]["title"], "日本語")
        self.assertIn("日本語", got["<m2@example.com>"]["text"])
        self.assertIn("Café “quoted”", got["<m3@example.com>"]["text"])

    def test_headers_written_in_raw_8bit(self):
        # Old mail with an accented subject sent without encoding it: UTF-8 most often, else Windows' Latin-1.
        raw = mbox(mail(1, subject="SUBJ1"), mail(2, subject="SUBJ2"))
        raw = raw.replace(b"SUBJ1", "Résumé 日本".encode()).replace(b"SUBJ2", "Café".encode("cp1252"))
        self.files({"Mail/All mail Including Spam and Trash.mbox": raw})
        self.run_import()
        got = self.by_id()
        self.assertEqual(got["<m1@example.com>"]["title"], "Résumé 日本")
        self.assertEqual(got["<m2@example.com>"]["title"], "Café")

    def test_a_part_in_a_charset_python_doesnt_know_keeps_its_text(self):
        body = "--b\r\nContent-Type: text/plain; charset=x-mac-roman-ish\r\n\r\nThe text is here.\r\n--b--"
        self.files({"Mail/All mail Including Spam and Trash.mbox": mbox(mail(1, ctype='multipart/alternative; boundary="b"', body=body))})
        self.run_import()
        self.assertIn("The text is here.", self.by_id()["<m1@example.com>"]["text"])

    def test_multipart_with_attachments(self):
        body = ("--mixed\r\nContent-Type: multipart/alternative; boundary=\"alt\"\r\n\r\n"
                "--alt\r\nContent-Type: text/plain; charset=UTF-8\r\n\r\nPlain words.\r\n"
                "--alt\r\nContent-Type: text/html; charset=UTF-8\r\n\r\n<p>Plain <b>words</b>.</p>\r\n--alt--\r\n"
                "--mixed\r\nContent-Type: application/pdf; name=\"=?UTF-8?Q?R=C3=A9sum=C3=A9.pdf?=\"\r\n"
                "Content-Disposition: attachment; filename*=UTF-8''R%C3%A9sum%C3%A9.pdf\r\nContent-Transfer-Encoding: base64\r\n\r\n"
                "JVBERi0xLjQK\r\n"
                "--mixed\r\nContent-Type: message/rfc822\r\nContent-Disposition: attachment; filename=\"fwd.eml\"\r\n\r\n"
                "From: x@example.com\r\nSubject: Inner\r\n\r\nForwarded.\r\n--mixed--")
        html_only = "<html><body><p>Only <i>HTML</i> here</p></body></html>"
        self.files({"Mail/All mail Including Spam and Trash.mbox": mbox(
            mail(1, ctype='multipart/mixed; boundary="mixed"', body=body),
            mail(2, ctype="text/html; charset=UTF-8", body=html_only))})
        self.run_import()
        got = self.by_id()
        self.assertIn("Plain words.", got["<m1@example.com>"]["text"])
        self.assertEqual(got["<m1@example.com>"]["meta"]["attachments"], ["Résumé.pdf", "fwd.eml"])
        self.assertIn("Only HTML here", got["<m2@example.com>"]["text"])

    def test_labels_mark_sent_spam_and_trash(self):
        self.files({"Mail/All mail Including Spam and Trash.mbox": mbox(
            mail(1, frm="Ada Lovelace <ada.old@example.org>", labels="Sent,Opened"),
            mail(2, labels="Spam"), mail(3, labels="Trash,Opened"),
            mail(4, labels='"Spam filters, old",Inbox'),  # a label of your own with "Spam" in its name
            mail(5, labels="=?UTF-8?Q?Wichtig,Ge=C3=B6ffnet?="))})
        self.run_import()
        got = self.by_id()
        self.assertTrue(got["<m1@example.com>"]["is_me"])
        self.assertEqual(got["<m2@example.com>"]["meta"].get("tier"), "spam")
        self.assertEqual(got["<m3@example.com>"]["meta"].get("tier"), "deleted")
        self.assertNotIn("tier", got["<m4@example.com>"]["meta"], "your own label isn't Spam")
        self.assertEqual(got["<m5@example.com>"]["meta"]["labels"], "Wichtig,Geöffnet")

    def test_times_without_a_date_header_or_with_minus_zero(self):
        received = "Received: by 2002:a05:6000:1:b0:1 with SMTP id x; Sun, 14 Jan 2024 09:00:00 -0800 (PST)\r\n"
        self.files({"Mail/All mail Including Spam and Trash.mbox": mbox(
            mail(1, date=None, headers=received), mail(2, date="Sat, 13 Jan 2024 18:57:09 -0000"))})
        self.run_import()
        got = self.by_id()
        self.assertEqual(got["<m1@example.com>"]["ts"], "2024-01-14T17:00:00Z", "from the Received line")
        self.assertEqual(got["<m2@example.com>"]["ts"], "2024-01-13T18:57:09Z", "-0000 is UTC")

    def test_recipients_have_no_blanks(self):
        self.files({"Mail/All mail Including Spam and Trash.mbox": mbox(mail(1))})
        self.run_import()
        self.assertEqual(self.by_id()["<m1@example.com>"]["meta"]["to"], ["ada@example.com"])

    def test_a_big_mailbox_in_a_zip_part(self):
        big = "x" * 3_000_000  # one 3 MB attachment's worth of base64
        att = f"--b\r\nContent-Type: text/plain\r\n\r\nSee attached.\r\n--b\r\nContent-Type: image/png; name=a.png\r\nContent-Transfer-Encoding: base64\r\n\r\n{big}\r\n--b--"
        msgs = [mail(i, subject=f"Mail {i}") for i in range(1, 1500)] + [mail(1500, ctype='multipart/mixed; boundary="b"', body=att)]
        self.zip("takeout-20261001T000000Z/takeout-20261001T000000Z-001.zip", {"Takeout/Mail/All mail Including Spam and Trash.mbox": mbox(*msgs)})
        self.run_import()
        got = self.by_id()
        self.assertEqual(len(got), 1500)
        self.assertEqual(got["<m1500@example.com>"]["meta"]["attachments"], ["a.png"])


# ---------------------------------------------------------------- Calendar

ICS_HEAD = ("BEGIN:VCALENDAR\r\nPRODID:-//Google Inc//Google Calendar 70.9054//EN\r\nVERSION:2.0\r\nCALSCALE:GREGORIAN\r\n"
            "X-WR-CALNAME:ada@example.com\r\nX-WR-TIMEZONE:America/Los_Angeles\r\n"
            "BEGIN:VTIMEZONE\r\nTZID:America/Los_Angeles\r\nX-LIC-LOCATION:America/Los_Angeles\r\n"
            "BEGIN:DAYLIGHT\r\nTZOFFSETFROM:-0800\r\nTZOFFSETTO:-0700\r\nTZNAME:PDT\r\nDTSTART:19700308T020000\r\n"
            "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU\r\nEND:DAYLIGHT\r\nBEGIN:STANDARD\r\nTZOFFSETFROM:-0700\r\nTZOFFSETTO:-0800\r\n"
            "TZNAME:PST\r\nDTSTART:19701101T020000\r\nRRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU\r\nEND:STANDARD\r\nEND:VTIMEZONE\r\n")


def vevent(*lines):
    return "BEGIN:VEVENT\r\n" + "".join(l + "\r\n" for l in lines) + "END:VEVENT\r\n"


class CalendarTests(Base):
    def test_zones_all_day_repeats_alarms_and_folded_lines(self):
        ics = ICS_HEAD + "".join([
            vevent("DTSTART;TZID=America/Los_Angeles:20240115T090000", "DTEND;TZID=America/Los_Angeles:20240115T093000",
                   "RRULE:FREQ=WEEKLY;BYDAY=MO", "EXDATE;TZID=America/Los_Angeles:20240122T090000", "UID:standup@google.com",
                   "SUMMARY:Standup", "DESCRIPTION:A long description that Google folds at seventy-five octets\\, so it",
                   "  goes on here\\nand on a new line.", "LOCATION:Room 4\\, Building B"),
            # One week moved: the same UID with a RECURRENCE-ID.
            vevent("DTSTART;TZID=America/Los_Angeles:20240129T100000", "DTEND;TZID=America/Los_Angeles:20240129T103000",
                   "RECURRENCE-ID;TZID=America/Los_Angeles:20240129T090000", "UID:standup@google.com", "SUMMARY:Standup (moved)"),
            vevent("DTSTART;VALUE=DATE:20240214", "DTEND;VALUE=DATE:20240215", "UID:valentine@google.com", "SUMMARY:Day off"),
            vevent("DTSTART:20240301T170000Z", "DTEND:20240301T180000Z", "UID:alarm@google.com", "SUMMARY:With a reminder",
                   'ATTENDEE;CUTYPE=INDIVIDUAL;ROLE=REQ-PARTICIPANT;PARTSTAT=ACCEPTED;CN="Hopper: Grace";X-NUM-GUESTS=0:mailto:grace@example.com',
                   "BEGIN:VALARM", "ACTION:EMAIL", "DESCRIPTION:This is an event reminder", "SUMMARY:Alarm notification",
                   "ATTENDEE:mailto:ada@example.com", "TRIGGER:-P0DT0H30M0S", "END:VALARM"),
            # Two events with no UID (made by another app): both kept.
            vevent("DTSTART:20240401T170000Z", "SUMMARY:No uid one"),
            vevent("DTSTART:20240401T170000Z", "SUMMARY:No uid two"),
            # A zone named the Windows way, from an Outlook invite: this Mac's clock.
            vevent('DTSTART;TZID="Pacific Standard Time":20240501T090000', "UID:outlook@example.com", "SUMMARY:From Outlook"),
        ]) + "END:VCALENDAR\r\n"
        self.files({"Kalender/ada@example.com.ics": ics})  # German: Kalender
        self.run_import()
        got = {r["title"]: r for r in self.of("google_calendar")}
        self.assertEqual(sorted(got), ["Day off", "From Outlook", "No uid one", "No uid two", "Standup", "Standup (moved)", "With a reminder"])
        s = got["Standup"]
        self.assertEqual((s["ts"], s["ts_end"], s["meta"].get("recurring")), ("2024-01-15T17:00:00Z", "2024-01-15T17:30:00Z", True))
        self.assertIn("seventy-five octets, so it goes on here\nand on a new line.", s["text"])
        self.assertEqual(s["meta"]["location"], "Room 4, Building B")
        self.assertEqual(got["Standup (moved)"]["ts"], "2024-01-29T18:00:00Z")
        self.assertEqual((got["Day off"]["ts"], got["Day off"]["ts_end"]), ("2024-02-14", "2024-02-15"))
        alarm = got["With a reminder"]
        self.assertNotIn("event reminder", alarm["text"], "the alarm's text isn't the event's")
        self.assertEqual(alarm.get("participants"), ["Hopper: Grace"], "the alarm's address isn't a guest")
        self.assertEqual(got["From Outlook"]["ts"], "2024-05-01T13:00:00Z")


# ---------------------------------------------------------------- Contacts

class ContactsTests(Base):
    CARD = ("BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Grace Hopper\r\nN:Hopper;Grace;;;\r\nTEL;TYPE=CELL:+1 555 0100\r\n"
            "TEL;TYPE=WORK:+1 555 0101\r\nEMAIL;TYPE=INTERNET:grace@example.com\r\nEMAIL;TYPE=INTERNET:g.hopper@navy.example\r\n"
            "item1.ADR:;;1 Main St;Arlington;VA;22201;US\r\nitem1.X-ABLabel:Home\r\n"
            "NOTE:Met at the conference\\, 1952. She said the most dangerous phrase is: we've always done it\r\n"
            "  this way.\r\nCATEGORIES:myContacts,starred\r\nEND:VCARD\r\n")

    def test_folded_lines_many_numbers_and_each_group_once(self):
        only_org = "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:\r\nORG:Acme Plumbing\r\nTEL:+1 555 0199\r\nEND:VCARD\r\n"
        only_mail = "BEGIN:VCARD\r\nVERSION:3.0\r\nEMAIL:someone@example.net\r\nEND:VCARD\r\n"
        self.files({"Contacts/All Contacts/All Contacts.vcf": self.CARD + only_org + only_mail,
                    "Contacts/Starred/Starred.vcf": self.CARD})
        self.files({"Kontakte/Alle Kontakte/Alle Kontakte.vcf": self.CARD.replace("Grace", "Gräce")}, root="takeout-20261002T000000Z/Takeout/")
        self.run_import()
        got = {r["title"]: r for r in self.of("google_contacts")}
        self.assertEqual(sorted(got), ["Acme Plumbing", "Grace Hopper", "Gräce Hopper", "someone@example.net"])
        text = got["Grace Hopper"]["text"]
        for x in ("+1 555 0100", "+1 555 0101", "grace@example.com", "g.hopper@navy.example", "Arlington",
                  "we've always done it this way."):
            self.assertIn(x, text)

    def test_an_android_export_in_vcard_21(self):
        card = ("BEGIN:VCARD\r\nVERSION:2.1\r\nN;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:Mart=C3=AD;Jos=C3=A9;;;\r\n"
                "FN;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:Jos=C3=A9 Mart=C3=AD\r\nTEL;CELL:+34600000000\r\n"
                "NOTE;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:Una nota larga que sigue =\r\nen la l=C3=ADnea siguiente\r\nEND:VCARD\r\n")
        self.files({"contacts.vcf": card}, root="phone")
        self.run_import()
        (r,) = self.of("vcard_contacts")
        self.assertEqual(r["title"], "José Martí")
        self.assertIn("Una nota larga que sigue en la línea siguiente", r["text"])


# ---------------------------------------------------------------- Keep

def note(title, text, created, **extra):
    return {"color": "DEFAULT", "isTrashed": False, "isPinned": False, "isArchived": False, "title": title, "textContent": text,
            "userEditedTimestampUsec": created + 5_000_000, "createdTimestampUsec": created, **extra}


KEEP_HTML = """<?xml version="1.0" ?>
<html><head><title>{title}</title><style type="text/css">body {{ font-family: sans-serif; }}</style></head><body>
<div class="note DEFAULT"><div class="heading"><div class="meta-icons"></div>Jan 2, 2016, 10:00:00 AM</div>
<div class="title">{title}</div>
<div class="content">{body}</div>
<div class="labels"><span class="label"><span class="label-name">Ideas</span></span></div></div></body></html>"""


class KeepTests(Base):
    def test_lists_links_labels_and_the_html_twin_once(self):
        t = 1700000000000000
        self.files({
            "Keep/Groceries.json": note("Groceries", "", t, listContent=[{"text": "milk", "isChecked": True}, {"text": "eggs", "isChecked": False}],
                                        labels=[{"name": "Home"}]),
            "Keep/Groceries.html": KEEP_HTML.format(title="Groceries", body="milk<br>eggs"),
            "Keep/A link.json": note("A link", "Read this", t + 1, annotations=[{"description": "Tides", "source": "WEBLINK",
                                                                               "title": "How tides work", "url": "https://example.com/tides"}]),
            "Keep/Old.json": note("Old", "in the bin", t + 2, isTrashed=True),
        })
        self.run_import()
        got = {r["title"]: r for r in self.of("google_keep")}
        self.assertEqual(sorted(got), ["A link", "Groceries", "Old"])
        self.assertEqual(got["Old"]["meta"]["tier"], "deleted", "a note in the bin is kept, as mail in the bin is")
        self.assertIn("[x] milk\n[ ] eggs", got["Groceries"]["text"])
        self.assertEqual(got["Groceries"]["meta"]["labels"], ["Home"])
        self.assertIn("https://example.com/tides", got["A link"]["text"], "a link in the note is kept with it")
        self.assertNotIn("imported_documents", self.recs, "the HTML twin isn't a document of its own")

    def test_an_old_export_with_only_html(self):
        # Before 2018 Keep came as HTML only: each note is kept, not dropped as a twin of a JSON that isn't there.
        self.files({"Keep/Ideas.html": KEEP_HTML.format(title="Ideas", body="A boat<br>made of paper")})
        self.run_import()
        texts = [r["text"] for s in ("google_keep", "imported_documents") for r in self.of(s)]
        self.assertTrue(any("A boat" in t and "made of paper" in t for t in texts), texts)


# ---------------------------------------------------------------- Tasks and Chat

TASKS = {"kind": "tasks#taskLists", "items": [{"kind": "tasks#taskList", "id": "L1", "title": "Meine Aufgaben", "updated": "2024-01-01T00:00:00.000Z",
         "items": [{"kind": "tasks#task", "id": "t1", "title": "Steuer", "notes": "bis Mai", "status": "needsAction",
                    "created": "2024-01-01T00:00:00.000Z", "updated": "2024-01-02T00:00:00.000Z", "due": "2024-05-01T00:00:00.000Z"}]}]}


class TasksAndChatTests(Base):
    def test_tasks_in_a_folder_named_in_german(self):
        self.files({"Aufgaben/Aufgaben.json": TASKS})
        self.run_import()
        self.assertEqual([r["title"] for r in self.of("google_tasks")], ["Steuer"])

    def test_chat_with_times_in_another_language_and_a_broken_group(self):
        msgs = {"messages": [
            {"creator": {"name": "Grace Hopper", "email": "grace@example.com", "user_type": "Human"},
             "created_date": "Wednesday, June 8, 2016 at 3:55:41 AM UTC", "text": "Hi Ada", "topic_id": "t1", "message_id": "m1"},
            {"creator": {"name": "Ada Lovelace", "email": "ada@example.com", "user_type": "Human"},
             "created_date": "Mittwoch, 8. Juni 2016 um 04:00:00 UTC", "text": "Hallo", "topic_id": "t1", "message_id": "m2"},
            {"creator": {"name": "Grace Hopper", "email": "grace@example.com", "user_type": "Human"},
             "created_date": "miércoles, 8 de junio de 2016, 4:05:00 UTC", "text": "Hola", "topic_id": "t1", "message_id": "m3"},
        ]}
        self.files({
            "Google Chat/Groups/DM abc/group_info.json": {"members": [{"name": "Grace Hopper", "email": "grace@example.com"},
                                                                     {"name": "Ada Lovelace", "email": "ada@example.com"}]},
            "Google Chat/Groups/DM abc/messages.json": msgs,
            "Google Chat/Groups/DM broken/group_info.json": "[not json",
            "Google Chat/Groups/DM broken/messages.json": "{\"messages\": [",
            "Calendar/ada@example.com.ics": ICS_HEAD + vevent("DTSTART:20240301T170000Z", "UID:x", "SUMMARY:Still here") + "END:VCALENDAR\r\n",
        })
        self.run_import()
        got = {r["text"]: r for r in self.of("google_chat")}
        self.assertEqual({t: r.get("ts") for t, r in got.items()},
                         {"Hi Ada": "2016-06-08T03:55:41Z", "Hallo": "2016-06-08T04:00:00Z", "Hola": "2016-06-08T04:05:00Z"})
        self.assertTrue(got["Hallo"]["is_me"])
        self.assertEqual([r["title"] for r in self.of("google_calendar")], ["Still here"])


# ---------------------------------------------------------------- Chrome

class ChromeTests(Base):
    def test_browser_history_and_its_older_name(self):
        new = {"Browser History": [
            {"favicon_url": "https://www.google.com/favicon.ico", "page_transition_qualifier": "CLIENT_REDIRECT", "title": "tide tables - Google Search",
             "ptoken": {}, "url": "https://www.google.com/search?q=tide+tables", "client_id": "c1", "time_usec": 1705172229000000},
            {"page_transition": "LINK", "title": "Tides", "url": "https://example.com/tides", "client_id": "c1", "time_usec": 1705172230000000}]}
        old = {"Browser History": [{"page_transition": "TYPED", "title": "Old page", "url": "https://example.com/old", "time_usec": 1505172230000000}]}
        self.files({"Chrome/BrowserHistory.json": new})
        self.files({"Chrome/History.json": old}, root="takeout-20171001T000000Z/Takeout/")
        self.run_import()
        got = {r["url"]: r for r in self.of("chrome_synced")}
        self.assertEqual(got["https://www.google.com/search?q=tide+tables"]["kind"], "search")
        self.assertEqual(got["https://example.com/tides"]["ts"], "2024-01-13T18:57:10Z")
        self.assertIn("https://example.com/old", got)

    def test_a_broken_history_stops_nothing_else(self):
        self.files({"Chrome/BrowserHistory.json": '{"Browser History": [{"url": "https://example.com", "time_usec": 17',
                    "Chrome/History.json": ["not", "the", "shape"],
                    "Maps (your places)/Saved Places.json": ["not", "a", "feature collection"],
                    "Location History/Semantic Location History/2019/2019_JANUARY.json": "{\"timelineObjects\": [",
                    "Saved/Want to go.csv": "Title,Note,URL\nNul\x00here,,https://example.com/x\nBakery,,https://www.google.com/maps/place/Bakery\n",
                    "Calendar/ada@example.com.ics": ICS_HEAD + vevent("DTSTART:20240301T170000Z", "UID:x", "SUMMARY:Still here") + "END:VCALENDAR\r\n"})
        self.run_import()
        self.assertEqual([r["title"] for r in self.of("google_calendar")], ["Still here"])
        self.assertIn("BrowserHistory.json", self.unclaimed(), "a file that couldn't be read is listed as not read")

    def test_bookmarks_named_in_german(self):
        page = ('<!DOCTYPE NETSCAPE-Bookmark-file-1>\n<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">\n'
                '<TITLE>Bookmarks</TITLE>\n<H1>Bookmarks</H1>\n<DL><p>\n<DT><H3 ADD_DATE="1700000000">Lesezeichenleiste</H3>\n<DL><p>\n'
                '<DT><A HREF="https://example.com/a" ADD_DATE="1700000001">Seite A</A>\n</DL><p>\n</DL><p>\n')
        self.files({"Chrome/Lesezeichen.html": page})
        self.run_import()
        self.assertEqual([(r["title"], r["meta"]["folder"]) for r in self.of("chrome_synced", "bookmark")], [("Seite A", "Lesezeichenleiste")])


# ---------------------------------------------------------------- Maps

def feature(lon, lat, **props):
    return {"geometry": {"coordinates": [lon, lat], "type": "Point"}, "properties": props, "type": "Feature"}


class MapsTests(Base):
    def test_saved_places_and_reviews_old_and_new(self):
        self.files({
            # Since 2023: lower-case keys; a place Maps no longer knows has [0, 0].
            "Maps (your places)/Saved Places.json": {"type": "FeatureCollection", "features": [
                feature(-122.4194, 37.7749, date="2024-01-13T18:57:09Z", google_maps_url="http://maps.google.com/?cid=1",
                        location={"address": "1 Market St, San Francisco", "name": "Ferry Building", "country_code": "US"}),
                feature(0, 0, date="2024-01-14T00:00:00Z", google_maps_url="http://maps.google.com/?q=Lost",
                        Comment="No location information is available for this saved place")]},
            "Maps (your places)/Reviews.json": {"type": "FeatureCollection", "features": [
                feature(-122.41, 37.77, date="2024-02-01T10:00:00Z", five_star_rating_published=5, review_text_published="Great bread",
                        google_maps_url="http://maps.google.com/?cid=2", location={"address": "2 Main St", "name": "Bakery"})]},
            "Maps/My labeled places/Labeled places.json": {"type": "FeatureCollection", "features": [
                feature(-122.0, 37.0, address="10 Home St", name="Home")]},
        })
        # Before 2023: capitalized keys, the place under "Location", a review's stars and words under their own names.
        self.files({
            "Maps (your places)/Saved Places.json": {"type": "FeatureCollection", "features": [
                feature(-0.1276, 51.5072, **{"Google Maps URL": "http://maps.google.com/?cid=3", "Published": "2019-05-01T10:00:00Z",
                                             "Title": "British Museum", "Updated": "2019-05-01T10:00:00Z",
                                             "Location": {"Address": "Great Russell St, London", "Business Name": "British Museum",
                                                          "Country Code": "GB", "Geo Coordinates": {"Latitude": "51.5194", "Longitude": "-0.1270"}}})]},
            "Maps (your places)/Reviews.json": {"type": "FeatureCollection", "features": [
                feature(-0.12, 51.5, **{"Google Maps URL": "http://maps.google.com/?cid=4", "Published": "2019-06-01T10:00:00Z",
                                        "Star Rating": 4, "Review Comment": "Lovely garden",
                                        "Location": {"Address": "Kew, Richmond", "Business Name": "Kew Gardens", "Country Code": "GB"}})]},
        }, root="takeout-20191001T000000Z/Takeout/")
        self.run_import()
        got = {r["title"]: r for r in self.of("google_maps_places")}
        self.assertEqual(sorted(got), ["Bakery", "British Museum", "Ferry Building", "Home", "Kew Gardens", "Lost"])
        self.assertEqual((got["Ferry Building"]["meta"]["lat"], got["Ferry Building"]["url"]), (37.7749, "http://maps.google.com/?cid=1"))
        self.assertNotIn("lat", got["Lost"].get("meta") or {}, "no place at 0, 0; its name from its link")
        self.assertIn("Great bread", got["Bakery"]["text"])
        self.assertIn("Rating: 5", got["Bakery"]["text"])
        museum = got["British Museum"]
        self.assertEqual((museum["url"], museum["ts"]), ("http://maps.google.com/?cid=3", "2019-05-01T10:00:00Z"))
        self.assertIn("Great Russell St, London", museum["text"])
        self.assertIn("Lovely garden", got["Kew Gardens"]["text"])
        self.assertIn("Rating: 4", got["Kew Gardens"]["text"])

    def test_places_named_in_german(self):
        self.files({"Maps (Meine Orte)/Gespeicherte Orte.json": {"type": "FeatureCollection", "features": [
            feature(13.4050, 52.5200, date="2024-01-13T18:57:09Z", google_maps_url="http://maps.google.com/?cid=9",
                    location={"address": "Pariser Platz, Berlin", "name": "Brandenburger Tor"})]}})
        self.run_import()
        self.assertEqual([r["title"] for r in self.of("google_maps_places")], ["Brandenburger Tor"])


# ---------------------------------------------------------------- Location History

class LocationTests(Base):
    def test_semantic_history_visits_and_trips(self):
        month = {"timelineObjects": [
            {"activitySegment": {"startLocation": {"latitudeE7": 377749000, "longitudeE7": -1224194000},
                                 "endLocation": {"latitudeE7": 377000000, "longitudeE7": -1224000000},
                                 "duration": {"startTimestamp": "2019-01-05T09:00:00.000Z", "endTimestamp": "2019-01-05T09:30:00.000Z"},
                                 "distance": 5123, "activityType": "IN_PASSENGER_VEHICLE", "confidence": "HIGH"}},
            {"placeVisit": {"location": {"latitudeE7": 377000000, "longitudeE7": -1224000000, "placeId": "ChIJ1",
                                         "address": "1 Market St", "name": "Ferry Building", "semanticType": "TYPE_UNKNOWN"},
                            "duration": {"startTimestamp": "2019-01-05T09:30:00Z", "endTimestamp": "2019-01-05T11:00:00Z"},
                            "childVisits": [{"location": {"latitudeE7": 377001000, "longitudeE7": -1224001000, "placeId": "ChIJ2", "name": "Coffee stand"},
                                             "duration": {"startTimestamp": "2019-01-05T09:40:00Z", "endTimestamp": "2019-01-05T09:50:00Z"}}]}},
            # Before 2022: times in milliseconds, as text.
            {"placeVisit": {"location": {"latitudeE7": 377100000, "longitudeE7": -1224100000, "placeId": "ChIJ3", "name": "Library"},
                            "duration": {"startTimestampMs": "1546722000000", "endTimestampMs": "1546725600000"}}},
        ]}
        self.files({"Standortverlauf/Semantic Location History/2019/2019_JANUARY.json": month})  # German: Standortverlauf
        self.run_import()
        visits = {r["title"]: r for r in self.of("location_history", "place_visit")}
        self.assertEqual(sorted(visits), ["Coffee stand", "Ferry Building", "Library"])
        self.assertEqual(visits["Library"]["ts"], "2019-01-05T21:00:00Z")
        (trip,) = self.of("location_history", "trip")
        self.assertEqual((trip["ts"], trip["ts_end"]), ("2019-01-05T09:00:00Z", "2019-01-05T09:30:00Z"))
        self.assertEqual(trip["meta"]["activity"], "IN_PASSENGER_VEHICLE")

    def test_timeline_from_an_android_phone(self):
        tl = {"semanticSegments": [
            {"startTime": "2024-06-01T10:00:00.000+02:00", "endTime": "2024-06-01T12:00:00.000+02:00", "startTimeTimezoneUtcOffsetMinutes": 120,
             "visit": {"hierarchyLevel": 0, "probability": 0.9, "topCandidate": {"placeId": "ChIJa", "semanticType": "HOME", "probability": 0.8,
                                                                                 "placeLocation": {"latLng": "52.5200°, 13.4050°"}}}},
            {"startTime": "2024-06-01T12:00:00.000+02:00", "endTime": "2024-06-01T12:30:00.000+02:00",
             "activity": {"start": {"latLng": "52.5200°, 13.4050°"}, "end": {"latLng": "52.5300°, 13.4100°"}, "distanceMeters": 2100.5,
                          "probability": 0.95, "topCandidate": {"type": "CYCLING", "probability": 0.9}}},
            {"startTime": "2024-06-01T12:00:00.000+02:00", "endTime": "2024-06-01T14:00:00.000+02:00",
             "timelinePath": [{"point": "52.5200°, 13.4050°", "time": "2024-06-01T12:01:00.000+02:00"}]}],
            "rawSignals": [], "userLocationProfile": {"frequentPlaces": [{"placeId": "ChIJa", "placeLocation": "52.5200°, 13.4050°", "label": "HOME"}]}}
        self.files({"Timeline.json": tl}, root="timeline")
        self.run_import()
        (visit,) = self.of("location_history", "place_visit")
        self.assertEqual((visit["ts"], visit["meta"]["place_id"], visit["meta"]["latlng"]), ("2024-06-01T08:00:00Z", "ChIJa", "52.5200°, 13.4050°"))
        (trip,) = self.of("location_history", "trip")
        self.assertEqual((trip["meta"]["activity"], trip["ts_end"]), ("CYCLING", "2024-06-01T10:30:00Z"))
        (home,) = self.of("location_history", "place")
        self.assertEqual((home["title"], home["meta"]["place_id"]), ("Home", "ChIJa"))
        self.assertEqual(self.manifest["location_history"]["notes"], {"raw_points_not_kept": 1}, "the raw points are counted, not dropped silently")

    def test_timeline_from_an_iphone(self):
        # The iPhone's export: a list, every value text, places as geo: links.
        tl = [{"endTime": "2024-06-01T12:00:00.000+02:00", "startTime": "2024-06-01T10:00:00.000+02:00",
               "visit": {"hierarchyLevel": "0", "topCandidate": {"probability": "0.85", "semanticType": "Home", "placeID": "ChIJb",
                                                                  "placeLocation": "geo:52.520000,13.405000"}, "probability": "0.9"}},
              {"endTime": "2024-06-01T12:30:00.000+02:00", "startTime": "2024-06-01T12:00:00.000+02:00",
               "activity": {"probability": "0.95", "end": "geo:52.530000,13.410000", "topCandidate": {"type": "walking", "probability": "0.9"},
                            "distanceMeters": "2100.5", "start": "geo:52.520000,13.405000"}},
              {"endTime": "2024-06-01T14:00:00.000+02:00", "startTime": "2024-06-01T12:00:00.000+02:00",
               "timelinePath": [{"point": "geo:52.520000,13.405000", "durationMinutesOffsetFromStartTime": "1"}]}]
        self.files({"location-history.json": tl}, root="timeline")
        self.run_import()
        (visit,) = self.of("location_history", "place_visit")
        self.assertEqual((visit["ts"], visit["meta"]["place_id"]), ("2024-06-01T08:00:00Z", "ChIJb"))
        (trip,) = self.of("location_history", "trip")
        self.assertEqual(trip["meta"]["activity"], "walking")

    def test_raw_records_are_not_dropped(self):
        rec = {"locations": [{"latitudeE7": 377749000, "longitudeE7": -1224194000, "accuracy": 20, "source": "WIFI",
                              "deviceTag": 1, "timestamp": "2019-01-05T09:00:00.000Z"},
                             {"latitudeE7": 377749100, "longitudeE7": -1224194100, "accuracy": 20, "timestampMs": "1546678800000"}]}
        self.files({"Location History/Records.json": rec})
        self.run_import()
        kept = [r for s, rs in self.recs.items() for r in rs if "Records.json" in json.dumps(r)]
        self.assertTrue(kept or "Records.json" in self.unclaimed(), "kept, or listed as not read")


# ---------------------------------------------------------------- Fit

class FitTests(Base):
    def test_fit_is_kept(self):
        session = {"fitnessActivity": "running", "startTime": "2024-01-13T08:00:00Z", "endTime": "2024-01-13T08:30:00Z", "duration": "1800s",
                   "aggregate": [{"metricName": "com.google.calories.expended", "floatValue": 300.5},
                                 {"metricName": "com.google.distance.delta", "floatValue": 5000.0}]}
        self.files({"Fit/All sessions/2024-01-13T08_00_00Z_RUNNING.json": session,
                    "Fit/Daily activity metrics/2024-01-13.csv": "Start time,End time,Move Minutes count,Calories (kcal),Distance (m),Step count\n"
                                                                  "08:00:00.000Z,08:15:00.000Z,15,150.2,2500,3000\n"})
        self.run_import()
        everything = json.dumps(self.recs)
        self.assertIn("running", everything, "a workout is kept")
        self.assertIn("3000", everything, "a day's steps are kept")


# ---------------------------------------------------------------- Archives

class ArchiveTests(Base):
    def test_a_product_split_across_zip_parts_dropped_in_loose(self):
        # Parts dropped straight into corpus/imports/, not in a folder of their own: still one export.
        yt = "Takeout/YouTube and YouTube Music/playlists/"
        self.zip("takeout-20261001T000000Z-001.zip", {
            yt + "playlists.csv": "Playlist ID,Add new videos to top,Playlist Title (Original),Playlist Title (Original) Language,Playlist Create Timestamp,"
                                  "Playlist Update Timestamp,Playlist Video Order,Playlist Visibility\n"
                                  "PL1,False,Tides,,2024-01-01T00:00:00+00:00,2024-01-02T00:00:00+00:00,Manual,Private\n",
            "Takeout/Google Photos/Trip/IMG_0009.jpg.json": {"title": "IMG_0009.jpg", "photoTakenTime": {"timestamp": "1704067200"},
                                                             "url": "https://photos.google.com/photo/nine"}})
        self.zip("takeout-20261001T000000Z-002.zip", {
            yt + "Tides-videos.csv": "Video ID,Playlist Video Creation Timestamp\nvid00000001,2024-01-01T10:00:00+00:00\n",
            "Takeout/Google Photos/Trip/IMG_0009.jpg": b"nine"})
        self.run_import()
        (saved,) = self.of("youtube", "saved")
        self.assertEqual(saved["thread"], "PL1", "the playlist's videos in part 2 go with the playlist in part 1")
        (photo,) = self.of("google_photos")
        self.assertTrue(photo["meta"].get("files"), "the photo in part 2 goes with its sidecar in part 1")
        self.assertNotIn("takeout_files", self.recs)

    def test_tgz_parts(self):
        yt = "Takeout/YouTube and YouTube Music/playlists/"
        self.tgz("takeout-20261001T000000Z/takeout-20261001T000000Z-001.tgz", {
            yt + "playlists.csv": "Playlist ID,Playlist Title (Original),Playlist Create Timestamp\nPL1,Tides,2024-01-01T00:00:00+00:00\n",
            "Takeout/Mail/All mail Including Spam and Trash.mbox": mbox(mail(1))})
        self.tgz("takeout-20261001T000000Z/takeout-20261001T000000Z-002.tgz", {
            yt + "Tides-videos.csv": "Video ID,Playlist Video Creation Timestamp\nvid00000001,2024-01-01T10:00:00+00:00\n"})
        self.run_import()
        self.assertEqual([r["id"] for r in self.of("gmail")], ["<m1@example.com>"])
        (saved,) = self.of("youtube", "saved")
        self.assertEqual(saved["thread"], "PL1")

    def test_parts_unzipped_by_finder_into_takeout_2(self):
        # Archive Utility unzips the second part beside the first as "Takeout 2".
        self.files({"Takeout/Keep/Idea.json": note("Idea", "first part", 1700000000000000)}, root="takeout-20261001T000000Z/")
        self.files({"Takeout 2/Keep/Other.json": note("Other", "second part", 1700000000000001),
                    "Takeout 2/Keep/Other.html": KEEP_HTML.format(title="Other", body="second part"),
                    "Takeout 2/Saved/Want to go.csv": "Title,Note,URL,Tags,Comment\nBakery,,https://www.google.com/maps/place/Bakery,,\n",
                    "Takeout 2/Mail/All mail Including Spam and Trash.mbox": mbox(mail(1, labels="Trash"))}, root="takeout-20261001T000000Z/")
        self.run_import()
        self.assertEqual(sorted(r["title"] for r in self.of("google_keep")), ["Idea", "Other"])
        self.assertNotIn("imported_documents", self.recs, "Keep's HTML twins in Takeout 2 aren't documents")
        self.assertEqual([r["title"] for r in self.of("google_saved")], ["Bakery"])
        self.assertEqual(self.of("gmail")[0]["meta"].get("tier"), "deleted")

    def test_a_part_cut_short_stops_nothing_and_says_so(self):
        good = self.zip("takeout-20261001T000000Z/takeout-20261001T000000Z-001.zip", {"Takeout/Mail/All mail Including Spam and Trash.mbox": mbox(mail(1))})
        cut = self.imports / "takeout-20261001T000000Z/takeout-20261001T000000Z-002.zip"
        cut.write_bytes(good.read_bytes()[:-30])  # a download that stopped before the end
        self.run_import()
        self.assertEqual([r["id"] for r in self.of("gmail")], ["<m1@example.com>"])
        self.assertIn("takeout-20261001T000000Z-002.zip", self.out, "the part that couldn't be opened is named")

    def test_a_member_that_fails_its_check_stops_nothing(self):
        p = self.zip("takeout-20261001T000000Z/takeout-20261001T000000Z-001.zip", {
            "Takeout/Chrome/BrowserHistory.json": {"Browser History": [{"url": "https://example.com/" + "a" * 2000, "time_usec": 1705172229000000}]},
            "Takeout/Tasks/Tasks.json": TASKS})
        b = bytearray(p.read_bytes())
        i = b.find(b"https://example.com/")  # stored, not deflated: flip a byte of the first file's data
        b[i + 30] ^= 1
        p.write_bytes(bytes(b))
        self.run_import()
        self.assertEqual([r["title"] for r in self.of("google_tasks")], ["Steuer"])


    def test_a_takeout_deep_in_folders_of_its_own(self):
        root = "old backups/2019/takeout-20190101T000000Z-001/Takeout/"
        self.files({"Mail/All mail Including Spam and Trash.mbox": mbox(mail(1)),
                    "Chrome/BrowserHistory.json": {"Browser History": [{"url": "https://example.com/a", "title": "A", "time_usec": 1546300800000000}]},
                    "Keep/Idea.json": note("Idea", "deep down", 1546300800000000)}, root=root)
        self.run_import()
        self.assertEqual(([r["id"] for r in self.of("gmail")], [r["url"] for r in self.of("chrome_synced")], [r["title"] for r in self.of("google_keep")]),
                         (["<m1@example.com>"], ["https://example.com/a"], ["Idea"]))

    def test_parts_zipped_together(self):
        # Both parts in one zip of their own (zipped again to send, say): still one export.
        inner = {}
        for n, files in ((1, {"Takeout/Google Photos/Trip/IMG_0009.jpg.json": {"title": "IMG_0009.jpg", "photoTakenTime": {"timestamp": "1704067200"},
                                                                                "url": "https://photos.google.com/photo/nine"}}),
                         (2, {"Takeout/Google Photos/Trip/IMG_0009.jpg": b"nine"})):
            b = io.BytesIO()
            with zipfile.ZipFile(b, "w") as z:
                for k, v in files.items():
                    z.writestr(k, data(v))
            inner[f"takeout-20261001T000000Z-00{n}.zip"] = b.getvalue()
        self.zip("from-a-friend/both parts.zip", inner)
        self.run_import()
        (photo,) = self.of("google_photos")
        self.assertTrue(photo["meta"].get("files"))

    def test_damaged_documents_and_photos_stop_nothing(self):
        p = self.zip("takeout-20261001T000000Z/takeout-20261001T000000Z-001.zip", {
            "Takeout/Drive/Report.txt": "A report " + "x" * 2000,
            "Takeout/Drive/holiday.jpg": b"\xff\xd8" + b"y" * 2000,
            "Takeout/Tasks/Tasks.json": TASKS})
        b = bytearray(p.read_bytes())
        for marker in (b"A report ", b"\xff\xd8yyyy"):  # stored, not deflated: flip a byte of each file's data
            b[b.find(marker) + 100] ^= 1
        p.write_bytes(bytes(b))
        self.run_import()
        self.assertEqual([r["title"] for r in self.of("google_tasks")], ["Steuer"])
        self.assertIn("Report.txt", self.out)
        self.assertIn("holiday.jpg", self.out)


# ---------------------------------------------------------------- My Activity and YouTube history, as JSON

def act(header, title, time, url=None, **extra):
    it = {"header": header, "title": title, "time": time, "products": [header]}
    if url:
        it["titleUrl"] = url
    return {**it, **extra}


class ActivityJSONTests(Base):
    def test_my_activity_and_youtube_history_named_in_other_languages(self):
        self.files({
            "Meine Aktivitäten/Suche/MeineAktivitäten.json": [
                act("Suche", "Nach Gezeiten gesucht", "2024-01-13T18:57:09.123Z", "https://www.google.com/search?q=Gezeiten")],
            "YouTube und YouTube Music/Verlauf/Wiedergabeverlauf.json": [
                act("YouTube", "Wie Gezeiten entstehen angesehen", "2024-01-13T19:00:00Z", "https://www.youtube.com/watch?v=vid00000001",
                    subtitles=[{"name": "Gezeitenkanal", "url": "https://www.youtube.com/channel/UC1"}])],
        })
        self.files({"Mi actividad/Búsqueda/MiActividad.json": [
            act("Búsqueda", "Has buscado mareas", "2024-01-14T10:00:00Z", "https://www.google.com/search?q=mareas")]},
            root="takeout-20261002T000000Z/Takeout/")
        self.run_import()
        got = {r["ts"]: r for r in self.of("google_activity")}
        self.assertEqual(sorted(got), ["2024-01-13T18:57:09.123000Z", "2024-01-13T19:00:00Z", "2024-01-14T10:00:00Z"])
        self.assertEqual((got["2024-01-13T18:57:09.123000Z"]["kind"], got["2024-01-13T18:57:09.123000Z"]["title"]), ("search", "Gezeiten"))
        self.assertEqual(got["2024-01-13T19:00:00Z"]["kind"], "media", "a YouTube video is something watched, in any language")
        self.assertIn("Gezeitenkanal", got["2024-01-13T19:00:00Z"]["text"])
        self.assertEqual(got["2024-01-14T10:00:00Z"]["title"], "mareas")
        self.assertNotIn("takeout_other", self.recs)

    def test_gemini_prompts_and_answers(self):
        self.files({"My Activity/Gemini Apps/MyActivity.json": [
            act("Gemini Apps", "Prompted What makes tides?", "2025-01-13T18:57:09Z",
                safeHtmlItem=[{"html": "<p>The <b>moon</b>'s pull, mostly.</p>"}], attachedFiles=["chart.png"]),
            act("Gemini Apps", "Used an Assistant feature", "2025-01-13T19:00:00Z")]})
        self.run_import()
        got = {r["ts"]: r for r in self.of("google_activity")}
        turn = got["2025-01-13T18:57:09Z"]
        self.assertEqual((turn["kind"], turn["title"]), ("ai_turn", "What makes tides?"))
        self.assertIn("The moon 's pull, mostly.", turn["text"])
        self.assertIn("2025-01-13T19:00:00Z", got)

    def test_an_item_that_isnt_the_usual_shape_stops_nothing(self):
        self.files({"My Activity/Search/MyActivity.json": [
            act("Search", "Searched for tides", "2024-01-13T18:57:09Z", "https://www.google.com/search?q=tides"),
            "a string, not an item", {"header": "Search", "title": None, "time": None, "subtitles": ["not a dict"], "details": "nor this"},
            act("Search", "Searched for moons", "2024-01-13T18:58:09Z", "https://www.google.com/search?q=moons")]})
        self.run_import()
        self.assertEqual(sorted(r["title"] for r in self.of("google_activity", "search")), ["moons", "tides"])


# ---------------------------------------------------------------- My Activity and YouTube history, as web pages (the default)

PAGE_HEAD = ('<html><head><meta charset="UTF-8"><title>My Activity</title><style type="text/css">'
             + ".mdl-grid { display: flex; } " * 400 + '</style></head><body><div class="mdl-grid">')


def cell(header, content, caption="<b>Products:</b><br>&emsp;Search<br>"):
    """One item as Takeout's page has it."""
    return ('<div class="outer-cell mdl-cell mdl-cell--12-col mdl-shadow--2dp"><div class="mdl-grid">'
            f'<div class="header-cell mdl-cell mdl-cell--12-col"><p class="mdl-typography--title">{header}<br></p></div>'
            f'<div class="content-cell mdl-cell mdl-cell--6-col mdl-typography--body-1">{content}</div>'
            '<div class="content-cell mdl-cell mdl-cell--6-col mdl-typography--body-1 mdl-typography--text-right"></div>'
            f'<div class="content-cell mdl-cell mdl-cell--12-col mdl-typography--caption">{caption}</div></div></div>')


def page(*cells):
    return PAGE_HEAD + "".join(cells) + "</div></body></html>"


WHY = "<b>Why is this here?</b><br>&emsp;This activity was saved to your Google Account because the following settings were on:&nbsp;Web &amp; App Activity.&nbsp;You can control these settings &nbsp;<a href=\"https://myaccount.google.com/activitycontrols\">here</a>."


class ActivityPageTests(Base):
    def test_search_youtube_gemini_and_ads_as_pages(self):
        self.files({
            "My Activity/Search/MyActivity.html": page(
                cell("Search", 'Searched for&nbsp;<a href="https://www.google.com/search?q=tide+tables">tide tables</a><br>Jan 13, 2024, 6:57:09 PM PST',
                     "<b>Products:</b><br>&emsp;Search<br>" + WHY),
                cell("Search", 'Visited&nbsp;<a href="https://example.com/tides">How tides work</a><br>Jan 31, 2018, 10:54:50 PM'),
                cell("Search", 'Visited&nbsp;<a href="https://ads.example/1">Cheap flights</a><br>6 Oct 2020, 14:32:28 GMT',
                     "<b>Products:</b><br>&emsp;Search<br><b>Details:</b><br>&emsp;From Google Ads<br>")),
            "YouTube and YouTube Music/history/watch-history.html": page(
                cell("YouTube", 'Watched&nbsp;<a href="https://www.youtube.com/watch?v=vid00000001">How tides work</a><br>'
                                '<a href="https://www.youtube.com/channel/UCtides">Tide Science</a><br>Jan 13, 2024, 7:00:00 PM PST<br>',
                     "<b>Products:</b><br>&emsp;YouTube<br>"),
                cell("YouTube", 'Watched a video that has been removed<br>Jan 13, 2024, 7:05:00 PM PST<br>', "<b>Products:</b><br>&emsp;YouTube<br>")),
            "My Activity/Gemini Apps/MyActivity.html": page(
                cell("Gemini Apps", "Prompted&nbsp;What makes tides?<br>Jan 13, 2025, 8:00:00 PM PST<br><p>The <b>moon</b>&#39;s pull.</p><p>And the sun's.</p>",
                     "<b>Products:</b><br>&emsp;Gemini Apps<br>")),
        })
        self.run_import()
        got = {r["title"]: r for r in self.of("google_activity")}
        s = got["tide tables"]
        self.assertEqual((s["kind"], s["ts"], s["url"]), ("search", "2024-01-14T02:57:09Z", "https://www.google.com/search?q=tide+tables"))
        self.assertEqual(got["How tides work"]["kind"], "media")
        self.assertIn("Tide Science", got["How tides work"]["text"])
        self.assertEqual(got["How tides work"]["ts"], "2024-01-14T03:00:00Z")
        self.assertIn("a video that has been removed", got)
        visit = [r for r in self.of("google_activity", "visit")]
        self.assertEqual([(r["title"], r["ts"]) for r in visit], [("How tides work", "2018-02-01T03:54:50Z")], "no zone: this Mac's clock")
        (ad,) = self.of("google_activity", "ad")
        self.assertEqual((ad["title"], ad["ts"]), ("Cheap flights", "2020-10-06T14:32:28Z"))
        turn = got["What makes tides?"]
        self.assertEqual(turn["kind"], "ai_turn")
        self.assertIn("The moon's pull.", turn["text"])
        self.assertIn("And the sun's.", turn["text"])
        self.assertNotIn("imported_documents", self.recs, "the pages aren't documents of their own")

    def test_pages_in_other_languages(self):
        self.files({
            "Meine Aktivitäten/Google Suche/MeineAktivitäten.html": page(
                cell("Google Suche", 'Nach&nbsp;<a href="https://www.google.com/search?q=Gezeiten">Gezeiten</a>&nbsp;gesucht<br>13.01.2024, 18:57:09 MEZ',
                     "<b>Produkte:</b><br>&emsp;Google Suche<br>")),
            "YouTube und YouTube Music/Verlauf/Wiedergabeverlauf.html": page(
                cell("YouTube", '<a href="https://www.youtube.com/watch?v=vid00000002">Wie Gezeiten entstehen</a>&nbsp;angesehen<br>'
                                '<a href="https://www.youtube.com/channel/UC2">Gezeitenkanal</a><br>13.01.2024, 19:00:00 MEZ<br>',
                     "<b>Produkte:</b><br>&emsp;YouTube<br>")),
        })
        self.files({"Mi actividad/YouTube/MiActividad.html": page(
            cell("YouTube", 'Has visto&nbsp;<a href="https://www.youtube.com/watch?v=vid00000003">Mareas</a><br>14 ene 2024, 10:00:00 CET<br>',
                 "<b>Productos:</b><br>&emsp;YouTube<br><b>Detalles:</b><br>&emsp;De los anuncios de Google<br>"))},
            root="takeout-20261002T000000Z/Takeout/")
        self.run_import()
        got = {r["ts"]: r for r in self.of("google_activity")}
        self.assertEqual(sorted(got), ["2024-01-13T17:57:09Z", "2024-01-13T18:00:00Z", "2024-01-14T09:00:00Z"])
        self.assertEqual((got["2024-01-13T17:57:09Z"]["kind"], got["2024-01-13T17:57:09Z"]["title"]), ("search", "Gezeiten"))
        self.assertEqual(got["2024-01-13T18:00:00Z"]["kind"], "media")
        self.assertEqual(got["2024-01-14T09:00:00Z"]["kind"], "ad", "an ad, in Spanish")


# ---------------------------------------------------------------- YouTube's own files, in other languages

class YouTubeTests(Base):
    def test_subscriptions_and_comments_named_and_headed_in_other_languages(self):
        # Takeout names YouTube's files and their columns in the account's language, the columns in the same order.
        self.files({
            "YouTube und YouTube Music/Abos/Abos.csv": "Kanal-ID,Kanal-URL,Kanaltitel\nUCtides,http://www.youtube.com/channel/UCtides,Gezeitenkanal\n",
            "YouTube und YouTube Music/Kommentare/Kommentare.csv":
                "Kommentar-ID,Kanal-ID,Zeitpunkt der Erstellung,Preis,ID des übergeordneten Kommentars,Beitrags-ID,Video-ID,Kommentartext\n"
                'c1,UCme,2024-01-13T18:57:09.123+00:00,0,,,vid00000001,"{""text"":""Toll erklärt!""}"\n',
        })
        self.files({"YouTube y YouTube Music/suscripciones/suscripciones.csv":
                    "ID del canal,URL del canal,Título del canal\nUCmar,http://www.youtube.com/channel/UCmar,Mareas\n"},
                   root="takeout-20261002T000000Z/Takeout/")
        self.run_import()
        self.assertEqual(sorted(r["title"] for r in self.of("youtube", "subscription")), ["Gezeitenkanal", "Mareas"])
        (c,) = self.of("youtube", "comment")
        self.assertEqual((c["text"], c["ts"], c["url"]), ("Toll erklärt!", "2024-01-13T18:57:09.123000Z",
                                                         "https://www.youtube.com/watch?v=vid00000001&lc=c1"))
        self.assertNotIn("takeout_other", self.recs)

    def test_a_broken_csv_stops_nothing(self):
        yt = "YouTube and YouTube Music/"
        self.files({yt + "subscriptions/subscriptions.csv": b"Channel Id,Channel Url,Channel Title\n\xff\xfe\x00\"unclosed\n",
                    yt + "comments/comments.csv": "Comment ID,Channel ID,Comment Create Timestamp,Price,Parent Comment ID,Post ID,Video ID,Comment Text\n"
                                                  'c1,UCme,2024-01-13T18:57:09+00:00,0,,,v1,"{""text"":""Still read""}"\n'})
        self.run_import()
        self.assertEqual([r["text"] for r in self.of("youtube", "comment")], ["Still read"])


# ---------------------------------------------------------------- more of the same, in other languages

class OtherLanguageTests(Base):
    def test_gmail_labels_in_french_and_spanish(self):
        # Gmail writes its own labels in the account's language, the whole list as one encoded word.
        self.files({"Mail/Tous les messages.mbox": mbox(
            mail(1, frm="Ada <ada.old@example.org>", labels="=?UTF-8?Q?Messages_envoy=C3=A9s,Important?="),
            mail(2, labels="Corbeille"), mail(3, labels="Papelera,Le=C3=ADdos"), mail(4, labels="Enviados"))})
        self.run_import()
        got = {r["id"]: r for r in self.of("gmail")}
        self.assertTrue(got["<m1@example.com>"]["is_me"], "Messages envoyés is Sent")
        self.assertEqual(got["<m2@example.com>"]["meta"].get("tier"), "deleted")
        self.assertEqual(got["<m3@example.com>"]["meta"].get("tier"), "deleted")
        self.assertTrue(got["<m4@example.com>"]["is_me"])

    def test_chat_times_in_british_english(self):
        self.files({"Google Chat/Groups/DM x/messages.json": {"messages": [
            {"creator": {"name": "Grace Hopper", "email": "grace@example.com"}, "created_date": "Tuesday, 7 February 2021 at 17:13:43 UTC",
             "text": "Tea?", "message_id": "m1"}]}})
        self.run_import()
        self.assertEqual([r["ts"] for r in self.of("google_chat")], ["2021-02-07T17:13:43Z"])

    def test_photos_in_german_and_the_index_page(self):
        self.files({"Google Fotos/Fotos von 2024/IMG_0001.jpg": b"one",
                    "Google Fotos/Fotos von 2024/IMG_0001.jpg.json": {"title": "IMG_0001.jpg", "photoTakenTime": {"timestamp": "1704067200"},
                                                                     "url": "https://photos.google.com/photo/one"},
                    "Google Fotos/Urlaub/IMG_0001.jpg.json": {"title": "IMG_0001.jpg", "photoTakenTime": {"timestamp": "1704067200"},
                                                             "url": "https://photos.google.com/photo/one"},
                    "Archiv_Übersicht.html": "<html><body><h1>Archiv-Übersicht</h1><p>Takeout</p></body></html>"})
        self.run_import()
        (photo,) = self.of("google_photos")
        self.assertEqual(photo["thread"], "Urlaub", "its album, not the year's folder")
        self.assertTrue(photo["meta"].get("files"))
        self.assertNotIn("imported_documents", self.recs, "Takeout's index page isn't a document")

    def test_saved_lists_in_german(self):
        self.files({"Gespeichert/Favoriten.csv": "Titel,Notiz,URL,Tags,Kommentar\nBäckerei,lecker,https://www.google.com/maps/place/B%C3%A4ckerei,,\n"})
        self.run_import()
        (r,) = self.of("google_saved")
        self.assertEqual((r["title"], r["url"], r["meta"]["list"], r["meta"]["what"]),
                         ("Bäckerei", "https://www.google.com/maps/place/B%C3%A4ckerei", "Favoriten", "place"))
        self.assertIn("lecker", r["text"])
