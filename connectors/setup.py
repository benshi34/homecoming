"""Setup: how you've arranged your computer and the tools you work in, and how that changed.

Config files you wrote or tuned (terminals, shells, window managers, editors, coding agents), the Mac's own settings
worth knowing (Dock, hot corners, keyboard, trackpad, Stage Manager), the layouts you work in (Warp's windows, tabs and
split panes and where each is; tmux; AeroSpace's workspaces), what you installed and run in the background, and the
machines you reach (Tailscale, ssh hosts, VMs).

Each version is a record of its own: a config's id is its path and a hash of what it says, so the corpus keeps every
version seen and a new one carries the diff from the last. Secrets in configs (API keys in an env block, tokens in a
.zshrc) are replaced by [redacted] before anything is written."""

import datetime as dt
import difflib
import fnmatch
import glob
import hashlib
import json
import os
import plistlib
import re
import shlex
import shutil
import sqlite3
import subprocess

from common import HOME, LIB, NORM, Writer, connect, from_unix, snapshot_sqlite
from redact import redact as redact_text

AVENUE = ("Local files and read-only commands. Configs (each version kept, with a diff from the last): Warp "
          "(~/.warp), Ghostty, tmux, kitty, WezTerm, Alacritty, zellij; zsh, bash, fish, starship, git, vim/neovim; "
          "AeroSpace, yabai, skhd, Hammerspoon, Karabiner, SketchyBar; VS Code, Cursor, Windsurf, Zed (settings, "
          "keybindings, extensions); Claude Code (settings, CLAUDE.md, agents, commands, skills), Codex, Gemini CLI, "
          "Claude Desktop's MCP servers. Mac settings via `defaults export` of the Dock, the global domain, trackpad, "
          "Finder, Stage Manager and apps like Rectangle and iTerm2, filtered to settings. Layouts: Warp's warp.sqlite "
          "(windows, tabs, pane splits, each pane's folder), `tmux list-panes -a`, `aerospace list-windows --all`. "
          "Installed: /Applications, `brew leaves`, ~/Library/LaunchAgents, scripts in ~/.local/bin and ~/bin. "
          "Machines: `tailscale status --json`, ~/.ssh/config's hosts, `prlctl list`, `colima list`, UTM's VMs; and, for hosts named "
          "in UMP_SETUP_HOSTS, the same configs plus uname, tmux, crontab, user services and containers over ssh (python3 there).")

NOW = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")  # when a version with no time of its own was first seen
CAP = 60_000  # characters of one config kept; a longer one is cut

# (group, tool, paths or globs under ~): what a person writes to shape their tools
FILES = [
    ("terminal", "Warp", [".warp/settings.toml", ".warp/tab_configs/*", ".warp/launch_configurations/*", ".warp/keybindings.yaml",
                          ".warp/themes/*"]),
    ("terminal", "Ghostty", [".config/ghostty/config", "Library/Application Support/com.mitchellh.ghostty/config"]),
    ("terminal", "tmux", [".tmux.conf", ".config/tmux/tmux.conf"]),
    ("terminal", "kitty", [".config/kitty/kitty.conf"]),
    ("terminal", "WezTerm", [".wezterm.lua", ".config/wezterm/wezterm.lua"]),
    ("terminal", "Alacritty", [".config/alacritty/alacritty.toml", ".config/alacritty/alacritty.yml"]),
    ("terminal", "zellij", [".config/zellij/config.kdl", ".config/zellij/layouts/*"]),
    ("shell", "zsh", [".zshrc", ".zprofile", ".zshenv", ".config/zsh/.zshrc"]),
    ("shell", "bash", [".bashrc", ".bash_profile"]),
    ("shell", "fish", [".config/fish/config.fish"]),
    ("shell", "starship", [".config/starship.toml"]),
    ("shell", "git", [".gitconfig", ".config/git/config"]),
    ("editor", "vim", [".vimrc", ".config/nvim/init.lua", ".config/nvim/init.vim"]),
    ("window manager", "AeroSpace", [".aerospace.toml", ".config/aerospace/aerospace.toml"]),
    ("window manager", "yabai", [".yabairc", ".config/yabai/yabairc"]),
    ("window manager", "skhd", [".skhdrc", ".config/skhd/skhdrc"]),
    ("window manager", "Hammerspoon", [".hammerspoon/init.lua"]),
    ("window manager", "SketchyBar", [".config/sketchybar/sketchybarrc"]),
    ("keyboard", "Karabiner", [".config/karabiner/karabiner.json"]),
    ("editor", "VS Code", ["Library/Application Support/Code/User/settings.json", "Library/Application Support/Code/User/keybindings.json"]),
    ("editor", "Cursor", ["Library/Application Support/Cursor/User/settings.json", "Library/Application Support/Cursor/User/keybindings.json",
                          ".cursor/mcp.json"]),
    ("editor", "Windsurf", ["Library/Application Support/Windsurf/User/settings.json", "Library/Application Support/Windsurf/User/keybindings.json"]),
    ("editor", "Zed", [".config/zed/settings.json", ".config/zed/keymap.json"]),
    ("agent", "Claude Code", [".claude/settings.json", ".claude/CLAUDE.md", ".claude/keybindings.json", ".claude/agents/*.md",
                              ".claude/commands/*.md", ".claude/skills/*/SKILL.md"]),
    ("agent", "Codex", [".codex/config.toml", ".codex/AGENTS.md", ".codex/prompts/*.md"]),
    ("agent", "Gemini CLI", [".gemini/settings.json", ".gemini/GEMINI.md"]),
    ("agent", "Claude Desktop", ["Library/Application Support/Claude/claude_desktop_config.json"]),
]
EXTENSIONS = [("VS Code", ".vscode/extensions/extensions.json"), ("Cursor", ".cursor/extensions/extensions.json"),
              ("Windsurf", ".windsurf/extensions/extensions.json")]

