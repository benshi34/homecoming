-- A made-up Signal Desktop database for test_signal.py, in the columns signal_desktop.py reads. Encrypted with
-- SQLCipher 4's defaults as Signal Desktop keys it (a raw key):
--   rm -f signal_db.sqlite; (printf "PRAGMA key = \"x'%s'\";\n" 2b7e151628aed2a6abf7158809cf4f3c762e7160f38b4da56a784d9045190cfe; cat signal_db.sql) | sqlcipher signal_db.sqlite
CREATE TABLE items (id STRING PRIMARY KEY, json TEXT);
CREATE TABLE conversations (id STRING PRIMARY KEY, json TEXT, active_at INTEGER, type STRING, members TEXT, name TEXT,
  profileName TEXT, profileFamilyName TEXT, profileFullName TEXT, e164 TEXT, serviceId TEXT, groupId TEXT);
CREATE TABLE messages (rowid INTEGER PRIMARY KEY ASC, id STRING UNIQUE, json TEXT, sent_at INTEGER, conversationId STRING,
  type STRING, body TEXT, isErased INTEGER, isViewOnce INTEGER, sourceServiceId TEXT, hasAttachments INTEGER);
CREATE TABLE message_attachments (messageId TEXT, editHistoryIndex INTEGER, attachmentType TEXT, orderInMessage INTEGER,
  contentType TEXT, fileName TEXT);
CREATE TABLE callsHistory (callId TEXT PRIMARY KEY, peerId TEXT, ringerId TEXT, mode TEXT, type TEXT, direction TEXT,
  status TEXT, timestamp INTEGER, endedTimestamp INTEGER);

INSERT INTO items VALUES ('uuid_id', '{"id":"uuid_id","value":"aaaaaaaa-0000-4000-8000-000000000001.2"}');
-- You (Note to Self), Grace (in your phone's contacts), Alan (his profile name only), a group of the three of you.
INSERT INTO conversations VALUES ('c-me', '{"type":"private"}', 0, 'private', NULL, NULL, 'Ada', NULL, 'Ada', '+15550000001', 'aaaaaaaa-0000-4000-8000-000000000001', NULL);
INSERT INTO conversations VALUES ('c-grace', '{"type":"private"}', 0, 'private', NULL, 'Grace Hopper', 'gh', NULL, 'gh', '+15550000002', 'aaaaaaaa-0000-4000-8000-000000000002', NULL);
INSERT INTO conversations VALUES ('c-alan', '{"type":"private"}', 0, 'private', NULL, NULL, 'Alan', 'Turing', 'Alan Turing', NULL, 'aaaaaaaa-0000-4000-8000-000000000003', NULL);
INSERT INTO conversations VALUES ('c-club', '{"type":"group","membersV2":[{"aci":"aaaaaaaa-0000-4000-8000-000000000001"},{"aci":"aaaaaaaa-0000-4000-8000-000000000002"},{"aci":"aaaaaaaa-0000-4000-8000-000000000003"}]}', 0, 'group', NULL, 'Tide club', NULL, NULL, NULL, NULL, NULL, 'group-1');

INSERT INTO messages VALUES (1, 'm1', '{"reactions":[{"emoji":"❤️","fromId":"c-me","targetTimestamp":1767261600000,"timestamp":1767261700000}]}', 1767261600000, 'c-grace', 'incoming', 'high tide at 6?', 0, 0, 'aaaaaaaa-0000-4000-8000-000000000002', 0);
INSERT INTO messages VALUES (2, 'm2', '{"quote":{"id":1767261600000,"authorAci":"aaaaaaaa-0000-4000-8000-000000000002","text":"high tide at 6?"},"editHistory":[{"body":"yes"},{"body":"ys"}]}', 1767261660000, 'c-grace', 'outgoing', 'yes', 0, 0, NULL, 0);
INSERT INTO messages VALUES (3, 'm3', '{}', 1767265200000, 'c-club', 'incoming', 'see you there', 0, 0, 'aaaaaaaa-0000-4000-8000-000000000003', 1);
INSERT INTO messages VALUES (4, 'm4', '{"deletedForEveryone":true}', 1767265260000, 'c-club', 'incoming', NULL, 0, 0, 'aaaaaaaa-0000-4000-8000-000000000002', 0);
INSERT INTO messages VALUES (5, 'm5', '{"poll":{"question":"Dinner?","options":["Thai","Pizza"],"allowMultiple":false,"votes":[]}}', 1767265320000, 'c-club', 'outgoing', NULL, 0, 0, NULL, 0);
INSERT INTO messages VALUES (6, 'm6', '{"sticker":{"emoji":"🌊","packId":"p","stickerId":1}}', 1767265380000, 'c-alan', 'incoming', NULL, 0, 0, 'aaaaaaaa-0000-4000-8000-000000000003', 0);
INSERT INTO messages VALUES (7, 'm7', '{}', 1767265400000, 'c-alan', 'keychange', NULL, 0, 0, NULL, 0);
INSERT INTO message_attachments VALUES ('m3', -1, 'attachment', 0, 'image/jpeg', 'tides.jpg');
INSERT INTO message_attachments VALUES ('m3', -1, 'preview', 1, 'image/png', 'link-preview.png');
INSERT INTO callsHistory VALUES ('k1', 'aaaaaaaa-0000-4000-8000-000000000002', 'aaaaaaaa-0000-4000-8000-000000000002', 'Direct', 'Audio', 'Incoming', 'Accepted', 1767270000000, 1767270300000);
INSERT INTO callsHistory VALUES ('k2', 'group-1', 'aaaaaaaa-0000-4000-8000-000000000003', 'Group', 'Group', 'Incoming', 'Missed', 1767271000000, NULL);
