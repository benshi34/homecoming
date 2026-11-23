"""Other machines (machines.py): read over a stand-in ssh that runs the commands here, with HOME set to the other
machine's made-up home, then indexed beside this Mac's. Everyone and everything is made up.

Run: python3 -m unittest discover -s connectors/tests -p 'test_*.py'
"""
import json
import os
import shlex
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

CONNECTORS = Path(__file__).resolve().parents[1]
BRIDGE = CONNECTORS.parent / "desktop/py/bridge.py"


class MachinesTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.home, self.box, self.corpus, self.bin, self.tmp = (self.root / d for d in ("home", "box", "corpus", "bin", "boxtmp"))
        for d in (self.home, self.box, self.corpus, self.bin, self.tmp):
            d.mkdir()
        (self.corpus / "network.json").write_text('{"sources": {"machines": true}}')  # switched on in Network
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
  box2) HOME="{self.root}/box2" TMPDIR="{self.tmp}" PATH="{self.bin}:/usr/bin:/bin" sh -c "$last";;
  box|theirs|coworker) HOME="{self.box}" TMPDIR="{self.tmp}" PATH="{self.bin}:/usr/bin:/bin" sh -c "$last";;
  nopython) exit 127;;
  down) echo "ssh: connect to host down port 22: Operation timed out" >&2; exit 255;;
  flaky) if [ -e "{self.root}/flaky.once" ]; then HOME="{self.box}" TMPDIR="{self.tmp}" PATH="{self.bin}:/usr/bin:/bin" sh -c "$last"
         else touch "{self.root}/flaky.once"; echo "Connection closed by UNKNOWN port 65535" >&2; exit 255; fi;;
  *) echo "Permission denied (publickey)." >&2; exit 255;;
