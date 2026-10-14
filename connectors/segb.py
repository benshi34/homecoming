"""Reader for Apple Biome SEGB stream files (~/Library/Biome/streams/...).

v2 (macOS 14+): "SEGB" at offset 0, int32 entry count at 4, 32-byte header; records are
    crc32 + 4 bytes + protobuf, 4-byte aligned; a trailer of 16-byte entries
    (int32 end offset relative to 32, int32 state, float64 time) is stored backwards
    from the end of the file.
v1 (macOS 12-13): "SEGB" at offset 52, 56-byte header; each record has a 32-byte header
    (int32 length, int32 state, float64 time, float64 time, crc32, 4 bytes), 8-byte aligned.
State 1 = live record; other states are deleted/tombstoned.
"""

import struct
from pathlib import Path

from apple_notes import _fields


def records(path):
    """Yield (time, protobuf_bytes) for live records in one SEGB file."""
    b = Path(path).read_bytes()
    if b[:4] == b"SEGB":
        n = struct.unpack_from("<i", b, 4)[0]
        start = 32
        for i in range(n):
            off = len(b) - 16 * (i + 1)
            if off < 32:
                return
            end_rel, state, ts = struct.unpack_from("<iid", b, off)
            end = 32 + end_rel
            if state == 1 and start + 8 < end <= len(b):
                yield ts, b[start + 8:end]
            start = (end + 3) & ~3
    elif b[52:56] == b"SEGB":
        end_of_data = struct.unpack_from("<i", b, 0)[0]
        pos = 56
        while pos + 32 <= min(end_of_data, len(b)):
            length, state, ts, _ts2 = struct.unpack_from("<iidd", b, pos)
            if length <= 0:
                break
            if state == 1:
                yield ts, b[pos + 32:pos + 32 + length]
            pos = (pos + 32 + length + 7) & ~7


def stream_files(stream_dir):
    """Yield (device_id or 'local', file) for a Biome stream directory."""
    stream_dir = Path(stream_dir)
    for f in sorted((stream_dir / "local").glob("[0-9]*")):
        yield "local", f
    for d in sorted((stream_dir / "remote").glob("*")):
        for f in sorted(d.glob("[0-9]*")):
            yield d.name, f


def decode(buf):
    """Protobuf -> {field: value} (last value wins; strings decoded when valid UTF-8)."""
    out = {}
    try:
        for f, wt, v in _fields(buf):
            if wt == 2:
                try:
                    v = v.decode("utf-8")
                except UnicodeDecodeError:
                    pass
            elif wt == 1:
                v = struct.unpack("<d", v)[0]
            out[f] = v
    except (IndexError, ValueError):
        pass
    return out
