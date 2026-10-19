"""Apple Health from the iPhone's healthdb_secure.sqlite (extracted from an encrypted local backup by
connectors/iphone_backup.py; unencrypted backups leave Health out).

Writes two sources:
- health: one record per local day (activity totals and averages), one per sleep session, and body
  measurements, for quick questions ("how much did I walk that week");
- health_samples: every sample as recorded (each step count, heart-rate reading, sleep stage, ...), so
  nothing is lost to the summaries: when in the day things happened, and types not identified yet.
 Each sample's timezone comes from its data_provenances row (tz_name: the device's zone
when it recorded), so days are local days without needing any other source.

Health stores data types as numbers. The ones mapped below were identified from their units, typical
values and start dates in this database (e.g. type 7 averages ~240 per sample from 2017 = steps); unmapped
types are left out of the daily summaries but kept in health_samples as "Health type <n>".

Cleaning, all counted in the manifest's notes:
- objects.type 2 rows are deleted samples (no value); apps that re-sync (Eight Sleep) leave thousands.
- exact duplicates (same type, source app, interval and value) are dropped: Eight Sleep writes each sleep
  stage and heart-rate reading twice per sync and re-syncs nights.
- physically impossible samples are dropped (more than CAPS per minute, intervals under a minute counted as
  one minute): e.g. a 2019 phone glitch logged 72,722 steps and 40 km in six minutes.

Older and newer databases (iOS 15-18 and the ones before) are read alike: a sample with no provenance row, or none that
matches, is kept (in UTC); one whose object has no type isn't a deleted one; tz_name, category_samples or the app names
in healthdb.sqlite may be missing. iOS 15 on, a series sample (a Watch's heart rate during a workout) can keep its
readings only in quantity_series_data, through quantity_sample_series.hfd_key, as iLEAPP's health_heart_rate and the
HealthDB project read them: each reading is then a sample of its own ("sample:<id>@<time>"). A sample with no start
time is counted (no_time), not guessed. A database with no samples table (made, never written to) leaves what was read
before as it is.
"""

import sqlite3
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from common import Writer, columns, connect, phone, phone_unencrypted, tables

DB = phone("HealthDomain", "Health/healthdb_secure.sqlite")
AVENUE = "iPhone encrypted local backup → connectors/iphone_backup.py → HealthDomain/Health/healthdb_secure.sqlite"
APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)

# data_type -> (field, how to combine within a day, multiplier to display units)
SUMMED = {7: ("steps", 1), 8: ("distance_km", 0.001), 12: ("flights", 1), 10: ("active_kcal", 1),
          9: ("resting_kcal", 1)}
AVERAGED = {5: ("heart_rate_bpm", 60), 61: ("breaths_per_min", 60), 173: ("headphone_db", 1),
            187: ("walking_speed_ms", 1), 188: ("step_length_m", 1), 182: ("double_support_pct", 100),
            194: ("walking_asymmetry_pct", 100)}
BODY = {2: ("height_m", 1), 3: ("weight_kg", 1)}
CAPS = {7: 250, 8: 400, 12: 20}  # steps, metres, flights per minute
SLEEP = 63
ACTIVITY = 76  # daily Activity rings (activity_caches)
SLEEP_STAGES = {0: "in_bed", 1: "asleep", 2: "awake", 3: "core", 4: "deep", 5: "rem"}
LABELS = {"steps": "{:,.0f} steps", "distance_km": "{:.1f} km walked/run", "flights": "{:.0f} flights climbed",
          "active_kcal": "{:.0f} active kcal", "resting_kcal": "{:.0f} resting kcal",
          "heart_rate_bpm": "heart rate {:.0f} bpm avg", "breaths_per_min": "{:.1f} breaths/min",
          "headphone_db": "headphone audio {:.0f} dB avg", "walking_speed_ms": "walking speed {:.2f} m/s",
          "step_length_m": "step length {:.2f} m", "double_support_pct": "double support {:.0f}%",
          "walking_asymmetry_pct": "walking asymmetry {:.1f}%"}


def local(t, tz):
    dt = APPLE_EPOCH + timedelta(seconds=t)
    try:
        return dt.astimezone(ZoneInfo(tz)) if tz else dt
    except Exception:
        return dt


# data_type -> (name, unit, multiplier) for health_samples text; anything else is "Health type <n>".
SAMPLE_NAMES = {7: ("Steps", "steps", 1), 8: ("Walking + running distance", "m", 1), 12: ("Flights climbed", "flights", 1),
                10: ("Active energy", "kcal", 1), 9: ("Resting energy", "kcal", 1), 5: ("Heart rate", "bpm", 60),
                61: ("Respiratory rate", "breaths/min", 60), 173: ("Headphone audio level", "dB", 1),
                187: ("Walking speed", "m/s", 1), 188: ("Step length", "m", 1), 182: ("Double support time", "%", 100),
                194: ("Walking asymmetry", "%", 100), 2: ("Height", "m", 1), 3: ("Weight", "kg", 1)}


