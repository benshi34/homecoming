#!/usr/bin/env python3
"""Your library in one .zip file (Settings, or the app menu: Export Your Library…).

  export_library.py sizes <corpus>                  -> {"records": bytes, "media": bytes, "originals": bytes, "estimate": {...}, "phone_backup": bool}
  export_library.py write <corpus> <out.zip> <parts> -> "@progress {...}" lines on stderr, the result on stdout

<parts> is a comma list of records, media and originals. Records are always written: the database, the records again a
file per source, the event stream, the manifest, who you are and how unknown downloads are read. media is the photos and
attachments that came with your downloads; originals is each download as it came (imports/) and what was read from this
Mac as it was (raw/). Anything else in the folder (notes or research kept beside the library) isn't the library's, and
is left out; so are links out of it, like raw/iphone, the decrypted copy of your iPhone backup, which stays where it is.

The app holds its imports while this runs, so nothing in the library is written meanwhile. The database is copied
under a read lock all the same, in case anything else writes to it. The zip is written beside <out.zip> under a
temporary name and renamed once it's whole, so a stopped or failed export leaves nothing that looks finished.
"""

import json
import os
import signal
import sqlite3
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

PARTS = {
    'records': ['corpus.db', 'manifest.json', 'identity.json', 'normalized', 'stream', 'mappings'],
    'media': ['media'],
    'originals': ['imports', 'raw'],
}
SKIP = {'.DS_Store'}
# Already compressed: stored as they are, which is as small and much faster.
STORED = {'.jpg', '.jpeg', '.png', '.gif', '.heic', '.heif', '.webp', '.avif', '.mp4', '.mov', '.m4v', '.webm', '.m4a',
          '.mp3', '.aac', '.ogg', '.opus', '.flac', '.zip', '.gz', '.tgz', '.bz2', '.xz', '.7z', '.rar', '.zst'}
CHUNK = 1 << 20

README = """Your Homecoming library, exported {when}.

{contents}
Everything here came from your own accounts and this Mac. Keep it somewhere safe: it has your messages and email.
"""
ABOUT = {
    'corpus.db': 'corpus.db: every record in one SQLite database, one row per message, email, post, visit or anything else in its records table. Any SQLite app opens it (DB Browser for SQLite, or sqlite3 in Terminal).',
    'normalized': 'normalized/: the same records, a file per source, one JSON object per line.',
    'stream': 'stream/: what happened, in order, a file per month.',
    'manifest.json': 'manifest.json: what was read, from where, and when.',
    'identity.json': 'identity.json: who you are to the library: your names, email addresses, usernames and numbers.',
    'mappings': 'mappings/: how the downloads Homecoming didn\'t know were read.',
    'media': 'media/: the photos and attachments that came with your downloads.',
    'imports': 'imports/: each service\'s download, as it came.',
    'raw': 'raw/: what was read from this Mac (Messages, Notes, Calendar, Chrome and the rest), as it was.',
}


def files_of(corpus: Path, parts: list[str]):
    """(path, name in the zip) for every file the parts hold, in order; links out of the library left out."""
    for part in parts:
        for top in PARTS[part]:
            p = corpus / top
            if p.is_symlink() or not p.exists():
                continue
            if p.is_file():
                yield p, top
                continue
            for root, dirs, names in os.walk(p):
                r = Path(root)
                dirs[:] = sorted(d for d in dirs if not (r / d).is_symlink())
                for n in sorted(names):
                    f = r / n
                    if n in SKIP or f.is_symlink() or not f.is_file():
                        continue
                    yield f, f.relative_to(corpus).as_posix()


def zipped(f: Path) -> int:
    """About what a file takes in the zip, erring large: text (records, email) at least halves; photos and zips don't."""
    n = f.stat().st_size
    return n if f.suffix.lower() in STORED else n // 2


def sizes(corpus: Path) -> dict:
    out: dict = {part: sum(f.stat().st_size for f, _ in files_of(corpus, [part])) for part in PARTS}
    out['estimate'] = {part: sum(zipped(f) for f, _ in files_of(corpus, [part])) for part in PARTS}
    out['phone_backup'] = (corpus / 'raw' / 'iphone').is_symlink()  # the decrypted copy, which is left out
    return out


