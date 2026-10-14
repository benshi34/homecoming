import type { AskConversation, AskEvent, AskProvider, AskSettings, AskSummary } from '../shared/ask.ts';
import type { ExploreProgress } from '../shared/explore.ts';
import type { DirectoryEntry, Onboarding, Settings, Snapshot } from '../shared/types.ts';

export interface Api {
  snapshot(): Promise<Snapshot>;
  onSnapshot(cb: (s: Snapshot) => void): () => void;
  onToast(cb: (t: { text: string; kind: string }) => void): () => void;
  onMenu(cb: (cmd: string) => void): () => void;
  action(sourceId: string, action: string, payload?: unknown): Promise<{ ok: boolean; error?: string; id?: string; ids?: string[]; data?: unknown }>;
  dropFiles(files: File[], sourceId: string | null): Promise<{ ok: boolean; error?: string }>;
  settings(patch: Partial<Settings>): Promise<Settings>;
  onboarding(patch: Partial<Onboarding>): Promise<Onboarding>;
  jobLog(sourceId: string): Promise<string[]>;
  directory(): Promise<DirectoryEntry[]>;
  icons(): Promise<Record<string, [string, string]>>; // brand logos: slug or source id -> [hex, svg path]
  ask: AskApi;
  explore<T = unknown>(op: string, args?: unknown[]): Promise<T | { error: string }>; // shared/explore.ts has the shapes
  onExploreProgress(cb: (p: ExploreProgress) => void): () => void;
  onAsk(cb: (channel: 'ask-event' | 'ask-done', payload: AskPush) => void): () => void;
}

export type AskPush = { id: string; turn: number; event?: AskEvent; conversation?: AskConversation };

// Overloads of the one "ask" channel (main.ts askOp).
export interface AskApi {
  (op: { op: 'list' }): Promise<AskSummary[]>;
  (op: { op: 'get'; id: string }): Promise<{ conversation: AskConversation | null; running: boolean } | null>;
  (op: { op: 'ask'; id: string | null; question: string }): Promise<{ id: string; error?: undefined } | { error: string; provider?: AskProvider; id?: undefined }>;
  (op: { op: 'stop' | 'remove'; id: string }): Promise<unknown>;
  (op: { op: 'settings'; patch: Partial<AskSettings> }): Promise<AskSettings>;
  (op: { op: 'confirm-retention'; provider: AskProvider }): Promise<AskSettings>;
  (op: { op: 'set-key'; kind: 'anthropic' | 'openai'; key: string | null }): Promise<{ ok?: boolean; error?: string }>;
  (op: { op: 'models'; provider: AskProvider }): Promise<string[]>;
  (op: { op: 'record'; rowid: number }): Promise<AskRecord | null>;
  (op: { op: 'open-link'; url: string }): Promise<null>;
}

export interface AskRecord {
  rowid: number; source: string; kind: string; ts: string | null; ts_end?: string | null; author?: string | null; is_me?: number;
  thread_name?: string | null; participants?: string | null; title?: string | null; text?: string | null; url?: string | null;
  meta: Record<string, unknown>; files: string[];
}

declare global {
  interface Window {
    api: Api;
  }
}

export const api = window.api;
