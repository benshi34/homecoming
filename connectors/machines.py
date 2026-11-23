"""Your other machines (off until "Other machines" is switched on in Network: it goes over ssh): what the same connectors find on the Macs and Linux machines you reach over ssh (a Mac mini,
a cloud workstation, a server), kept beside this Mac's and marked with the machine each came from.

Which machines, by themselves: your own Macs and Linux machines on Tailscale (not one shared with you, nor a
coworker's on a work network) and this Mac's running Linux VMs (Lima's as "lima:<vm>", OrbStack's as "<vm>@orb"),
each that one ssh call that never asks for anything (BatchMode) signs in to and that has python3. A host only in
~/.ssh/config isn't tried by itself (signing in to some, a university cluster, sends a phone prompt): name it in
corpus/machines.json, which can also take one out or turn this off ({"read": ["devbox"], "skip": ["nas"],
"auto": false, "sources": {"devbox": ["ai_coding", "shell_history"]}}: what to read on one, else all but
NOT_THERE's). `UMP_MACHINES` (ssh names, space-separated) reads only those. `python3 machines.py --find` lists them
all, a "*" by the ones read (`--ssh` tries the ssh config hosts too).

Reading one: these connectors go to a new temporary folder there over ssh, run with python3 there, reading that
machine's files in place (no copies on its disk), and come back as their normalized files; the folder is then
removed. Nothing is installed or left on the machine. A record goes in normalized/<source>@<machine>.jsonl with its
id as "@<machine>/<id>" and meta.machine; one this Mac (or a machine read before) already has is kept once, as
the first's: the same id (an iMessage through iCloud, a commit), or the same thing under another id (a contact, a call,
a synced browser visit: see fingerprints). Like a source on this Mac, what a machine no longer has is kept."""

import concurrent.futures
import importlib.util
import io
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import tarfile
import threading
import time
from pathlib import Path

from common import CORPUS, HOME, NORM, RAW, online, read_manifest, tailscale_devices, tailscale_status, write_manifest

HERE = Path(__file__).resolve().parent
CONFIG = CORPUS / "machines.json"
# Not read on another machine: this one (machines), what's slow and big there (every document's text, every photo's
# labels), the phone's (it comes from a backup on this Mac), and exports dropped on this Mac.
NOT_THERE = {"machines", "photos", "health", "imports"}
SSH = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=4"]
TIMEOUT = int(os.environ.get("UMP_MACHINE_TIMEOUT") or 3600)


def config():
    try:
        c = json.loads(CONFIG.read_text())
        return c if isinstance(c, dict) else {}
    except (OSError, ValueError):
        return {}


_chosen = None


def chosen(cancelled=None):
    """The machines read: UMP_MACHINES if set (and only those); else the ones found by themselves (auto: your own
    Tailscale machines and this Mac's running VMs that sign in without asking and have python3), with machines.json's
    "read" added (an ssh config host, which isn't tried by itself) and its "skip" taken out; "auto": false for only
    "read"'s."""
    global _chosen
    if os.environ.get("UMP_MACHINES") is not None:
        return os.environ["UMP_MACHINES"].split()
    if _chosen is None:
        c = config()
        named = [str(h) for h in c.get("read") or []]
        found = auto(cancelled) if c.get("auto", True) is not False else []
        skip = {str(h) for h in c.get("skip") or []}
        _chosen = [m for m in dict.fromkeys([*named, *found]) if m not in skip]
    return _chosen


def listed():
    """For a settings page, without contacting any machine: each one found, with "read" (whether a run reads it). One
    found by itself counts as read unless skipped; the run still passes over it if it turns out not to sign in or have
    python3."""
    if os.environ.get("UMP_MACHINES") is not None:
        named, found_too, skip = set(os.environ["UMP_MACHINES"].split()), False, set()
    else:
        c = config()
        named, skip = {str(h) for h in c.get("read") or []}, {str(h) for h in c.get("skip") or []}
        found_too = c.get("auto", True) is not False
    return [{**m, "read": m["name"] not in skip and (m["name"] in named or (found_too and bool(m.get("mine"))))}
            for m in find(contact=False)]


