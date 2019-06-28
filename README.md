# Slack ArchiveBot

A bot that can search your slack message history.  Makes it possible to search
further back than 10,000 messages.

## Installation

1. Clone this repo.
1. Install the requirements:

        pip install -r requirements.txt

1. [Export your team's slack history.](https://get.slack.help/hc/en-us/articles/201658943-Export-your-team-s-Slack-history)
Download the archive and export it to a directory. Then run `import_archive.py`
on the directory.  For example:

        python import_archive.py export

    This will create a file `slack.sqlite`.
1. Create a new [bot user](https://api.slack.com/bot-users) on your slack
channel and get the API key. 
1. Create an environment variable on your system called "SLACK_API_TOKEN" equal to the API key from the just mentioned slack user. Note that after setting said environment variable, you may need to restart your CLI/IDE for it to take effect.
1. Start the bot with:

        python archivebot.py


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


## Contributing

Contributions are more than welcome.  From bugs to new features. I threw this
together to meet my team's needs, but there's plenty I've overlooked.

## License

Code released under the [MIT license](LICENSE).
