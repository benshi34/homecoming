import assert from 'node:assert/strict';
import { afterEach, test } from 'node:test';
import { BY_ID, CATALOG, refreshServices, reservedFolders, SERVICE_WAIT, serviceKey, serviceSource, setServices } from '../../src/shared/catalog.ts';
import { accountChoices } from '../../src/shared/progress.ts';
import type { ServiceEntry } from '../../src/shared/types.ts';
import { actionIds, hoursAgo, state, stats, view, views } from './helpers.ts';

const wattpad: ServiceEntry = { id: 'svc_wattpad', slug: 'wattpad', name: 'Wattpad', folder: 'wattpad', domains: ['wattpad.com'],
  site: 'https://www.wattpad.com', email: 'privacy@wattpad.example', addedAt: hoursAgo(5), from: 'you' };
const builtIns = CATALOG.length;

afterEach(() => setServices([]));

test('a service you add becomes a web source that keeps whatever its download holds', () => {
  const s = serviceSource(wattpad);
  assert.equal(s.group, 'web');
  assert.equal(s.custom, 'you');
  assert.deepEqual(s.produces, ['wattpad', 'wattpad_other', 'wattpad_files'], 'read with a mapping, else by the catch-alls');
  assert.equal(s.importDir, 'wattpad');
  assert.deepEqual(s.waitHours, SERVICE_WAIT);
  assert.equal(s.url, 'https://www.wattpad.com', 'no export page known: its home page');
  const legacy = { ...wattpad, site: undefined, account: 'https://www.wattpad.com/account/delete' } as ServiceEntry;
  assert.equal(serviceSource(legacy).url, 'https://wattpad.com', "never the old account link, which was often the page that deletes the account");
  assert.match(s.steps![0].text, /Download your data/);
  assert.match(s.steps![1].detail!, /privacy@wattpad\.example/);
  const known = serviceSource({ ...wattpad, url: 'https://support.example/export', notes: 'Choose JSON.' });
  assert.equal(known.url, 'https://support.example/export');
  assert.equal(known.steps![0].text, 'Choose JSON.');
  assert.equal(serviceKey('Amazon-Audible'), 'amazon_audible');
});

test('an added service picks up a fixed link and steps from the directory at launch', () => {
  const old = { ...wattpad, url: 'https://old.example/form', notes: 'Old steps.' };
  const dir = [{ slug: 'wattpad', name: 'Wattpad', domains: ['wattpad.com'], export: { url: 'https://wattpad.example/export', notes: 'New steps.' },
    privacy_email: 'privacy@wattpad.example' }];
  const [fresh] = refreshServices([old], dir)!;
  assert.equal(fresh.url, 'https://wattpad.example/export');
  assert.equal(fresh.notes, 'New steps.');
  assert.equal(fresh.email, 'privacy@wattpad.example');
  assert.equal(fresh.addedAt, old.addedAt, 'still the same entry');
  assert.equal(refreshServices([fresh], dir), null, 'nothing to save once it matches');
  const sender = { ...wattpad, domains: ['wattpad-fanclub.example'], url: undefined, notes: undefined };
  assert.equal(refreshServices([sender], dir), null, 'a mail sender that only shares the slug is left alone');
  assert.equal(refreshServices([old], []), null, 'gone from the directory: kept as it was');
});

test('setServices adds and removes them, and leaves the built-in sources alone', () => {
  setServices([wattpad]);
  assert.equal(CATALOG.length, builtIns + 1);
  assert.equal(BY_ID.svc_wattpad.name, 'Wattpad');
  setServices([]);
  assert.equal(CATALOG.length, builtIns);
  assert.equal(BY_ID.svc_wattpad, undefined);
  assert.ok(reservedFolders().has('linkedin') && reservedFolders().has('whatsapp'), 'built-in folders are taken');
});

test('its status: not asked yet, asked, then collected', () => {
  const st = (fn?: (s: ReturnType<typeof state>) => void) => state((s) => {
    s.services = [wattpad];
    fn?.(s);
  });
  const fresh = view('svc_wattpad', { state: st() });
  assert.equal(fresh.section, 'needs');
  assert.equal(fresh.status, 'Not requested yet');
  assert.deepEqual(actionIds(fresh), ['open', 'mark-requested', 'add-file', 'draft-request', 'skip', 'remove-service']);
  const asked = view('svc_wattpad', { state: st((s) => (s.sources.svc_wattpad = { requestedAt: hoursAgo(2) })) });
  assert.equal(asked.section, 'working');
  assert.match(asked.status, /^Requested 2 h ago\. Most services answer in a day or two; by law they have about 30 days\./);
  const day3 = view('svc_wattpad', { state: st((s) => (s.sources.svc_wattpad = { requestedAt: hoursAgo(72) })) });
  assert.equal(day3.section, 'working', 'no nudging after a day: it has the law\'s 30 days');
  assert.ok(actionIds(asked).includes('remove-service'), 'can still be removed once asked for');
  assert.ok(asked.actions.find((a) => a.id === 'remove-service')?.confirm, 'and asks first');
  const done = view('svc_wattpad', { state: st(), stats: { ...stats({ wattpad_other: { count: 40 } }), facets: { imported_documents: { wattpad: 2, linkedin: 9 } } } });
  assert.equal(done.section, 'done');
  assert.equal(done.records, 42, 'its documents count too, and only its own');
  assert.ok(accountChoices(views({ state: st() })).some((v) => v.id === 'svc_wattpad'), 'it is on the Accounts page');
});
