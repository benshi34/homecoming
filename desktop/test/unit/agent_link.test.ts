import assert from 'node:assert/strict';
import { test } from 'node:test';
import { agentLink } from '../../src/shared/agent_link.ts';

const instagram = { url: 'https://accountscenter.instagram.com/info_and_permissions/dyi/', domains: ['instagram.com'] };
const google = { url: 'https://takeout.google.com/', downloadUrl: 'https://takeout.google.com/manage', domains: ['google.com'] };
const discord = { url: 'https://discord.com/settings', domains: ['discord.com'] };

test('Claude opens a ready email\'s link only under the service\'s own export pages, or its mail redirect', () => {
  assert.equal(agentLink(instagram, 'https://accountscenter.instagram.com/info_and_permissions/dyi/?id=1'), 'https://accountscenter.instagram.com/info_and_permissions/dyi/?id=1');
  assert.equal(agentLink(google, 'https://takeout.google.com/settings/takeout/downloads?user=1'), 'https://takeout.google.com/settings/takeout/downloads?user=1');
  assert.equal(agentLink(discord, 'https://click.discord.com/ls/click?upn=abc'), 'https://click.discord.com/ls/click?upn=abc');
  // A page anyone can make on the service's domain, or anywhere else: Claude starts from the service's own page instead.
  assert.equal(agentLink(google, 'https://docs.google.com/document/d/evil'), undefined);
  assert.equal(agentLink(instagram, 'https://www.instagram.com/p/some-post'), undefined);
  assert.equal(agentLink(discord, 'https://click.evil.example/x'), undefined);
  assert.equal(agentLink(google, 'http://takeout.google.com/manage'), undefined, 'not over plain http');
  assert.equal(agentLink(google, 'not a link'), undefined);
  assert.equal(agentLink(google, undefined), undefined);
});
