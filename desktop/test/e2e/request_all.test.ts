// Ask for Everything, end to end, with a made-up Chrome (a profile with Claude in Chrome, and a cookie file that says
// what it's signed in to: names and dates only) and the stand-in for Claude Code in Chrome. Chrome is signed in to
// Instagram, not Spotify: its page opens in Chrome, you sign in, Check Again, and Claude asks for them all at once (3
// at once, as usual: each a session with a tab group of its own), saying what needs you once at the end. Spotify's
// sign-in had lapsed: once Chrome has it again, Claude carries on by itself. Reddit is yours (Claude in Chrome isn't allowed there); a service you added gets its request by email,
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
const lines = (n: string) => (fs.existsSync(file(n)) ? fs.readFileSync(file(n), 'utf8').trim().split('\n').filter(Boolean).map((l) => JSON.parse(l)) : []);
const runs = () => lines('agent.log');
const ended = () => lines('agent.log.ended'); // when each run ended, by session
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
  // Claude, at all three at once: Spotify's sign-in had lapsed (it stops for it), Instagram and Lumen Notes are asked
  // for, and Spotify once you're in. Each takes a few seconds, long enough to be seen at it together.
  fs.writeFileSync(file('plan.json'), JSON.stringify({
    request: [
      { for: 'Spotify', steps: ['Opening Spotify\'s privacy page', 'Spotify wants you to sign in first'], result: 'needs_you Sign in to Spotify in Chrome.', sleep: 1.2 },
      { for: 'Spotify', steps: ['Choosing all of your data', 'Requesting the export'], result: 'requested', sleep: 0.3 },
      { for: 'Spotify', steps: ['Choosing all of your data', 'Requesting the export'], result: 'requested', sleep: 0.3 },
      { for: 'Instagram', steps: ['Opening Instagram\'s export page', 'Choosing all of your data', 'Requesting the export'], result: 'requested', sleep: 0.9 },
      { for: 'Lumen Notes', steps: ['Opening Lumen Notes\' settings', 'Requesting the export'], result: 'requested', sleep: 1.2 },
      // Asked for again, at once: Instagram meets Claude's usage limit while Lumen Notes is still at it.
      { for: 'Instagram', steps: ['Opening Instagram\'s export page'], limit: 'You\'ve hit your usage limit · resets 7pm', sleep: 1.5 },
      { for: 'Lumen Notes', steps: ['Opening Lumen Notes\' settings', 'Choosing everything', 'Choosing JSON', 'Requesting the export'], result: 'requested', sleep: 3 },
      // And again, one at a time (AI Settings), then three at once: each slow enough to be seen waiting its turn.
      ...['Instagram', 'Spotify', 'Lumen Notes'].map((n) => ({ for: n, steps: [`Opening ${n}`, 'Choosing everything', 'Requesting the export'], result: 'requested', sleep: 6 })),
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

test('Claude asks for all three at once, says what needs you once at the end, and carries on by itself once Chrome has the sign-in', async () => {
  const p = run.page;
  const sheet = p.locator('[data-testid=request-all]');
  assert.match(await sheet.locator('[data-testid=ra-fresh]').innerText(), /^First, Claude opens the 3 sites it hasn't worked on before, so Chrome can ask you to allow Claude on each/);
  assert.match(await sheet.locator('[data-testid=ra-how]').innerText(), /^Claude asks for each one in your Chrome, all at once, each in a tab group of its own, while you do something else/);
  await sheet.locator('button[data-action=ra-ask]', { hasText: 'Ask Claude for 3' }).click();
  await sheet.waitFor({ state: 'detached' });
  // Once each site has been opened: all three at once, each saying what it's doing, on the Overview as on each page.
  const ids = ['spotify', 'instagram', 'svc_lumennotes'];
  const atIt = (x: Awaited<ReturnType<typeof snap>>, id: string) => find(x, id).actions.some((a) => a.id === 'agent-stop') && !find(x, id).waiting;
  let s = await until(p, 'three at once', (x) => ids.every((id) => atIt(x, id)), 30_000);
  assert.ok(ids.every((id) => !/^Waiting/.test(find(s, id).status)), ids.map((id) => find(s, id).status).join(' / '));
  const box = p.locator('[data-testid=overview] [data-testid=claude-work]');
  await box.locator('[data-testid=claude-work-title]', { hasText: 'Claude is working on 3 services at once' }).waitFor({ timeout: 5_000 });
  await shot(p, 'request-all-at-once');
  // Spotify stops for the sign-in; Instagram and Lumen Notes are requested.
  s = await until(p, 'Instagram and Lumen Notes requested, Spotify waiting on you', (x) => !!find(x, 'instagram').requestedAt && !!find(x, 'svc_lumennotes').requestedAt
    && find(x, 'spotify').status === 'Needs you: Sign in to Spotify in Chrome.', 60_000);
  assert.match(find(s, 'spotify').detail ?? '', /Once you're signed in, Claude carries on by itself/);
  s = await until(p, 'one notification at the end', (x) => x.log.some((l) => /^Claude asked for 2 of your exports\. 1 needs you: Spotify \(sign in to Spotify in Chrome\)\.$/.test(l.line)), 15_000);
  assert.match(opened(), /notify: Claude asked for 2 of your exports\n/);
  assert.doesNotMatch(opened(), /notify: Requested your Instagram data|notify: Claude needs you for Spotify/, 'not one each as it went');
  assert.deepEqual(runs().map((r) => [r.mode, r.resume]), [['visit', false], ['request', false], ['request', false], ['request', false]], 'the sites first, then the requests');
  // Three Claude Code sessions at once, each in a folder (and a session) of its own: all started before any ended.
  const asked = runs().filter((r) => r.mode === 'request');
  assert.deepEqual(asked.map((r) => r.service).sort(), ['Instagram', 'Lumen Notes', 'Spotify']);
  assert.equal(new Set(asked.map((r) => r.session)).size, 3);
  assert.equal(new Set(asked.map((r) => r.cwd)).size, 3);
  const endOf = (r: { session: string }) => ended().find((e) => e.session === r.session)!.t;
  assert.ok(Math.max(...asked.map((r) => r.t)) < Math.min(...asked.map(endOf)), 'at once, not one after another');
  assert.ok(runs()[0].t < Math.min(...asked.map((r) => r.t)) && ended()[0].t <= Math.min(...asked.map((r) => r.t)), 'the first look at each site first, alone');
  assert.ok(asked.every((r) => /each in a tab group of its own\. Work only in the tab you open/.test(r.prompt)), 'each keeps to its own tabs');
  assert.match(runs()[0].prompt, /Open each of these pages in turn[\s\S]*don't click, type or sign in[\s\S]*- Spotify: https:\/\/www\.spotify\.com\/account\/privacy\//);
  assert.match(opened(), /notify: Claude is waiting for you\n/, 'said at once, while you are there');
  const st = JSON.parse(fs.readFileSync(path.join(sb.userData, 'state.json'), 'utf8'));
  assert.ok(['spotify', 'instagram', 'svc_lumennotes'].every((id) => st.sources[id].siteAllowed), 'each allowed now: not asked about again');
  assert.match(asked.find((r) => r.service === 'Lumen Notes').prompt, /Request a full export of their Lumen Notes data[\s\S]*Open https:\/\/lumennotes\.example\/settings\/export[\s\S]*Settings → Export → Request export\./);
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
  assert.equal(last.session, asked.find((r) => r.service === 'Spotify').session);
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

test('Claude\'s usage limit in one stops the rest, the ones running alongside too; one notification says so', async () => {
  const p = run.page;
  const before = runs().length;
  const notified = (opened().match(/notify: /g) ?? []).length;
  const r = await act(p, '*', 'request-all', { ids: ['instagram', 'spotify', 'svc_lumennotes'] });
  assert.equal(r.ok, true, r.error ?? '');
  // Each site is allowed now: no first look, all three at once straight away.
  await until(p, 'three at once', (x) => ['instagram', 'spotify', 'svc_lumennotes'].filter((id) => find(x, id).actions.some((a) => a.id === 'agent-stop')).length === 3, 10_000);
  const s = await until(p, 'Instagram meets the limit, Lumen Notes is stopped', (x) => /usage limit was reached/.test(find(x, 'instagram').detail ?? find(x, 'instagram').status)
    && !find(x, 'svc_lumennotes').actions.some((a) => a.id === 'agent-stop') && !find(x, 'spotify').actions.some((a) => a.id === 'agent-stop'), 30_000);
  const again = runs().slice(before);
  assert.deepEqual(again.map((x) => x.service).sort(), ['Instagram', 'Lumen Notes', 'Spotify'], 'no first look this time');
  const notes = again.find((x) => x.service === 'Lumen Notes');
  assert.equal(ended().some((e) => e.session === notes.session), false, 'Lumen Notes was stopped partway, not left to finish');
  assert.notEqual(find(s, 'svc_lumennotes').status, 'Interrupted when Homecoming quit');
  await until(p, 'one notification', () => (opened().match(/notify: /g) ?? []).length > notified, 10_000);
  const said = opened().split('\n').filter((l) => l.startsWith('notify: ')).slice(notified);
  assert.equal(said.length, 1, said.join(' / '));
  assert.match(said[0], /^notify: Claude asked for 1 of your exports$/);
  assert.ok(s.log.some((l) => /^Claude asked for 1 of your exports\. 1 needs you: Instagram \(claude's usage limit was reached \(resets 7pm\)\. Try again then\)\.$/.test(l.line)), s.log.map((l) => l.line).slice(-8).join('\n'));
  assert.deepEqual(run.errors, []);
});

test('Sites at once, in AI Settings: one at a time, the rest waiting their turn; set to 3 mid-run, the waiting ones start', async () => {
  const p = run.page;
  await p.locator('[data-testid=nav-ai]').click();
  const row = p.locator('[data-testid=settings-at-once]');
  assert.match(await row.innerText(), /Sites at once[\s\S]*How many sites Claude works on at the same time, each in a tab group of its own in (Chrome|your browser)\. More is faster, but uses more of your Claude usage at a time\./);
  const pick = row.locator('[data-testid=setup-at-once-pick]');
  assert.equal(await pick.inputValue(), '3', 'as usual');
  assert.deepEqual(await pick.locator('option').allInnerTexts(), ['One at a time', '2 at once', '3 at once', '4 at once', '5 at once']);
  await row.scrollIntoViewIfNeeded();
  await shot(p, 'ai-sites-at-once');
  await pick.selectOption('1');
  await until(p, 'one at a time', (x) => x.settings.agentsAtOnce === 1);
  await until(p, 'kept', () => JSON.parse(fs.readFileSync(path.join(sb.userData, 'state.json'), 'utf8')).settings.agentsAtOnce === 1, 5_000);
  const ids = ['instagram', 'spotify', 'svc_lumennotes'];
  // Claude at it (its Stop, and a busy bar), or waiting its turn (its Stop, and the clock).
  const claude = (x: Awaited<ReturnType<typeof snap>>, turn: boolean) => ids.filter((id) => find(x, id).actions.some((a) => a.id === 'agent-stop') && !!find(x, id).waiting === turn);
  const atIt = (x: Awaited<ReturnType<typeof snap>>) => claude(x, false);
  const waiting = (x: Awaited<ReturnType<typeof snap>>) => claude(x, true);
  assert.equal((await act(p, '*', 'request-all', { ids })).ok, true);
  let s = await until(p, 'one at it, two waiting', (x) => atIt(x).length === 1 && waiting(x).length === 2, 10_000);
  assert.deepEqual(atIt(s), ['instagram']);
  assert.equal(find(s, 'spotify').status, 'Waiting: Claude is doing Instagram first');
  await p.click('[data-testid=nav-overview]');
  const box = p.locator('[data-testid=overview] [data-testid=claude-work]');
  assert.match(await box.innerText(), /Claude is working on 3 services[\s\S]*2 more wait their turn: Claude works on one at a time, as set in AI Settings\./);
  await p.waitForTimeout(1500);
  assert.equal(atIt(await snap(p)).length, 1, 'still one at a time');
  // Three at once again, while the first is still at it: the two waiting start now.
  await p.locator('[data-testid=nav-ai]').click();
  await pick.selectOption('3');
  s = await until(p, 'all three at once', (x) => atIt(x).length === 3, 10_000);
  await p.click('[data-testid=nav-overview]');
  await box.locator('[data-testid=claude-work-title]', { hasText: 'Claude is working on 3 services at once' }).waitFor({ timeout: 5_000 });
  await box.locator('button[data-action=agent-stop-all]').click();
  await until(p, 'all stopped', (x) => atIt(x).length === 0 && waiting(x).length === 0, 15_000);
  assert.deepEqual(run.errors, []);
});
