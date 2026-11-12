"""Loose photos and videos on mounted external drives.

The files stay where they are.  This connector records the metadata that is useful to the photo views and keeps
the path in ``meta.path`` so a later reader can open the original.  Drive discovery and directory filtering belong
to :mod:`documents`; this module deliberately uses the same policy instead of walking volumes itself.

JPEG/TIFF EXIF and the small subset of ISO-BMFF used by HEIC/MOV/MP4 are parsed here so an unindexed drive works
without Pillow, ImageIO or another optional package.
"""

import datetime as dt
import json
import mmap
import os
import struct
from pathlib import Path

import documents
from common import NORM, RAW, Writer, from_unix, read_json, write_atomic

AVENUE = ("Loose photos and videos on selected mounted external drives. Metadata is read in place from JPEG/TIFF "
          "EXIF and HEIC/MOV/MP4 containers: taken time, GPS, camera, pixel size and video duration. No pixels are "
          "copied. An unchanged file (same size and modification time) uses the metadata cache in "
          "corpus/raw/drive_photos/read.json; records remain when a drive is unplugged.")

READER = "1"
READ = RAW / "drive_photos" / "read.json"
MIN_IMAGE_BYTES = 20 * 1024
IMAGE_EXTS = {".jpg", ".jpeg", ".heic", ".heif", ".png", ".tif", ".tiff", ".dng", ".cr2", ".cr3", ".nef",
              ".arw", ".raf", ".orf", ".rw2"}
VIDEO_EXTS = {".mov", ".mp4", ".m4v", ".avi", ".mts"}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS
UTC = dt.timezone.utc
QUICKTIME_EPOCH = dt.datetime(1904, 1, 1, tzinfo=UTC)


def _iso_date(value, offset=None):
    """Parse EXIF/QuickTime date text and return a Writer-friendly ISO timestamp."""
    if isinstance(value, bytes):
        value = value.split(b"\0", 1)[0].decode("latin1", errors="replace")
    if not isinstance(value, str):
        return None
    value = value.strip().replace("\0", "")
    if not value:
        return None
    # QuickTime metadata commonly stores an ISO date; EXIF uses colons in the date portion.
    if len(value) >= 19 and value[4] == ":" and value[7] == ":":
        value = value[:10].replace(":", "-") + value[10:]
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = dt.datetime.strptime(value, fmt)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        if offset:
            try:
                sign = -1 if str(offset).startswith("-") else 1
                raw = str(offset).lstrip("+-")
                hours, minutes = (raw.split(":", 1) + ["0"])[:2]
                parsed = parsed.replace(tzinfo=dt.timezone(sign * dt.timedelta(hours=int(hours), minutes=int(minutes))))
            except (TypeError, ValueError, OverflowError):
                parsed = parsed.replace(tzinfo=UTC)
        else:
            # EXIF DateTimeOriginal without OffsetTimeOriginal is the camera's wall clock: read in this Mac's time
            # zone, as Photos does when it imports such a file.
            parsed = parsed.astimezone()
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _tiff_value(data, endian, typ, count, raw):
    sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}
    size = sizes.get(typ)
    if size is None:
        return None
    total = size * count
    if total > len(raw):
        return None
    fmt = ">" if endian == "M" else "<"
    try:
        if typ == 2:
            return raw[:total].split(b"\0", 1)[0].decode("utf-8", errors="replace")
        if typ in (1, 7):
            return list(raw[:total])
        if typ == 3:
            vals = list(struct.unpack(fmt + f"{count}H", raw[:total]))
        elif typ == 4:
            vals = list(struct.unpack(fmt + f"{count}I", raw[:total]))
        elif typ == 5:
            vals = []
            for i in range(count):
                n, d = struct.unpack(fmt + "II", raw[i * 8:i * 8 + 8])
                vals.append(n / d if d else 0)
        elif typ == 9:
            vals = list(struct.unpack(fmt + f"{count}i", raw[:total]))
        elif typ == 10:
            vals = []
            for i in range(count):
                n, d = struct.unpack(fmt + "ii", raw[i * 8:i * 8 + 8])
                vals.append(n / d if d else 0)
        else:
            return None
        return vals[0] if count == 1 else vals
    except (struct.error, ZeroDivisionError):
        return None


