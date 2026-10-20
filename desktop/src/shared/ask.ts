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
  // Codex only as the harness (the free CLI that runs the lookups): the model is the one on this Mac, no OpenAI account.
  { id: 'local', harness: 'codex', name: 'Codex harness', auth: 'A model on this Mac', short: 'local model', cloud: false, models: ['default'] },
];
export const PROVIDER = Object.fromEntries(PROVIDERS.map((p) => [p.id, p])) as Record<AskProvider, ProviderInfo>;
// "Codex (your ChatGPT account)", "Claude Code (an Anthropic API key)": the AI picked, in a sentence.
export const providerLabel = (id: string) => {
  const p = PROVIDER[id as AskProvider];
  return p ? `${p.name} (${p.auth.charAt(0).toLowerCase()}${p.auth.slice(1)})` : 'the AI picked';
};

// Local model servers Codex can use (codex --oss): Ollama or LM Studio, with their usual addresses.
export const LOCAL_SERVERS = {
  ollama: { name: 'Ollama', url: 'http://localhost:11434/v1' },
  lmstudio: { name: 'LM Studio', url: 'http://localhost:1234/v1' },
} as const;
export type LocalServer = keyof typeof LOCAL_SERVERS;

// "A model on this Mac" is one on this Mac: its address is localhost, so nothing leaves it (and nothing else is checked).
export function isLocalAddress(url: string): boolean {
  try {
    const u = new URL(url.trim());
    return (u.protocol === 'http:' || u.protocol === 'https:') && ['localhost', '127.0.0.1', '[::1]'].includes(u.hostname);
  } catch {
    return false;
  }
}

// "http://localhost:11434/v1" -> "localhost:11434", for sentences.
export function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

// Whether something answers at the local model's address (main/ask.ts checks it, on this Mac only). up is null until
// it's been checked.
// models: the ones the server says it has (its /models), when it answered.
export interface LocalStatus { url: string; up: boolean | null; at: string; models?: string[] }

// Where to get what an agent needs, opened in the person's browser.
export const LINKS = {
  'claude-code': { label: 'Get Claude Code', url: 'https://claude.com/claude-code' },
  codex: { label: 'Get Codex', url: 'https://developers.openai.com/codex/cli' },
  anthropic: { label: 'console.anthropic.com', url: 'https://console.anthropic.com/settings/keys' },
  openai: { label: 'platform.openai.com', url: 'https://platform.openai.com/api-keys' },
} as const;

