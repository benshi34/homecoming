import type { Source } from './catalog.ts';

// A link from the service's "it's ready" email, for Claude to open by itself: only one under the service's own export
// or download page, or a mail redirect on its domain (click.discord.com). Never another page there (a Google Doc, a
// post anyone can make), which could tell Claude what to do: then it starts from the service's own download page.
export function agentLink(src: Pick<Source, 'url' | 'downloadUrl' | 'domains'> | undefined, link?: string): string | undefined {
  if (!src || !link) return undefined;
  let u: URL;
  try {
    u = new URL(link);
  } catch {
    return undefined;
  }
  if (u.protocol !== 'https:') return undefined;
  const under = [src.url, src.downloadUrl].some((own) => {
    try {
      const o = new URL(own!);
      return o.hostname === u.hostname && u.pathname.startsWith(o.pathname.replace(/\/?$/, ''));
    } catch {
      return false;
    }
  });
  const site = (h: string) => h.split('.').slice(-2).join('.');
  const redirect = /^(click|links?|email|t|l|go)\./.test(u.hostname) && (src.domains ?? []).some((d) => site(d) === site(u.hostname));
  return under || redirect ? link : undefined;
}
