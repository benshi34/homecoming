"""Build desktop/data/services.json: the services people have accounts with, the web domains each one emails
and serves from, and, where known, how to get a copy of your data.

  python3 desktop/scripts/build_services.py [--check-links] [jdm_sites.json jgmd_sites.json]

Two community directories, both MIT-licensed (notices in desktop/data/THIRD_PARTY.md):
  JustDeleteMe (github.com/jdm-contrib/jdm): ~2,700 services with their domains and account pages. Its notes
    and links are about deleting accounts (a third of its links are the page that deletes yours), so only names,
    domains and privacy emails are kept, and a service's link is its home page.
  JustGetMyData (github.com/justgetmydata/jgmd): ~140 services' data-request pages and steps.
Without arguments both are fetched from GitHub. EXPORTS below adds pages checked by hand. Each service's kind
(the hub's sections) comes from data/categories.json, slug -> category, sorted once by Claude from each service's
name and domains; a service missing from it is "other" until it's added there.

--check-links visits every export page and looks up every service's domains, and writes what's dead to
data/link_check.json; every build leaves those out. A dead export page loses its link (a request by email still
works); a service none of whose domains exist any more is dropped. Pages that only stop scripts (403, captchas,
bad certificate chains) and sign-in pages count as alive.
"""

import http.client
import json
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

OUT = Path(__file__).resolve().parents[1] / "data/services.json"
CATEGORIES = OUT.parent / "categories.json"
LINKS = OUT.parent / "link_check.json"
JDM = "https://raw.githubusercontent.com/jdm-contrib/jdm/master/_data/sites.json"
JGMD = "https://raw.githubusercontent.com/justgetmydata/jgmd/master/_data/sites.json"