// What each cloud provider keeps of what's sent, and the setting that keeps it to the least. Checked 2026-10-12
// against Anthropic's and OpenAI's docs; shown before first use and under the composer after.
// done: the same once the person has checked it, for the line under the composer.
export interface Retention { short: string; done: string; detail: string[]; link: { label: string; url: string }; confirm: string }
export const RETENTION: Partial<Record<AskProvider, Retention>> = {
  'claude-code': {
    short: 'Make sure "Help improve Claude" is off in claude.ai → Settings → Privacy, so your data isn\'t used for training or kept for years.',
    done: '"Help improve Claude" is off.',
    detail: [
      'Questions, and the records and photos the assistant looks at to answer them, go to Anthropic under your claude.ai plan, as do the pages Claude works on in your browser for Do It for Me.',
      'In claude.ai, open Settings → Privacy and turn off "Help improve Claude". Off, your chats aren\'t used to train models and are kept 30 days. On, they can be used for training and kept up to 5 years.',
      'Rating an answer with thumbs up or down keeps that conversation longer, whatever the setting.',
    ],
    link: { label: 'Anthropic Privacy Center', url: 'https://privacy.claude.com' },
    confirm: '"Help improve Claude" is off in my claude.ai settings',
  },
  codex: {
    short: 'Make sure "Improve the model for everyone" is off in ChatGPT → Settings → Data controls, so your data isn\'t used for training.',
    done: '"Improve the model for everyone" is off.',
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
    done: 'Anthropic keeps API requests 30 days at most.',
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
    done: 'OpenAI keeps API requests 30 days at most.',
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

// ---------------------------------------------------------------- can the chosen agent answer?

// Whether Claude Code or Codex is signed in on this Mac, as they say themselves (claude auth status, codex login
// status: both read only what's saved on this Mac). who: the account, when it says; how: "claude.ai", "ChatGPT".
export interface SignIn { state: 'in' | 'out' | 'unknown'; who?: string; how?: string; plan?: string; at: string }

// What the app knows of the agents on this Mac (the snapshot's ask).
export interface AgentState {
  settings: AskSettings;
  installed: { 'claude-code': boolean; codex: boolean };
  keys: { anthropic: boolean; openai: boolean };
  local?: LocalStatus;
  signIn?: Partial<Record<'claude-code' | 'codex', SignIn>>;
}

// What's missing before a provider can answer: the agent itself, its sign-in or key, or a local model server that answers.
export type AgentNeed =
  | { kind: 'install'; harness: 'claude-code' | 'codex' }
  | { kind: 'sign-in'; harness: 'claude-code' | 'codex' }
  | { kind: 'key'; key: 'anthropic' | 'openai' }
  | { kind: 'local'; url: string; server: LocalServer } // nothing answers there
  | { kind: 'local-address'; url: string } // not an address on this Mac
  | { kind: 'local-model'; server: LocalServer; models: string[] }; // no model picked that the server has

export function agentNeed(v: AgentState, p: AskProvider = v.settings.provider): AgentNeed | null {
  const info = PROVIDER[p];
  if (!info) return null;
  if (!v.installed[info.harness]) return { kind: 'install', harness: info.harness };
  if (info.needsKey && !v.keys[info.needsKey]) return { kind: 'key', key: info.needsKey };
  // Signed in with your account (not a key, not the model on this Mac): only once it says it isn't.
  if (!info.needsKey && p !== 'local' && v.signIn?.[info.harness]?.state === 'out') return { kind: 'sign-in', harness: info.harness };
  if (p === 'local') {
    const url = v.settings.localUrl;
    if (!isLocalAddress(url)) return { kind: 'local-address', url };
    if (v.local?.url === url && v.local.up === false) return { kind: 'local', url, server: v.settings.localServer };
    // One it has, picked: with none ("default"), or one it doesn't have, Codex downloads its own (gpt-oss, ~13 GB).
    const m = v.settings.models.local;
    if (v.local?.url === url && v.local.up && v.local.models && (!m || m === 'default' || !v.local.models.includes(m))) {
      return { kind: 'local-model', server: v.settings.localServer, models: v.local.models };
    }
  }
  return null;
}

// The same, in a sentence or two.
export function needText(n: AgentNeed): string {
  switch (n.kind) {
    case 'install': return `${n.harness === 'codex' ? 'Codex' : 'Claude Code'} isn't on this Mac.`;
    case 'sign-in': return n.harness === 'codex' ? 'Codex isn\'t signed in on this Mac. Sign In opens ChatGPT\'s sign-in in your browser.'
      : 'Claude Code isn\'t signed in on this Mac. Sign In opens claude.ai\'s sign-in in your browser.';
    case 'key': return n.key === 'anthropic' ? 'Claude Code needs your Anthropic API key to answer.' : 'Codex needs your OpenAI API key to answer.';
    case 'local': return `Nothing is answering at ${hostOf(n.url)}. Open ${LOCAL_SERVERS[n.server]?.name ?? 'the model server'}, then try again.`;
    case 'local-address': return `${hostOf(n.url)} isn't on this Mac. Use the address your model server shows, like ${LOCAL_SERVERS.ollama.url}.`;
    case 'local-model': return n.models.length
      ? `Pick one of the models ${LOCAL_SERVERS[n.server]?.name ?? 'your model server'} has (${n.models.slice(0, 4).join(', ')}${n.models.length > 4 ? '…' : ''}). With none picked, Codex would download its own, about 13 GB.`
      : `${LOCAL_SERVERS[n.server]?.name ?? 'Your model server'} has no models yet. Download one there (gpt-oss works best), then pick it.`;
  }
}

// ---------------------------------------------------------------- what went wrong, in plain words

// What a person can do about an agent's error: sign in again in Terminal, check the key or the model, open the local
// server, or install the agent.
export type AskFix = 'sign-in' | 'key' | 'model' | 'local' | 'install';

const companyOf = (p: AskProvider) => (PROVIDER[p]?.harness === 'codex' ? 'OpenAI' : 'Anthropic');

// An agent's own error (its last words, or stderr) as a sentence with a way forward. The raw text stays under Details.
export function explainError(provider: AskProvider, raw: string, opts: { localUrl?: string; localServer?: LocalServer; model?: string } = {}): { text: string; fix?: AskFix } {
  const info = PROVIDER[provider];
  const who = info?.name ?? 'The agent';
  const company = companyOf(provider);
  const r = raw || '';
  const server = LOCAL_SERVERS[opts.localServer ?? 'ollama']?.name ?? 'the model server';
  if (/isn't on this Mac/i.test(r)) return { text: r.split('\n')[0], fix: 'install' };
  // What the app itself said, already in plain words.
  if (/^Pick one of the models/.test(r)) return { text: r.split('\n')[0], fix: 'model' };
  if (/^(The app's lookup tools didn't start|It took more steps than an answer gets)/.test(r)) return { text: r.split('\n')[0] };
  // A model on this Mac's own troubles: no tools, the server too old for Codex, or the question not fitting.
  if (provider === 'local' && /does not support tools|doesn't support tools|tools? (is|are) not supported|no tool support/i.test(r)) {
    return { text: `${opts.model && opts.model !== 'default' ? `“${opts.model}”` : 'That model'} can't use tools, so it can't look anything up. Pick one that can, like gpt-oss, under AI Settings.`, fix: 'model' };
  }
  if (provider === 'local' && (/is too old|requires (ollama|lm studio)|update (ollama|lm studio)|minimum version/i.test(r) || (/\b404\b/.test(r) && /responses/i.test(r)))) {
    return { text: `${server} is too old for Codex. Update it, then try again.`, fix: 'local' };
  }
  if (/context (length|window)|maximum context|num_ctx|prompt is too long|too many tokens|input is too long/i.test(r)) {
    return provider === 'local'
      ? { text: `The question and Codex's instructions don't fit in what ${server} keeps of a conversation. Raise its context length (64k or more) in ${server}'s settings, then try again.`, fix: 'local' }
      : { text: 'That was too much for one answer. Start a new conversation, or ask about less at once.' };
  }
  if (/^Add your .* API key first/i.test(r)) return { text: r.split('\n')[0], fix: 'key' };
  if (provider === 'local' && /ECONNREFUSED|connection refused|error sending request|failed to connect|couldn't connect|connect error|tcp connect|os error 61|no running|not running|ollama serve|is it running|unreachable/i.test(r)) {
    return { text: `Nothing is answering at ${hostOf(opts.localUrl ?? LOCAL_SERVERS.ollama.url)}. Open ${server}, then try again.`, fix: 'local' };
  }
  if (provider !== 'local' && /invalid api key|invalid x-api-key|invalid_api_key|incorrect api key|\/login|not logged in|log in|sign in|signing in|401|unauthori[sz]ed|authentication|expired|credentials/i.test(r)) {
    switch (provider) {
      case 'claude-code': return { text: 'Claude Code isn\'t signed in. Sign In opens claude.ai\'s sign-in in your browser.', fix: 'sign-in' };
      case 'codex': return { text: 'Codex\'s sign-in has expired. Sign In opens ChatGPT\'s sign-in in your browser, to sign in again.', fix: 'sign-in' };
      default: return { text: `${company} didn't accept the key. Check it under AI Settings.`, fix: 'key' };
    }
  }
  if (/model[^\n]{0,60}(not found|not_found|does not exist|doesn't exist|isn't available|not available|unknown|invalid|not supported)|model_not_found|unknown model|invalid model|not_found_error/i.test(r)) {
    const m = opts.model && opts.model !== 'default' ? ` called “${opts.model}”` : ' by that name';
    return { text: `${provider === 'local' ? server : company} doesn't have a model${m}. Pick another under AI Settings.`, fix: 'model' };
  }
  if (/credit balance|insufficient_quota|exceeded your current quota|billing/i.test(r)) {
    return { text: `Your ${company} account is out of credit. Add some in its console, then try again.` };
  }
  if (/usage limit|limit reached|reached your limit|out of extra usage/i.test(r)) {
    return { text: `You've reached your ${provider === 'codex' ? 'ChatGPT' : 'claude.ai'} usage limit for now. Try again later, or choose another way to answer under AI Settings.` };
  }
  if (/rate.?limit|too many requests|\b429\b|overloaded|\b529\b|\b503\b/i.test(r)) {
    return { text: `${provider === 'local' ? server : company} is busy right now. Try again in a minute.` };
  }
  if (provider !== 'local' && /ENOTFOUND|getaddrinfo|ETIMEDOUT|ECONNRESET|network|offline|unable to connect|connection error|timed out/i.test(r)) {
    return { text: `Couldn't reach ${company}. Check that this Mac is online, then try again.` };
  }
  return { text: `${who} stopped before it answered.` };
}

// What happens in one answer, as it streams and as it's saved.
export type AskEvent =
  | { t: 'text'; text: string } // a piece of the answer (or a whole block, from the command-line agents)
  // What the agent thought on the way, as it sends it (a summary of its thinking): pieces as they come from Claude Code,
  // a whole block from Codex. seconds: how long these thoughts had taken so far. Shown, never sent back to it.
  | { t: 'thinking'; text: string; seconds?: number }
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
  error?: string; // what went wrong, in plain words
  errorDetail?: string; // the agent's own words, shown under Details
  fix?: AskFix;
}

export interface AskConversation { id: string; title: string; createdAt: string; updatedAt: string; turns: AskTurn[] }
export interface AskSummary { id: string; title: string; updatedAt: string; turns: number; failed?: boolean } // failed: its last question went unanswered

// The question for an agent that keeps no memory between turns: earlier questions and answers come along. A turn that
// failed or was stopped has no answer to bring.
export function followupPrompt(question: string, turns: AskTurn[], maxChars = 30_000): string {
  const done = turns.filter((t) => t.answer && !t.error && !t.stopped);
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

// Adds an event to a turn as it arrives: a streamed piece of text joins the text before it, and of thinking the thinking.
export function addEvent(turn: Pick<AskTurn, 'provider' | 'events'>, e: AskEvent) {
  const last = turn.events[turn.events.length - 1];
  if (e.t === 'text' && last?.t === 'text' && streams(turn.provider)) turn.events[turn.events.length - 1] = { t: 'text', text: last.text + e.text };
  else if (e.t === 'thinking' && last?.t === 'thinking' && streams(turn.provider)) {
    turn.events[turn.events.length - 1] = { ...last, text: last.text + e.text, ...(e.seconds !== undefined ? { seconds: e.seconds } : {}) };
  } else turn.events.push(e);
}

// The agent's thinking in a turn, in order: each stretch of it, and how many lookups it made before the next.
export interface Thoughts { parts: ({ kind: 'thought'; text: string } | { kind: 'looked'; n: number })[]; seconds: number }
export function thoughtsOf(events: AskEvent[]): Thoughts {
  const parts: Thoughts['parts'] = [];
  let seconds = 0;
  let looked = 0;
  for (const e of events) {
    if (e.t === 'tool') looked++;
    if (e.t !== 'thinking') continue;
    seconds += e.seconds ?? 0;
    const text = e.text.trim();
    if (!text) continue; // its thinking left out (Claude's, unless asked for): nothing to show
    const prev = parts[parts.length - 1];
    if (looked && prev) parts.push({ kind: 'looked', n: looked });
    if (prev?.kind === 'thought' && !looked) prev.text += `\n\n${text}`;
    else parts.push({ kind: 'thought', text });
    looked = 0;
  }
  return { parts, seconds };
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
      return [line(a.query) ? `"${line(a.query)}"` : 'by time', ...filters].join(' · '); // no words: records by time
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
