// Render the production components: cached update controls must follow the current Network switch.
import assert from 'node:assert/strict';
import path from 'node:path';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import { buildSync } from 'esbuild';
import { createElement, type ComponentType } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { DEFAULT_ASK } from '../../src/shared/ask.ts';
import { INTERNET_OFF } from '../../src/shared/network.ts';
import type { Snapshot } from '../../src/shared/types.ts';

const require = createRequire(import.meta.url);
function renderer(file: string): Record<string, ComponentType<any>> {
  const built = buildSync({ entryPoints: [path.resolve(import.meta.dirname, `../../src/renderer/${file}.tsx`)],
    bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic',
    external: ['react', 'react-dom', 'react/jsx-runtime'] });
  const module = { exports: {} };
  new Function('require', 'module', 'exports', 'window', built.outputFiles[0].text)(require, module, module.exports, { api: {} });
  return module.exports;
}
const { UpdateSheet } = renderer('update_sheet');
const { GeneralPage } = renderer('general');

function snapshot(offline: boolean, failed = false): Snapshot {
  return { settings: { offline, autoRefresh: false, watchDownloads: false }, build: { version: '0.5.0' },
    ask: { settings: structuredClone(DEFAULT_ASK), installed: { codex: true, 'claude-code': true }, keys: { anthropic: false, openai: false } },
    setup: { mail: { accounts: [], checks: false, notifications: false } },
    update: { checks: true, checking: false, how: 'app', from: '~/homecoming',
      available: { version: '9.9.0', releases: [{ version: '9.9.0', text: [], bullets: ['A new version.'] }] },
      ...(failed ? { run: { state: 'failed', message: 'The update stopped before it finished.', log: [] } } : {}) },
  } as unknown as Snapshot;
}
function update(offline: boolean, failed = false) {
  return renderToStaticMarkup(createElement(UpdateSheet, { snap: snapshot(offline, failed), onClose() {} }));
}
function button(html: string, action: string) {
  const tag = html.match(new RegExp(`<button[^>]*data-action="${action}"[^>]*>`))?.[0];
  assert.ok(tag, `the ${action} button exists`);
  return tag;
}

test('Update and Try Again are disabled offline even for a release found earlier', () => {
  for (const failed of [false, true]) {
    const action = failed ? 'update-again' : 'update-start';
    const html = update(true, failed);
    assert.match(button(html, action), / disabled=""/, `${action} is disabled offline`);
    assert.ok(html.includes(INTERNET_OFF), 'the sheet says why');
    assert.doesNotMatch(button(update(false, failed), action), / disabled=/, `${action} is available online`);
  }
});

test('Network lists iCloud downloads, sign-in and links, with iCloud downloads off until allowed', () => {
  const html = renderToStaticMarkup(createElement(GeneralPage, { snap: snapshot(true), onAssistant() {}, onExport() {}, onWhatsNew() {}, onUpdate() {} }));
  assert.match(html, /Download iCloud exports/);
  assert.match(html, /iCloud Drive/);
  assert.match(html, /Sign-in and web links/);
  assert.match(html, /Ask and export mappings/);
  assert.match(html, /<button[^>]*aria-checked="false"[^>]*data-testid="toggle-network-icloud-exports"[^>]*disabled=""/);
});
