// Ask for Everything: the exports still to ask for, sorted by who does them. Claude asks for the ones Chrome is signed
// in to, or can't tell (it checks, and stops if it isn't), services you added included when their export page is
// known; you sign in to the rest first, once, and Claude does those too. What Claude in Chrome isn't allowed on is
// yours; a service you added with no page Claude can use, but an address, gets a request by email. Pure, for the tests.

import { BY_ID, type Source } from './catalog.ts';
import type { SourceState, SourceView } from './types.ts';

export interface RequestPlan {
  claude: SourceView[]; // Claude asks for these on its own
  signIn: SourceView[]; // Chrome isn't signed in: sign in first, then Claude asks
  yourself: SourceView[]; // Claude in Chrome isn't allowed there, or AI is off: their pages
  email: SourceView[]; // a request by email (services you added)
}

export function requestPlan(views: SourceView[]): RequestPlan {
  const plan: RequestPlan = { claude: [], signIn: [], yourself: [], email: [] };
  for (const v of views) {
    if (!v.toRequest) continue;
    const src = BY_ID[v.id];
    // Claude can do it (a built-in export, or a service you added with its export page): it asks, once Chrome's signed in.
    if (!src?.agentBlocked && v.actions.some((a) => a.id === 'agent-request')) (v.signIn?.state === 'out' ? plan.signIn : plan.claude).push(v);
    else if (src?.custom && v.requestEmail) plan.email.push(v);
    else plan.yourself.push(v);
  }
  return plan;
}

// When an export's download link stops working: from its ready email (or when it should have been ready), plus the days
// the service keeps it. Never, for one that doesn't say. Downloads go soonest first.
export function linkExpires(src: Source | undefined, st: SourceState | undefined): number {
  if (!src?.expiresDays || !st?.requestedAt) return Infinity;
  const ready = st.readySignal?.at ? Date.parse(st.readySignal.at) : Date.parse(st.requestedAt) + (src.waitHours?.[0] ?? 0) * 3600_000;
  return ready + src.expiresDays * 24 * 3600_000;
}

const lower = (s?: string) => (s ? s.charAt(0).toLowerCase() + s.slice(1).replace(/\.$/, '') : '');

// The one notification once Claude has been through them all: how many it asked for, and what needs you, by name.
// Nothing to say when every one was stopped.
export function batchSummary(results: { name: string; status: string; note?: string }[], browser = 'Chrome'): { title: string; body: string } | null {
  const asked = results.filter((r) => r.status === 'requested');
  const you = results.filter((r) => r.status === 'needs_you' || r.status === 'failed');
  if (!asked.length && !you.length) return null;
  const title = asked.length ? `Claude asked for ${asked.length} of your exports` : 'Claude couldn\'t ask for your exports';
  const body = you.length
    ? `${you.length} ${you.length === 1 ? 'needs' : 'need'} you: ${you.map((r) => `${r.name} (${lower(r.note) || `have a look in ${browser}`})`).join('; ')}.`
    : 'Each one is imported when it comes.';
  return { title, body };
}
