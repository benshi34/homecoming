"""Reading on a schedule, without the app open: your layouts (and the agent session in each pane) every few minutes,
so a freeze or a terminal overwriting its own saved layout leaves a recent version to rebuild from; and every source
now and then. The app reads every source daily while it's open; this is for a corpus kept without it, or alongside.

    python3 schedule.py install [--layouts-every 10m] [--all-every 1d]   (either can be "off")
    python3 schedule.py status
    python3 schedule.py uninstall

On a Mac each job is a LaunchAgent (~/Library/LaunchAgents/org.homecoming.schedule.<job>.plist); on Linux a systemd
user timer, or a crontab line without systemd. Installing again replaces what's there. The jobs run this Python and
these connectors, from where they are now, on the corpus in CORPUS_DIR (or the default) at install time.

A job doesn't start while its last run is still going, and nothing runs with the disk nearly full (under 2 GB free
where the corpus is): a full disk is when a read is likeliest to fail halfway, and when the Mac needs the space most.
Each job's log is corpus/raw/schedule/<job>.log, its last lines kept."""

import fcntl
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from common import CORPUS, HOME, RAW

HERE = Path(__file__).resolve().parent
JOBS = ("layouts", "all")
DEFAULT = {"layouts": "10m", "all": "1d"}
LABEL = "org.homecoming.schedule.{}"
MIN_FREE = int(os.environ.get("UMP_SCHEDULE_MIN_FREE") or 2 << 30)
LOG_KEEP = 200_000  # bytes of each job's log kept


def seconds(every):
    """"10m", "6h", "1d", "90s" -> seconds; "off" -> None."""
    if str(every).lower() in ("off", "0", "none", "never"):
        return None
    m = re.fullmatch(r"(\d+)\s*([smhd]?)", str(every).strip().lower())
    if not m or int(m.group(1)) == 0:
        raise SystemExit(f"not a cadence: {every!r} (say 10m, 6h, 1d or off)")
    return int(m.group(1)) * {"": 60, "s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]


def command(job):
    return [sys.executable, str(HERE / "schedule.py"), "run", job]


def platform():
    if os.environ.get("UMP_SCHEDULER") in KINDS:  # the tests: each kind, on any machine
        return os.environ["UMP_SCHEDULER"]
    if sys.platform == "darwin":
        return "launchd"
    if sys.platform.startswith("linux"):
        if shutil.which("systemctl") and subprocess.run(["systemctl", "--user", "show-environment"], capture_output=True).returncode == 0:
            return "systemd"
        if shutil.which("crontab"):
            return "cron"
    return None


# ---------------------------------------------------------------- each kind of scheduler

def plist_path(job):
    return HOME / "Library/LaunchAgents" / f"{LABEL.format(job)}.plist"


def launchd_install(job, every):
    import plistlib
    args = command(job)
    if job == "all" and os.path.exists("/usr/bin/caffeinate"):
        args = ["/usr/bin/caffeinate", "-i", *args]  # a full read over other machines shouldn't stall on sleep
    p = plist_path(job)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(plistlib.dumps({
        "Label": LABEL.format(job), "ProgramArguments": args, "StartInterval": every, "RunAtLoad": job == "layouts",
        "EnvironmentVariables": {"CORPUS_DIR": str(CORPUS), "PYTHONWARNINGS": "ignore"},
        "ProcessType": "Background", "LowPriorityIO": True, "Nice": 10,
        "StandardOutPath": "/dev/null", "StandardErrorPath": "/dev/null"}))  # the job writes its own log
    launchd_remove(job, keep_file=True)
    r = subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(p)], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"launchctl couldn't load {p.name}: {r.stderr.strip()}")


def launchd_remove(job, keep_file=False):
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL.format(job)}"], capture_output=True)
    if not keep_file:
        plist_path(job).unlink(missing_ok=True)


def launchd_installed(job):
    p = plist_path(job)
    if not p.exists():
        return None
    import plistlib
    try:
        return plistlib.loads(p.read_bytes()).get("StartInterval")
    except Exception:
        return None


def unit(job):
    return HOME / ".config/systemd/user" / f"homecoming-{job}"


def systemd_install(job, every):
    import shlex
    d = unit(job).parent
    d.mkdir(parents=True, exist_ok=True)
    unit(job).with_suffix(".service").write_text(
        f"[Unit]\nDescription=Homecoming: read {job}\n\n[Service]\nType=oneshot\nNice=10\nIOSchedulingClass=idle\n"
        f"Environment=CORPUS_DIR={shlex.quote(str(CORPUS))}\nExecStart={' '.join(shlex.quote(a) for a in command(job))}\n")
    unit(job).with_suffix(".timer").write_text(
        f"[Unit]\nDescription=Homecoming: read {job} every {every}s\n\n[Timer]\n"
        f"OnBootSec={'60' if job == 'layouts' else every}\nOnUnitActiveSec={every}\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n")
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    r = subprocess.run(["systemctl", "--user", "enable", "--now", f"homecoming-{job}.timer"], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"systemctl couldn't start homecoming-{job}.timer: {r.stderr.strip()}")


