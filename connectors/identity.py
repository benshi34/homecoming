"""Who "me" is across sources. Loaded from corpus/identity.json (written during onboarding);
falls back to the macOS Contacts "me" card. Used to set is_me on emails, chats and exports."""

import json

from common import CORPUS

PATH = CORPUS / "identity.json"


def load():
    data = {"names": [], "emails": [], "usernames": [], "phones": []}
    if PATH.exists():
        data.update(json.loads(PATH.read_text()))
    else:
        try:
            from contacts import load_contacts
            for c in load_contacts():
                if c["is_me"]:
                    data["names"].append(c["name"])
                    data["emails"] += [v for _, v in c["emails"]]
                    data["phones"] += [v for _, v in c["phones"]]
        except Exception:
            pass
    data["names_l"] = {n.lower() for n in data["names"] if n}
    data["emails_l"] = {e.lower() for e in data["emails"] if e}
    data["usernames_l"] = {u.lower() for u in data["usernames"] if u}
    return data


ME = load()


def is_me_name(name):
    return bool(name) and name.strip().lower() in ME["names_l"] | ME["usernames_l"]


def is_me_email(addr):
    return bool(addr) and addr.strip().lower() in ME["emails_l"]
