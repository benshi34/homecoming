#!/usr/bin/env node
/**
 * Capture the screenshots and short recordings used by the export guides.
 *
 * This file intentionally has no dependencies of its own. It uses the copy of
 * playwright-core installed for the desktop app and the installed Google Chrome.
 */
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import readline from 'node:readline';
import { chromium } from '../../desktop/node_modules/playwright-core/index.mjs';
import { CATALOG } from '../../desktop/src/shared/catalog.ts';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_SHOTS = path.join(HERE, 'shots.json');
const DEFAULT_OUTPUT_ROOT = path.resolve(HERE, '..');
const ACTION_TIMEOUT = 15_000;
const REFUSED_ACTION_RE = /create export|start export|request (data|archive)|submit|send|download|delete|deactivate|confirm|save|log ?out|sign ?out|post|pay|buy/i;

export class ActionRefusedError extends Error {
  constructor(action, targetText) {
    const what = targetText || describeAction(action);
    super(`Refused unsafe action: ${what}`);
    this.name = 'ActionRefusedError';
    this.action = action;
    this.targetText = targetText || what;
  }
}

const describeAction = (action) => {
  if (!action || typeof action !== 'object') return String(action);
  if (action.click) return `click ${JSON.stringify(action.click)}`;
  if (action.scroll) return `scroll ${JSON.stringify(action.scroll)}`;
  if (action.wait !== undefined) return `wait ${action.wait}ms`;
  return JSON.stringify(action);
};

const targetStrings = (target) => {
  if (!target || typeof target !== 'object') return [];
  const values = [];
  for (const key of ['role', 'name', 'text', 'css']) {
    if (typeof target[key] === 'string') values.push(target[key]);
  }
  return values;
};

/** Return the matching refusal phrase, or null for a harmless target. */
export function refusalReason(targetOrAction) {
  const target = targetOrAction?.click ?? targetOrAction?.scroll ?? targetOrAction;
  const match = targetStrings(target).find((value) => REFUSED_ACTION_RE.test(value));
  return match ?? null;
}

/** Pure refusal check used by the CLI and unit tests. */
export function isRefusedAction(targetOrAction) {
  return refusalReason(targetOrAction) !== null;
}

export const isDangerousTarget = isRefusedAction;
export const isRefused = isRefusedAction;
export const resolveHide = normalizeHide;

function assertSafeTarget(action, targetText = '') {
  const reason = refusalReason(action) || (REFUSED_ACTION_RE.test(targetText) ? targetText : null);
  if (reason) throw new ActionRefusedError(action, reason);
}

export function normalizeRegion(region) {
  if (region === null || region === undefined) return null;
  if (typeof region !== 'object') throw new TypeError('region must be null, {css}, or {text, pad}');
  if (typeof region.css === 'string' && region.css.trim()) return { css: region.css, pad: 0 };
  if (typeof region.text === 'string' && region.text.trim()) {
    const pad = Number(region.pad ?? 0);
    if (!Number.isFinite(pad) || pad < 0) throw new TypeError('region.pad must be a non-negative number');
    return { text: region.text, pad };
  }
  throw new TypeError('region must have a non-empty css or text');
}

function sourceById(catalog) {
  return new Map((catalog ?? []).map((source) => [source.id, source]));
}

/** Validate a shots manifest against catalog source ids and step counts. */
export function normalizeHide(hide) {
  if (hide === undefined || hide === null) return [];
  const values = Array.isArray(hide) ? hide : String(hide).split(',');
  return [...new Set(values.map((value) => String(value).trim().toLocaleLowerCase()).filter(Boolean))];
}

