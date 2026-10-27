"""Setup: configs, the Mac's settings, layouts and machines, in a made-up home with stand-ins for defaults, tmux,
aerospace, brew, tailscale and ssh. Everyone and everything is made up.

Run: python3 -m unittest discover -s connectors/tests -p 'test_*.py'
"""
import json
import plistlib
import os
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

CONNECTORS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONNECTORS))
import setup  # noqa: E402
WARP = "Library/Group Containers/2BBY89MBSN.dev.warp/Library/Application Support/dev.warp.Warp-Stable/warp.sqlite"
DOCK = """<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict>
<key>autohide</key><true/><key>tilesize</key><integer>36</integer><key>mod-count</key><integer>812</integer>
<key>persistent-apps</key><array><dict><key>tile-data</key><dict><key>file-label</key><string>Ghostty</string></dict></dict></array>
</dict></plist>"""
RECTANGLE = """<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict>
<key>gapSize</key><integer>8</integer><key>lastVersion</key><string>0.80</string><key>SUEnableAutomaticChecks</key><true/>
</dict></plist>"""


WARP_PANE = "0123456789abcdef0123456789abcdef"
S1, S2, S3 = "4ccc0001-0000-4000-8000-000000000000", "4ccc0002-0000-4000-8000-000000000000", "4ccc0003-0000-4000-8000-000000000000"
C4 = "01a10004-0000-7000-8000-000000000000"
C1, C2, C3 = "01a10001-0000-7000-8000-000000000000", "01a10002-0000-7000-8000-000000000000", "01a10003-0000-7000-8000-000000000000"
STARTED = 1767261600  # 2026-01-01 10:00 UTC, when the made-up agents started


def processes(home):
    """Made-up processes for a stand-in ps: (pid, ppid, tty, args, environment)."""
    return [
        (100, 1, "??", "/Applications/Warp.app/Contents/MacOS/stable", {}),
        (101, 100, "ttys001", "-zsh", {"TERM_PROGRAM": "WarpTerminal", "WARP_TERMINAL_SESSION_UUID": WARP_PANE}),
        (102, 101, "ttys001", "claude --resume", {"TERM_PROGRAM": "WarpTerminal", "WARP_TERMINAL_SESSION_UUID": WARP_PANE}),
        (103, 102, "ttys001", "node /usr/local/lib/node_modules/@openai/codex/bin/codex exec hi", {"TERM_PROGRAM": "WarpTerminal"}),  # started by the agent
        (200, 1, "??", "/Applications/Ghostty.app/Contents/MacOS/ghostty", {}),
        # an iTerm id inherited from where Ghostty was opened isn't Ghostty's pane
        (202, 200, "ttys002", "claude", {"TERM_PROGRAM": "ghostty", "ITERM_SESSION_ID": "w9t9p9:STALE"}),
        (203, 200, "ttys003", "claude", {"TERM_PROGRAM": "ghostty"}),
        (301, 300, "ttys004", "claude", {"TERM_PROGRAM": "tmux", "TMUX_PANE": "%0"}),
        (400, 1, "??", "/Users/x/.codex/bin/codex app-server", {"TERM_PROGRAM": "ghostty"}),  # a server, in no terminal
        (401, 1, "ttys005", f"node /usr/local/bin/codex resume {C1}", {"TERM_PROGRAM": "iTerm.app", "ITERM_SESSION_ID": "w0t0p0:ABC"}),
        (402, 1, "ttys006", "codex", {"TERM_PROGRAM": "iTerm.app", "ITERM_SESSION_ID": "w0t1p0:DEF"}),
        (204, 200, "ttys007", "codex", {"TERM_PROGRAM": "ghostty"}),
        (500, 1, "??", "/opt/lanes/bin/lane-runner --all", {}),
        (501, 500, "ttys008", "zsh (a shell integration's own terminal)", {}),
        (503, 501, "ttys009", "bash", {}),
        (502, 503, "ttys009", "claude", {}),  # a runner's agent: no terminal says where it is
        (600, 1, "??", "herdr server", {}),
        (601, 600, "ttys010", "claude", {"HERDR_ENV": "1", "HERDR_SESSION": "work", "HERDR_PANE_ID": "w1:pA"}),  # herdr's pane 10
    ]


def agent_files(home):
    (home / ".claude/sessions").mkdir(parents=True)
    (home / ".claude/projects/-tides").mkdir(parents=True)
    # rewritten shorter in place: stale bytes after the object
    (home / ".claude/sessions/102.json").write_text(json.dumps({"pid": 102, "sessionId": S1, "cwd": str(home)}) + '"cwd": "/old"}')
    (home / ".claude/sessions/202.json").write_text(json.dumps({"pid": 202, "sessionId": S2, "cwd": str(home)}))
    (home / ".claude/sessions/203.json").write_text(json.dumps({"pid": 203, "sessionId": S3, "cwd": str(home / "tides")}))
    (home / ".claude/sessions/202.made-up.key").write_text("KEYFILE-NEVER-READ")
    (home / f".claude/projects/-tides/{S1}.jsonl").write_text(
        json.dumps({"type": "ai-title", "aiTitle": "Tide chart"}) + "\n" + json.dumps({"type": "custom-title", "customTitle": "Fix the tide chart"}) + "\n")
    (home / f".claude/projects/-tides/{S2}.jsonl").write_text(json.dumps({"type": "ai-title", "aiTitle": "Moon phases\nand more"}) + "\n")
    (home / ".codex").mkdir()
    con = sqlite3.connect(home / ".codex/state_5.sqlite")
    con.execute("create table threads (id text, cwd text, created_at_ms integer, title text, name text, source text, originator text)")
    con.executemany("insert into threads values (?, ?, ?, ?, ?, ?, ?)", [
        (C1, str(home), (STARTED - 86400) * 1000, "Port the tide tables", None, "cli", "codex-tui"),
        (C2, str(home / "tides"), (STARTED + 2) * 1000, "Reply with exactly: ok", None, "exec", "codex_exec"),  # `codex exec`'s
        (C3, str(home / "tides"), (STARTED + 3) * 1000, "can you add alerts for low tide", "Tide alerts", "vscode", "codex-tui"),
        (C4, str(home), (STARTED + 4) * 1000, "make the moon tables", "Moon tables", "cli", "codex-tui")])
    con.commit()
    con.close()


