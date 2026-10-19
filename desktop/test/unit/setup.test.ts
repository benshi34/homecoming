// Your Setup's defaults (src/shared/setup.ts): which browser Do It for Me works in, whether it can run and why not,
// what the connectors are told; and phone numbers read in the region chosen (src/shared/identity.ts).
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { test } from 'node:test';
import { e164, keyOf, setPhoneRegion } from '../../src/shared/identity.ts';
import { providerLabel } from '../../src/shared/ask.ts';
import { agentBrowser, agentProvider, agentReady, type BrowserFound, claudeInboxes, inboxesOn, macDefault, notYetTitle, pageBrowser, setupEnv } from '../../src/shared/setup.ts';

const REPO = path.resolve(import.meta.dirname, '../../..');

const b = (id: string, over: Partial<BrowserFound> = {}): BrowserFound => ({
  id, name: id[0].toUpperCase() + id.slice(1), app: `/Applications/${id}.app`, profiles: 1, history: true, read: true,
  claude: ['chrome', 'edge', 'brave', 'arc', 'vivaldi', 'opera'].includes(id), default: false, ...over,
});

test('Do It for Me works in the browser chosen, else the default if Claude works there, else the first in order', () => {
  const found = [b('safari', { default: true }), b('firefox'), b('brave'), b('arc')];
  assert.equal(agentBrowser(found)?.id, 'brave', 'Safari is the default, and Claude can\'t work in it');
  assert.equal(agentBrowser(found, 'arc')?.id, 'arc');
  assert.equal(agentBrowser([b('chrome'), b('arc', { default: true })])?.id, 'arc');
  assert.equal(agentBrowser(found, 'firefox')?.id, 'brave', 'a choice Claude can\'t work in falls back');
  assert.equal(agentBrowser([b('safari'), b('firefox')]), null);
  assert.equal(agentBrowser([b('chrome', { app: null, claude: false })]), null, 'history left behind, no app');
});

test('export pages open in the browser chosen, if its app is here; otherwise the Mac\'s default', () => {
  assert.equal(pageBrowser([b('firefox')], 'firefox')?.id, 'firefox');
  assert.equal(pageBrowser([b('firefox', { app: null })], 'firefox'), null);
  assert.equal(pageBrowser([b('firefox')], ''), null);
});

test('the Mac\'s default browser is one of those found, by the name the probe gives it', () => {
  const found = [b('chrome', { app: '/Applications/Google Chrome.app' }), b('firefox')];
  assert.equal(macDefault(found, 'Google Chrome')?.name, 'Chrome', 'macOS says "Google Chrome": it\'s Chrome, not a second browser');
  assert.equal(macDefault([b('safari', { default: true }), ...found], 'Google Chrome')?.id, 'safari', 'Launch Services, as the probe read it, first');
  assert.equal(macDefault(found, 'Orion'), null, 'one not found here: just its name, from macOS');
  assert.equal(macDefault(found, null), null);
});

test('whether Do It for Me can run, and if not, why in a sentence', () => {
  const chrome = b('chrome');
  const at = new Date().toISOString();
  assert.deepEqual(agentReady({ claudeCode: true, browser: chrome, signIn: { state: 'in', how: 'claude.ai', plan: 'Max plan', at } }), { ok: true });
  assert.equal(agentReady({ claudeCode: true, browser: chrome }).ok, true, 'not asked yet: not stopped');
  assert.equal(agentReady({ claudeCode: false, browser: chrome }).fix, 'install');
  const none = agentReady({ claudeCode: true, browser: null });
  assert.equal(none.fix, 'browser');
  assert.match(none.why!, /Chrome, Edge, Brave, Arc, Vivaldi or Opera/);
  assert.equal(agentReady({ claudeCode: true, browser: chrome, signIn: { state: 'out', at } }).fix, 'sign-in');
  const key = agentReady({ claudeCode: true, browser: chrome, signIn: { state: 'in', how: 'api_key', at } });
  assert.equal(key.fix, 'plan');
  assert.match(key.why!, /^Claude Code is signed in with an API key, and Claude works in a browser only with a claude\.ai account/);
  assert.equal(agentReady({ claudeCode: true, browser: chrome, signIn: { state: 'in', how: 'claude.ai', plan: 'Free plan', at } }).fix, 'plan');
});

