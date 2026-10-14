import { MAC_CONNECTORS } from '../../src/shared/catalog.ts';
import type { StatusInput } from '../../src/shared/status.ts';
import { computeSources } from '../../src/shared/status.ts';
import type { AppState, ManifestEntry, Probe, SourceView, Stats } from '../../src/shared/types.ts';
import { defaultState } from '../../src/main/store.ts';

export const NOW = new Date('2026-10-08T12:00:00Z');
export const H = 3600_000;

export function hoursAgo(h: number): string {
  return new Date(NOW.getTime() - h * H).toISOString();
}

export function probe(over: Partial<Probe> = {}): Probe {
  return {
    time: NOW.toISOString(), home: '/h', repo: '/r',
    python: { path: '/usr/bin/python3', version: '3.14.0', cryptography: true, pypdf: true },
    fda: true, fda_path: '/h/Library/Messages/chat.db',
    sources: Object.fromEntries(MAC_CONNECTORS.map((c) => [c, 'ok'])),
    corpus: { path: '/c/corpus', exists: true, real_path: '/c/corpus', in_icloud: false, free_bytes: 100e9, total_bytes: 500e9 },
    identity: { names: ['Ada Lovelace'], emails: ['ada@example.com'], usernames: [], phones: [] },
    identity_suggestion: null, backups: [], mirror: null, keychain_password: false, ileapp_installed: true, mailbox_sources: [],
    retention: { claude: { present: true, days: 36500 }, messages: { readable: true, value: 0 }, safari: { readable: true, value: 365000 } },
    ...over,
  };
}

export function stats(manifest: Record<string, Partial<ManifestEntry>> = {}, years: Stats['years'] = {}): Stats {
  const m: Stats['manifest'] = {};
  for (const [k, v] of Object.entries(manifest)) m[k] = { count: 0, ran_at: hoursAgo(1), ...v };
  return { manifest: m, years, db_mtime: 1, manifest_mtime: 1 };
}

export function state(fn?: (s: AppState) => void): AppState {
  const s = defaultState();
  s.identityDismissed = s.identityDismissed ?? [];
  fn?.(s);
  return s;
}

export function input(over: Partial<StatusInput> = {}): StatusInput {
  return { probe: probe(), stats: stats(), state: state(), jobs: [], now: NOW, ...over };
}

export function views(over: Partial<StatusInput> = {}): SourceView[] {
  return computeSources(input(over));
}

export function view(id: string, over: Partial<StatusInput> = {}): SourceView {
  const v = views(over).find((x) => x.id === id);
  if (!v) throw new Error(`no view ${id}`);
  return v;
}

export function actionIds(v: SourceView): string[] {
  return v.actions.map((a) => a.id);
}
