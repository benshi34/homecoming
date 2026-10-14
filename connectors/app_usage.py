"""Screen time: which app was in focus when, on every Apple device synced to this Mac
(Mac, iPhone, iPad), plus what was playing (music / podcasts / video) via Now Playing."""

import collections
import hashlib
import json
import plistlib
from pathlib import Path

import segb
from common import LIB, Writer, connect, from_apple

AVENUE = ("Local Biome streams (SEGB files of protobufs), needs Full Disk Access: "
          "~/Library/Biome/streams/restricted/App.InFocus/{local,remote/<device>}/ and Media.NowPlaying/. "
          "remote/ holds other devices on the same Apple ID (iPhone, iPad, other Macs). "
          "Device names/OS builds in ~/Library/Biome/sync/sync.db DevicePeer. Only ~4 weeks retained.")

STREAMS = LIB / "Biome/streams/restricted"
PLATFORMS = {1: "iPad", 2: "iPhone", 3: "Mac", 4: "Mac"}
IOS_NAMES = {
    "com.apple.MobileSMS": "Messages", "com.apple.camera": "Camera", "com.atebits.Tweetie2": "X",
    "com.tencent.xin": "WeChat", "com.google.Maps": "Google Maps", "com.burbn.instagram": "Instagram",
    "com.apple.mobilesafari": "Safari", "com.apple.mobilephone": "Phone", "com.apple.InCallService": "Phone call",
    "com.apple.mobileslideshow": "Photos", "com.apple.mobilemail": "Mail", "com.apple.mobilenotes": "Notes",
    "com.google.ios.youtube": "YouTube", "com.netflix.Netflix": "Netflix", "com.spotify.client": "Spotify",
    "com.hammerandchisel.discord": "Discord", "net.whatsapp.WhatsApp": "WhatsApp", "com.facebook.Messenger": "Messenger",
    "com.zhiliaoapp.musically": "TikTok", "com.reddit.Reddit": "Reddit", "com.linkedin.LinkedIn": "LinkedIn",
    "com.tinyspeck.chatlyio": "Slack", "com.openai.chat": "ChatGPT", "com.anthropic.claude": "Claude",
    "com.goodnotesapp.x": "GoodNotes", "com.apple.Music": "Music", "com.apple.podcasts": "Podcasts",
    "com.apple.Maps": "Apple Maps", "com.apple.mobilecal": "Calendar", "com.apple.reminders": "Reminders",
    "com.apple.Preferences": "Settings", "com.apple.AppStore": "App Store", "com.apple.Health": "Health",
    "com.venmo.TouchFree": "Venmo", "com.ubercab.UberClient": "Uber", "com.google.chrome.ios": "Chrome",
}
SYSTEM = ("com.apple.loginwindow", "com.apple.springboard", "com.apple.ScreenSaver", "SBSpotlightAlert",
          "com.apple.SecurityAgent", "com.apple.UserNotificationCenter", "com.apple.dock")
MAX_SESSION = 3 * 3600


def mac_app_names():
    names = {}
    for root in (Path("/Applications"), Path("/System/Applications"), Path.home() / "Applications"):
        for app in list(root.glob("*.app")) + list(root.glob("*/*.app")):
            try:
                info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
                bid = info.get("CFBundleIdentifier")
                if bid:
                    names[bid] = info.get("CFBundleDisplayName") or info.get("CFBundleName") or app.stem
            except (OSError, plistlib.InvalidFileException, ValueError):
                pass
    return names


def devices():
    out = {"local": "this Mac"}
    try:
        con = connect(LIB / "Biome/sync/sync.db")
        for r in con.execute("select device_identifier, name, model, platform, me from DevicePeer"):
            label = r["name"] or f"{PLATFORMS.get(r['platform'], 'device')} ({r['model']})"
            out[r["device_identifier"]] = "this Mac" if r["me"] else label
    except Exception:
        pass
    return out


def app_name(bid, names):
    if bid in names:
        return names[bid]
    if bid in IOS_NAMES:
        return IOS_NAMES[bid]
    return bid.split(".")[-1] if bid else "unknown"


