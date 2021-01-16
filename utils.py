import sqlite3

def migrate_db(conn, cursor):
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            message TEXT,
            user TEXT,
            channel TEXT,
            timestamp TEXT,
            UNIQUE(channel, timestamp) ON CONFLICT REPLACE
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            name TEXT,
            id TEXT,
            avatar TEXT,
            UNIQUE(id) ON CONFLICT REPLACE
    )''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS channels (
            name TEXT,
            id TEXT,
            is_private BOOLEAN NOT NULL CHECK (is_private IN (0,1)),
            UNIQUE(id) ON CONFLICT REPLACE
    )''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS members (
            channel TEXT,
            user TEXT,
            FOREIGN KEY (channel) REFERENCES channels(id),
            FOREIGN KEY (user) REFERENCES users(id)
        )
    ''')
    conn.commit()

    # Add `is_private` to channels for dbs that existed in v0.1
    try:
        cursor.execute('''
            ALTER TABLE channels
            ADD COLUMN is_private BOOLEAN default 1
            NOT NULL CHECK (is_private IN (0,1))
        ''')
        conn.commit()
    except:
        pass

def db_connect(database_path):
    conn = sqlite3.connect(database_path)
    cursor = conn.cursor()
    return conn, cursor