def auto(cancelled=None):
    return [m["name"] for m in find(cancelled=cancelled) if m.get("mine") and m.get("reachable") and m.get("python")]


def target(machine):
    """ssh's arguments for a machine: a name ssh knows (its config, Tailscale, "<vm>@orb" for an OrbStack machine), or
    "lima:<vm>" for a Lima VM, reached through the ssh config Lima writes for it."""
    if machine.startswith("lima:"):
        vm = machine[5:]
        return ["-F", str(HOME / ".lima" / vm / "ssh.config"), "--", f"lima-{vm}"]
    return ["--", machine]


def prefix(machine):
    return f"@{machine}/"


# ---------------------------------------------------------------- finding them

def tailscale_peers():
    d = tailscale_status()
    out = []
    for p in tailscale_devices(d):
        name = (p.get("DNSName") or "").split(".")[0] or p.get("HostName")
        if name and p.get("OS") in ("macOS", "linux"):
            # yours: signed in as you, not shared into your network by someone else (nor a coworker's)
            mine = not p.get("ShareeNode") and p.get("UserID") is not None and p.get("UserID") == (d.get("Self") or {}).get("UserID")
            out.append({"name": name, "via": "tailscale", "os": p.get("OS"), "online": bool(p.get("Online")),
                        "addresses": p.get("TailscaleIPs") or [], "mine": mine})
    return out


def vms():
    """The Linux VMs on this Mac that ssh reaches: Lima's ("lima:<vm>") and OrbStack's ("<vm>@orb"). One that's stopped
    is listed, not started."""
    out = []
    for cmd, parse in ((["limactl", "list", "--json"], lambda d: (f"lima:{d['name']}", d.get("status") == "Running")),
                       (["orbctl", "list", "--format", "json"], lambda d: (f"{d['name']}@orb", d.get("state") == "running"))):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            continue
        text = r.stdout.strip()
        items = json.loads(text) if text.startswith("[") else [json.loads(l) for l in text.splitlines() if l.startswith("{")]
        for d in items:
            try:
                name, running = parse(d)
            except (KeyError, TypeError):
                continue
            out.append({"name": name, "via": "VM on this Mac", "online": running, "mine": True, **({} if running else {"why": "stopped"})})
    return out


def anywhere_to_look():
    """Whether this Mac could have other machines to read, cheaply (the app asks every minute): your own Mac or Linux
    machine on Tailscale, Lima or OrbStack set up (their folders), or machines.json naming one."""
    if config().get("read") or (HOME / ".lima").is_dir() or (HOME / ".orbstack").is_dir():
        return True
    return any(p["mine"] for p in tailscale_peers())


def ssh_hosts():
    from setup import ssh_lines  # the ssh config, Includes and all
    out, names = [], set()
    for line in ssh_lines(HOME / ".ssh/config"):
        m = re.match(r"(?i)\s*host\s*[ =]\s*(.+)", line)
        for name in (m.group(1).split() if m else []):
            if not re.search(r"[*?!]", name) and name not in names:
                names.add(name)
                out.append({"name": name, "via": "ssh config"})
    return out


SIGN_IN = re.compile(r"permission denied|host key verification failed|too many authentication failures", re.I)
RETRY_AFTER = float(os.environ.get("UMP_MACHINE_RETRY_AFTER") or 10)


def ssh_failed(stderr):
    """What ssh's exit 255 was: a sign-in it couldn't do without asking, or a connection that didn't happen (and ssh's
    own words for it, so a dropped link isn't reported as a sign-in problem)."""
    if SIGN_IN.search(stderr):
        return "couldn't sign in without asking"
    said = [l.strip() for l in stderr.splitlines() if l.strip() and not l.lower().startswith(("warning", "debug"))]
    return f"couldn't connect: {said[-1][:160]}" if said else "couldn't connect"


