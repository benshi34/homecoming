"""Loose media on external drives: metadata, filtering, caching and persistence."""

import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CONNECTORS = Path(__file__).resolve().parents[1]
MIN_IMAGE_BYTES = 20 * 1024


def _entry(tag, typ, count, value, endian="<"):
    size = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8}[typ] * count
    if size <= 4:
        if typ == 2:
            raw = bytes(value).ljust(4, b"\0")
        elif typ == 3:
            raw = struct.pack(endian + "H", value).ljust(4, b"\0")
        elif typ == 4:
            raw = struct.pack(endian + "I", value)
        else:
            raw = bytes(value).ljust(4, b"\0")
    else:
        raw = struct.pack(endian + "I", value)
    return struct.pack(endian + "HHI", tag, typ, count) + raw


def jpeg_with_exif(size=24 * 1024):
    """A small valid JPEG carrying DateTimeOriginal, GPS, make/model and dimensions."""
    endian = "<"
    make, model, date = b"Acme\0", b"Camera 1\0", b"2024:05:06 07:08:09\0"
    ifd0_size = 2 + 4 * 12 + 4
    exif_size = 2 + 12 + 4
    gps_size = 2 + 4 * 12 + 4
    rationals_size = 6 * 8
    data_start = 8 + ifd0_size + exif_size + gps_size
    lat_off = data_start
    lon_off = lat_off + 24
    make_off = lon_off + 24
    model_off = make_off + len(make)
    date_off = model_off + len(model)
    exif_off = 8 + ifd0_size
    gps_off = exif_off + exif_size
    ifd0 = [
        _entry(0x010F, 2, len(make), make_off), _entry(0x0110, 2, len(model), model_off),
        _entry(0x8769, 4, 1, exif_off), _entry(0x8825, 4, 1, gps_off),
    ]
    exif = [_entry(0x9003, 2, len(date), date_off)]
    gps = [_entry(1, 2, 2, b"N\0"), _entry(2, 5, 3, lat_off), _entry(3, 2, 2, b"W\0"), _entry(4, 5, 3, lon_off)]
    tiff = (b"II*\0" + struct.pack("<I", 8) + struct.pack("<H", len(ifd0)) + b"".join(ifd0) + b"\0" * 4
            + struct.pack("<H", len(exif)) + b"".join(exif) + b"\0" * 4
            + struct.pack("<H", len(gps)) + b"".join(gps) + b"\0" * 4
            + struct.pack("<IIIIII", 37, 1, 46, 1, 30, 1)
            + struct.pack("<IIIIII", 122, 1, 25, 1, 0, 1) + make + model + date)
    app1 = b"Exif\0\0" + tiff
    jpeg = (b"\xff\xd8" + b"\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1
            + b"\xff\xc0" + struct.pack(">H", 17) + b"\x08" + struct.pack(">HH", 480, 640)
            + b"\x01\x11\0" * 3 + b"\xff\xd9")
    return jpeg + b"\xff\xe2" + struct.pack(">H", max(2, size - len(jpeg))) + b"x" * max(0, size - len(jpeg) - 2)


def box(kind, payload):
    return struct.pack(">I", len(payload) + 8) + kind + payload


def mp4_fixture():
    creation = 2_082_844_800 + 1_700_000_000
    mvhd = b"\0\0\0\0" + struct.pack(">IIII", creation, 0, 1000, 12500) + b"\0" * 80
    return box(b"moov", box(b"mvhd", mvhd))


def heic_fixture():
    # ispe is normally under meta/iprp/ipco; this minimal tree is enough for the parser and mirrors the box shape.
    ispe = box(b"ispe", b"\0\0\0\0" + struct.pack(">II", 321, 123))
    return (box(b"meta", b"\0\0\0\0" + box(b"iprp", box(b"ipco", ispe)))
            + b"\0" * (MIN_IMAGE_BYTES + 1))


class DrivePhotoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.home, self.corpus, self.volumes = root / "home", root / "corpus", root / "volumes"
        self.home.mkdir()
        self.corpus.mkdir()
        self.volumes.mkdir()
        self.addCleanup(self.tmp.cleanup)

    def run_connector(self, extra="", info=True):
        drive = self.volumes / "Camera Card"
        on = bool(info)  # whatever the card is called, diskutil says it's the same volume
        code = (
            "import drive_photos, documents; from pathlib import Path; "
            f"documents.VOLUMES=Path({str(self.volumes)!r}); "
            f"documents._mounted_fs_types=lambda: {{}}; documents._backup_mounts=lambda: set(); "
            f"documents._diskutil_info=lambda p: {{'VolumeName': Path(p).name, 'VolumeUUID': 'camera-id'}} if {on!r} else {{}}; "
            f"{extra}drive_photos.main()"
        )
        env = {**os.environ, "HOME": str(self.home), "CORPUS_DIR": str(self.corpus), "TZ": "America/Los_Angeles",
               "UMP_VOLUMES": str(self.volumes)}
        return subprocess.run([sys.executable, "-c", code], cwd=CONNECTORS, env=env, capture_output=True, text=True, timeout=120)

    def records(self):
        p = self.corpus / "normalized/drive_photos.jsonl"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def test_date_gps_camera_size_and_video_duration(self):
        drive = self.volumes / "Camera Card"
        drive.mkdir()
        (drive / "IMG_0001.JPG").write_bytes(jpeg_with_exif())
        (drive / "CLIP.MP4").write_bytes(mp4_fixture())
        (drive / "still.HEIC").write_bytes(heic_fixture())
        result = self.run_connector()
        self.assertEqual(result.returncode, 0, result.stderr)
        by_name = {r["title"]: r for r in self.records()}
        photo = by_name["IMG_0001.JPG"]["meta"]
        self.assertEqual(by_name["IMG_0001.JPG"]["ts"], "2024-05-06T14:08:09Z")  # the camera's clock, read as this Mac's zone
        self.assertAlmostEqual(photo["lat"], 37 + 46 / 60 + 30 / 3600, places=5)
        self.assertAlmostEqual(photo["lon"], -(122 + 25 / 60), places=5)
        self.assertEqual((photo["camera"], photo["width"], photo["height"]), ("Acme Camera 1", 640, 480))
        self.assertEqual(by_name["CLIP.MP4"]["meta"]["seconds"], 12)
        self.assertEqual((by_name["still.HEIC"]["meta"]["width"], by_name["still.HEIC"]["meta"]["height"]), (321, 123))

    def test_file_time_and_tiny_icon_are_handled(self):
        drive = self.volumes / "Camera Card"
        drive.mkdir()
        (drive / "Trip").mkdir()
        (drive / "Trip/IMG_0001.JPG").write_bytes(jpeg_with_exif())
        no_exif = drive / "Trip/plain.jpg"  # lost its EXIF, but sits with a camera's pictures
        no_exif.write_bytes(b"\xff\xd8\xff\xd9" + b"x" * (MIN_IMAGE_BYTES + 10))
        os.utime(no_exif, (1_600_000_000, 1_600_000_000))
        (drive / "Trip/icon.png").write_bytes(b"tiny")
        (drive / "app-images").mkdir()  # an app's images: no camera, no camera's pictures beside them
        (drive / "app-images/banner.jpg").write_bytes(b"\xff\xd8\xff\xd9" + b"x" * (MIN_IMAGE_BYTES + 10))
        (drive / "DCIM/100CANON").mkdir(parents=True)  # a camera card's folder, whatever's in it
        (drive / "DCIM/100CANON/IMG_9999.JPG").write_bytes(b"\xff\xd8\xff\xd9" + b"x" * (MIN_IMAGE_BYTES + 10))
        result = self.run_connector()
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [r for r in self.records() if r["title"] != "IMG_0001.JPG"]
        self.assertEqual(sorted(r["title"] for r in rows), ["IMG_9999.JPG", "plain.jpg"])
        rows = [r for r in rows if r["title"] == "plain.jpg"]
        self.assertEqual(rows[0]["meta"]["time_from"], "file")
        self.assertEqual(rows[0]["ts"], "2020-09-13T12:26:40Z")

    def test_noindex_repositories_and_web_assets_are_skipped(self):
        drive = self.volumes / "Camera Card"
        drive.mkdir()
        (drive / "ok.jpg").write_bytes(jpeg_with_exif())
        (drive / "cache.noindex").mkdir()
        (drive / "cache.noindex/hidden.jpg").write_bytes(jpeg_with_exif())
        (drive / "site").mkdir()
        (drive / "site/package.json").write_text("{}")
        (drive / "site/asset.jpg").write_bytes(jpeg_with_exif())
        (drive / "repo/.git").mkdir(parents=True)
        (drive / "repo/code.jpg").write_bytes(jpeg_with_exif())
        (drive / "Lisbon gallery").mkdir()  # a photo-gallery export: its index.html doesn't make it code
        (drive / "Lisbon gallery/index.html").write_text("<img src=tram.jpg>")
        (drive / "Lisbon gallery/tram.jpg").write_bytes(jpeg_with_exif())
        result = self.run_connector()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sorted(r["title"] for r in self.records()), ["ok.jpg", "tram.jpg"])

    def test_png_size_is_read(self):
        import struct, zlib
        drive = self.volumes / "Camera Card"
        drive.mkdir()
        ihdr = struct.pack(">IIBBBBB", 640, 480, 8, 2, 0, 0, 0)
        png = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr))
        (drive / "IMG_0001.JPG").write_bytes(jpeg_with_exif())
        (drive / "screen.png").write_bytes(png + b"\0" * 30000)  # over the icon floor, beside a camera's picture
        result = self.run_connector()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([(r["meta"]["width"], r["meta"]["height"]) for r in self.records() if r["title"] == "screen.png"], [(640, 480)])

    def test_renamed_drive_keeps_its_records(self):
        drive = self.volumes / "Camera Card"
        drive.mkdir()
        (drive / "DCIM").mkdir()
        (drive / "DCIM/IMG_0001.JPG").write_bytes(jpeg_with_exif())
        self.assertEqual(self.run_connector().returncode, 0)
        drive.rename(self.volumes / "Renamed Card")
        self.assertEqual(self.run_connector().returncode, 0)
        self.assertEqual([r["id"] for r in self.records()], ["drive:camera-id/DCIM/IMG_0001.JPG"])

    def test_cache_hit_does_not_parse_again(self):
        drive = self.volumes / "Camera Card"
        drive.mkdir()
        (drive / "cached.jpg").write_bytes(jpeg_with_exif())
        self.assertEqual(self.run_connector().returncode, 0)
        marker = Path(self.tmp.name) / "parsed"
        extra = (
            f"orig=drive_photos._metadata; "
            f"drive_photos._metadata=lambda p,s: (Path({str(marker)!r}).write_text('parsed'), orig(p,s))[1]; "
        )
        result = self.run_connector(extra)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.exists())

    def test_also_in_photos_and_unplugged_records_stay(self):
        normalized = self.corpus / "normalized"
        normalized.mkdir()
        (normalized / "photos.jsonl").write_text(json.dumps({"id": "p", "ts": "2024-05-06T14:08:09Z", "title": "IMG_0001.JPG",
                                                               "meta": {"filename": "IMG_0001.JPG"}}) + "\n")
        drive = self.volumes / "Camera Card"
        drive.mkdir()
        (drive / "IMG_0001.JPG").write_bytes(jpeg_with_exif())
        self.assertEqual(self.run_connector().returncode, 0)
        self.assertEqual(self.records()[0]["meta"]["also_in"], "photos")
        (drive / "IMG_0001.JPG").unlink()
        drive.rmdir()
        result = self.run_connector(info=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.records()), 1)


if __name__ == "__main__":
    unittest.main()
