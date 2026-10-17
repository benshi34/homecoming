"""The web browsers this Mac may have: where each keeps its history, its app, and whether Claude can work in it.

Chromium browsers all keep Chrome's History database, one per profile folder; Firefox and its relatives keep
places.sqlite. A browser's data folder alone doesn't mean it's installed (Claude Code, for one, writes a file into
every Chromium browser's folder), so being here means its app is in Applications.

UMP_BROWSERS_SKIP (comma-separated ids) lists the browsers whose history the person chose not to read.
"""

import os
from pathlib import Path

HOME = Path.home()
SUPPORT = HOME / "Library/Application Support"

# id, name, app bundle names, bundle id, kind, data folder, Claude in Chrome works in it (code.claude.com/docs/en/chrome:
# Chrome and Edge, and Claude Code also connects in Brave, Arc, Vivaldi and Opera).
BROWSERS = [
    ("safari", "Safari", ["Safari"], "com.apple.safari", "safari", HOME / "Library/Safari", False),
    ("chrome", "Chrome", ["Google Chrome"], "com.google.chrome", "chromium", SUPPORT / "Google/Chrome", True),
    ("arc", "Arc", ["Arc"], "company.thebrowser.browser", "chromium", SUPPORT / "Arc/User Data", True),
    ("edge", "Edge", ["Microsoft Edge"], "com.microsoft.edgemac", "chromium", SUPPORT / "Microsoft Edge", True),
    ("brave", "Brave", ["Brave Browser"], "com.brave.browser", "chromium", SUPPORT / "BraveSoftware/Brave-Browser", True),
    ("vivaldi", "Vivaldi", ["Vivaldi"], "com.vivaldi.vivaldi", "chromium", SUPPORT / "Vivaldi", True),
    ("opera", "Opera", ["Opera"], "com.operasoftware.opera", "chromium", SUPPORT / "com.operasoftware.Opera", True),
    ("dia", "Dia", ["Dia"], "company.thebrowser.dia", "chromium", SUPPORT / "Dia/User Data", False),
    ("chromium", "Chromium", ["Chromium"], "org.chromium.chromium", "chromium", SUPPORT / "Chromium", False),
    ("chrome_beta", "Chrome Beta", ["Google Chrome Beta"], "com.google.chrome.beta", "chromium", SUPPORT / "Google/Chrome Beta", False),
    ("chrome_canary", "Chrome Canary", ["Google Chrome Canary"], "com.google.chrome.canary", "chromium", SUPPORT / "Google/Chrome Canary", False),
    ("firefox", "Firefox", ["Firefox"], "org.mozilla.firefox", "firefox", SUPPORT / "Firefox", False),
    ("zen", "Zen", ["Zen", "Zen Browser"], "app.zen-browser.zen", "firefox", SUPPORT / "zen", False),
]
BY_ID = {b[0]: b for b in BROWSERS}


def app_path(names):
    """Where the app is: Applications (UMP_APPLICATIONS in the tests), or the one in your home folder."""
    for root in (Path(os.environ.get("UMP_APPLICATIONS") or "/Applications"), HOME / "Applications"):
        for n in names:
            p = root / f"{n}.app"
            if p.exists():
                return p
    return None


def skipped():
    return {s.strip() for s in os.environ.get("UMP_BROWSERS_SKIP", "").split(",") if s.strip()}


def chromium_profiles(root):
    """(folder, History file) for each profile. Opera keeps its one profile in the data folder itself."""
    found = sorted(root.glob("*/History"))
    if (root / "History").is_file():
        found.insert(0, root / "History")
    return [(p.parent.name if p.parent != root else "Default", p) for p in found]


def firefox_profiles(root):
    return [(p.parent.name, p) for p in sorted(root.glob("Profiles/*/places.sqlite"))]


def history_files(bid):
    """(profile folder, database) for each profile of browser `bid` that has history on this Mac."""
    _, _, _, _, kind, root, _ = BY_ID[bid]
    try:
        if kind == "safari":
            return [("default", root / "History.db")] if (root / "History.db").exists() else []
        return chromium_profiles(root) if kind == "chromium" else firefox_profiles(root)
    except OSError:
        return []


def default_browser():
    """The bundle id of the app that opens web links, from Launch Services; Safari when none was ever chosen."""
    import plistlib
    try:
        prefs = plistlib.loads((HOME / "Library/Preferences/com.apple.LaunchServices/com.apple.launchservices.secure.plist").read_bytes())
        for h in prefs.get("LSHandlers", []):
            if h.get("LSHandlerURLScheme") == "https" and h.get("LSHandlerRoleAll"):
                return h["LSHandlerRoleAll"].lower()
    except Exception:
        pass
    return "com.apple.safari"


def found():
    """Every browser that's installed or has history here, for the app: what it is, where its app is, whether its
    history is read, and whether Claude can work in it."""
    default = default_browser()
    out = []
    for bid, name, apps, bundle, kind, root, claude in BROWSERS:
        app = app_path(apps)
        profiles = history_files(bid)
        if not app and not profiles:
            continue
        out.append({"id": bid, "name": name, "app": str(app) if app else None, "profiles": len(profiles),
                    "history": bool(profiles), "read": bid not in skipped(), "claude": claude and bool(app),
                    "default": bundle == default})
    return out
