"""Reading on a schedule (schedule.py): installing each kind (launchd, a systemd user timer, cron) against stand-ins
that record what they're asked, again and away, and what a job does when it runs. Everything is made up.

Run: python3 -m unittest discover -s connectors/tests -p 'test_*.py'
"""
import fcntl
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CONNECTORS = Path(__file__).resolve().parents[1]


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.home, self.corpus, self.bin = self.root / "home", self.root / "corpus", self.root / "bin"
        for d in (self.home, self.corpus, self.bin):
            d.mkdir()
        self.tool("launchctl", f'echo "$@" >> "{self.root}/launchctl.log"')
        self.tool("systemctl", f'echo "$@" >> "{self.root}/systemctl.log"')
        # crontab: -l prints what's kept (none yet: exit 1, as cron says), - replaces it
        self.tool("crontab", f'f="{self.root}/crontab"; if [ "$1" = -l ]; then [ -f "$f" ] && cat "$f" || exit 1; else cat > "$f"; fi')

    def tool(self, name, body):
        p = self.bin / name
        p.write_text("#!/bin/sh\n" + body + "\n")
        p.chmod(0o755)

    def schedule(self, *args, **env):
        e = {k: v for k, v in os.environ.items() if not k.startswith("UMP_")}
        e.update({"HOME": str(self.home), "CORPUS_DIR": str(self.corpus), "PATH": f"{self.bin}:/usr/bin:/bin", **env})
        r = subprocess.run([sys.executable, "schedule.py", *args], cwd=CONNECTORS, env=e, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_launchd_installs_again_without_doubling_and_comes_out(self):
        self.schedule("install", UMP_SCHEDULER="launchd")
        out = self.schedule("install", "--layouts-every", "5m", "--all-every", "6h", UMP_SCHEDULER="launchd")
        agents = sorted((self.home / "Library/LaunchAgents").iterdir())
        self.assertEqual([p.name for p in agents], ["org.homecoming.schedule.all.plist", "org.homecoming.schedule.layouts.plist"])
        layouts = plistlib.loads(agents[1].read_bytes())
        self.assertEqual(layouts["ProgramArguments"], [sys.executable, str(CONNECTORS / "schedule.py"), "run", "layouts"])
        self.assertEqual((layouts["StartInterval"], layouts["EnvironmentVariables"]["CORPUS_DIR"]), (300, str(self.corpus)))
        self.assertEqual(plistlib.loads(agents[0].read_bytes())["StartInterval"], 6 * 3600)
        # each load replaces the one before (unloaded first), so it never runs twice
        log = (self.root / "launchctl.log").read_text().splitlines()
        self.assertEqual(sum(1 for l in log if l.startswith("bootstrap") and "layouts" in l), 2)
        self.assertEqual(sum(1 for l in log if l.startswith("bootout") and l.endswith("org.homecoming.schedule.layouts")), 2)
        self.assertIn("layouts: every 5m", out)
        self.schedule("install", "--all-every", "off", UMP_SCHEDULER="launchd")
        self.assertFalse((self.home / "Library/LaunchAgents/org.homecoming.schedule.all.plist").exists(), "off takes it out")
        self.schedule("uninstall", UMP_SCHEDULER="launchd")
        self.assertEqual(list((self.home / "Library/LaunchAgents").iterdir()), [])

    def test_systemd_timers(self):
        self.schedule("install", "--layouts-every", "10m", UMP_SCHEDULER="systemd")
        d = self.home / ".config/systemd/user"
        self.assertIn("OnUnitActiveSec=600", (d / "homecoming-layouts.timer").read_text())
        self.assertIn(f"Environment=CORPUS_DIR={self.corpus}", (d / "homecoming-layouts.service").read_text())
        self.assertIn("enable --now homecoming-layouts.timer", (self.root / "systemctl.log").read_text())
        self.assertIn("layouts: every 600s", self.schedule("status", UMP_SCHEDULER="systemd"))
        self.schedule("uninstall", UMP_SCHEDULER="systemd")
        self.assertEqual(list(d.iterdir()), [])

    def test_cron_keeps_your_own_lines(self):
        (self.root / "crontab").write_text("0 9 * * * /usr/bin/true # mine\n")
        self.schedule("install", UMP_SCHEDULER="cron")
        self.schedule("install", "--layouts-every", "15m", UMP_SCHEDULER="cron")
        lines = (self.root / "crontab").read_text().splitlines()
        self.assertEqual(lines[0], "0 9 * * * /usr/bin/true # mine")
        self.assertEqual(len(lines), 3, lines)
        self.assertTrue(any(l.startswith("*/15 * * * * ") and l.endswith("homecoming-schedule:layouts every=900") for l in lines))
        self.assertTrue(any(l.startswith("0 4 */1 * * ") and "run all" in l for l in lines))
        self.schedule("uninstall", UMP_SCHEDULER="cron")
        self.assertEqual((self.root / "crontab").read_text(), "0 9 * * * /usr/bin/true # mine\n")

    def test_a_layouts_run_keeps_what_it_didnt_read(self):
        (self.home / ".zshrc").write_text("alias gs='git status'\n")
        (self.home / ".config/zellij/layouts").mkdir(parents=True)
        (self.home / ".config/zellij/layouts/made.kdl").write_text("// This file was generated by a tool\nlayout {}\n")
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "UMP_MAY_SCRIPT": "{}"}
        self.tool("ps", "exit 0")  # no agents running
        self.tool("tmux", "printf 'work\\t0\\tsh\\t5d1e,80x24,0,0\\t0\\t%s\\tsh\\t%%0\\n' \"$HOME\"")
        r = subprocess.run([sys.executable, "-c", "import setup; setup.main()"], cwd=CONNECTORS, capture_output=True, text=True,
                           env={**os.environ, "HOME": str(self.home), "CORPUS_DIR": str(self.corpus), **env}, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.tool("tmux", "printf 'work\\t0\\tsh\\t5d1e,80x24,0,0\\t0\\t%s/x\\tsh\\t%%0\\n' \"$HOME\"")
        self.schedule("run", "layouts", **env)
        what = [json.loads(l)["meta"]["what"] for l in (self.corpus / "normalized/setup.jsonl").read_text().splitlines()]
        self.assertIn("file:~/.zshrc", what, "a config the layouts run didn't read")
        self.assertIn("file:~/.config/zellij/layouts/made.kdl", what, "nor a generated one")
        self.assertEqual(what.count("layout:tmux"), 2, "the layout's new version beside the last")
        self.assertIn("done in", (self.corpus / "raw/schedule/layouts.log").read_text())

    def test_setup_waits_for_another_setup_on_the_same_corpus(self):
        import time
        env = {**os.environ, "HOME": str(self.home), "CORPUS_DIR": str(self.corpus), "PATH": f"{self.bin}:/usr/bin:/bin", "UMP_MAY_SCRIPT": "{}"}
        self.tool("ps", "exit 0")
        (self.corpus / "normalized").mkdir()
        with open(self.corpus / ".setup.lock", "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            p = subprocess.Popen([sys.executable, "-c", "import setup; setup.main(setup.LAYOUTS)"], cwd=CONNECTORS, env=env,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(3)
            self.assertIsNone(p.poll(), "it waits while another Setup writes")
        self.assertEqual(p.wait(timeout=60), 0)

    def test_a_job_waits_for_its_last_run_and_for_disk(self):
        with open(self.corpus / ".schedule-layouts.lock", "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            self.schedule("run", "layouts")
        self.schedule("run", "layouts", UMP_SCHEDULE_MIN_FREE=str(1 << 60))
        log = (self.corpus / "raw/schedule/layouts.log").read_text()
        self.assertIn("skipped: the last run is still going", log)
        self.assertIn("MB free where the corpus is", log)
        self.assertFalse((self.corpus / "normalized/setup.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