test('Do It for Me follows the AI picked: Claude Code with claude.ai can, Codex is coming, an Anthropic API key can\'t', () => {
  assert.deepEqual(agentProvider('claude-code', providerLabel('claude-code')), { ok: true });
  for (const id of ['codex', 'openai', 'local']) {
    const r = agentProvider(id, providerLabel(id));
    assert.deepEqual([r.ok, r.fix, r.soon], [false, 'provider', true], id);
    assert.equal(notYetTitle(r), 'Do It for Me isn\'t here yet with this AI');
  }
  assert.match(agentProvider('codex', providerLabel('codex')).why!, /^Do It for Me doesn't work with Codex \(your ChatGPT account\) yet: it's coming soon\./);
  const key = agentProvider('anthropic', providerLabel('anthropic'));
  assert.deepEqual([key.ok, key.fix, key.soon], [false, 'provider', undefined], 'not promised: Claude in Chrome needs a claude.ai account');
  assert.match(key.why!, /with an API key, Claude Code can't work in your browser/);
  assert.equal(notYetTitle(key), 'Do It for Me needs your claude.ai account');
});

test('Claude is told only the inboxes that are on: with all of them on too, and the one the service named unless it\'s off', () => {
  const mine = ['ada@gmail.com', 'ada@work.example'];
  assert.deepEqual(claudeInboxes(mine), { inboxes: mine, to: undefined }, 'every one on: still only these');
  assert.deepEqual(claudeInboxes(mine, ['ada@work.example']), { inboxes: ['ada@gmail.com'], to: undefined });
  assert.deepEqual(claudeInboxes(mine, [], 'ada@alumni.example.edu'), { inboxes: [...mine, 'ada@alumni.example.edu'], to: 'ada@alumni.example.edu' },
    'the address the service said it writes to, though it isn\'t one this Mac knows');
  assert.deepEqual(claudeInboxes(mine, ['ada@work.example'], 'Ada@Work.example'), { inboxes: ['ada@gmail.com'], to: undefined }, 'turned off: not even then');
  assert.deepEqual(claudeInboxes([], [], 'ada@gmail.com'), { to: 'ada@gmail.com' }, 'none known: no list (AI Settings says it may look in any)');
});

test('what the connectors are told, and the inboxes Claude may look in', () => {
  assert.deepEqual(setupEnv({}), { UMP_BROWSERS_SKIP: '' });
  assert.deepEqual(setupEnv({ historyOff: ['arc', 'firefox'], phoneRegion: 'GB', mailChecks: false, notificationChecks: false }),
    { UMP_BROWSERS_SKIP: 'arc,firefox', UMP_PHONE_REGION: 'GB', UMP_READY_MAIL: '0', UMP_READY_NOTIFICATIONS: '0' });
  assert.deepEqual(setupEnv({ phoneRegion: '' }), { UMP_BROWSERS_SKIP: '' }, 'unset: this Mac\'s region');
  assert.deepEqual(inboxesOn(['Ada@Gmail.com', 'ada@work.example'], ['ada@gmail.com']), ['ada@work.example']);
});

test('phone numbers without a country code are read in the region (the same as connectors/phones.py)', () => {
  try {
    setPhoneRegion({ cc: '1', trunk: '1', intl: '011' });
    assert.equal(e164('(415) 555-0100'), '+14155550100');
    assert.equal(e164('1 415 555 0100'), '+14155550100');
    assert.equal(e164('011 44 7700 900123'), '+447700900123');
    setPhoneRegion({ cc: '44', trunk: '0', intl: '00' });
    assert.equal(keyOf('phone', '07700 900123'), keyOf('phone', '+44 7700 900123'));
    assert.equal(e164('0044 7700 900123'), '+447700900123');
    assert.equal(e164('+1 415 555 0100'), '+14155550100', 'a number from abroad keeps its own country');
    setPhoneRegion({ cc: '39', trunk: '', intl: '00' });
    assert.equal(e164('06 1234 5678'), '+390612345678', 'Italy keeps the 0');
    setPhoneRegion({ cc: '65', trunk: '', intl: '00' });
    assert.equal(e164('9123 4567'), '+6591234567');
    setPhoneRegion({ cc: null, trunk: null, intl: '00' });
    assert.equal(e164('0612 345 678'), '+0612345678', 'a region not known: as written');
  } finally {
    setPhoneRegion({ cc: '1', trunk: '1', intl: '011' });
  }
});

test('the window reads numbers exactly as connectors/phones.py does, in every region it knows', () => {
  const samples = ['(415) 555-0100', '14155550100', '07700 900123', '0044 7700 900123', '011 44 7700 900123', '0011 44 7700 900123',
    '06 12 34 56 78', '33612345678', '9123 4567', '+81 3-1234-5678', '090-1234-5678', '8 912 345 67 89', '555-0100'];
  const py = `import json, sys; sys.path.insert(0, ${JSON.stringify(path.join(REPO, 'connectors'))}); import phones
out = {}
for r in phones.REGIONS:
    cc, trunk = phones.REGIONS[r]
    out[r] = {"info": {"cc": cc, "trunk": trunk, "intl": phones.INTL.get(cc, "00")}, "e164": [phones.e164(s, r) for s in json.loads(sys.argv[1])]}
print(json.dumps(out))`;
  const want = JSON.parse(execFileSync('python3', ['-c', py, JSON.stringify(samples)], { encoding: 'utf8' })) as
    Record<string, { info: { cc: string; trunk: string; intl: string }; e164: string[] }>;
  try {
    for (const [region, { info, e164: py164 }] of Object.entries(want)) {
      setPhoneRegion(info);
      assert.deepEqual(samples.map((x) => e164(x)), py164, region);
    }
  } finally {
    setPhoneRegion({ cc: '1', trunk: '1', intl: '011' });
  }
});
