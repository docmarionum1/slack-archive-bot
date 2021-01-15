import argparse
import datetime
import logging
import os
import sqlite3
import time
import traceback
from websocket import WebSocketConnectionClosedException

from slack_bolt import App

parser = argparse.ArgumentParser()
parser.add_argument('-d', '--database-path', default='slack.sqlite', help=(
                    'path to the SQLite database. (default = ./slack.sqlite)'))
parser.add_argument('-l', '--log-level', default='debug', help=(
                    'CRITICAL, ERROR, WARNING, INFO or DEBUG (default = DEBUG)'))
parser.add_argument('-p', '--port', default=3333, help='Port to serve on. (default = 3333)')
args = parser.parse_args()

log_level = args.log_level.upper()
assert log_level in ['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG']
logging.basicConfig(level=getattr(logging, log_level))
logger = logging.getLogger(__name__)

database_path = args.database_path

# Connects to the previously created SQL database
def db_connect():
    conn = sqlite3.connect(database_path)
    cursor = conn.cursor()
    return conn, cursor




app = App(
    token=os.environ.get("SLACK_BOT_TOKEN"),
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET"),
    logger=logger
)

# Save the bot user's user ID
app._bot_user_id = app.client.auth_test()['user_id']

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
def update_users(conn, cursor):
    logger.info('Updating users')
    info = app.client.users_list()

    ENV['user_id'] = dict([(m['profile']['display_name'], m['id']) for m in info['members']])
    ENV['id_user'] = dict([(m['id'], m['profile']['display_name']) for m in info['members']])

    args = []
    for m in info['members']:
        args.append((
            m['profile']['display_name'],
            m['id'],
            m['profile'].get('image_72', 'https://secure.gravatar.com/avatar/c3a07fba0c4787b0ef1d417838eae9c5.jpg?s=32&d=https%3A%2F%2Ffst.slack-edge.com%2F66f9%2Fimg%2Favatars%2Fava_0024-32.png')
        ))
    cursor.executemany("INSERT INTO users(name, id, avatar) VALUES(?,?,?)", args)
    conn.commit()

def get_user_id(name):
    """
    Get a user's user_id given their name; Used to resolve from:@X queries.
    """
    return ENV['user_id'].get(name, None)

def update_channel(channel_id):
    channel = app.client.conversations_info(channel=channel_id)['channel']

    ENV['channel_id'][channel['name']] = channel['id']
    ENV['id_channel'][channel['id']] = channel['name']

    # If the channel is private, we need to get the member list
    if channel['is_private']:
        response = app.client.conversations_members(channel=channel['id'])
        members = response['members']
        while response['response_metadata']['next_cursor']:
            response = app.client.conversations_members(channel=channel['id'])
            members += response['members']
        members = set(members)
    else:
        members = set()

    ENV['channel_info'][channel['id']] = {
        'is_private': channel['is_private'],
        'members': members
    }

    return channel['id'], channel['name']

def update_channels(conn, cursor):
    logger.info("Updating channels")
    channels = app.client.conversations_list(types='public_channel,private_channel')['channels']

    args = []
    for channel in channels:
        # Only add channels that archive bot is a member of
        if not channel['is_member']:
            continue

        update_channel(channel['id'])

        args.append((
            channel['name'],
            channel['id']
        ))

    cursor.executemany("INSERT INTO channels(name, id) VALUES(?,?)", args)
    conn.commit()


def get_channel_id(name):
    return ENV['channel_id'].get(name, None)


def can_query_channel(channel_id, user_id):
    if channel_id in ENV['id_channel']:
        return (
            (not ENV['channel_info'][channel_id]['is_private']) or
            (user_id in ENV['channel_info'][channel_id]['members'])
        )


def handle_query(event, cursor, say):
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
                        raise ValueError(f'User {p[1]} not found')
                if p[0] == 'in':
                    channel = get_channel_id(p[1].replace('#','').strip())
                    if channel is None:
                        raise ValueError(f'Channel {p[1]} not found. Either {p[1]} does not exist or Archive Bot is not a member of {p[1]}.')
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

        query = 'SELECT message,user,timestamp,channel FROM messages WHERE message LIKE (?)'
        query_args=["%"+" ".join(text)+"%"]

        if user:
            query += ' AND user=(?)'
            query_args.append(user)
        if channel:
            query += ' AND channel=(?)'
            query_args.append(channel)
        if sort:
            query += ' ORDER BY timestamp %s' % sort

        logger.debug(query)
        logger.debug(query_args)

        cursor.execute(query,query_args)

        res = cursor.fetchmany(limit)
        res_message=None
        if res:
            logger.debug(res)
            res_message = '\n'.join(
                ['*<@%s>* _<!date^%s^{date_pretty} {time}|A while ago>_ _<#%s>_\n%s\n\n' % (
                    i[1], int(float(i[2])), i[3], i[0]
                ) for i in res if can_query_channel(i[3], event['user'])]
            )
        if res_message:
            say(res_message)
        else:
            say('No results found')
    except ValueError as e:
        logger.error(traceback.format_exc())
        say(str(e))

