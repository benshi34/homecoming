"""Your devices: each iPhone backed up to this Mac (its name, model, iOS and number), each phone line it has had (the
number, the carrier, the label you gave it such as Personal or Travel, eSIM or not, and when it was added), and this
Mac. Kept as records, so what you had, and when, can be looked up and asked about.

The SIM's own identifiers (ICCID, IMSI, IMEI, MEID, the serial number) are never read into a record: they say
nothing about you, and they're what someone asks a carrier for to move your number to their SIM."""

import os
import platform
import plistlib
import re
import subprocess
from pathlib import Path

from datetime import timezone

from common import HOME, RAW, Writer, from_unix
from phones import e164

BACKUPS = HOME / "Library/Application Support/MobileSync/Backup"
PHONE = RAW / "iphone"  # the decrypted copy of the newest backup (iphone_backup.py): <domain>/<path>
LINES = Path("WirelessDomain/Library/Preferences/com.apple.commcenter.data.plist")
AVENUE = ("Each iPhone backup's Info.plist in ~/Library/Application Support/MobileSync/Backup (unencrypted: Device "
          "Name, Product Type, Product Version, Phone Number, Last Backup Date); the phone lines from the decrypted "
          "backup's WirelessDomain com.apple.commcenter.data.plist (PersonalWallet: mdn, esim, cb_id, label-id, ts; "
          "unique-sim-label-store: the label's text); this Mac from sysctl hw.model, sw_vers and scutil. ICCID, IMSI, "
          "IMEI, MEID and serial numbers are left out.")


def read_plist(path):
    try:
        with open(path, "rb") as f:
            return plistlib.load(f)
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None


def when(v):
    """A plist date or Unix seconds, as an ISO time."""
    if hasattr(v, "astimezone"):  # plistlib gives naive UTC datetimes
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        return from_unix(float(v)) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def number(v):
    v = str(v or "").strip()
    return (e164(v) or v) if v else None


def carrier(cb_id):
    """com.apple.Verizon_US -> Verizon (cb_id is the carrier bundle the line uses)."""
    if not cb_id:
        return None
    name = str(cb_id).rsplit(".", 1)[-1]
    return re.sub(r"_[A-Z]{2}$", "", name).replace("_", " ") or None


def phones(w):
    """One record per iPhone (or iPad) backed up here: Info.plist, which Finder leaves unencrypted."""
    if not BACKUPS.is_dir():
        return
    try:
        folders = sorted(BACKUPS.iterdir())
    except OSError:  # no Full Disk Access
        w.notes["backups_not_allowed"] = 1
        return
    for d in folders:
        info = read_plist(d / "Info.plist")
        if not isinstance(info, dict):
            continue
        name, product = info.get("Device Name"), info.get("Product Type") or ""
        ios, num = info.get("Product Version"), number(info.get("Phone Number"))
        backed_up = when(info.get("Last Backup Date"))
        kind = "iPhone" if product.startswith("iPhone") else "iPad" if product.startswith("iPad") else "device"
        text = f"{name or kind} ({product}, iOS {ios})" + (f", number {num}" if num else "") + \
            (f", last backed up to this Mac {backed_up[:10]}" if backed_up else "")
        w.add(id=f"phone:{d.name}", kind="device", ts=backed_up, author="me", is_me=True, title=name or kind,
              text=text, meta={"device": kind, "product": product, "os": f"iOS {ios}" if ios else None,
                               "number": num, "backed_up": backed_up})


def lines(w):
    """One record per phone line the newest backup's phone has had (PersonalWallet), with its label's text."""
    pl = read_plist(PHONE / LINES)
    if not isinstance(pl, dict):
        return
    labels = {k: v.get("text") for k, v in (pl.get("unique-sim-label-store") or {}).items() if isinstance(v, dict)}
    seen = 0
    for sim in (pl.get("PersonalWallet") or {}).values():
        for z in (sim.values() if isinstance(sim, dict) else ()):
            if not isinstance(z, dict):
                continue
            num, label = number(z.get("mdn")), labels.get(z.get("label-id"))
            net, esim, added = carrier(z.get("cb_id")), bool(z.get("esim")), when(z.get("ts"))
            if not (num or label or net):
                continue
            seen += 1
            title = f"{label or 'Phone'} line" + (f" {num}" if num else "")
            text = title + (f", {net}" if net else "") + (", eSIM" if esim else ", SIM card") + \
                (f", added {added[:10]}" if added else "")
            w.add(id=f"line:{num or z.get('label-id') or seen}", kind="phone_line", ts=added, author="me", is_me=True,
                  title=title, text=text, meta={"number": num, "label": label, "carrier": net, "carrier_bundle": z.get("cb_id"),
                                               "esim": esim})


def mac(w):
    def run(*cmd):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip() or None
        except (OSError, subprocess.SubprocessError):
            return None
    model, name, version = run("sysctl", "-n", "hw.model"), run("scutil", "--get", "ComputerName"), platform.mac_ver()[0]
    if not (model or name):
        return
    text = f"{name or 'This Mac'} ({model}, macOS {version})"
    w.add(id=f"mac:{name or model}", kind="device", ts=None, author="me", is_me=True, title=name or "This Mac", text=text,
          meta={"device": "Mac", "product": model, "os": f"macOS {version}" if version else None, "this_mac": True})


def main():
    with Writer("devices", AVENUE) as w:
        phones(w)
        lines(w)
        if os.uname().sysname == "Darwin":
            mac(w)


if __name__ == "__main__":
    main()
