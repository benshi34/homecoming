"""Apple Maps on this Mac: what you searched for, places you looked up and got directions to, your favorites, your
guides and the places in them, places Maps says you visited, places you rated and places it asked you to rate. Maps
syncs these through iCloud, so the Mac's copy is also the iPhone's.

Most place details are plain columns. Those that aren't (a place you looked up, rated or got directions to) are in
Apple's own encoding; only the place's name and address lines are read from it, where they are plainly there."""

import json

from apple_notes import _fields
from common import LIB, NORM, Writer, columns, connect, from_apple, snapshot_sqlite

DB = LIB / "Containers/com.apple.Maps/Data/Maps/MapsSync_0.0.1"
AVENUE = ("Local SQLite (Core Data, synced by iCloud): ~/Library/Containers/com.apple.Maps/Data/Maps/MapsSync_0.0.1. "
          "ZHISTORYITEM = recents, one entity per kind (Z_PRIMARYKEY names them: HistorySearchItem ZQUERY / "
          "ZLOCATIONDISPLAY, HistoryPlaceItem, HistoryDirectionsItem...); ZFAVORITEITEM = favorites (ZMAPITEMNAME, "
          "ZMAPITEMADDRESS, ZCUSTOMNAME; one with no name, address or place is an empty slot, counted); ZCOLLECTION + "
          "Z_6PLACES + ZCOLLECTIONITEM = guides and their places (with your note); ZVISIT -> ZVISITEDLOCATION = visited "
          "places; ZREVIEWEDPLACE = places you rated (ZRATING, ZHASUSERREVIEWED, photos), or that Maps asked you to rate "
          "(none of those, ZLASTSUGGESTEDREVIEWDATE set). Place blobs (ZMAPITEMSTORAGE, waypoints) are protobuf: the name "
          "at place -> component (4) -> value (8) -> entity (1) -> 10 -> 3, as iLEAPP's appleMapsSearchHistory reads it, "
          "and address lines at 101 -> 2 -> 11, as its mapsSync does. Recents the iPhone backup's phone_mapssync already "
          "has (same time and search) are left to it. Tables checked on macOS 26 and read there (a guide, places to rate "
          "with their names, empty favorites); recents, guide places, visits and real ratings are written against the "
          "schema.")


def _sub(buf, field):
    return next((v for f, wt, v in _fields(buf) if f == field and wt == 2), None)


def _text(b):
    try:
        s = b.decode("utf-8").strip()
    except (AttributeError, UnicodeDecodeError):
        return None
    return s if s and s.isprintable() else None


def place_details(blob, depth=0, out=None):
    """(names, address lines) found in a place blob, in order. A field read as a message that isn't one is skipped."""
    out = ([], []) if out is None else out
    if not blob or depth > 7:
        return out
    try:
        fields = list(_fields(blob))
    except (IndexError, ValueError):
        return out
    for f, wt, v in fields:
        if wt != 2 or not v:
            continue
        try:
            if f == 4:  # a component of a place: its value's entity's name
                entity = _sub(v, 8) and _sub(_sub(v, 8), 1)
                name = entity and _sub(entity, 10) and _text(_sub(_sub(entity, 10), 3))
                if name and name not in out[0]:
                    out[0].append(name)
            if f == 101:
                address = _sub(v, 2)
                lines = [_text(x) for g, wt2, x in _fields(address) if g == 11 and wt2 == 2] if address else []
                out[1].extend(x for x in lines if x and x not in out[1])
        except (IndexError, ValueError, TypeError):
            pass
        place_details(v, depth + 1, out)
    return out


def phone_recents():
    """(time, search) of the recents the iPhone backup's Maps brought in through iLEAPP (phone_mapssync)."""
    seen = set()
    try:
        with (NORM / "phone_mapssync.jsonl").open(encoding="utf-8", errors="replace") as f:
            for line in f:
                try:  # one line cut off (a crash mid-write) mustn't hide the rest, or they'd be counted twice
                    fields = (json.loads(line).get("meta") or {}).get("fields") or {}
                    if fields.get("Timestamp"):
                        seen.add((str(fields["Timestamp"])[:19].replace(" ", "T"), str(fields.get("Location Search") or "").strip()))
                except (ValueError, AttributeError):
                    continue
    except OSError:
        pass
    return seen


def clean(meta):
    return {k: v for k, v in meta.items() if v not in (None, "")}


