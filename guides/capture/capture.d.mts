// Types for capture.mjs, for the desktop typecheck (its unit test imports it)
export class ActionRefusedError extends Error {}
export function isRefusedAction(targetOrAction: unknown): boolean;
export function normalizeRegion(region: unknown): { css?: string; text?: string; pad: number } | null;
export function validateShots(shots: Record<string, unknown>, catalog?: unknown): string[];
export function runCapture(opts: Record<string, unknown>): Promise<{ id: string; error?: string; hidden: number }[]>;
