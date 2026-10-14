// Shapes shared by the main process, the renderer and the tests.

import type { AskSettings } from './ask.ts';

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
export interface SourceState {
  requestedAt?: string;
  openedAt?: string; // its export page was last opened from the app
  readySignal?: { at: string; via: string; text: string }; // a notification that looked like the service saying it's ready
  stepsDone?: number[];
  skipped?: string; // reason
  doneAt?: string; // guided sources marked done by hand
  lastError?: string;
  lastErrorAt?: string;
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
}

export interface Settings {
  autoRefresh: boolean;
  watchDownloads: boolean;
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
}

export interface JobView {
  id: string;
  kind: 'connectors' | 'iphone' | 'index' | 'import';
  label: string;
  sourceIds: string[];
  connectors: string[];
  state: 'queued' | 'running';
  current?: string;
  startedAt?: string;
  lastLine?: string;
}

export type Section = 'needs' | 'working' | 'done' | 'unavailable';

export interface Action {
  id: string;
  label: string;
  primary?: boolean;
  // Extra input the renderer collects before calling the action.
  input?: 'password' | 'identity' | 'account' | 'skip-reason' | 'file';
  confirm?: string;
}

export interface SourceView {
  id: string;
  name: string;
  group: string;
  blurb: string;
  section: Section;
  status: string;
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
  // How the app can ask Claude to write a mapping: the Claude CLI, the API (ANTHROPIC_API_KEY), or neither (copy and paste).
  claude: 'cli' | 'api' | null;
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
}

export interface ContentGroup { title: string; rows: { label: string; count: number }[] }

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

