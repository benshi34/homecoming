__artifacts_v2__ = {
    "corpusXDirectMessages": {
        "name": "X - Direct Messages (dmv2)",
        "description": "Direct messages from the X (Twitter) app's per-account dmv2.db, where current versions keep "
                       "DMs. The upstream twitterX module reads Library/Caches/com.atebits.tweetie.direct-message.cache, "
                       "which iTunes/Finder backups don't include.",
        "author": "q1_user_model",
        "creation_date": "2026-10-07",
        "last_update_date": "2026-10-07",
        "requirements": "none",
        "category": "Twitter",
        "notes": "One database per signed-in account, named <account id>-dmv2.db. Only entry_type 'message' rows are "
                 "messages; the others are join, read and conversation-change events.",
        "paths": ('*/com.atebits.tweetie.databases/v1/*/*-dmv2.db*',),
        "output_types": "standard",
        "artifact_icon": "message",
        "data_views": {
            "conversation": {
                "conversationDiscriminatorColumn": "conversation_id",
                "conversationLabelColumn": "conversation",
                "textColumn": "message",
                "directionColumn": "direction",
                "directionSentValue": "Outgoing",
                "timeColumn": "timestamp",
                "senderColumn": "sender",
            }
        },
    }
}

import os

from scripts.ilapfuncs import artifact_processor, convert_unix_ts_to_utc, open_sqlite_db_readonly


@artifact_processor
def corpusXDirectMessages(context):
    data_list, sources = [], []
    for file_found in context.get_files_found():
        file_found = str(file_found)
        if not file_found.endswith('-dmv2.db'):
            continue
        account = os.path.basename(file_found).split('-')[0]
        db = open_sqlite_db_readonly(file_found)
        if not db:
            continue
        sources.append(file_found)
        cur = db.cursor()
        users = {str(r[0]): r[1] or r[2] or str(r[0]) for r in
                 cur.execute("SELECT id, screen_name, nickname FROM dm_user")}
        titles = {r[0]: r[1] for r in cur.execute("SELECT conversation_id, custom_title FROM dm_conversation")}
        cur.execute("""SELECT entry_id, conversation_id, timestamp, sender_id, sender_is_owner, plain_text,
                              has_attachment, attachment_types, message_status
                       FROM dm_entry WHERE entry_type = 'message' ORDER BY timestamp""")
        for entry_id, conv, ts, sender, owner, text, has_att, att_types, status in cur.fetchall():
            others = [users.get(i, i) for i in (conv or '').split(':') if i and i != account]
            label = titles.get(conv) or ', '.join(dict.fromkeys(others)) or conv
            data_list.append((convert_unix_ts_to_utc(ts), account, users.get(account, account), conv, label,
                              'Outgoing' if owner else 'Incoming', users.get(str(sender), str(sender)), text,
                              'Yes' if has_att else 'No', att_types, status, entry_id,
                              context.get_relative_path(file_found)))
        db.close()
    data_headers = (('Timestamp', 'datetime'), 'Account ID', 'Account', 'Conversation ID', 'Conversation',
                    'Direction', 'Sender', 'Message', 'Has Attachment', 'Attachment Types', 'Message Status',
                    'Message ID', 'Source File')
    return data_headers, data_list, '\n'.join(sources)
