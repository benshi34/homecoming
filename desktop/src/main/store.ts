// The app's memory between launches: what was requested when, which steps are ticked, what was skipped,
// which downloads were seen. A JSON file in the app's data folder. Never holds passwords.

import fs from 'node:fs';
import path from 'node:path';
import { DEFAULT_ASK, LOCAL_SERVERS, PROVIDER, type AskSettings } from '../shared/ask.ts';
import type { AppState, ServiceEntry, SourceState } from '../shared/types.ts';

export function defaultState(): AppState {
  return {
    version: 1,
    sources: {},
    found: [],
    ignoredFiles: [],
    importedFiles: [],
    settings: { autoRefresh: true, watchDownloads: true },
    onboarding: { done: false },
    identityDismissed: [],
    services: [],
    ask: { ...DEFAULT_ASK, models: {}, retention: {} },
  };
}

export function fileKey(p: string, size: number): string {
  return `${p}|${size}`;
}

// Fill in anything an older or hand-edited file is missing, and drop what doesn't belong.
// Do It for Me, turned on before AI had its own switch, was agreeing to AI: it stays on.
function settingsFrom(d: AppState['settings'], r: unknown): AppState['settings'] {
  const s = { ...d, ...(r && typeof r === 'object' ? r : {}) } as AppState['settings'];
  if (s.agentExports && s.aiOn === undefined) Object.assign(s, { aiOn: true, aiAgreedAt: s.aiAgreedAt ?? new Date().toISOString() });
  return s;
}

export function normalize(raw: unknown): AppState {
  const d = defaultState();
  if (!raw || typeof raw !== 'object') return d;
  const r = raw as Partial<AppState>;
  return {
    version: 1,
    sources: r.sources && typeof r.sources === 'object' ? r.sources : {},
    found: Array.isArray(r.found) ? r.found : [],
    ignoredFiles: Array.isArray(r.ignoredFiles) ? r.ignoredFiles : [],
    importedFiles: Array.isArray(r.importedFiles) ? r.importedFiles : [],
    settings: settingsFrom(d.settings, r.settings),
    lastAutoRefresh: typeof r.lastAutoRefresh === 'string' ? r.lastAutoRefresh : undefined,
    onboarding: r.onboarding && typeof r.onboarding === 'object'
      ? { done: !!r.onboarding.done, step: typeof r.onboarding.step === 'string' ? r.onboarding.step : undefined,
        chosen: Array.isArray(r.onboarding.chosen) ? r.onboarding.chosen.filter((x) => typeof x === 'string') : undefined }
      : { done: false },
    identityDismissed: Array.isArray(r.identityDismissed) ? r.identityDismissed.filter((x) => typeof x === 'string') : [],
    services: Array.isArray(r.services) ? r.services.filter((x) => x && typeof x.id === 'string' && typeof x.name === 'string' && typeof x.folder === 'string')
      // Before 2026-10-09 an entry kept JustDeleteMe's link for the account, often the page that deletes it.
      .map(({ account: _, ...x }: ServiceEntry & { account?: unknown }) => ({ ...x, domains: Array.isArray(x.domains) ? x.domains : [] })) : [],
    ask: normalizeAsk(r.ask),
  };
}

function normalizeAsk(raw: unknown): AskSettings {
  const r = (raw && typeof raw === 'object' ? raw : {}) as Partial<AskSettings>;
  const strings = (o: unknown) => Object.fromEntries(Object.entries(o && typeof o === 'object' ? o : {})
    .filter(([k, v]) => k in PROVIDER && typeof v === 'string'));
  return {
    provider: typeof r.provider === 'string' && r.provider in PROVIDER ? r.provider : DEFAULT_ASK.provider,
    models: strings(r.models),
    localServer: typeof r.localServer === 'string' && r.localServer in LOCAL_SERVERS ? r.localServer : DEFAULT_ASK.localServer,
    localUrl: typeof r.localUrl === 'string' && r.localUrl ? r.localUrl : DEFAULT_ASK.localUrl,
    retention: strings(r.retention),
  };
}

export class Store {
  readonly file: string;
  state: AppState;
  private timer: NodeJS.Timeout | null = null;

  constructor(file: string) {
    this.file = file;
    this.state = this.load();
  }

  load(): AppState {
    let text: string;
    try {
      text = fs.readFileSync(this.file, 'utf8');
    } catch {
      return defaultState();
    }
    try {
      return normalize(JSON.parse(text));
    } catch {
      // Keep the unreadable file for inspection and start over.
      try {
        fs.renameSync(this.file, `${this.file}.corrupt-${Date.now()}`);
      } catch {
        /* ignore */
      }
      return defaultState();
    }
  }

  source(id: string): SourceState {
    return (this.state.sources[id] ??= {});
  }

  update(fn: (s: AppState) => void): void {
    fn(this.state);
    this.scheduleSave();
  }

  scheduleSave(): void {
    if (this.timer) return;
    this.timer = setTimeout(() => {
      this.timer = null;
      this.saveNow();
    }, 150);
  }

  saveNow(): void {
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    const tmp = `${this.file}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(this.state, null, 2));
    fs.renameSync(tmp, this.file);
  }
}
