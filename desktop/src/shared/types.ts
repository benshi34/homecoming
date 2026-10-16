// Shapes shared by the main process, the renderer and the tests.

import type { AskSettings, LocalStatus, SignIn } from './ask.ts';
import type { Inbox } from './inbox.ts';

export type Access = 'ok' | 'blocked' | 'absent';

export interface Backup {
  dir: string;
  id: string;
  device?: string | null;
  product?: string | null;
  ios?: string | null;
  date?: string | null;
  encrypted: boolean;
  finished: boolean;
  in_progress: boolean;
}

// Something that looks like it's you, and where it was seen (bridge.py identity-candidates).
export interface Candidate {
  kind: 'name' | 'email' | 'username' | 'phone';
  value: string;
  sources: { label: string; count?: number }[];
  strong: boolean;
}

export interface Identity {
  names: string[];
  emails: string[];
  usernames: string[];
  phones: string[];
}

export interface Probe {
  time: string;
  home: string;
  repo: string;
  python: { path: string; version: string; cryptography: boolean; pypdf: boolean };
  fda: boolean | null;
  fda_path: string | null;
  sources: Record<string, Access>;
  corpus: { path: string; exists: boolean; real_path: string; in_icloud: boolean; free_bytes: number; total_bytes: number };
  identity: Identity | null;
  identity_suggestion: Identity | null;
  backups: Backup[];
  mirror: { backup?: string; backed_up?: string; decrypted_at?: string; device?: string } | null;
  keychain_password: boolean;
  ileapp_installed: boolean;
  mailbox_sources: string[];
  // Notification Center: whether it can be read (Full Disk Access), and whether the iPhone's notifications reach this Mac.
  notifications?: { readable: boolean; iphone: boolean };
  retention: {
    claude: { present: boolean; days?: number | string | null; path?: string };
    messages: { readable: boolean; value: number | string | null };
    safari: { readable: boolean; value: number | string | null };
    iphone_messages?: { readable: boolean; value: number | string | null };
    codex?: { present: boolean };
    shell?: { shell: string | null; savehist?: number | null; extended?: boolean; rc?: string; ours?: boolean };
  };
}

export interface ManifestEntry {
  count: number;
  kinds?: Record<string, number>;
  first?: string | null;
  last?: string | null;
  ran_at?: string;
  avenue?: string;
  notes?: Record<string, unknown>;
}

export interface Stats {
  manifest: Record<string, ManifestEntry>;
  years: Record<string, Record<string, number>>;
  copies?: Record<string, Record<string, number>>; // source -> device copy ("iphone", "mac") -> records
  device?: string[]; // phone sources that are mostly phone internals (meta.tier = "device")
  facets?: Record<string, Record<string, number>>; // source -> value of its FACETS field (bridge.py) -> records
  db_mtime: number | null;
  manifest_mtime: number | null;
}

export interface Identified {
  path: string;
  name: string;
  kind: string | null;
  valid: boolean;
  size: number;
  reason?: string | null;
  export_id?: string | null;
  entries?: number;
  already_imported?: string | null; // the same bytes are already in corpus/imports/ (this path, relative)
  encrypted?: boolean; // a zip locked with a password (WeChat's): it has to be unzipped first
}

// Per-source memory the app keeps between launches (userData/state.json). Never holds passwords.
// "Do It for Me" (main/export_agent.ts): Claude Code requesting or downloading an export in the person's Chrome.
export type AgentMode = 'request' | 'download';
// stopped: by the person's Stop; dismissed: "I'll Do It Myself". Both are kept a while, so the page can say what to do next.
export type AgentStatus = 'queued' | 'running' | 'needs_you' | 'failed' | 'requested' | 'downloading' | 'not_ready' | 'stopped' | 'dismissed';
// auto: started by the app, not the person: a look while it's on its way ("check"), or the download after a ready email
// ("ready"). reason: why it needs you or failed, when that changes what the page offers.
export interface AgentState { mode: AgentMode; status: AgentStatus; at: string; step?: string; note?: string; session?: string;
  auto?: 'check' | 'ready'; reason?: 'chrome' | 'no-claude' | 'quit' }

export interface SourceState {
  requestedAt?: string;
  openedAt?: string; // its export page was last opened from the app
  // A notification or an email that looked like the service saying it's ready; an email from it carries the link.
  readySignal?: { at: string; via: string; text: string; link?: string; sender?: string };
  agent?: AgentState;
  notifyEmail?: string; // where the service said it would email the download link (Do It for Me saw it when requesting)
  checkedAt?: string; // Claude last looked for it (or that look was stopped): the next look waits from here
  noChecks?: string; // when the person said Stop Checking: Claude doesn't look for it by itself until they ask again
  stepsDone?: number[];
  skipped?: string; // reason
  doneAt?: string; // guided sources marked done by hand
  lastError?: string;
  lastErrorAt?: string;
  // 'file': a download that couldn't be used (incomplete, locked, not this service's), so nothing was imported;
  // otherwise the import itself failed.
  lastErrorKind?: 'file';
  lastRunAt?: string;
  importedAt?: string;
  lastFileAt?: string; // a download for this source was last moved into corpus/imports/
  notified?: string[];
  accountName?: string; // other_mail: the folder under corpus/imports/
  libraryMapping?: string; // when the app's shared mapping for this service was put to use (once: taking it out sticks)
}

