// Finished exports: spotting them in ~/Downloads, deciding where in corpus/imports/ each one goes, and
// moving it there. Browsers and Mail leave half-written files behind under temporary names, so a file
// counts only once its name is final and its size has stopped changing.

import fs from 'node:fs';
import path from 'node:path';
import { BY_ID } from '../shared/catalog.ts';
import { mailSource } from '../shared/status.ts';
import type { Identified } from '../shared/types.ts';

const PARTIAL = /\.(crdownload|download|part|partial|tmp|opdownload)$|\.partial\.mbox$|^Unconfirmed \d+/i;
const STILL_WRITING = ['.part', '.crdownload', '.download'];
const FILE_EXT = /\.(zip|vcf|mbox|olm|vtt|tgz|tar\.gz)$/i;
// Folders: what an export's zip is called, or (unzipped by Safari) the folder at its top ("Takeout", "Spotify Account Data").
const EXPORT_NAMES = /^(takeout\b|takeout-|instagram-|facebook-|export-|twitter-|discord|package|my_spotify_data|spotify (account data|extended streaming history)|mydata$|complete_linkedindataexport|basic_linkedindataexport|export_|whatsapp chat|dataexport_|chatexport_)/i;
// What's at the top of an unzipped export whose folder is named after nothing in particular (ChatGPT's "<hash>-<date>", Claude's
// "data-<date>", a Slack workspace's export): looked for one level down, so other folders cost a directory listing.
const EXPORT_INSIDE = ['conversations.json', 'your_instagram_activity', 'your_facebook_activity', 'channels.json', 'Takeout', 'StreamingHistory_music_0.json',
  'Connections.csv', 'tweets.js', 'account.js'];
export function looksLikeExport(dir: string): boolean {
  let names: string[];
  try {
    names = fs.readdirSync(dir);
  } catch {
    return false;
  }
  if (names.some((n) => EXPORT_INSIDE.includes(n) || /^Streaming_History|^StreamingHistory/.test(n))) return true;
  return names.includes('data') && (() => {
    try {
      return fs.readdirSync(path.join(dir, 'data')).some((n) => n === 'tweets.js' || n === 'account.js');
    } catch {
      return false;
    }
  })();
}

// What Export Your Library writes ("Homecoming Library 2026-10-15.zip"): yours, not an export to import, if it's saved here.
const OUR_EXPORT = /^Homecoming Library\b.*\.zip$/i;

export function isPartial(name: string): boolean {
  return name.startsWith('.') || PARTIAL.test(name);
}

// Worth asking bridge.py about. Safari unzips "safe" downloads, so export-named folders count too.
export function isCandidate(name: string, isDir: boolean): boolean {
  if (isPartial(name) || OUR_EXPORT.test(name)) return false;
  if (isDir) return /\.mbox$/i.test(name) || EXPORT_NAMES.test(name);
  return FILE_EXT.test(name) || /^(timeline|location-history)\.json$/i.test(name);
}

// The folder under corpus/imports/ a recognized file goes in.
export function importDirFor(kind: string, sourceId: string, f: Pick<Identified, 'export_id' | 'name'>, accountName?: string): string {
  if (kind === 'google_takeout' || kind === 'google_photos_drive') return f.export_id ? `takeout-${f.export_id}` : 'takeout';
  if (kind === 'mailbox') return mailSource(accountName);
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
    // Copied under a name imports.py leaves alone (.partial: still arriving), then renamed: an import that runs meanwhile
    // doesn't read half of it.
    const part = `${dest}.partial`;
    await fs.promises.rm(part, { recursive: true, force: true });
    await fs.promises.cp(src, part, { recursive: true, errorOnExist: true, force: false });
    await fs.promises.rename(part, dest);
    return { dest, copied: true };
  }
}

interface Seen {
  size: number;
  mtime: number;
  stableSince: number;
}

// fs.watch fires for every write while a browser downloads: one scan once they pause this long (polling covers the rest).
const QUIET_MS = 500;

