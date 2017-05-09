import glob
import json
import os
import sqlite3
import sys

directory = sys.argv[1]

conn = sqlite3.connect('messages.sqlite')
cursor = conn.cursor()
cursor.execute('create table if not exists messages (message text, user text, channel text, timestamp text, UNIQUE(channel, timestamp) ON CONFLICT REPLACE)')

with open(os.path.join(directory, 'channels.json')) as f:
    channels = json.load(f)

for channel in channels:
    print(channel['name'])

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