def progress(**kw):
    sys.stderr.write('@progress ' + json.dumps(kw) + '\n')
    sys.stderr.flush()


class Stopped(Exception):
    pass


def write(corpus: Path, out: Path, parts: list[str]) -> dict:
    parts = ['records'] + [p for p in parts if p in PARTS and p != 'records']
    todo = list(files_of(corpus, parts))
    total = sum(f.stat().st_size for f, _ in todo)
    est = sum(zipped(f) for f, _ in todo)
    free = free_bytes(out.parent)
    if free < est + (256 << 20):
        return {'ok': False, 'error': 'space', 'need': est, 'free': free}
    root = out.stem
    tmp = out.with_name(f'.{out.name}.partial')
    done = 0
    last = 0.0

    def stop(*_):
        raise Stopped()
    signal.signal(signal.SIGTERM, stop)
    lock = db_lock(corpus / 'corpus.db')
    try:
        with zipfile.ZipFile(tmp, 'w', allowZip64=True, strict_timestamps=False) as z:
            for f, name in todo:
                info = zipfile.ZipInfo.from_file(f, f'{root}/{name}', strict_timestamps=False)
                stored = f.suffix.lower() in STORED
                info.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
                if not stored:
                    setattr(info, 'compress_level' if hasattr(info, 'compress_level') else '_compresslevel', 5)
                with open(f, 'rb') as src, z.open(info, 'w', force_zip64=info.file_size > (1 << 30)) as dst:
                    while chunk := src.read(CHUNK):
                        dst.write(chunk)
                        done += len(chunk)
                        now = time.monotonic()
                        if now - last > 0.25:
                            last = now
                            progress(done=done, total=total, file=name)
                if name == 'corpus.db' and lock:
                    lock.rollback()  # copied: imports may write it again
                    lock.close()
                    lock = None
            readme = README.format(when=datetime.now().strftime('%-d %B %Y at %-I:%M %p').replace('AM', 'am').replace('PM', 'pm'),
                                   contents='\n'.join(ABOUT[t] for p in parts for t in PARTS[p] if t in ABOUT and (corpus / t).exists() and not (corpus / t).is_symlink()) + '\n')
            z.writestr(f'{root}/README.txt', readme)
        os.replace(tmp, out)
    except Stopped:
        tmp.unlink(missing_ok=True)
        return {'ok': False, 'error': 'stopped'}
    except OSError as e:
        tmp.unlink(missing_ok=True)
        if e.errno == 28:  # the drive filled up after all
            return {'ok': False, 'error': 'space', 'need': est, 'free': free_bytes(out.parent)}
        return {'ok': False, 'error': str(e)}
    finally:
        if lock:
            lock.close()
    progress(done=total, total=total, file='')
    return {'ok': True, 'path': str(out), 'bytes': out.stat().st_size, 'files': len(todo) + 1, 'read': total}


def free_bytes(folder: Path) -> int:
    st = os.statvfs(folder)
    return st.f_bavail * st.f_frsize


def db_lock(db: Path):
    """A read transaction on corpus.db: in its journal mode a writer waits until it ends, so the copy is whole."""
    if not db.exists():
        return None
    con = sqlite3.connect(db, timeout=120, isolation_level=None)
    if con.execute('PRAGMA journal_mode').fetchone()[0].lower() == 'wal':
        con.close()  # the lock wouldn't hold its writes back; the app's databases don't use WAL, and imports are held
        return None
    con.execute('BEGIN')
    con.execute('SELECT count(*) FROM sqlite_master').fetchone()
    return con


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == 'sizes':
        print(json.dumps(sizes(Path(argv[1]))))
        return 0
    if len(argv) >= 4 and argv[0] == 'write':
        print(json.dumps(write(Path(argv[1]), Path(argv[2]), argv[3].split(','))))
        return 0
    sys.stderr.write(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