def _parse_tiff(data):
    """Read the useful EXIF/TIFF tags from a TIFF header at the beginning of *data*."""
    if len(data) < 8 or data[:2] not in (b"II", b"MM"):
        return {}
    endian = "I" if data[:2] == b"II" else "M"
    fmt = "<" if endian == "I" else ">"
    if struct.unpack(fmt + "H", data[2:4])[0] != 42:
        return {}
    first = struct.unpack(fmt + "I", data[4:8])[0]
    tags = {}
    seen = set()

    def ifd(offset, depth=0):
        if depth > 3 or offset in seen or offset + 2 > len(data):
            return
        seen.add(offset)
        try:
            count = struct.unpack(fmt + "H", data[offset:offset + 2])[0]
        except struct.error:
            return
        pos = offset + 2
        for _ in range(min(count, 512)):
            if pos + 12 > len(data):
                return
            try:
                tag, typ, n = struct.unpack(fmt + "HHI", data[pos:pos + 8])
            except struct.error:
                return
            size = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}.get(typ)
            if size is None:
                pos += 12
                continue
            total = size * n
            value_offset = pos + 8 if total <= 4 else None
            if value_offset is None:
                try:
                    value_offset = struct.unpack(fmt + "I", data[pos + 8:pos + 12])[0]
                except struct.error:
                    value_offset = -1
            raw = data[value_offset:value_offset + total] if value_offset >= 0 else b""
            if len(raw) == total:
                value = _tiff_value(data, endian, typ, n, raw)
                if tag not in tags:
                    tags[tag] = value
                if tag == 0x8769 and isinstance(value, (int, float)):
                    ifd(int(value), depth + 1)
                elif tag == 0x8825:
                    ifd(int(value[0] if isinstance(value, list) else value), depth + 1)
            pos += 12

    ifd(first)
    return tags


def _exif_from_bytes(data):
    """Find an EXIF payload in a JPEG APP1 or an HEIF Exif item."""
    marker = data.find(b"Exif\0\0")
    if marker >= 0:
        parsed = _parse_tiff(data[marker + 6:])
        if parsed:
            return parsed
    for marker in (data.find(b"II*\0"), data.find(b"MM\0*")):
        if marker >= 0:
            parsed = _parse_tiff(data[marker:])
            if parsed:
                return parsed
    return {}


def _gps(tags):
    lat, lon = tags.get(2), tags.get(4)
    if not isinstance(lat, (list, tuple)) or not isinstance(lon, (list, tuple)) or len(lat) < 3 or len(lon) < 3:
        return None, None
    try:
        lat = float(lat[0]) + float(lat[1]) / 60 + float(lat[2]) / 3600
        lon = float(lon[0]) + float(lon[1]) / 60 + float(lon[2]) / 3600
        if str(tags.get(1, "N")).upper().startswith("S"):
            lat = -lat
        if str(tags.get(3, "E")).upper().startswith("W"):
            lon = -lon
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None, None
        return lat, lon
    except (TypeError, ValueError, ZeroDivisionError):
        return None, None


def _camera(tags):
    make = str(tags.get(0x010F) or "").strip()
    model = str(tags.get(0x0110) or "").strip()
    camera = " ".join(x for x in (make, model) if x)
    return camera or None, make or None, model or None


def _jpeg(data):
    tags = {}
    width = height = None
    if data[:2] != b"\xff\xd8":
        return {}, width, height
    pos = 2
    sof = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            pos += 1
            continue
        while pos < len(data) and data[pos] == 0xFF:
            pos += 1
        if pos >= len(data):
            break
        marker = data[pos]
        pos += 1
        if marker in (0xD8, 0xD9):
            continue
        if marker == 0xDA:
            break
        try:
            length = struct.unpack(">H", data[pos:pos + 2])[0]
        except struct.error:
            break
        if length < 2 or pos + length > len(data):
            break
        payload = data[pos + 2:pos + length]
        if marker == 0xE1 and payload.startswith(b"Exif\0\0"):
            tags.update(_parse_tiff(payload[6:]))
        if marker in sof and len(payload) >= 5:
            height, width = struct.unpack(">HH", payload[1:5])
        pos += length
    return tags, width, height


def _iter_boxes(data, start=0, end=None):
    end = len(data) if end is None else min(end, len(data))
    pos = max(0, start)
    while pos + 8 <= end:
        try:
            size = struct.unpack(">I", data[pos:pos + 4])[0]
        except struct.error:
            return
        typ = data[pos + 4:pos + 8]
        head = 8
        if size == 1:
            if pos + 16 > end:
                return
            size = struct.unpack(">Q", data[pos + 8:pos + 16])[0]
            head = 16
        elif size == 0:
            size = end - pos
        if size < head or pos + size > end:
            return
        yield typ, data[pos + head:pos + size]
        pos += size


CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts", b"dinf", b"udta", b"meta", b"ilst",
              b"iprp", b"ipco", b"meco", b"mere", b"iref"}


def _movie_times(payload):
    """creation seconds, timescale and duration from an mvhd/mdhd FullBox payload."""
    if len(payload) < 20:
        return None
    try:
        if payload[0] == 1:
            if len(payload) < 32:
                return None
            creation, _modified, timescale, duration = struct.unpack(">QQIQ", payload[4:32])
        else:
            creation, _modified, timescale, duration = struct.unpack(">IIII", payload[4:20])
        return creation, timescale, duration
    except struct.error:
        return None


def _bmff(data):
    result = {}
    tags = {}

    def visit(start=0, end=None):
        for typ, payload in _iter_boxes(data, start, end):
            if typ == b"mvhd" and len(payload) >= 20:
                try:
                    values = _movie_times(payload)
                    if values is None:
                        raise struct.error
                    creation, timescale, duration = values
                    if creation:
                        result["ts"] = _iso_date((QUICKTIME_EPOCH + dt.timedelta(seconds=creation)).isoformat())
                    if timescale:
                        result["seconds"] = duration / timescale
                except (struct.error, OverflowError, ValueError):
                    pass
            elif typ == b"mdhd" and len(payload) >= 20 and "seconds" not in result:
                try:
                    values = _movie_times(payload)
                    if values is None:
                        raise struct.error
                    creation, timescale, duration = values
                    if creation and "ts" not in result:
                        result["ts"] = _iso_date((QUICKTIME_EPOCH + dt.timedelta(seconds=creation)).isoformat())
                    if timescale:
                        result["seconds"] = duration / timescale
                except (struct.error, OverflowError, ValueError):
                    pass
            elif typ == b"tkhd" and len(payload) >= 8:
                try:
                    result.setdefault("width", round(struct.unpack(">I", payload[-8:-4])[0] / 65536))
                    result.setdefault("height", round(struct.unpack(">I", payload[-4:])[0] / 65536))
                except struct.error:
                    pass
            elif typ == b"ispe" and len(payload) >= 12:
                try:
                    result.setdefault("width", struct.unpack(">I", payload[4:8])[0])
                    result.setdefault("height", struct.unpack(">I", payload[8:12])[0])
                except struct.error:
                    pass
            elif typ in (b"\xa9day", b"day ", b"date"):
                value = payload[4:] if len(payload) >= 4 and payload[:4] == b"data" else payload
                result.setdefault("ts", _iso_date(value))
            elif typ in (b"\xa9mak", b"make", b"manu"):
                tags["make"] = payload[8:] if len(payload) >= 8 and payload[4:8] == b"data" else payload
            elif typ in (b"\xa9mod", b"model"):
                tags["model"] = payload[8:] if len(payload) >= 8 and payload[4:8] == b"data" else payload
            if typ == b"Exif" or typ in CONTAINERS:
                # FullBox containers have four version/flags bytes before their child boxes.
                child_start = 4 if typ == b"meta" else 0
                if typ == b"Exif":
                    exif = _exif_from_bytes(payload)
                    if exif:
                        tags.update({f"exif:{k}": v for k, v in exif.items()})
                elif len(payload) >= child_start + 8:
                    visit_from(payload, child_start)

    def visit_from(payload, start=0):
        # Nested box traversal needs the payload's own bytes, but metadata values are small and can be handled inline.
        for typ, child in _iter_boxes(payload, start):
            if typ == b"Exif":
                exif = _exif_from_bytes(child)
                if exif:
                    tags.update({f"exif:{k}": v for k, v in exif.items()})
            elif typ == b"mvhd" and len(child) >= 20:
                try:
                    values = _movie_times(child)
                    if values is None:
                        raise struct.error
                    creation, timescale, duration = values
                    if creation and "ts" not in result:
                        result["ts"] = _iso_date((QUICKTIME_EPOCH + dt.timedelta(seconds=creation)).isoformat())
                    if timescale and "seconds" not in result:
                        result["seconds"] = duration / timescale
                except (struct.error, OverflowError, ValueError):
                    pass
            elif typ == b"mdhd" and len(child) >= 20 and "seconds" not in result:
                try:
                    values = _movie_times(child)
                    if values is None:
                        raise struct.error
                    creation, timescale, duration = values
                    if creation and "ts" not in result:
                        result["ts"] = _iso_date((QUICKTIME_EPOCH + dt.timedelta(seconds=creation)).isoformat())
                    if timescale:
                        result["seconds"] = duration / timescale
                except (struct.error, OverflowError, ValueError):
                    pass
            elif typ == b"tkhd" and len(child) >= 8:
                try:
                    result.setdefault("width", round(struct.unpack(">I", child[-8:-4])[0] / 65536))
                    result.setdefault("height", round(struct.unpack(">I", child[-4:])[0] / 65536))
                except struct.error:
                    pass
            elif typ == b"ispe" and len(child) >= 12:
                try:
                    result.setdefault("width", struct.unpack(">I", child[4:8])[0])
                    result.setdefault("height", struct.unpack(">I", child[8:12])[0])
                except struct.error:
                    pass
            elif typ in (b"\xa9day", b"day ", b"date"):
                value = child[8:] if len(child) >= 8 and child[4:8] == b"data" else child
                result.setdefault("ts", _iso_date(value))
            elif typ in (b"\xa9mak", b"make", b"manu"):
                tags["make"] = child[8:] if len(child) >= 8 and child[4:8] == b"data" else child
            elif typ in (b"\xa9mod", b"model"):
                tags["model"] = child[8:] if len(child) >= 8 and child[4:8] == b"data" else child
            if typ == b"meta":
                visit_from(child, 4)
            elif typ in CONTAINERS:
                visit_from(child)

    visit()
    # Some hand-written HEIC fixtures and older cameras put the Exif item outside a standard box hierarchy.
    if not any(k.startswith("exif:") for k in tags):
        exif = _exif_from_bytes(data)
        tags.update({f"exif:{k}": v for k, v in exif.items()})
    exif = {int(k[5:]) if k[5:].isdigit() else k[5:]: v for k, v in tags.items() if k.startswith("exif:")}
    if exif:
        result["exif"] = exif
    result["tags"] = tags
    return result