def place(name, address=None, category=None):
    return ", ".join(x for x in (name, address) if x) + (f" ({category})" if category else "")


def main():
    with Writer("apple_maps", AVENUE) as w:
        if not DB.exists():
            return
        con = connect(snapshot_sqlite(DB, "apple_maps/MapsSync_0.0.1"))
        tables = {r[0] for r in con.execute("select name from sqlite_master where type = 'table'")}
        if "Z_PRIMARYKEY" not in tables:  # made, never written to
            w.notes["empty"] = 1
            return
        ents = {r["Z_ENT"]: r["Z_NAME"] for r in con.execute("select Z_ENT, Z_NAME from Z_PRIMARYKEY")}
        has = lambda t, *cs: t in tables and set(cs) <= columns(con, t)  # noqa: E731
        sel = lambda t, cs: ", ".join(c if c in columns(con, t) else f"null {c}" for c in cs)  # noqa: E731

        if has("ZHISTORYITEM", "ZCREATETIME"):
            on_phone = phone_recents()
            mixin = {}
            if has("ZMIXINMAPITEM", "ZMAPITEMSTORAGE"):
                mixin = {r["Z_PK"]: r["ZMAPITEMSTORAGE"] for r in con.execute("select Z_PK, ZMAPITEMSTORAGE from ZMIXINMAPITEM")}
            cols = ("Z_PK", "Z_ENT", "ZCREATETIME", "ZMODIFICATIONTIME", "ZQUERY", "ZLOCATIONDISPLAY", "ZLATITUDE",
                    "ZLONGITUDE", "ZMAPITEM", "ZMAPITEMSTORAGE", "ZSTARTWAYPOINT", "ZENDWAYPOINT", "ZROUTEREQUESTSTORAGE",
                    "ZCUSTOMNAME", "ZNAVIGATIONINTERRUPTED")
            for r in con.execute(f"select {sel('ZHISTORYITEM', cols)} from ZHISTORYITEM"):
                entity, ts = ents.get(r["Z_ENT"], ""), from_apple(r["ZCREATETIME"])
                query = (r["ZQUERY"] or "").strip()
                if ts and (ts[:19], query) in on_phone:
                    w.skip(f"recent:{r['Z_PK']}")
                    w.notes["in_the_iphone_backup"] = w.notes.get("in_the_iphone_backup", 0) + 1
                    continue
                coords = {"lat": r["ZLATITUDE"], "lon": r["ZLONGITUDE"]} if r["ZLATITUDE"] or r["ZLONGITUDE"] else {}
                meta = {"entity": entity, **coords}
                if "Directions" in entity or entity in ("HistoryMultiPointRoute", "HistoryTransitItem"):
                    start, end = (place_details(r[c])[0] for c in ("ZSTARTWAYPOINT", "ZENDWAYPOINT"))
                    via = place_details(r["ZROUTEREQUESTSTORAGE"])[0] if not end else []
                    to = (end or via[-1:] or [None])[0]
                    frm = (start or (via[:1] if len(via) > 1 else []) or [None])[0]
                    title = f"Directions to {to}" if to else "Directions"
                    w.add(id=f"recent:{r['Z_PK']}", kind="directions", ts=ts, author="me", is_me=True, title=title,
                          text=title + (f" from {frm}" if frm else ""),
                          meta=clean({**meta, "from": frm, "to": to, "interrupted": bool(r["ZNAVIGATIONINTERRUPTED"]) or None}))
                elif query or "Search" in entity:
                    shown = (r["ZLOCATIONDISPLAY"] or "").strip()
                    w.add(id=f"recent:{r['Z_PK']}", kind="search", ts=ts, author="me", is_me=True, title=query or shown,
                          text=f"Searched Maps for {query or shown}" + (f" near {shown}" if shown and query else ""),
                          meta=clean({**meta, "near": shown or None}))
                else:
                    names, lines = place_details(r["ZMAPITEMSTORAGE"] or mixin.get(r["ZMAPITEM"]))
                    name = r["ZCUSTOMNAME"] or (names[0] if names else None)
                    what = place(name, ", ".join(lines) or None) or "a place"
                    w.add(id=f"recent:{r['Z_PK']}", kind="place_lookup", ts=ts, author="me", is_me=True,
                          title=name or what, text=f"Looked at {what} in Maps",
                          meta=clean({**meta, "place": name, "address": ", ".join(lines) or None}))

        if has("ZFAVORITEITEM", "ZCREATETIME"):
            cols = ("Z_PK", "ZCREATETIME", "ZCUSTOMNAME", "ZMAPITEMNAME", "ZMAPITEMADDRESS", "ZMAPITEMCATEGORY", "ZTYPE",
                    "ZLATITUDE", "ZLONGITUDE", "ZHIDDEN")
            for r in con.execute(f"select {sel('ZFAVORITEITEM', cols)} from ZFAVORITEITEM"):
                label = r["ZCUSTOMNAME"]
                name = r["ZMAPITEMNAME"] or label
                if not (name or r["ZMAPITEMADDRESS"] or r["ZLATITUDE"] or r["ZLONGITUDE"]):  # a slot never filled in
                    w.notes["empty_favorites"] = w.notes.get("empty_favorites", 0) + 1
                    continue
                what = place(name, r["ZMAPITEMADDRESS"], r["ZMAPITEMCATEGORY"]) or "a place"
                w.add(id=f"favorite:{r['Z_PK']}", kind="place", ts=from_apple(r["ZCREATETIME"]), author="me", is_me=True,
                      title=label or name, thread="favorites", thread_name="Favorites",
                      text=f"Favorite in Maps: {what}" + (f" (you call it {label})" if label and label != name else ""),
                      meta={k: v for k, v in (("saved_as", "favorite"), ("label", label), ("place", r["ZMAPITEMNAME"]),
                                              ("address", r["ZMAPITEMADDRESS"]), ("category", r["ZMAPITEMCATEGORY"]),
                                              ("lat", r["ZLATITUDE"]), ("lon", r["ZLONGITUDE"]),
                                              ("type", r["ZTYPE"]), ("hidden", bool(r["ZHIDDEN"]) or None)) if v is not None})

        if has("ZCOLLECTION", "ZTITLE"):
            guides = {r["Z_PK"]: r for r in con.execute(
                f"select {sel('ZCOLLECTION', ('Z_PK', 'ZTITLE', 'ZCOLLECTIONDESCRIPTION', 'ZCREATETIME', 'ZPLACESCOUNT'))} from ZCOLLECTION")}
            for g in guides.values():
                w.add(id=f"guide:{g['Z_PK']}", kind="guide", ts=from_apple(g["ZCREATETIME"]), author="me", is_me=True,
                      title=g["ZTITLE"], thread=f"guide:{g['Z_PK']}", thread_name=g["ZTITLE"],
                      text="\n".join(x for x in (f"Your guide in Maps: {g['ZTITLE']}", g["ZCOLLECTIONDESCRIPTION"]) if x),
                      meta={"places": g["ZPLACESCOUNT"]})
            # Which guide each place is in: the join table is named after the two entities' numbers (Z_6PLACES).
            join = next((t for t in tables if t.startswith("Z_") and t.endswith("PLACES")), None)
            in_guide = {}
            if join:
                gcol, pcol = (next((c for c in columns(con, join) if c.endswith(x)), None) for x in ("COLLECTIONS", "PLACES"))
                if gcol and pcol:
                    for r in con.execute(f"select {gcol} g, {pcol} p from {join}"):
                        in_guide.setdefault(r["p"], []).append(r["g"])
            if has("ZCOLLECTIONITEM", "ZCREATETIME"):
                cols = ("Z_PK", "ZCREATETIME", "ZCUSTOMNAME", "ZMAPITEMNAME", "ZMAPITEMADDRESS", "ZMAPITEMCATEGORY",
                        "ZPLACEITEMNOTE", "ZLATITUDE", "ZLONGITUDE")
                for r in con.execute(f"select {sel('ZCOLLECTIONITEM', cols)} from ZCOLLECTIONITEM"):
                    g = next((guides[x] for x in in_guide.get(r["Z_PK"], []) if x in guides), None)
                    name = r["ZCUSTOMNAME"] or r["ZMAPITEMNAME"]
                    what = place(name, r["ZMAPITEMADDRESS"], r["ZMAPITEMCATEGORY"]) or "a place"
                    w.add(id=f"guide_place:{r['Z_PK']}", kind="place", ts=from_apple(r["ZCREATETIME"]), author="me",
                          is_me=True, title=name, thread=f"guide:{g['Z_PK']}" if g else None, thread_name=g["ZTITLE"] if g else None,
                          text="\n".join(x for x in (f"Saved in Maps{' to ' + g['ZTITLE'] if g else ''}: {what}",
                                                     r["ZPLACEITEMNOTE"] and f"Your note: {r['ZPLACEITEMNOTE']}") if x),
                          meta={k: v for k, v in (("saved_as", "guide"), ("guide", g["ZTITLE"] if g else None), ("place", name),
                                                  ("address", r["ZMAPITEMADDRESS"]), ("category", r["ZMAPITEMCATEGORY"]),
                                                  ("note", r["ZPLACEITEMNOTE"]), ("lat", r["ZLATITUDE"]),
                                                  ("lon", r["ZLONGITUDE"])) if v is not None})

        if has("ZVISIT", "ZSTARTDATE") and has("ZVISITEDLOCATION", "ZMAPITEMNAME"):
            cols = ("ZMAPITEMNAME", "ZMAPITEMADDRESS", "ZMAPITEMCITY", "ZMAPITEMCATEGORY", "ZLATITUDE", "ZLONGITUDE")
            # Each column only if this version of Maps has it, as above: one missing mustn't lose every visit.
            vis, loc = columns(con, "ZVISIT"), columns(con, "ZVISITEDLOCATION")
            pick = lambda a, have, cs: ", ".join(f"{a}.{c}" if c in have else f"null {c}" for c in cs)  # noqa: E731
            on = "l.Z_PK = v.ZLOCATION" if "ZLOCATION" in vis and "Z_PK" in loc else "0"
            for r in con.execute(f"""select {pick('v', vis, ('Z_PK', 'ZSTARTDATE', 'ZHIDDEN'))}, {pick('l', loc, cols)}
                                     from ZVISIT v left join ZVISITEDLOCATION l on {on}"""):
                name = r["ZMAPITEMNAME"]
                what = place(name, r["ZMAPITEMADDRESS"] or r["ZMAPITEMCITY"], r["ZMAPITEMCATEGORY"]) or "a place"
                w.add(id=f"visit:{r['Z_PK']}", kind="place_visit", ts=from_apple(r["ZSTARTDATE"]), author="me", is_me=True,
                      title=name, text=f"Visited {what}",
                      meta={k: v for k, v in (("place", name), ("address", r["ZMAPITEMADDRESS"]), ("city", r["ZMAPITEMCITY"]),
                                              ("category", r["ZMAPITEMCATEGORY"]), ("lat", r["ZLATITUDE"]),
                                              ("lon", r["ZLONGITUDE"]), ("hidden", bool(r["ZHIDDEN"]) or None)) if v is not None})

        if has("ZREVIEWEDPLACE", "ZRATING"):
            cols = ("Z_PK", "ZCREATETIME", "ZMODIFICATIONTIME", "ZRATING", "ZHASUSERREVIEWED", "ZUPLOADEDPHOTOSCOUNT",
                    "ZLASTSUGGESTEDREVIEWDATE", "ZLATITUDE", "ZLONGITUDE", "ZMAPITEMSTORAGE")
            for r in con.execute(f"select {sel('ZREVIEWEDPLACE', cols)} from ZREVIEWEDPLACE"):
                names, lines = place_details(r["ZMAPITEMSTORAGE"])
                name = names[0] if names else None
                what = place(name, ", ".join(lines) or None) or "a place"
                photos = r["ZUPLOADEDPHOTOSCOUNT"] or 0
                # A row with no rating, review or photo is a place Maps asked you to rate (after you'd been, it thought).
                rated = bool(r["ZRATING"] or r["ZHASUSERREVIEWED"] or photos)
                asked = from_apple(r["ZLASTSUGGESTEDREVIEWDATE"])
                w.add(id=f"rating:{r['Z_PK']}", kind="review" if rated else "rating_asked",
                      ts=from_apple(r["ZCREATETIME"]) if rated else asked or from_apple(r["ZCREATETIME"]),
                      ts_end=from_apple(r["ZMODIFICATIONTIME"]) if rated else None, author="me" if rated else "Maps",
                      is_me=rated, title=name or what,
                      text=(f"Rated {what} in Maps" + (f", and added {photos} photo{'s' * (photos > 1)}" if photos else "")) if rated
                      else f"Maps asked you to rate {what}",
                      meta={k: v for k, v in (("place", name), ("address", ", ".join(lines) or None),
                                              ("rating", r["ZRATING"] if rated else None), ("photos", photos or None),
                                              ("asked", asked), ("lat", r["ZLATITUDE"]), ("lon", r["ZLONGITUDE"])) if v is not None})


if __name__ == "__main__":
    main()