esac""")
        self.tool("tailscale", """echo '{"Self": {"HostName": "laptop", "UserID": 1}, "Peer": {"a": {"HostName": "box", "DNSName": "box.tail.ts.net.", "OS": "linux", "Online": true, "TailscaleIPs": ["100.64.0.9"], "UserID": 1}, "b": {"HostName": "phone", "DNSName": "phone.tail.ts.net.", "OS": "iOS", "UserID": 1}, "c": {"HostName": "funnel-ingress-node"}, "d": {"HostName": "box", "DNSName": "theirs.tail.ts.net.", "OS": "linux", "Online": true, "TailscaleIPs": ["100.64.0.20"], "UserID": 2, "ShareeNode": true}, "e": {"HostName": "box", "DNSName": "coworker.tail.ts.net.", "OS": "macOS", "Online": true, "TailscaleIPs": ["100.64.0.21"], "UserID": 3}, "f": {"HostName": "old", "DNSName": "old.tail.ts.net.", "OS": "linux", "Online": false, "UserID": 1}}}'""")

    def tool(self, name, body):
        p = self.bin / name
        p.write_text("#!/bin/sh\n" + body + "\n")
        p.chmod(0o755)

    def env(self, **extra):
        env = {k: v for k, v in os.environ.items() if not k.startswith("UMP_")}
        env.update({"HOME": str(self.home), "CORPUS_DIR": str(self.corpus), "PATH": f"{self.bin}:/usr/bin:/bin", "UMP_MACHINE_SOURCES": "shell_history",
                    "UMP_VOLUMES": str(self.root / "no-volumes"), **extra})  # not this Mac's own drives
        return env

    def py(self, code, *args, **extra):
        r = subprocess.run([sys.executable, *(["-c", code] if code else args)], cwd=CONNECTORS, env=self.env(**extra), capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def records(self, name):
        f = self.corpus / "normalized" / f"{name}.jsonl"
        return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []

    def wait_for(self, predicate, why, timeout=10):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            if predicate():
                return
            time.sleep(0.02)
        self.fail(why)

    def network(self, value):
        tmp = self.corpus / "network.json.tmp"
        tmp.write_text(json.dumps(value))
        tmp.replace(self.corpus / "network.json")  # the app's settings handler writes it this way

    def blocking_reader(self):
        """The existing stand-in SSH, with a remote shell in a separate session. Killing the client cannot kill
        that shell: only EOF reaching remote_run, its process-group stop, and the shell's EXIT trap clean it up.
        """
        ssh = self.bin / "ssh"
        slowhome = self.root / "slowhome"
        slowhome.mkdir()
        (slowhome / ".zsh_history").write_text(": 1767268800:0;make bench\n")
        launch = shlex.quote("import subprocess, sys; sys.exit(subprocess.call(['sh', '-c', sys.argv[1]], start_new_session=True))")
        ssh.write_text(ssh.read_text().replace('  box2)',
            f'  slow|slow2|queued) TEST_HOST="$host" HOME="{slowhome}" TMPDIR="{self.tmp}" PATH="{self.bin}:/usr/bin:/bin" '
            f'{shlex.quote(sys.executable)} -c {launch} "$last";;\n  box2)'))
        reader = self.root / "slow_reader.py"
        reader.write_text(f'''import json, os, signal, subprocess, sys, time
from pathlib import Path

def main():
    host = os.environ.get("TEST_HOST")
    if not host or os.environ.get("TEST_WAIT") != "1":
        return
    root = Path({str(self.root)!r})
    child_code = "import signal, sys, time; from pathlib import Path; signal.signal(signal.SIGTERM, lambda *a: (Path(sys.argv[1]).touch(), sys.exit(0))); print('ready', flush=True); time.sleep(120)"
    child = subprocess.Popen([sys.executable, "-c", child_code, str(root / (host + ".child-stopped"))], stdout=subprocess.PIPE)
    child.stdout.readline()
    def stopped(*args):
        (root / (host + ".stopped")).touch()
        child.wait(timeout=2)
        raise SystemExit(143)
    signal.signal(signal.SIGTERM, stopped)
    (root / (host + ".running")).write_text(json.dumps({{"pid": os.getpid(), "child": child.pid, "shell": os.getppid(), "group": os.getpgrp()}}))
    time.sleep(120)
''')
        (self.bin / "python3").unlink()
        self.tool("python3", f'if [ "$1" = remote_run.py ]; then cp {shlex.quote(str(reader))} reminders.py; fi\nexec {shlex.quote(sys.executable)} "$@"')

        def stop_readers():
            for marker in self.root.glob("*.running"):
                ids = json.loads(marker.read_text())
                for pid in (ids["child"], ids["pid"], ids["shell"]):
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

        self.addCleanup(stop_readers)

    def bridge_read(self, *names, **extra):
        p = subprocess.Popen([sys.executable, str(BRIDGE), "run", *names], cwd=CONNECTORS,
                             env=self.env(**extra), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             start_new_session=True)

        def stop():
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGKILL)
            try:
                p.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                p.stdout.close()
                p.stderr.close()

        self.addCleanup(stop)
        return p

    def stalled_ssh(self, ignore_term=False):
        """A stuck SSH/ProxyCommand that never reads the upload. Its child exits only if the whole group is stopped."""
        script = self.root / "stalled_ssh.py"
        script.write_text(f'''import json, os, signal, subprocess, sys, time
from pathlib import Path
root = Path({str(self.root)!r})
if "-G" in sys.argv:
    print("hostname " + sys.argv[-1])
    print("user ada")
    sys.exit(0)
code = "import signal, sys, time; from pathlib import Path; signal.signal(signal.SIGTERM, {'signal.SIG_IGN' if ignore_term else 'lambda *a: (Path(sys.argv[1]).touch(), sys.exit(0))'}); print('ready', flush=True); time.sleep(120)"
child = subprocess.Popen([sys.executable, "-c", code, str(root / "proxy.stopped")], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
child.stdout.readline()
{'signal.signal(signal.SIGTERM, signal.SIG_IGN)' if ignore_term else ''}
(root / "proxy.running").write_text(json.dumps({{"pid": child.pid, "ssh": os.getpid()}}))
time.sleep(120)
''')
        self.tool("ssh", f'exec {shlex.quote(sys.executable)} {shlex.quote(str(script))} "$@"')

        def stop_proxy():
            marker = self.root / "proxy.running"
            if marker.exists():
                for pid in json.loads(marker.read_text()).values():
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

        self.addCleanup(stop_proxy)

    def stop_during_read(self, network):
        self.blocking_reader()
        # Both completed machines and the previous read of a now-blocked machine must stay in the library.
        self.py("import machines; machines.main()", UMP_MACHINES="box slow")
        before = self.records("shell_history@slow")
        self.assertTrue(before)
        old = json.loads((self.corpus / "manifest.json").read_text())["machines"]["machines"]["slow"]
        (self.box / ".zsh_history").write_text(": 1767272400:0;make test\n")
        (self.root / "ssh.log").unlink()
        p = self.bridge_read("machines", "shell_history", UMP_MACHINES="box slow slow2 queued", UMP_MACHINES_AT_ONCE="2",
                             UMP_MACHINE_SOURCES="shell_history reminders", TEST_WAIT="1")
        self.wait_for(lambda: all((self.root / (h + ".running")).exists() for h in ("slow", "slow2")), "two SSH reads never started")
        self.wait_for(lambda: "make test" in [r["text"] for r in self.records("shell_history@box")], "the completed machine was not merged")
        self.network(network)
        out, err = p.communicate(timeout=8)
        self.assertEqual(p.returncode, 0, err + out)
        events = [json.loads(line) for line in out.splitlines()]
        self.assertEqual(events[-1], {"type": "finished", "failed": []}, "the bridge job must finish")
        self.assertTrue(any(e["type"] == "done" and e.get("connector") == "shell_history" for e in events), "local reads still work offline")
        for host in ("slow", "slow2"):
            self.assertTrue((self.root / (host + ".stopped")).exists(), "the remote reader survived the connection closing")
            self.assertTrue((self.root / (host + ".child-stopped")).exists(), "the remote reader's child was not stopped with its group")
        self.assertEqual(list(self.tmp.iterdir()), [], "the remote shell's EXIT trap must remove its temporary folder")
        self.assertNotIn("queued", (self.root / "ssh.log").read_text().split(), "a waiting read started after permission was removed")
        self.assertEqual(self.records("shell_history@slow"), before)
        manifest = json.loads((self.corpus / "manifest.json").read_text())["machines"]
        self.assertTrue(manifest["off"])
        self.assertEqual(manifest["machines"]["slow"], old, "the stopped machine keeps its previous counts too")
        with sqlite3.connect(self.corpus / "corpus.db") as db:
            self.assertEqual(db.execute("select count(*) from records where id like '@slow/%'").fetchone()[0], len(before))
            self.assertEqual(db.execute("select count(*) from records where text = 'make test'").fetchone()[0], 1)

    def test_turning_other_machines_off_stops_running_ssh_and_keeps_earlier_reads(self):
        self.stop_during_read({"sources": {}})

    def test_turning_the_internet_off_stops_running_ssh_and_keeps_earlier_reads(self):
        self.stop_during_read({"offline": True, "sources": {"machines": True}})

    def test_turning_off_during_a_retry_wait_does_not_try_ssh_again(self):
        p = self.bridge_read("--no-index", "machines", UMP_MACHINES="down", UMP_MACHINE_RETRY_AFTER="30")
        log = self.root / "ssh.log"
        self.wait_for(lambda: log.exists() and "down" in log.read_text(), "SSH never tried the unreachable machine")
        self.network({"offline": True, "sources": {"machines": True}})
        out, err = p.communicate(timeout=5)
        self.assertEqual(p.returncode, 0, err + out)
        self.assertEqual(log.read_text().split(), ["down"], "permission was removed, so there is no second attempt")

    def test_cancelling_a_stalled_upload_stops_the_ssh_process_group(self):
        self.stalled_ssh()
        p = self.bridge_read("--no-index", "machines", UMP_MACHINES="box")
        self.wait_for(lambda: (self.root / "proxy.running").exists(), "SSH never started")
        self.network({"sources": {}})
        out, err = p.communicate(timeout=8)
        self.assertEqual(p.returncode, 0, err + out)
        self.assertTrue((self.root / "proxy.stopped").exists(), "the SSH child must receive SIGTERM with its process group")

    def test_a_timed_out_ssh_call_stops_its_process_group(self):
        self.stalled_ssh()
        p = self.bridge_read("--no-index", "machines", UMP_MACHINES="box", UMP_MACHINE_TIMEOUT="1")
        out, err = p.communicate(timeout=8)
        self.assertEqual(p.returncode, 0, err + out)
        self.assertTrue((self.root / "proxy.stopped").exists(), "an SSH timeout must stop its children too")
        entry = json.loads((self.corpus / "manifest.json").read_text())["machines"]["machines"]["box"]
        self.assertEqual(entry, {"not_read": "took too long"})

    def test_an_ssh_group_ignoring_term_is_killed_during_a_stalled_upload(self):
        self.stalled_ssh(ignore_term=True)
        p = self.bridge_read("--no-index", "machines", UMP_MACHINES="box")
        self.wait_for(lambda: (self.root / "proxy.running").exists(), "SSH never started")
        self.network({"sources": {}})
        out, err = p.communicate(timeout=8)
        self.assertEqual(p.returncode, 0, err + out)
        pid = json.loads((self.root / "proxy.running").read_text())["pid"]

        def gone():
            try:
                os.kill(pid, 0)
                return False
            except ProcessLookupError:
                return True

        self.wait_for(gone, "the SSH group ignored TERM and was not killed")

    def test_permission_removal_stays_cancelled_if_the_switch_is_turned_back_on(self):
        self.py('''import machines, threading
from unittest.mock import patch
cancelled = threading.Event()
with patch.object(machines, 'online', return_value=False):
    try:
        machines.permitted(cancelled)
    except machines.Stopped:
        pass
assert cancelled.is_set()
with patch.object(machines, 'online', return_value=True):
    try:
        machines.permitted(cancelled)
    except machines.Stopped:
        pass
    else:
        raise AssertionError('a cancelled read must not resume when permission returns')
''')

    def test_direct_ssh_check_cannot_start_when_network_is_off(self):
        self.network({"sources": {}})
        self.py('''import machines
from unittest.mock import patch
with patch.object(machines.subprocess, 'Popen', side_effect=AssertionError('SSH started while Network was off')):
    result = machines.check('box')
assert result['reachable'] is False
assert 'off in Network' in result['why']
''')

    def test_turning_off_during_discovery_stops_the_probe_process_group(self):
        self.stalled_ssh()
        p = self.bridge_read("--no-index", "machines")  # no UMP_MACHINES: discover your own Tailscale machines
        self.wait_for(lambda: (self.root / "proxy.running").exists(), "the SSH probe never started")
        self.network({"offline": True, "sources": {"machines": True}})
        out, err = p.communicate(timeout=8)
        self.assertEqual(p.returncode, 0, err + out)
        self.assertTrue((self.root / "proxy.stopped").exists(), "the discovery probe must stop its children too")

    def test_stopping_the_bridge_job_also_stops_ssh_and_cleans_the_remote_folder(self):
        self.blocking_reader()
        p = self.bridge_read("--no-index", "machines", UMP_MACHINES="slow", UMP_MACHINE_SOURCES="reminders", TEST_WAIT="1")
        self.wait_for(lambda: (self.root / "slow.running").exists(), "the remote reader never started")
        os.killpg(p.pid, signal.SIGTERM)  # desktop/src/main/bridge.ts stops queue jobs this way
        out, err = p.communicate(timeout=8)
        self.assertEqual(p.returncode, 1, err + out)
        self.assertIn('"type": "finished"', out)
        self.assertTrue((self.root / "slow.child-stopped").exists())
        self.assertEqual(list(self.tmp.iterdir()), [], "stopping a job must also run remote cleanup")

    def test_off_in_network_nothing_goes_over_ssh(self):
        self.py("import shell_history; shell_history.main()")
        self.py("import machines; machines.main()", UMP_MACHINES="box")
        before = self.records("shell_history@box")
        self.assertTrue(before)
        (self.root / "ssh.log").unlink()
        for off in ('{"sources": {}}', '{"offline": true, "sources": {"machines": true}}'):
            (self.corpus / "network.json").write_text(off)
            self.py("import machines; machines.main()", UMP_MACHINES="box")
            out = self.py(None, "machines.py", "--find", "--ssh")
            self.assertFalse((self.root / "ssh.log").exists(), "a machine was reached with Other machines off")
            self.assertIn("off in Network", out)
            self.assertEqual(self.records("shell_history@box"), before)  # what an earlier read brought stays

    def test_settings_for_what_is_read_go_along_and_network_json_never_does(self):
        (self.corpus / "ai_coding.json").write_text('{"leave_out": ["~/evals"]}')
        out = self.py("import io, tarfile, machines; print(sorted(n for n in tarfile.open(fileobj=io.BytesIO(machines.bundle())).getnames() if n.startswith('corpus/')))")
        self.assertEqual(out.strip(), "['corpus/ai_coding.json']")

    @unittest.skipUnless(sys.platform == "darwin", "Full Disk Access is a Mac's")
    def test_check_says_what_remote_login_cant_read_and_the_steps(self):
        mail, vols = self.box / "Library/Mail", self.root / "volumes"
        (vols / "Travel SSD").mkdir(parents=True)
        (vols / "Open Drive").mkdir()
        mail.mkdir(parents=True)
        for d in (mail, vols / "Travel SSD"):
            d.chmod(0)
            self.addCleanup(d.chmod, 0o755)
        out = json.loads(self.py(None, "machines.py", "--check", "box", UMP_VOLUMES=str(vols)))
        self.assertEqual((out["full_disk_access"], out["blocked"], out["drives_blocked"]), (False, ["Mail"], ["Travel SSD"]))
        self.assertIn("Remote Login", out["fix"])
        self.assertEqual(json.loads((self.corpus / "manifest.json").read_text())["machines"]["machines"]["box"]["sources"]["_access"], out)
        for d in (mail, vols / "Travel SSD"):
            d.chmod(0o755)
        out = json.loads(self.py(None, "machines.py", "--check", "box", UMP_VOLUMES=str(vols)))
        self.assertEqual((out["full_disk_access"], out.get("fix")), (True, None))

    def test_fix_steps_follow_the_macos_version(self):
        out = self.py("import remote_run as r; print(r.fix_steps('13.0')); print(r.fix_steps('12.7'))")  # Ventura added the switch
        new, old = out.strip().split("\n")
        self.assertIn("General > Sharing", new)
        self.assertIn("Allow full disk access for remote users", new)
        self.assertIn("sshd-keygen-wrapper", old)

    def test_listing_for_settings_contacts_no_machine(self):
        (self.corpus / "machines.json").write_text('{"skip": ["box"], "read": ["lab"]}')
        out = json.loads(self.py("import json, machines; print(json.dumps(machines.listed()))"))
        read = {m["name"]: m["read"] for m in out}
        self.assertEqual({k: read.get(k) for k in ("box", "old", "lab", "theirs", "coworker")},
                         {"box": False, "old": True, "lab": True, "theirs": False, "coworker": False})  # skipped, yours, named, not yours
        self.assertFalse((self.root / "ssh.log").exists() and (self.root / "ssh.log").read_text().strip(), "no ssh while listing")

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

    def test_two_machines_read_at_once_keep_what_both_have_once(self):
        (self.root / "box2").mkdir()
        (self.root / "box2/.zsh_history").write_text(": 1767265200:0;make train\n: 1767265300:0;htop\n")
        self.py("import machines; machines.main()", UMP_MACHINES="box box2", UMP_MACHINES_AT_ONCE="2")
        texts = sorted(r["text"] for m in ("box", "box2") for r in self.records(f"shell_history@{m}"))
        self.assertEqual(texts, ["git status", "htop", "make train"])
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_plain_python_packages_go_along_and_what_cant_run_there_says_why(self):
        import io, tarfile
        sys.path.insert(0, str(CONNECTORS))
        import machines
        names = tarfile.open(fileobj=io.BytesIO(machines.bundle())).getnames()
        try:
            import pypdf  # noqa: F401
            self.assertIn("connectors/_deps/pypdf/__init__.py", names)
        except ImportError:
            pass
        self.assertFalse([n for n in names if n.endswith((".so", ".pyd", ".dylib")) or n.startswith("connectors/tests/")])
        # a connector whose package that machine lacks: a note, not just a traceback in the log
        self.py("import remote_run; remote_run.main(['no_such_reader'])")
        said = json.loads((self.corpus / "manifest.json").read_text())["no_such_reader"]
        self.assertEqual(said, {"not_read": "needs no_such_reader on this machine's Python"})

    @unittest.skipIf(sys.platform != "darwin" or os.geteuid() == 0, "Full Disk Access is a Mac's, and root reads anything")
    def test_a_mac_without_full_disk_access_for_remote_login_says_so(self):
        (self.box / "Library/Messages").mkdir(parents=True)
        db = self.box / "Library/Messages/chat.db"
        db.write_bytes(b"")
        db.chmod(0)
        self.addCleanup(db.chmod, 0o644)
        self.py("import machines; machines.main()", UMP_MACHINES="box")
        box = json.loads((self.corpus / "manifest.json").read_text())["machines"]["machines"]["box"]["sources"]
        self.assertEqual((box["_access"]["full_disk_access"], box["_access"]["blocked"]), (False, ["Messages"]))
        self.assertIn("Remote Login", box["_access"]["fix"])

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

    def test_why_a_reader_couldnt_run_goes_once_it_runs(self):
        (self.corpus / "manifest.json").write_text(json.dumps({"machines": {"machines": {"box": {"sources": {
            "apple_notes": {"not_read": "needs cryptography on this machine's Python"},  # installed there since; nothing to read
            "setup": {"not_read": "needs yaml on this machine's Python"}}}}}}))  # not run this time: still the last word
        self.py("import machines; machines.main()", UMP_MACHINES="box", UMP_MACHINE_SOURCES="apple_notes")
        sources = json.loads((self.corpus / "manifest.json").read_text())["machines"]["machines"]["box"]["sources"]
        self.assertEqual(sources, {"setup": {"not_read": "needs yaml on this machine's Python"}})

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

    def test_a_row_number_is_the_same_visit_only_when_it_says_the_same(self):
        norm = self.corpus / "normalized"
        norm.mkdir()
        mine = [{"id": "safari:12", "source": "browser_history", "kind": "visit", "ts": "2026-11-01T09:00:00Z", "title": "Docs", "url": "https://example.com/docs"},
                {"id": "safari:13", "source": "browser_history", "kind": "visit", "ts": "2026-11-01T09:05:00Z", "title": "Home", "url": "https://example.com/"},
                {"id": "f00d-guid", "source": "browser_history", "kind": "visit", "ts": "2026-11-01T09:06:00Z", "title": "A", "url": "https://example.com/a"}]
        (norm / "browser_history.jsonl").write_text("".join(json.dumps(r) + "\n" for r in mine))
        theirs = [{**mine[0], "ts": "2026-10-02T17:30:00Z", "title": "Weather", "url": "https://example.org/weather"},  # its own row 12: another visit
                  mine[1],  # a copy migrated from this Mac: row 13 and all it says
                  {**mine[2], "title": "A, renamed"}]  # an id that names the thing: the same visit, whatever else changed
        data = "".join(json.dumps(r) + "\n" for r in theirs).encode()
        out = self.py("import json, machines; print(json.dumps(machines.merge('box', 'browser_history', " + repr(data) + ")))")
        self.assertEqual(json.loads(out), [1, 2])
        self.assertEqual([(r["id"], r["title"]) for r in self.records("browser_history@box")], [("@box/safari:12", "Weather")])
        # read again: the box's row 12 is kept from before, not taken for this Mac's
        out = self.py("import json, machines; print(json.dumps(machines.merge('box', 'browser_history', b'')))")
        self.assertEqual(json.loads(out), [1, 0])

    def test_a_dropped_connection_is_tried_again_and_isnt_called_a_sign_in(self):
        self.py("import machines; machines.main()", UMP_MACHINES="flaky down", UMP_MACHINE_RETRY_AFTER="0")
        m = json.loads((self.corpus / "manifest.json").read_text())["machines"]["machines"]
        self.assertEqual(m["flaky"]["sources"]["shell_history"]["count"], 2, "read on the second try")
        self.assertEqual(m["down"], {"not_read": "couldn't connect: ssh: connect to host down port 22: Operation timed out"})
        self.assertEqual((self.root / "ssh.log").read_text().split().count("down"), 2)

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

    def test_machines_are_read_by_themselves_and_only_yours(self):
        env = {k: v for k, v in self.env().items() if k != "UMP_MACHINES"}
        run = lambda: subprocess.run([sys.executable, "-c", "import machines; machines.main()"], cwd=CONNECTORS, env=env, capture_output=True, text=True, timeout=300)
        self.assertEqual(run().returncode, 0)
        read = json.loads((self.corpus / "manifest.json").read_text())["machines"]["machines"]
        self.assertEqual(sorted(read), ["box"], "your own machine, not one shared with you, a coworker's, one offline, nor an ssh host")
        self.assertEqual([r["text"] for r in self.records("shell_history@box")], ["git status", "make train"])
        self.assertNotIn("lab", (self.root / "ssh.log").read_text())
        self.assertFalse({"theirs", "coworker"} & set((self.root / "ssh.log").read_text().split()), "no sign-in tried at a machine not yours")
        # machines.json adds one, takes one out, or turns it off
        (self.corpus / "machines.json").write_text(json.dumps({"read": ["lab"], "skip": ["box"]}))
        boxes = (self.root / "ssh.log").read_text().split().count("box")
        run()
        log = (self.root / "ssh.log").read_text().split()
        self.assertIn("lab", log)
        self.assertEqual(log.count("box"), boxes + 1, "found (one check), but skipped: not read")
        self.assertEqual(json.loads((self.corpus / "manifest.json").read_text())["machines"]["machines"]["lab"], {"not_read": "couldn't sign in without asking"})
        (self.corpus / "machines.json").write_text(json.dumps({"auto": False}))
        before = len(log)
        run()
        self.assertEqual(len((self.root / "ssh.log").read_text().split()), before, "auto off: not even looked for")

    def test_finding_machines_asks_nothing_of_ssh_hosts_unless_told(self):
        out = self.py(None, "machines.py", "--find", UMP_MACHINES="box")
        lines = {l[2:].split()[0]: l for l in out.splitlines() if l.strip()}
        self.assertIn("tailscale   darwin, python3", lines["box"].lower())
        self.assertNotIn("phone", out, "a phone on the network isn't a machine to read")
        self.assertNotIn("funnel", out, "nor Tailscale's own relay")
        self.assertRegex(out, r"old .*offline")
        self.assertIn("not checked", lines["lab"], "an ssh host isn't signed in to (it may send a phone prompt)")
        self.assertNotIn("*.corp", out)
        self.assertNotIn("lab", (self.root / "ssh.log").read_text())
        out = self.py(None, "machines.py", "--find", "--ssh")
        self.assertIn("lab", (self.root / "ssh.log").read_text())


if __name__ == "__main__":
    unittest.main()