export interface FoundFile extends Identified {
  foundAt: string;
  sourceId: string;
  ignoredAt?: string; // the person chose Ignore: kept here (it's in ignoredFiles too) so the page can show it again
}

export interface Settings {
  autoRefresh: boolean;
  watchDownloads: boolean;
  // "Do It for Me" is on (the person said yes once), and downloads start by themselves once an export is ready.
  agentExports?: boolean;
  agentDownloads?: boolean;
  // While an export is on its way, Claude opens Chrome every few hours to look for it (needs downloads on). On unless turned off.
  agentChecks?: boolean;
  // Closing the window leaves the app in the menu bar, reading and watching (the packaged app).
  background?: boolean;
  // Opening at login (the packaged app): follows background until the person sets it.
  openAtLogin?: boolean;
  backgroundNoticeAt?: string; // the window was first closed with the app staying in the menu bar, and it said so

  // AI as a whole (the AI page, agreed to once): undefined until the person decides; off stops Ask, Do It for Me and the
  // download helper. Which agent does the work is the Ask provider (AskSettings.provider), shared by all of them.
  aiOn?: boolean;
  aiAgreedAt?: string;
}

export interface AppState {
  version: 1;
  sources: Record<string, SourceState>;
  found: FoundFile[];
  ignoredFiles: string[]; // "<path>|<size>" the user chose not to import
  importedFiles: string[]; // same key, already moved into corpus/imports
  settings: Settings;
  lastAutoRefresh?: string;
  onboarding: Onboarding;
  identityDismissed: string[]; // "kind:value" (lowercase) the person said aren't them
  services: ServiceEntry[];
  ask: AskSettings;
}

// The Setup Assistant: whether it's finished, where it is, and which web accounts the person said they use.
export interface Onboarding {
  done: boolean;
  step?: string;
  chosen?: string[];
  skippedAt?: string; // left before the end: the Overview offers to carry on
}

export interface JobView {
  id: string;
  kind: 'connectors' | 'iphone' | 'index' | 'import';
  label: string;
  sourceIds: string[];
  connectors: string[];
  state: 'queued' | 'running';
  current?: string;
  finished?: string[];
  startedAt?: string;
  lastLine?: string;
}

export type Section = 'needs' | 'working' | 'done' | 'unavailable';

export interface Action {
  id: string;
  label: string;
  primary?: boolean;
  ai?: boolean; // done by an AI agent: drawn with the AI mark
  // Extra input the renderer collects before calling the action.
  // reply: Claude asked something, and the answer box goes with this action.
  input?: 'password' | 'identity' | 'account' | 'skip-reason' | 'file' | 'reply';
  confirm?: string;
}

export interface SourceView {
  id: string;
  name: string;
  group: string;
  blurb: string;
  section: Section;
  status: string;
  stage?: 'waiting' | 'reading' | 'read'; // where it is in a run that reads several sources in turn
  waiting?: boolean; // requested, and the service hasn't sent it yet
  detail?: string;
  records: number;
  first?: string | null;
  last?: string | null;
  warnings: string[];
  notes?: string[];
  actions: Action[];
  priority: number;
  optional?: boolean;
  blockedBy?: string;
  steps?: { text: string; detail?: string; done: boolean }[];
  url?: string;
  progress?: number; // 0..1 when known
  parts?: { name: string; records: number; device?: boolean; artifacts?: Record<string, number> }[];
  // iPhone backup: what the phone added to sources merged with the Mac's copy (Messages, calls).
  merged?: { id: string; name: string; fromPhone: number; onlyMac: number }[];
  // What a source holds, in words (shared/contents.ts).
  contents?: ContentGroup[];
  ranAt?: string;
  tag?: string;
  requestedAt?: string;
  accountName?: string;
  // Asked for and not in yet, as far as the app can tell: before its usual wait is up, ready (an email or a
  // notification said so), past its usual wait, late, or its link has probably expired.
  onTheWay?: 'waiting' | 'ready' | 'due' | 'late' | 'expired';
  deferred?: boolean; // skipped "for now": kept under Needs You's optional ones, not put away
  inboxes?: Inbox[]; // where its "it's ready" email will come, for Look in Gmail and the like (shared/inbox.ts)
  ignored?: string[]; // files in Downloads the person chose to ignore for this source
  arrived?: boolean; // came home while the window was closed: its banner shows when the window opens again
}

export interface Summary {
  records: number;
  sourcesDone: number;
  needsYou: number;
  working: number;
}