export function validateShots(shots, catalog = CATALOG) {
  const errors = [];
  if (!shots || typeof shots !== 'object' || Array.isArray(shots)) return ['shots.json must be an object keyed by source id'];
  const sources = sourceById(catalog);
  for (const [id, entry] of Object.entries(shots)) {
    const source = sources.get(id);
    if (!source) {
      errors.push(`${id}: not in catalog`);
      continue;
    }
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
      errors.push(`${id}: entry must be an object`);
      continue;
    }
    if (entry.manual) {
      if (entry.steps !== undefined && !Array.isArray(entry.steps)) errors.push(`${id}: manual steps must be an array`);
      continue;
    }
    if (source.url && !entry.url) errors.push(`${id}: url is required`);
    if (source.url && entry.url && entry.url !== source.url) errors.push(`${id}: url does not match catalog`);
    if (!Array.isArray(entry.viewport) || entry.viewport.length !== 2 || entry.viewport.some((x) => !Number.isInteger(x) || x <= 0)) {
      errors.push(`${id}: viewport must be [positive integer width, positive integer height]`);
    }
    if (!Array.isArray(source.steps)) {
      errors.push(`${id}: catalog source has no steps`);
    }
    if (!Array.isArray(entry.steps)) {
      errors.push(`${id}: steps must be an array`);
    } else {
      const seen = new Set();
      for (const item of entry.steps) {
        if (!item || typeof item !== 'object') {
          errors.push(`${id}: each step entry must be an object`);
          continue;
        }
        if (!Number.isInteger(item.step) || item.step < 0 || item.step >= (source.steps?.length ?? 0)) {
          errors.push(`${id}: step ${item.step} is outside catalog steps`);
        } else if (seen.has(item.step)) {
          errors.push(`${id}: step ${item.step} appears more than once`);
        } else {
          seen.add(item.step);
        }
        if (typeof item.file !== 'string' || !item.file.trim()) errors.push(`${id}: step ${item.step} has no file`);
        else { try { safeOutputFile(path.join(DEFAULT_OUTPUT_ROOT, id), item.file); } catch (error) { errors.push(`${id}: step ${item.step}: ${error.message}`); } }
        if (item.actions !== undefined && !Array.isArray(item.actions)) errors.push(`${id}: step ${item.step} actions must be an array`);
        try { normalizeRegion(item.region ?? null); } catch (error) { errors.push(`${id}: step ${item.step}: ${error.message}`); }
      }
      if (source.steps && seen.size !== source.steps.length) errors.push(`${id}: expected ${source.steps.length} step entries, got ${seen.size}`);
    }
    if (entry.clip !== undefined) {
      if (!entry.clip || typeof entry.clip !== 'object') errors.push(`${id}: clip must be an object`);
      else if (typeof entry.clip.file !== 'string' || !entry.clip.file.trim()) errors.push(`${id}: clip has no file`);
      else { try { safeOutputFile(path.join(DEFAULT_OUTPUT_ROOT, id), entry.clip.file); } catch (error) { errors.push(`${id}: clip: ${error.message}`); } }
      if (entry.clip && entry.clip.actions !== undefined && !Array.isArray(entry.clip.actions)) errors.push(`${id}: clip actions must be an array`);
    }
  }
  return errors;
}

export function assertValidShots(shots, catalog = CATALOG) {
  const errors = validateShots(shots, catalog);
  if (errors.length) throw new Error(`Invalid shots.json:\n${errors.map((error) => `- ${error}`).join('\n')}`);
  return shots;
}

function locatorForTarget(page, target) {
  if (target?.role && target?.name !== undefined) return page.getByRole(target.role, { name: target.name, exact: true }).first();
  if (target?.text !== undefined) return page.getByText(target.text, { exact: true }).first();
  if (target?.css !== undefined) return page.locator(target.css).first();
  throw new TypeError(`Target must be {role,name}, {text}, or {css}: ${JSON.stringify(target)}`);
}

async function targetText(locator) {
  return locator.evaluate((element) => {
    const el = /** @type {HTMLElement} */ (element);
    return [el.getAttribute('aria-label'), el.getAttribute('title'), el.innerText, el.textContent, el.getAttribute('value')]
      .filter(Boolean).join(' ').replace(/\s+/g, ' ').trim();
  }).catch(() => '');
}