class Stopped(RuntimeError):
    """Permission was removed during a read. Keep what was already brought home."""


def permitted(cancelled):
    if not online("machines"):
        cancelled.set()
    if cancelled.is_set():
        raise Stopped("Other machines is off in Network")


def ssh_run(args, *, data=None, timeout, cancelled):
    """An SSH call with its own process group, stopped when either Network switch goes off.

    Keep stdin open after the bundle: remote_run watches it for a closed connection. communicate(input=...)
    would close it as soon as the bundle was sent, before the remote readers had finished.
    """
    permitted(cancelled)
    p = subprocess.Popen(args, stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    pipe, sender = p.stdin, None
    if pipe is not None:
        p.stdin = None  # communicate drains stdout/stderr without closing the connection's input

        def send():
            try:
                pipe.write(data)
                pipe.flush()
            except (OSError, ValueError):  # SSH closed, or the read was stopped during the upload
                pass

        sender = threading.Thread(target=send, daemon=True)
        sender.start()
    deadline = time.monotonic() + timeout
    try:
        while True:
            permitted(cancelled)
            left = deadline - time.monotonic()
            if left <= 0:
                raise subprocess.TimeoutExpired(args, timeout)
            try:
                out, err = p.communicate(timeout=min(0.1, left))
                return subprocess.CompletedProcess(args, p.returncode, out, err)
            except subprocess.TimeoutExpired:
                pass
    finally:
        # Terminate the group, including a ProxyCommand, rather than leaving children behind with open pipes.
        if p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        if sender is not None:
            sender.join(timeout=2)
            if sender.is_alive():
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                sender.join()
            pipe.close()  # EOF also stops remote_run if sshd leaves a non-interactive remote shell alive
        try:
            p.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            p.communicate()


def check(name, cancelled=None):
    """One ssh call that asks for nothing: (reachable, what it is)."""
    try:
        r = ssh_run([*SSH[:-6], "-o", "ConnectTimeout=6", *target(name), "uname -s; command -v python3 && python3 -V"],
                    timeout=25, cancelled=cancelled if cancelled is not None else threading.Event())
    except Stopped as e:
        return {"reachable": False, "why": str(e)}
    except (OSError, subprocess.TimeoutExpired):
        return {"reachable": False, "why": "no answer"}
    stdout, stderr = r.stdout.decode(errors="replace"), r.stderr.decode(errors="replace")
    if r.returncode == 255:
        return {"reachable": False, "why": ssh_failed(stderr)}
    lines = stdout.split()
    return {"reachable": True, "system": lines[0] if lines else "?", "python": "Python" in stdout}


def resolved(name):
    """Where ssh would go for a config host, and as whom (`ssh -G`: the config applied, nothing sent)."""
    try:
        r = subprocess.run(["ssh", "-G", "--", name], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    return dict(l.split(" ", 1) for l in r.stdout.splitlines() if " " in l and l.split(" ", 1)[0] in ("hostname", "user", "proxycommand"))


def find(with_ssh=False, also=(), contact=True, cancelled=None):
    """The machines there are to read. contact=False lists them from Tailscale's and the ssh config's own state and
    sends nothing to any of them (for a settings page to draw)."""
    peers = tailscale_peers()
    found = {}
    hosts = ssh_hosts()
    with concurrent.futures.ThreadPoolExecutor(16) as pool:
        where = dict(zip([h["name"] for h in hosts], pool.map(resolved, [h["name"] for h in hosts])))
    for p in peers:
        # a peer the ssh config names (by its address or name) is reached the way the config says, as that host
        alias = next((h for h, g in where.items() if g.get("hostname") in (*p["addresses"], p["name"]) or
                      str(g.get("hostname", "")).startswith(p["name"] + ".")), None)
        found[alias or p["name"]] = {**p, "name": alias or p["name"], **({"tailscale_name": p["name"]} if alias else {})}
    listed = {tuple(sorted(where.get(n, {}).items())) for n in found if where.get(n)}
    for m in vms():
        found[m["name"]] = m
    for m in hosts:
        key = tuple(sorted(where.get(m["name"], {}).items()))
        if m["name"] not in found and not (key and key in listed):
            listed.add(key)
            found[m["name"]] = {**m, **({"via": "ssh config (a command)"} if where.get(m["name"], {}).get("proxycommand") else {})}
    for m in found.values():
        if m["via"] == "tailscale" and not m.get("online"):
            m["why"] = "offline"
    if not contact:
        return sorted(found.values(), key=lambda m: m["name"])
    if not online("machines"):  # listed from Tailscale's and the ssh config's own state; nothing is sent to any of them
        for m in found.values():
            m.setdefault("why", "not tried: Other machines is off in Network")
        return sorted(found.values(), key=lambda m: m["name"])
    # Never a sign-in attempt at a Tailscale machine that isn't yours (shared with you, a coworker's) unless you named it
    theirs = lambda m: m["via"] == "tailscale" and not m.get("mine")
    to_check = [n for n, m in found.items() if n in also or not theirs(m) and (
        (m["via"] in ("tailscale", "VM on this Mac") and m.get("online", True)) or with_ssh)]
    cancelled = cancelled if cancelled is not None else threading.Event()
    with concurrent.futures.ThreadPoolExecutor(16) as pool:
        for name, res in zip(to_check, pool.map(lambda name: check(name, cancelled), to_check)):
            found[name].update(res)
    return sorted(found.values(), key=lambda m: (not m.get("reachable"), m["name"]))


# ---------------------------------------------------------------- reading one

# Packages the connectors use that are plain Python, so they go along (the other machine rarely has them); a compiled
# one (cryptography, for Signal) can't: built for this Mac, not that machine.
PURE = ("pypdf", "typing_extensions")


CARRIED = ("ai_coding.json",)  # corpus settings a machine's read follows too


def bundle():
    """These connectors as a gzipped tar: no tests, no vendored phone tools, no caches; and PURE's packages that this
    Python has, in _deps/."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for p in sorted(HERE.rglob("*")):
            rel = p.relative_to(HERE)
            if p.is_file() and rel.parts[0] not in ("tests", "vendor", "_deps") and "__pycache__" not in rel.parts and p.suffix in (".py", ".txt", ".json"):
                t.add(p, arcname=f"connectors/{rel}")
        for name in PURE:
            try:
                spec = importlib.util.find_spec(name)
            except (ImportError, ValueError):
                spec = None
            if not spec or not spec.origin:
                continue
            where = Path(spec.origin)
            files = sorted(where.parent.rglob("*.py")) if where.name == "__init__.py" else [where]
            if where.name == "__init__.py" and any(f.suffix in (".so", ".pyd", ".dylib") for f in where.parent.rglob("*")):
                continue
            for f in files:
                if "__pycache__" not in f.parts:
                    t.add(f, arcname=f"connectors/_deps/{f.relative_to(where.parent.parent if where.name == '__init__.py' else where.parent)}")
        # Your settings for what's read go along, so a machine leaves out what this Mac does (ai_coding.json's leave_out).
        # Never network.json: there, nothing goes online.
        for name in CARRIED:
            if (CORPUS / name).is_file():
                t.add(CORPUS / name, arcname=f"corpus/{name}")
    return buf.getvalue()


def connectors(machine):
    """What to run there: every connector but NOT_THERE's, or what machines.json's "sources" names for it (or
    UMP_MACHINE_SOURCES for all of them)."""
    from run_all import CONNECTORS
    try:
        named = (json.loads(CONFIG.read_text()).get("sources") or {}).get(machine)
    except (OSError, ValueError, AttributeError):
        named = None
    if os.environ.get("UMP_MACHINE_SOURCES"):
        named = os.environ["UMP_MACHINE_SOURCES"].split()
    return [c for c in CONNECTORS if c != "machines" and (c in named if named else c not in NOT_THERE)]


def fetch(machine, names, cancelled=None):
    """Run the connectors there; {file name: bytes} of what they wrote, and the run's log."""
    cancelled = cancelled if cancelled is not None else threading.Event()
    permitted(cancelled)
    data = bundle()
    script = ('d=$(mktemp -d "${TMPDIR:-/tmp}/homecoming.XXXXXX") || exit 70; trap \'rm -rf "$d"\' EXIT; '
              'trap \'exit 130\' HUP INT TERM; '
              f'head -c {len(data)} | tar -xzf - -C "$d" || exit 71; '
              'cd "$d/connectors" || exit 72; command -v python3 >/dev/null || exit 127; '
              f'CORPUS_DIR="$d/corpus" python3 remote_run.py --watch-stdin {" ".join(shlex.quote(n) for n in names)} >&2 || exit $?; '
              'cd "$d/corpus" 2>/dev/null && COPYFILE_DISABLE=1 tar -czf - normalized manifest.json 2>/dev/null')
    for attempt in (1, 2):  # a dropped connection gets one more try; a refused sign-in doesn't
        r = ssh_run([*SSH, *target(machine), script], data=data, timeout=TIMEOUT, cancelled=cancelled)
        log = r.stderr.decode(errors="replace")
        if r.returncode != 255 or SIGN_IN.search(log) or attempt == 2:
            break
        until = time.monotonic() + RETRY_AFTER
        while time.monotonic() < until:
            permitted(cancelled)
            cancelled.wait(min(0.1, until - time.monotonic()))
    if r.returncode == 127:
        raise RuntimeError("no python3 there")
    if r.returncode == 255:
        raise RuntimeError(ssh_failed(log))
    out = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(r.stdout), mode="r:gz") as t:
            for m in t.getmembers():
                if m.isfile() and re.fullmatch(r"(normalized/\w[\w.-]*\.jsonl|manifest\.json)", m.name):
                    out[m.name] = t.extractfile(m).read()
    except tarfile.TarError:
        raise RuntimeError(f"nothing came back (exit {r.returncode})")
    return out, log


# An id that's a database's row number ("safari:1234", "book:7") is only unique on its own device: another Mac's row 1234
# is some other visit. Such a record is the same as one here only when what it says matches (its fingerprints), which a
# copy migrated from this Mac does. Ids that name the thing itself (a message's guid, a contact's uuid) match on their own.
ROW_NUMBER = re.compile(r"(?:[a-z_]+:)?\d+")


def fingerprints(r):
    """What makes two records the same thing, whatever id each device gave it: a contact or a call has its own id on
    every Mac, a synced browser visit too. The same kind, time (to the minute), author, conversation, title, text and
    link; or, for a long text or one of several lines, all of that but the time (a contact's time is when this device
    last saved it)."""
    def norm(v):
        return re.sub(r"\s+", " ", str(v or "")).strip().lower()
    text = norm(r.get("text"))[:500]
    base = (r.get("kind"), norm(r.get("author")), norm(r.get("thread_name")), norm(r.get("title")), text, norm(r.get("url")))
    out = [hash((str(r.get("ts") or "")[:16], *base))]
    raw = str(r.get("text") or "").strip()
    if len(text) >= 40 or "\n" in raw and len(text) >= 20:  # a long text, or a card ("Riley Park\nphone: +1..."): not a coincidence
        out.append(hash(("untimed", *base)))
    return out


def already(source, machine):
    """The ids and fingerprints of what this Mac (and every other machine read) holds of a source: a record also there
    is kept once, as the first's."""
    ids, prints = set(), set()
    for p in [NORM / f"{source}.jsonl", *sorted(NORM.glob(f"{source}@*.jsonl"))]:
        if p.stem == f"{source}@{machine}" or not p.exists():
            continue
        for line in p.open(encoding="utf-8", errors="replace"):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            rid = str(r.get("id", ""))
            ids.add(rid.split("/", 1)[1] if rid.startswith("@") and "/" in rid else rid)
            prints.update(fingerprints(r))
    return ids, prints


def merge(machine, source, data):
    """A machine's records of a source into normalized/<source>@<machine>.jsonl: its ids marked as the machine's,
    what this Mac has left out, and what an earlier read found and this one didn't kept."""
    (mine, prints), pre = already(source, machine), prefix(machine)
    NORM.mkdir(parents=True, exist_ok=True)
    path = NORM / f"{source}@{machine}.jsonl"
    tmp = path.with_suffix(".jsonl.tmp")
    seen, n, same = set(), 0, 0
    with open(tmp, "w", encoding="utf-8") as f:
        for line in data.decode("utf-8", "replace").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if not isinstance(r, dict) or r.get("id") is None or r.get("source") != source:
                continue
            if (str(r["id"]) in mine and not ROW_NUMBER.fullmatch(str(r["id"]))) or any(fp in prints for fp in fingerprints(r)):
                same += 1
                continue
            r["id"] = pre + str(r["id"])
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            r["meta"] = {**(r.get("meta") if isinstance(r.get("meta"), dict) else {}), "machine": machine}
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
        if path.exists():  # what this machine had before and no longer does (its browser keeps weeks, not years)
            for line in path.open(encoding="utf-8", errors="replace"):
                try:
                    old = json.loads(line)
                except ValueError:
                    continue
                bare = str(old.get("id", ""))[len(pre):] if isinstance(old, dict) else ""
                if isinstance(old, dict) and old.get("id") not in seen and (bare not in mine or ROW_NUMBER.fullmatch(bare)) \
                        and not any(fp in prints for fp in fingerprints(old)):
                    f.write(line if line.endswith("\n") else line + "\n")
                    seen.add(old.get("id"))
                    n += 1
    if n:
        tmp.replace(path)
    else:  # nothing of its own: everything it had is on this Mac (or nothing was ever read)
        tmp.unlink(missing_ok=True)
        path.unlink(missing_ok=True)
    return n, same


def read(machine, fetched=None):
    """A machine's records into normalized/: fetched there (or given, fetched already), then merged here."""
    t = time.time()
    files, log = fetched if fetched is not None else fetch(machine, connectors(machine))
    (RAW / "machines").mkdir(parents=True, exist_ok=True)
    (RAW / "machines" / f"{machine}.log").write_text(log)
    there = json.loads(files.get("manifest.json") or b"{}")
    sources = {}
    for name, data in sorted(files.items()):
        if name.startswith("normalized/"):
            source = name[len("normalized/"):-len(".jsonl")]
            if "@" in source:
                continue
            try:
                n, same = merge(machine, source, data)
            except (OSError, UnicodeError) as e:  # one source's file stops no other
                sources[source] = {"not_read": f"{type(e).__name__}: {e}"[:200]}
                continue
            if n or same:
                sources[source] = {"count": n, **({"also_on_this_mac": same} if same else {}),
                                   **({"notes": there[source]["notes"]} if isinstance(there.get(source), dict) and there[source].get("notes") else {})}
    a = there.get("_access")
    if isinstance(a, dict) and a.get("full_disk_access") is False:  # what Remote Login can't read there, and the fix
        sources["_access"] = a
    for name, said in there.items():  # one that couldn't run there, and why
        if isinstance(said, dict) and said.get("not_read") and name not in sources:
            sources[name] = {"not_read": said["not_read"]}
    return {"sources": sources, "seconds": round(time.time() - t)}


AT_ONCE = int(os.environ.get("UMP_MACHINES_AT_ONCE") or 3)


def main():
    manifest = read_manifest()
    before = (manifest.get("machines") or {}).get("machines") or {}
    if not online("machines"):  # nothing goes over ssh; what earlier reads brought stays
        print("[machines] off in Network: no machine read", flush=True)
        manifest["machines"] = {**(manifest.get("machines") or {}), "off": True}
        write_manifest(manifest)
        return
    entry = {"avenue": __doc__.split("\n\n")[0], "machines": dict(before)}
    cancelled = threading.Event()
    targets = []

    def stop(signum, frame):
        cancelled.set()  # the SSH workers have their own process groups; let them close and reap those too
        raise KeyboardInterrupt

    handlers = {s: signal.signal(s, stop) for s in (signal.SIGINT, signal.SIGTERM)}
    # Read there a few at a time (each is mostly waiting on that machine); merged here one at a time, as each comes
    # back, so two machines with the same message don't both keep it.
    try:
        targets = chosen(cancelled)
        permitted(cancelled)
        with concurrent.futures.ThreadPoolExecutor(AT_ONCE) as pool:
            started = {pool.submit(lambda m: (time.time(), fetch(m, connectors(m), cancelled)), m): m for m in targets}
            for done in concurrent.futures.as_completed(started):
                machine = started[done]
                try:
                    t, fetched = done.result()
                    entry["machines"][machine] = {**read(machine, fetched), "seconds": round(time.time() - t)}
                except Stopped:
                    continue  # retain this machine's previous records and manifest, including its counts
                except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError) as e:
                    entry["machines"][machine] = {"not_read": str(e) if not isinstance(e, subprocess.TimeoutExpired) else "took too long"}
                # a source not read this time keeps what the last read said of it (_access is this read's to say;
                # so is why a reader that ran this time couldn't before: it may run now)
                ran = set(connectors(machine))
                old = {k: v for k, v in ((before.get(machine) or {}).get("sources") or {}).items()
                       if k != "_access" and not (k in ran and isinstance(v, dict) and "not_read" in v)}
                if old and "sources" in entry["machines"][machine]:
                    entry["machines"][machine]["sources"] = {**old, **entry["machines"][machine]["sources"]}
                print(f"[machines] {machine}: {entry['machines'][machine]}", flush=True)
    except Stopped:
        pass
    finally:
        if cancelled.is_set():
            if not online("machines"):
                entry["off"] = True
            print("[machines] stopped; earlier reads kept", flush=True)
        # A machine no longer chosen keeps what was read from it (taking it out is a separate choice).
        kept = sorted({p.stem.split("@", 1)[1] for p in NORM.glob("*@*.jsonl")} - set(targets))
        if kept:
            entry["no_longer_read"] = kept
        manifest["machines"] = {**entry, "count": sum(s.get("count", 0) for m in entry["machines"].values() for s in (m.get("sources") or {}).values())}
        try:
            write_manifest(manifest)
        finally:
            for s, handler in handlers.items():
                signal.signal(s, handler)


