import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import fsSync from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import { test } from 'node:test';
import { CATALOG } from '../../src/shared/catalog.ts';
import { ActionRefusedError, isRefusedAction, normalizeRegion, runCapture, validateShots } from '../../../guides/capture/capture.mjs';


function pngSize(file: string): [number, number] {
  const bytes = fsSync.readFileSync(file);
  assert.equal(bytes.toString('ascii', 1, 4), 'PNG');
  return [bytes.readUInt32BE(16), bytes.readUInt32BE(20)];
}

function chromeInstalled() {
  const executable = ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/usr/bin/google-chrome', '/usr/bin/chromium']
    .find((candidate) => fsSync.existsSync(candidate));
  if (!executable) return false;
  const probe = fsSync.mkdtempSync(path.join(os.tmpdir(), 'homecoming-chrome-probe-'));
  const result = spawnSync(executable, ['--headless=new', '--no-sandbox', '--disable-gpu', `--user-data-dir=${probe}`, '--dump-dom', 'data:text/html,ok'], {
    stdio: 'ignore', timeout: 5_000,
  });
  fsSync.rmSync(probe, { recursive: true, force: true });
  return result.status === 0;
}

test('refusal checks reject export and account-changing targets before a click', () => {
  assert.equal(isRefusedAction({ click: { role: 'button', name: 'Create export' } }), true);
  assert.equal(isRefusedAction({ click: { text: 'Request Data' } }), true);
  assert.equal(isRefusedAction({ click: { role: 'button', name: 'Deselect all' } }), false);
  assert.equal(isRefusedAction({ click: { css: '#safe' } }), false);
  assert.equal(ActionRefusedError.name, 'ActionRefusedError');
});

test('regions and manifest validation are pure and catalog-aware', () => {
  assert.deepEqual(normalizeRegion(null), null);
  assert.deepEqual(normalizeRegion({ css: '#main' }), { css: '#main', pad: 0 });
  assert.deepEqual(normalizeRegion({ text: 'Export', pad: 20 }), { text: 'Export', pad: 20 });
  assert.ok(validateShots({ missing: {} }, CATALOG).some((error) => error.includes('not in catalog')));
  assert.ok(validateShots({ google_takeout: { url: 'https://takeout.google.com/', viewport: [1, 1], steps: [{ step: 999, file: 'x.png' }] } }, CATALOG)
    .some((error) => error.includes('outside catalog steps')));
  assert.deepEqual(validateShots({ telegram: { manual: true, steps: [] } }, CATALOG), []);
});

test('fixture capture clicks a safe control, refuses Create export, redacts, and crops at 2x', { skip: !chromeInstalled() }, async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'homecoming-guide-capture-'));
  const html = path.join(root, 'fixture.html');
  const output = path.join(root, 'guides');
  const profile = path.join(root, 'chrome-profile');
  await fs.writeFile(html, `<!doctype html>
    <meta name="viewport" content="width=device-width">
    <style>body{margin:0;font:16px sans-serif}#region{display:inline-block;margin:40px;width:120px;height:30px;background:#def}</style>
    <img id="avatar" width="32" height="32" alt="avatar" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='32' height='32'%3E%3Crect width='32' height='32' fill='red'/%3E%3C/svg%3E">
    <div id="private">Ada Secret</div><div id="region">SAFE REGION</div>
    <button id="safe" onclick="document.body.dataset.clicked='yes'">Safe action</button>
    <button id="danger">Create export</button>`);
  const url = pathToFileURL(html).href;
  const catalog = [{ id: 'fixture', name: 'Fixture', url, steps: [{ text: 'safe' }, { text: 'danger' }] }];
  const shots = { fixture: {
    url, viewport: [500, 400],
    steps: [
      { step: 0, file: '0-safe.png', actions: [{ click: { role: 'button', name: 'Safe action' } }], region: { text: 'SAFE REGION', pad: 10 } },
      { step: 1, file: '1-danger.png', actions: [{ click: { role: 'button', name: 'Create export' } }], region: null },
    ],
  }};
  const shotsFile = path.join(root, 'shots.json');
  await fs.writeFile(shotsFile, JSON.stringify(shots));
  const loadedShots = JSON.parse(await fs.readFile(shotsFile, 'utf8'));
  const reports = await runCapture({ profileDir: profile, shots: loadedShots, catalog, outputRoot: output, hide: ['Ada Secret'] });
  assert.equal(reports.length, 1);
  assert.match(reports[0].error ?? '', /Create export/);
  assert.ok(reports[0].hidden >= 2, `expected hidden text and avatar, got ${reports[0].hidden}`);
  const shot = path.join(output, 'fixture', '0-safe.png');
  assert.ok(fsSync.existsSync(shot), 'safe screenshot was written before refusal');
  const [width, height] = pngSize(shot);
  assert.ok(width >= 200 && width <= 340, `cropped width ${width}`);
  assert.ok(height >= 60 && height <= 160, `cropped height ${height}`);
});
