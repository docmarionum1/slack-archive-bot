import os

from archivebot import init

bind = f"0.0.0.0:{os.getenv('ARCHIVE_BOT_PORT', 3333)}"
workers = os.getenv("WORKERS", 4)


def on_starting(server):
    init()
