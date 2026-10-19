// What an off-screen walk through every page found, fixed, in the real app: Do It for Me's switch back off when its
// sheet is cancelled; an export page's own I've Requested It moving on as the footer's does; Keep History and
// Notifications in true words; Browse All Sources offering only accounts, and Add by Name only when nothing has that
// name; toasts about one source not contradicting each other; set-aside sources still counted; who you are kept while
// you look at another page; the Mac's default browser listed once; Explore's Year locked with too little to show; a
// read of this Mac counted as its page counts it. Then read-only mode: every control on the Setup Assistant's iPhone,
// Accounts and You pages disabled with its note, Continue going on, and nothing of the assistant saved.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { after, before, describe, test } from 'node:test';
import type { Page } from 'playwright-core';
import { act, confirmClaudeSheet, DESKTOP, find, launch, readJson, type Running, type Sandbox, sandbox, sandboxEnv, snap, until } from './harness.ts';

const NOTE = 'Read-only mode: nothing can be changed.';
const step = (p: Page) => p.locator('[data-testid=assistant]').getAttribute('data-step');
const writeState = (sb: Sandbox, st: object) => {
  fs.mkdirSync(sb.userData, { recursive: true });
  fs.writeFileSync(path.join(sb.userData, 'state.json'), JSON.stringify({ version: 1, ...st }));
};

