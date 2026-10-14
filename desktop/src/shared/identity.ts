// "Who you are", assembled from evidence instead of memory. bridge.py finds candidates (Apple ID, the addresses
// Messages sends from, account exports...); this merges them with what's already confirmed in identity.json
// and decides what's new.

import type { Candidate, Identity } from './types.ts';

export type Kind = Candidate['kind'];
export const KINDS: { kind: Kind; field: keyof Identity; label: string; add: string }[] = [
  { kind: 'name', field: 'names', label: 'Names', add: 'Add a name' },
  { kind: 'email', field: 'emails', label: 'Email addresses', add: 'Add an email address' },
  { kind: 'username', field: 'usernames', label: 'Usernames', add: 'Add a username' },
  { kind: 'phone', field: 'phones', label: 'Phone numbers', add: 'Add a phone number' },
];

// Same normalization as bridge.py's Candidates.norm, so "+1 (415) 555-0100" and "4155550100" are one number.
export function normalize(kind: Kind, value: string): string {
  const v = value.trim();
  if (kind === 'email') return v.toLowerCase();
  if (kind === 'username') return v.replace(/^@/, '').toLowerCase();
  if (kind === 'phone') {
    const d = v.replace(/\D/g, '');
    return v.startsWith('+') ? `+${d}` : d.length === 10 ? `+1${d}` : `+${d}`;
  }
  return v.replace(/\s+/g, ' ').toLowerCase();
}

export const keyOf = (kind: Kind, value: string) => `${kind}:${normalize(kind, value)}`;

export function identityKeys(id: Identity | null | undefined): Set<string> {
  const out = new Set<string>();
  for (const k of KINDS) for (const v of id?.[k.field] ?? []) if (v) out.add(keyOf(k.kind, v));
  return out;
}

// Strong evidence for something not in identity.json that the person hasn't already said isn't them.
export function newCandidates(cands: Candidate[], id: Identity | null | undefined, dismissed: string[]): Candidate[] {
  const have = identityKeys(id);
  const no = new Set(dismissed);
  return cands.filter((c) => c.strong && !have.has(keyOf(c.kind, c.value)) && !no.has(keyOf(c.kind, c.value)));
}

export interface PickRow {
  key: string;
  kind: Kind;
  value: string;
  sources: { label: string; count?: number }[];
  checked: boolean; // the default
  isNew: boolean; // found since identity.json was last saved
  strong: boolean;
}

// Everything to show in the picker: candidates first (strongest evidence first), then confirmed values the
// evidence didn't turn up ("Added by you").
export function pickerRows(cands: Candidate[], id: Identity | null | undefined, dismissed: string[]): PickRow[] {
  const have = identityKeys(id);
  const no = new Set(dismissed);
  const fresh = !id || !(id.names?.length || id.emails?.length);
  const rows: PickRow[] = [];
  const seen = new Set<string>();
  for (const c of cands) {
    const key = keyOf(c.kind, c.value);
    if (seen.has(key)) continue;
    seen.add(key);
    const inId = have.has(key);
    rows.push({ key, kind: c.kind, value: c.value, sources: c.sources, strong: c.strong, isNew: !fresh && !inId && c.strong && !no.has(key),
      checked: inId || (c.strong && !no.has(key)) });
  }
  for (const k of KINDS) {
    for (const v of id?.[k.field] ?? []) {
      const key = keyOf(k.kind, v);
      if (!v || seen.has(key)) continue;
      seen.add(key);
      rows.push({ key, kind: k.kind, value: v, sources: [{ label: 'Added by you' }], strong: true, isNew: false, checked: true });
    }
  }
  return rows;
}

export function buildIdentity(rows: PickRow[], checked: Set<string>): Identity {
  const id: Identity = { names: [], emails: [], usernames: [], phones: [] };
  for (const r of rows) if (checked.has(r.key)) id[KINDS.find((k) => k.kind === r.kind)!.field].push(r.value);
  return id;
}

// "1 new email address and 1 new phone number"
export function describeNew(cands: Candidate[]): string {
  const n = (k: Kind) => cands.filter((c) => c.kind === k).length;
  const words: Record<Kind, [string, string]> = { name: ['name', 'names'], email: ['email address', 'email addresses'], username: ['username', 'usernames'], phone: ['phone number', 'phone numbers'] };
  const parts = KINDS.map((k) => k.kind).filter((k) => n(k)).map((k) => `${n(k)} new ${words[k][n(k) === 1 ? 0 : 1]}`);
  return parts.length <= 1 ? parts.join('') : `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}`;
}
