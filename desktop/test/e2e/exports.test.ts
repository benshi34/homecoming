// Web exports and guided sources, end to end: export pages open in your own browser, downloads are picked up from
// ~/Downloads, files added by hand, and every way an import can go wrong. The real imports.py parses the fixture
// exports into a throwaway corpus.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { after, before, test } from 'node:test';
import { act, clickAction, find, launch, readJson, type Running, type Sandbox, sandbox, sandboxEnv, selectSource, shot, snap, until } from './harness.ts';

let sb: Sandbox;
let run: Running;

before(async () => {
  sb = sandbox({ identity: true });
  // A stand-in for the Claude CLI: keeps what it was asked, answers with a mapping for the Wattpad download below (as
  // its stream-json result line).
  const fakeClaude = path.join(sb.home, 'fake-claude');
  fs.writeFileSync(fakeClaude, `#!/bin/sh\ncat > "${path.join(sb.home, 'asked.txt')}"\ncat "${path.join(sb.home, 'reply.json')}"\n`, { mode: 0o755 });
  const mapping = { service: 'Wattpad', items: [{ describe: 'Stories you wrote', file: 'wattpad-export.json', path: 'stories', kind: 'post',
    time: 'created', title: 'title', author: 'me' }] };
  fs.writeFileSync(path.join(sb.home, 'reply.json'), JSON.stringify({ type: 'result', is_error: false, result: `Here it is:\n\`\`\`json\n${JSON.stringify(mapping)}\n\`\`\`` }));
  run = await launch(sandboxEnv(sb, {
    UMP_NO_AUTORUN: '1', UMP_CLAUDE_CMD: fakeClaude, UMP_NOTIFICATIONS_DB: notificationDb(), UMP_SIGNAL_MS: '500',
    UMP_URLS: JSON.stringify({
      discord: 'https://discord.example/export', google_takeout: 'https://takeout.example/', 'google_takeout:download': 'https://takeout.example/manage',
    }),
  }));
  await until(run.page, 'first probe', (x) => !!x.probeTime);
});
after(async () => {
  await run?.close();
  sb?.cleanup();
});

// Where the test's Notification Center keeps notifications (written by notify() below).
function notificationDb() {
  return path.join(sb.home, 'notifications/db');
}
// A notification as macOS stores it: an app, when, and a plist with the title, subtitle and body.
function notifyOnThisMac(app: string, title: string, subtitle: string, body: string) {
  fs.mkdirSync(path.dirname(notificationDb()), { recursive: true });
  const db = new DatabaseSync(notificationDb());
  db.exec('create table if not exists app (app_id integer primary key, identifier text, badge integer); '
    + 'create table if not exists record (rec_id integer primary key, app_id integer, uuid blob, data blob, request_date real, request_last_date real, '
    + 'delivered_date real, presented integer, style integer, snooze_fire_date real)');
  db.prepare('insert into app (identifier, badge) values (?, 0)').run(app);
  const id = (db.prepare('select max(app_id) as id from app').get() as { id: number }).id;
  const esc = (t: string) => t.replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const plist = `<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict><key>app</key><string>${esc(app)}</string><key>req</key><dict>`
    + `<key>titl</key><string>${esc(title)}</string><key>subt</key><string>${esc(subtitle)}</string><key>body</key><string>${esc(body)}</string></dict></dict></plist>`;
  db.prepare('insert into record (app_id, data, delivered_date) values (?, ?, ?)').run(id, Buffer.from(plist), Date.now() / 1000 - 978307200);
  db.close();
}

const opened = () => (fs.existsSync(path.join(sb.userData, 'opened.txt')) ? fs.readFileSync(path.join(sb.userData, 'opened.txt'), 'utf8').trim().split('\n') : []);