# (group, tool, defaults domain, keys kept or None for all a person sets): the Mac's settings and apps' preferences
DOMAINS = [
    ("mac", "Dock", "com.apple.dock", {"autohide", "autohide-delay", "orientation", "tilesize", "magnification", "largesize",
                                       "show-recents", "mru-spaces", "minimize-to-application", "persistent-apps", "persistent-others",
                                       "wvous-tl-corner", "wvous-tr-corner", "wvous-bl-corner", "wvous-br-corner", "expose-group-apps"}),
    ("mac", "Keyboard and text", "NSGlobalDomain", {"KeyRepeat", "InitialKeyRepeat", "ApplePressAndHoldEnabled", "AppleKeyboardUIMode",
                                                    "AppleInterfaceStyle", "AppleShowAllExtensions", "AppleShowScrollBars",
                                                    "com.apple.swipescrolldirection", "com.apple.keyboard.fnState",
                                                    "NSAutomaticSpellingCorrectionEnabled", "NSAutomaticCapitalizationEnabled",
                                                    "NSAutomaticPeriodSubstitutionEnabled", "NSAutomaticQuoteSubstitutionEnabled",
                                                    "NSAutomaticDashSubstitutionEnabled", "_HIHideMenuBar", "AppleReduceDesktopTinting",
                                                    "NSUserKeyEquivalents", "AppleLanguages", "AppleLocale"}),
    ("mac", "Trackpad", "com.apple.AppleMultitouchTrackpad", {"Clicking", "TrackpadThreeFingerDrag", "TrackpadRightClick",
                                                              "TrackpadScroll", "FirstClickThreshold", "ActuationStrength"}),
    ("mac", "Finder", "com.apple.finder", {"ShowPathbar", "ShowStatusBar", "FXPreferredViewStyle", "AppleShowAllFiles",
                                           "FXDefaultSearchScope", "NewWindowTarget", "_FXSortFoldersFirst", "FXEnableExtensionChangeWarning"}),
    ("mac", "Stage Manager and tiling", "com.apple.WindowManager", None),
    ("mac", "Menu bar", "com.apple.controlcenter", None),
    ("window manager", "Rectangle", "com.knollsoft.Rectangle", None),
    ("window manager", "Magnet", "com.crowdcafe.windowmagnet", None),
    ("window manager", "Moom", "com.manytricks.Moom", None),
    ("window manager", "Raycast", "com.raycast.macos", None),
    ("keyboard", "BetterTouchTool", "com.hegenberg.BetterTouchTool", None),
    ("terminal", "iTerm2", "com.googlecode.iterm2", None),
    ("terminal", "Ghostty", "com.mitchellh.ghostty", None),
    ("terminal", "Warp", "dev.warp.Warp-Stable", None),
]
# What an app writes for itself, not a choice of yours: window frames, launch counts, update checks, caches.
VOLATILE = re.compile(r"(?i)(date|time|count|last|launch|version|^SU|update|cache|recent|history|frame|^NSWindow|^NSSplitView|"
                      r"^NSToolbar|^NSNavPanel|^NSStatusItem|uuid|identifier|token|session|onboard|^MS|seen|shown|telemetry|"
                      r"analytics|install|nonce|^com\.apple\.ScreenTimeAgent|bookmark|position|^_|scroll|license)")

