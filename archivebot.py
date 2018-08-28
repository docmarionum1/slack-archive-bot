import datetime
import os
import sqlite3
import time
import traceback

from slackclient import SlackClient
from websocket import WebSocketConnectionClosedException

# Connects to the previously created SQL database
conn = sqlite3.connect('slack.sqlite')
cursor = conn.cursor()
cursor.execute('create table if not exists messages (message text, user text, channel text, timestamp text, UNIQUE(channel, timestamp) ON CONFLICT REPLACE)')
cursor.execute('create table if not exists users (name text, id text, avatar text, UNIQUE(id) ON CONFLICT REPLACE)')
cursor.execute('create table if not exists channels (name text, id text, UNIQUE(id) ON CONFLICT REPLACE)')

# This token is given when the bot is started in terminal
slack_token = os.environ["SLACK_API_TOKEN"]

# Makes bot user active on Slack
# NOTE: terminal must be running for the bot to continue
sc = SlackClient(slack_token)

# Double naming for better search functionality
# Keys are both the name and unique ID where needed
ENV = {
    'user_id': {},
    'id_user': {},
    'channel_id': {},
    'id_channel': {},
    'channel_info': {}
}

# Uses slack API to get most recent user list
# Necessary for User ID correlation
def update_users():
    print('Updating users')
    info = sc.api_call('users.list')
    ENV['user_id'] = dict([(m['name'], m['id']) for m in info['members']])
    ENV['id_user'] = dict([(m['id'], m['name']) for m in info['members']])

    args = []
    for m in info['members']:
        args.append((
            m['name'],
            m['id'],
            m['profile'].get('image_72', 'https://secure.gravatar.com/avatar/c3a07fba0c4787b0ef1d417838eae9c5.jpg?s=32&d=https%3A%2F%2Ffst.slack-edge.com%2F66f9%2Fimg%2Favatars%2Fava_0024-32.png')
        ))
    cursor.executemany("INSERT INTO users(name, id, avatar) VALUES(?,?,?)", args)
    conn.commit()

def get_user_name(uid):
    if uid not in ENV['id_user']:
        update_users()
    return ENV['id_user'].get(uid, None)

def get_user_id(name):
    if name not in ENV['user_id']:
        update_users()
    return ENV['user_id'].get(name, None)


def update_channels():
    print("Updating channels")
    info = sc.api_call('channels.list')['channels'] + sc.api_call('groups.list')['groups']
    ENV['channel_id'] = dict([(m['name'], m['id']) for m in info])
    ENV['id_channel'] = dict([(m['id'], m['name']) for m in info])

    args = []
    for m in info:
        ENV['channel_info'][m['id']] = {
            'is_private': ('is_group' in m) or m['is_private'],
            'members': m['members']
        }

        args.append((
            m['name'],
            m['id']
        ))

    cursor.executemany("INSERT INTO channels(name, id) VALUES(?,?)", args)
    conn.commit()

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

def can_query_channel(channel_id, user_id):
    if channel_id in ENV['id_channel']:
        return (
            (not ENV['channel_info'][channel_id]['is_private']) or
            (user_id in ENV['channel_info'][channel_id]['members'])
        )


def handle_query(event):
    """
    Handles a DM to the bot that is requesting a search of the archives.

    Usage:

        <query> from:<user> in:<channel> sort:asc|desc limit:<number>

        query: The text to search for.
        user: If you want to limit the search to one user, the username.
        channel: If you want to limit the search to one channel, the channel name.
        sort: Either asc if you want to search starting with the oldest messages,
            or desc if you want to start from the newest. Default asc.
        limit: The number of responses to return. Default 10.
    """
    try:
        text = []
        user = None
        channel = None
        sort = None
        limit = 10

        params = event['text'].lower().split()
        for p in params:
            # Handle emoji
            # usual format is " :smiley_face: "
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

        query = 'SELECT message,user,timestamp,channel FROM messages WHERE message LIKE "%%%s%%"' % " ".join(text)
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
            print(res)
            send_message('\n'.join(
                ['%s (@%s, %s, %s)' % (
                    i[0], get_user_name(i[1]), convert_timestamp(i[2]), '#'+get_channel_name(i[3])
                ) for i in res if can_query_channel(i[3], event['user'])]
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

    # If it's a DM, treat it as a search query
    if event['channel'][0] == 'D':
        handle_query(event)
    elif 'user' not in event:
        print("No valid user. Previous event not saved")
    else: # Otherwise save the message to the archive.
        cursor.executemany('INSERT INTO messages VALUES(?, ?, ?, ?)',
            [(event['text'], event['user'], event['channel'], event['ts'])]
        )
        conn.commit()
        print("--------------------------")

# Loop
if sc.rtm_connect(auto_reconnect=True):
    update_users()
    update_channels()
    print('Archive bot online. Messages will now be recorded...')
    while sc.server.connected is True:
        try:
            for event in sc.rtm_read():
                if event['type'] == 'message':
                    handle_message(event)
                    if 'subtype' in event and event['subtype'] in ['group_leave']:
                        update_channels()
                elif event['type'] in ['group_joined', 'member_joined_channel', 'channel_created', 'group_left']:
                    update_channels()
        except WebSocketConnectionClosedException:
            sc.rtm_connect()
        except:
            print(traceback.format_exc())
        time.sleep(1)
else:
    print(datetime.datetime.now() + "Connection Failed, invalid token?")
