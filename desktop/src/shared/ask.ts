// The Ask assistant, shared by the main process and the window: who can answer, what they're told about keeping
// your data, and the conversation as it's shown and saved.

export type AskProvider = 'claude-code' | 'codex' | 'anthropic' | 'openai' | 'local';

// Every provider runs one of two agent harnesses, the Claude Code or Codex CLI on this Mac, signed in a different way.
export interface ProviderInfo {
  id: AskProvider;
  harness: 'claude-code' | 'codex';
  name: string; // the harness
  auth: string; // how it's signed in, as a row title
  short: string; // the same in a few words, for the toolbar
  cloud: boolean; // the data leaves this Mac
  needsKey?: 'anthropic' | 'openai';
  models: string[]; // offered in the model field; the first is the default ("default": the harness's own choice)
}

const CLAUDE_MODELS = ['claude-sonnet-5-5', 'claude-opus-5-5', 'claude-haiku-5-5'];
export const PROVIDERS: ProviderInfo[] = [
  { id: 'claude-code', harness: 'claude-code', name: 'Claude Code', auth: 'Your claude.ai account', short: 'claude.ai account', cloud: true, models: CLAUDE_MODELS },
  { id: 'anthropic', harness: 'claude-code', name: 'Claude Code', auth: 'An Anthropic API key', short: 'API key', cloud: true, needsKey: 'anthropic', models: CLAUDE_MODELS },
  { id: 'codex', harness: 'codex', name: 'Codex', auth: 'Your ChatGPT account', short: 'ChatGPT account', cloud: true, models: ['default'] },
  { id: 'openai', harness: 'codex', name: 'Codex', auth: 'An OpenAI API key', short: 'API key', cloud: true, needsKey: 'openai', models: ['default'] },
  { id: 'local', harness: 'codex', name: 'Codex', auth: 'A model on this Mac', short: 'local model', cloud: false, models: ['default'] },
];
export const PROVIDER = Object.fromEntries(PROVIDERS.map((p) => [p.id, p])) as Record<AskProvider, ProviderInfo>;

// Local model servers Codex can use (codex --oss): Ollama or LM Studio, with their usual addresses.
export const LOCAL_SERVERS = {
  ollama: { name: 'Ollama', url: 'http://localhost:11434/v1' },
  lmstudio: { name: 'LM Studio', url: 'http://localhost:1234/v1' },
} as const;
export type LocalServer = keyof typeof LOCAL_SERVERS;

// What each cloud provider keeps of what's sent, and the setting that keeps it to the least. Checked 2026-10-12
// against Anthropic's and OpenAI's docs; shown before first use and under the composer after.
export interface Retention { short: string; detail: string[]; link: { label: string; url: string }; confirm: string }
export const RETENTION: Partial<Record<AskProvider, Retention>> = {
  'claude-code': {
    short: 'Make sure "Help improve Claude" is off in claude.ai → Settings → Privacy, so your data isn\'t used for training or kept for years.',
    detail: [
      'Questions, and the records and photos the assistant looks at to answer them, go to Anthropic under your claude.ai plan.',
      'In claude.ai, open Settings → Privacy and turn off "Help improve Claude". Off, your chats aren\'t used to train models and are kept 30 days. On, they can be used for training and kept up to 5 years.',
      'Rating an answer with thumbs up or down keeps that conversation longer, whatever the setting.',
    ],
    link: { label: 'Anthropic Privacy Center', url: 'https://privacy.claude.com' },
    confirm: '"Help improve Claude" is off in my claude.ai settings',
  },
  codex: {
    short: 'Make sure "Improve the model for everyone" is off in ChatGPT → Settings → Data controls, so your data isn\'t used for training.',
    detail: [
      'Questions, and the records and photos the assistant looks at to answer them, go to OpenAI under your ChatGPT plan.',
      'In ChatGPT, open Settings → Data controls and turn off "Improve the model for everyone". It covers Codex too.',
      'Giving feedback on a reply lets OpenAI use that whole conversation, whatever the setting.',
    ],
    link: { label: 'Data controls in ChatGPT', url: 'https://help.openai.com/en/articles/7730893-data-controls-in-chatgpt' },
    confirm: '"Improve the model for everyone" is off in my ChatGPT settings',
  },
  anthropic: {
    short: 'Anthropic keeps API requests up to 30 days unless your organization has zero data retention. Check it in the Claude Console.',
    detail: [
      'Questions, and the records and photos the assistant looks at to answer them, go to Anthropic\'s API. Anthropic doesn\'t train on API data.',
      'By default Anthropic deletes API requests and responses within 30 days. Zero data retention, where nothing is kept, is an arrangement Anthropic approves for an organization: check Settings → Privacy Controls → Data retention period in the Claude Console.',
      'The Fable models need 30-day retention even with zero data retention.',
    ],
    link: { label: 'API and data retention', url: 'https://platform.claude.com/docs/en/manage-claude/api-and-data-retention' },
    confirm: 'I\'ve checked how long my Anthropic organization keeps API data',
  },
  openai: {
    short: 'OpenAI keeps API requests up to 30 days unless your organization has zero data retention, which OpenAI must approve.',
    detail: [
      'Questions, and the records and photos the assistant looks at to answer them, go to OpenAI\'s API. OpenAI doesn\'t train on API data unless you opt in.',
      'OpenAI keeps API requests up to 30 days to watch for abuse. Zero data retention needs OpenAI\'s approval for your organization.',
    ],
    link: { label: 'Data controls in the OpenAI platform', url: 'https://developers.openai.com/api/docs/guides/your-data' },
    confirm: 'I\'ve checked how long my OpenAI organization keeps API data',
  },
};