# A config's secret: the value of an env var or key named like one, besides the shapes redact.py knows.
SECRET_NAME = r"[\w.-]*(?:api[_-]?key|access[_-]?key|secret[_-]?key|private[_-]?key|_KEY|_key|token|TOKEN|secret|SECRET|passw(?:or)?d|PASSWORD|credential)s?"
SECRETS = [
    re.compile(rf"(?P<keep>\"{SECRET_NAME}\"\s*:\s*\")[^\"]+(?=\")"),  # JSON: "OPENAI_API_KEY": "..."
    re.compile(rf"(?im)(?P<keep>^\s*(?:export\s+)?{SECRET_NAME}\s*=\s*)(?![\d.]+\s*$|true\b|false\b)\S.*$"),  # TOML, shell
    re.compile(r"(?P<keep>(?:-H|--header)\s+['\"]?(?:Authorization|X-Api-Key|Api-Key)[:=]\s*)[^'\"\s]+(?:\s+[^'\"\s]+)?"),
    re.compile(rf"(?P<keep>\\\"{SECRET_NAME}\\\"\s*:\s*\\\")[^\\\"]+"),  # JSON inside a JSON string: \"token\":\"...\"
    re.compile(r"(?P<keep>\"--?(?:key|token|api[_-]?key|secret|password|auth|access[_-]?token)\"\s*,\s*\")[^\"]+(?=\")"),  # an MCP server's args
    re.compile(r"(?P<keep>--?(?:key|token|api[_-]?key|secret|password|access[_-]?token)[ =])(?!\[)[^\s\"']+"),
    re.compile(r"(?P<keep>)\b(?:lin_api|lin_oauth|xai|pplx|gsk|r8|sk_live|pk_live|sk_test|rk_live|tvly|fc|nvapi|pat)[-_][A-Za-z0-9_-]{16,}"),
    # Anything else shaped like a key: long, no path or dots, upper and lower case and digits (a git hash is all hex).
    re.compile(r"(?P<keep>)(?<![\w/.-])(?=[A-Za-z0-9_-]*[A-Z])(?=[A-Za-z0-9_-]*[a-z])(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{28,}(?![\w/.])"),
]


def redact(text):
    for pat in SECRETS:
        text = pat.sub(lambda m: m.group("keep") + "[redacted]", text)
    return redact_text(text)


def run(cmd, timeout=20):
    """A read-only command's output, or None when it isn't installed or fails."""
    if not shutil.which(cmd[0]) and not os.path.exists(cmd[0]):
        return None
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def tilde(p):
    p = str(p)
    return "~" + p[len(str(HOME)):] if p.startswith(str(HOME)) else p


class Versions:
    """Each thing's last version in the corpus, so a new one carries what changed."""

    def __init__(self):
        self.last = {}
        p = NORM / "setup.jsonl"
        if p.exists():
            for line in p.open(encoding="utf-8", errors="replace"):
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                k = (r.get("meta") or {}).get("what")
                if k and (k not in self.last or (r.get("ts") or "") >= (self.last[k].get("ts") or "")):
                    self.last[k] = r

    def add(self, w, what, kind, title, text, ts, meta):
        text = text if len(text) <= CAP else text[:CAP] + "\n[cut: longer than this]"
        digest = hashlib.sha256(text.encode()).hexdigest()[:16]
        rid = f"{what}@{digest}"
        if w.has(rid):
            return
        before = self.last.get(what)
        meta = {"what": what, **meta}
        if before and before.get("id") != rid:
            diff = list(difflib.unified_diff((before.get("text") or "").splitlines(), text.splitlines(), lineterm="", n=0))[2:]
            meta["changed"] = {"from": before["id"], "added": sum(1 for d in diff if d.startswith("+")),
                               "removed": sum(1 for d in diff if d.startswith("-")),
                               "diff": "\n".join(d for d in diff if not d.startswith("@@"))[:4000]}
            title = f"Changed: {title}"
        w.add(id=rid, kind=kind, ts=ts or NOW, title=title, text=text, author="me", is_me=True, thread=f"setup:{meta.get('group')}",
              thread_name=(meta.get("group") or "setup").capitalize(), meta=meta)


