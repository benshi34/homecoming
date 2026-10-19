"""Photos library metadata: when and where each photo/video was taken, who is in it (named
faces), and Apple's on-device labels (scenes, places, businesses, events, text in the image).
Each record links the best image of it already on disk in meta.files (no copies): the library's own previews
(resources/derivatives/<X>/<UUID>_1_105_c.jpeg ~1-2k px, else masters/<X>/<UUID>_4_5005_c.jpeg thumbnails, else
the original when it's downloaded), so a model can look at the photo; with iCloud "Optimize Mac Storage" most
originals live only in iCloud.

Photos other people shared with you are kept, as their own source (shared_photos), so nothing counts them as yours:
shared albums (yours there are copies of photos already in your library), photos sent as an iCloud link, Shared with
You from Messages, and what others added to an iCloud Shared Library. What you added to a Shared Library is yours."""

import collections
import plistlib
import sqlite3
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
          "Hidden and trashed items are skipped, and counted (notes hidden_left_out, in_trash_left_out). ZGENERICASSET on "
          "macOS 10.15, ZDETECTEDFACE.ZASSET/ZPERSON before macOS 14 (ZASSETFORFACE/ZPERSONFORFACE since). An edited photo "
          "(ZHASADJUSTMENTS) links its edited version, resources/renders/<X>/<UUID>_1_201_a.*. ZASSET.ZBUNDLESCOPE says "
          "where an asset came from (0 your library, 1 an iCloud link, 2 a shared album, with ZCLOUDISMYASSET for the ones you posted, 3 Shared with You); in an iCloud "
          "Shared Library (ZLIBRARYSCOPE) who added it is ZASSETCONTRIBUTOR -> ZSHAREPARTICIPANT.ZISCURRENTUSER. Those "
          "that aren't your own go to shared_photos.")

# ZBUNDLESCOPE: where an asset came from, when not your own library.
SHARED_SCOPES = {1: "icloud_link", 2: "shared_album", 3: "shared_with_you"}

PLACE_ORDER = (1700, 1520, 6, 5, 10, 12, 14)
BUCKETS = {"scenes": {1500, 1510}, "events": {1600, 1601, 1611, 1800, 1402}, "text": {1203},
           "app": {2200}, "camera": {2300}, "type": {1903, 1905, 1907, 1908, 1909, 1910, 1912, 1914, 1915, 1919, 2800}}


def index_labels():
    """asset UUID -> {bucket: [strings]} from the Photos search index; none while Photos hasn't built one."""
    labels = collections.defaultdict(lambda: collections.defaultdict(list))
    if not (DB / "search/psi.sqlite").exists():
        return labels
    try:
        con = connect(DB / "search/psi.sqlite")
        groups = {r[0]: (r[1], r[2]) for r in con.execute("select rowid, category, content_string from groups")}
        rows = con.execute("select rowid, uuid_0, uuid_1 from assets").fetchall()
        pairs = con.execute("select groupid, assetid from ga").fetchall()
    except sqlite3.Error:  # an index of another shape, or one being rebuilt
        return labels
    assets = {}
    for rowid, a, b in rows:
        if isinstance(a, int) and isinstance(b, int):
            raw = a.to_bytes(8, "little", signed=True) + b.to_bytes(8, "little", signed=True)
            assets[rowid] = str(uuid.UUID(bytes=raw)).upper()
    for gid, aid in pairs:
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


def renders():
    """Asset UUID -> its edited version, full size (resources/renders/<X>/<UUID>_1_201_a.jpeg or .heic), which Photos
    keeps for a photo edited and shows in its place."""
    return {p.name[:36]: str(p) for p in sorted((LIBRARY / "resources/renders").glob("*/*_1_201_a.*"))}


SHARED_WORDS = {"icloud_link": "Shared with you as an iCloud link", "shared_album": "In a shared album",
                "shared_with_you": "Shared with you in Messages", "shared_library": "Added to your Shared Library by someone else",
                "shared": "Shared with you"}