def warp_db(path):
    path.parent.mkdir(parents=True)
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE windows (id INTEGER, active_tab_index INTEGER, window_width REAL, window_height REAL, fullscreen_state INTEGER);
        CREATE TABLE tabs (id INTEGER, window_id INTEGER, custom_title TEXT, color TEXT, tab_group_id INTEGER, pinned INTEGER);
        CREATE TABLE pane_nodes (id INTEGER, tab_id INTEGER, parent_pane_node_id INTEGER, flex REAL, is_leaf INTEGER);
        CREATE TABLE pane_branches (id INTEGER, pane_node_id INTEGER, horizontal INTEGER);
        CREATE TABLE pane_leaves (pane_node_id INTEGER, kind TEXT, is_focused INTEGER, custom_vertical_tabs_title TEXT);
        CREATE TABLE terminal_panes (id INTEGER, kind TEXT, uuid BLOB, cwd TEXT);
        INSERT INTO windows VALUES (1, 1, 1440, 900, 0);
        INSERT INTO tabs VALUES (1, 1, NULL, NULL, NULL, 0), (2, 1, 'servers', NULL, NULL, 1);
        INSERT INTO pane_nodes VALUES (1, 1, NULL, NULL, 1), (2, 2, NULL, NULL, 0), (3, 2, 2, 1.0, 1), (4, 2, 2, 3.0, 1);
        INSERT INTO pane_branches VALUES (1, 2, 1);
        INSERT INTO pane_leaves VALUES (1, 'terminal', 1, NULL), (3, 'terminal', 0, NULL), (4, 'code', 1, NULL);
    """)
    con.execute("INSERT INTO terminal_panes VALUES (1, 'terminal', ?, ?), (3, 'terminal', ?, ?)",
                (bytes.fromhex("11" * 16), str(path.parents[6] / "tides"), bytes.fromhex(WARP_PANE), str(path.parents[6])))
    con.commit()
    con.close()


class SetupTests(unittest.TestCase):
    may_script = "yes"

    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.home, self.corpus, self.bin = self.root / "home", self.root / "corpus", self.root / "bin"
        for d in (self.home, self.corpus, self.bin):
            d.mkdir()
        self.write(".zshrc", "alias gs='git status'\nexport OPENAI_API_KEY=sk-madeupmadeupmadeupmadeup1234\nexport EDITOR=nvim\n")
        self.write(".claude/settings.json", json.dumps({"model": "opus", "env": {"TIDE_API_TOKEN": "tok-made-up-123"}}, indent=2))
        self.write(".cursor/mcp.json", json.dumps({"mcpServers": {"tides": {"command": "npx", "args": ["tides-mcp", "--key", "7d3c1b2a-made-up"]}}}, indent=2))
        self.write(".aerospace.toml", "gaps.inner.horizontal = 8\n[mode.main.binding]\nalt-h = 'focus left'\n")
        self.write(".vscode/extensions/extensions.json", json.dumps([{"identifier": {"id": "vscodevim.vim"}}, {"identifier": {"id": "ms-python.python"}}]))
        self.write(".ssh/config", "Host box\n  HostName 100.64.0.9\n  User ada\n  IdentityFile ~/.ssh/made_up\nHost *\n  ServerAliveInterval 30\n")
        self.write("Library/LaunchAgents/com.ada.sync.plist", """<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict>
            <key>Label</key><string>com.ada.sync</string><key>ProgramArguments</key><array><string>/usr/bin/true</string></array>
            <key>StartInterval</key><integer>3600</integer></dict></plist>""")
        warp_db(self.home / WARP)
        agent_files(self.home)
        procs = processes(self.home)
        (self.root / "ps.json").write_text(json.dumps(procs))
        # ps: the list, one's environment (macOS's -E: the command, then it), or when it started
        self.tool("ps", f"""exec {sys.executable} - "$@" <<'X'
import json, sys, time
a = sys.argv[1:]
procs = json.load(open("{self.root}/ps.json"))
if "-axwwo" in a:
    for p, pp, tty, args, env in procs:
        print(p, pp, tty, args)
elif "-E" in a:  # pid=,command= for the pids asked, each with its environment after
    want = {{int(x) for x in a[a.index("-p") + 1].split(",")}}
    for q, _, _, args, env in procs:
        if q in want:
            print(q, args + "".join(" " + k + "=" + v for k, v in env.items()))
elif "lstart=" in a:
    print(time.strftime("%a %b %d %H:%M:%S %Y", time.localtime({STARTED})))
