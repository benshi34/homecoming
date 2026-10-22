"""Setup: configs, the Mac's settings, layouts and machines, in a made-up home with stand-ins for defaults, tmux,
aerospace, brew, tailscale and ssh. Everyone and everything is made up.

Run: python3 -m unittest discover -s connectors/tests -p 'test_*.py'
"""
import json
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
WARP = "Library/Group Containers/2BBY89MBSN.dev.warp/Library/Application Support/dev.warp.Warp-Stable/warp.sqlite"
DOCK = """<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict>
<key>autohide</key><true/><key>tilesize</key><integer>36</integer><key>mod-count</key><integer>812</integer>
<key>persistent-apps</key><array><dict><key>tile-data</key><dict><key>file-label</key><string>Ghostty</string></dict></dict></array>
</dict></plist>"""
RECTANGLE = """<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict>
<key>gapSize</key><integer>8</integer><key>lastVersion</key><string>0.80</string><key>SUEnableAutomaticChecks</key><true/>
</dict></plist>"""


def warp_db(path):
    path.parent.mkdir(parents=True)
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE windows (id INTEGER, active_tab_index INTEGER, window_width REAL, window_height REAL, fullscreen_state INTEGER);
        CREATE TABLE tabs (id INTEGER, window_id INTEGER, custom_title TEXT, color TEXT, tab_group_id INTEGER, pinned INTEGER);
        CREATE TABLE pane_nodes (id INTEGER, tab_id INTEGER, parent_pane_node_id INTEGER, flex REAL, is_leaf INTEGER);
        CREATE TABLE pane_branches (id INTEGER, pane_node_id INTEGER, horizontal INTEGER);
        CREATE TABLE pane_leaves (pane_node_id INTEGER, kind TEXT, is_focused INTEGER, custom_vertical_tabs_title TEXT);
        CREATE TABLE terminal_panes (id INTEGER, kind TEXT, cwd TEXT);
        INSERT INTO windows VALUES (1, 1, 1440, 900, 0);
        INSERT INTO tabs VALUES (1, 1, NULL, NULL, NULL, 0), (2, 1, 'servers', NULL, NULL, 1);
        INSERT INTO pane_nodes VALUES (1, 1, NULL, NULL, 1), (2, 2, NULL, NULL, 0), (3, 2, 2, 1.0, 1), (4, 2, 2, 3.0, 1);
        INSERT INTO pane_branches VALUES (1, 2, 1);
        INSERT INTO pane_leaves VALUES (1, 'terminal', 1, NULL), (3, 'terminal', 0, NULL), (4, 'code', 1, NULL);
    """)
    con.execute("INSERT INTO terminal_panes VALUES (1, 'terminal', ?), (3, 'terminal', ?)", (str(path.parents[6] / "tides"), str(path.parents[6])))
    con.commit()
    con.close()


class SetupTests(unittest.TestCase):
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
        self.tool("defaults", f"""case "$2" in com.apple.dock) cat <<'X'\n{DOCK}\nX\n;; com.knollsoft.Rectangle) cat <<'X'\n{RECTANGLE}\nX\n;; *) exit 1;; esac""")
        self.tool("tmux", "printf 'work\\t0\\teditor\\t5d1e,200x50,0,0\\t0\\t%s/tides\\tnvim\\n' \"$HOME\"")
        self.tool("aerospace", "printf '1\\tGhostty\\n1\\tGhostty\\n2\\tFirefox\\n'")
        self.tool("brew", '[ "$1" = leaves ] && echo ripgrep || echo ghostty')
        self.tool("tailscale", """echo '{"Self": {"HostName": "laptop"}, "Peer": {"a": {"HostName": "box", "OS": "linux", "Online": true}, "b": {"HostName": "funnel-ingress-node"}}}'""")
        self.tool("prlctl", "printf 'NAME STATUS\\nWin11 stopped\\n'")
        self.tool("colima", "exit 1")
        # ssh runs the probe locally with HOME set to a second made-up home, as if it were the host's
        (self.root / "remote/.config/sway").mkdir(parents=True)
        (self.root / "remote/.config/sway/config").write_text("bindsym $mod+Return exec foot\n")
        (self.root / "remote/.tmux.conf").write_text("set -g mouse on\n")
        self.tool("ssh", f'host=""; for a; do case "$a" in -o) skip=1;; *) [ -n "$skip" ] && skip="" && continue; [ -z "$host" ] && host="$a" && continue; cmd="$a";; esac; done\n'
                         f'[ "$host" = box ] || exit 255\nHOME="{self.root}/remote" PATH=/usr/bin:/bin sh -c "{sys.executable} ${{cmd#python3}}"')

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
        env.update(HOME=str(self.home), CORPUS_DIR=str(self.corpus), PATH=f"{self.bin}:/usr/bin:/bin", UMP_SETUP_HOSTS=hosts)
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
        self.assertEqual(warp["text"], "Window 1: 1440x900, 2 tabs\n  Tab 1\n    terminal ~/tides (focused)\n  servers (active) (pinned)\n"
                                       "    side by side:\n      25% terminal ~\n      75% code (focused)")
        self.assertIn("work:0 editor  [5d1e,200x50,0,0]\n    pane 0: nvim in ~/tides", by["layout:tmux"]["text"])
        self.assertEqual(by["layout:AeroSpace"]["text"], "1: Ghostty\n2: Firefox")
        self.assertIn("com.ada.sync: /usr/bin/true (every 3600s)", by["installed:launch_agents"]["text"])
        self.assertEqual(by["installed:brew"]["text"], "Formulae:\nripgrep\nCasks:\nghostty")
        self.assertEqual(by["machines:tailscale"]["text"], "This Mac: laptop\nbox (linux) online")
        self.assertEqual(by["machines:ssh"]["text"], "box hostname=100.64.0.9 user=ada", "hosts, never their keys")
        self.assertEqual(by["machines:vms"]["text"], "Parallels: Win11 stopped")

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

    def test_other_machines_over_ssh(self):
        by, _, manifest = self.run_setup(hosts="box gone")
        self.assertEqual(manifest["notes"]["hosts_not_read"], ["gone"], "a host that doesn't answer stops no other")
        self.assertEqual(by["box:file:~/.tmux.conf"]["meta"]["tool"], "tmux")
        self.assertEqual(by["box:file:~/.config/sway/config"]["text"], "bindsym $mod+Return exec foot")
        self.assertIn("system:", by["box:running"]["text"])


if __name__ == "__main__":
    unittest.main()