def shared_library_mine(con):
    """Asset -> whether you added it to the iCloud Shared Library, for the assets whose contributor is known."""
    try:
        rows = con.execute("""select c.Z3LIBRARYSCOPEASSETCONTRIBUTORS a, max(p.ZISCURRENTUSER) me from ZASSETCONTRIBUTOR c
                              join ZSHAREPARTICIPANT p on p.Z_PK = c.ZPARTICIPANT group by 1""").fetchall()
    except Exception:  # a library from before Shared Libraries
        return {}
    return {r["a"]: bool(r["me"]) for r in rows if r["a"] is not None}


def name_of(blob):
    """A shared album member's name, from Photos' archived NSPersonNameComponents (given and family name)."""
    try:
        objs = plistlib.loads(blob).get("$objects", [])
    except Exception:
        return None
    ref = lambda v: objs[v.data] if isinstance(v, plistlib.UID) and v.data < len(objs) else v
    for o in objs:
        if isinstance(o, dict) and "NS.givenName" in o:
            parts = [ref(o.get(k)) for k in ("NS.givenName", "NS.middleName", "NS.familyName")]
            name = " ".join(p for p in parts if isinstance(p, str) and p and p != "$null").strip()
            return name or (ref(o.get("NS.nickname")) if isinstance(ref(o.get("NS.nickname")), str) else None)
    return None


def collection_shares(con):
    """Shared albums as Photos keeps them since macOS 26: a ZSHARE row (CollectionShare) each, linked from
    ZASSET.ZCOLLECTIONSHARE, and who posted each photo through ZASSETCONTRIBUTOR (before, a ZGENERICALBUM of kind 1505).
    Asset -> (album, who posted it, or None when it was you)."""
    cols = {r[1] for r in con.execute("pragma table_info(ZASSET)")}
    if "ZCOLLECTIONSHARE" not in cols:
        return {}
    by = "ZCOLLECTIONSHAREASSETCONTRIBUTOR" if "ZCOLLECTIONSHAREASSETCONTRIBUTOR" in cols else None
    try:
        rows = con.execute(f"""select a.Z_PK asid, s.ZTITLE title, {"p.ZISCURRENTUSER me, p.ZNAMECOMPONENTS names, p.ZEMAILADDRESS email" if by else "null me, null names, null email"}
                               from ZASSET a join ZSHARE s on s.Z_PK = a.ZCOLLECTIONSHARE
                               {f"left join ZASSETCONTRIBUTOR c on c.Z_PK = a.{by} left join ZSHAREPARTICIPANT p on p.Z_PK = c.ZPARTICIPANT" if by else ""}
                               where s.ZTITLE is not null""").fetchall()
    except sqlite3.Error:
        return {}
    names = {}
    out = {}
    for r in rows:
        who = None
        if by and not r["me"] and (r["names"] or r["email"]):
            key = (r["names"], r["email"])
            if key not in names:
                names[key] = (name_of(r["names"]) if r["names"] else None) or r["email"]
            who = names[key]
        out[r["asid"]] = (r["title"], who)
    return out


def table_columns(con, table):
    try:
        return {r[1] for r in con.execute(f"pragma table_info({table})")}
    except sqlite3.Error:
        return set()