async function clickTarget(page, action) {
  const target = action.click;
  assertSafeTarget(action);
  const locator = locatorForTarget(page, target);
  await locator.waitFor({ state: 'visible', timeout: ACTION_TIMEOUT });
  const text = await targetText(locator);
  assertSafeTarget(action, text);
  await locator.click({ timeout: ACTION_TIMEOUT });
}

async function scrollTarget(page, action) {
  const target = action.scroll;
  const locator = locatorForTarget(page, target);
  await locator.waitFor({ state: 'visible', timeout: ACTION_TIMEOUT });
  await locator.scrollIntoViewIfNeeded({ timeout: ACTION_TIMEOUT });
}

export async function performAction(page, action) {
  if (!action || typeof action !== 'object') throw new TypeError(`Invalid action: ${JSON.stringify(action)}`);
  if (action.wait !== undefined) {
    const ms = Number(action.wait);
    if (!Number.isFinite(ms) || ms < 0) throw new TypeError(`Invalid wait: ${action.wait}`);
    await page.waitForTimeout(ms);
    return;
  }
  if (action.click) return clickTarget(page, action);
  if (action.scroll) return scrollTarget(page, action);
  throw new TypeError(`Unknown action: ${JSON.stringify(action)}`);
}

async function locatorForRegion(page, region) {
  const normalized = normalizeRegion(region);
  if (!normalized) return null;
  const locator = normalized.css !== undefined
    ? page.locator(normalized.css).first()
    : page.getByText(normalized.text, { exact: false }).first();
  await locator.waitFor({ state: 'visible', timeout: ACTION_TIMEOUT });
  return { locator, pad: normalized.pad };
}

/** Resolve a manifest region to a viewport CSS-pixel clip. */
export async function resolveRegion(page, region, viewport = page.viewportSize()) {
  const selected = await locatorForRegion(page, region);
  if (!selected) return null;
  const box = await selected.locator.boundingBox();
  if (!box) throw new Error(`Region is not visible: ${JSON.stringify(region)}`);
  const size = viewport ?? page.viewportSize();
  if (!size) throw new Error('Cannot resolve region without a viewport');
  const pad = selected.pad;
  const x = Math.max(0, box.x - pad);
  const y = Math.max(0, box.y - pad);
  const right = Math.min(size.width, box.x + box.width + pad);
  const bottom = Math.min(size.height, box.y + box.height + pad);
  if (right <= x || bottom <= y) throw new Error(`Region is outside the viewport: ${JSON.stringify(region)}`);
  return { x, y, width: right - x, height: bottom - y };
}

export function hideMatches(text, hide) {
  const lower = String(text ?? '').toLocaleLowerCase();
  return normalizeHide(hide).some((needle) => lower.includes(needle));
}

/**
 * Add the persistent blur style and mark matching text and small top-of-page
 * avatars. The returned count is also printed for each capture.
 */
export async function applyRedaction(page, hide) {
  const needles = normalizeHide(hide);
  return page.evaluate((needles) => {
    const marker = 'data-homecoming-capture-hidden';
    const styleId = 'homecoming-capture-redaction-style';
    if (!document.getElementById(styleId)) {
      const style = document.createElement('style');
      style.id = styleId;
      style.textContent = `[${marker}="true"] { filter: blur(8px) !important; }`;
      document.head.appendChild(style);
    }
    for (const el of document.querySelectorAll(`[${marker}="true"]`)) el.removeAttribute(marker);
    let count = 0;
    const seen = new Set();
    const mark = (el) => {
      if (!(el instanceof Element) || seen.has(el)) return;
      seen.add(el);
      el.setAttribute(marker, 'true');
      count += 1;
    };
    const lower = (value) => String(value ?? '').toLocaleLowerCase();
    const scan = () => {
      for (const el of document.querySelectorAll('*')) {
        const ownText = [...el.childNodes]
          .filter((node) => node.nodeType === Node.TEXT_NODE)
          .map((node) => node.textContent ?? '').join(' ');
        if (needles.some((needle) => lower(ownText).includes(needle))) mark(el);
      }
      for (const img of document.images) {
        const rect = img.getBoundingClientRect();
        if (rect.top < 120 && rect.bottom > 0 && rect.width <= 64 && rect.height <= 64) mark(img);
      }
    };
    scan();
    if (!globalThis.__homecomingCaptureRedactionObserver && document.documentElement) {
      const observer = new MutationObserver(scan);
      observer.observe(document.documentElement, { childList: true, subtree: true, characterData: true });
      globalThis.__homecomingCaptureRedactionObserver = observer;
    }
    return { count, selector: `[${marker}="true"]` };
  }, needles);
}

