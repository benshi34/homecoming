// Ask for Everything, end to end, with a made-up Chrome (a profile with Claude in Chrome, and a cookie file that says
// what it's signed in to: names and dates only) and the stand-in for Claude Code in Chrome. Chrome is signed in to
// Instagram, not Spotify: its page opens in Chrome, you sign in, Check Again, and Claude asks for both, one after the
// other, saying what needs you once at the end. Spotify's sign-in had lapsed: once Chrome has it again, Claude carries
// on by itself. Reddit is yours (Claude in Chrome isn't allowed there); a service you added gets its request by email,
// sent from Mail once you say so.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { after, before, test } from 'node:test';
import { BY_ID } from '../../src/shared/catalog.ts';
import { act, claudeChecked, DESKTOP, find, launch, type Running, type Sandbox, sandbox, sandboxEnv, selectSource, shot, snap, until } from './harness.ts';

let sb: Sandbox;
let run: Running;
const file = (n: string) => path.join(sb.home, n);
const opened = () => (fs.existsSync(path.join(sb.userData, 'opened.txt')) ? fs.readFileSync(path.join(sb.userData, 'opened.txt'), 'utf8') : '');
const runs = () => (fs.existsSync(file('agent.log')) ? fs.readFileSync(file('agent.log'), 'utf8').trim().split('\n').map((l) => JSON.parse(l)) : []);
const chromeUs = (ms: number) => BigInt(ms + 11644473600000) * 1000n; // Chrome counts microseconds from 1601
const COOKIES = () => file('Library/Application Support/Google/Chrome/Default/Cookies');

// A session cookie in the made-up Chrome, as Chrome keeps it (the value encrypted: here, made-up bytes).
function signIn(host: string, name: string, at = Date.now()) {
  const db = new DatabaseSync(COOKIES());
  db.prepare('delete from cookies where host_key = ? and name = ?').run(host, name);
  db.prepare(`insert into cookies (creation_utc, host_key, top_frame_site_key, name, value, encrypted_value, path, expires_utc, is_secure, is_httponly,
    last_access_utc, has_expires, is_persistent, priority, samesite, source_scheme, source_port, last_update_utc) values (?, ?, '', ?, '', ?, '/', ?, 1, 1, ?, 1, 1, 1, 0, 2, 443, ?)`)
    .run(chromeUs(at), host, name, Buffer.from('v10made-up'), chromeUs(at + 365 * 86400_000), chromeUs(at), chromeUs(at));
  db.close();
}

before(async () => {
  sb = sandbox({ identity: true });
  const chrome = file('Library/Application Support/Google/Chrome');
  fs.mkdirSync(path.join(chrome, 'Default/Extensions/fcoeoabgfenejglbffodgkkbkcdhcgfn/1.0'), { recursive: true });
  fs.writeFileSync(path.join(chrome, 'Local State'), JSON.stringify({ profile: { info_cache: { Default: { name: 'Ada', user_name: 'ada@example.com' } } } }));
  const db = new DatabaseSync(COOKIES());
  db.exec(`create table cookies (creation_utc integer, host_key text, top_frame_site_key text, name text, value text, encrypted_value blob, path text,
    expires_utc integer, is_secure integer, is_httponly integer, last_access_utc integer, has_expires integer, is_persistent integer, priority integer,
    samesite integer, source_scheme integer, source_port integer, last_update_utc integer)`);
  db.close();
  signIn('.instagram.com', 'sessionid');
  signIn('.instagram.com', 'csrftoken');
  // Claude: Spotify's sign-in had lapsed (it stops for it), then Instagram is asked for, and Spotify once you're in.
  fs.writeFileSync(file('plan.json'), JSON.stringify({
    request: [
      { steps: ['Opening Spotify\'s privacy page', 'Spotify wants you to sign in first'], result: 'needs_you Sign in to Spotify in Chrome.', sleep: 0.4 },
      { steps: ['Choosing all of your data', 'Requesting the export'], result: 'requested', sleep: 0.3 },
    ],
    download: [{ steps: ['Downloading'], result: 'downloading', sleep: 0.2 }],
    // First, each new site opened once: Chrome asks to allow Claude on one, and it waits for you.
    visit: [{ steps: ['Opening Spotify\'s privacy page', 'WAITING: Allow Claude on spotify.com in Chrome.', 'OPENED: https://www.spotify.com/account/privacy/',
      'OPENED: https://lumennotes.example/settings/export', 'OPENED: https://accountscenter.instagram.com/info_and_permissions/dyi/'], result: 'requested', sleep: 0.3 }],
  }));
  // Everything but these three and a service added by hand is skipped.
  const keep = ['instagram', 'spotify', 'reddit'];
  const sources: Record<string, unknown> = Object.fromEntries(Object.values(BY_ID).filter((s) => s.group === 'web' && !keep.includes(s.id)).map((s) => [s.id, { skipped: 'I don\'t use it' }]));
  fs.mkdirSync(sb.userData, { recursive: true });
  fs.writeFileSync(path.join(sb.userData, 'state.json'), JSON.stringify({
    version: 1, ask: claudeChecked(), onboarding: { done: true }, sources,
    settings: { autoRefresh: false, watchDownloads: true, aiOn: true, aiAgreedAt: new Date().toISOString(), agentExports: true, agentDownloads: true, agentChecks: false },
    services: [{ id: 'svc_lumenfit', slug: 'lumenfit', name: 'Lumen Fitness', folder: 'lumenfit', domains: ['lumenfit.example'], email: 'privacy@lumenfit.example', addedAt: new Date().toISOString(), from: 'you' },
      { id: 'svc_lumennotes', slug: 'lumennotes', name: 'Lumen Notes', folder: 'lumennotes', domains: ['lumennotes.example'], url: 'https://lumennotes.example/settings/export',
        notes: 'Settings → Export → Request export.', addedAt: new Date().toISOString(), from: 'you' }],
  }));
  run = await launch(sandboxEnv(sb, {
    UMP_NO_AUTORUN: '1', UMP_AGENT_CMD: path.join(DESKTOP, 'test/fakes/fake_claude_browser.py'), FAKE_BROWSER_PLAN: file('plan.json'),
    FAKE_BROWSER_LOG: file('agent.log'), UMP_SIGNIN_POLL_MS: '300', UMP_NOTIFICATIONS_DB: path.join(sb.home, 'no-notifications/db'),
  }));
  await until(run.page, 'Chrome checked', (x) => !!x.probeTime && !!find(x, 'spotify').signIn, 30_000);
});
after(async () => {
  await run?.close();
  sb?.cleanup();
});

