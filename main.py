import os
import sqlite3
import time
from slackclient import SlackClient

conn = sqlite3.connect('messages.sqlite')
cursor = conn.cursor()
cursor.execute('create table if not exists messages (message text, user text, channel text, timestamp real, UNIQUE(user, timestamp) ON CONFLICT REPLACE)')

slack_token = os.environ["SLACK_API_TOKEN"]
sc = SlackClient(slack_token)

'''for channel in sc.api_call("channels.list", exclude_archived=1)['channels']:
    if not channel['is_member']:
        print(sc.api_call(
          "channels.join",
          channel=channel['id']
        ))

exit()'''

channels = {}
def get_channel_name(id):
    if id[0] == 'D':
        return "DM"

    if id not in channels:
        info = sc.api_call(
          "channels.info",
          channel=id
        )
        channels[id] = {
            'name': info['channel']['name'],
            'previous_names': info['channel']['previous_names']
        }

    return channels[id]['name']

def get_user_name(id):
    info = sc.api_call(
      "users.info",
      user=id
    )
    print(info)

#get_user_name('U0766LV3J')
#exit()

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
        cursor.execute(
            'SELECT message FROM messages WHERE message LIKE "%%%s%%"' % event['text']
        )
        print(sc.api_call(
          "chat.postMessage",
          channel=event['channel'],
          text=str(cursor.fetchmany(10))
        ))
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
        for event in sc.rtm_read():
            if event['type'] == 'message':
                handle_message(event)
        time.sleep(1)
else:
    print("Connection Failed, invalid token?")
