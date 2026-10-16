// Homecoming at work with its window closed: what the menu bar item lists as needing you, and whether it opens at login.
// Pure, so the tests can check it without Electron (main.ts builds the menu and sets the login item from these).

import type { Settings, SourceView } from '../shared/types.ts';

const clip = (t: string, n = 60) => (t.length > n ? `${t.slice(0, n - 1)}…` : t);

// What needs you, most pressing first, as the Dock badge counts it: Claude's questions as such, the rest by their status.
export function trayNeeds(views: SourceView[]): { id: string; label: string }[] {
  return views.filter((v) => v.section === 'needs' && !v.blockedBy && !v.optional)
    .sort((a, b) => a.priority - b.priority)
    .map((v) => ({ id: v.id, label: clip(v.status.startsWith('Needs you') ? `Claude needs you for ${v.name}` : `${v.name}: ${v.status}`) }));
}

// Opening at login is its own choice; until it's made, it goes with keeping working when the window is closed (on for the
// packaged app).
export function loginItemWanted(s: Settings, packaged: boolean): boolean {
  return s.openAtLogin ?? s.background ?? packaged;
}