describe('the walk\'s fixes', () => {
  let sb: Sandbox;
  let run: Running;
  let p: Page;

  before(async () => {
    sb = sandbox({ identity: true });
    // Chrome (Claude in Chrome works in it) as the Mac's default for web links, the way Launch Services keeps it; and Firefox.
    for (const a of ['Google Chrome.app', 'Firefox.app']) fs.mkdirSync(path.join(sb.home, 'Applications', a), { recursive: true });
    const ls = path.join(sb.home, 'Library/Preferences/com.apple.LaunchServices');
    fs.mkdirSync(ls, { recursive: true });
    fs.writeFileSync(path.join(ls, 'com.apple.launchservices.secure.plist'), `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>LSHandlers</key><array><dict><key>LSHandlerURLScheme</key><string>https</string>
<key>LSHandlerRoleAll</key><string>com.google.chrome</string></dict></array></dict></plist>`);
    writeState(sb, { onboarding: { done: true }, settings: { autoRefresh: true, watchDownloads: true, aiOn: true, aiAgreedAt: new Date().toISOString() } });
    run = await launch(sandboxEnv(sb, { UMP_NO_AUTORUN: '1', UMP_CLAUDE_CMD: path.join(DESKTOP, 'test/fakes/fake_claude.py'),
      UMP_AGENT_CMD: path.join(DESKTOP, 'test/fakes/fake_claude_browser.py') }));
    p = run.page;
    await p.emulateMedia({ reducedMotion: 'reduce' });
    await until(p, 'probe', (x) => !!x.probeTime && x.setup.browsers.length > 0);
  });
  after(async () => {
    await run?.close();
    sb?.cleanup();
  });

  // The Setup Assistant, opened on one of its pages (from the main window's toolbar), and left again.
  async function assistantAt(id: string) {
    await p.evaluate((x) => (window as unknown as { api: { onboarding(o: object): Promise<unknown> } }).api.onboarding({ step: x }), id);
    await until(p, 'step saved', (x) => x.onboarding.step === id);
    await p.waitForTimeout(400); // the window has it too
    await p.locator('button[data-testid=open-assistant]').click();
    await p.locator(`[data-testid=assistant][data-step="${id}"]`).waitFor({ timeout: 10_000 });
  }
  async function leaveAssistant() {
    await p.locator('button[data-action=assistant-exit]').click();
    await p.locator('[data-testid=app][data-mode=main]').waitFor();
  }

  test('an export page\'s own I\'ve Requested It moves on, as the footer\'s does, when the footer offers Do It for Me', async () => {
    await assistantAt('export:discord');
    assert.match(await p.locator('button[data-action=assistant-continue]').innerText(), /Do It for Me/);
    await p.locator('[data-testid=export-actions] button[data-action=mark-requested]').click();
    await p.waitForFunction(() => !/^export:discord$/.test(document.querySelector('[data-testid=assistant]')?.getAttribute('data-step') ?? ''), null, { timeout: 10_000 });
    assert.match((await step(p)) ?? '', /^export:/, 'on to the next export');
    assert.ok(find(await snap(p), 'discord').requestedAt, 'and marked as requested');
    await leaveAssistant();
    await act(p, 'discord', 'unrequest');
  });

  test('Keep History says what Claude Code really keeps; Notifications points to General', async () => {
    await assistantAt('keep');
    const claude = await p.locator('[data-testid=check-retention_claude]').innerText();
    assert.match(claude, /Transcripts are deleted after 7 days/, 'this Mac\'s setting (cleanupPeriodDays 7)');
    assert.doesNotMatch(claude, /30 days/);
    await leaveAssistant();
    await assistantAt('notifications');
    assert.match(await p.locator('[data-testid=assistant] .page').innerText(), /General → Notifications in Homecoming/);
    await leaveAssistant();
  });

  test('Browse All Sources offers Add for accounts only; Add by Name only when nothing is called that', async () => {
    await assistantAt('accounts');
    await p.locator('button[data-action=browse-all-services]').click();
    const hub = p.locator('[data-testid=hub-sheet]');
    await hub.waitFor();
    await p.locator('[data-testid=hub-search]').fill('Apple Maps');
    const maps = hub.locator('[data-testid=hub-apple_maps]').first();
    await maps.waitFor();
    assert.equal(await maps.locator('button[data-action=hub-choose]').count(), 0, 'a Mac source is read anyway: nothing to add to the list');
    assert.equal(await hub.locator('button[data-action=hub-add-named]').count(), 0, 'Apple Maps is listed');
    await p.locator('[data-testid=hub-search]').fill('Apple Ma');
    await hub.locator('button[data-action=hub-add-named]').waitFor();
    await p.locator('[data-testid=hub-search]').fill('Slack');
    await hub.locator('[data-testid=hub-slack] button[data-action=hub-choose]').waitFor(); // an account not on the list yet
    await hub.locator('.sheet-actions button', { hasText: 'Done' }).click();
    await leaveAssistant();
  });

  test('a newer toast about a source takes the place of an older one', async () => {
    const toasts = p.locator('[data-testid=toasts]');
    await act(p, 'discord', 'skip', { reason: 'I don\'t use it' });
    await toasts.getByText('Discord is skipped').waitFor({ timeout: 5_000 });
    await act(p, 'discord', 'unskip');
    await act(p, 'discord', 'skip', { reason: 'Not now' });
    await toasts.getByText('Discord is set aside').waitFor({ timeout: 5_000 });
    assert.doesNotMatch(await toasts.innerText(), /Discord is skipped/);
    assert.equal(await toasts.locator('button[data-action=toast-undo]').count(), 1);
    await act(p, 'discord', 'unskip');
  });

  test('sources set aside for now still count, as not collected yet', async () => {
    const foot = p.locator('[data-testid=sidebar-progress]');
    const was = (await foot.innerText()).trim();
    const ids = ['discord', 'reddit', 'spotify', 'x'];
    for (const id of ids) await act(p, id, 'skip', { reason: 'Not now' });
    await until(p, 'set aside', (x) => ids.every((id) => find(x, id).deferred));
    await p.waitForTimeout(400);
    assert.equal((await foot.innerText()).trim(), was);
    for (const id of ids) await act(p, id, 'unskip');
  });

  test('who you are, being changed in Your Setup, stays open with what you typed while you look at another page', async () => {
    await p.locator('[data-testid=nav-yoursetup]').click();
    await p.locator('button[data-action=setup-identity-change]').click();
    const form = p.locator('[data-testid=setup-identity-form]');
    await form.locator('#add-name').fill('Grace Hopper');
    const box = form.locator('[data-testid="cand-email:ada@example.com"] input');
    await box.uncheck();
    await p.locator('[data-testid=nav-general]').click();
    await p.locator('[data-testid=general]').waitFor();
    await p.locator('[data-testid=nav-yoursetup]').click();
    await form.waitFor();
    assert.equal(await form.locator('#add-name').inputValue(), 'Grace Hopper');
    assert.equal(await box.isChecked(), false);
    // Done closes it, and what wasn't saved goes.
    await p.locator('button[data-action=setup-identity-close]').click();
    await p.locator('button[data-action=setup-identity-change]').click();
    assert.equal(await form.locator('#add-name').inputValue(), '');
    assert.equal(await box.isChecked(), true);
    await p.locator('button[data-action=setup-identity-close]').click();
  });

  test('the Mac\'s default browser is listed once, under one name', async () => {
    await p.locator('[data-testid=nav-yoursetup]').click();
    const options = await p.locator('[data-testid=setup-page-browser-pick] option').allInnerTexts();
    assert.deepEqual(options, ['Chrome (this Mac\'s default)', 'Firefox']);
    assert.equal((await snap(p)).defaultBrowser, 'Chrome');
  });

  test('Explore with little in it: Your Year is locked rather than an empty year, and Firsts says what it needs plainly', async () => {
    await act(p, 'git_commits', 'run'); // one commit, in 2024
    await until(p, 'git read', (x) => find(x, 'git_commits').section === 'done' && !x.jobs.length, 120_000);
    await p.locator('[data-testid=nav-explore]').click();
    const card = (id: string) => p.locator(`[data-testid=explore-card-${id}]`);
    for (const id of ['year', 'firsts']) await p.locator(`[data-testid=explore-card-${id}][data-ready=yes]`).waitFor({ timeout: 60_000 });
    assert.equal(await card('year').getAttribute('data-locked'), 'yes');
    assert.match(await card('year').innerText(), /Needs more of your history/);
    assert.doesNotMatch(await card('year').innerText(), /so far/);
    const firsts = await card('firsts').innerText();
    assert.match(firsts, /Needs more of your history[\s\S]*[12] of 3 firsts so far/);
    assert.doesNotMatch(firsts, /more of a little/);
    await card('year').click();
    assert.match(await p.locator('[data-testid=explore-locked]').innerText(), /Your Year needs more of your history/);
    await p.locator('[data-testid=explore-back]').click();
  });

  test('Read This Mac Now: Mail with no accounts isn\'t read, and the toast counts what the page counts', async () => {
    let s = await snap(p);
    assert.equal(find(s, 'apple_mail').status, 'No accounts in Mail');
    assert.equal(find(s, 'apple_mail').section, 'unavailable');
    const t0 = new Date().toISOString();
    await act(p, '*', 'run-all-mac');
    s = await until(p, 'reading', (x) => x.jobs.some((j) => j.kind === 'connectors'), 10_000);
    assert.ok(!s.jobs.find((j) => j.kind === 'connectors')!.sourceIds.includes('apple_mail'));
    // Said once the counts are in (toasts are logged too).
    s = await until(p, 'read and said', (x) => !x.jobs.length && x.log.some((l) => l.time >= t0 && /^(Read |Nothing found in )/.test(l.line)), 120_000);
    const text = s.log.filter((l) => l.time >= t0 && /^(Read |Nothing found in )/.test(l.line)).pop()!.line;
    assert.doesNotMatch(text, /Mail/);
    const read = s.sources.filter((v) => v.group === 'mac' && v.section !== 'unavailable').map((v) => v.name); // as the Mac's page counts
    if (read.length > 3) assert.equal(text, `Read ${read.length} sources on this Mac`);
    else {
      assert.ok(read.length > 0 && read.every((n) => text.includes(n)), `${text}: ${read.join(', ')}`);
      assert.equal(text.length, `Read ${read.join(', ')}`.length, `${text}: only those`);
    }
  });

  test('Do It for Me\'s switch goes back off when its data-settings sheet is cancelled, and asks again', async () => {
    await p.locator('[data-testid=nav-ai]').click();
    const sw = p.locator('[data-testid=toggle-agent]');
    await sw.waitFor();
    assert.equal(await sw.getAttribute('aria-checked'), 'false');
    await sw.click();
    const sheet = p.locator('[data-testid=ask-retention]');
    await sheet.waitFor();
    assert.equal(await sw.getAttribute('aria-checked'), 'true', 'on while the sheet asks');
    await sheet.locator('button', { hasText: 'Cancel' }).click();
    await sheet.waitFor({ state: 'detached' });
    await p.locator('[data-testid=toggle-agent][aria-checked=false]').waitFor({ timeout: 5_000 });
    // The next click asks again: it doesn't save "off" without a word.
    await sw.click();
    await sheet.waitFor();
    assert.equal((await snap(p)).settings.agentExports, undefined);
    await confirmClaudeSheet(p);
    await until(p, 'on', (x) => x.settings.agentExports === true);
    await p.locator('[data-testid=toggle-agent][aria-checked=true]').waitFor();
    await sw.click();
    await until(p, 'off', (x) => x.settings.agentExports === false);
    assert.deepEqual(run.errors, []);
  });
});

