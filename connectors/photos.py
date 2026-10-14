"""Photos library metadata: when and where each photo/video was taken, who is in it (named
faces), and Apple's on-device labels (scenes, places, businesses, events, text in the image).
Each record links the best image of it already on disk in meta.files (no copies): the library's own previews
(resources/derivatives/<X>/<UUID>_1_105_c.jpeg ~1-2k px, else masters/<X>/<UUID>_4_5005_c.jpeg thumbnails, else
the original when it's downloaded), so a model can look at the photo; with iCloud "Optimize Mac Storage" most
originals live only in iCloud."""

import collections
import uuid

from common import HOME, Writer, connect, from_apple

LIBRARY = HOME / "Pictures/Photos Library.photoslibrary"
DB = LIBRARY / "database"
AVENUE = ("Local SQLite, read in place (Photos.sqlite is multi-GB, so no snapshot): "
          "~/Pictures/Photos Library.photoslibrary/database/Photos.sqlite for dates, GPS, named faces "
          "(ZDETECTEDFACE -> ZPERSON), moments, captions, albums; database/search/psi.sqlite for Apple's "
          "on-device labels (groups.category codes: 1-14 place hierarchy, 1500s scenes, 1700 businesses, "
          "1203 OCR text, 1600/1800 events and concerts, 2300 camera model; ga maps group -> asset; asset "
          "uuid_0/uuid_1 are the UUID's two little-endian int64 halves). Needs Full Disk Access. "
          "Hidden and trashed items are skipped.")

PLACE_ORDER = (1700, 1520, 6, 5, 10, 12, 14)
BUCKETS = {"scenes": {1500, 1510}, "events": {1600, 1601, 1611, 1800, 1402}, "text": {1203},
           "app": {2200}, "camera": {2300}, "type": {1903, 1905, 1907, 1908, 1909, 1910, 1912, 1914, 1915, 1919, 2800}}


def index_labels():
    """asset UUID -> {bucket: [strings]} from the Photos search index."""
    con = connect(DB / "search/psi.sqlite")
    groups = {r[0]: (r[1], r[2]) for r in con.execute("select rowid, category, content_string from groups")}
    assets = {}
    for rowid, a, b in con.execute("select rowid, uuid_0, uuid_1 from assets"):
        raw = a.to_bytes(8, "little", signed=True) + b.to_bytes(8, "little", signed=True)
        assets[rowid] = str(uuid.UUID(bytes=raw)).upper()
    labels = collections.defaultdict(lambda: collections.defaultdict(list))
    for gid, aid in con.execute("select groupid, assetid from ga"):
        cat, s = groups.get(gid, (None, None))
        u = assets.get(aid)
        if not u or not s or not s.strip():
            continue
        if cat in PLACE_ORDER:
            labels[u][("place", cat)].append(s)
        else:
            for bucket, cats in BUCKETS.items():
                if cat in cats:
                    labels[u][bucket].append(s)
    return labels


def previews():
    """Asset UUID -> path of the largest image of it in the library (originals first, then previews)."""
    rank = {}
    best = {}

    def offer(uuid_, path, score):
        if score > rank.get(uuid_, -1):
            rank[uuid_], best[uuid_] = score, str(path)

    for path in (LIBRARY / "resources/derivatives").glob("*/*_1_10[0-9]_c.jpeg"):
        offer(path.name[:36], path, 2 if "_1_105_" in path.name else 1)
    for path in (LIBRARY / "resources/derivatives/masters").glob("*/*_4_5005_c.jpeg"):
        offer(path.name[:36], path, 0)
    for path in (LIBRARY / "originals").glob("*/*"):
        offer(path.stem[:36], path, 3)
    return best