X""")
        self.tool("lsof", '[ "$5" = 402 ] && echo "n$HOME/tides"; [ "$5" = 204 ] && echo "n$HOME"; exit 0')
        self.ghostty("✳ Fix the tide chart", "◐ Moon phases")
        self.tool("osascript", f'[ "$1" = -l ] && cat "{self.root}/windows.json" || cat "{self.root}/ghostty.txt"')
        # the window server's list: two apps' windows, AppKit's hidden one in three apps (all at one frame), a tiny one
        (self.root / "windows.json").write_text(json.dumps({"screens": [["Studio Display", 0, 0, 2560, 1440]], "windows": [
            ["Ghostty", 1, 0, 25, 1280, 1415], ["Ghostty", 0, 0, 25, 1280, 1415], ["Firefox", 1, 1280, 25, 1280, 1415], ["Firefox", 0, 0, 617, 500, 500],
            ["Mail", 0, 0, 617, 500, 500], ["Ghostty", 0, 0, 617, 500, 500], ["Mail", 0, 300, 200, 900, 700]]}))
        self.write(".config/herdr/sessions/work/session.json", json.dumps({"version": 1, "workspaces": [{"id": "w1", "custom_name": "tides",
            "identity_cwd": f"{self.home}/tides", "tabs": [{"custom_name": "charts", "layout": {"Split": {"direction": "Vertical", "ratio": 0.5,
            "first": {"Pane": 10}, "second": {"Pane": 11}}}, "panes": {"10": {"cwd": f"{self.home}/tides"}, "11": {"cwd": str(self.home)}}}]}]}))
        self.write("Library/Application Support/taiku/tui-layout.json", json.dumps({"version": 1, "workspaces": {str(self.home): {"snapshot": {
            "tabs": [{"layout": {"kind": "split", "direction": "horizontal", "ratio": 0.4, "first": {"kind": "leaf", "tiles": [1]},
                                 "second": {"kind": "leaf", "tiles": [2]}}}], "tile_names": {"2": "logs"}}}}}))
        app = self.write("sims/A/data/Containers/Bundle/Application/X/Tides.app/Info.plist", "")
        app.write_bytes(plistlib.dumps({"CFBundleDisplayName": "Tides", "CFBundleShortVersionString": "0.3", "CFBundleIdentifier": "org.ada.tides"}))
        self.write(".android/avd/Tide_Pixel.avd/config.ini", "avd.ini.displayname=Tide Pixel\nhw.device.name=pixel_8\nabi.type=arm64-v8a\n")
        self.tool("pmset", "printf 'AC Power:\\n sleep 10\\n displaysleep 5\\n'")
        self.tool("defaults", f"""case "$2" in com.apple.dock) cat <<'X'\n{DOCK}\nX\n;; com.knollsoft.Rectangle) cat <<'X'\n{RECTANGLE}\nX\n;; *) exit 1;; esac""")
        self.tool("tmux", "printf 'work\\t0\\teditor\\t5d1e,200x50,0,0\\t0\\t%s/tides\\tnode\\t%%0\\n' \"$HOME\"")
        self.tool("aerospace", "printf '1\\tGhostty\\n1\\tGhostty\\n2\\tFirefox\\n'")
        self.tool("brew", '[ "$1" = leaves ] && echo ripgrep || echo ghostty')
        self.tool("tailscale", """echo '{"Self": {"HostName": "laptop"}, "Peer": {"a": {"HostName": "box", "OS": "linux", "Online": true}, "b": {"HostName": "funnel-ingress-node"}}}'""")
        self.tool("prlctl", "printf 'NAME STATUS\\nWin11 stopped\\n'")
        self.tool("colima", "exit 1")
        self.tool("xcrun", f"""case "$1 $2 $3" in
"simctl list devices") echo '{{"devices": {{"com.apple.CoreSimulator.SimRuntime.iOS-26-4": [{{"name": "iPhone 17", "udid": "5111A000-0000-4000-8000-000000000000", "isAvailable": true, "state": "Shutdown", "deviceTypeIdentifier": "com.apple.CoreSimulator.SimDeviceType.iPhone-17", "dataPath": "{self.home}/sims/A/data"}}]}}}}';;
"devicectl device info") echo '{{"result": {{"apps": [{{"name": "Tides", "version": "0.3", "bundleIdentifier": "org.ada.tides", "builtByDeveloper": true, "removable": true}}, {{"name": "Moonwatch", "version": "2.1", "bundleIdentifier": "com.moon.watch", "removable": true}}, {{"name": "Safari", "defaultApp": true}}, {{"name": "Hidden", "hidden": true}}]}}}}';;
"devicectl list devices") echo 'Devices:'; echo '{{"result": {{"devices": [{{"identifier": "D1", "deviceProperties": {{"name": "Ada iPhone", "osVersionNumber": "26.1", "developerModeStatus": "enabled"}}, "hardwareProperties": {{"marketingName": "iPhone 16", "deviceType": "iPhone", "platform": "iOS"}}, "connectionProperties": {{"pairingState": "paired", "tunnelState": "connected", "lastConnectionDate": "2026-10-01T10:00:00Z"}}}}]}}}}';;
*) exit 1;; esac""")
        # adb: the phone, its OS, the apps you installed and its settings (some the phone's own or naming it)
        self.tool("adb", """case "$*" in