def memories(con):
    """Photos' Memories (not the ones you turned down): title, dates, and how often you watched and shared each."""
    # Each column only if this library has it (older ones count fewer things): one missing mustn't lose them all, now that
    # nothing is kept from an earlier read.
    cols = table_columns(con, "ZMEMORY")
    opt = lambda c: c if c in cols else f"null as {c}"  # noqa: E731
    try:
        rows = con.execute(f"""select ZUUID, ZTITLE, {", ".join(map(opt, ("ZSUBTITLE", "ZSTARTDATE", "ZENDDATE", "ZCREATIONDATE", "ZFAVORITE",
                                                                         "ZPLAYCOUNT", "ZVIEWCOUNT", "ZSHARECOUNT")))}
                               from ZMEMORY where ZTITLE is not null and coalesce({"ZREJECTED" if "ZREJECTED" in cols else 0}, 0) = 0""").fetchall()
    except sqlite3.Error:  # a library without Memories
        return []
    return [dict(id=f"memory:{r['ZUUID']}", kind="memory", ts=from_apple(r["ZSTARTDATE"]), ts_end=from_apple(r["ZENDDATE"]), author="Photos",
                 is_me=False, title=r["ZTITLE"], text=" · ".join(x for x in (r["ZTITLE"], r["ZSUBTITLE"]) if x),
                 meta={k: v for k, v in (("subtitle", r["ZSUBTITLE"]), ("made", from_apple(r["ZCREATIONDATE"])), ("favorite", bool(r["ZFAVORITE"]) or None),
                                         ("plays", r["ZPLAYCOUNT"] or None), ("views", r["ZVIEWCOUNT"] or None), ("shares", r["ZSHARECOUNT"] or None)) if v})
            for r in rows]


def highlights(con):
    """The days and trips Photos titled (ZPHOTOSHIGHLIGHT kind 0, a day; 3, several days), with its description of each.
    Months and years are left out: they only add up the rest."""
    cols = table_columns(con, "ZPHOTOSHIGHLIGHT")
    opt = lambda c: c if c in cols else f"null as {c}"  # noqa: E731
    try:
        rows = con.execute(f"""select ZUUID, ZKIND, ZTITLE, {", ".join(map(opt, ("ZSUBTITLE", "ZSTARTDATE", "ZENDDATE", "ZVERBOSESMARTDESCRIPTION")))}
                               from ZPHOTOSHIGHLIGHT where ZKIND in (0, 3) and ZTITLE is not null""").fetchall()
    except sqlite3.Error:
        return []
    return [dict(id=f"highlight:{r['ZUUID']}", kind="highlight", ts=from_apple(r["ZSTARTDATE"]), ts_end=from_apple(r["ZENDDATE"]), author="Photos",
                 is_me=False, title=r["ZTITLE"], text="\n".join(x for x in (" · ".join(y for y in (r["ZTITLE"], r["ZSUBTITLE"]) if y), r["ZVERBOSESMARTDESCRIPTION"]) if x),
                 meta={k: v for k, v in (("span", "days" if r["ZKIND"] == 3 else "day"), ("subtitle", r["ZSUBTITLE"])) if v})
            for r in rows]