@app.event('member_joined_channel')
def handle_join(event):
    #print(event)
    print(event)
    conn, cursor = db_connect()

    # If the user added is archive bot, then add the channel too
    if event['user'] == app._bot_user_id:
        channel_id, channel_name = update_channel(event['channel'])
        cursor.execute("INSERT INTO channels(name, id) VALUES(?,?)", (channel_id, channel_name))
    elif event['channel'] in ENV['id_channel']:
        ENV['channel_info'][event['channel']]['members'].add(event['user'])

    print(ENV)

@app.event('member_left_channel')
def handle_left(event):
    if event['channel'] in ENV['channel_info']:
        ENV['channel_info'][event['channel']]['members'].discard(event['user'])

def handle_rename(event):
    channel = event['channel']
    channel_id = channel['id']
    new_channel_name = channel['name']
    old_channel_name = ENV['id_channel'][channel_id]

    ENV['id_channel'][channel_id] = new_channel_name
    del ENV['channel_id'][old_channel_name]
    ENV['channel_id'][new_channel_name] = channel_id

    conn, cursor = db_connect()
    cursor.execute("UPDATE channels SET name = ? WHERE id = ?", (new_channel_name, channel_id))
    conn.commit()

@app.event('channel_rename')
def handle_channel_rename(event):
    handle_rename(event)

@app.event('group_rename')
def handle_group_rename(event):
    handle_rename(event)

# For some reason slack fires off both *_rename and *_name events, so create handlers for them
# but don't do anything in the *_name events.
@app.event({
    "type": "message",
    "subtype": "group_name"
})
def handle_group_name(event):
    pass

@app.event({
    "type": "message",
    "subtype": "channel_name"
})
def handle_channel_name(event):
    pass

@app.event('user_change')
def handle_user_change(event):
    print("USER CHANGE MY GOD")
    print(event)

    user_id = event['user']['id']
    new_username = event['user']['profile']['display_name']
    old_username = ENV['id_user'][user_id]

    ENV['id_user'][user_id] = new_username
    del ENV['user_id'][old_username]
    ENV['user_id'][new_username] = user_id

    conn, cursor = db_connect()
    cursor.execute("UPDATE users SET name = ? WHERE id = ?", (new_username, user_id))
    conn.commit()

@app.message('')
def handle_message(message, say):
    logger.debug(message)
    if 'text' not in message or message['user'] == 'USLACKBOT':
        return

    conn, cursor = db_connect()

    # If it's a DM, treat it as a search query
    if message['channel_type'] == 'im':
        handle_query(message, cursor, say)
    elif 'user' not in message:
        logger.warn("No valid user. Previous event not saved")
    else: # Otherwise save the message to the archive.
        cursor.executemany('INSERT INTO messages VALUES(?, ?, ?, ?)',
            [(message['text'], message['user'], message['channel'], message['ts'])]
        )
        conn.commit()

        # Ensure that the user exists in the DB/ENV
        if message['user'] not in ENV['id_user']:
            update_users(conn, cursor)

    logger.debug("--------------------------")

if __name__ == '__main__':
    # Initialize the DB if it doesn't exist
    conn, cursor = db_connect()
    cursor.execute('create table if not exists messages (message text, user text, channel text, timestamp text, UNIQUE(channel, timestamp) ON CONFLICT REPLACE)')
    cursor.execute('create table if not exists users (name text, id text, avatar text, UNIQUE(id) ON CONFLICT REPLACE)')
    cursor.execute('create table if not exists channels (name text, id text, UNIQUE(id) ON CONFLICT REPLACE)')
    conn.commit()

    # Update the users and channels in the DB and in the local memory mapping
    update_users(conn, cursor)
    update_channels(conn, cursor)
    #print(ENV)

    #1/0
    app.start(port=args.port)