async function screenshot(page, file, region, hide) {
  await fs.mkdir(path.dirname(file), { recursive: true });
  const redaction = await applyRedaction(page, hide);
  const clip = await resolveRegion(page, region);
  const masks = redaction.count ? [page.locator(redaction.selector)] : [];
  await page.screenshot({
    path: file,
    clip: clip ?? undefined,
    mask: masks,
    maskColor: 'rgba(0,0,0,0)',
    scale: 'device',
    animations: 'disabled',
  });
  return redaction.count;
}

async function runActions(page, actions) {
  for (const action of actions ?? []) await performAction(page, action);
}

function safeProfileDir(profileDir) {
  if (!profileDir) throw new Error('--profile is required: use a dedicated Chrome user-data-dir');
  const resolved = path.resolve(profileDir.replace(/^~(?=$|\/)/, os.homedir()));
  const chromeRoot = path.resolve(os.homedir(), 'Library/Application Support/Google/Chrome');
  if (resolved === chromeRoot || resolved.startsWith(`${chromeRoot}${path.sep}`)) {
    throw new Error(`Refusing the real Chrome profile: ${resolved}`);
  }
  return resolved;
}

export function parseArgs(argv) {
  const args = { only: null, hide: [], headed: false, signIn: false, outputRoot: DEFAULT_OUTPUT_ROOT, shotsFile: DEFAULT_SHOTS };
  for (let i = 0; i < argv.length; i += 1) {
    const value = argv[i];
    if (value === '--profile') args.profileDir = argv[++i];
    else if (value === '--only') args.only = (argv[++i] ?? '').split(',').map((x) => x.trim()).filter(Boolean);
    else if (value === '--hide') args.hide = normalizeHide(argv[++i]);
    else if (value === '--headed') args.headed = true;
    else if (value === '--sign-in') args.signIn = true;
    else if (value === '--output') args.outputRoot = path.resolve(argv[++i]);
    else if (value === '--shots') args.shotsFile = path.resolve(argv[++i]);
    else if (value === '--help' || value === '-h') args.help = true;
    else throw new Error(`Unknown argument: ${value}`);
  }
  if (args.signIn) args.headed = true;
  return args;
}

async function waitForEnter(prompt) {
  if (!process.stdin.isTTY) throw new Error(`--sign-in needs an interactive stdin (${prompt})`);
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  await new Promise((resolve) => rl.question(`${prompt}\nPress Enter after signing in... `, resolve));
  rl.close();
}

async function gotoSource(page, url) {
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: ACTION_TIMEOUT });
  await page.waitForTimeout(250);
}

function sourceOutputDir(outputRoot, id) {
  return path.join(outputRoot, id);
}

function safeOutputFile(directory, file) {
  const resolved = path.resolve(directory, file);
  const root = path.resolve(directory);
  if (resolved !== root && !resolved.startsWith(`${root}${path.sep}`)) throw new Error(`Output file escapes source directory: ${file}`);
  return resolved;
}

async function renameVideo(videoPath, destination) {
  if (!videoPath) return false;
  await fs.mkdir(path.dirname(destination), { recursive: true });
  await fs.rm(destination, { force: true });
  await fs.rename(videoPath, destination);
  return true;
}

