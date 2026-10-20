// Which Homecoming this is, and what's new in each version. The version is package.json's; the commit and the day it
// was built are written into dist/build.json by build.mjs. What's new is CHANGELOG.md at the top of the repository,
// copied into the app when it's built, so nothing is looked up online. Each version is a "## 0.3.0" heading, then a
// line or two of words and "- " bullets, newest first. The first time a newer version opens, it shows what's new since
// the one that last ran (main.ts).

import { day } from './format.ts';
import type { BuildInfo } from './types.ts';

export interface Release { version: string; text: string[]; bullets: string[] }

// What's said after the version, in About Homecoming and General: "a1b2c3d, built Oct 20, 2026". A copy from Download
// ZIP has no commit; one run from Terminal says so.
export function buildNote(b: BuildInfo): string {
  return [b.commit && (b.modified ? `${b.commit} with changes` : b.commit), b.date && `built ${day(b.date)}`, b.source && 'run from source']
    .filter(Boolean).join(', ');
}

// "0.10.0" is newer than "0.9.2": compared number by number. Negative: a is older.
export function compareVersions(a: string, b: string): number {
  const pa = a.split('.').map((n) => parseInt(n, 10) || 0);
  const pb = b.split('.').map((n) => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] ?? 0) - (pb[i] ?? 0);
    if (d) return d;
  }
  return 0;
}

// The versions in CHANGELOG.md, as written (newest first). A bullet goes on over the indented lines under it, and a
// paragraph over the lines up to a blank one.
export function parseChangelog(md: string): Release[] {
  const out: Release[] = [];
  let cur: Release | null = null;
  let inside: 'bullet' | 'text' | null = null;
  for (const line of md.replace(/\r\n?/g, '\n').split('\n')) {
    const h = /^##\s+v?(\d+(?:\.\d+)*)\b/.exec(line);
    if (h) {
      out.push((cur = { version: h[1], text: [], bullets: [] }));
      inside = null;
    } else if (!cur || /^#/.test(line)) {
      continue;
    } else if (/^\s*[-*]\s+/.test(line)) {
      cur.bullets.push(line.replace(/^\s*[-*]\s+/, '').trim());
      inside = 'bullet';
    } else if (!line.trim()) {
      inside = null;
    } else if (inside === 'bullet' && /^\s/.test(line)) {
      cur.bullets[cur.bullets.length - 1] += ` ${line.trim()}`;
    } else if (inside === 'text') {
      cur.text[cur.text.length - 1] += ` ${line.trim()}`;
    } else {
      cur.text.push(line.trim());
      inside = 'text';
    }
  }
  return out;
}

// What's new for someone who last ran `seen` and now has `current`: every version after the one they had, up to this
// one. Not known (it ran before versions were kept): this version's alone.
export function whatsNewSince(releases: Release[], current: string, seen?: string): Release[] {
  return releases.filter((r) => compareVersions(r.version, current) <= 0
    && (seen ? compareVersions(r.version, seen) > 0 : compareVersions(r.version, current) === 0));
}
