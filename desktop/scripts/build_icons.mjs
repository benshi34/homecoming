// Brand logos for the services directory and the app's own web accounts, from Simple Icons (simple-icons on npm,
// CC0; notice in data/THIRD_PARTY.md). Writes data/service_icons.json: { slug or source id: [hex, svg path] }.
//
//   node scripts/build_icons.mjs        (after build_services.py, or after updating simple-icons)
//
// A service gets a logo when its name (or a part of it, "Amazon / Audible" -> "Audible") is a logo's title or one of
// its other names. Failing that, when its domain is the site the logo came from, no other logo claims that site, and
// the logo's name is the service's home site's or its first word: a site alone gave OpenAI the "OpenAI Gym" logo and
// Marvel the Marvel prototyping app's. Logos that carry their own licence instead of CC0 are left out. Services
// without one get a lettered tile in the app.

import fs from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const DATA = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../data');
const require = createRequire(import.meta.url);
const si = await import('simple-icons');
const meta = JSON.parse(fs.readFileSync(require.resolve('simple-icons/icons.json'), 'utf8'));

const norm = (t) => t.normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]/g, '');
const host = (u) => {
  try {
    return new URL(u).hostname.replace(/^www\./, '');
  } catch {
    return '';
  }
};
// example.co.uk -> example.co.uk, developer.spotify.com -> spotify.com
const site = (h) => {
  const p = h.split('.');
  return p.length > 2 && (p[p.length - 2].length <= 3 && p[p.length - 1].length === 2) ? p.slice(-3).join('.') : p.slice(-2).join('.');
};
// Sites that host many brands' logos (or brand guidelines for several products): never evidence for one brand.
const SHARED = new Set(['github.com', 'githubusercontent.com', 'gitlab.com', 'wikipedia.org', 'wikimedia.org', 'figma.com', 'google.com',
  'dribbble.com', 'behance.net', 'npmjs.com', 'bitbucket.org', 'twitter.com', 'x.com', 'facebook.com', 'youtube.com', 'apple.com',
  'microsoft.com', 'amazon.com', 'brandfetch.com', 'worldvectorlogo.com', 'seeklogo.com', 'svgporn.com', 'iconfinder.com']);

const icons = new Map(); // slug -> { hex, path }
for (const x of Object.values(si)) if (x && x.slug && x.path) icons.set(x.slug, { hex: x.hex, path: x.path });
const byName = new Map();
const bySite = new Map();
const titles = new Map(); // slug -> normalized title
for (const m of meta) {
  if (m.license || !icons.has(m.slug)) continue; // CC0 only
  titles.set(m.slug, norm(m.title));
  for (const n of [m.title, m.slug, ...(m.aliases?.aka ?? [])]) if (norm(n) && !byName.has(norm(n))) byName.set(norm(n), m.slug);
  const s = site(host(m.source ?? ''));
  if (s && !SHARED.has(s)) bySite.set(s, bySite.has(s) && bySite.get(s) !== m.slug ? null : m.slug); // null: more than one claims it
}

// The app's own web accounts and guided sources, by source id. No logo (LinkedIn, ChatGPT): they keep their glyph.
const BUILT_IN = { google_takeout: 'google', google_photos_drive: 'googlephotos', facebook: 'facebook', instagram: 'instagram',
  discord: 'discord', notion: 'notion', claude_ai: 'claude', x: 'x', reddit: 'reddit', spotify: 'spotify', whatsapp_chats: 'whatsapp',
  slack: 'slack', zoom: 'zoom' };

const out = {};
const how = { builtIn: 0, name: 0, site: 0 };
for (const [id, slug] of Object.entries(BUILT_IN)) {
  if (icons.has(slug)) {
    out[id] = [icons.get(slug).hex, icons.get(slug).path];
    how.builtIn++;
  }
}
const dir = JSON.parse(fs.readFileSync(path.join(DATA, 'services.json'), 'utf8'));
const viaSite = [];
const viaPart = [];
for (const e of dir) {
  const parts = [e.name, ...e.name.split(/\s*[/(),:]\s*|\s+-\s+|\s+\|\s+/)].map(norm).filter((n) => n.length >= 2);
  let slug = parts.map((n) => byName.get(n)).find(Boolean);
  if (slug) {
    how.name++;
    if (titles.get(slug) !== norm(e.name)) viaPart.push(`${e.name} -> ${slug}`);
  } else {
    // Its home site only: some entries list other brands' domains too (Classy lists gofundme.com).
    const words = new Set([norm(e.name.split(/\s+/)[0]), site(host(e.site ?? '')).split('.')[0]]);
    slug = e.domains.map((d) => bySite.get(site(d))).find((x) => x && words.has(titles.get(x)));
    if (slug) {
      how.site++;
      viaSite.push(`${e.name} -> ${slug}`);
    }
  }
  if (slug) out[e.slug] = [icons.get(slug).hex, icons.get(slug).path];
}
fs.writeFileSync(path.join(DATA, 'service_icons.json'), `${JSON.stringify(out)}\n`);
const size = fs.statSync(path.join(DATA, 'service_icons.json')).size;
console.log(`${Object.keys(out).length} logos (${how.builtIn} built-in accounts, ${how.name} services by name, ${how.site} by site) of ${dir.length} services, ${(size / 1024).toFixed(0)} KB`);
if (process.argv.includes('--show')) console.log(`by site:\n  ${viaSite.join('\n  ')}\nby another name or part of the name:\n  ${viaPart.join('\n  ')}`);
