import glob
import json
import os
import sqlite3
import sys

# of slack archive
directory = sys.argv[1]

conn = sqlite3.connect('slack.sqlite')
cursor = conn.cursor()
cursor.execute('create table if not exists messages (message text, user text, channel text, timestamp text, UNIQUE(channel, timestamp) ON CONFLICT REPLACE)')
cursor.execute('create table if not exists users (name text, id text, text avatar, UNIQUE(id) ON CONFLICT REPLACE)')
cursor.execute('create table if not exists channels (name text, id text, UNIQUE(id) ON CONFLICT REPLACE)')

print("Importing channels..")
with open(os.path.join(directory, 'channels.json')) as f:
    channels = json.load(f)
args = [(c['name'], c['id']) for c in channels]
cursor.executemany('INSERT INTO channels VALUES(?,?)', (args))
print("- Channels imported")

print("Importing users..")
with open(os.path.join(directory, 'users.json')) as f:
    users = json.load(f)
args = [(u['name'], u['id'], u['profile']['image_32']) for u in users]
cursor.executemany('INSERT INTO users VALUES(?,?,?)', (args))
print("- Users imported")

print("Importing messages..")
for channel in channels:
    files = glob.glob(os.path.join(directory, channel['name'], '*.json'))
    for file_name in files:
        with open(file_name) as f:
            messages = json.load(f)

        args = []
        for message in messages:
            if ('id' in channel and 'ts' in message):
                args.append((
                    message['text'] if 'text' in message else "~~There is a message ommitted here~~",
                    message['user'] if 'user' in message else "", channel['id'], message['ts']
                ))
            else:
                print("In "+file_name+": An exception occured, message not added to archive.")

        cursor.executemany('INSERT INTO messages VALUES(?, ?, ?, ?)', args)
        conn.commit()
print("- Messages imported")
print("Done")
