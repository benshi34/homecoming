"""Phone numbers in one form (+<country code><number>), read the way this Mac's region writes them.

A number saved without its country code ("07700 900123" in the UK, "(415) 555-0100" in the US) belongs to the region
the person lives in: the one chosen in Your Setup (UMP_PHONE_REGION), else this Mac's region (System Settings ->
General -> Language & Region), else the US. Each region's country code and the digit(s) dialled before a number at
home (the trunk prefix: 0 in most places, 1 in North America, none in Italy or Spain) come from the ITU's lists.
"""

import os
import plistlib
import re
from pathlib import Path

# region: (country code, trunk prefix). The places most people using this app live in; anywhere else, a number
# without its country code is kept as written.
REGIONS = {
    "US": ("1", "1"), "CA": ("1", "1"), "PR": ("1", "1"),
    "GB": ("44", "0"), "IE": ("353", "0"), "AU": ("61", "0"), "NZ": ("64", "0"), "ZA": ("27", "0"),
    "IN": ("91", "0"), "SG": ("65", ""), "HK": ("852", ""), "PH": ("63", "0"), "MY": ("60", "0"),
    "NG": ("234", "0"), "KE": ("254", "0"), "PK": ("92", "0"), "AE": ("971", "0"), "IL": ("972", "0"),
    "DE": ("49", "0"), "FR": ("33", "0"), "NL": ("31", "0"), "BE": ("32", "0"), "CH": ("41", "0"),
    "AT": ("43", "0"), "IT": ("39", ""), "ES": ("34", ""), "PT": ("351", ""), "GR": ("30", ""),
    "SE": ("46", "0"), "NO": ("47", ""), "DK": ("45", ""), "FI": ("358", "0"), "PL": ("48", ""),
    "CZ": ("420", ""), "JP": ("81", "0"), "KR": ("82", "0"), "CN": ("86", "0"), "TW": ("886", "0"),
    "MX": ("52", ""), "BR": ("55", "0"),
}
# What's dialled before an international number, besides "+": 00 almost everywhere, 011 in North America.
INTL = {"1": "011", "61": "0011", "81": "010"}


def mac_region(home=None):
    """This Mac's region ("US" from AppleLocale "en_US"), or None."""
    home = Path(home or Path.home())
    try:
        prefs = plistlib.loads((home / "Library/Preferences/.GlobalPreferences.plist").read_bytes())
    except Exception:
        return None
    m = re.match(r"[a-z]{2,3}(?:[-_][A-Za-z]{4})?[-_]([A-Z]{2})", str(prefs.get("AppleLocale") or ""))
    return m.group(1) if m else (str(prefs.get("Country") or "").upper() or None)


def region():
    return (os.environ.get("UMP_PHONE_REGION") or mac_region() or "US").upper()


def e164(value, reg=None):
    """"+<country code><number>" for a phone number, or None for something that isn't one."""
    s = str(value or "").strip()
    if not s or "@" in s:
        return None
    d = re.sub(r"\D", "", s)
    if len(d) < 5:
        return None
    if s.startswith("+"):
        return "+" + d
    cc, trunk = REGIONS.get((reg or region()).upper(), (None, None))
    for prefix in (INTL.get(cc or ""), "00"):  # the longer first: Australia's 0011 isn't 00 and 11...
        if prefix and d.startswith(prefix) and len(d) - len(prefix) >= 8:
            return "+" + d[len(prefix):]
    if cc is None:
        return "+" + d  # a region we don't know: as written
    if cc == "1":  # North America: ten digits, or eleven starting with 1
        return "+" + d if len(d) == 11 and d.startswith("1") else "+1" + d if len(d) == 10 else "+" + d
    if trunk and d.startswith(trunk):
        return "+" + cc + d[len(trunk):]
    if d.startswith(cc) and len(d) >= len(cc) + 8:  # the country code written without its "+"
        return "+" + d
    return "+" + cc + d


def info():
    """For the app: the region numbers are read in, the one this Mac is set to, and the regions there are."""
    reg = region()
    cc, trunk = REGIONS.get(reg, (None, None))
    return {"region": reg, "mac": mac_region(), "chosen": bool(os.environ.get("UMP_PHONE_REGION")), "cc": cc, "trunk": trunk,
            "intl": INTL.get(cc or "", "00"), "known": cc is not None, "regions": sorted(REGIONS)}