def check_access(machine):
    """Only whether Remote Login there can read what's behind Full Disk Access (no connector runs): after the steps
    were followed. Kept in the manifest with the machine, as a read keeps it."""
    if not online("machines"):
        return {"not_read": "Other machines is off in Network"}
    files, _ = fetch(machine, [])
    a = json.loads(files.get("manifest.json") or b"{}").get("_access")
    manifest = read_manifest()
    entry = manifest.setdefault("machines", {}).setdefault("machines", {}).setdefault(machine, {})
    a = a if isinstance(a, dict) else {"full_disk_access": None}  # None: not a Mac, nothing to give
    if a.get("full_disk_access") is False:
        entry.setdefault("sources", {})["_access"] = a
    else:
        entry.get("sources", {}).pop("_access", None)  # fixed: the steps go
    write_manifest(manifest)
    return a


if __name__ == "__main__":
    if "--check" in sys.argv:
        print(json.dumps(check_access(sys.argv[sys.argv.index("--check") + 1])))
    elif "--find" in sys.argv:
        for m in find(with_ssh="--ssh" in sys.argv, also=[str(h) for h in config().get("read") or []]):
            state = (f"{m.get('system')}, {'python3' if m.get('python') else 'no python3'}" if m.get("reachable")
                     else m.get("why") or "not checked")
            print(f"{'*' if m['name'] in chosen() else ' '} {m['name']:40s} {m['via']:11s} {state}")
    else:
        main()