# Data-download pages the directories lack or get wrong, each checked against the service's own help pages and
# walked in a signed-in browser up to the request button (2026-10-12).
EXPORTS = {
    "amazon-audible": {"url": "https://www.amazon.com/hz/privacy-central/data-requests/preview.html",
                       "notes": "Amazon asks you to sign in again here. Choose the information you want (\"Request All Your Data\" "
                                "covers everything), then Submit Request. Click the link in the email Amazon sends: a request "
                                "that isn't confirmed is never started. The download link arrives by email, usually within a day.",
                       "difficulty": "easy"},
    "apple-account-itunes": {"url": "https://privacy.apple.com/",
                             "notes": "Sign in, choose Request a copy of your data, tick what you want, then Continue. If it asks "
                                      "for a largest file size, the biggest means fewer parts. Apple checks it's you, then puts "
                                      "the files on this page and tells you. You have 14 days to download them.",
                             "difficulty": "easy"},
    "booking": {"url": "https://www.booking.com/content/dsar.html",
                "notes": "Fill in your name and email, choose \"Right to obtain a copy of my personal data\" (in some places "
                         "\"Right of access to personal data\"), then Submit request. Open the link in the email Booking.com sends "
                         "within 24 hours and click Confirm request. The report comes by email, within the time the law "
                         "allows (up to 30 or 45 days).",
                "difficulty": "medium", "email": "privacyrequests@booking.com"},
    "craigslist": {"url": "https://www.craigslist.org/contact?step=form&reqKey=a38",
                   "notes": "Craigslist's Download my data form. Sign in so it knows it's you, then fill it in and send it. "
                            "Without an account, email ccpa@craigslist.org.",
                   "difficulty": "medium", "email": "ccpa@craigslist.org"},
    "duolingo": {"url": "https://drive-thru.duolingo.com/",
                 "notes": "Sign in at duolingo.com first, then open this page again: Data Vault doesn't send you there and "
                          "back. Ask for a copy of your data (the same page can delete your account: not that button). "
                          "Duolingo says it can take up to 30 days.",
                 "difficulty": "medium"},
    "ea-games-origin-electronic-arts": {"url": "https://myaccount.ea.com/cp-ui/downloaddata/index",
                                        "notes": "Sign in, then Request a download under Download your EA data (EA Account → "
                                                 "Security and Privacy). It's usually ready in under two hours: download it "
                                                 "from the same page.",
                                        "difficulty": "easy", "email": "dpo@ea.com"},
    "github": {"url": "https://github.com/settings/admin",
               "notes": "Settings → Account → Export account data → Start export. GitHub emails a download link to your "
                        "primary address. It lasts 7 days and may ask for your password again.",
               "difficulty": "easy"},
    "lyft": {"url": "https://account.lyft.com/privacy/data",
             "notes": "Sign in with the code Lyft texts you, then click Start under Download Data. Lyft emails when it's "
                      "ready, usually in a few days. US and Canada only.",
             "difficulty": "easy"},
    "microsoft-account": {"url": "https://account.microsoft.com/privacy/download-data",
                          "notes": "Sign in, then Download your data → Create new archive. It's ready on the same page under "
                                   "Archives (there's no email), as a zip of JSON files. It has your activity: searches, "
                                   "browsing, location and app use. Outlook mail and OneDrive have their own exports. For "
                                   "everything else Microsoft holds, ask at account.microsoft.com/privacy/privacy-request "
                                   "(Export my data).",
                          "difficulty": "medium"},
    "netflix": {"url": "https://www.netflix.com/account/getmyinfo",
                "notes": "Sign in (Netflix may send a code first), then Submit Request and confirm it from the email Netflix "
                         "sends. Netflix emails when it's ready, within 30 days. Only the account owner can ask: with just a "
                         "profile on someone else's account, email privacy@netflix.com.",
                "difficulty": "medium"},
    "patreon": {"url": "https://privacy.patreon.com/?action=ACCESS&modal=take-control",
                "notes": "Take Control → Download all my data, then sign in to Patreon to show it's you. It's usually ready "
                         "within minutes (Patreon allows up to 30 days). The link comes by email and the report stays "
                         "there for 14 days.",
                "difficulty": "easy", "email": "privacy@patreon.com"},
    "paypal": {"url": "https://www.paypal.com/myaccount/privacy/data/dar",
               "notes": "Settings → Data & Privacy → Download your data: choose what to include, then Submit Request. For "
                        "your payments, also download Activity → the download icon → a Custom report as CSV (12 months per "
                        "file, up to 7 years back).",
               "difficulty": "easy"},
    "steam": {"url": "https://help.steampowered.com/en/accountdata",
              "notes": "Steam has no single download. Sign in: this page lists your account data by kind (purchases, "
                       "logins, playtime and more), each on a page of its own. Open the ones you want and save each with "
                       "File → Save Page As. For anything else, Contact Steam Support with an account data question.",
              "difficulty": "medium"},
    "tiktok": {"url": "https://www.tiktok.com/setting/download-your-data",
               "notes": "On Request data: choose JSON (the default is TXT), click Select all (nothing is ticked to start), "
                        "then Request data. It's often ready within hours (TikTok allows a few days). Download it from the "
                        "Download data tab on the same page within 4 days: TikTok emails you a code to type in first.",
               "difficulty": "easy"},
    "tumblr": {"url": "https://www.tumblr.com/settings/privacy",
               "notes": "Settings → Privacy → Request Privacy Data (on the web: the apps don't have it). Tumblr emails to "
                        "check, then again when it's ready, up to 30 days later: download it from the same page. Your posts "
                        "and media are a separate export: Settings → pick the blog → Export, kept for 3 days.",
               "difficulty": "easy"},
    "uber": {"url": "https://myprivacy.uber.com/privacy/exploreyourdata/download",
             "notes": "Uber asks you to sign in again here, with a code, even when you're already signed in. Then choose "
                      "Download your data. Uber emails or texts when it has the request and again when the file is ready.",
             "difficulty": "medium"},
    "wattpad": {"url": "https://www.wattpad.com/settings",
                "notes": "Sign in, then on Settings scroll to Download your Personal Information and choose JSON (not HTML): "
                         "it downloads straight away. For more than this summary, email privacy@wattpad.com.",
                "difficulty": "easy", "email": "privacy@wattpad.com"},
    "wechat": {"url": "https://cs.help.wechat.com/hc/en-us/articles/11916362921871-FAQ-for-Data-Export",
               "notes": "Only the phone app can ask: Me → Settings → Privacy → My Information & Authorizations → View and "
                        "Export Personal Data. Give your email, tap OK in the email WeChat sends, then choose the data and "
                        "submit. A link arrives within 3 business days: open it on this Mac, scan the QR code with WeChat, "
                        "and unzip the download with the password it shows. Chats aren't kept on WeChat's servers, so it "
                        "has Moments, Favorites and account details only.",
               "difficulty": "medium"},
    "wikipedia": {"url": "https://en.wikipedia.org/w/api.php?action=query&meta=userinfo&uiprop=email%7Cregistrationdate%7C"
                         "rights%7Cgroups%7Coptions%7Ceditcount%7Clatestcontrib&format=json",
                  "notes": "Wikipedia has no download. Sign in to Wikipedia first, then open this page: it shows your "
                           "account (sign-up date, groups, edit count and settings) as JSON. Save it with File → Save Page "
                           "As. Your edits are listed at Special:Contributions.",
                  "difficulty": "easy"},
}
# Typos in JustDeleteMe's domains, found by --check-links (the misspelled ones don't exist).
DOMAIN_FIXES = {"ardwarewebwinkel.nl": "hardwarewebwinkel.nl", "serviciosenlinea.sinac.go.cra": "serviciosenlinea.sinac.go.cr"}
# Dead in ways a script can't tell: the page loads but what it pointed to is gone (checked 2026-10-09).
DEAD_BY_HAND = {
    "https://engadget.mydashboard.oath.com/#section-manage": "Oath's privacy dashboard was retired (400 for every page)",
}
GONE_BY_HAND = {
    "myworld": "myworld.com redirects to a domain seller; its other sites don't resolve or answer",
}