# ---------------------------------------------------------------- configs

def configs(w, v):
    for group, tool, pats in FILES:
        for pat in pats:
            for p in sorted(glob.glob(str(HOME / pat))):
                if not os.path.isfile(p) or os.path.getsize(p) > 5_000_000:
                    continue
                try:
                    text = open(p, encoding="utf-8", errors="replace").read()
                except OSError:
                    continue
                name = tilde(p)
                v.add(w, f"file:{name}", "config", f"{tool}: {name}", redact(text), from_unix(os.path.getmtime(p)),
                      {"group": group, "tool": tool, "path": name, "lines": text.count("\n") + 1})
    for tool, rel in EXTENSIONS:
        p = HOME / rel
        try:
            exts = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        ids = sorted({(e.get("identifier") or {}).get("id", "") for e in exts if isinstance(e, dict)} - {""})
        if ids:
            v.add(w, f"extensions:{tool}", "config", f"{tool}: {len(ids)} extensions", "\n".join(ids), from_unix(os.path.getmtime(p)),
                  {"group": "editor", "tool": tool, "path": tilde(p), "lines": len(ids)})


def plain(x, depth=0):
    """A plist value as short text: Dock tiles by name, data blobs and deep trees left out."""
    if isinstance(x, dict):
        label = (x.get("tile-data") or {}).get("file-label") if isinstance(x.get("tile-data"), dict) else None
        if label:
            return label
        if depth > 2:
            return "{…}"
        return "{" + ", ".join(f"{k}: {plain(val, depth + 1)}" for k, val in sorted(x.items()) if not isinstance(val, bytes)) + "}"
    if isinstance(x, list):
        return "[" + ", ".join(plain(i, depth + 1) for i in x[:60]) + ("…" if len(x) > 60 else "") + "]"
    if isinstance(x, bytes):
        return "<data>"
    return str(x)


def domains(w, v):
    for group, tool, domain, keep in DOMAINS:
        out = run(["defaults", "export", domain, "-"])
        if not out:
            continue
        try:
            d = plistlib.loads(out.encode())
        except Exception:
            continue
        lines = []
        for k in sorted(d):
            if keep is not None and k not in keep:
                continue
            if keep is None and (VOLATILE.search(k) or isinstance(d[k], bytes)):
                continue
            val = plain(d[k])
            if keep is None and len(val) > 400:
                continue
            lines.append(f"{k} = {val}")
        if lines:
            v.add(w, f"defaults:{domain}", "preference", f"{tool} settings", redact("\n".join(lines)), None,
                  {"group": group, "tool": tool, "domain": domain, "lines": len(lines)})


# ---------------------------------------------------------------- layouts

def warp_db():
    for p in (LIB / "Group Containers/2BBY89MBSN.dev.warp/Library/Application Support/dev.warp.Warp-Stable/warp.sqlite",
              LIB / "Application Support/dev.warp.Warp-Stable/warp.sqlite"):
        if p.exists():
            return p
    return None


