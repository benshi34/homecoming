"""Apple Calendar events (includes every account synced into Calendar.app, e.g. iCloud)."""

import datetime as dt

from common import LIB, UTC, Writer, columns, connect, from_apple, select, snapshot_sqlite, tables

AVENUE = ("Local SQLite: ~/Library/Group Containers/group.com.apple.calendar/Calendar.sqlitedb "
          "(macOS 14+; older: ~/Library/Calendars). Needs Full Disk Access. Covers every account added "
          "in System Settings > Internet Accounts; Google Calendar only if that account is added there "
          "(otherwise use Google Takeout).")

SKIP_STORE_TYPES = {4, 6}  # 4 = subscribed (holidays), 6 = Reminders' scheduled items
# Participant.status, as EventKit numbers a reply (unconfirmed beyond these on one Mac: 0, 1, 2, 3, 7).
REPLIES = {1: "not replied", 2: "accepted", 3: "declined", 4: "maybe", 5: "delegated", 7: "replying"}
# Recurrence.frequency (1 daily .. 4 yearly; this Mac had weekly and yearly ones).
EVERY = {1: ("day", "days"), 2: ("week", "weeks"), 3: ("month", "months"), 4: ("year", "years")}


def repeats(r):
    one, many = EVERY.get(r["frequency"], (None, None))
    if not one:
        return None
    n = r["interval"] or 1
    return f"every {one}" if n == 1 else f"every {n} {many}"


def when(v, tz):
    """A time as Calendar keeps it: seconds since 2001 in UTC, but a floating one (start_tz "_float": no zone, as an
    event made "floating" or imported without one) is the wall clock, read as this Mac shows it, as imports.py reads a
    floating .ics time. An all-day event's floating midnight stays as it is: a date (stream.py's whole_day)."""
    if tz != "_float" or v in (None, 0, ""):
        return from_apple(v)
    try:
        return (dt.datetime(2001, 1, 1) + dt.timedelta(seconds=float(v))).astimezone(UTC).isoformat().replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return from_apple(v)


def main():
    db = snapshot_sqlite(LIB / "Group Containers/group.com.apple.calendar/Calendar.sqlitedb", "calendar/Calendar.sqlitedb")
    with Writer("calendar", AVENUE) as w:
        if not db.exists():  # macOS 13 and before keep Calendar Cache instead (not read here)
            return
        con = connect(db)
        have = tables(con)
        if not {"CalendarItem", "Calendar"} <= have:  # made, never written to
            w.notes["empty"] = 1
            return
        read(con, have, w)


