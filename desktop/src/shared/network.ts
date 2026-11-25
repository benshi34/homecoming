import type { Settings } from './types.ts';

// Connectors from other changes add their internet-facing sources here.
export const NETWORK_SOURCES: { id: string; name: string; hosts: string[]; what: string }[] = [
  { id: 'icloud-exports', name: 'Download iCloud exports', hosts: ['iCloud Drive'], what: 'Download export files that are not on this Mac yet.' },
  { id: 'machines', name: 'Other machines', hosts: ['your Tailscale machines and VMs, over ssh'],
    what: 'Reads the same sources on your other Macs and Linux machines.' },
];

// Mac sources that read nothing unless their switch in Network is on (and the internet is). While it's off they aren't
// due for a read (one that reads nothing would be due again at once), and with nothing read yet they're unavailable.
export const NEEDS_NETWORK: Record<string, string> = { machines: 'machines' };

export function networkOff(sourceId: string, settings: Partial<Pick<Settings, 'offline' | 'networkOn'>> | undefined): boolean {
  const need = NEEDS_NETWORK[sourceId];
  return !!need && (settings?.offline === true || !(settings?.networkOn ?? []).includes(need));
}

export const INTERNET_OFF = 'Homecoming is offline. Turn on Use the internet in General.';

export function networkFile(settings: Pick<Settings, 'offline' | 'networkOn'>): { offline: boolean; sources: Record<string, true> } {
  const allowed = new Set(NETWORK_SOURCES.map((source) => source.id));
  const sources: Record<string, true> = {};
  for (const id of Array.isArray(settings.networkOn) ? settings.networkOn : []) if (allowed.has(id)) sources[id] = true;
  return { offline: settings.offline === true, sources };
}
