"""Other machines (machines.py): read over a stand-in ssh that runs the commands here, with HOME set to the other
machine's made-up home, then indexed beside this Mac's. Everyone and everything is made up.

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


class MachinesTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.home, self.box, self.corpus, self.bin, self.tmp = (self.root / d for d in ("home", "box", "corpus", "bin", "boxtmp"))
        for d in (self.home, self.box, self.corpus, self.bin, self.tmp):
            d.mkdir()
        # A command typed on both (the same history through a synced dotfile) and one only on the box
        (self.home / ".zsh_history").write_text(": 1767261600:0;git status\n")
        (self.box / ".zsh_history").write_text(": 1767261600:0;git status\n: 1767265200:0;make train\n")
        (self.home / ".ssh").mkdir()
        (self.home / ".ssh/config").write_text("Host box\n  HostName 100.64.0.9\nHost lab\n  HostName lab.example.edu\nHost *.corp\n  User x\n")
        (self.bin / "python3").symlink_to(sys.executable)
        # ssh: "box" runs the command here as if there (its HOME, its TMPDIR); "nopython" has no python3; else unreachable
        self.tool("ssh", f"""case " $* " in *" -G "*) for a; do last="$a"; done; echo "hostname $last"; echo "user ada"; exit 0;; esac
for a; do last="$a"; done
host=""; skip=""; for a; do
  if [ -n "$skip" ]; then skip=""; continue; fi
  case "$a" in -o|-F) skip=1;; -*) ;; *) [ -z "$host" ] && host="$a";; esac
done
echo "$host" >> "{self.root}/ssh.log"
case "$host" in
  box) HOME="{self.box}" TMPDIR="{self.tmp}" PATH="{self.bin}:/usr/bin:/bin" sh -c "$last";;
  nopython) exit 127;;
  *) echo "Permission denied (publickey)." >&2; exit 255;;