def main():
    if not DB.exists():
        if phone_unencrypted():
            print("[health] this iPhone backup isn't encrypted, and Finder leaves Health out of those: turn on "
                  "\"Encrypt local backup\" in Finder and back up again to have it")
        else:
            print(f"[health] no {DB}; run connectors/iphone_backup.py first")
        return
    try:
        with closing(connect(DB)) as con:
            have = tables(con)
    except sqlite3.DatabaseError as e:
        print(f"[health] {DB.name} can't be read ({e}); what was read before stays")
        return
    if "samples" not in have:
        print(f"[health] no samples in {DB.name} (made, never written to?); what was read before stays")
        return
    summaries()
    samples()


def readings(con, order):
    """Every live sample as a dict (data_id, data_type, start_date, end_date, quantity, value, tz_name,
    origin_product_type, source_id, at): at is None for a sample, else the time of one reading of a series sample that
    has no value of its own. Joins are LEFT and a column this version lacks is null, so no sample is lost to them."""
    have = tables(con)
    cols = {t: columns(con, t) for t in ("objects", "data_provenances", "quantity_samples", "category_samples") if t in have}
    joins, pick = [], {}
    if "provenance" in cols.get("objects", ()):
        joins.append("left join objects o on o.data_id = s.data_id")
        if "data_provenances" in cols:
            joins.append("left join data_provenances p on p.ROWID = o.provenance")
            pick.update({c: f"p.{c}" for c in ("tz_name", "origin_product_type", "source_id") if c in cols["data_provenances"]})
    for table, alias, c in (("quantity_samples", "q", "quantity"), ("category_samples", "c", "value")):
        if c in cols.get(table, ()):
            joins.append(f"left join {table} {alias} on {alias}.data_id = s.data_id")
            pick[c] = f"{alias}.{c}"
    live = "where o.type is not 2" if "type" in cols.get("objects", ()) and "provenance" in cols["objects"] else ""  # 2: deleted
    want = ("quantity", "value", "tz_name", "origin_product_type", "source_id")
    picked = ", ".join(f"{pick.get(c, 'null')} {c}" for c in want)
    sql = f"select s.data_id, s.data_type, s.start_date, s.end_date, {picked} from samples s {' '.join(joins)} {live} order by s.{order}"
    series = series_readings(con, have)
    for r in con.execute(sql):
        r = dict(r)
        points = series.get(r["data_id"]) if r["quantity"] is None and r["value"] is None else None
        if not points:
            r["at"] = None
            yield r
            continue
        for at, v, duration in points:
            yield {**r, "start_date": at, "end_date": at + (duration or 0), "quantity": v, "at": at}


def series_readings(con, have):
    """data_id -> [(time, value, duration)] of each series sample with no quantity of its own (iOS 15 on)."""
    if not {"quantity_sample_series", "quantity_series_data"} <= have or \
            not {"data_id", "hfd_key"} <= columns(con, "quantity_sample_series") or \
            not {"series_identifier", "timestamp", "value"} <= columns(con, "quantity_series_data"):
        return {}
    own = "left join quantity_samples q on q.data_id = ss.data_id where q.quantity is null" if "quantity" in columns(
        con, "quantity_samples") else ""
    duration = "d.duration" if "duration" in columns(con, "quantity_series_data") else "0"
    out = {}
    for r in con.execute(f"""select ss.data_id, d.timestamp, d.value, {duration} from quantity_sample_series ss
                              join quantity_series_data d on d.series_identifier = ss.hfd_key {own}
                              order by ss.data_id, d.timestamp"""):
        if r[1] is not None and r[2] is not None:
            out.setdefault(r[0], []).append((r[1], r[2], r[3]))
    return out


def timed(r):
    """(start, end) in Apple seconds, an end missing taken as the start; None if there's no start, or one out of range."""
    s, e = r["start_date"], r["end_date"]
    if not isinstance(s, (int, float)):
        return None
    e = e if isinstance(e, (int, float)) else s
    try:
        APPLE_EPOCH + timedelta(seconds=max(s, e))
        APPLE_EPOCH + timedelta(seconds=min(s, e))
    except OverflowError:
        return None
    return s, e


def samples():
    with closing(connect(DB)) as con:
        _samples(con)


