import os
import time
import logging
import sqlite3

from slackclient import SlackClient
from websocket import WebSocketConnectionClosedException

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("main")

# Connects to the previously created SQL database
# TODO: lock on slack.sqlite to ensure only one instance is running

conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), 'slack.sqlite'))
conn.row_factory = sqlite3.Row


try:
    conn.execute('ALTER TABLE messages ADD COLUMN thread_timestamp TEXT')
except sqlite3.OperationalError:
    pass  # this is ok. It just means the column already exists.
conn.execute('create table if not exists messages (message text, user text, channel text, timestamp text, thread_timestamp text, UNIQUE(channel, timestamp) ON CONFLICT REPLACE)')
conn.execute('create table if not exists users (name text, id text, avatar text, UNIQUE(id) ON CONFLICT REPLACE)')
conn.execute('create table if not exists channels (name text, id text, UNIQUE(id) ON CONFLICT REPLACE)')

# This token is given when the bot is started in terminal
slack_token = os.environ['SLACK_API_TOKEN']

# Makes bot user active on Slack
# NOTE: terminal must be running for the bot to continue
sc = SlackClient(slack_token)

known_channels = set(record[0] for record in conn.execute("SELECT channel, count(*) FROM messages"))


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
def update_users(conn):
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
    conn.executemany('INSERT INTO users(name, id, avatar) VALUES(?,?,?)', args)


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


def update_channels(conn):
    info = sc.api_call('channels.list')
    ENV['channel_id'] = dict([(m['name'], m['id']) for m in info['channels']])
    ENV['id_channel'] = dict([(m['id'], m['name']) for m in info['channels']])

    args = []
    for m in info['channels']:
        args.append((
            m['name'],
            m['id'] ))
    conn.executemany('INSERT INTO channels(name, id) VALUES(?,?)', args)


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

        query += ' LIMIT {}'.format(limit)
        logger.debug(query)

        res = conn.execute(query)

        if res:
            send_message('\n\n'.join(
                [format_response(line)
                 for line in res]
            ), event['channel'])
        else:
            send_message('No results found', event['channel'])
    except ValueError as e:
        logger.exception('During query')
        send_message(str(e), event['channel'])


def handle_message(conn, event):
    if 'text' not in event:
        return
    if 'username' in event and event['username'] == 'bot':
        return

    try:
        logger.debug(event)
    except:
        logger.debug('*' * 20)

    # If it's a DM, treat it as a search query
    channel = event['channel']
    if channel[0] == 'D':
        handle_query(event)
    elif 'user' not in event:
        logger.debug('No valid user. Previous event not saved')
    else:  # Otherwise save the message to the archive.
        if channel not in known_channels:
            logger.debug("{} is a new channel. Stand by while syncing its history".format(channel))
            known_channels.add(channel)
            sync_channel(channel_id=channel, conn=conn)

        conn.execute('INSERT INTO messages VALUES(?, ?, ?, ?, ?)',
                     (event['text'],
                      event['user'],
                      event['channel'],
                      event['ts'],
                      event.get('thread_ts')))
        logger.debug('--------------------------')


def format_response(line):
    # message, user, timestamp, channel, thread_timestamp, thread_title):
    message = '\n'.join(map(lambda s: '> %s' % s, line['message'].split('\n')))  # add > before each line
    username = get_user_name(line['user'])
    timestamp = get_timestamp(line['timestamp'])
    if line['thread_timestamp'] is not None:
        thread_timestamp = get_timestamp(line['thread_timestamp'])
        return '*<@%s> <#%s> <!date^%s^{date_short} {time_secs}|date>* <!date^%s^{date_short} {time_secs}|date>*\n %s %s)' % (username, line['channel'], timestamp, thread_timestamp, line['thread_title'], message)
    else:
        return '*<@%s> <#%s> <!date^%s^{date_short} {time_secs}|date>*\n%s)' % (username, line['channel'], timestamp, message)


def update_channel_history(conn):
    """
    For each channel we have previously received, check if there are any later messages
    which we missed
    """
    channels_map = dict(record for record in conn.execute("SELECT channel, MAX(timestamp) as latest_timestamp FROM messages"))
    for channel_id, last_seen in channels_map.items():
        if channel_id is not None:
            # FIXME: if channel is archived or deleted,
            # this will raise an exception - which is OK.
            # But during development/testing, we'll keep it failing
            # to catch issues with the sync
            sync_channel(channel_id=channel_id, oldest=last_seen, conn=conn)


def sync_channel(conn, channel_id, oldest=None):
    """
    Keeps reading channel history until we have caught up.
    """
    latest = None
    logger.info("Checking channel {}".format(channel_id))
    has_more = True
    total = 0
    api_name = 'groups.history' if channel_id.startswith('G') else 'channels.history'
    while has_more:
        kw = dict()
        if oldest is not None:
            kw['oldest'] = oldest
        if latest is not None:
            kw['latest'] = latest
        result = sc.api_call(api_name,
                             channel=channel_id,
                             **kw)
        if not result['ok']:
            raise Exception(result['error'])

        timestamps = set()
        for message in result['messages']:
            message['channel'] = channel_id
            timestamps.add(float(message['ts']))
            handle_message(conn=conn, event=message)
        total += len(result['messages'])

        logger.info("Processed {} messages so far".format(total))
        if len(timestamps) > 0:
            latest = min(timestamps)
        has_more = result['has_more']


# Loop
if sc.rtm_connect():
    with conn:
        update_users(conn)
        logger.info('Users updated')
        update_channels(conn)
        logger.info('Channels updated')
        update_channel_history(conn)
        logger.info('Archive bot online. Messages will now be recorded...')
    while True:
        try:
            for event in sc.rtm_read():
                if event['type'] == 'message':
                    with conn:
                        handle_message(conn=conn, event=event)
        except WebSocketConnectionClosedException:
            sc.rtm_connect()
        except:
            logger.exception("In main RTC loop")
        time.sleep(1)
else:
    logger.error('Connection Failed, invalid token?')
