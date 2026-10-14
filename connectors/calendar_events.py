"""Apple Calendar events (includes every account synced into Calendar.app, e.g. iCloud)."""

from common import LIB, Writer, connect, from_apple, snapshot_sqlite

AVENUE = ("Local SQLite: ~/Library/Group Containers/group.com.apple.calendar/Calendar.sqlitedb "
          "(macOS 14+; older: ~/Library/Calendars). Needs Full Disk Access. Covers every account added "
          "in System Settings > Internet Accounts; Google Calendar only if that account is added there "
          "(otherwise use Google Takeout).")

SKIP_STORE_TYPES = {4, 6}  # 4 = subscribed (holidays), 6 = Reminders' scheduled items


def main():
    db = snapshot_sqlite(LIB / "Group Containers/group.com.apple.calendar/Calendar.sqlitedb", "calendar/Calendar.sqlitedb")
    con = connect(db)
    cals = {r["ROWID"]: dict(r) for r in con.execute(
        "select c.ROWID, c.title, s.type store_type, s.name store from Calendar c join Store s on s.ROWID = c.store_id")}
    people = {}
    for r in con.execute("""select p.owner_id, p.status, p.is_self, coalesce(i.display_name, p.email, i.address) who
                            from Participant p left join Identity i on i.ROWID = p.identity_id"""):
        if r["who"]:
            people.setdefault(r["owner_id"], []).append(r["who"].replace("mailto:", ""))
    locations = {r["ROWID"]: ", ".join(x for x in (r["title"], r["address"]) if x)
                 for r in con.execute("select ROWID, title, address from Location")}

    with Writer("calendar", AVENUE) as w:
        for r in con.execute("""select ROWID, UUID, summary, description, start_date, end_date, all_day, calendar_id,
                                       location_id, url, has_recurrences, status, creation_date, last_modified,
                                       conference_url
                                from CalendarItem where entity_type = 2"""):
            cal = cals.get(r["calendar_id"], {})
            if cal.get("store_type") in SKIP_STORE_TYPES or cal.get("title") == "Birthdays":
                continue
            loc = locations.get(r["location_id"])
            attendees = people.get(r["ROWID"], [])
            lines = [r["summary"] or ""]
            if loc:
                lines.append(f"Location: {loc}")
            if attendees:
                lines.append("Attendees: " + ", ".join(attendees))
            if r["description"]:
                lines.append(r["description"])
            w.add(id=r["UUID"] or r["ROWID"], kind="event", ts=from_apple(r["start_date"]),
                  ts_end=from_apple(r["end_date"]), title=r["summary"], text="\n".join(lines),
                  thread=cal.get("title"), thread_name=f"{cal.get('store')} / {cal.get('title')}",
                  participants=attendees or None, url=r["url"] or r["conference_url"],
                  meta={k: v for k, v in (("all_day", bool(r["all_day"]) or None), ("location", loc),
                                          ("recurring", bool(r["has_recurrences"]) or None),
                                          ("created", from_apple(r["creation_date"])),
                                          ("modified", from_apple(r["last_modified"]))) if v})


if __name__ == "__main__":
    main()