def _samples(con):
    """Every live sample: deleted rows (no value), exact duplicates and physically impossible readings are the
    only ones left out, each counted in the manifest's notes."""
    apps = {}
    other = DB.with_name("healthdb.sqlite")
    if other.exists():
        try:
            with closing(connect(other)) as names:
                if "sources" in tables(names) and "name" in columns(names, "sources"):
                    apps = {r[0]: r[1] for r in names.execute("select ROWID, name from sources")}
        except sqlite3.DatabaseError:
            pass  # app names are a nicety: the samples are read without them
    rows = readings(con, "start_date")
    # Type 76 is the daily Activity rings summary; its numbers live in activity_caches, not the sample tables.
    # Older Health databases have no such table, or fewer of its columns.
    has_rings = con.execute("select 1 from sqlite_master where type = 'table' and name = 'activity_caches'").fetchone()
    rings = {r["data_id"]: dict(r) for r in con.execute("select * from activity_caches")} if has_rings else {}
    seen, notes = set(), {"duplicates": 0, "implausible": 0, "no_value": 0}
    with Writer("health_samples", AVENUE, accumulate=False) as w:
        w.notes = notes
        for r in rows:
            t, q, v = r["data_type"], r["quantity"], r["value"]
            ring = rings.get(r["data_id"]) if t == ACTIVITY else None
            if q is None and v is None and ring is None:
                notes["no_value"] += 1
                continue
            when = timed(r)
            if not when:
                notes["no_time"] = notes.get("no_time", 0) + 1
                continue
            r["start_date"], r["end_date"] = when
            key = (t, r["source_id"], r["start_date"], r["end_date"], q, v)
            if key in seen:
                notes["duplicates"] += 1
                continue
            seen.add(key)
            if t in CAPS and q is not None and q > CAPS[t] * max((r["end_date"] - r["start_date"]) / 60, 1):
                notes["implausible"] += 1
                continue
            name, unit, mult = SAMPLE_NAMES.get(t, (f"Health type {t}", "", 1))
            extra = {}
            if ring is not None:
                extra = {k: ring.get(k) for k in ("energy_burned", "energy_burned_goal", "move_minutes", "brisk_minutes",
                                                  "brisk_minutes_goal", "active_hours", "active_hours_goal", "steps",
                                                  "walk_distance", "flights") if ring.get(k) is not None}
                name = "Activity rings"
                shown = (f"move {ring.get('energy_burned') or 0:.0f}/{ring.get('energy_burned_goal') or 0:.0f} kcal"
                         + (f", exercise {ring['brisk_minutes']:.0f} min" if ring.get("brisk_minutes") is not None else "")
                         + (f", stand {ring['active_hours']:.0f} h" if ring.get("active_hours") is not None else "")
                         + (f", {ring['steps']:.0f} steps" if ring.get("steps") else ""))
            elif t == SLEEP:
                name, shown = "Sleep", SLEEP_STAGES.get(v, f"stage {v}")
            elif q is not None:
                shown = f"{q * mult:.4g} {unit}".strip()
            else:
                shown = f"value {v}"
            a, b = local(r["start_date"], r["tz_name"]), local(r["end_date"], r["tz_name"])
            app = apps.get(r["source_id"])
            span = f"{a:%Y-%m-%d %H:%M}" + (f"–{b:%H:%M}" if r["end_date"] != r["start_date"] else "")
            w.add(id=f"sample:{r['data_id']}" + (f"@{round(r['at'], 3)}" if r["at"] is not None else ""), kind="health_sample",
                  ts=(APPLE_EPOCH + timedelta(seconds=r["start_date"])).isoformat(),
                  ts_end=(APPLE_EPOCH + timedelta(seconds=r["end_date"])).isoformat(), author="me", is_me=True,
                  title=name, text=f"{name}: {shown}, {span} ({r['tz_name'] or 'UTC'})" + (f", {app}" if app else ""),
                  meta={k: x for k, x in (("type", t), ("value", q * mult if q is not None else v), ("unit", unit or None),
                                          ("app", app), ("device", r["origin_product_type"]), ("tz", r["tz_name"])) if x is not None}
                  | extra)


def summaries():
    with closing(connect(DB)) as con:
        _summaries(con)