"devices -l") printf 'List of devices attached\\nR5CT1 device usb:1-1 product:tide model:Pixel_9 device:tide\\nX1 unauthorized\\n';;
*getprop*) echo 15;;
*"pm list packages -3") printf 'package:org.ada.tides\\npackage:com.moon.watch\\n';;
*"settings list system") printf 'font_scale=1.15\\nscreen_off_timeout=60000\\nbluetooth_name=Ada Pixel\\nwallpaper_finish_drawing=1792801435669\\n';;
*"settings list secure") printf 'android_id=9f8e7d6c5b4a3921\\nlocation_mode=3\\nlast_setup_shown=1\\n';;
*"settings list global") printf 'stay_on_while_plugged_in=3\\nboot_count=41\\n';;
*) exit 1;; esac""")
        self.tool("system_profiler", """echo '{"SPBluetoothDataType": [{"device_connected": [{"Ada AirPods": {"device_address": "AA:BB:CC:DD:EE:FF", "device_serialNumber": "SERIAL123", "device_minorType": "Headphones", "device_vendorID": "0x004C"}}]}], "SPDisplaysDataType": [{"spdisplays_ndrvs": [{"_name": "Studio Display", "_spdisplays_resolution": "2560 x 1440 @ 60.00Hz", "spdisplays_connection_type": "spdisplays_thunderbolt", "spdisplays_main": "spdisplays_yes", "_spdisplays_display-serial-number": "DSERIAL"}]}], "SPUSBHostDataType": [{"_name": "USB 3.1 Bus", "_items": [{"_name": "Tide Keyboard", "USBDeviceKeyVendorName": "Tide Co", "USBKeyHardwareType": "Removable", "USBDeviceKeySerialNumber": "USERIAL"}]}]}'""")
        # ssh runs the probe locally with HOME set to a second made-up home, as if it were the host's
        (self.root / "remote/.config/sway").mkdir(parents=True)
        (self.root / "remote/.config/sway/config").write_text("bindsym $mod+Return exec foot\n")
        (self.root / "remote/.tmux.conf").write_text("set -g mouse on\n")
        self.tool("ssh", f'host=""; for a; do case "$a" in -o) skip=1;; --) ;; *) [ -n "$skip" ] && skip="" && continue; [ -z "$host" ] && host="$a" && continue; cmd="$a";; esac; done\n'
                         f'[ "$host" = box ] || exit 255\nHOME="{self.root}/remote" PATH=/usr/bin:/bin sh -c "{sys.executable} ${{cmd#python3}}"')

    def ghostty(self, mark1, mark2):
        """What Ghostty answers: one window, a tab of two terminals, titled by the agents in them (with their marks)."""
        (self.root / "ghostty.txt").write_text(f"1\t1\t{mark1}\t{mark1}\t{self.home}\n1\t1\t{mark1}\t◐ zsh\t{self.home}/tides\n"
                                               f"1\t2\tMoon tables | home\tMoon tables | home\t{self.home}\n")

    def write(self, rel, text):
        p = self.home / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text))
        return p

    def tool(self, name, body):
        p = self.bin / name
        p.write_text("#!/bin/sh\n" + body + "\n")
        p.chmod(0o755)

    def run_setup(self, hosts=""):
        env = {k: v for k, v in os.environ.items() if k != "UMP_SETUP_HOSTS"}
        env.update(HOME=str(self.home), CORPUS_DIR=str(self.corpus), PATH=f"{self.bin}:/usr/bin:/bin", UMP_SETUP_HOSTS=hosts,
                   UMP_MAY_SCRIPT=json.dumps({"com.mitchellh.ghostty": self.may_script}))
        r = subprocess.run([sys.executable, "-c", "import setup; setup.main()"], cwd=CONNECTORS, env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        recs = [json.loads(l) for l in (self.corpus / "normalized/setup.jsonl").read_text().splitlines()]
        by = {}
        for r in recs:  # each thing's newest version (an earlier run's versions follow this run's)
            if r["meta"]["what"] not in by or (r.get("ts") or "") > (by[r["meta"]["what"]].get("ts") or ""):
                by[r["meta"]["what"]] = r
        return by, recs, json.loads((self.corpus / "manifest.json").read_text())["setup"]

    def test_configs_with_their_secrets_out(self):
        by, recs, manifest = self.run_setup()
        self.assertNotIn("not_read", manifest.get("notes", {}), manifest)
        everything = "\n".join(r.get("text", "") for r in recs)
        for secret in ("sk-madeupmadeup", "tok-made-up-123", "7d3c1b2a-made-up"):
            self.assertNotIn(secret, everything)
        zshrc = by["file:~/.zshrc"]
        self.assertEqual((zshrc["kind"], zshrc["meta"]["tool"], zshrc["meta"]["group"], zshrc["is_me"]), ("config", "zsh", "shell", True))
        self.assertIn("alias gs='git status'", zshrc["text"])
        self.assertIn("export EDITOR=nvim", zshrc["text"], "only the secret goes, not the line around it")
        self.assertEqual(json.loads(by["file:~/.claude/settings.json"]["text"])["env"]["TIDE_API_TOKEN"], "[redacted]", "a JSON config stays JSON")
        self.assertEqual(by["extensions:VS Code"]["text"], "ms-python.python\nvscodevim.vim")
        self.assertEqual(by["file:~/.aerospace.toml"]["meta"]["group"], "window manager")

    def test_mac_settings_layouts_installed_and_machines(self):
        by, _, _ = self.run_setup()
        dock = by["defaults:com.apple.dock"]["text"]
        self.assertEqual(dock, "autohide = True\npersistent-apps = [Ghostty]\ntilesize = 36", "the Dock's settings; not its counters")
        self.assertEqual(by["defaults:com.knollsoft.Rectangle"]["text"], "gapSize = 8", "an app's choices, not its update checks")
        warp = by["layout:Warp"]
        self.assertEqual(warp["text"], "Window 1: 1440x900, 2 tabs\n  Tab 1\n    terminal ~/tides\n  servers (pinned)\n"
                                       "    side by side:\n      25% terminal ~  claude 4ccc0001 \"Fix the tide chart\"\n      75% code")
        self.assertIn("work:0 editor  [5d1e,200x50,0,0]\n    pane 0: claude in ~/tides", by["layout:tmux"]["text"], "tmux's pane %0: the agent there")
        self.assertEqual(by["layout:AeroSpace"]["text"], "1: Ghostty\n2: Firefox")
        self.assertIn("com.ada.sync: /usr/bin/true (every 3600s)", by["installed:launch_agents"]["text"])
        self.assertEqual(by["installed:brew"]["text"], "Formulae:\nripgrep\nCasks:\nghostty")
        self.assertEqual(by["machines:tailscale"]["text"], "This Mac: laptop\nbox (linux)")
        self.assertEqual(by["machines:ssh"]["text"], "box hostname=100.64.0.9 user=ada", "hosts, never their keys")
        self.assertEqual(by["machines:vms"]["text"], "Parallels: Win11 stopped")

    def test_devices_without_addresses_or_serials(self):
        by, recs, _ = self.run_setup()
        self.assertEqual(by["device:phone:Ada iPhone"]["text"], "Ada iPhone\nmodel: iPhone 16\ntype: iPhone\nos: iOS 26.1\npaired: paired\ndeveloper mode: on")
        self.assertEqual(by["device:phone:Pixel 9"]["text"], "Pixel 9\ntype: Android\nproduct: tide\nos: Android 15", "an unauthorized phone isn't listed")
        self.assertNotIn("device:phone:X1", by)
        self.assertEqual(by["device:bluetooth:Ada AirPods"]["text"], "Ada AirPods\ntype: Headphones\nvendor: Apple")
        self.assertIn("resolution: 2560 x 1440 @ 60.00Hz\nconnection: thunderbolt\nmain: yes", by["device:display:Studio Display"]["text"])
        self.assertEqual(by["device:usb:Tide Keyboard"]["text"], "Tide Keyboard\nvendor: Tide Co")
        everything = json.dumps(recs)
        for private in ("AA:BB:CC:DD:EE:FF", "SERIAL123", "DSERIAL", "USERIAL"):
            self.assertNotIn(private, everything)

    def test_what_isnt_a_change(self):
        first, recs, _ = self.run_setup()
        # focus moving between panes, a phone connecting: not a new version
        con = sqlite3.connect(self.home / WARP)
        con.execute("update pane_leaves set is_focused = 1 - is_focused")
        con.execute("update windows set active_tab_index = 0")
        con.commit()
        con.close()
        self.tool("xcrun", """[ "$1" = devicectl ] || exit 1; echo '{"result": {"devices": [{"deviceProperties": {"name": "Ada iPhone", "osVersionNumber": "26.1", "developerModeStatus": "enabled"}, "hardwareProperties": {"marketingName": "iPhone 16", "deviceType": "iPhone", "platform": "iOS"}, "connectionProperties": {"pairingState": "paired", "tunnelState": "disconnected", "lastConnectionDate": "2026-10-09T10:00:00Z"}}]}}'""")
        time.sleep(1.1)
        _, again, _ = self.run_setup()
        self.assertEqual(len(again), len(recs))
        # a file a program regenerates is kept once, as it is now
        self.write(".warp/launch_configurations/restore.yaml", "# generated 2026-10-22 15:20 by restore-snapshot\nwindows: 1\n")
        self.run_setup()
        self.write(".warp/launch_configurations/restore.yaml", "# generated 2026-10-22 15:41 by restore-snapshot\nwindows: 2\n")
        by, recs, _ = self.run_setup()
        mine = [r for r in recs if r["meta"]["what"] == "file:~/.warp/launch_configurations/restore.yaml"]
        self.assertEqual([r["text"].splitlines()[1] for r in mine], ["windows: 2"])
        self.assertNotIn("changed", mine[0]["meta"])

    def test_a_change_is_a_new_version_with_its_diff(self):
        first, _, _ = self.run_setup()
        again, recs, _ = self.run_setup()
        self.assertEqual(len(recs), len(first), "nothing changed: nothing new")
        self.write(".aerospace.toml", "gaps.inner.horizontal = 12\n[mode.main.binding]\nalt-h = 'focus left'\n")
        by, recs, _ = self.run_setup()
        self.assertEqual(len(recs), len(first) + 1, "the old version stays")
        new = by["file:~/.aerospace.toml"]
        self.assertEqual(new["title"], "Changed: AeroSpace: ~/.aerospace.toml")
        self.assertEqual(new["meta"]["changed"]["diff"], "-gaps.inner.horizontal = 8\n+gaps.inner.horizontal = 12")
        self.assertEqual(new["meta"]["changed"]["from"], first["file:~/.aerospace.toml"]["id"])
        self.tool("defaults", f"""case "$2" in com.apple.dock) cat <<'X'\n{DOCK.replace('<true/>', '<false/>')}\nX\n;; *) exit 1;; esac""")
        time.sleep(1.1)  # a setting has no time of its own: a version is when it was first seen
        by, _, _ = self.run_setup()
        self.assertEqual(by["defaults:com.apple.dock"]["meta"]["changed"]["diff"], "-autohide = True\n+autohide = False")
        self.tool("defaults", f"""case "$2" in com.apple.dock) cat <<'X'\n{DOCK.replace('<true/>', '<false/>').replace('>36<', '>48<')}\nX\n;; *) exit 1;; esac""")
        time.sleep(1.1)
        by, _, _ = self.run_setup()
        self.assertEqual(by["defaults:com.apple.dock"]["meta"]["changed"]["diff"], "-tilesize = 36\n+tilesize = 48", "from the version before, not the first")

    def test_versions_over_many_runs(self):
        first, _, _ = self.run_setup()
        self.write(".aerospace.toml", "gaps.inner.horizontal = 12\n")
        changed, _, _ = self.run_setup()
        self.run_setup()  # nothing changed since: the change and when it was first seen stay
        by, recs, _ = self.run_setup()
        self.assertEqual(by["file:~/.aerospace.toml"]["meta"]["changed"], changed["file:~/.aerospace.toml"]["meta"]["changed"])
        self.assertEqual(by["defaults:com.apple.dock"]["ts"], first["defaults:com.apple.dock"]["ts"], "a setting is timed when first seen")
        # back to the first text, restored with its old file time: a new version, once
        old = self.write(".aerospace.toml", "gaps.inner.horizontal = 8\n[mode.main.binding]\nalt-h = 'focus left'\n")
        os.utime(old, (1_600_000_000, 1_600_000_000))
        by, recs, _ = self.run_setup()
        newest = max((r for r in recs if r["meta"]["what"] == "file:~/.aerospace.toml"), key=lambda r: r["meta"]["seen"])
        self.assertEqual(newest["meta"]["changed"]["from"], changed["file:~/.aerospace.toml"]["id"])
        self.assertNotEqual(newest["id"], first["file:~/.aerospace.toml"]["id"], "an earlier version keeps its own record")
        _, again, _ = self.run_setup()
        self.assertEqual(len(again), len(recs), "and isn't a change again on the next run")

    def test_a_change_past_the_cap_is_a_change(self):
        self.write(".zshrc", "# x\n" * 40_000 + "alias a=b\n")
        self.run_setup()
        self.write(".zshrc", "# x\n" * 40_000 + "alias a=c\n")
        _, recs, _ = self.run_setup()
        mine = [r for r in recs if r["meta"]["what"] == "file:~/.zshrc"]
        self.assertEqual(len(mine), 2)
        self.assertTrue(mine[0]["text"].endswith("[cut: longer than this]"))

    def test_an_earlier_runs_leak_is_taken_out(self):
        self.run_setup()
        f = self.corpus / "normalized/setup.jsonl"
        leaked = {"id": "file:~/.npmrc@0", "source": "setup", "kind": "config", "ts": "2026-01-01T00:00:00Z", "title": "npm: ~/.npmrc",
                  "text": "//registry.npmjs.org/:_authToken=npm_abcdefghijklmnopqrstuvwxyz0123456789",
                  "meta": {"what": "file:~/.npmrc", "group": "shell", "seen": "2026-01-01T00:00:00Z",
                           "changed": {"from": "x", "added": 1, "removed": 0, "diff": "+_authToken=npm_abcdefghijklmnopqrstuvwxyz0123456789"}}}
        f.write_text(f.read_text() + json.dumps(leaked) + "\n")
        self.run_setup()
        self.assertNotIn("npm_abcdefghijklmnopqrstuvwxyz", f.read_text())
        self.assertIn("file:~/.npmrc@0", f.read_text(), "the version stays, without its secret")

    def test_ssh_includes_and_match_blocks(self):
        self.write(".ssh/config", "Include config.d/*\nHost box lab\n  HostName 100.64.0.9\nMatch host *.corp\n  User someone-else\n")
        self.write(".ssh/config.d/work", "Host=build\n  HostName build.example.com\n  User ci\n")
        by, _, _ = self.run_setup()
        self.assertEqual(by["machines:ssh"]["text"], "build hostname=build.example.com user=ci\nbox, lab hostname=100.64.0.9")

    def test_the_agent_sessions_in_each_pane(self):
        by, recs, manifest = self.run_setup()
        everything = json.dumps(recs)
        self.assertNotIn("KEYFILE-NEVER-READ", everything)
        # every agent running in a terminal, once: not the one an agent started, nor a server in no terminal
        sessions = by["layout:agents"]["meta"]["sessions"]
        self.assertEqual(sorted((a["terminal"], a.get("session")) for a in sessions), sorted([
            ("WarpTerminal", S1), ("ghostty", S2), ("ghostty", S3), ("tmux", None), ("iTerm.app", C1), ("iTerm.app", C3), ("ghostty", C4), ("lane-runner", None),
            ("herdr", None)]))
        by_session = {a.get("session"): a for a in sessions}
        self.assertEqual(by_session[S1]["title"], "Fix the tide chart", "the last custom title, over the AI's")
        self.assertEqual(by_session[S2]["title"], "Moon phases", "a title's first line")
        self.assertEqual((by_session[C1]["title"], by_session[C1]["pane"]), ("Port the tide tables", "w0t0p0:ABC"), "codex resume <id>")
        self.assertEqual(by_session[C3]["title"], "Tide alerts", "a new codex: its terminal conversation (by name), not `codex exec`'s")
        self.assertNotIn("pane", by_session[S2], "an inherited iTerm id isn't Ghostty's pane")
        # Warp's split, for a program to rebuild: direction, shares, each pane's folder and agent
        tab = by["layout:Warp"]["meta"]["layout"][1]
        self.assertEqual((tab["title"], tab["split"], [c["share"] for c in tab["children"]]), ("servers", "side by side", [0.25, 0.75]))
        self.assertEqual(tab["children"][0]["agent"], {"tool": "claude", "session": S1, "title": "Fix the tide chart"})
        # Ghostty: by title (after its mark), then the one left in that folder
        g = by["layout:Ghostty"]
        self.assertEqual(g["text"], f'Window 1: 2 tabs\n  Fix the tide chart\n    pane ~  claude 4ccc0002 "Moon phases"\n'
                                    f'    pane ~/tides  claude 4ccc0003\n  Moon tables | home\n    pane ~  codex 01a10004 "Moon tables"', g["text"])

    def test_multiplexers_windows_simulators_and_phones(self):
        by, recs, _ = self.run_setup()
        everything = json.dumps(recs)
        # herdr: the split, each pane's folder, and the agent its pane variable names
        h = by["layout:herdr:work"]
        tab = h["meta"]["layout"][0]
        self.assertEqual((tab["window"], tab["title"], tab["split"], tab["ratio"]), ("tides", "charts", "vertical", 0.5))
        self.assertEqual([c["cwd"] for c in tab["children"]], [f"{self.home}/tides", str(self.home)])
        self.assertEqual(tab["children"][0]["agent"], {"tool": "claude"})
        self.assertNotIn("agent", tab["children"][1])
        t = by["layout:taiku"]["meta"]["layout"][0]
        self.assertEqual((t["split"], t["ratio"], t["children"]), ("horizontal", 0.4, [{"tile": 1}, {"tile": 2, "name": "logs"}]))
        # every app's windows: on screen or not, the same frame once, not AppKit's hidden ones
        win = by["layout:windows"]
        self.assertEqual(win["text"], "display Studio Display: 2560x1440 at 0,0\nFirefox: 1280x1415 at 1280,25 (on screen)\n"
                                      "Ghostty: 1280x1415 at 0,25 x2 (on screen)\nMail: 900x700 at 300,200", win["text"])
        # a simulator's apps, read from its bundles while it's shut down; an emulator
        self.assertIn("Tides 0.3  org.ada.tides", by["device:simulator:5111A000-0000-4000-8000-000000000000"]["text"])
        self.assertEqual(by["device:emulator:Tide Pixel"]["title"], "emulator: Tide Pixel")
        # the iPhone's apps by where they came from; not a hidden one
        self.assertEqual(by["apps:phone:Ada iPhone"]["text"], "installed (1):\n  Moonwatch 2.1  com.moon.watch\nbuilt by you (1):\n  Tides 0.3  org.ada.tides\n"
                                                             "Apple's (1):\n  Safari", by["apps:phone:Ada iPhone"]["text"])
        # Android: the apps, and the settings chosen; not ids, the phone's name, counters or a time under another name
        self.assertEqual(by["apps:phone:Pixel 9"]["text"], "com.moon.watch\norg.ada.tides")
        self.assertEqual(by["settings:phone:Pixel 9"]["text"], "system:\n  font_scale = 1.15\n  screen_off_timeout = 60000\nsecure:\n  location_mode = 3\n"
                                                              "global:\n  stay_on_while_plugged_in = 3")
        for leak in ("9f8e7d6c5b4a3921", "Ada Pixel", "1792801435669", "boot_count"):
            self.assertNotIn(leak, everything)
        self.assertIn("os: Android 15", by["device:phone:Pixel 9"]["text"])
        self.assertIn("displaysleep 5", by["pmset:custom"]["text"])
        # and nothing of it is a new version when nothing changed
        _, again, _ = self.run_setup()
        self.assertEqual(len(again), len(recs))

    def test_an_agent_going_from_idle_to_working_isnt_a_new_layout(self):
        self.run_setup()
        self.ghostty("◐ Fix the tide chart", "✳ Moon phases")
        _, recs, _ = self.run_setup()
        self.assertEqual(sum(1 for r in recs if r["meta"]["what"] == "layout:Ghostty"), 1)

    def test_ghostty_isnt_asked_when_it_would_put_up_a_dialog(self):
        self.may_script = "ask"
        (self.bin / "osascript").write_text(f"#!/bin/sh\n[ \"$1\" = -l ] && exit 0\ntouch {self.root}/asked\n")  # the window list asks nothing
        by, _, manifest = self.run_setup()
        self.assertNotIn("layout:Ghostty", by)
        self.assertFalse((self.root / "asked").exists())
        self.assertIn("Automation", manifest["notes"]["ghostty"])

    def test_one_odd_thing_stops_nothing_else(self):
        (self.home / ".bashrc").write_bytes(b"alias ll='ls -l'\n\xff\xfe not utf-8\n")
        self.write("Library/LaunchAgents/odd.plist", '<?xml version="1.0"?><plist version="1.0"><array><string>x</string></array></plist>')
        self.write("Library/LaunchAgents/odder.plist", '<?xml version="1.0"?><plist version="1.0"><dict><key>Label</key><string>odder</string>'
                   '<key>ProgramArguments</key><array><integer>1</integer></array></dict></plist>')
        con = sqlite3.connect(self.home / WARP)
        con.execute("alter table pane_nodes drop column flex")
        con.commit()
        con.close()
        by, _, manifest = self.run_setup()
        self.assertIn("alias ll='ls -l'", by["file:~/.bashrc"]["text"])
        self.assertIn("odder: 1 (on demand)", by["installed:launch_agents"]["text"])
        self.assertIn("layout:Warp", by, "a Warp without a column still gives its layout")
        self.assertNotIn("not_read", manifest.get("notes", {}))



# (what a config says, what's kept): secrets in each syntax configs use, and settings that only look like secrets
REDACTIONS = [
    ('export OPENAI_API_KEY=sk-madeupmadeupmadeupmadeup1234', 'export OPENAI_API_KEY=[redacted]'),
    ('"env": {"TIDE_API_TOKEN": "tok-made-up-123"}', '"env": {"TIDE_API_TOKEN": "[redacted]"}'),
    ('"accessToken": "Zk2mQ9pL4xWv", "clientSecret": "s3cr3tValue99", "apiKey": "abcd1234efgh"',
     '"accessToken": "[redacted]", "clientSecret": "[redacted]", "apiKey": "[redacted]"'),
    ('"headers": {"Authorization": "Basic dXNlcjpwYXNzd29yZA=="}', '"headers": {"Authorization": "Basic [redacted]"}'),
    ('"api_key" = "abc123secretvalue"', '"api_key" = "[redacted]"'),
    ('token: abc123secretvalueXY', 'token: [redacted]'),
    ('set -gx GITHUB_TOKEN abc123secretvalueXY', 'set -gx GITHUB_TOKEN [redacted]'),
    ('local token = "abc123secretvalueXY"', 'local token = "[redacted]"'),
    ('cfg = { token = "abc123secretvalueXY" }', 'cfg = { token = "[redacted]" }'),
    ('"args": ["--auth-token", "abc123secretvalueXY"]', '"args": ["--auth-token", "[redacted]"]'),
    ('"--key",\n  "7d3c1b2a-made-up-uuid",', '"--key",\n  "[redacted]",'),
    ('"\\"{\\\\\\"token\\\\\\":\\\\\\"lin_api_Sqzp9xY2kLmN4bVc8RtW1qZ3\\\\\\"}\\""', '"\\"{\\\\\\"token\\\\\\":\\\\\\"[redacted]\\\\\\"}\\""'),
    ('https://Zk9mQ2pL4xWv8RtYa7c3Bn5Dk1Fh@github.com/x', 'https://[redacted]@github.com/x'),
    ('postgres://ada:hunter22@db/x', 'postgres://ada:[redacted]@db/x'),
    ('curl "https://x.io/a?access_token=abcdef123456&page=2"', 'curl "https://x.io/a?access_token=[redacted]&page=2"'),
    ('//registry.npmjs.org/:_authToken=npm_abcdefghijklmnopqrstuvwxyz0123456789', '//registry.npmjs.org/:_authToken=[redacted]'),
    ('the password for the router is Tide-2024!', 'the password for the router is [redacted]'),
    ("curl -H 'Authorization: Bearer abc123def456ghi'", "curl -H 'Authorization: Bearer [redacted]'"),
    ('Set `api_key: your-key-here`', 'Set `api_key: [redacted]`'),
    ('{"key": "cmd+shift+p", "command": "x"}', None), ('{"key": "ctrl+k ctrl+s"}', None),
    ('ssh_key_path = "keys/deploy-2024"', None), ('token_file = "secrets/ci-2024"', None), ('"tokenizer": "cl100k_base"', None),
    ('"MAX_THINKING_TOKENS": "31999"', None), ('max_tokens = 4096  # cap', None), ('env_key = "OPENAI_API_KEY"', None),
    ('gpg --default-key ABCD1234', None), ('TestVeryLongCamelCaseName2Final', None), ('agentview task add "..." --key <source>', None),
    ('if [[ $PWD =~ $HOME/x ]]; then', None), ('keybind = cmd+t=new_tab', None), ('commit = 3f49db7a8c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f', None),
    ('the token expires after a day; set api_key in the file', None), ('export TOKEN=$(security find-generic-password -w -s x)', None),
    ('url = "https://example.com:8080/x"', None), ('token: "{{ .Values.token }}"', None),
]


class VersionTests(unittest.TestCase):
    def test_the_newest_version_is_the_one_seen_last(self):
        # a config restored from a backup keeps its old file time: the version seen last is still the newest
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "setup.jsonl").write_text(
                json.dumps({"id": "a@1", "ts": "2026-02-01T00:00:00Z", "text": "edited", "meta": {"what": "a", "seen": "2026-02-01T00:00:00.000001+00:00"}}) + "\n" +
                json.dumps({"id": "a@2", "ts": "2020-01-01T00:00:00Z", "text": "restored", "meta": {"what": "a", "seen": "2026-03-01T00:00:00.000001+00:00"}}) + "\n")
            old = setup.NORM
            setup.NORM = Path(t)
            try:
                self.assertEqual(setup.Versions().latest["a"]["id"], "a@2")
            finally:
                setup.NORM = old


class RedactionTests(unittest.TestCase):
    def test_each_syntax(self):
        for raw, kept in REDACTIONS:
            with self.subTest(raw=raw):
                self.assertEqual(setup.redact(raw), raw if kept is None else kept)
                self.assertEqual(setup.redact(setup.redact(raw)), setup.redact(raw), "redacting twice changes nothing")

    def test_prose(self):
        self.assertEqual(setup.redact("Set `api_key: your-key-here` in the file", prose=True), "Set `api_key: your-key-here` in the file",
                         "in docs, a value has to look like a key")
        self.assertEqual(setup.redact("- `api_key`, `organization_id`: dropped. token: see below", prose=True),
                         "- `api_key`, `organization_id`: dropped. token: see below", "docs name keys without holding them")
        self.assertEqual(setup.redact("Put it in `TIDE_API_KEY=sk-ant-abcdefghijklmnopqrstuv1234`.", prose=True), "Put it in `TIDE_API_KEY=[redacted]`.")


if __name__ == "__main__":
    unittest.main()