def read(con, have, w):
    store = "Store" in have
    cals = {r["ROWID"]: dict(r) for r in con.execute(
        "select c.ROWID, c.title, s.type store_type, s.name store from Calendar c left join Store s on s.ROWID = c.store_id" if store
        else "select ROWID, title, null store_type, null store from Calendar")}
    people, said, replies, who_of = {}, {}, {}, {}  # said: each attendee with their reply, for the text
    # Who each attendee is: their Identity since iOS 13 / macOS 14, before that only the participant's email.
    pcols = columns(con, "Participant") if "Participant" in have else set()
    pick = lambda c: f"p.{c}" if c in pcols else f"null {c}"  # noqa: E731
    email = "p.email" if "email" in pcols else "null"
    identity = "Identity" in have and "identity_id" in pcols
    who = f"coalesce(i.display_name, {email}, i.address)" if identity else email
    for r in con.execute(f"""select p.ROWID, {pick("owner_id")}, {pick("status")}, {pick("entity_type")}, {who} who
                             from Participant p {"left join Identity i on i.ROWID = p.identity_id" if identity else ""}"""
                         if pcols else "select 1 where 0"):
        if r["who"]:
            who = r["who"].replace("mailto:", "")
            who_of[r["ROWID"]] = who
            replies[r["ROWID"]] = REPLIES.get(r["status"])
            if r["entity_type"] != 8:  # 8: the organizer, said apart
                people.setdefault(r["owner_id"], []).append(who)
                reply = REPLIES.get(r["status"])
                said.setdefault(r["owner_id"], []).append(f"{who} ({reply})" if reply in ("accepted", "declined", "maybe") else who)
    rules = {r["owner_id"]: repeats(r) for r in con.execute(
        select(con, "Recurrence", ("owner_id", "frequency", "interval")) if "Recurrence" in have else "select 1 where 0")}
    locations = {r["ROWID"]: ", ".join(x for x in (r["title"], r["address"]) if x) for r in con.execute(
        select(con, "Location", ("ROWID", "title", "address")) if "Location" in have else "select 1 where 0")}

    cols = columns(con, "CalendarItem")
    # A repeating event's occurrence moved on its own is a row of its own (orig_item_id: the series), which can have the
    # series' UUID: the series' rows first, so each keeps the id it has always had.
    uuid_of = {r["ROWID"]: r["UUID"] for r in con.execute("select ROWID, UUID from CalendarItem")}
    query = select(con, "CalendarItem", (
        "ROWID", "UUID", "summary", "description", "start_date", "start_tz", "end_date", "end_tz", "all_day", "calendar_id",
        "location_id", "url", "has_recurrences", "status", "creation_date", "last_modified", "conference_url", "organizer_id",
        "self_attendee_id", "orig_item_id", "orig_date", "entity_type"))
    for r in con.execute(f"""{query} where {"entity_type = 2" if "entity_type" in cols else "1"}
                             order by coalesce({"orig_item_id" if "orig_item_id" in cols else "null"}, 0) > 0, ROWID"""):
        cal = cals.get(r["calendar_id"], {})
        if cal.get("store_type") in SKIP_STORE_TYPES or cal.get("title") == "Birthdays":
            continue
        loc = locations.get(r["location_id"])
        attendees = people.get(r["ROWID"], [])
        lines = [r["summary"] or ""]
        if loc:
            lines.append(f"Location: {loc}")
        organizer = who_of.get(r["organizer_id"]) if r["organizer_id"] else None
        mine = replies.get(r["self_attendee_id"]) if r["self_attendee_id"] else None
        rule = rules.get(r["ROWID"]) if r["has_recurrences"] else None
        if organizer:
            lines.append(f"Organized by {organizer}")
        if attendees:
            lines.append("Attendees: " + ", ".join(said.get(r["ROWID"], attendees)))
        if mine:
            lines.append(f"You {mine}" if mine in ("accepted", "declined") else f"Your reply: {mine}")
        if rule:
            lines.append(f"Repeats {rule}")
        if r["description"]:
            lines.append(r["description"])
        rid = r["UUID"] or r["ROWID"]
        series = uuid_of.get(r["orig_item_id"]) if r["orig_item_id"] else None
        if w.has(rid):  # an occurrence with its series' UUID
            rid = f"{rid}:{from_apple(r['orig_date']) or r['ROWID']}"
        floating = r["start_tz"] == "_float" and not r["all_day"]
        w.add(id=rid, kind="event", ts=when(r["start_date"], None if r["all_day"] else r["start_tz"]),
              ts_end=when(r["end_date"], None if r["all_day"] else r["end_tz"] or r["start_tz"]), title=r["summary"],
              text="\n".join(lines), thread=cal.get("title"),
              thread_name=" / ".join(x for x in (cal.get("store"), cal.get("title")) if x) or None,
              participants=attendees or None, url=r["url"] or r["conference_url"],
              meta={k: v for k, v in (("all_day", bool(r["all_day"]) or None), ("floating", floating or None), ("location", loc),
                                      ("recurring", bool(r["has_recurrences"]) or None), ("repeats", rule),
                                      ("occurrence_of", series), ("organizer", organizer), ("my_reply", mine),
                                      ("created", from_apple(r["creation_date"])),
                                      ("modified", from_apple(r["last_modified"]))) if v})


if __name__ == "__main__":
    main()
