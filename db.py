import sqlite3
import aiosqlite

DB_PATH = "haewon.db"

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    user_id    INTEGER PRIMARY KEY,
    name       TEXT    NOT NULL,
    chat_count INTEGER NOT NULL DEFAULT 0,
    points     INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS approved_users (
    user_id INTEGER PRIMARY KEY REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS sticker_tags (
    file_unique_id TEXT    PRIMARY KEY,
    user_id        INTEGER NOT NULL REFERENCES users(user_id),
    name           TEXT    NOT NULL DEFAULT '',
    message        TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_chat (
    user_id INTEGER NOT NULL,
    date    TEXT    NOT NULL,
    count   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, date)
);

CREATE TABLE IF NOT EXISTS attendance (
    user_id      INTEGER NOT NULL,
    date         TEXT    NOT NULL,
    streak       INTEGER NOT NULL DEFAULT 1,
    points_given INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, date)
);

CREATE TABLE IF NOT EXISTS points_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(user_id),
    delta      INTEGER NOT NULL,
    reason     TEXT    NOT NULL,
    created_at TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS shop_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    price       INTEGER NOT NULL,
    stock       INTEGER NOT NULL DEFAULT -1,
    is_active   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS purchases (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(user_id),
    item_id    INTEGER NOT NULL REFERENCES shop_items(id),
    price_paid INTEGER NOT NULL,
    created_at TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT OR IGNORE INTO config VALUES ('surprise_enabled',        '0');
INSERT OR IGNORE INTO config VALUES ('surprise_min_seconds',    '1800');
INSERT OR IGNORE INTO config VALUES ('surprise_max_seconds',    '7200');
INSERT OR IGNORE INTO config VALUES ('surprise_points',         '50');
INSERT OR IGNORE INTO config VALUES ('last_group_chat_id',      '');
INSERT OR IGNORE INTO config VALUES ('daily_rank_1',            '100');
INSERT OR IGNORE INTO config VALUES ('daily_rank_2',            '70');
INSERT OR IGNORE INTO config VALUES ('daily_rank_3',            '50');
INSERT OR IGNORE INTO config VALUES ('daily_rank_4_10',         '30');
INSERT OR IGNORE INTO config VALUES ('daily_rank_11_plus',      '10');
INSERT OR IGNORE INTO config VALUES ('attendance_base_pts',     '20');
INSERT OR IGNORE INTO config VALUES ('attendance_streak_bonus', '5');
"""


def init_db_sync() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA_SQL)
    conn.close()


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA_SQL)
        await db.commit()


async def get_config(db: aiosqlite.Connection, key: str) -> str:
    async with db.execute("SELECT value FROM config WHERE key=?", (key,)) as cur:
        row = await cur.fetchone()
    return row[0] if row else ""


async def set_config(db: aiosqlite.Connection, key: str, value: str) -> None:
    await db.execute("INSERT OR REPLACE INTO config(key,value) VALUES (?,?)", (key, value))
    await db.commit()