test('Ask for Everything: who does each, Chrome signed in to Spotify from its page, and one request by email sent from Mail', async () => {
  const p = run.page;
  let s = await snap(p);
  assert.equal(find(s, 'instagram').signIn?.state, 'in');
  assert.deepEqual(find(s, 'spotify').signIn, { state: 'out' });
  assert.ok(find(s, 'instagram').notes?.some((n) => /^Chrome is signed in to Instagram, so Claude can ask for it without you/.test(n)));
  await p.click('[data-testid=nav-overview]');
  const card = p.locator('[data-testid=ask-everything]');
  // (once the window has the sign-ins: they come a moment after the rest)
  await card.filter({ hasText: /5 exports still to ask for[\s\S]*Claude can ask for 2 on its own · sign in to Spotify first · 1 request by email · 1 for you to do/ }).waitFor({ timeout: 10_000 });
  await card.locator('button[data-action=ask-everything]').click();
  const sheet = p.locator('[data-testid=request-all]');
  await sheet.locator('[data-testid=ra-claude] [data-testid=ra-row-instagram]', { hasText: 'Chrome is signed in' }).waitFor();
  await sheet.locator('[data-testid=ra-claude] [data-testid=ra-row-svc_lumennotes]', { hasText: 'Claude checks you\'re signed in' }).waitFor(); // a service you added, with its export page
  await sheet.locator('[data-testid=ra-sign-in] [data-testid=ra-row-spotify]', { hasText: 'Chrome isn\'t signed in' }).waitFor();
  assert.match(await sheet.locator('[data-testid=ra-yourself]').innerText(), /Reddit[\s\S]*isn't allowed there/);
  assert.match(await sheet.locator('[data-testid=ra-email]').innerText(), /Lumen Fitness[\s\S]*privacy@lumenfit\.example/);
  await shot(p, 'request-all');
  // Spotify's page opens in Chrome; you sign in; Check Again.
  await sheet.locator('button[data-action=ra-open-spotify]').click();
  await until(p, 'opened in Chrome', () => opened().includes('chrome: https://www.spotify.com/account/privacy/'), 10_000);
  signIn('.spotify.com', 'sp_dc');
  await sheet.locator('button[data-action=ra-check]').click();
  await sheet.locator('[data-testid=ra-claude] [data-testid=ra-row-spotify]', { hasText: 'Chrome is signed in' }).waitFor({ timeout: 15_000 });
  // The email: said who it goes to and from where, then sent from Mail; it's requested.
  await sheet.locator('button[data-action=ra-send]').click();
  assert.match(await sheet.locator('[data-testid=ra-email]').innerText(), /sent from Mail's default account/);
  await sheet.locator('button[data-action=ra-send-confirm]', { hasText: 'Send to Lumen Fitness' }).dblclick(); // a second click doesn't send it twice
  s = await until(p, 'Lumen Fitness requested', (x) => !!find(x, 'svc_lumenfit').requestedAt, 15_000);
  assert.equal(opened().match(/mail: privacy@lumenfit\.example · Request for a copy of my personal data/g)?.length, 1, 'sent once');
  assert.equal(find(s, 'svc_lumenfit').toRequest, undefined, 'asked for: not in the list any more');
  assert.deepEqual(run.errors, []);
});

test('Claude asks for both in turn, says what needs you once at the end, and carries on by itself once Chrome has the sign-in', async () => {
  const p = run.page;
  const sheet = p.locator('[data-testid=request-all]');
  assert.match(await sheet.locator('[data-testid=ra-fresh]').innerText(), /^First, Claude opens the 3 sites it hasn't worked on before, so Chrome can ask you to allow Claude on each/);
  await sheet.locator('button[data-action=ra-ask]', { hasText: 'Ask Claude for 3' }).click();
  await sheet.waitFor({ state: 'detached' });
  // Spotify first (its wait is longest): it stops for the sign-in; then Instagram is requested.
  let s = await until(p, 'Instagram and Lumen Notes requested, Spotify waiting on you', (x) => !!find(x, 'instagram').requestedAt && !!find(x, 'svc_lumennotes').requestedAt
    && find(x, 'spotify').status === 'Needs you: Sign in to Spotify in Chrome.', 60_000);
  assert.match(find(s, 'spotify').detail ?? '', /Once you're signed in, Claude carries on by itself/);
  s = await until(p, 'one notification at the end', (x) => x.log.some((l) => /^Claude asked for 2 of your exports\. 1 needs you: Spotify \(sign in to Spotify in Chrome\)\.$/.test(l.line)), 15_000);
  assert.match(opened(), /notify: Claude asked for 2 of your exports\n/);
  assert.doesNotMatch(opened(), /notify: Requested your Instagram data|notify: Claude needs you for Spotify/, 'not one each as it went');
  assert.deepEqual(runs().map((r) => [r.mode, r.resume]), [['visit', false], ['request', false], ['request', false], ['request', false]], 'the sites first, then the requests');
  assert.match(runs()[0].prompt, /Open each of these pages in turn[\s\S]*don't click, type or sign in[\s\S]*- Spotify: https:\/\/www\.spotify\.com\/account\/privacy\//);
  assert.match(opened(), /notify: Claude is waiting for you\n/, 'said at once, while you are there');
  const st = JSON.parse(fs.readFileSync(path.join(sb.userData, 'state.json'), 'utf8'));
  assert.ok(['spotify', 'instagram', 'svc_lumennotes'].every((id) => st.sources[id].siteAllowed), 'each allowed now: not asked about again');
  assert.match(runs()[2].prompt, /Request a full export of their Lumen Notes data[\s\S]*Open https:\/\/lumennotes\.example\/settings\/export[\s\S]*Settings → Export → Request export\./);
  // You sign in to Spotify in Chrome (its cookie is renewed): with Do It for Me off, Claude doesn't carry on; on again, it does,
  // in the same session.
  const settings = (patch: Record<string, unknown>) => p.evaluate((x) => (window as unknown as { api: { settings(x: unknown): Promise<unknown> } }).api.settings(x), patch);
  await settings({ agentExports: false });
  signIn('.spotify.com', 'sp_dc', Date.now() + 1000);
  await p.waitForTimeout(2500);
  assert.equal(runs().length, 4, `not while Do It for Me is off: ${JSON.stringify(runs().map((r) => [r.mode, r.resume, r.session]))} ${JSON.stringify((await snap(p)).settings.agentExports)}`);
  await settings({ agentExports: true });
  s = await until(p, 'Spotify requested', (x) => !!find(x, 'spotify').requestedAt, 30_000);
  const last = runs().at(-1);
  assert.equal(last.resume, true, 'carried on, not started again');
  assert.equal(last.session, runs()[1].session);
  assert.ok(s.log.some((l) => l.line === 'Signed in to Spotify in Chrome: Claude carries on.'));
  // Reddit: Claude in Chrome isn't allowed there.
  await selectSource(p, 'reddit');
  assert.equal(await p.locator('[data-testid=detail] button[data-action=agent-request]').count(), 0);
  assert.match(await p.locator('[data-testid=detail]').innerText(), /isn't allowed on reddit\.com/);
  const r = await p.evaluate(() => (window as unknown as { api: { action(a: string, b: string): Promise<{ ok: boolean; error?: string }> } }).api.action('reddit', 'agent-request'));
  assert.equal(r.ok, false);
  await act(p, '*', 'check-sign-ins');
  assert.deepEqual(run.errors, []);
});