test('Discord: open the export page in your browser, request, and the download is picked up from Downloads', async () => {
  await selectSource(run.page, 'discord');
  assert.equal(await run.page.locator('[data-testid=status]').innerText(), 'Not requested yet');
  assert.equal(await run.page.locator('[data-testid=detail] [data-testid=steps] .steps-row').count(), 5, 'the steps stay in the app');
  await clickAction(run.page, 'open');
  await until(run.page, 'opened in the browser', () => opened().includes('https://discord.example/export'));
  await shot(run.page, 'export-detail');
  await clickAction(run.page, 'mark-requested');
  let s = await until(run.page, 'requested', (x) => !!find(x, 'discord').requestedAt);
  assert.equal(find(s, 'discord').section, 'working');
  await run.page.locator('[data-testid=state] .wait-clock').waitFor({ timeout: 10_000 }); // its clock has started
  assert.equal(await run.page.locator('[data-testid=state] .bar').count(), 0, 'no progress bar while the service prepares it');
  // Days later the email's link downloads the package into Downloads.
  fs.copyFileSync(sb.exports.discord, path.join(sb.downloads, 'package.zip'));
  s = await until(run.page, 'discord imported', (x) => find(x, 'discord').section === 'done' && !x.jobs.length, 90_000);
  assert.equal(find(s, 'discord').records, 3);
  // It's home: a banner says so, and opens it.
  const banner = run.page.locator('[data-testid=arrival-discord]');
  await banner.waitFor({ timeout: 10_000 });
  assert.match(await banner.innerText(), /Discord is home/);
  assert.ok(fs.existsSync(path.join(sb.corpus, 'imports/discord/package.zip')));
  assert.ok(!fs.existsSync(path.join(sb.downloads, 'package.zip')), 'moved out of Downloads');
  assert.equal(readJson(path.join(sb.corpus, 'manifest.json')).discord.count, 3);
  await shot(run.page, 'export-imported');
  assert.match(await run.page.locator('[data-testid=detail]').innerText(), /3 records/);
});

test('Takeout: once requested, its download page opens, and the parts that arrive share a folder', async () => {
  await act(run.page, 'google_takeout', 'mark-requested');
  await act(run.page, 'google_takeout', 'open-download');
  await until(run.page, 'download page opened', () => opened().includes('https://takeout.example/manage'));
  fs.copyFileSync(sb.exports.google_takeout, path.join(sb.downloads, path.basename(sb.exports.google_takeout)));
  const s = await until(run.page, 'google imported', (x) => find(x, 'google_takeout').section === 'done' && !x.jobs.length, 90_000);
  assert.ok(fs.existsSync(path.join(sb.corpus, 'imports/takeout-20250301/takeout-20250301T120000Z-1-001.zip')));
  const m = readJson(path.join(sb.corpus, 'manifest.json'));
  assert.equal(m.gmail.count, 2);
  assert.equal(m.chrome_synced.count, 1);
  assert.equal(find(s, 'google_takeout').records, 3);
});

test('Downloads watcher: an expected export is imported on arrival', async () => {
  await act(run.page, 'linkedin', 'mark-requested');
  const src = sb.exports.linkedin_nested;
  fs.copyFileSync(src, path.join(sb.downloads, path.basename(src)));
  const s = await until(run.page, 'linkedin imported', (x) => find(x, 'linkedin').section === 'done' && !x.jobs.length, 90_000);
  assert.ok(find(s, 'linkedin').records >= 2);
  assert.ok(!fs.existsSync(path.join(sb.downloads, path.basename(src))), 'moved out of Downloads');
  assert.ok(fs.existsSync(path.join(sb.corpus, 'imports/linkedin', path.basename(src))));
});

test('an export that reveals another of your addresses asks, then re-labels', async () => {
  // The LinkedIn archive just imported lists ada.work@example.com; the fake Mac knows an iCloud address and a phone.
  let s = await until(run.page, 'new identity found', (x) => /new .* found/.test(find(x, 'identity').status), 60_000);
  assert.deepEqual([find(s, 'identity').section, !!find(s, 'identity').needsYou], ['todo', false], 'to do, in Your Setup');
  await selectSource(run.page, 'identity');
  // The form is open already: no Review button above it that would only open it again.
  const form = run.page.locator('[data-testid=identity-form]');
  await form.waitFor();
  assert.equal(await run.page.locator('[data-testid=detail] [data-testid=actions] button[data-action=save-identity]').count(), 0);
  const work = form.locator('[data-testid="cand-email:ada.work@example.com"]');
  await work.waitFor();
  assert.match(await work.innerText(), /New/);
  assert.match(await work.innerText(), /LinkedIn export/);
  await form.locator('[data-testid="cand-phone:+14155550100"] input').uncheck();
  await shot(run.page, 'identity-new-found');
  await form.locator('button[type=submit]').click();
  s = await until(run.page, 'relabel queued', (x) => x.jobs.some((j) => j.kind === 'import'), 20_000);
  assert.ok(readJson(path.join(sb.corpus, 'identity.json')).emails.includes('ada.work@example.com'));
  s = await until(run.page, 'relabeled', (x) => !x.jobs.length && find(x, 'identity').section === 'done', 90_000);
  assert.ok(readJson(path.join(sb.userData, 'state.json')).identityDismissed.includes('phone:+14155550100'));
});

