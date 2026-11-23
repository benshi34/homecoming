import type { Settings } from './types.ts';

// Connectors from other changes add their internet-facing sources here.
export const NETWORK_SOURCES: { id: string; name: string; hosts: string[]; what: string }[] = [
  { id: 'icloud-exports', name: 'Download iCloud exports', hosts: ['iCloud Drive'], what: 'Download export files that are not on this Mac yet.' },
];

export const INTERNET_OFF = 'Homecoming is offline. Turn on Use the internet in General.';

export function networkFile(settings: Pick<Settings, 'offline' | 'networkOn'>): { offline: boolean; sources: Record<string, true> } {
  const allowed = new Set(NETWORK_SOURCES.map((source) => source.id));
  const sources: Record<string, true> = {};
  for (const id of Array.isArray(settings.networkOn) ? settings.networkOn : []) if (allowed.has(id)) sources[id] = true;
  return { offline: settings.offline === true, sources };
}