// Polls a folder (fs.watch on macOS misses some renames) and reports each finished candidate once. `also` adds
// files the name rules don't know, e.g. a .csv named after a service you asked for its data. While `active` says no
// (Watch Downloads is off), nothing is reported or marked as reported: what's there is reported once it says yes.
// Folders are sized off the main thread, and one already reported isn't sized again (nothing more comes of it).
export class FolderWatcher {
  private seen = new Map<string, Seen>();
  private reported = new Set<string>();
  private timer: NodeJS.Timeout | null = null;
  private quiet: NodeJS.Timeout | null = null;
  private watcher: fs.FSWatcher | null = null;
  private scanning: Promise<void> | null = null;
  readonly dir: string;
  readonly settleMs: number;
  readonly intervalMs: number;
  private onReady: (p: string, size: number) => void;
  private also: (name: string, isDir: boolean) => boolean;
  private active: () => boolean;
  sizeOf: (dir: string) => Promise<number> = dirSize; // tests count the folders sized

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
    void this.scan();
    this.timer = setInterval(() => void this.scan(), this.intervalMs);
    try {
      this.watcher = fs.watch(this.dir, () => {
        if (this.quiet) clearTimeout(this.quiet);
        this.quiet = setTimeout(() => {
          this.quiet = null;
          void this.scan();
        }, QUIET_MS);
      });
    } catch {
      /* the folder may not exist yet; polling covers it */
    }
  }

  stop() {
    if (this.timer) clearInterval(this.timer);
    if (this.quiet) clearTimeout(this.quiet);
    this.watcher?.close();
    this.timer = null;
    this.quiet = null;
    this.watcher = null;
  }

  // A folder named after nothing, looked inside once (again only if it changes): an unzipped export, or not.
  private inside = new Map<string, { mtime: number; is: boolean }>();
  private exportInside(p: string): boolean {
    let mtime: number;
    try {
      mtime = fs.statSync(p).mtimeMs;
    } catch {
      return false;
    }
    const was = this.inside.get(p);
    if (was && was.mtime === mtime) return was.is;
    const is = !isPartial(path.basename(p)) && looksLikeExport(p);
    this.inside.set(p, { mtime, is });
    return is;
  }

  forget(p: string) {
    this.reported.delete(p);
    this.seen.delete(p);
  }

  // One scan at a time: asked again meanwhile, the one under way is the answer (the next tick looks again).
  scan(now = Date.now()): Promise<void> {
    this.scanning ??= this.scanOnce(now).finally(() => (this.scanning = null));
    return this.scanning;
  }

  private async scanOnce(now: number) {
    let names: fs.Dirent[];
    try {
      names = await fs.promises.readdir(this.dir, { withFileTypes: true });
    } catch {
      return;
    }
    const present = new Set<string>();
    const active = this.active();
    const here = new Set(names.map((d) => d.name));
    for (const d of names) {
      const p = path.join(this.dir, d.name);
      if (!isCandidate(d.name, d.isDirectory()) && (isPartial(d.name) || !this.also(d.name, d.isDirectory())) && !(d.isDirectory() && this.exportInside(p))) continue;
      // Firefox writes a download to <name>.part, beside an empty file under its final name: not finished while that's there.
      if (!d.isDirectory() && STILL_WRITING.some((x) => here.has(d.name + x))) continue;
      present.add(p);
      const was = this.reported.has(p);
      if (was && d.isDirectory()) continue;
      let st: fs.Stats;
      try {
        st = await fs.promises.stat(p);
      } catch {
        continue;
      }
      if (!d.isDirectory() && st.size === 0) continue; // nothing in it yet
      const size = d.isDirectory() ? await this.sizeOf(p) : st.size;
      const mtime = st.mtimeMs;
      const prev = this.seen.get(p);
      if (was) {
        // A file that changed after it was reported (Firefox's placeholder, filled in at the end) is looked at again once it settles.
        if (prev && prev.size === size && prev.mtime === mtime) continue;
        this.reported.delete(p);
      }
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

// Everything in a folder, in bytes: read a few dozen entries at a time, so a big unzipped export doesn't hold up the app.
export async function dirSize(p: string): Promise<number> {
  let total = 0;
  const stack = [p];
  while (stack.length) {
    const d = stack.pop()!;
    let entries: fs.Dirent[];
    try {
      entries = await fs.promises.readdir(d, { withFileTypes: true });
    } catch {
      continue;
    }
    const files: string[] = [];
    for (const e of entries) {
      const full = path.join(d, e.name);
      if (e.isDirectory()) stack.push(full);
      else files.push(full);
    }
    for (let i = 0; i < files.length; i += 64) {
      const sizes = await Promise.all(files.slice(i, i + 64).map((f) => fs.promises.stat(f).then((s) => s.size, () => 0))); // 0: vanished
      for (const n of sizes) total += n;
    }
  }
  return total;
}