test('Downloads watcher: an unexpected export waits for a yes', async () => {
  fs.copyFileSync(sb.exports.instagram, path.join(sb.downloads, path.basename(sb.exports.instagram)));
  fs.copyFileSync(sb.exports.facebook, path.join(sb.downloads, path.basename(sb.exports.facebook)));
  fs.copyFileSync(sb.exports.unknown, path.join(sb.downloads, 'holiday-photos (2).zip'));
  fs.copyFileSync(sb.exports.broken, path.join(sb.downloads, 'package-broken.zip'));
  let s = await until(run.page, 'found two', (x) => x.sources.filter((v) => v.status.startsWith('Found')).length === 2);
  const ig = find(s, 'instagram');
  assert.deepEqual([ig.section, ig.needsYou], ['working', true], 'its file is here: in progress, waiting for your yes');
  const firstSourceNeed = s.sources.filter((v) => v.needsYou && v.group !== 'setup' && !v.blockedBy).sort((a, b) => a.priority - b.priority)[0];
  assert.ok(['instagram', 'facebook'].includes(firstSourceNeed.id), 'a found file comes before anything else a source needs');
  assert.ok(fs.existsSync(path.join(sb.downloads, path.basename(sb.exports.instagram))), 'not moved without asking');
  await selectSource(run.page, 'instagram');
  await shot(run.page, 'found-in-downloads');
  await clickAction(run.page, 'import-found');
  s = await until(run.page, 'instagram imported', (x) => find(x, 'instagram').section === 'done' && !x.jobs.length, 90_000);
  assert.equal(readJson(path.join(sb.corpus, 'manifest.json')).instagram.count, 1);

  await selectSource(run.page, 'facebook');
  assert.match(find(s, 'facebook').detail!, /You hadn't asked Facebook and Messenger for your data in the app, so it waits for a yes\. Importing moves it out of Downloads/);
  await clickAction(run.page, 'ignore-found');
  s = await until(run.page, 'facebook ignored', (x) => !find(x, 'facebook').status.startsWith('Found'));
  assert.equal(find(s, 'facebook').status, 'Not requested yet');
  // Ignore can be undone: from its toast, or later from the page.
  await run.page.locator('[data-testid=toasts] button[data-action=toast-undo]').waitFor();
  await run.page.locator('[data-testid=detail] [data-testid=ignored]', { hasText: '1 ignored file in Downloads' }).waitFor();
  await shot(run.page, 'ignored-file');
  await run.page.locator('[data-testid=detail] button[data-action=unignore-found]').click();
  s = await until(run.page, 'shown again', (x) => find(x, 'facebook').status === 'Found the export in Downloads');
  await until(run.page, 'not ignored any more', () => !readJson(path.join(sb.userData, 'state.json')).ignoredFiles.some((k: string) => k.includes('facebook-ada')));
  await clickAction(run.page, 'ignore-found');
  s = await until(run.page, 'facebook ignored again', (x) => !find(x, 'facebook').status.startsWith('Found'));
  await run.page.locator('[data-testid=toasts] button[data-action=toast-undo]').last().click();
  s = await until(run.page, 'undone from the toast', (x) => find(x, 'facebook').status === 'Found the export in Downloads');
  await clickAction(run.page, 'ignore-found');
  s = await until(run.page, 'and ignored', (x) => !find(x, 'facebook').status.startsWith('Found'));
  assert.ok(fs.existsSync(path.join(sb.downloads, path.basename(sb.exports.facebook))), 'ignored files stay put');
  await until(run.page, 'ignore saved', () => readJson(path.join(sb.userData, 'state.json')).ignoredFiles.some((k: string) => k.includes('facebook-ada')));
  assert.ok(fs.existsSync(path.join(sb.downloads, 'package-broken.zip')), 'half-downloaded zips are left alone');

  // The same Instagram export again, under another name: it's already in the library, so it isn't offered.
  fs.copyFileSync(sb.exports.instagram, path.join(sb.downloads, 'instagram-again.zip'));
  await until(run.page, 'recognized', () => readJson(path.join(sb.userData, 'state.json')).importedFiles.some((k: string) => k.includes('instagram-again.zip')));
  assert.ok(!find(await snap(run.page), 'instagram').status.startsWith('Found'));
});

test('a download for a source you skipped is shown, and importing it includes the source again', async () => {
  await act(run.page, 'claude_ai', 'skip', { reason: 'I don\'t use Claude.ai' });
  await until(run.page, 'skipped', (x) => find(x, 'claude_ai').section === 'unavailable');
  fs.copyFileSync(sb.exports.claude_ai, path.join(sb.downloads, path.basename(sb.exports.claude_ai)));
  let s = await until(run.page, 'found', (x) => find(x, 'claude_ai').status === 'Found the export in Downloads');
  assert.deepEqual([find(s, 'claude_ai').section, find(s, 'claude_ai').needsYou], ['working', true]);
  assert.match(find(s, 'claude_ai').detail!, /You skipped Claude\.ai\. Importing it includes Claude\.ai again/);
  await selectSource(run.page, 'claude_ai');
  await shot(run.page, 'skipped-found');
  await clickAction(run.page, 'import-found');
  s = await until(run.page, 'included and imported', (x) => !x.jobs.length && find(x, 'claude_ai').section !== 'unavailable' && !find(x, 'claude_ai').status.startsWith('Found'), 90_000);
  assert.equal(readJson(path.join(sb.userData, 'state.json')).sources.claude_ai.skipped, undefined, 'included again');
  assert.ok(!fs.existsSync(path.join(sb.downloads, path.basename(sb.exports.claude_ai))), 'moved out of Downloads');
});

test('with Watch Downloads off, an export waits in Downloads; turned back on, it is picked up', async () => {
  await act(run.page, 'notion', 'mark-requested');
  await run.page.evaluate(() => (window as unknown as { api: { settings(x: object): Promise<unknown> } }).api.settings({ watchDownloads: false }));
  const name = path.basename(sb.exports.notion);
  fs.copyFileSync(sb.exports.notion, path.join(sb.downloads, name));
  await new Promise((r) => setTimeout(r, 2500));
  assert.ok(fs.existsSync(path.join(sb.downloads, name)), 'left alone while it\'s off');
  assert.equal(readJson(path.join(sb.userData, 'state.json')).sources.notion.lastFileAt, undefined);
  await run.page.click('[data-testid=nav-general]');
  await run.page.locator('[data-testid=general]', { hasText: 'Off: add each download on its page' }).waitFor();
  await shot(run.page, 'settings-watch-off');
  await run.page.locator('[data-testid=toggle-watch]').click();
  await until(run.page, 'picked up once it is on', () => !fs.existsSync(path.join(sb.downloads, name)) && !!readJson(path.join(sb.userData, 'state.json')).sources.notion?.lastFileAt, 30_000);
  await run.page.keyboard.press('Escape');
  await until(run.page, 'imported', (x) => !x.jobs.length, 90_000);
});

test('Open Messages and the like go through the same door as links, so tests never open real apps', async () => {
  await act(run.page, 'retention_messages', 'open-app');
  await until(run.page, 'logged', () => opened().includes('app: Messages'));
});

test('adding files by hand, and the mistakes people make', async () => {
  // A photo zip handed to Discord
  let r = await act(run.page, 'discord', 'add-file', { paths: [path.join(sb.downloads, 'holiday-photos (2).zip')] });
  assert.equal(r.ok, false);
  let s = await until(run.page, 'wrong file error', (x) => /doesn't look like a Discord export/.test(find(x, 'discord').detail ?? ''));
  // Nothing went in, so it asks for the right download, not to run the import again.
  assert.equal(find(s, 'discord').status, 'That download couldn\'t be used');
  assert.equal(find(s, 'discord').actions[0].id, 'add-file');
  // A truncated download
  r = await act(run.page, 'reddit', 'add-file', { paths: [path.join(sb.downloads, 'package-broken.zip')] });
  assert.equal(r.ok, false);
  s = await until(run.page, 'broken zip error', (x) => /looks incomplete or damaged/.test(find(x, 'reddit').detail ?? ''));
  // The right export for a different source is filed where it belongs
  r = await act(run.page, 'reddit', 'add-file', { paths: [sb.exports.x] });
  assert.equal(r.ok, true);
  await until(run.page, 'x filed under x', () => fs.existsSync(path.join(sb.corpus, 'imports/x/twitter-2025-03-01-abc.zip')));
  // A guided source: the Timeline file from the phone
  await act(run.page, 'maps_timeline', 'add-file', { paths: [sb.exports.maps_timeline] });
  s = await until(run.page, 'timeline imported', (x) => find(x, 'maps_timeline').section === 'done' && !x.jobs.length, 90_000);
  assert.equal(find(s, 'maps_timeline').records, 1);
});

test('another service: add it by name, drop its download in any format, and everything in it is kept', async () => {
  const r = await act(run.page, '*', 'add-service', { name: 'Wattpad', url: 'wattpad.com' });
  assert.ok(r.ok && r.id, r.error ?? 'no id');
  const id = r.id!;
  let s = await until(run.page, 'service added', (x) => x.sources.some((v) => v.id === id));
  assert.equal(find(s, id).status, 'Not requested yet');
  assert.equal(find(s, id).group, 'web');
  assert.equal(find(s, id).url, 'https://www.wattpad.com/settings', 'known to the directory: its export page');
  await selectSource(run.page, id);
  await shot(run.page, 'service-added');
  // No download option: the app drafts an access request for the person to send.
  await act(run.page, id, 'draft-request');
  assert.match(decodeURIComponent(opened().join('\n')), /^mailto:.*subject=Request for a copy of my personal data.*GDPR Article 15/ms);
  // A format nothing in the app knows: kept by imports.py's catch-alls, item by item.
  const dl = path.join(sb.home, 'wattpad-export.json');
  fs.writeFileSync(dl, JSON.stringify({ stories: [{ title: 'The Difference Engine', created: '2019-03-01T10:00:00Z', reads: 120 },
    { title: 'Gears', created: '2020-07-04T10:00:00Z', reads: 8 }] }));
  const added = await act(run.page, id, 'add-file', { paths: [dl] });
  assert.equal(added.ok, true, added.error ?? 'not added');
  s = await until(run.page, 'service imported', (x) => find(x, id).section === 'done' && !x.jobs.length, 90_000);
  assert.equal(find(s, id).records, 2);
  assert.equal(find(s, id).status, '2 records, 2019 to Jul 4, 2020');
  assert.ok(fs.existsSync(path.join(sb.corpus, 'imports/wattpad/wattpad-export.json')));
  const recs = fs.readFileSync(path.join(sb.corpus, 'normalized/wattpad_other.jsonl'), 'utf8');
  assert.match(recs, /The Difference Engine/);
  // Claude reads the structure (never the values unless allowed), writes a mapping, the person checks and uses it.
  await selectSource(run.page, id);
  await run.page.click('[data-action=open-mapping]');
  const sheet = run.page.locator('[data-testid=mapping-sheet]');
  assert.match(await sheet.locator('p').first().innerText(), /^Claude reads how the download is laid out/, 'the agent that will answer, by name');
  // What's sent is there to open, not in the way.
  assert.equal(await run.page.locator('[data-testid=mapping-prompt]').count(), 0);
  await sheet.locator('[data-testid=mapping-sent] .disclose-btn').click();
  const prompt = run.page.locator('[data-testid=mapping-prompt]');
  await prompt.filter({ hasText: 'Structure:' }).waitFor();
  assert.match(await prompt.innerText(), /"title": "text \(up to 21 characters\)"/);
  assert.doesNotMatch(await prompt.innerText(), /Difference Engine/, 'no content without permission');
  await shot(run.page, 'mapping-ask');
  // AI isn't on yet: nothing is sent until it is, and turning it on goes through what that means, once.
  assert.equal(await run.page.locator('[data-action=ask-claude]').count(), 0);
  await sheet.locator('button[data-action=mapping-turn-on]', { hasText: 'Turn On AI and Ask…' }).click();
  await sheet.locator('[data-testid=ai-agreement]').waitFor();
  assert.notEqual((await snap(run.page)).settings.aiOn, true, 'not on by itself');
  await shot(run.page, 'mapping-agreement');
  await sheet.locator('button[data-action=mapping-ai-on]').click();
  // Claude Code with your claude.ai account, as Ask uses it: its data settings are confirmed first, as in Ask.
  const retention = run.page.locator('[data-testid=ask-retention]');
  await retention.waitFor();
  await retention.locator('input[type=checkbox]').check();
  await retention.locator('button[data-action=confirm-retention]').click();
  await run.page.locator('[data-testid=mapping-preview]', { hasText: 'Stories you wrote' }).waitFor({ timeout: 30_000 });
  assert.match(await run.page.locator('[data-testid=mapping-preview]').innerText(), /2 found, 100% with a time/);
  assert.doesNotMatch(fs.readFileSync(path.join(sb.home, 'asked.txt'), 'utf8'), /Difference Engine/, 'what was sent had no content');
  await shot(run.page, 'mapping-preview');
  await run.page.click('[data-action=use-mapping]');
  s = await until(run.page, 'read with the mapping', (x) => !x.jobs.length && !!x.mappings.wattpad && (find(x, id).contents ?? []).some((g) => g.rows.some((r) => r.label === 'Posts')), 90_000);
  assert.equal(find(s, id).records, 2, 'the same two items, now as posts, not twice');
  const posts = fs.readFileSync(path.join(sb.corpus, 'normalized/wattpad.jsonl'), 'utf8').trim().split('\n').map((l) => JSON.parse(l));
  assert.deepEqual(posts.map((p) => [p.kind, p.title, p.is_me]), [['post', 'The Difference Engine', true], ['post', 'Gears', true]]);
  assert.ok(!fs.existsSync(path.join(sb.corpus, 'normalized/wattpad_other.jsonl')), 'the catch-all no longer keeps them too');
  // A reply that isn't a mapping is caught before anything is saved.
  const bad = await act(run.page, id, 'try-mapping', { text: 'Sorry, I can\'t help with that.' });
  assert.deepEqual(bad, { ok: false, error: 'There\'s no mapping in that reply.' });

  // Kept on this Mac, never written into the app's own mappings. One the app ships starts the next Wattpad off,
  // and the same name gets its own folder.
  assert.ok(!fs.existsSync(path.join(sb.home, 'mapping-library/wattpad.json')), 'nothing written into the app');
  fs.mkdirSync(path.join(sb.home, 'mapping-library'), { recursive: true });
  fs.copyFileSync(path.join(sb.corpus, 'mappings/wattpad.json'), path.join(sb.home, 'mapping-library/wattpad.json'));
  // Wattpad by name again is the Wattpad that's here, not a second copy that would never get its files.
  assert.equal((await act(run.page, '*', 'add-service', { name: 'Wattpad' })).id, id);
  const again = await act(run.page, '*', 'add-service', { slug: 'wattpad' }); // from the directory: a second account
  assert.notEqual(again.id, id);
  await until(run.page, 'starts with the shared mapping', (x) => !!x.mappings['wattpad-2']);
  assert.equal((await act(run.page, 'discord', 'remove-service')).ok, false);
  await act(run.page, again.id!, 'remove-service');
  s = await until(run.page, 'removed', (x) => !x.sources.some((v) => v.id === again.id));
  // The hub lists every service the app can collect from, by kind; search it and add one with a click.
  await run.page.click('[data-testid=nav-hub]');
  await run.page.locator('[data-testid=hub-kind-reading]').waitFor();
  assert.ok(await run.page.locator('[data-testid=hub-instagram]').count(), 'built-in accounts are in it');
  assert.equal(await run.page.locator('[data-testid="hub-dir:instagram"]').count(), 0, 'once');
  await shot(run.page, 'hub');
  await run.page.fill('[data-testid=hub-search]', 'goodreads');
  const good = run.page.locator('[data-testid=hub-results] [data-testid="hub-dir:goodreads"]');
  await good.waitFor();
  await good.locator('[data-action=hub-add]').click();
  s = await until(run.page, 'added from the hub', (x) => x.services.some((e) => e.slug === 'goodreads'));
  const gr = s.services.find((e) => e.slug === 'goodreads')!;
  assert.equal(find(s, gr.id).group, 'web');
  assert.equal(find(s, gr.id).url, 'https://www.goodreads.com', 'no export page known: its home page, never an account page');
  await run.page.click('[data-testid=nav-found]');
  await run.page.locator('[data-testid=hub-filter-found][aria-selected=true]').waitFor();
  // Adding one that isn't listed starts on the same page.
  await run.page.click('[data-testid=hub] button[data-action=hub-add-source]');
  await run.page.locator('[data-testid=add-service] #svc-name').waitFor();
  await run.page.keyboard.press('Escape');
});

test('Downloads watcher: a service you asked sends a .csv named after it, and it is imported on arrival', async () => {
  const gr = (await snap(run.page)).services.find((e) => e.slug === 'goodreads')!;
  const unnamed = path.join(sb.downloads, 'library_export.csv');
  fs.writeFileSync(unnamed, 'Title,Author\nIgnored,Nobody\n');
  const csv = 'Book Id,Title,Author,My Rating,Date Read,Exclusive Shelf\n1,The Left Hand of Darkness,Ursula K. Le Guin,5,2021/05/02,read\n' +
    '2,Middlemarch,George Eliot,4,2022/11/20,read\n3,Piranesi,Susanna Clarke,0,,to-read\n';
  // Before you've asked Goodreads, a file like this is just a file.
  fs.writeFileSync(path.join(sb.downloads, 'goodreads_library_export.csv'), csv);
  await new Promise((r) => setTimeout(r, 2000));
  assert.ok(fs.existsSync(path.join(sb.downloads, 'goodreads_library_export.csv')), 'not asked for yet: left alone');
  fs.rmSync(path.join(sb.downloads, 'goodreads_library_export.csv'));
  await act(run.page, gr.id, 'mark-requested');
  await until(run.page, 'requested', (x) => !!find(x, gr.id).requestedAt);
  fs.writeFileSync(path.join(sb.downloads, 'goodreads_library_export.csv'), csv);
  const s = await until(run.page, 'goodreads imported', (x) => find(x, gr.id).section === 'done' && !x.jobs.length, 90_000);
  assert.ok(fs.existsSync(path.join(sb.corpus, 'imports/goodreads/goodreads_library_export.csv')), 'moved into the corpus');
  assert.ok(!fs.existsSync(path.join(sb.downloads, 'goodreads_library_export.csv')));
  assert.ok(find(s, gr.id).records >= 3, `the three books are kept (${find(s, gr.id).records})`);
  assert.ok(fs.existsSync(unnamed), 'a file named after nothing you asked for stays in Downloads');
  fs.rmSync(unnamed);
  // A service on account.ubisoft.com is "ubisoft", not "account": a bank statement isn't its export.
  const ubi = await act(run.page, '*', 'add-service', { name: 'Ubisoft' });
  await act(run.page, ubi.id!, 'mark-requested');
  await until(run.page, 'ubisoft requested', (x) => !!find(x, ubi.id!).requestedAt);
  const statement = path.join(sb.downloads, 'account_statement.csv');
  fs.writeFileSync(statement, 'Date,Amount\n2026-01-02,12.00\n');
  await new Promise((r) => setTimeout(r, 2000));
  assert.ok(fs.existsSync(statement), 'left in Downloads');
  fs.rmSync(statement);
  await act(run.page, ubi.id!, 'remove-service');
});

test('another mail account: name it, add the mailbox', async () => {
  await selectSource(run.page, 'other_mail');
  await run.page.fill('#acct', 'Work Mail');
  await run.page.locator('[data-testid=account-form] button').click();
  await until(run.page, 'account saved', (x) => find(x, 'other_mail').accountName === 'Work Mail');
  await act(run.page, 'other_mail', 'add-file', { paths: [sb.exports.mailbox] });
  const s = await until(run.page, 'mail imported', (x) => find(x, 'other_mail').section === 'done' && !x.jobs.length, 90_000);
  assert.ok(fs.existsSync(path.join(sb.corpus, 'imports/work_mail/Inbox.mbox/mbox')));
  assert.equal(readJson(path.join(sb.corpus, 'manifest.json')).work_mail.count, 2);
  assert.equal(find(s, 'other_mail').records, 2);
  await shot(run.page, 'other-mail');
});

test('a malformed export fails on its own row and blocks nothing else', async () => {
  const good = path.join(sb.root, 'x-good.zip');
  fs.renameSync(path.join(sb.corpus, 'imports/x/twitter-2025-03-01-abc.zip'), good); // only the malformed archive this time
  await act(run.page, 'x', 'add-file', { paths: [sb.exports.x_malformed] });
  await act(run.page, 'spotify', 'add-file', { paths: [sb.exports.spotify] });
  const s = await until(run.page, 'imports settled', (x) => !x.jobs.length && !!find(x, 'x').needsYou && find(x, 'spotify').section === 'done', 90_000);
  assert.equal(find(s, 'x').status, 'The import failed');
  assert.match(find(s, 'x').detail!, /KeyError/);
  assert.equal(find(s, 'spotify').records, 1);
  assert.equal(find(s, 'discord').section, 'done', 'earlier imports are unaffected');
  await selectSource(run.page, 'x');
  await shot(run.page, 'import-failed');
  // Replace the bad file with a good one and retry
  fs.rmSync(path.join(sb.corpus, 'imports/x/twitter-2025-03-02-old.zip'));
  fs.renameSync(good, path.join(sb.corpus, 'imports/x/twitter-2025-03-01-abc.zip'));
  await clickAction(run.page, 'reimport');
  await until(run.page, 'x recovers', (x) => find(x, 'x').section === 'done' && !x.jobs.length, 90_000);
});

test('an export with nothing usable in it is flagged, not silently dropped', async () => {
  fs.rmSync(path.join(sb.corpus, 'imports/spotify'), { recursive: true });
  await act(run.page, 'spotify', 'add-file', { paths: [sb.exports.spotify_empty] });
  const s = await until(run.page, 'empty export flagged', (x) => find(x, 'spotify').status === 'The export had nothing the app could read' && !x.jobs.length, 90_000);
  assert.match(find(s, 'spotify').detail!, /Extended streaming history/);
});

test('a notification on this Mac that sounds like Spotify saying it is ready: "looks ready", and you hear about it', async () => {
  await act(run.page, 'spotify', 'mark-requested');
  await until(run.page, 'requested', (x) => find(x, 'spotify').section === 'working');
  notifyOnThisMac('com.apple.mobilesms', 'Sam', '', 'is spotify wrapped ready yet?'); // a chat: not a data request
  notifyOnThisMac('com.apple.mail', 'Spotify', 'Your Spotify data is ready to download', 'Hi Ada, the data you requested is ready.');
  const s = await until(run.page, 'looks ready', (x) => find(x, 'spotify').status.startsWith('Looks ready'), 30_000);
  assert.match(find(s, 'spotify').status, /^Looks ready: a notification from Mail/);
  assert.match(find(s, 'spotify').detail!, /"Spotify Your Spotify data is ready to download/);
  assert.match(find(s, 'spotify').detail!, /check your email or Spotify to be sure/);
  assert.ok(opened().includes('notify: Your Spotify data looks ready → spotify'), 'and clicking it opens Spotify');
  await selectSource(run.page, 'spotify');
  await shot(run.page, 'looks-ready');
  // The setting that lets the iPhone's notifications in, with why.
  assert.equal(find(s, 'iphone_notifications').section, 'todo');
  await act(run.page, 'iphone_notifications', 'open-notification-settings');
  assert.ok(opened().includes('x-apple.systempreferences:com.apple.Notifications-Settings.extension'));
});

test('no real site is opened in tests, and the UI stayed error-free', async () => {
  const s = await snap(run.page);
  const pages = opened().filter((l) => l.startsWith('http'));
  assert.ok(pages.length >= 2 && pages.every((l) => new URL(l).hostname.endsWith('.example')), pages.join('\n'));
  assert.equal(s.readOnly, false);
  assert.deepEqual(run.errors, []);
});