def _summaries(con):
    rows = readings(con, "data_id")
    sums = defaultdict(lambda: defaultdict(float))     # (day, field, device) -> total
    avgs = defaultdict(lambda: [0.0, 0, None, None])   # (day, field) -> [sum, n, min, max]
    tzs, sleep, body, skipped, seen = {}, [], [], defaultdict(int), set()
    dropped = {"duplicates": 0, "implausible": 0}
    for r in rows:
        t, tz = r["data_type"], r["tz_name"]
        when = timed(r)
        if not when:
            dropped["no_time"] = dropped.get("no_time", 0) + 1
            continue
        r["start_date"], r["end_date"] = when
        key = (t, r["source_id"], r["start_date"], r["end_date"], r["quantity"], r["value"])
        if key in seen:
            dropped["duplicates"] += 1
            continue
        seen.add(key)
        if t in CAPS and r["quantity"] is not None and \
                r["quantity"] > CAPS[t] * max((r["end_date"] - r["start_date"]) / 60, 1):
            dropped["implausible"] += 1
            continue
        start = local(r["start_date"], tz)
        day = start.date().isoformat()
        if t in SUMMED and r["quantity"] is not None:
            field, mult = SUMMED[t]
            sums[(day, field)][r["origin_product_type"]] += r["quantity"] * mult
            tzs.setdefault(day, tz)
        elif t in AVERAGED and r["quantity"] is not None:
            field, mult = AVERAGED[t]
            v = r["quantity"] * mult
            a = avgs[(day, field)]
            a[0] += v
            a[1] += 1
            a[2] = v if a[2] is None else min(a[2], v)
            a[3] = v if a[3] is None else max(a[3], v)
            tzs.setdefault(day, tz)
        elif t == SLEEP and r["value"] is not None:
            sleep.append((r["start_date"], r["end_date"], r["value"], tz, r["data_id"]))
        elif t in BODY and r["quantity"] is not None:
            body.append((r, BODY[t]))
        else:
            skipped[t] += 1

    days = defaultdict(dict)
    for (day, field), per_device in sums.items():
        days[day][field] = max(per_device.values())  # two phones counting the same steps: keep one
    for (day, field), (total, n, lo, hi) in avgs.items():
        days[day][field] = total / n
        if field == "heart_rate_bpm":
            days[day]["heart_rate_min"], days[day]["heart_rate_max"] = lo, hi

    # The phone's database is the full history (synced across phones), so rebuild rather than accumulate.
    with Writer("health", AVENUE, accumulate=False) as w:
        w.notes = {**dropped, "skipped_types": {str(k): v for k, v in sorted(skipped.items())}}
        for day in sorted(days):
            d = days[day]
            parts = [LABELS[f].format(d[f]) for f in LABELS if f in d]
            if "heart_rate_min" in d:
                parts[parts.index(LABELS["heart_rate_bpm"].format(d["heart_rate_bpm"]))] += \
                    f" ({d['heart_rate_min']:.0f}–{d['heart_rate_max']:.0f})"
            w.add(id=f"day:{day}", kind="health_day", ts=f"{day}T00:00:00", author="me", is_me=True,
                  title=f"Health {day}", text=f"Health {day} ({tzs.get(day) or 'UTC'}): " + ", ".join(parts),
                  meta={**{k: round(v, 3) for k, v in d.items()}, "tz": tzs.get(day)})

        # Sleep: samples within 2 hours of each other form one session.
        sleep.sort()
        sessions, cur = [], None
        for s, e, v, tz, did in sleep:
            if cur and s - cur["end"] <= 7200:
                cur["end"] = max(cur["end"], e)
            else:
                cur = {"start": s, "end": e, "tz": tz, "id": did, "stages": defaultdict(float)}
                sessions.append(cur)
            cur["stages"][SLEEP_STAGES.get(v, f"value_{v}")] += (e - s) / 60
        for x in sessions:
            st = x["stages"]
            asleep = sum(st[k] for k in ("asleep", "core", "deep", "rem") if k in st)
            a, b = local(x["start"], x["tz"]), local(x["end"], x["tz"])
            detail = ", ".join(f"{k} {v / 60:.1f} h" for k, v in st.items() if k not in ("asleep", "in_bed") and v)
            # Stage data needs a sleep tracker; the iPhone's Bedtime feature (2017-19) only logged time in bed.
            head = f"Slept {asleep / 60:.1f} h" if asleep else f"In bed {st.get('in_bed', 0) / 60:.1f} h"
            w.add(id=f"sleep:{x['id']}", kind="sleep", ts=(APPLE_EPOCH + timedelta(seconds=x["start"])).isoformat(),
                  ts_end=(APPLE_EPOCH + timedelta(seconds=x["end"])).isoformat(), author="me", is_me=True,
                  title=f"Sleep {b.date().isoformat()}",
                  text=f"{head}, {a:%a %b %d %H:%M} to {b:%H:%M} ({x['tz'] or 'UTC'})"
                       + (f"; {detail}" if detail else ""),
                  meta={"asleep_min": round(asleep), **{f"{k}_min": round(v) for k, v in st.items()}, "tz": x["tz"]})

        for r, (field, mult) in body:
            when = local(r["start_date"], r["tz_name"])
            w.add(id=f"body:{r['data_id']}" + (f"@{round(r['at'], 3)}" if r["at"] is not None else ""), kind="measurement", ts=(APPLE_EPOCH + timedelta(seconds=r["start_date"])).isoformat(),
                  author="me", is_me=True, title=field.replace("_", " "),
                  text=f"{field.replace('_', ' ')}: {r['quantity'] * mult:g} ({when.date().isoformat()})",
                  meta={field: r["quantity"] * mult})


if __name__ == "__main__":
    main()
