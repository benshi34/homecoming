// Your Setup: what the app found on this Mac (browsers, Mail, the phone region, who you are), and what the person
// chose instead. Pure, so the source list, the main process and the Your Setup page agree on the same defaults.

import type { SignIn } from './ask.ts';

// bridge.py probe "browsers" (connectors/browsers.py): installed, or with history here.
export interface BrowserFound { id: string; name: string; app: string | null; profiles: number; history: boolean; read: boolean; claude: boolean; default: boolean }
// bridge.py probe "phone" (connectors/phones.py): the region numbers without a country code are read in.
export interface PhoneInfo { region: string; mac: string | null; chosen: boolean; cc: string | null; trunk: string | null; intl: string; known: boolean; regions: string[] }

// The browsers Claude in Chrome works in (code.claude.com/docs/en/chrome), in the order one is picked when the
// default browser isn't one of them.
export const CLAUDE_BROWSERS = ['chrome', 'edge', 'brave', 'arc', 'vivaldi', 'opera'];
export const CLAUDE_BROWSER_NAMES = 'Chrome, Edge, Brave, Arc, Vivaldi or Opera';

// Where Do It for Me works: the one chosen, else the default browser if Claude can work in it, else the first here.
export function agentBrowser(found: BrowserFound[], chosen?: string): BrowserFound | null {
  const ok = found.filter((b) => b.claude);
  return ok.find((b) => b.id === chosen) ?? ok.find((b) => b.default) ?? CLAUDE_BROWSERS.map((id) => ok.find((b) => b.id === id)).find(Boolean) ?? null;
}

// The Mac's default browser among those found: as Launch Services says (the probe), else the one whose app has the name
// macOS gives for web links ("Google Chrome" is Chrome), so the default is one browser with one name everywhere.
export function macDefault(found: BrowserFound[], appName?: string | null): BrowserFound | null {
  const named = (b: BrowserFound) => !!appName && !!b.app && b.app.replace(/\/+$/, '').split('/').pop()!.replace(/\.app$/, '') === appName;
  return found.find((b) => b.default) ?? found.find(named) ?? null;
}

// Where export pages open: the browser chosen, if its app is here; null means the Mac's default.
export function pageBrowser(found: BrowserFound[], chosen?: string): BrowserFound | null {
  return found.find((b) => b.id === chosen && b.app) ?? null;
}

// How Claude Code is signed in, in words, for one that isn't a claude.ai account.
const HOW: Record<string, string> = { api_key: 'an API key', api_key_helper: 'an API key', oauth_token: 'a long-lived token', third_party: 'a cloud provider (Bedrock, Vertex or Foundry)' };

// soon: with fix 'provider', Do It for Me is coming with the AI picked (Codex); without, it can't be (an API key).
export interface AgentReady { ok: boolean; why?: string; fix?: 'install' | 'browser' | 'sign-in' | 'plan' | 'provider'; soon?: boolean }

// Do It for Me follows the AI picked in AI Settings, as everything AI does: for now only Claude Code with a claude.ai
// account can work in a browser (Claude in Chrome). With Codex it's coming, and says so; with an Anthropic API key,
// Claude Code keeps the browser off, so it points to the claude.ai account instead.
export function agentProvider(provider: string, label: string): AgentReady {
  if (provider === 'claude-code') return { ok: true };
  if (provider === 'anthropic') {
    return { ok: false, fix: 'provider',
      why: 'Do It for Me needs Claude Code signed in with your claude.ai account: with an API key, Claude Code can\'t work in your browser. Pick your claude.ai account in AI Settings to use it; each export\'s page has the steps to do it yourself.' };
  }
  return { ok: false, fix: 'provider', soon: true,
    why: `Do It for Me doesn't work with ${label} yet: it's coming soon. For now it works with Claude Code signed in with your claude.ai account (AI Settings), and each export's page has the steps to do it yourself.` };
}

// Whether Do It for Me can run here, and if not, what's missing in a sentence: Claude Code, a browser the extension
// works in, and a claude.ai sign-in on a paid plan (with an API key or a token, Claude Code keeps the browser off).
// signIn: what Claude Code says of itself; unknown (not asked yet, or an older Claude Code) doesn't stop it.
export function agentReady(o: { claudeCode: boolean; browser: BrowserFound | null; signIn?: SignIn }): AgentReady {
  if (!o.claudeCode) return { ok: false, why: 'Needs Claude Code on this Mac, signed in with your claude.ai account.', fix: 'install' };
  if (!o.browser) return { ok: false, why: `Needs ${CLAUDE_BROWSER_NAMES}: the Claude in Chrome extension works only in those.`, fix: 'browser' };
  const s = o.signIn;
  if (s?.state === 'out') return { ok: false, why: 'Claude Code isn\'t signed in. Sign in with your claude.ai account (Pro, Max, Team or Enterprise).', fix: 'sign-in' };
  if (s?.state === 'in' && s.how && s.how !== 'claude.ai') {
    return { ok: false, why: `Claude Code is signed in with ${HOW[s.how] ?? s.how}, and Claude works in a browser only with a claude.ai account on Pro, Max, Team or Enterprise.`, fix: 'plan' };
  }
  if (s?.state === 'in' && /^free\b/i.test(s.plan ?? '')) return { ok: false, why: 'Claude works in a browser only on a paid claude.ai plan: Pro, Max, Team or Enterprise.', fix: 'plan' };
  return { ok: true };
}

// The addresses Claude may look in for "your data is ready" emails: yours, less the ones you turned off.
// The title of what says so: coming, or not with this one.
export const notYetTitle = (r: AgentReady) => (r.soon ? 'Do It for Me isn\'t here yet with this AI' : 'Do It for Me needs your claude.ai account');

export const inboxesOn = (emails: string[], off: string[] = []) => emails.filter((e) => !off.includes(e.trim().toLowerCase()));

// What Claude is told of your inboxes (AI Settings' list): only those on, and the one the service said it writes to
// unless that one's off. With no addresses known, it may look in any inbox signed in to the browser (and it says so).
export function claudeInboxes(emails: string[], off: string[] = [], to?: string): { inboxes?: string[]; to?: string } {
  const said = to && !off.includes(to.trim().toLowerCase()) ? to : undefined;
  if (!emails.length) return { to: said };
  const on = inboxesOn(emails, off);
  return { inboxes: said && !on.some((e) => e.toLowerCase() === said.toLowerCase()) ? [...on, said] : on, to: said };
}

// What Your Setup tells the connectors (connectors/browsers.py, phones.py) and bridge.py's ready checks.
export function setupEnv(s: { historyOff?: string[]; phoneRegion?: string; mailChecks?: boolean; notificationChecks?: boolean }): Record<string, string> {
  return {
    UMP_BROWSERS_SKIP: (s.historyOff ?? []).join(','),
    ...(s.phoneRegion ? { UMP_PHONE_REGION: s.phoneRegion } : {}),
    ...(s.mailChecks === false ? { UMP_READY_MAIL: '0' } : {}),
    ...(s.notificationChecks === false ? { UMP_READY_NOTIFICATIONS: '0' } : {}),
  };
}