def main():
    names, devs = mac_app_names(), devices()
    with Writer("app_usage", AVENUE) as w:
        # App focus sessions
        events = collections.defaultdict(list)
        for dev, f in segb.stream_files(STREAMS / "App.InFocus"):
            for _, buf in segb.records(f):
                r = segb.decode(buf)
                bid, t = r.get(6), r.get(4)
                if isinstance(bid, str) and isinstance(t, float):
                    events[dev].append((t, r.get(3) == 1, bid))
        sessions = {}  # id -> (device, day, app, seconds); seeded with earlier runs so day totals survive retention
        if w.path.exists():
            for line in w.path.open():
                r = json.loads(line)
                if r.get("kind") == "app_usage":
                    sessions[r["id"]] = (r["thread"], r["ts"][:10], r["title"], r["meta"]["seconds"])
        for dev, evs in events.items():
            evs = sorted(set(evs))
            device = devs.get(dev, dev)
            open_app = None
            for t, starting, bid in evs + [(float("inf"), False, None)]:
                if open_app and (starting or bid == open_app[1] or bid is None):
                    start, obid = open_app
                    secs = min(t, start + MAX_SESSION) - start
                    open_app = None
                    if secs >= 2 and not obid.startswith(SYSTEM):
                        name = app_name(obid, names)
                        ts = from_apple(start)
                        w.add(id=f"{dev}:{start:.3f}:{obid}", kind="app_usage", ts=ts, ts_end=from_apple(start + secs),
                              author="me", is_me=True, thread=device, thread_name=device, title=name,
                              text=f"{name} on {device} for {round(secs / 60, 1)} min",
                              meta={"bundle": obid, "seconds": round(secs), "device": device})
                        sessions[f"{dev}:{start:.3f}:{obid}"] = (device, ts[:10], name, secs)
                if starting and t != float("inf"):
                    open_app = (t, bid)
        daily = collections.defaultdict(collections.Counter)
        for device, day, name, secs in sessions.values():
            daily[(device, day)][name] += secs
        for (device, day), apps in sorted(daily.items()):
            total = sum(apps.values())
            top = ", ".join(f"{a} {round(s / 60)}m" for a, s in apps.most_common(15) if s >= 60)
            w.add(id=f"day:{device}:{day}", kind="app_usage_day", ts=f"{day}T00:00:00Z", author="me", is_me=True,
                  thread=device, thread_name=device, title=f"Screen time {day} ({device})",
                  text=f"Screen time on {device}, {day}: {round(total / 3600, 1)} h. {top}",
                  meta={"device": device, "minutes": {a: round(s / 60) for a, s in apps.most_common()}})

        # Now Playing (music, podcasts, video)
        last = {}
        for dev, f in segb.stream_files(STREAMS / "Media.NowPlaying"):
            for ts, buf in segb.records(f):
                r = segb.decode(buf)
                title, artist, album, bid = r.get(4), r.get(5), r.get(8), r.get(15)
                if r.get(3) != 1 or not isinstance(title, str) or not title:
                    continue
                ts = r[2] if isinstance(r.get(2), float) else ts
                key = (dev, title, artist)
                if key in last and ts - last[key] < 600:
                    continue  # same track still playing
                last[key] = ts
                device = devs.get(dev, dev)
                app = app_name(bid, names) if isinstance(bid, str) else None
                nid = f"np:{dev}:{ts:.0f}:" + hashlib.sha1(f"{title}|{artist}".encode()).hexdigest()[:8]
                if w.has(nid):
                    continue
                w.add(id=nid, kind="media", ts=from_apple(ts), author="me", is_me=True,
                      thread=device, thread_name=device, title=title,
                      text=" — ".join(x for x in (title, artist, album) if isinstance(x, str) and x) + (f" ({app})" if app else ""),
                      meta={k: v for k, v in (("artist", artist), ("album", album), ("app", app), ("device", device),
                                              ("duration", r.get(6))) if v})


if __name__ == "__main__":
    main()
