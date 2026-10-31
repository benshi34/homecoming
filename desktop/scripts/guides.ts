// Writes the export guides (../guides/): a page for each source the app walks you through, from the same steps the app
// shows (shared/catalog.ts), with each step's picture and the source's recording where there is one. The app is the
// source of truth; run this after changing a step, or the guides test says the pages are out of date.
//
//     node scripts/guides.ts            write them
//     node scripts/guides.ts --check    say which page differs, and exit 1 (the unit test runs this)
import fs from 'node:fs';
import path from 'node:path';
import { CATALOG, type Source } from '../src/shared/catalog.ts';

const ROOT = path.resolve(import.meta.dirname, '../../guides');
const GROUPS: [Source['group'], string][] = [['setup', 'Before you start'], ['mac', 'On this Mac'], ['iphone', 'From your iPhone'],
  ['web', 'Exports from websites'], ['guided', 'Other accounts']];

const hours = (h: number) => (h < 24 ? `${h} hour${h === 1 ? '' : 's'}` : `${Math.round(h / 24)} day${h < 48 ? '' : 's'}`);

export function page(s: Source): string {
  const out = [`# ${s.name}`, '', s.blurb, ''];
  if (s.url) out.push(`Where: ${s.url}`, '');
  if (s.clip) out.push(`<video src="${s.clip}" controls muted width="640"></video>`, '');
  s.steps!.forEach((st, i) => {
    out.push(`${i + 1}. ${st.text}`);
    if (st.detail) out.push(`   ${st.detail}`);
    if (st.shot) out.push('', `   ![Step ${i + 1}](${st.shot})`);
    out.push('');
  });
  const when = [s.waitHours && `The download link usually comes in ${hours(s.waitHours[0])}, at most ${hours(s.waitHours[1])}.`,
    s.expiresDays && `It works for ${s.expiresDays} days.`, s.fileHint && `The file: \`${s.fileHint}\`.`].filter(Boolean);
  if (when.length) out.push(when.join(' '), '');
  if (s.knownGaps?.length) out.push('Not in it:', ...s.knownGaps.map((g) => `- ${g}`), '');
  return out.join('\n');
}

export function index(): string {
  const out = ['# Export guides', '', 'How to get each kind of data to Homecoming: the same steps the app shows, with a picture where the page has something to find.',
    'Written from shared/catalog.ts by desktop/scripts/guides.ts; edit the steps there, not here. Pictures and recordings are',
    'taken by guides/capture (see its README) and live beside each page.', ''];
  for (const [g, title] of GROUPS) {
    const here = CATALOG.filter((s) => s.group === g && s.steps?.length);
    if (!here.length) continue;
    out.push(`## ${title}`, '', ...here.map((s) => `- [${s.name}](${s.id}/README.md)${s.steps!.some((x) => x.shot) || s.clip ? '' : ' (no pictures yet)'}`), '');
  }
  return out.join('\n');
}

export function pages(): Record<string, string> {
  const all: Record<string, string> = { 'README.md': index() };
  for (const s of CATALOG.filter((x) => x.steps?.length)) all[`${s.id}/README.md`] = page(s);
  return all;
}

if (import.meta.main) {
  const check = process.argv.includes('--check');
  let stale = 0;
  for (const [rel, text] of Object.entries(pages())) {
    const f = path.join(ROOT, rel);
    const now = fs.existsSync(f) ? fs.readFileSync(f, 'utf8') : null;
    if (now === text) continue;
    if (check) {
      console.log(`out of date: guides/${rel}`);
      stale++;
    } else {
      fs.mkdirSync(path.dirname(f), { recursive: true });
      fs.writeFileSync(f, text);
    }
  }
  if (check && stale) process.exit(1);
}