export interface Snapshot {
  sources: SourceView[];
  summary: Summary;
  next: string | null;
  jobs: JobView[];
  settings: Settings;
  probeTime?: string;
  corpusPath?: string;
  readOnly: boolean;
  demo?: boolean; // a made-up library (scripts/demo.mjs)
  agentInstalled?: boolean; // Do It for Me can run: Claude Code is on this Mac (or the demo's stand-in)
  label?: string;
  accent?: string;
  onboarding: Onboarding;
  identityCandidates: Candidate[];
  identityCandidatesReady: boolean;
  identityDismissed: string[];
  identity: Identity | null;
  identitySuggestion: Identity | null;
  services: ServiceEntry[];
  // corpus/mappings/<folder>.json: how a service's export is read (connectors/mapped_exports.py).
  mappings: Record<string, { service: string; items: { describe: string; kind: string }[] }>;
  // What can write a mapping for a download the app doesn't know: the agent Ask uses (Claude Code or Codex), if it's on
  // this Mac, or nothing (copy and paste). 'api' is no longer used.
  claude: 'cli' | 'api' | 'codex' | null;
  // Found in your data and not yet in the app: built-in accounts and services already added are left out.
  discovery: Discovery | null;
  defaultBrowser: string; // where export pages open: "Safari", "Google Chrome"
  log: { time: string; line: string }[];
  ask: AskView;
}

// The Ask assistant's settings, and what this Mac has for it.
export interface AskView {
  settings: AskSettings;
  installed: { 'claude-code': boolean; codex: boolean };
  keys: { anthropic: boolean; openai: boolean };
  local?: LocalStatus; // whether the local model's server answers (checked on this Mac only)
  signIn?: Partial<Record<'claude-code' | 'codex', SignIn>>; // whether Claude Code and Codex are signed in, as they say
}

export interface ContentGroup { title: string; rows: { label: string; count: number }[] }

// A record as it is, for a source's samples (py/glance.py samples): what it is, when, who, what it says, and a few
// things from its meta (call length, steps, the repository...).
export interface SampleRecord {
  rowid: number; source: string; kind: string; ts: string; ts_end?: string | null; author?: string | null; is_me: boolean;
  thread?: string | null; thread_name?: string | null; title?: string | null; text?: string | null; url?: string | null;
  meta: Record<string, string | number | boolean>;
}

// A collected source at a glance (py/glance.py): records month by month (local time), by hour and weekday (Sunday
// first), day by day for the last year, and what's worth saying about them, in words.
export interface Glance {
  total: number;
  kinds?: Record<string, number>;
  months?: Record<string, number>; // "2019-03" -> records
  hours?: number[]; // 24
  weekdays?: number[]; // 7, Sunday first
  recent?: Record<string, number>; // "2026-10-15" -> records, the last year or so
  first?: string | null;
  last?: string | null;
  facts?: { label: string; value: string; detail?: string | null }[];
}

// A service found in your data (bridge.py discover-services), matched against data/services.json.
export interface FoundService {
  slug: string;
  name: string;
  domains: string[];
  site?: string; // its home page
  export?: { url?: string; notes?: string; difficulty?: string; email?: string }; // how to get your data (JustGetMyData)
  privacy_email?: string;
  popular?: boolean;
  emails: number; // mail from them
  automated: number; // ... of it from no-reply, account and notification addresses
  first?: string | null;
  last?: string | null;
  visits: number; // pages visited on their sites
  apps: string[]; // "Duolingo on your iPhone"
}

// Mail from a domain no directory knows: an obscure service, a shop, a club.
export interface UnknownSender { domain: string; name?: string; emails: number; automated: number; first?: string | null; last?: string | null; visits: number; apps: string[] }

export interface Discovery { found: FoundService[]; unmatched: UnknownSender[]; services: number }

// An account the person added (by hand, or by ticking a found one). It becomes a web source: request, wait,
// download, import. Files go to corpus/imports/<folder>/ and imports.py's catch-alls read whatever is there.
export interface ServiceEntry {
  id: string; // "svc_<folder>"
  slug: string;
  name: string;
  folder: string;
  domains: string[];
  url?: string; // where to get your data
  site?: string; // its home page, opened when no export page is known
  notes?: string;
  email?: string; // where an access request goes
  addedAt: string;
  from: 'found' | 'you';
}

// bridge.py try-mapping: what a mapping finds across the whole export, before anything is saved.
export interface MappingPreview {
  mapping: { service: string; version: number; items: Record<string, unknown>[] };
  rules: { describe: string; kind: string; file: string; files: number; items: number; timed: number; first: string | null; last: string | null;
    sample: { ts?: string; title?: string; text?: string; author?: string }[] }[];
  structured: number;
  mapped: number;
  unmapped: string[];
  error?: string;
}

// One service in data/services.json: what the hub lists (scripts/build_services.py).
export interface DirectoryEntry {
  slug: string;
  name: string;
  domains: string[];
  category?: string;
  site?: string;
  export?: { url?: string; notes?: string; difficulty?: string; email?: string };
  privacy_email?: string;
  popular?: boolean;
}