def load(arg, url):
    if arg:
        return json.loads(Path(arg).read_text())
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read())


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def host(url):
    h = (urlparse(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def parents(h):
    """privacy.apple.com -> privacy.apple.com, apple.com"""
    parts = h.split(".")
    return [".".join(parts[i:]) for i in range(len(parts) - 1)]


def site(url, domains):
    """A service's home page: the main domain its link sits under (support.wattpad.com/... -> wattpad.com), on
    the link's own host when that is the main site (www.tumblr.com/account/delete -> www.tumblr.com)."""
    if not domains:
        return None
    h = (urlparse(url or "").hostname or "").lower()
    main = min(domains, key=lambda d: (d.count("."), len(d)))
    mine = [d for d in parents(h.removeprefix("www.")) if d in domains]
    d = mine[-1] if mine and mine[-1].count(".") <= main.count(".") else main  # not engadget.mydashboard.oath.com
    return "https://" + (h if d == h.removeprefix("www.") else d)


def plain(notes):
    """JGMD's notes are Markdown and the app shows them as text: [privacy@x.com](mailto:privacy@x.com) -> the
    address (from the link: its text is sometimes mangled), [ticket form](https://help.x.com/...) -> ticket form
    (help.x.com), and links into JGMD's own page ([Google](./#google)) -> their text."""
    def one(m):
        text, url = m.group(1), m.group(2)
        if url.startswith("mailto:"):
            return url.removeprefix("mailto:")
        h = host(url)
        return f"{text} ({h})" if h and h not in text else text
    return re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", one, notes) if notes else notes


def export_url(s):
    """JGMD sometimes links the home page and puts the real page in the notes."""
    u = s.get("url") or ""
    if urlparse(u).path in ("", "/"):
        m = re.search(r"https?://[^\s'\")]+", s.get("notes") or "")
        if m:
            return m.group(0).rstrip(".,")
    return u


def main(argv, check=False):
    jdm = load(argv[0] if argv else None, JDM)
    jgmd = load(argv[1] if len(argv) > 1 else None, JGMD)
    out = {}
    for s in jdm:
        if not s.get("name") or not s.get("domains"):
            continue
        domains = sorted({DOMAIN_FIXES.get(d, d) for d in (d.lower().removeprefix("www.") for d in s["domains"])})
        e = {"slug": slug(s["name"]) or slug(s["domains"][0]), "name": s["name"], "domains": domains, "site": site(s.get("url"), domains)}
        if s.get("email"):
            e["privacy_email"] = s["email"]
        if s.get("meta") == "popular":
            e["popular"] = True
        out.setdefault(e["slug"], e)
    by_domain = {d: e for e in out.values() for d in e["domains"]}
    for s in jgmd:
        key = slug(s["name"])
        e = out.get(key) or next((by_domain[d] for d in parents(host(s.get("url") or "")) if d in by_domain), None)
        if e and key not in out and "export" in e:
            continue  # "YouTube / YouTube Music" pointing at Takeout mustn't replace Google's own steps
        if not e:
            domains = [host(s["url"])] if host(s.get("url") or "") else []
            e = out[key] = {"slug": key, "name": s["name"], "domains": domains, "site": site(s.get("url"), domains)}
        e["export"] = {k: v for k, v in {"url": export_url(s), "notes": plain(s.get("notes")), "difficulty": s.get("difficulty"),
                                         "email": s.get("email")}.items() if v}
        if s.get("meta") == "popular":
            e["popular"] = True
    for key, x in EXPORTS.items():
        if key in out:
            out[key]["export"] = x
    if check:
        check_links(out.values())
    dead = {**(json.loads(LINKS.read_text()) if LINKS.exists() else {}).get("dead", {}), **DEAD_BY_HAND}
    kinds = json.loads(CATEGORIES.read_text()) if CATEGORIES.exists() else {}
    rows, gone, unlinked = [], 0, 0
    for e in out.values():
        if e["slug"] in GONE_BY_HAND or e["domains"] and all(d in dead for d in e["domains"]):  # its mail bounces too
            gone += 1
            continue
        if (urlparse(e["site"]).hostname or "").removeprefix("www.") in dead:
            e["site"] = "https://" + next(d for d in e["domains"] if d not in dead)
        x = e.get("export")
        if x and x.get("url") in dead:
            unlinked += 1
            x.pop("url")
            if not x.get("email"):
                del e["export"]  # its steps were about that page
        e["category"] = kinds.get(e["slug"], "other")
        rows.append(e)
    rows.sort(key=lambda e: e["name"].lower())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"{len(rows)} services ({sum('export' in e for e in rows)} with export steps) -> {OUT}; "
          f"left out {gone} that no longer exist and {unlinked} dead export pages")


UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
NOT_FOUND = re.compile(r"\b(404|page not found|not found|doesn.t exist|does not exist|no longer available)\b", re.I)
# python.org's Python ships without root certificates; the system's are here.
TLS = ssl.create_default_context(cafile="/etc/ssl/cert.pem" if Path("/etc/ssl/cert.pem").exists() else None)


def read(r):
    try:
        return r.read(200_000)
    except http.client.IncompleteRead as e:  # the page answered, then cut off
        return e.partial


def page_dead(url, tries=3):
    """Why an export page is dead, or None while it's there (including pages that only stop scripts)."""
    why = f"no answer in {tries} tries"
    for _ in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*", "Accept-Language": "en-US,en"})
        try:
            with urllib.request.urlopen(req, timeout=20, context=TLS) as r:
                status, body = r.status, read(r)
        except urllib.error.HTTPError as e:
            status, body = e.code, read(e) if e.fp else b""
        except urllib.error.URLError as e:
            if isinstance(e.reason, socket.gaierror):
                why = "no such site"
            elif isinstance(e.reason, ssl.SSLError):
                return None  # an incomplete certificate chain: browsers fetch the missing piece
            time.sleep(5)
            continue  # timed out or refused: try again
        except (TimeoutError, ConnectionError):
            time.sleep(5)
            continue
        except http.client.HTTPException:
            return None  # it answered, oddly
        if status in (404, 410):
            return f"not found ({status})"
        m = re.search(rb"<title[^>]*>(.*?)</title>", body, re.I | re.S)
        title = m.group(1).decode("utf-8", "replace") if m else ""
        return f"page says {' '.join(title.split())[:80]!r}" if NOT_FOUND.search(title) else None
    return why


def domain_dead(d):
    for h in dict.fromkeys((d, "www." + d, ".".join(d.split(".")[-2:]))):
        try:
            socket.getaddrinfo(h, 443)
            return None
        except socket.gaierror:
            pass
        except OSError:
            return None
    return "no such domain"


CONTROLS = ("apple.com", "google.com", "wikipedia.org")


def online():
    return not any(domain_dead(d) for d in CONTROLS)


def check_links(services):
    services = list(services)
    pages = sorted({e["export"]["url"] for e in services if e.get("export", {}).get("url")})
    domains = sorted({d for e in services for d in e["domains"]})
    if not online():
        sys.exit("Offline (apple.com, google.com and wikipedia.org don't resolve): nothing checked.")
    with ThreadPoolExecutor(8) as ex:
        dead = {u: why for u, why in zip(pages, ex.map(page_dead, pages)) if why}
        first = [d for d, why in zip(domains, ex.map(domain_dead, domains)) if why]
        time.sleep(30)  # a lookup can fail for a moment: only what fails twice counts
        dead |= {d: why for d, why in zip(first, ex.map(domain_dead, first)) if why}
    # A dropped connection makes everything look dead (2026-10-09: all 6,167 domains): keep the last check.
    if not online() or len(dead) > 0.2 * (len(pages) + len(domains)):
        sys.exit(f"{len(dead)} of {len(pages) + len(domains)} links look dead, more than a lost connection explains: "
                 f"{LINKS.name} left as it was. Try again.")
    LINKS.write_text(json.dumps({"checked": date.today().isoformat(), "pages": len(pages), "domains": len(domains),
                                 "dead": dict(sorted(dead.items()))}, indent=1, ensure_ascii=False) + "\n")
    print(f"checked {len(pages)} export pages and {len(domains)} domains: {len(dead)} dead -> {LINKS}")


if __name__ == "__main__":
    args = sys.argv[1:]
    check = "--check-links" in args
    main([a for a in args if a != "--check-links"], check)
