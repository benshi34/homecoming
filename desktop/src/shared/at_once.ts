// How many services Do It for Me works on at once (AI Settings), each in a tab group of its own in the browser: 3
// unless set, 1 to 5. More is quicker, and uses more of the person's Claude usage at a time.
export const AT_ONCE = { min: 1, max: 5, usual: 3 };

export function agentsAtOnce(s?: { agentsAtOnce?: unknown }): number {
  const n = s?.agentsAtOnce;
  return typeof n === 'number' && Number.isFinite(n) ? Math.min(AT_ONCE.max, Math.max(AT_ONCE.min, Math.round(n))) : AT_ONCE.usual;
}
