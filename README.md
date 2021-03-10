# slack-archive-bot

A bot that can search your slack message history.  Makes it possible to search
further back than 10,000 messages.

## Requirements

1. Permission to install new apps to your Slack workspace.
2. python3
3. A publicly accessible URL to serve the bot from. (Slack recommends using [ngrok](https://ngrok.com/) to get around this.)

## Installation

1. Clone this repo.
2. Install the requirements:

        pip install -r requirements.txt

3. If you want to include your existing slack messages, [export your team's slack history.](https://get.slack.help/hc/en-us/articles/201658943-Export-your-team-s-Slack-history)
Download the archive and export it to a directory. Then run `import.py`
on the directory.  For example:

        python import.py export

    This will create a file `slack.sqlite`.
    
4. Create a new [Slack app](https://api.slack.com/start/overview).

- Add the following bot token oauth scopes and install it to your workspace:

  - `channels:history`
  - `channels:read`
  - `chat:write`
  - `groups:history` (if you want to archive/search private channels)
  - `groups:read` (if you want to archive/search private channels)
  - `im:history`
  - `users:read`

5. Start slack-archive-bot with:

        SLACK_BOT_TOKEN=<BOT_TOKEN> SLACK_SIGNING_SECRET=<SIGNING_SECRET> python archivebot.py

Where `SIGNING_SECRET` is the "Signing Secret" from your app's "Basic Information" page and `BOT_TOKEN` is the
"Bot User OAuth Access Token" from the app's "OAuth & Permissions" page.

Use `python archivebot.py -h` for a list of all command line options.

6. Go to the app's "Event Subscriptions" page and add the url to where slack-archive-bot is being served. The default port is `3333`. (i.e. `http://<ip>:3333/slack/events`)

- Then add the following bot events:

  - `channel_rename`
  - `group_rename` (if you want to archive/search private channels)
  - `member_joined_channel`
  - `member_left_channel`
  - `message.channels`
  - `message.groups` (if you want to archive/search private channels)
  - `message.im`
  - `user_change`

## Deploying Production Server Using WSGI

By default when you run `python archivebot.py` it will launch a development server. But they don't recommend using it in production. The following is an example of using
Flask and Gunicorn to deploy slack-archive-bot, but it should work equally well with any other WSGI server. 

1. `pip install flask gunicorn`
2. `SLACK_BOT_TOKEN=<BOT_TOKEN> SLACK_SIGNING_SECRET=<SIGNING_SECRET> gunicorn flask_app:flask_app -c gunicorn_conf.py <other gunicorn args>`
3. `flask_app.py` provides a thin wrapper around `archivebot.app` using `slack_bolt.adapter.flask.SlackRequestHandler`. There are many other adapters provided by bolt. To use them, simply `from archivebot import app` and wrap `app`.
4. `gunicorn_conf.py` ensures that the local database is updated when the server is started, but that it's not run for each worker.
5. You can use `ARCHIVE_BOT_LOG_LEVEL` and `ARCHIVE_BOT_DATABASE_PATH` to configure slack-archive-bot while running it via gunicorn. 

## Archiving New Messages

When running, ArchiveBot will continue to archive new messages for any channel it
is invited to.  To add the bot to your channels:

        /invite @ArchiveBot

If @ArchiveBot is the name you gave your bot user.

## Searching

To search the archive, direct message (DM) @ArchiveBot with the search query.
For example, sending the word "pizza" will return the first 10 messages that
contain the word "pizza".  There are a number of parameters that can be provided
to the query.  The full usage is:

        <query> from:<user> in:<channel> sort:asc|desc limit:<number>

        query: The text to search for.
        user: If you want to limit the search to one user, the username.
        channel: If you want to limit the search to one channel, the channel name.
        sort: Either asc if you want to search starting with the oldest messages,
            or desc if you want to start from the newest. Default asc.
        limit: The number of responses to return. Default 10.


## Migrating from slack-archive-bot v0.1

`slack-archive-bot` v0.1 used the legacy Slack API which Slack [ended support for in February 2021](https://api.slack.com/changelog/2020-01-deprecating-antecedents-to-the-conversations-api). To migrate to the new version:

- Follow the installation steps above to create a new slack app with all of the required permissions and event subscriptions.
- The biggest change in requirements with the new version is the move from the [Real Time Messaging API](https://api.slack.com/rtm) to the [Events API](https://api.slack.com/apis/connections/events-api) which necessitates having a publicly-accessible url that Slack can send events to. If you are unable to serve a public endpoint, you can use [ngrok](https://ngrok.com/).

## Contributing

Contributions are more than welcome.  From bugs to new features. I threw this
together to meet my team's needs, but there's plenty I've overlooked.

## License

Code released under the [MIT license](LICENSE).
