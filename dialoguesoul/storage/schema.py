SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS messages (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      platform TEXT NOT NULL,
      self_id TEXT NOT NULL,
      chat_type TEXT NOT NULL,
      chat_id TEXT NOT NULL,
      message_id TEXT,
      sender_id TEXT,
      sender_name TEXT,
      timestamp REAL NOT NULL,
      components TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_messages_chat_time
      ON messages(platform, self_id, chat_type, chat_id, timestamp)
    """,
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
]
