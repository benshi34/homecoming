// Launches the real Electron app against a sandbox (fake HOME, throwaway corpus, fake Downloads, fresh app
// state) and drives it with Playwright. A tiny local site stands in for the export pages.

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import electronPath from 'electron';
import { _electron as electron, type ElectronApplication, type Page } from 'playwright-core';
import type { Snapshot, SourceView } from '../../src/shared/types.ts';

export const DESKTOP = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
export const REPO = path.dirname(DESKTOP);
export const RESULTS = path.join(DESKTOP, 'test-results');
fs.mkdirSync(RESULTS, { recursive: true });
const PY = process.env.UMP_PYTHON || '/usr/local/bin/python3';

export interface Sandbox {
  root: string;
  home: string;
  corpus: string;
  downloads: string;
  userData: string;
  exports: Record<string, string>;
  cleanup(): void;
}

export function sandbox(opts: { identity?: boolean } = {}): Sandbox {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ump-e2e-'));
  const home = path.join(root, 'home');
  const corpus = path.join(root, 'corpus');
  const userData = path.join(root, 'userData');
  fs.mkdirSync(corpus, { recursive: true });
  const fixtures = path.join(DESKTOP, 'test/fixtures/make_fixtures.py');
  execFileSync(PY, [fixtures, 'home', home]);
  const exports = JSON.parse(execFileSync(PY, [fixtures, 'exports', path.join(root, 'exports')]).toString());
  if (opts.identity) {
    fs.writeFileSync(path.join(corpus, 'identity.json'), JSON.stringify({ names: ['Ada Lovelace'], emails: ['ada@example.com'], usernames: ['ada_l'], phones: [] }));
  }
  return {
    root, home, corpus, userData, downloads: path.join(home, 'Downloads'), exports,
    cleanup() {
      execFileSync('chmod', ['-R', 'u+rwx', root]);
      fs.rmSync(root, { recursive: true, force: true });
    },
  };
}

export interface Running {
  app: ElectronApplication;
  page: Page;
  close(): Promise<void>;
  errors: string[];
}

// Tests start in the main window unless they ask for the Setup Assistant (assistant: true).
export async function launch(env: Record<string, string>, opts: { assistant?: boolean } = {}): Promise<Running> {
  if (!opts.assistant && env.UMP_USER_DATA) {
    const f = path.join(env.UMP_USER_DATA, 'state.json');
    if (!fs.existsSync(f)) {
      fs.mkdirSync(env.UMP_USER_DATA, { recursive: true });
      fs.writeFileSync(f, JSON.stringify({ version: 1, onboarding: { done: true } }));
    }
  }
  const base = Object.fromEntries(Object.entries(process.env).filter(([k]) => !k.startsWith('UMP_') && k !== 'CORPUS_DIR' && k !== 'ELECTRON_RUN_AS_NODE')) as Record<string, string>;
  const app = await electron.launch({
    executablePath: electronPath as unknown as string,
    args: [DESKTOP],
    env: { ...base, UMP_SETTLE_MS: '300', UMP_POLL_MS: '250', UMP_HIDDEN: '1', ...env }, // off screen, so a test run doesn't take over the Mac
    timeout: 60_000,
  });
  const page = await app.firstWindow();
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
  await page.waitForSelector('[data-testid=app]', { timeout: 60_000 });
  return { app, page, errors, close: () => app.close() };
}

export function sandboxEnv(sb: Sandbox, extra: Record<string, string> = {}): Record<string, string> {
  return { HOME: sb.home, CORPUS_DIR: sb.corpus, UMP_DOWNLOADS: sb.downloads, UMP_USER_DATA: sb.userData,
    UMP_EXTERNAL_LOG: path.join(sb.userData, 'opened.txt'), UMP_APPLICATIONS: path.join(sb.home, 'Applications'),
    UMP_MAPPING_LIBRARY: path.join(sb.home, 'mapping-library'), ...extra };
}

export function snap(page: Page): Promise<Snapshot> {
  return page.evaluate(() => (window as unknown as { api: { snapshot(): Promise<Snapshot> } }).api.snapshot());
}

export function find(s: Snapshot, id: string): SourceView {
  const v = s.sources.find((x) => x.id === id);
  if (!v) throw new Error(`no source ${id}`);
  return v;
}

// Polls the app's own snapshot until the predicate holds.
export async function until(page: Page, what: string, pred: (s: Snapshot) => boolean, timeoutMs = 60_000): Promise<Snapshot> {
  const end = Date.now() + timeoutMs;
  let last: Snapshot | null = null;
  while (Date.now() < end) {
    last = await snap(page);
    if (pred(last)) return last;
    await new Promise((r) => setTimeout(r, 250));
  }
  const brief = last?.sources.map((v) => `${v.id}:${v.section}:${v.status}`).join('\n');
  throw new Error(`timed out waiting for ${what}\n${brief}\nlog:\n${last?.log.map((l) => l.line).slice(-30).join('\n')}`);
}

export function act(page: Page, sourceId: string, action: string, payload?: unknown) {
  return page.evaluate(([s, a, p]) => (window as unknown as { api: { action(...x: unknown[]): Promise<{ ok: boolean; error?: string; id?: string; ids?: string[] }> } }).api.action(s, a, p),
    [sourceId, action, payload] as const);
}

export async function shot(page: Page, name: string) {
  await page.waitForTimeout(250);
  await page.screenshot({ path: path.join(RESULTS, `${name}.png`) });
}

export async function selectSource(page: Page, id: string) {
  const s = await snap(page);
  const v = find(s, id);
  const nav = v.group === 'setup' && v.section !== 'needs' ? 'setup' : v.blockedBy ? 'needs' : v.section;
  await page.locator(`[data-testid=nav-${nav}]`).click();
  await page.locator(`[data-testid=row-${id}]`).first().click();
  await page.locator(`[data-testid=detail][data-source=${id}]`).waitFor({ timeout: 10_000 });
}

export async function clickAction(page: Page, action: string) {
  await page.locator(`[data-testid=detail] button[data-action=${action}]`).first().click();
}

export function readJson(p: string) {
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}
