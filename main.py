import datetime
import os
import sqlite3
import time
import traceback

from slackclient import SlackClient

conn = sqlite3.connect('messages.sqlite')
cursor = conn.cursor()
cursor.execute('create table if not exists messages (message text, user text, channel text, timestamp text, UNIQUE(channel, timestamp) ON CONFLICT REPLACE)')

slack_token = os.environ["SLACK_API_TOKEN"]
sc = SlackClient(slack_token)

ENV = {
    'user_id': {},
    'id_user': {},
    'channel_id': {},
    'id_channel': {}
}

def update_users():
    info = sc.api_call('users.list')
    ENV['user_id'] = dict([(m['name'], m['id']) for m in info['members']])
    ENV['id_user'] = dict([(m['id'], m['name']) for m in info['members']])

def get_user_name(uid):
    if uid not in ENV['id_user']:
        update_users()
    return ENV['id_user'].get(uid, None)

def get_user_id(name):
    if name not in ENV['user_id']:
        update_users()
    return ENV['user_id'].get(name, None)


def update_channels():
    info = sc.api_call('channels.list')
    ENV['channel_id'] = dict([(m['name'], m['id']) for m in info['channels']])
    ENV['id_channel'] = dict([(m['id'], m['name']) for m in info['channels']])

def get_channel_name(uid):
    if uid not in ENV['id_channel']:
        update_channels()
    return ENV['id_channel'].get(uid, None)

def get_channel_id(name):
    if name not in ENV['channel_id']:
        update_channels()
    return ENV['channel_id'].get(name, None)

def send_message(message, channel):
    sc.api_call(
      "chat.postMessage",
      channel=channel,
      text=message
    )

def convert_timestamp(ts):
    return datetime.datetime.fromtimestamp(
        int(ts.split('.')[0])
    ).strftime('%Y-%m-%d %H:%M:%S')

def handle_query(event):
    try:
        text = []
        user = None
        channel = None
        sort = None
        limit = 10

        params = event['text'].lower().split()
        for p in params:
            # Handle emoji
            if len(p) > 2 and p[0] == ':' and p[-1] == ':':
                text.append(p)
                continue

            p = p.split(':')

            if len(p) == 1:
                text.append(p[0])
            if len(p) == 2:
                if p[0] == 'from':
                    user = get_user_id(p[1].replace('@','').strip())
                    if user is None:
                        raise ValueError('User %s not found' % p[1])
                if p[0] == 'in':
                    channel = get_channel_id(p[1].replace('#','').strip())
                    if channel is None:
                        raise ValueError('Channel %s not found' % p[1])
                if p[0] == 'sort':
                    if p[1] in ['asc', 'desc']:
                        sort = p[1]
                    else:
                        raise ValueError('Invalid sort order %s' % p[1])
                if p[0] == 'limit':
                    try:
                        limit = int(p[1])
                    except:
                        raise ValueError('%s not a valid number' % p[1])

        query = 'SELECT message,user,timestamp FROM messages WHERE message LIKE "%%%s%%"' % " ".join(text)
        if user:
            query += ' AND user="%s"' % user
        if channel:
            query += ' AND channel="%s"' % channel
        if sort:
            query += ' ORDER BY timestamp %s' % sort

        print(query)

        cursor.execute(query)

        res = cursor.fetchmany(limit)
        if res:
            send_message('\n'.join(
                ['%s (@%s, %s)' % (
                    i[0], get_user_name(i[1]), convert_timestamp(i[2])
                ) for i in res]
            ), event['channel'])
        else:
            send_message('No results found', event['channel'])
    except ValueError as e:
        print(traceback.format_exc())
        send_message(str(e), event['channel'])

def handle_message(event):
    if 'text' not in event:
        return
    if 'username' in event and event['username'] == 'bot':
        return

    try:
        print(event)
    except:
        print("*"*20)

    if event['channel'][0] == 'D':
        handle_query(event)
    else:
        print(
            event['text'], event['user'], event['channel'], event['ts']
        )
        cursor.executemany('INSERT INTO messages VALUES(?, ?, ?, ?)',
            [(event['text'], event['user'], event['channel'], event['ts'])]
        )
        conn.commit()

if sc.rtm_connect():
    while True:
        try:
            for event in sc.rtm_read():
                if event['type'] == 'message':
                    handle_message(event)
        except:
            print(traceback.format_exc())
        time.sleep(1)
else:
    print("Connection Failed, invalid token?")