esac""")
        self.tool("tailscale", """echo '{"Self": {"HostName": "laptop"}, "Peer": {"a": {"HostName": "box", "DNSName": "box.tail.ts.net.", "OS": "linux", "Online": true, "TailscaleIPs": ["100.64.0.9"]}, "b": {"HostName": "phone", "DNSName": "phone.tail.ts.net.", "OS": "iOS"}, "c": {"HostName": "funnel-ingress-node"}}}'""")

    def tool(self, name, body):
        p = self.bin / name
        p.write_text("#!/bin/sh\n" + body + "\n")
        p.chmod(0o755)

    def env(self, **extra):
        env = {k: v for k, v in os.environ.items() if not k.startswith("UMP_")}
        env.update({"HOME": str(self.home), "CORPUS_DIR": str(self.corpus), "PATH": f"{self.bin}:/usr/bin:/bin", "UMP_MACHINE_SOURCES": "shell_history", **extra})
        return env

    def py(self, code, *args, **extra):
        r = subprocess.run([sys.executable, *(["-c", code] if code else args)], cwd=CONNECTORS, env=self.env(**extra), capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def records(self, name):
        f = self.corpus / "normalized" / f"{name}.jsonl"
        return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []

    def test_a_machine_read_beside_this_mac(self):
        self.py("import shell_history; shell_history.main()")
        self.py("import machines; machines.main()", UMP_MACHINES="box nopython lab")
        box = self.records("shell_history@box")
        self.assertEqual([r["text"] for r in box], ["make train"], "what this Mac has too is kept once, as this Mac's")
        self.assertTrue(box[0]["id"].startswith("@box/"))
        self.assertEqual((box[0]["source"], box[0]["meta"]["machine"]), ("shell_history", "box"))
        m = json.loads((self.corpus / "manifest.json").read_text())["machines"]["machines"]
        self.assertEqual(m["box"]["sources"]["shell_history"], {"count": 1, "also_on_this_mac": 1})
        self.assertEqual((m["nopython"], m["lab"]), ({"not_read": "no python3 there"}, {"not_read": "couldn't sign in without asking"}))
        self.assertEqual(list(self.tmp.iterdir()), [], "nothing left on the machine")
        self.assertFalse((self.box / "corpus").exists())

    def test_what_a_machine_no_longer_has_is_kept(self):
        self.py("import machines; machines.main()", UMP_MACHINES="box")
        (self.box / ".zsh_history").write_text(": 1767268800:0;ls\n")
        self.py("import machines; machines.main()", UMP_MACHINES="box")
        self.assertEqual(sorted(r["text"] for r in self.records("shell_history@box")), ["git status", "ls", "make train"])
        self.py("import machines; machines.main()", UMP_MACHINES="box", UMP_MACHINE_SOURCES="setup")
        sources = json.loads((self.corpus / "manifest.json").read_text())["machines"]["machines"]["box"]["sources"]
        self.assertEqual(sorted(sources), ["setup", "shell_history"], "a source not read this time keeps what was said of it")
        self.py("import machines; machines.main()", UMP_MACHINES="nopython")
        self.assertIn("box", json.loads((self.corpus / "manifest.json").read_text())["machines"]["machines"], "nor a machine not read this time")
        self.py("import machines; machines.main()", UMP_MACHINES="")
        self.assertEqual(len(self.records("shell_history@box")), 3, "a machine no longer chosen keeps what was read")

    def test_the_index_holds_both_and_reloading_one_keeps_the_other(self):
        self.py("import shell_history; shell_history.main()")
        # most of the library unchanged, so the index is updated in place, not built again from nothing
        (self.corpus / "normalized").mkdir(exist_ok=True)
        (self.corpus / "normalized/notes.jsonl").write_text("".join(json.dumps({"id": f"n{i}", "source": "notes", "kind": "note", "text": "x" * 200}) + "\n" for i in range(300)))
        self.py("import machines; machines.main(); import build_index; build_index.main()", UMP_MACHINES="box")
        db = self.corpus / "corpus.db"

        def rows():
            con = sqlite3.connect(db)
            try:
                return sorted(con.execute("select id like '@box/%', text from records where source = 'shell_history'"))
            finally:
                con.close()

        self.assertEqual(rows(), [(0, "git status"), (1, "make train")])
        # this Mac's history changes: its file is read again, and the box's records stay
        (self.home / ".zsh_history").write_text(": 1767261600:0;git status\n: 1767272400:0;open .\n")
        self.py("import shell_history; shell_history.main(); import build_index; build_index.main()")
        self.assertEqual(rows(), [(0, "git status"), (0, "open ."), (1, "make train")])
        # and the box's changes: this Mac's stay
        (self.box / ".zsh_history").write_text(": 1767276000:0;nvidia-smi\n")
        self.py("import machines; machines.main(); import build_index; build_index.main()", UMP_MACHINES="box")
        self.assertEqual(rows(), [(0, "git status"), (0, "open ."), (1, "make train"), (1, "nvidia-smi")])

    def test_the_same_thing_under_another_id_is_kept_once(self):
        norm = self.corpus / "normalized"
        norm.mkdir()
        mine = [{"id": "E1", "source": "contacts", "kind": "contact", "ts": "2026-09-26T01:16:45Z", "title": "Riley Park", "text": "Riley Park\nphone: +15550100"},
                {"id": "A1", "source": "contacts", "kind": "contact", "ts": "2026-09-26T01:16:45Z", "title": "Grace Hopper",
                 "text": "Grace Hopper\n+1 415 555 0100\ngrace@example.com"},
                {"id": "C1", "source": "contacts", "kind": "call", "ts": "2026-09-01T10:00:20Z", "thread_name": "Grace Hopper", "text": "call"}]
        (norm / "contacts.jsonl").write_text("".join(json.dumps(r) + "\n" for r in mine))
        theirs = [{**mine[1], "id": "B7", "ts": "2026-08-13T10:24:56Z"},  # the same contact, saved on that Mac another day
                  {**mine[2], "id": "C9", "ts": "2026-09-01T10:00:51Z"},  # the same call, its own id there
                  {**mine[2], "id": "C10", "ts": "2026-09-02T10:00:00Z"},  # another call
                  {**mine[1], "id": "A1", "text": "Grace Hopper\n+1 415 555 0100"},  # this Mac's contact, saved differently there
                  {"id": "S1", "source": "contacts", "kind": "contact", "ts": "2026-08-13T10:24:56Z", "title": "Riley Park", "text": "Riley Park\nphone: +15550100"},
                  {"id": "M1", "source": "contacts", "kind": "call", "ts": "2026-09-01T10:00:20Z", "thread_name": "Alan Turing", "text": "call"}]
        out = self.py("import json, machines; print(json.dumps(machines.merge('box', 'contacts', " + repr("".join(json.dumps(r) + "\n" for r in theirs).encode()) + ")))")
        self.assertEqual(json.loads(out), [2, 4])
        self.assertEqual(sorted(r["id"] for r in self.records("contacts@box")), ["@box/C10", "@box/M1"])
        # a second machine with the first one's call: kept once, as the first machine's
        out = self.py("import json, machines; print(json.dumps(machines.merge('lab', 'contacts', " + repr(json.dumps({**theirs[2], "id": "Z"}).encode()) + ")))")
        self.assertEqual(json.loads(out), [0, 1])

    def test_vms_on_this_mac_are_found_and_reached_by_their_own_ssh_config(self):
        self.tool("limactl", """echo '{"name": "dev", "status": "Running"}'; echo '{"name": "old", "status": "Stopped"}'""")
        self.tool("orbctl", """echo '[{"name": "ubuntu", "state": "running"}]'""")
        out = self.py(None, "machines.py", "--find")
        self.assertIn("lima:dev", out)
        self.assertIn("ubuntu@orb", out)
        self.assertRegex(out, r"lima:old .*stopped")
        log = (self.root / "ssh.log").read_text().split()
        self.assertIn("lima-dev", log, "a running Lima VM is checked through the ssh config Lima wrote")
        self.assertIn("ubuntu@orb", log)
        self.assertNotIn("lima-old", log, "a stopped VM isn't started")

    def test_finding_machines_asks_nothing_of_ssh_hosts_unless_told(self):
        out = self.py(None, "machines.py", "--find", UMP_MACHINES="box")
        lines = {l[2:].split()[0]: l for l in out.splitlines() if l.strip()}
        self.assertIn("tailscale   darwin, python3", lines["box"].lower())
        self.assertNotIn("phone", out, "a phone on the network isn't a machine to read")
        self.assertIn("not checked", lines["lab"], "an ssh host isn't signed in to (it may send a phone prompt)")
        self.assertNotIn("*.corp", out)
        self.assertNotIn("lab", (self.root / "ssh.log").read_text())
        out = self.py(None, "machines.py", "--find", "--ssh")
        self.assertIn("lab", (self.root / "ssh.log").read_text())


if __name__ == "__main__":
    unittest.main()
