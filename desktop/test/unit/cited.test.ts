// What a cited calendar event shows (shared/explore.ts): which events are a calendar's, when one is, and its notes
// without the lines laid out already. Times are read here, as the window reads them.

import assert from 'node:assert/strict';
import { test } from 'node:test';
import { eventNotes, eventSpan, isCalendarEvent } from '../../src/shared/explore.ts';

test('an event from a calendar, not one a chat app writes itself', () => {
  for (const source of ['calendar', 'google_calendar', 'phone_calendarall']) assert.equal(isCalendarEvent({ kind: 'event', source }), true, source);
  for (const source of ['imessage', 'slack', 'whatsapp']) assert.equal(isCalendarEvent({ kind: 'event', source }), false, source);
  assert.equal(isCalendarEvent({ kind: 'message', source: 'calendar' }), false);
});

test('when an event is: from and to, all day by its date, and no made-up time', () => {
  const timed = eventSpan({ ts: '2026-03-06T19:30:00Z', ts_end: '2026-03-06T21:30:00Z' })!;
  assert.deepEqual([timed.start.toISOString(), timed.end?.toISOString(), timed.allDay], ['2026-03-06T19:30:00.000Z', '2026-03-06T21:30:00.000Z', false]);
  // A calendar keeps the start of the day after an all-day event's last.
  const birthday = eventSpan({ ts: '2026-03-22T00:00:00Z', ts_end: '2026-03-23T00:00:00Z', meta: { all_day: true } })!;
  assert.deepEqual([birthday.start.toDateString(), birthday.end?.toDateString(), birthday.allDay, birthday.oneDay], ['Sun Mar 22 2026', 'Sun Mar 22 2026', true, true]);
  const trip = eventSpan({ ts: '2026-04-10T00:00:00Z', ts_end: '2026-04-13T00:00:00Z', meta: { all_day: true } })!;
  assert.deepEqual([trip.start.toDateString(), trip.end?.toDateString(), trip.oneDay], ['Fri Apr 10 2026', 'Sun Apr 12 2026', false]);
  assert.equal(eventSpan({ ts: '2026-03-06T19:30:00Z', ts_end: 'never' })!.end, null, 'an end that isn\'t a time');
  assert.equal(eventSpan({ ts: '2026-03-06T19:30:00Z', ts_end: '2026-03-06T18:00:00Z' })!.end, null, 'nor one before it starts');
  assert.equal(eventSpan({ ts: null }), null);
  assert.equal(eventSpan({ ts: 'garbage' }), null);
});

test('an event\'s notes are what its text says besides what\'s laid out', () => {
  // As connectors/calendar_events.py writes it.
  assert.equal(eventNotes({ title: 'Dinner with Grace', meta: { location: 'Tasca, Lisbon' },
    text: 'Dinner with Grace\nLocation: Tasca, Lisbon\nOrganized by Grace Hopper\nAttendees: Grace Hopper, Alan Turing\nYou accepted\nRepeats every week\nBring the good wine.\nAnd the cheese.' }),
  'Bring the good wine.\nAnd the cheese.');
  assert.equal(eventNotes({ title: 'Standup', text: 'Standup\nYour reply: tentative' }), '');
  // An .ics file's, and the demo's "title at place".
  assert.equal(eventNotes({ title: 'Dentist', meta: { location: 'Mission Dental' }, text: 'Dentist\nLocation: Mission Dental\nAttendees: Ada Lovelace' }), '');
  assert.equal(eventNotes({ title: 'Climbing', meta: { location: 'First Ascent' }, text: 'Climbing at First Ascent' }), '');
  // A line that only starts like one is kept.
  assert.equal(eventNotes({ title: 'Lunch', text: 'Lunch\nLunch with the team, then the offsite' }), 'Lunch with the team, then the offsite');
  assert.equal(eventNotes({ title: 'Lunch' }), '');
});