describe('read-only mode\'s Setup Assistant', () => {
  let sb: Sandbox;
  let run: Running | null = null;
  const stateFile = () => path.join(sb.userData, 'state.json');
  async function start(onboarding: object) {
    await run?.close();
    writeState(sb, { onboarding });
    run = await launch(sandboxEnv(sb, { UMP_READONLY: '1', UMP_NO_AUTORUN: '1' }), { assistant: true });
    await run.page.emulateMedia({ reducedMotion: 'reduce' });
    await until(run.page, 'probe', (x) => !!x.probeTime);
    return run.page;
  }
  const disabled = async (b: ReturnType<Page['locator']>, what: string) => {
    // (once the page has its buttons: under load, the iPhone page is still checking a moment after it opens)
    await b.first().waitFor({ timeout: 15_000 }).catch(() => undefined);
    assert.ok(await b.count(), `${what}: there`);
    for (const one of await b.all()) {
      assert.ok(await one.isDisabled(), `${what}: disabled`);
      assert.equal(await one.getAttribute('title'), NOTE, `${what}: says why`);
    }
  };

  before(() => {
    sb = sandbox({ identity: true });
  });
  after(async () => {
    await run?.close();
    sb?.cleanup();
  });

  test('the iPhone and Accounts pages: their choices disabled, with the note, and Continue goes on', async () => {
    const p = await start({ done: false, step: 'iphone' });
    await p.locator('[data-testid=assistant][data-step=iphone]').waitFor();
    await disabled(p.locator('button[data-action=iphone-later]'), 'Back Up Later');
    await disabled(p.locator('button[data-action=iphone-none]'), 'I Don\'t Have an iPhone');
    await disabled(p.locator('[data-testid=steps] input[type=checkbox]'), 'a step');
    await p.locator('[data-testid=iphone-locked]', { hasText: NOTE }).waitFor();
    await p.locator('button[data-action=assistant-continue]').click();
    await p.locator('[data-testid=assistant][data-step=accounts]').waitFor();
    await disabled(p.locator('button[data-action=remove-account]'), 'Remove');
    await disabled(p.locator('button[data-action=add-account]'), 'Add');
    await p.locator('[data-testid=accounts-locked]', { hasText: NOTE }).waitFor();
    const n = Number(/Continue with (\d+)/.exec(await p.locator('button[data-action=assistant-continue]').innerText())?.[1]);
    assert.match(await p.locator('[data-testid=steps-bar]').innerText(), new RegExp(`Exports \\(${n}\\)`), 'the same count as the exports to come');
    await p.locator('button[data-action=browse-all-services]').click();
    await p.locator('[data-testid=hub-search]').fill('Slack');
    await disabled(p.locator('[data-testid=hub-sheet] [data-testid=hub-slack] button[data-action=hub-choose]'), 'Add in Browse All Sources');
    await p.locator('[data-testid=hub-sheet] .sheet-actions button', { hasText: 'Done' }).click();
    await p.locator('button[data-action=assistant-continue]').click();
    await p.locator('[data-testid=assistant][data-step=notifications]').waitFor();
    assert.equal(await p.locator('[data-testid=toasts]').innerText(), '', 'nothing refused: nothing was asked');
    await p.locator('button[data-action=assistant-exit]').click();
    await p.locator('[data-testid=app][data-mode=main]').waitFor();
    await run!.close();
    run = null;
    assert.deepEqual(readJson(stateFile()).onboarding, { done: false, step: 'iphone' }, 'where it got to, and skipping it, aren\'t saved');
  });

  test('the You page: shown as it is, Continue goes on, in plain words; and Your Setup\'s form is locked too', async () => {
    const p = await start({ done: false, step: 'identity' });
    await p.locator('[data-testid=assistant][data-step=identity]').waitFor();
    await until(p, 'candidates', (x) => x.identityCandidatesReady, 30_000);
    await disabled(p.locator('[data-testid=identity-form] input'), 'who you are');
    await p.locator('[data-testid=identity-locked]', { hasText: NOTE }).waitFor();
    assert.equal(await p.locator('button[data-action=identity-later]').count(), 0, 'Continue is the way on');
    await p.locator('button[data-action=assistant-continue]').click();
    await p.locator('[data-testid=assistant][data-step=keep]').waitFor({ timeout: 5_000 });
    assert.equal(await p.locator('[data-testid=identity-error]').count(), 0);
    await p.locator('button[data-action=assistant-exit]').click();
    await p.locator('[data-testid=app][data-mode=main]').waitFor();
    await p.locator('[data-testid=nav-yoursetup]').click();
    await p.locator('button[data-action=setup-identity-change]').click();
    const form = p.locator('[data-testid=setup-identity-form]');
    await disabled(form.locator('input'), 'Your Setup\'s who you are');
    await disabled(form.locator('button[type=submit]'), 'Save');
    await run!.close();
    run = null;
    assert.deepEqual(readJson(stateFile()).onboarding, { done: false, step: 'identity' });
  });
});
