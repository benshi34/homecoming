// A record's kind in plain words, by its source where the same kind means different things.

import assert from 'node:assert/strict';
import { test } from 'node:test';
import { kindName } from '../../src/shared/explore.ts';

test('a film from Letterboxd is a film, a TikTok watch a video, a finished book a book, an anime an anime', () => {
  assert.equal(kindName('watch', 'letterboxd'), 'Film you watched');
  assert.equal(kindName('watch', 'tiktok'), 'Video you watched');
  assert.equal(kindName('read', 'goodreads'), 'Book you read');
  assert.equal(kindName('saved', 'goodreads'), 'Saved');
  assert.equal(kindName('watch', 'trakt'), 'Film or show you watched');
  assert.equal(kindName('watch', 'netflix'), 'Film or show you watched');
  assert.equal(kindName('watch', 'myanimelist'), 'Anime you watched');
  assert.equal(kindName('read', 'myanimelist'), 'Manga you read');
  assert.equal(kindName('read', 'the_storygraph'), 'Book you read');
  assert.equal(kindName('event', 'telegram'), 'Something that happened');
  assert.equal(kindName('event', 'google_calendar'), 'Calendar event');
  assert.equal(kindName('reminder', 'todoist'), 'Task');
  assert.equal(kindName('note', 'trello'), 'Card');
});