def warp(w, v):
    db = warp_db()
    if not db:
        return
    con = connect(snapshot_sqlite(db, "setup/warp.sqlite"))
    try:
        wins = con.execute("select * from windows order by id").fetchall()
        tabs = con.execute("select * from tabs order by window_id, id").fetchall()
        nodes = {r["id"]: dict(r) for r in con.execute("select * from pane_nodes")}
        branch = {r["pane_node_id"]: r["horizontal"] for r in con.execute("select * from pane_branches")}
        leaves = {r["pane_node_id"]: dict(r) for r in con.execute("select * from pane_leaves")}
        cwd = {r["id"]: r["cwd"] for r in con.execute("select id, cwd from terminal_panes")}
    except sqlite3.Error as e:
        w.notes["warp"] = f"not read: {e}"
        return
    finally:
        con.close()
    kids = {}
    for n in nodes.values():
        kids.setdefault(n["parent_pane_node_id"], []).append(n)

    def tree(n, pad):
        if n["is_leaf"]:
            leaf = leaves.get(n["id"]) or {}
            where = tilde(cwd.get(n["id"])) if cwd.get(n["id"]) else ""
            return [f"{pad}{leaf.get('kind') or 'pane'} {where}".rstrip() + (" (focused)" if leaf.get("is_focused") else "")]
        ch = kids.get(n["id"], [])
        total = sum(c["flex"] or 1 for c in ch) or 1
        head = f"{pad}{'side by side' if branch.get(n['id']) else 'stacked'}:"
        out = [head]
        for c in ch:
            sub = tree(c, pad + "  ")
            out += [f"{pad}  {round(100 * (c['flex'] or 1) / total)}% {sub[0].strip()}"] + sub[1:]
        return out

    lines, panes = [], 0
    for win in wins:
        mine = [t for t in tabs if t["window_id"] == win["id"]]
        lines.append(f"Window {win['id']}: {int(win['window_width'] or 0)}x{int(win['window_height'] or 0)}"
                     f"{', full screen' if win['fullscreen_state'] else ''}, {len(mine)} tabs")
        for i, t in enumerate(mine):
            root = next((n for n in kids.get(None, []) if n["tab_id"] == t["id"]), None)
            name = t["custom_title"] or f"Tab {i + 1}"
            lines.append(f"  {name}{' (active)' if i == win['active_tab_index'] else ''}{' (pinned)' if t['pinned'] else ''}")
            if root:
                lines += tree(root, "    ")
        panes += sum(1 for n in nodes.values() if n["is_leaf"])
    if lines:
        v.add(w, "layout:Warp", "layout", f"Warp: {len(wins)} windows, {len(tabs)} tabs, {len(leaves)} panes", "\n".join(lines),
              from_unix(os.path.getmtime(db)), {"group": "terminal", "tool": "Warp", "windows": len(wins), "tabs": len(tabs), "panes": len(leaves)})


def tmux(w, v):
    out = run(["tmux", "list-panes", "-a", "-F", "#{session_name}\t#{window_index}\t#{window_name}\t#{window_layout}\t#{pane_index}\t#{pane_current_path}\t#{pane_current_command}"])
    if not out:
        return
    lines, sessions = [], set()
    last = None
    for row in out.splitlines():
        s, wi, wn, layout, pi, path, cmd = (row.split("\t") + [""] * 7)[:7]
        sessions.add(s)
        if (s, wi) != last:
            lines.append(f"{s}:{wi} {wn}  [{layout}]")
            last = (s, wi)
        lines.append(f"    pane {pi}: {cmd} in {tilde(path)}")
    v.add(w, "layout:tmux", "layout", f"tmux: {len(sessions)} sessions", "\n".join(lines), None,
          {"group": "terminal", "tool": "tmux", "sessions": len(sessions)})


def aerospace(w, v):
    out = run(["aerospace", "list-windows", "--all", "--format", "%{workspace}\t%{app-name}"])
    if not out:
        return
    by = {}
    for row in out.splitlines():
        ws, app = (row.split("\t") + [""])[:2]
        by.setdefault(ws, []).append(app)
    lines = [f"{ws}: {', '.join(sorted(set(apps)))}" for ws, apps in sorted(by.items())]
    v.add(w, "layout:AeroSpace", "layout", f"AeroSpace: {len(by)} workspaces in use", "\n".join(lines), None,
          {"group": "window manager", "tool": "AeroSpace", "workspaces": len(by)})


# ---------------------------------------------------------------- what's installed and running

