// Finished exports: spotting them in ~/Downloads, deciding where in corpus/imports/ each one goes, and
// moving it there. Browsers and Mail leave half-written files behind under temporary names, so a file
// counts only once its name is final and its size has stopped changing.

import fs from 'node:fs';
import path from 'node:path';
import { BY_ID } from '../shared/catalog.ts';
import { slug } from '../shared/status.ts';
import type { Identified } from '../shared/types.ts';

const PARTIAL = /\.(crdownload|download|part|partial|tmp|opdownload)$|\.partial\.mbox$|^Unconfirmed \d+/i;
const FILE_EXT = /\.(zip|vcf|mbox|vtt)$/i;
const EXPORT_NAMES = /^(takeout-|instagram-|facebook-|export-|twitter-|discord|package|my_spotify_data|complete_linkedindataexport|basic_linkedindataexport|export_|whatsapp chat)/i;

export function isPartial(name: string): boolean {
  return name.startsWith('.') || PARTIAL.test(name);
}

// Worth asking bridge.py about. Safari unzips "safe" downloads, so export-named folders count too.
export function isCandidate(name: string, isDir: boolean): boolean {
  if (isPartial(name)) return false;
  if (isDir) return /\.mbox$/i.test(name) || EXPORT_NAMES.test(name);
  return FILE_EXT.test(name) || /^(timeline|location-history)\.json$/i.test(name);
}

// The folder under corpus/imports/ a recognized file goes in.
export function importDirFor(kind: string, sourceId: string, f: Pick<Identified, 'export_id' | 'name'>, accountName?: string): string {
  if (kind === 'google_takeout' || kind === 'google_photos_drive') return f.export_id ? `takeout-${f.export_id}` : 'takeout';
  if (kind === 'mailbox') return slug(accountName || 'other_mail');
  return BY_ID[sourceId]?.importDir ?? sourceId;
}

export function uniquePath(p: string, exists: (p: string) => boolean = fs.existsSync): string {
  if (!exists(p)) return p;
  const dir = path.dirname(p);
  const name = path.basename(p);
  // "a.zip" -> "a (2).zip"; keep compound endings like .zip.zip and .partial.mbox together
  const m = name.match(/^(.*?)((?:\.[A-Za-z0-9]{1,5}){0,2})$/);
  const stem = m?.[1] || name;
  const ext = m?.[2] ?? '';
  for (let i = 2; ; i++) {
    const c = path.join(dir, `${stem} (${i})${ext}`);
    if (!exists(c)) return c;
  }
}

// rename(2) when the file and the corpus share a volume. From another volume (an external drive kept for
// big exports) the file is copied and the original left where it is.
export async function moveInto(src: string, destDir: string,
  rename: (a: string, b: string) => Promise<void> = fs.promises.rename): Promise<{ dest: string; copied: boolean }> {
  await fs.promises.mkdir(destDir, { recursive: true });
  const dest = uniquePath(path.join(destDir, path.basename(src)));
  try {
    await rename(src, dest);
    return { dest, copied: false };
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code !== 'EXDEV') throw e;
    await fs.promises.cp(src, dest, { recursive: true, errorOnExist: true, force: false });
    return { dest, copied: true };
  }
}

interface Seen {
  size: number;
  mtime: number;
  stableSince: number;
}

// Polls a folder (fs.watch on macOS misses some renames) and reports each finished candidate once. `also` adds
// files the name rules don't know, e.g. a .csv named after a service you asked for its data. While `active` says no
// (Watch Downloads is off), nothing is reported or marked as reported: what's there is reported once it says yes.
export class FolderWatcher {
  private seen = new Map<string, Seen>();
  private reported = new Set<string>();
  private timer: NodeJS.Timeout | null = null;
  private watcher: fs.FSWatcher | null = null;
  readonly dir: string;
  readonly settleMs: number;
  readonly intervalMs: number;
  private onReady: (p: string, size: number) => void;
  private also: (name: string, isDir: boolean) => boolean;
  private active: () => boolean;

  constructor(dir: string, onReady: (p: string, size: number) => void, settleMs = 4000, intervalMs = 3000,
    also: (name: string, isDir: boolean) => boolean = () => false, active: () => boolean = () => true) {
    this.dir = dir;
    this.onReady = onReady;
    this.settleMs = settleMs;
    this.intervalMs = intervalMs;
    this.also = also;
    this.active = active;
  }

  start() {
    this.scan();
    this.timer = setInterval(() => this.scan(), this.intervalMs);
    try {
      this.watcher = fs.watch(this.dir, () => this.scan());
    } catch {
      /* the folder may not exist yet; polling covers it */
    }
  }

  stop() {
    if (this.timer) clearInterval(this.timer);
    this.watcher?.close();
    this.timer = null;
    this.watcher = null;
  }

  forget(p: string) {
    this.reported.delete(p);
    this.seen.delete(p);
  }

  scan(now = Date.now()) {
    let names: fs.Dirent[];
    try {
      names = fs.readdirSync(this.dir, { withFileTypes: true });
    } catch {
      return;
    }
    const present = new Set<string>();
    const active = this.active();
    for (const d of names) {
      if (!isCandidate(d.name, d.isDirectory()) && (isPartial(d.name) || !this.also(d.name, d.isDirectory()))) continue;
      const p = path.join(this.dir, d.name);
      present.add(p);
      let st: fs.Stats;
      try {
        st = fs.statSync(p);
      } catch {
        continue;
      }
      const size = d.isDirectory() ? dirSize(p) : st.size;
      const mtime = st.mtimeMs;
      const prev = this.seen.get(p);
      if (!prev || prev.size !== size || prev.mtime !== mtime) {
        this.seen.set(p, { size, mtime, stableSince: now });
        continue;
      }
      if (active && !this.reported.has(p) && now - prev.stableSince >= this.settleMs) {
        this.reported.add(p);
        this.onReady(p, size);
      }
    }
    for (const p of this.seen.keys()) if (!present.has(p)) this.forget(p);
  }
}

export function dirSize(p: string): number {
  let total = 0;
  const stack = [p];
  while (stack.length) {
    const d = stack.pop()!;
    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(d, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const e of entries) {
      const full = path.join(d, e.name);
      if (e.isDirectory()) stack.push(full);
      else {
        try {
          total += fs.statSync(full).size;
        } catch {
          /* vanished */
        }
      }
    }
  }
  return total;
}