// Settings drift (a new plan, a changed default), so the check is asked again after this long.
export const RECHECK_DAYS = 90;

// Whether a provider may be used now: on this Mac, or its data settings confirmed recently.
export function retentionOk(s: AskSettings, p: AskProvider, now = new Date()): boolean {
  if (!PROVIDER[p].cloud) return true;
  const at = Date.parse(s.retention[p] ?? '');
  return Number.isFinite(at) && now.getTime() - at < RECHECK_DAYS * 86_400_000;
}

// Settings kept in the app's state.
export interface AskSettings {
  provider: AskProvider;
  models: Partial<Record<AskProvider, string>>;
  localServer: LocalServer;
  localUrl: string; // its address
  retention: Partial<Record<AskProvider, string>>; // when the person confirmed the provider's settings
}
export const DEFAULT_ASK: AskSettings = { provider: 'claude-code', models: {}, localServer: 'ollama', localUrl: LOCAL_SERVERS.ollama.url, retention: {} };

// What happens in one answer, as it streams and as it's saved.
export type AskEvent =
  | { t: 'text'; text: string } // a piece of the answer (or a whole block, from the command-line agents)
  | { t: 'tool'; id: string; name: string; input: unknown }
  | { t: 'tool_result'; id: string; text: string; error: boolean; seconds?: number; images?: number }
  | { t: 'notice'; text: string }
  | { t: 'error'; text: string };

export interface AskTurn {
  question: string;
  provider: AskProvider;
  model: string;
  startedAt: string;
  endedAt?: string;
  events: AskEvent[];
  answer: string;
  stopped?: boolean;
  error?: string;
}

export interface AskConversation { id: string; title: string; createdAt: string; updatedAt: string; turns: AskTurn[] }
export interface AskSummary { id: string; title: string; updatedAt: string; turns: number }

// The question for an agent that keeps no memory between turns: earlier questions and answers come along.
export function followupPrompt(question: string, turns: AskTurn[], maxChars = 30_000): string {
  const done = turns.filter((t) => t.answer);
  if (!done.length) return question;
  const blocks: string[] = [];
  let used = 0;
  for (let i = done.length - 1; i >= 0 && blocks.length < 8; i--) {
    const b = `### Earlier question ${i + 1}\n${done[i].question}\n\n### Your answer\n${done[i].answer}\n`;
    if (used + b.length > maxChars && blocks.length) break;
    blocks.unshift(b);
    used += b.length;
  }
  return 'This continues a conversation. The earlier turns are below, oldest first; the answers are your own. Look the data up again '
    + `whenever you need details they don't include.\n\n${blocks.join('\n')}\n---\n\nQuestion: ${question}`;
}

// Claude Code streams text in pieces; Codex sends whole messages.
export const streams = (p: AskProvider) => PROVIDER[p]?.harness === 'claude-code';

// Adds an event to a turn as it arrives: a streamed piece of text joins the text before it.
export function addEvent(turn: Pick<AskTurn, 'provider' | 'events'>, e: AskEvent) {
  const last = turn.events[turn.events.length - 1];
  if (e.t === 'text' && last?.t === 'text' && streams(turn.provider)) turn.events[turn.events.length - 1] = { t: 'text', text: last.text + e.text };
  else turn.events.push(e);
}

// The answer's text: the text after the last tool call (what came before it was the assistant thinking aloud).
export function answerOf(events: AskEvent[]): string {
  let last = -1;
  events.forEach((e, i) => {
    if (e.t === 'tool' || e.t === 'tool_result') last = i;
  });
  return events.slice(last + 1).filter((e): e is Extract<AskEvent, { t: 'text' }> => e.t === 'text').map((e) => e.text.trim()).join('\n\n');
}

// "claude-sonnet-5-5" -> "Sonnet 5.5"; other names as they are.
export function modelLabel(id: string): string {
  if (!id || id === 'default') return 'Default model';
  const m = /^claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?(?:-\d{8})?$/.exec(id);
  return m ? `${m[1][0].toUpperCase()}${m[1].slice(1)} ${m[2]}${m[3] ? `.${m[3]}` : ''}` : id;
}

// One line for a tool call: the query, the search, the first line of code.
export function describeTool(name: string, input: unknown): string {
  const a = (input && typeof input === 'object' ? input : {}) as Record<string, unknown>;
  const line = (v: unknown) => String(v ?? '').replace(/\s+/g, ' ').trim();
  switch (name) {
    case 'sql': return line(a.query);
    case 'search': {
      const filters = ['source', 'kind', 'thread', 'author', 'after', 'before'].filter((k) => a[k]).map((k) => `${k} ${line(a[k])}`);
      return [`"${line(a.query)}"`, ...filters].join(' · ');
    }
    case 'python': return String(a.code ?? '').split('\n').map((l) => l.trim()).find((l) => l && !l.startsWith('#')) ?? '';
    case 'read_file':
    case 'view_image': return `record #${line(a.rowid)}${a.file !== undefined ? `, file ${line(a.file)}` : ''}`;
    case 'shell': return line(a.command);
    default: return typeof input === 'string' ? line(input) : line(JSON.stringify(input ?? {}));
  }
}

export const TOOL_LABEL: Record<string, string> = {
  sql: 'Database', search: 'Search', python: 'Python', read_file: 'Read file', view_image: 'Looked at', shell: 'Shell',
};

// A short title from the first question.
export function titleOf(question: string): string {
  const q = question.replace(/\s+/g, ' ').trim();
  return q.length <= 60 ? q : `${q.slice(0, 57).replace(/\s+\S*$/, '')}…`;
}
