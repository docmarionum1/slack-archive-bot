import argparse
import logging
import os
import traceback

from slack_bolt import App

from utils import db_connect, migrate_db

parser = argparse.ArgumentParser()
parser.add_argument(
    "-d",
    "--database-path",
    default="slack.sqlite",
    help=("path to the SQLite database. (default = ./slack.sqlite)"),
)
parser.add_argument(
    "-l",
    "--log-level",
    default="debug",
    help=("CRITICAL, ERROR, WARNING, INFO or DEBUG (default = DEBUG)"),
)
parser.add_argument(
    "-p", "--port", default=3333, help="Port to serve on. (default = 3333)"
)
cmd_args, unknown = parser.parse_known_args()

# Check the environment too
log_level = os.environ.get("ARCHIVE_BOT_LOG_LEVEL", cmd_args.log_level)
database_path = os.environ.get("ARCHIVE_BOT_DATABASE_PATH", cmd_args.database_path)
port = os.environ.get("ARCHIVE_BOT_PORT", cmd_args.port)

# Setup logging
log_level = log_level.upper()
assert log_level in ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]
logging.basicConfig(level=getattr(logging, log_level))
logger = logging.getLogger(__name__)


app = App(
    token=os.environ.get("SLACK_BOT_TOKEN"),
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET"),
    logger=logger,
)

# Save the bot user's user ID
app._bot_user_id = app.client.auth_test()["user_id"]

# Uses slack API to get most recent user list
# Necessary for User ID correlation
def update_users(conn, cursor):
    logger.info("Updating users")
    info = app.client.users_list()

    args = []
    for m in info["members"]:
        args.append(
            (
                m["profile"]["display_name"],
                m["id"],
                m["profile"].get(
                    "image_72",
                    "http://fst.slack-edge.com/66f9/img/avatars/ava_0024-32.png",
                ),
            )
        )
    cursor.executemany("INSERT INTO users(name, id, avatar) VALUES(?,?,?)", args)
    conn.commit()


def get_channel_info(channel_id):
    channel = app.client.conversations_info(channel=channel_id)["channel"]

    # Get a list of members for the channel. This will be used when querying private channels.
    response = app.client.conversations_members(channel=channel["id"])
    members = response["members"]
    while response["response_metadata"]["next_cursor"]:
        response = app.client.conversations_members(
            channel=channel["id"], cursor=response["response_metadata"]["next_cursor"]
        )
        members += response["members"]

    return (
        channel["id"],
        channel["name"],
        channel["is_private"],
        [(channel["id"], m) for m in members],
    )


def update_channels(conn, cursor):
    logger.info("Updating channels")
    channels = app.client.conversations_list(types="public_channel,private_channel")[
        "channels"
    ]

    channel_args = []
    member_args = []
    for channel in channels:
        if channel["is_member"]:
            channel_id, channel_name, channel_is_private, members = get_channel_info(
                channel["id"]
            )

            channel_args.append((channel_name, channel_id, channel_is_private))

            member_args += members

    cursor.executemany(
        "INSERT INTO channels(name, id, is_private) VALUES(?,?,?)", channel_args
    )
    cursor.executemany("INSERT INTO members(channel, user) VALUES(?,?)", member_args)
    conn.commit()


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
        user_name = None
        channel_name = None
        sort = None
        limit = 10

        params = event["text"].lower().split()
        for p in params:
            # Handle emoji
            # usual format is " :smiley_face: "
            if len(p) > 2 and p[0] == ":" and p[-1] == ":":
                text.append(p)
                continue

            p = p.split(":")

            if len(p) == 1:
                text.append(p[0])
            if len(p) == 2:
                if p[0] == "from":
                    user_name = p[1]
                if p[0] == "in":
                    channel_name = p[1].replace("#", "").strip()
                if p[0] == "sort":
                    if p[1] in ["asc", "desc"]:
                        sort = p[1]
                    else:
                        raise ValueError("Invalid sort order %s" % p[1])
                if p[0] == "limit":
                    try:
                        limit = int(p[1])
                    except:
                        raise ValueError("%s not a valid number" % p[1])

        query = f"""
            SELECT DISTINCT
                messages.message, messages.user, messages.timestamp, messages.channel
            FROM messages
            INNER JOIN users ON messages.user = users.id
            -- Only query channel that archive bot is a part of
            INNER JOIN (
                SELECT * FROM channels
                INNER JOIN members ON
                    channels.id = members.channel AND
                    members.user = (?)
            ) as channels ON messages.channel = channels.id
            INNER JOIN members ON channels.id = members.channel
            WHERE
                -- Only return messages that are in public channels or the user is a member of
                (channels.is_private <> 1 OR members.user = (?)) AND
                messages.message LIKE (?)
        """
        query_args = [app._bot_user_id, event["user"], "%" + " ".join(text) + "%"]

        if user_name:
            query += " AND users.name = (?)"
            query_args.append(user_name)
        if channel_name:
            query += " AND channels.name = (?)"
            query_args.append(channel_name)
        if sort:
            query += " ORDER BY messages.timestamp %s" % sort

        logger.debug(query)
        logger.debug(query_args)

        cursor.execute(query, query_args)

        res = cursor.fetchmany(limit)
        res_message = None
        if res:
            logger.debug(res)
            res_message = "\n".join(
                [
                    "*<@%s>* _<!date^%s^{date_pretty} {time}|A while ago>_ _<#%s>_\n%s\n\n"
                    % (i[1], int(float(i[2])), i[3], i[0])
                    for i in res
                ]
            )
        if res_message:
            say(res_message)
        else:
            say("No results found")
    except ValueError as e:
        logger.error(traceback.format_exc())
        say(str(e))


