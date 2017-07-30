import os
import sqlite3
import time
import traceback

from slackclient import SlackClient
from websocket import WebSocketConnectionClosedException

# Connects to the previously created SQL database
# TODO: lock on slack.sqlite to ensure only one instance is running

conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), 'slack.sqlite'))

cursor = conn.cursor()
try:
    cursor.execute('ALTER TABLE messages ADD COLUMN thread_timestamp TEXT')
except sqlite3.OperationalError:
    pass  # this is ok. It just means the column already exists.
cursor.execute('create table if not exists messages (message text, user text, channel text, timestamp text, thread_timestamp text, UNIQUE(channel, timestamp) ON CONFLICT REPLACE)')
cursor.execute('create table if not exists users (name text, id text, avatar text, UNIQUE(id) ON CONFLICT REPLACE)')
cursor.execute('create table if not exists channels (name text, id text, UNIQUE(id) ON CONFLICT REPLACE)')

# This token is given when the bot is started in terminal
slack_token = os.environ['SLACK_API_TOKEN']

# Makes bot user active on Slack
# NOTE: terminal must be running for the bot to continue
sc = SlackClient(slack_token)

cursor.execute("SELECT DISTINCT channel FROM messages")
known_channels = set(record[0] for record in cursor)


# Double naming for better search functionality
# Keys are both the name and unique ID where needed
ENV = {
    'user_id': {},
    'id_user': {},
    'channel_id': {},
    'id_channel': {}
}


# Uses slack API to get most recent user list
# Necessary for User ID correlation
def update_users():
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
    cursor.executemany('INSERT INTO users(name, id, avatar) VALUES(?,?,?)', args)
    conn.commit()


def get_user_name(uid):
    if uid not in ENV['id_user']:
        update_users()
    return ENV['id_user'].get(uid, None)


def get_user_id(name):
    if name not in ENV['user_id']:
        update_users()
    return ENV['user_id'].get(name, None)


def get_timestamp(ts):
    return int(ts.split('.')[0])


def update_channels():
    info = sc.api_call('channels.list')
    ENV['channel_id'] = dict([(m['name'], m['id']) for m in info['channels']])
    ENV['id_channel'] = dict([(m['id'], m['name']) for m in info['channels']])

    args = []
    for m in info['channels']:
        args.append((
            m['name'],
            m['id'] ))
    cursor.executemany('INSERT INTO channels(name, id) VALUES(?,?)', args)
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
      'chat.postMessage',
      channel=channel,
      text=message
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
                    user = get_user_id(p[1].replace('@', '').strip())
                    if user is None:
                        raise ValueError('User %s not found' % p[1])
                if p[0] == 'in':
                    channel = get_channel_id(p[1].replace('#', '').strip())
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

        query = '''
SELECT messages.*,
       tm.message AS thread_title
FROM messages
LEFT OUTER JOIN (SELECT timestamp, message, user, channel FROM messages) tm
    ON (messages.thread_timestamp = tm.timestamp AND
        messages.channel = tm.channel)
WHERE messages.message LIKE "%%%s%%"
ORDER BY COALESCE(tm.timestamp, messages.timestamp), messages.timestamp
''' % ' '.join(text)
        if user:
            query += ' AND user="%s"' % user
        if channel:
            query += ' AND channel="%s"' % channel
        if sort:
            query += ' ORDER BY timestamp %s' % sort

        print(query)

        cursor.execute(query)
        column_names = [col[0] for col in cursor.description]

        res = cursor.fetchmany(limit)
        if res:
            send_message('\n\n'.join(
                [format_response(**dict(zip(column_names, line)))
                 for line in res]
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
        print('*' * 20)

    # If it's a DM, treat it as a search query
    channel = event['channel']
    if channel[0] == 'D':
        handle_query(event)
    elif 'user' not in event:
        print('No valid user. Previous event not saved')
    else:  # Otherwise save the message to the archive.
        if channel not in known_channels:
            print("{} is a new channel. Stand by while syncing its history".format(channel))
            known_channels.add(channel)
            sync_channel(channel)

        cursor.executemany('INSERT INTO messages VALUES(?, ?, ?, ?, ?)',
                           [(event['text'],
                             event['user'],
                             event['channel'],
                             event['ts'],
                             event.get('thread_ts'))])
        conn.commit()
        print('--------------------------')


def format_response(message, user, timestamp, channel, thread_timestamp, thread_title):
    message = '\n'.join(map(lambda s: '> %s' % s, message.split('\n')))  # add > before each line
    username = get_user_name(user)
    timestamp = get_timestamp(timestamp)
    if thread_timestamp is not None:
        thread_timestamp = get_timestamp(thread_timestamp)
        return '*<@%s> <#%s> <!date^%s^{date_short} {time_secs}|date>* <!date^%s^{date_short} {time_secs}|date>*\n %s %s)' % (username, channel, timestamp, thread_timestamp, thread_title, message)
    else:
        return '*<@%s> <#%s> <!date^%s^{date_short} {time_secs}|date>*\n%s)' % (username, channel, timestamp, message)


def update_channel_history():
    """
    For each channel we have previously received, check if there are any later messages
    which we missed
    """
    cursor.execute("SELECT channel, MAX(timestamp) as latest_timestamp FROM messages")
    channels_map = dict(record for record in cursor)
    for channel_id, latest in channels_map.items():
        if channel_id is not None:
            sync_channel(channel_id=channel_id, oldest=latest)


def sync_channel(channel_id, **kw):
    print("Checking channel {}".format(channel_id))
    has_more = True
    total = 0
    while has_more:
        print("Reading channel, as more messages are pending")
        result = sc.api_call('channels.history',
                             channel=channel_id,
                             **kw)
        for message in result['messages']:
            message['channel'] = channel_id
            handle_message(message)
        total += len(result['messages'])
        print("Processed {} messages so far".format(total))
        kw['oldest'] = result.get('latest')
        has_more = result['has_more']


# Loop
if sc.rtm_connect():
    update_users()
    print('Users updated')
    update_channels()
    print('Channels updated')
    update_channel_history()
    print('Archive bot online. Messages will now be recorded...')
    while True:
        try:
            for event in sc.rtm_read():
                if event['type'] == 'message':
                    handle_message(event)
        except WebSocketConnectionClosedException:
            sc.rtm_connect()
        except:
            print(traceback.format_exc())
        time.sleep(1)
else:
    print('Connection Failed, invalid token?')