def installed(w, v):
    apps = sorted({os.path.basename(p)[:-4] for d in ("/Applications", str(HOME / "Applications")) for p in glob.glob(d + "/*.app")})
    if apps:
        v.add(w, "installed:apps", "inventory", f"{len(apps)} apps installed", "\n".join(apps), None, {"group": "installed", "tool": "Applications"})
    brew = run(["brew", "leaves"], timeout=60) if shutil.which("brew") else None
    casks = run(["brew", "list", "--cask"], timeout=60) if shutil.which("brew") else None
    if brew or casks:
        text = "\n".join(x for x in ("Formulae:\n" + (brew or "").strip() if brew else None, "Casks:\n" + (casks or "").strip() if casks else None) if x)
        v.add(w, "installed:brew", "inventory", "Homebrew: what you installed", text, None, {"group": "installed", "tool": "Homebrew"})
    agents = []
    for p in sorted(glob.glob(str(HOME / "Library/LaunchAgents/*.plist"))):
        try:
            d = plistlib.loads(open(p, "rb").read())
        except Exception:
            continue
        prog = d.get("Program") or " ".join((d.get("ProgramArguments") or [])[:4])
        when = (f"every {d['StartInterval']}s" if d.get("StartInterval") else "on a calendar" if d.get("StartCalendarInterval")
                else "kept alive" if d.get("KeepAlive") else "at login" if d.get("RunAtLoad") else "on demand")
        agents.append(f"{d.get('Label') or os.path.basename(p)}: {tilde(prog)} ({when}){' [disabled]' if d.get('Disabled') else ''}")
    if agents:
        v.add(w, "installed:launch_agents", "inventory", f"{len(agents)} background jobs (LaunchAgents)", redact("\n".join(agents)), None,
              {"group": "installed", "tool": "launchd"})
    for d in (HOME / ".local/bin", HOME / "bin"):
        if d.is_dir():
            names = sorted(p.name for p in d.iterdir() if p.is_file() and os.access(p, os.X_OK) and not p.is_symlink())
            if names:
                v.add(w, f"installed:{tilde(d)}", "inventory", f"{len(names)} scripts of your own in {tilde(d)}", "\n".join(names), None,
                      {"group": "installed", "tool": "scripts", "path": tilde(d)})


# ---------------------------------------------------------------- machines

def machines(w, v):
    ts = run(["tailscale", "status", "--json"]) or run(["/Applications/Tailscale.app/Contents/MacOS/Tailscale", "status", "--json"])
    if ts:
        try:
            d = json.loads(ts)
            peers = [p for p in (d.get("Peer") or {}).values() if p.get("HostName") != "funnel-ingress-node"]
            lines = [f"{p.get('HostName')} ({p.get('OS') or '?'}){' online' if p.get('Online') else ''}"
                     f"{' (shared in)' if p.get('ShareeNode') else ''}" for p in sorted(peers, key=lambda p: str(p.get("HostName")))]
            me = d.get("Self") or {}
            v.add(w, "machines:tailscale", "inventory", f"Tailscale: {len(peers)} machines", f"This Mac: {me.get('HostName')}\n" + "\n".join(lines),
                  None, {"group": "machines", "tool": "Tailscale", "machines": len(peers)})
        except ValueError:
            pass
    cfg = HOME / ".ssh/config"
    if cfg.exists():
        hosts, cur = [], None
        for line in cfg.read_text(errors="replace").splitlines():
            m = re.match(r"(?i)\s*(host|hostname|user|proxyjump|proxycommand)\s+(.+)", line)
            if not m:
                continue
            k, val = m.group(1).lower(), m.group(2).strip()
            if k == "host":
                cur = {"host": val}
                hosts.append(cur)
            elif cur is not None and k in ("hostname", "user", "proxyjump"):
                cur[k] = val
            elif cur is not None:
                cur["via"] = "a command"
        lines = [h["host"] + "".join(f" {k}={h[k]}" for k in ("hostname", "user", "proxyjump", "via") if h.get(k)) for h in hosts if h["host"] != "*"]
        if lines:
            v.add(w, "machines:ssh", "inventory", f"ssh: {len(lines)} hosts you set up", "\n".join(lines), from_unix(cfg.stat().st_mtime),
                  {"group": "machines", "tool": "ssh", "hosts": len(lines)})
    vms = []
    prl = run(["prlctl", "list", "-a", "-o", "name,status"]) or run(["/usr/local/bin/prlctl", "list", "-a", "-o", "name,status"])
    vms += [f"Parallels: {l.strip()}" for l in (prl or "").splitlines()[1:] if l.strip()]
    col = run(["colima", "list", "--json"])
    for l in (col or "").splitlines():
        try:
            c = json.loads(l)
            vms.append(f"colima: {c.get('name')} ({c.get('status')}, {c.get('cpus')} CPUs, {round((c.get('memory') or 0) / 2**30)} GB)")
        except ValueError:
            pass
    utm = LIB / "Containers/com.utmapp.UTM/Data/Documents"
    vms += [f"UTM: {p.name[:-4]}" for p in sorted(utm.glob("*.utm"))] if utm.exists() else []
    if vms:
        v.add(w, "machines:vms", "inventory", f"{len(vms)} virtual machines", "\n".join(vms), None, {"group": "machines", "tool": "VMs"})