/** Capture one manifest source. Failures are returned on the report so callers can continue. */
export async function captureSource({ source, entry, profileDir, outputRoot = DEFAULT_OUTPUT_ROOT, hide = [], headed = false, signIn = false, browser = chromium }) {
  const report = { id: source.id, shots: [], hidden: 0, clip: null, error: null };
  const outDir = sourceOutputDir(outputRoot, source.id);
  await fs.mkdir(outDir, { recursive: true });
  let context;
  let video;
  try {
    const options = {
      channel: 'chrome',
      headless: !headed,
      viewport: { width: entry.viewport[0], height: entry.viewport[1] },
      deviceScaleFactor: 2,
      recordVideo: entry.clip ? { dir: outDir, size: { width: entry.viewport[0], height: entry.viewport[1] } } : undefined,
    };
    context = await browser.launchPersistentContext(profileDir, options);
    const page = context.pages()[0] ?? await context.newPage();
    if (entry.clip) video = page.video();
    await gotoSource(page, entry.url ?? source.url);
    await applyRedaction(page, hide);
    if (signIn) await waitForEnter(`${source.name}: ${entry.url ?? source.url}`);

    for (const shot of entry.steps ?? []) {
      await runActions(page, shot.actions);
      const file = safeOutputFile(outDir, shot.file);
      const count = await screenshot(page, file, shot.region ?? null, hide);
      report.hidden += count;
      report.shots.push({ step: shot.step, file, hidden: count });
      console.log(`${source.id} shot: ${path.relative(path.resolve(outputRoot, '..'), file)} (step ${shot.step}; hidden ${count})`);
    }
    if (entry.clip) await runActions(page, entry.clip.actions);
  } catch (error) {
    report.error = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
    console.error(`${source.id}: ${report.error}`);
  } finally {
    if (context) {
      try { await context.close(); } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        report.error ??= `Browser close failed: ${message}`;
      }
    }
    if (video) {
      try {
        const videoPath = await video.path();
        const clipFile = safeOutputFile(outDir, entry.clip.file);
        await renameVideo(videoPath, clipFile);
        report.clip = clipFile;
        console.log(`${source.id} clip: ${path.relative(path.resolve(outputRoot, '..'), clipFile)} (hidden ${report.hidden})`);
      } catch (error) {
        report.error ??= `Video save failed: ${error instanceof Error ? error.message : String(error)}`;
      }
    }
  }
  console.log(`${source.id}: hidden ${report.hidden} element(s)`);
  return report;
}

export async function runCapture({ profileDir, shots, catalog = CATALOG, outputRoot = DEFAULT_OUTPUT_ROOT, hide = [], headed = false, signIn = false, only = null, browser = chromium }) {
  const errors = validateShots(shots, catalog);
  if (errors.length) throw new Error(`Invalid shots.json:\n${errors.map((error) => `- ${error}`).join('\n')}`);
  const profile = safeProfileDir(profileDir);
  await fs.mkdir(profile, { recursive: true });
  const selected = only ? new Set(only) : null;
  const reports = [];
  for (const [id, entry] of Object.entries(shots)) {
    if (selected && !selected.has(id)) continue;
    const source = catalog.find((candidate) => candidate.id === id);
    if (!source) continue;
    if (entry.manual) {
      console.log(`${id}: manual source, skipped (${entry.note ?? 'capture it in the desktop app'})`);
      reports.push({ id, manual: true, shots: [], hidden: 0, clip: null, error: null });
      continue;
    }
    reports.push(await captureSource({ source, entry, profileDir: profile, outputRoot, hide, headed, signIn, browser }));
  }
  return reports;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log('Usage: node guides/capture/capture.mjs --profile <dir> [--only id,id] [--hide "Name,email"] [--headed] [--sign-in] [--output dir] [--shots file]');
    return;
  }
  const shots = JSON.parse(await fs.readFile(args.shotsFile, 'utf8'));
  assertValidShots(shots, CATALOG);
  const reports = await runCapture({ ...args, shots });
  if (reports.some((report) => report.error)) process.exitCode = 1;
}

const invoked = process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url;
if (invoked) main().catch((error) => { console.error(error instanceof Error ? error.message : error); process.exitCode = 1; });
