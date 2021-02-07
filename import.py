import argparse
import glob
import json
import logging
import os

from utils import db_connect, migrate_db


parser = argparse.ArgumentParser()
parser.add_argument("directory", help=("path to the downloaded Slack archive"))
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
args = parser.parse_args()

log_level = args.log_level.upper()
assert log_level in ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]
logging.basicConfig(level=getattr(logging, log_level))
logger = logging.getLogger(__name__)

conn, cursor = db_connect(args.database_path)
migrate_db(conn, cursor)

directory = args.directory

logger.info("Importing channels..")
with open(os.path.join(directory, "channels.json")) as f:
    channels = json.load(f)
args = [(c["name"], c["id"], 1) for c in channels]
cursor.executemany("INSERT INTO channels VALUES(?,?,?)", (args))
logger.info("- Channels imported")

logger.info("Importing users..")
with open(os.path.join(directory, "users.json")) as f:
    users = json.load(f)
args = [(u["name"], u["id"], u["profile"]["image_72"]) for u in users]
cursor.executemany("INSERT INTO users VALUES(?,?,?)", (args))
logger.info("- Users imported")

logger.info("Importing messages..")
for channel in channels:
    files = glob.glob(os.path.join(directory, channel["name"], "*.json"))
    if not files:
        logger.warning("No messages found for #%s" % channel["name"])
    for file_name in files:
        with open(file_name, encoding="utf8") as f:
            messages = json.load(f)

        args = []
        for message in messages:
            if "id" in channel and "ts" in message:
                args.append(
                    (
                        message["text"]
                        if "text" in message
                        else "~~There is a message ommitted here~~",
                        message["user"] if "user" in message else "",
                        channel["id"],
                        message["ts"],
                    )
                )
            else:
                logger.warning(
                    "In "
                    + file_name
                    + ": An exception occured, message not added to archive."
                )

        cursor.executemany("INSERT INTO messages VALUES(?, ?, ?, ?)", args)
        conn.commit()
logger.info("- Messages imported")
logger.info("Done")