def systemd_remove(job):
    subprocess.run(["systemctl", "--user", "disable", "--now", f"homecoming-{job}.timer"], capture_output=True)
    for suffix in (".timer", ".service"):
        unit(job).with_suffix(suffix).unlink(missing_ok=True)
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)


def systemd_installed(job):
    t = unit(job).with_suffix(".timer")
    m = re.search(r"^OnUnitActiveSec=(\d+)", t.read_text(), re.M) if t.exists() else None
    return int(m.group(1)) if m else None


CRON_TAG = "# homecoming-schedule:{}"


def crontab():
    r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    return r.stdout.splitlines() if r.returncode == 0 else []


def set_crontab(lines):
    subprocess.run(["crontab", "-"], input="".join(l + "\n" for l in lines), text=True, check=True)


def cron_install(job, every):
    import shlex
    m = max(1, every // 60)
    when = f"*/{m} * * * *" if m < 60 else f"0 */{max(1, m // 60)} * * *" if m < 1440 else f"0 4 */{max(1, m // 1440)} * *"
    line = f"{when} CORPUS_DIR={shlex.quote(str(CORPUS))} {' '.join(shlex.quote(a) for a in command(job))} {CRON_TAG.format(job)} every={every}"
    set_crontab([l for l in crontab() if CRON_TAG.format(job) + " " not in l] + [line])


def cron_remove(job):
    lines = crontab()
    if any(CRON_TAG.format(job) + " " in l for l in lines):
        set_crontab([l for l in lines if CRON_TAG.format(job) + " " not in l])


def cron_installed(job):
    m = next((re.search(r"every=(\d+)", l) for l in crontab() if CRON_TAG.format(job) + " " in l), None)
    return int(m.group(1)) if m else None


KINDS = {"launchd": (launchd_install, launchd_remove, launchd_installed), "systemd": (systemd_install, systemd_remove, systemd_installed),
         "cron": (cron_install, cron_remove, cron_installed)}


# ---------------------------------------------------------------- running a job

def log(job, line):
    p = RAW / "schedule" / f"{job}.log"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
    if p.stat().st_size > LOG_KEEP * 2:
        p.write_bytes(p.read_bytes()[-LOG_KEEP:])


def run(job):
    free = shutil.disk_usage(CORPUS if CORPUS.exists() else CORPUS.parent).free
    if free < MIN_FREE:
        log(job, f"skipped: {free >> 20} MB free where the corpus is")
        return
    CORPUS.mkdir(parents=True, exist_ok=True)
    with open(CORPUS / f".schedule-{job}.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            log(job, "skipped: the last run is still going")
            return
        t = time.time()
        sys.path.insert(0, str(HERE))
        try:
            if job == "layouts":
                import setup
                setup.main(setup.LAYOUTS)
            else:
                import run_all
                run_all.main([])
            log(job, f"done in {time.time() - t:.0f}s")
        except BaseException as e:  # noqa: BLE001 - said in the log, then the scheduler's own exit code
            log(job, f"failed after {time.time() - t:.0f}s: {type(e).__name__}: {e}"[:400])
            raise


# ---------------------------------------------------------------- the commands

def main(argv):
    if not argv or argv[0] not in ("install", "uninstall", "status", "run"):
        sys.exit(__doc__)
    if argv[0] == "run":
        return run(argv[1] if len(argv) > 1 and argv[1] in JOBS else sys.exit(f"run {'|'.join(JOBS)}"))
    kind = platform()
    if not kind:
        sys.exit("no scheduler here this knows (launchd on a Mac; systemd or cron on Linux)")
    install, remove, installed = KINDS[kind]
    if argv[0] == "install":
        want = dict(DEFAULT)
        for i, a in enumerate(argv):
            for job in JOBS:
                if a == f"--{job}-every" and i + 1 < len(argv):
                    want[job] = argv[i + 1]
        for job in JOBS:
            every = seconds(want[job])
            if every is None:
                remove(job)
                print(f"{job}: off")
            else:
                install(job, every)
                print(f"{job}: every {want[job]} ({kind}), on {CORPUS}")
    elif argv[0] == "uninstall":
        for job in JOBS:
            remove(job)
        print(f"removed ({kind})")
    else:
        for job in JOBS:
            every = installed(job)
            p = RAW / "schedule" / f"{job}.log"
            last = p.read_text(errors="replace").splitlines()[-1] if p.exists() and p.stat().st_size else "not run yet"
            print(f"{job}: {'every ' + str(every) + 's' if every else 'off'}; last: {last}")


if __name__ == "__main__":
    main(sys.argv[1:])