def main():
    images = previews()
    con = connect(DB / "Photos.sqlite")
    moments = {r["Z_PK"]: ", ".join(x for x in (r["ZTITLE"], r["ZSUBTITLE"]) if x)
               for r in con.execute("select Z_PK, ZTITLE, ZSUBTITLE from ZMOMENT")}
    people = collections.defaultdict(set)
    for r in con.execute("""select f.ZASSETFORFACE a, coalesce(nullif(p.ZFULLNAME, ''), nullif(p.ZDISPLAYNAME, '')) name
                            from ZDETECTEDFACE f join ZPERSON p on p.Z_PK = f.ZPERSONFORFACE
                            where f.ZASSETFORFACE is not null"""):
        if r["name"]:
            people[r["a"]].add(r["name"])
    extra = {r["ZASSET"]: r for r in con.execute(
        """select a.ZASSET, a.ZORIGINALFILENAME, a.ZTITLE, a.ZTIMEZONENAME, a.ZIMPORTEDBYDISPLAYNAME, d.ZLONGDESCRIPTION
           from ZADDITIONALASSETATTRIBUTES a left join ZASSETDESCRIPTION d on d.Z_PK = a.ZASSETDESCRIPTION""")}
    albums = collections.defaultdict(list)
    names = {r["Z_PK"]: r["ZTITLE"] for r in con.execute("select Z_PK, ZTITLE from ZGENERICALBUM where ZKIND = 2 and ZTITLE is not null")}
    for (table,) in con.execute("select name from sqlite_master where type='table' and name like 'Z\\_%ASSETS' escape '\\'"):
        cols = [r[1] for r in con.execute(f"pragma table_info({table})")]
        acol = next((c for c in cols if c.endswith("ALBUMS")), None)
        scol = next((c for c in cols if c.endswith("ASSETS") and c != acol), None)
        if acol and scol:
            for r in con.execute(f"select {acol} al, {scol} asid from {table}"):
                if r["al"] in names:
                    albums[r["asid"]].append(names[r["al"]])
    labels = index_labels()

    with Writer("photos", AVENUE) as w:
        for r in con.execute("""select Z_PK, ZUUID, ZDATECREATED, ZLATITUDE, ZLONGITUDE, ZFILENAME, ZKIND, ZFAVORITE,
                                       ZHIDDEN, ZTRASHEDSTATE, ZDURATION, ZMOMENT
                                from ZASSET where ZTRASHEDSTATE = 0 and ZHIDDEN = 0"""):
            lab = labels.get(r["ZUUID"], {})
            place = [next(iter(lab[("place", c)])) for c in PLACE_ORDER if lab.get(("place", c))]
            place = list(dict.fromkeys(place)) or ([moments[r["ZMOMENT"]]] if moments.get(r["ZMOMENT"]) else [])
            who = sorted(people.get(r["Z_PK"], set()))
            camera = next(iter(lab.get("camera", [])), "").replace("\x00", "").strip() or None
            x = extra.get(r["Z_PK"])
            media = "video" if r["ZKIND"] == 1 else "photo"
            types = sorted(set(lab.get("type", [])))
            lines = [f"{media.title()}{' (' + ', '.join(types) + ')' if types else ''}"]
            if place:
                lines.append("Place: " + ", ".join(place))
            if who:
                lines.append("People: " + ", ".join(who))
            for key, label in (("scenes", "Scenes"), ("events", "Events"), ("app", "App")):
                vals = list(dict.fromkeys(lab.get(key, [])))
                if vals:
                    lines.append(f"{label}: " + ", ".join(vals[:25]))
            text_in_image = list(dict.fromkeys(lab.get("text", [])))
            if text_in_image:
                lines.append("Text in image: " + " ".join(text_in_image[:60]))
            if x is not None and (x["ZTITLE"] or x["ZLONGDESCRIPTION"]):
                lines.append("Caption: " + " ".join(v for v in (x["ZTITLE"], x["ZLONGDESCRIPTION"]) if v))
            if albums.get(r["Z_PK"]):
                lines.append("Albums: " + ", ".join(albums[r["Z_PK"]]))
            has_gps = r["ZLATITUDE"] not in (None, 0, -180) and -90 <= r["ZLATITUDE"] <= 90
            meta = {"type": media, "lat": r["ZLATITUDE"] if has_gps else None, "lon": r["ZLONGITUDE"] if has_gps else None,
                    "filename": (x["ZORIGINALFILENAME"] if x is not None else None) or r["ZFILENAME"],
                    "favorite": bool(r["ZFAVORITE"]) or None, "seconds": round(r["ZDURATION"]) if r["ZDURATION"] else None,
                    "timezone": x["ZTIMEZONENAME"] if x is not None else None,
                    "imported_by": x["ZIMPORTEDBYDISPLAYNAME"] if x is not None else None,
                    "moment": moments.get(r["ZMOMENT"]), "camera": camera}
            if r["ZUUID"] in images:
                meta["files"] = [images[r["ZUUID"]]]
            w.add(id=r["ZUUID"], kind="photo", ts=from_apple(r["ZDATECREATED"]), author="me", is_me=True,
                  thread=moments.get(r["ZMOMENT"]), thread_name=moments.get(r["ZMOMENT"]),
                  participants=who or None, title=place[0] if place else meta["filename"], text="\n".join(lines),
                  meta={k: v for k, v in meta.items() if v is not None})


if __name__ == "__main__":
    main()