def _png(data):
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24 and data[12:16] == b"IHDR":
        return struct.unpack(">II", data[16:24])
    return None, None


def _read_container(path, data):
    ext = path.suffix.lower()
    result = {}
    if ext in (".jpg", ".jpeg"):
        tags, width, height = _jpeg(data)
        result.update({"tags": tags, "width": width, "height": height})
    elif ext == ".png":
        width, height = _png(data)
        result.update({"width": width, "height": height})
    elif ext in {".tif", ".tiff", ".dng", ".cr2", ".nef", ".arw", ".raf", ".orf", ".rw2"}:
        result["tags"] = _parse_tiff(data)
    elif ext in {".cr3", ".heic", ".heif", ".mov", ".mp4", ".m4v", ".mts"}:
        result.update(_bmff(data))
    elif ext == ".avi":
        # AVI's RIFF header has no universally reliable capture timestamp.  Keep file time in that case; dimensions
        # can be read from the avih chunk when present.
        marker = data.find(b"avih", 0, 65536)
        if marker >= 0 and marker + 48 <= len(data):
            try:
                result["width"], result["height"] = struct.unpack("<II", data[marker + 40:marker + 48])
            except struct.error:
                pass
    return result


def _metadata(path, st):
    # Mapped, not read: the parsers touch only the headers and boxes they need, so a 4 GB video costs a few pages.
    try:
        with open(path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
            try:
                result = _read_container(path, data)
            except Exception:  # noqa: BLE001  one odd file is read by its name and dates, never ends the run
                result = {}
    except (OSError, ValueError):  # unreadable, or empty (an empty file can't be mapped)
        return None
    tags = result.get("tags") or {}
    if "exif" in result:
        tags = {**tags, **result["exif"]}
    date = tags.get(0x9003) or tags.get(0x9004) or tags.get(0x0132)
    timestamp = _iso_date(date, tags.get(0x9011) or tags.get(0x9012))
    if not timestamp:
        timestamp = result.get("ts")
    time_from = None
    if not timestamp:
        timestamp = from_unix(getattr(st, "st_birthtime", 0) or st.st_mtime)
        time_from = "file"
    lat, lon = _gps(tags)
    camera = None
    make = model = None
    if tags:
        camera, make, model = _camera(tags)
    bmff_tags = result.get("tags") or {}
    if not camera:
        make = _as_text(bmff_tags.get("make"))
        model = _as_text(bmff_tags.get("model"))
        camera = " ".join(x for x in (make, model) if x) or None
    width = result.get("width") or tags.get(0x0100)
    height = result.get("height") or tags.get(0x0101)
    out = {"ts": timestamp, "time_from": time_from, "lat": lat, "lon": lon, "camera": camera,
           "camera_make": make, "camera_model": model, "width": width, "height": height,
           "seconds": round(result["seconds"]) if result.get("seconds") is not None else None}
    return {k: v for k, v in out.items() if v is not None}


def _as_text(value):
    if isinstance(value, bytes):
        return value.rstrip(b"\0").decode("utf-8", errors="replace").strip() or None
    return str(value).strip() if value else None


def _time_key(ts):
    if not ts:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except ValueError:
        return str(ts)[:19]


def _photos_seen():
    """(original filename, timestamp-to-second) pairs already in Photos."""
    out = set()
    path = NORM / "photos.jsonl"
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                meta = rec.get("meta") or {}
                filename = meta.get("filename") or rec.get("title")
                if filename and rec.get("ts"):
                    out.add((Path(str(filename)).name.casefold(), _time_key(rec["ts"])))
    except OSError:
        pass
    return out


def _drive_files(selected):
    roots = [Path(mount) for _, mount, _ in selected]
    for name, mount, volume_uuid in selected:
        root = Path(mount)
        others = {p for p in roots if p != root} | {Path(os.path.realpath(p)) for p in roots if p != root}
        try:
            iterator = documents.walk(root, others=others, downloads=True, drive=True)
            for path, _counts in iterator:
                ext = path.suffix.lower()
                if ext not in MEDIA_EXTS:
                    continue
                try:
                    st = path.stat()
                except OSError:
                    continue
                if ext in IMAGE_EXTS and st.st_size < MIN_IMAGE_BYTES:
                    continue
                yield name, str(volume_uuid or ""), root, path, st
        except OSError:
            # A drive can disappear between diskutil discovery and os.walk. Writer accumulation keeps its records.
            continue


def main():
    notes = {}
    available = documents.drives(notes)
    selected = documents.selected_drives(available)
    cache = read_json(READ, {})
    old = cache.get("files") if isinstance(cache, dict) and cache.get("reader") == READER else {}
    old = old if isinstance(old, dict) else {}
    files = dict(old)
    photos = _photos_seen()
    with Writer("drive_photos", AVENUE, parser="connectors/drive_photos.py:main") as w:
        w.notes.update(notes)
        found = []
        for drive, drive_id, root, path, st in _drive_files(selected):
            key = str(path)
            entry = old.get(key)
            stat_key = {"size": st.st_size, "mtime": st.st_mtime_ns}
            if isinstance(entry, dict) and entry.get("size") == st.st_size and entry.get("mtime") == st.st_mtime_ns \
                    and isinstance(entry.get("meta"), dict):
                meta = dict(entry["meta"])
            else:
                meta = _metadata(path, st)
                files[key] = {**stat_key, "meta": meta}
            if not meta:
                w.notes["metadata_unreadable"] = w.notes.get("metadata_unreadable", 0) + 1
                continue
            found.append((drive, drive_id, root, path, key, meta))
        # A camera's: one with a camera or a time it was taken, one beside such (a photo folder where some lost
        # theirs), or one under DCIM (a camera card). The rest (screenshots, an app's images) are only counted.
        made = lambda meta: bool(meta.get("camera") or meta.get("time_from") != "file")  # noqa: E731
        photo_folders = {path.parent for _, _, _, path, _, meta in found if made(meta)}
        for drive, drive_id, root, path, key, meta in found:
            if not (made(meta) or path.parent in photo_folders or "DCIM" in path.relative_to(root).parts):
                w.notes["images_not_from_a_camera"] = w.notes.get("images_not_from_a_camera", 0) + 1
                continue
            media = "video" if path.suffix.lower() in VIDEO_EXTS else "photo"
            taken = _time_key(meta.get("ts"))
            record_meta = {"type": media, "filename": path.name, "path": key, "files": [key], "drive": drive, "drive_id": drive_id or None,
                           **{k: meta.get(k) for k in ("lat", "lon", "camera", "camera_make", "camera_model", "width", "height", "seconds", "time_from")}}
            record_meta = {k: v for k, v in record_meta.items() if v is not None}
            if (path.name.casefold(), taken) in photos:
                record_meta["also_in"] = "photos"
            rid = f"drive:{drive_id}/{path.relative_to(root)}" if drive_id else key  # a renamed drive: same records
            w.add(id=rid, kind=media, ts=meta.get("ts"), author="me", is_me=True, thread=drive, thread_name=drive,
                  title=path.name, text=f"{media.title()}: {path.name}\nDrive: {drive}", meta=record_meta)
    write_atomic(READ, json.dumps({"reader": READER, "files": files}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
