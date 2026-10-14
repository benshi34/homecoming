import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const DATA = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../data');
const icons = JSON.parse(fs.readFileSync(path.join(DATA, 'service_icons.json'), 'utf8')) as Record<string, [string, string]>;
const slugs = new Set((JSON.parse(fs.readFileSync(path.join(DATA, 'services.json'), 'utf8')) as { slug: string }[]).map((e) => e.slug));

test('logos for the well-known services and the built-in accounts, keyed by what the app looks them up by', () => {
  for (const id of ['google_takeout', 'facebook', 'instagram', 'spotify', 'reddit', 'discord']) assert.ok(icons[id], id);
  for (const slug of ['airbnb', 'duolingo', 'netflix', 'paypal', 'github', 'tumblr', 'wattpad', 'venmo']) assert.ok(icons[slug], slug);
  for (const [key, [hex, d]] of Object.entries(icons)) {
    assert.match(hex, /^[0-9A-F]{6}$/i, key);
    assert.match(d, /^[Mm]/, key);
    assert.ok(slugs.has(key) || !key.includes('-') || key.includes('_'), `${key} is a directory slug or a source id`);
  }
});

test('no logo by a guess that went wrong before (a site alone gave OpenAI the "OpenAI Gym" logo)', () => {
  assert.equal(icons['openai-chatgpt'], undefined);
  assert.equal(icons.weirdgloop, undefined, 'WeirdGloop is not League of Legends');
});

// What "Open" opens for each service in the directory (catalog.serviceSource: its export page, else its home page).
const dir = JSON.parse(fs.readFileSync(path.join(DATA, 'services.json'), 'utf8')) as { name: string; site?: string; export?: { url?: string } }[];
const DELETION = /delete|deletion|deactivat|close-?account|closeaccount|cancel-?account|remove-?account/i;
const GETTING = /download|export|copy|access|request|your-?data|my-?data|privacy|gdpr|dsar/i;

test('every service opens its export page, else its home page, and never a page for deleting the account', () => {
  for (const e of dir) {
    const url = e.export?.url ?? e.site;
    assert.ok(url, `${e.name} has somewhere to open`);
    if (!e.export?.url) assert.equal(new URL(url!).pathname, '/', `${e.name}: ${url} is a home page`);
    // An export page may mention deleting too ("download or delete your data").
    assert.ok(!DELETION.test(url!) || GETTING.test(url!), `${e.name}: ${url} looks like a page for deleting the account`);
  }
});