def main():
    if not (DB / "Photos.sqlite").exists():
        print("[photos] no Photos library here")
        return
    con = connect(DB / "Photos.sqlite")
    have = {r[0] for r in con.execute("select name from sqlite_master where type = 'table'")}
    # The assets table: ZASSET since macOS 11, ZGENERICASSET on 10.15 (osxphotos' _DB_TABLE_NAMES).
    asset = "ZASSET" if "ZASSET" in have else "ZGENERICASSET" if "ZGENERICASSET" in have else None
    if not asset:  # made, never written to
        print("[photos] the library has no photos yet")
        return
    images, edited_images = previews(), renders()
    moments = {r["Z_PK"]: ", ".join(x for x in (r["ZTITLE"], r["ZSUBTITLE"]) if x)
               for r in con.execute("select Z_PK, ZTITLE, ZSUBTITLE from ZMOMENT" if "ZMOMENT" in have else "select 1 where 0")}
    people = collections.defaultdict(set)
    # Who is in each: ZDETECTEDFACE.ZASSETFORFACE and .ZPERSONFORFACE since macOS 14, .ZASSET and .ZPERSON before.
    fcols = table_columns(con, "ZDETECTEDFACE")
    fa, fp = ("ZASSETFORFACE", "ZPERSONFORFACE") if "ZASSETFORFACE" in fcols else ("ZASSET", "ZPERSON")
    if {fa, fp} <= fcols and "ZPERSON" in have:
        for r in con.execute(f"""select f.{fa} a, coalesce(nullif(p.ZFULLNAME, ''), nullif(p.ZDISPLAYNAME, '')) name
                                 from ZDETECTEDFACE f join ZPERSON p on p.Z_PK = f.{fp}
                                 where f.{fa} is not null"""):
            if r["name"]:
                people[r["a"]].add(r["name"])
    # How often each was looked at, played and shared (and last looked at), where Photos counts it; each column only if
    # this version of Photos has it.
    acols = table_columns(con, "ZADDITIONALASSETATTRIBUTES")
    counted = ", ".join(f"a.{c}" if c in acols else f"null {c}" for c in (
        "ZORIGINALFILENAME", "ZTITLE", "ZTIMEZONENAME", "ZIMPORTEDBYDISPLAYNAME", "ZVIEWCOUNT", "ZPLAYCOUNT", "ZSHARECOUNT", "ZLASTVIEWEDDATE"))
    described = "ZASSETDESCRIPTION" in have and "ZASSETDESCRIPTION" in acols
    extra = {r["ZASSET"]: r for r in con.execute(
        f"""select a.ZASSET, {"d.ZLONGDESCRIPTION" if described else "null ZLONGDESCRIPTION"}, {counted}
           from ZADDITIONALASSETATTRIBUTES a {"left join ZASSETDESCRIPTION d on d.Z_PK = a.ZASSETDESCRIPTION" if described else ""}"""
        if "ZASSET" in acols else "select 1 where 0")}
    albums = collections.defaultdict(list)
    # Albums, and shared albums (kind 1505), by name.
    names = {r["Z_PK"]: r["ZTITLE"] for r in con.execute("select Z_PK, ZTITLE from ZGENERICALBUM where ZKIND in (2, 1505) and ZTITLE is not null"
                                                          if "ZGENERICALBUM" in have else "select 1 where 0")}
    for (table,) in con.execute("select name from sqlite_master where type='table' and name like 'Z\\_%ASSETS' escape '\\'"):
        cols = [r[1] for r in con.execute(f"pragma table_info({table})")]
        acol = next((c for c in cols if c.endswith("ALBUMS")), None)
        scol = next((c for c in cols if c.endswith("ASSETS") and c != acol), None)
        if acol and scol:
            for r in con.execute(f"select {acol} al, {scol} asid from {table}"):
                if r["al"] in names:
                    albums[r["asid"]].append(names[r["al"]])
    posted_by = {}
    for asid, (album, who) in collection_shares(con).items():
        if album not in albums[asid]:
            albums[asid].append(album)
        if who:
            posted_by[asid] = who
    labels = index_labels()
    added_by_me = shared_library_mine(con)
    cols = table_columns(con, asset)
    opt = lambda c: c if c in cols else f"null as {c}"  # older libraries have no sharing columns

    with Writer("photos", AVENUE) as w, Writer("shared_photos", AVENUE, parser="connectors/photos.py:main") as ws:
        # Hidden and in the trash: left out, and counted, so the manifest says how many. A flag never set (null) isn't one.
        hidden, trashed = con.execute(f"""select sum(coalesce(ZHIDDEN, 0) != 0 and coalesce(ZTRASHEDSTATE, 0) = 0),
                                                 sum(coalesce(ZTRASHEDSTATE, 0) != 0) from {asset}""").fetchone()
        for key, n in (("hidden_left_out", hidden), ("in_trash_left_out", trashed)):
            if n:
                w.notes[key] = n
        for r in con.execute(f"""select Z_PK, ZUUID, ZDATECREATED, ZLATITUDE, ZLONGITUDE, ZFILENAME, ZKIND, ZFAVORITE,
                                       ZHIDDEN, ZTRASHEDSTATE, ZDURATION, ZMOMENT, {opt("ZBUNDLESCOPE")}, {opt("ZCLOUDISMYASSET")},
                                       {opt("ZLIBRARYSCOPE")}, {opt("ZKINDSUBTYPE")}, {opt("ZHASADJUSTMENTS")}
                                from {asset} where coalesce(ZTRASHEDSTATE, 0) = 0 and coalesce(ZHIDDEN, 0) = 0"""):
            shared = SHARED_SCOPES.get(r["ZBUNDLESCOPE"]) or ("shared_library" if r["ZLIBRARYSCOPE"] else None)
            if r["ZBUNDLESCOPE"] and not shared:
                shared = "shared"  # a kind of sharing Photos has added since: not your own library either way
            # Yours: your own library, and what you added to a Shared Library (who added it unknown counts as you).
            others = shared and not (shared == "shared_library" and added_by_me.get(r["Z_PK"], True))
            mine = not others or (shared == "shared_album" and r["ZCLOUDISMYASSET"] == 1)
            lab = labels.get(r["ZUUID"], {})
            place = [next(iter(lab[("place", c)])) for c in PLACE_ORDER if lab.get(("place", c))]
            place = list(dict.fromkeys(place)) or ([moments[r["ZMOMENT"]]] if moments.get(r["ZMOMENT"]) else [])
            who = sorted(people.get(r["Z_PK"], set()))
            camera = next(iter(lab.get("camera", [])), "").replace("\x00", "").strip() or None
            x = extra.get(r["Z_PK"])
            media = "video" if r["ZKIND"] == 1 else "photo"
            types = sorted(set(lab.get("type", [])) | ({"Screenshot"} if r["ZKINDSUBTYPE"] == 10 else set()))
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
                    "moment": moments.get(r["ZMOMENT"]), "camera": camera, "screenshot": r["ZKINDSUBTYPE"] == 10 or None,
                    "views": (x["ZVIEWCOUNT"] or None) if x is not None else None, "plays": (x["ZPLAYCOUNT"] or None) if x is not None else None,
                    "shares": (x["ZSHARECOUNT"] or None) if x is not None else None,
                    "last_viewed": from_apple(x["ZLASTVIEWEDDATE"]) if x is not None else None, "album": (albums.get(r["Z_PK"]) or [None])[0] if shared == "shared_album" else None,
                    "posted_by": posted_by.get(r["Z_PK"]), "edited": bool(r["ZHASADJUSTMENTS"]) or None}
            # As it looks now: an edited one's edited version, else the best image of it there is.
            best = (edited_images.get(r["ZUUID"]) if r["ZHASADJUSTMENTS"] else None) or images.get(r["ZUUID"])
            if best:
                meta["files"] = [best]
            if shared:
                meta["shared"] = shared
            if others and mine:
                meta["copy"] = True  # one you posted to a shared album: the original is in your library
            if others:
                said = f'In the shared album "{meta["album"]}"' if shared == "shared_album" and meta.get("album") else SHARED_WORDS[shared]
                lines.insert(1, said + (" (one you posted)" if mine else f", posted by {posted_by[r['Z_PK']]}" if r["Z_PK"] in posted_by else ""))
                w.skip(r["ZUUID"])  # an earlier run may have kept it with your own photos
            (ws if others else w).add(
                id=r["ZUUID"], kind="photo", ts=from_apple(r["ZDATECREATED"]),
                author="me" if mine else posted_by.get(r["Z_PK"]) or "someone else", is_me=bool(mine),
                thread=moments.get(r["ZMOMENT"]), thread_name=moments.get(r["ZMOMENT"]),
                participants=who or None, title=place[0] if place else meta["filename"], text="\n".join(lines),
                meta={k: v for k, v in meta.items() if v is not None})
    # What Photos made of them: Memories, and the days and trips it titled. Their own source, so nothing counts them as
    # photos you took, and left out of the stream: they're Photos' summaries, not something that happened. As Photos has
    # them now: one you turned down, or that Photos dropped, isn't kept from an earlier read.
    with Writer("photos_memories", AVENUE, parser="connectors/photos.py:memories", accumulate=False) as wm:
        for m in [*memories(con), *highlights(con)]:
            wm.add(**m)


if __name__ == "__main__":
    main()