@app.event("member_joined_channel")
def handle_join(event):
    conn, cursor = db_connect(database_path)

    # If the user added is archive bot, then add the channel too
    if event["user"] == app._bot_user_id:
        channel_id, channel_name, channel_is_private, members = get_channel_info(
            event["channel"]
        )
        cursor.execute(
            "INSERT INTO channels(name, id, is_private) VALUES(?,?,?)",
            (channel_id, channel_name, channel_is_private),
        )
        cursor.executemany("INSERT INTO members(channel, user) VALUES(?,?)", members)
    else:
        cursor.execute(
            "INSERT INTO members(channel, user) VALUES(?,?)",
            (event["channel"], event["user"]),
        )

    conn.commit()


@app.event("member_left_channel")
def handle_left(event):
    conn, cursor = db_connect(database_path)
    cursor.execute(
        "DELETE FROM members WHERE channel = ? AND user = ?",
        (event["channel"], event["user"]),
    )
    conn.commit()


def handle_rename(event):
    channel = event["channel"]
    conn, cursor = db_connect(database_path)
    cursor.execute(
        "UPDATE channels SET name = ? WHERE id = ?", (channel["name"], channel["id"])
    )
    conn.commit()


@app.event("channel_rename")
def handle_channel_rename(event):
    handle_rename(event)


@app.event("group_rename")
def handle_group_rename(event):
    handle_rename(event)


# For some reason slack fires off both *_rename and *_name events, so create handlers for them
# but don't do anything in the *_name events.
@app.event({"type": "message", "subtype": "group_name"})
def handle_group_name():
    pass


@app.event({"type": "message", "subtype": "channel_name"})
def handle_channel_name():
    pass


@app.event("user_change")
def handle_user_change(event):
    user_id = event["user"]["id"]
    new_username = event["user"]["profile"]["display_name"]

    conn, cursor = db_connect(database_path)
    cursor.execute("UPDATE users SET name = ? WHERE id = ?", (new_username, user_id))
    conn.commit()


@app.message("")
def handle_message(message, say):
    logger.debug(message)
    if "text" not in message or message["user"] == "USLACKBOT":
        return

    conn, cursor = db_connect(database_path)

    # If it's a DM, treat it as a search query
    if message["channel_type"] == "im":
        handle_query(message, cursor, say)
    elif "user" not in message:
        logger.warning("No valid user. Previous event not saved")
    else:  # Otherwise save the message to the archive.
        cursor.execute(
            "INSERT INTO messages VALUES(?, ?, ?, ?)",
            (message["text"], message["user"], message["channel"], message["ts"]),
        )
        conn.commit()

        # Ensure that the user exists in the DB
        cursor.execute("SELECT * FROM users WHERE id = ?", (message["user"],))
        row = cursor.fetchone()
        if row is None:
            update_users(conn, cursor)

    logger.debug("--------------------------")


@app.event({"type": "message", "subtype": "message_changed"})
def handle_message_changed(event):
    message = event["message"]
    conn, cursor = db_connect(database_path)
    cursor.execute(
        "UPDATE messages SET message = ? WHERE user = ? AND channel = ? AND timestamp = ?",
        (message["text"], message["user"], event["channel"], message["ts"]),
    )
    conn.commit()


def init():
    # Initialize the DB if it doesn't exist
    conn, cursor = db_connect(database_path)
    migrate_db(conn, cursor)

    # Update the users and channels in the DB and in the local memory mapping
    update_users(conn, cursor)
    update_channels(conn, cursor)


def main():
    init()

    # Start the development server
    app.start(port=port)


if __name__ == "__main__":
    main()