# ---------------------------------------------------------------- other machines, over ssh (opt-in: UMP_SETUP_HOSTS)

REMOTE = r"""
import glob, json, os, subprocess, sys
pats = json.loads(sys.argv[1]); home = os.path.expanduser("~"); out = {"files": {}, "cmds": {}}
for pat in pats:
    for p in sorted(glob.glob(os.path.join(home, pat)))[:50]:
        try:
            if os.path.isfile(p) and os.path.getsize(p) < 2000000:
                out["files"]["~" + p[len(home):]] = [open(p, errors="replace").read(), os.path.getmtime(p)]
        except OSError:
            pass
for name, cmd in (("system", "uname -srm; sw_vers 2>/dev/null; cat /etc/os-release 2>/dev/null | head -2"),
                  ("tmux", "tmux list-panes -a -F '#{session_name}:#{window_index} #{window_name} #{pane_current_command} #{pane_current_path}'"),
                  ("crontab", "crontab -l"), ("services", "systemctl --user list-units --type=service --state=running --no-legend --plain"),
                  ("containers", "docker ps --format '{{.Names}} {{.Image}} {{.Status}}'")):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            out["cmds"][name] = r.stdout[:20000]
    except Exception:
        pass
print(json.dumps(out))
"""
LINUX_FILES = [".config/i3/config", ".config/sway/config", ".config/hypr/hyprland.conf", ".xinitrc", ".config/systemd/user/*.service"]


def remote(w, v):
    """Each host in UMP_SETUP_HOSTS (ssh names, space-separated): its configs and what it runs, read over ssh with
    python3 there. Nothing is installed or left on the host."""
    hosts = (os.environ.get("UMP_SETUP_HOSTS") or "").split()
    pats = [p for _, _, ps in FILES for p in ps if not p.startswith("Library/")] + LINUX_FILES
    tools = {p: (g, t) for g, t, ps in FILES for p in ps}
    for host in hosts:
        try:
            r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, "python3 - " + shlex.quote(json.dumps(pats))],
                               input=REMOTE, capture_output=True, text=True, timeout=120)
            got = json.loads(r.stdout) if r.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired, ValueError):
            got = None
        if not got:
            w.notes.setdefault("hosts_not_read", []).append(host)
            continue
        for path, (text, mtime) in got["files"].items():
            group, tool = next(((g, t) for pat, (g, t) in tools.items() if fnmatch.fnmatch(path[2:], pat)), ("machines", "config"))
            v.add(w, f"{host}:file:{path}", "config", f"{host}: {tool}: {path}", redact(text), from_unix(mtime),
                  {"group": group, "tool": tool, "path": path, "host": host, "lines": text.count("\n") + 1})
        cmds = got["cmds"]
        if cmds:
            text = "\n\n".join(f"{k}:\n{val.strip()}" for k, val in cmds.items())
            v.add(w, f"{host}:running", "inventory", f"{host}: system, sessions and services", redact(text), None,
                  {"group": "machines", "tool": "ssh", "host": host})


def main():
    with Writer("setup", AVENUE) as w:
        v = Versions()
        for part in (configs, domains, warp, tmux, aerospace, installed, machines, remote):
            try:
                part(w, v)
            except Exception as e:  # one tool's odd file stops nothing else
                w.notes.setdefault("not_read", {})[part.__name__] = f"{type(e).__name__}: {e}"[:200]


if __name__ == "__main__":
    main()
