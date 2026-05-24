import aiosqlite
import os
from datetime import datetime, timezone, timedelta

DB_PATH = os.getenv("DB_PATH", "bot.db")
KST = timezone(timedelta(hours=9))


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def today_ymd() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db():
    async with await get_db() as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id    INTEGER PRIMARY KEY,
                username   TEXT,
                total_chat INTEGER DEFAULT 0,
                points     INTEGER DEFAULT 0,
                joined_at  TEXT,
                last_seen  TEXT
            );
            CREATE TABLE IF NOT EXISTS daily (
                user_id    INTEGER,
                ymd        TEXT,
                chat_count INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, ymd)
            );
            CREATE TABLE IF NOT EXISTS config (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS admins (
                user_id  INTEGER PRIMARY KEY,
                username TEXT,
                added_at TEXT
            );
            CREATE TABLE IF NOT EXISTS log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER,
                delta      INTEGER,
                reason     TEXT,
                memo       TEXT,
                created_at TEXT
            );
        """)
        defaults = {
            "settle_enabled": "true",
            "settle_rewards": "[100,90,80,70,60,50,40,30,20,10]",
            "surprise_enabled": "true",
            "surprise_points": "50",
            "surprise_chance": "0.001",
            "surprise_expire_sec": "5",
            "chat_min_len": "3",
            "chat_cooldown_sec": "1",
            "msg_autodelete_sec": "5",
        }
        for k, v in defaults.items():
            await db.execute(
                "INSERT OR IGNORE INTO config(key,value) VALUES(?,?)", (k, v)
            )
        await db.commit()


# ── users ──────────────────────────────────────────────────────────────────

async def upsert_user(user_id: int, username: str | None):
    async with await get_db() as db:
        existing = await db.execute(
            "SELECT user_id FROM users WHERE user_id=?", (user_id,)
        )
        row = await existing.fetchone()
        now = now_kst()
        if row is None:
            await db.execute(
                "INSERT INTO users(user_id,username,joined_at,last_seen) VALUES(?,?,?,?)",
                (user_id, username, now, now),
            )
        else:
            await db.execute(
                "UPDATE users SET username=?, last_seen=? WHERE user_id=?",
                (username, now, user_id),
            )
        await db.commit()


async def get_user(user_id: int) -> aiosqlite.Row | None:
    async with await get_db() as db:
        cur = await db.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        return await cur.fetchone()


async def get_daily_count(user_id: int, ymd: str | None = None) -> int:
    ymd = ymd or today_ymd()
    async with await get_db() as db:
        cur = await db.execute(
            "SELECT chat_count FROM daily WHERE user_id=? AND ymd=?", (user_id, ymd)
        )
        row = await cur.fetchone()
        return row["chat_count"] if row else 0


async def increment_chat(user_id: int, username: str | None):
    ymd = today_ymd()
    now = now_kst()
    async with await get_db() as db:
        await db.execute(
            "INSERT OR IGNORE INTO users(user_id,username,joined_at,last_seen) VALUES(?,?,?,?)",
            (user_id, username, now, now),
        )
        await db.execute(
            "UPDATE users SET total_chat=total_chat+1, last_seen=?, username=COALESCE(?,username) WHERE user_id=?",
            (now, username, user_id),
        )
        await db.execute(
            "INSERT INTO daily(user_id,ymd,chat_count) VALUES(?,?,1) "
            "ON CONFLICT(user_id,ymd) DO UPDATE SET chat_count=chat_count+1",
            (user_id, ymd),
        )
        await db.commit()


async def add_points(user_id: int, delta: int, reason: str, memo: str = ""):
    async with await get_db() as db:
        await db.execute(
            "UPDATE users SET points=points+? WHERE user_id=?", (delta, user_id)
        )
        await db.execute(
            "INSERT INTO log(user_id,delta,reason,memo,created_at) VALUES(?,?,?,?,?)",
            (user_id, delta, reason, memo, now_kst()),
        )
        await db.commit()


async def set_points(user_id: int, new_points: int, memo: str = ""):
    async with await get_db() as db:
        cur = await db.execute("SELECT points FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        old = row["points"] if row else 0
        delta = new_points - old
        await db.execute(
            "UPDATE users SET points=? WHERE user_id=?", (new_points, user_id)
        )
        await db.execute(
            "INSERT INTO log(user_id,delta,reason,memo,created_at) VALUES(?,?,?,?,?)",
            (user_id, delta, "admin_edit", memo, now_kst()),
        )
        await db.commit()


# ── ranking ────────────────────────────────────────────────────────────────

async def get_daily_rank(ymd: str | None = None, limit: int = 50):
    ymd = ymd or today_ymd()
    async with await get_db() as db:
        cur = await db.execute(
            """
            SELECT d.user_id, u.username, d.chat_count
            FROM daily d JOIN users u ON d.user_id=u.user_id
            WHERE d.ymd=? AND d.chat_count>0
            ORDER BY d.chat_count DESC, d.user_id ASC
            LIMIT ?
            """,
            (ymd, limit),
        )
        return await cur.fetchall()


async def get_total_rank(limit: int = 50):
    async with await get_db() as db:
        cur = await db.execute(
            """
            SELECT user_id, username, total_chat, points
            FROM users WHERE total_chat>0
            ORDER BY total_chat DESC, user_id ASC
            LIMIT ?
            """,
            (limit,),
        )
        return await cur.fetchall()


# ── config ─────────────────────────────────────────────────────────────────

async def get_config_raw() -> dict:
    async with await get_db() as db:
        cur = await db.execute("SELECT key, value FROM config")
        rows = await cur.fetchall()
        return {r["key"]: r["value"] for r in rows}


async def set_config(key: str, value: str):
    async with await get_db() as db:
        await db.execute(
            "INSERT INTO config(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        await db.commit()


# ── admins ─────────────────────────────────────────────────────────────────

async def is_admin(user_id: int) -> bool:
    async with await get_db() as db:
        cur = await db.execute(
            "SELECT user_id FROM admins WHERE user_id=?", (user_id,)
        )
        return await cur.fetchone() is not None


async def add_admin(user_id: int, username: str | None):
    async with await get_db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO admins(user_id,username,added_at) VALUES(?,?,?)",
            (user_id, username, now_kst()),
        )
        await db.commit()


async def remove_admin(user_id: int):
    async with await get_db() as db:
        await db.execute("DELETE FROM admins WHERE user_id=?", (user_id,))
        await db.commit()


async def list_admins():
    async with await get_db() as db:
        cur = await db.execute("SELECT * FROM admins ORDER BY added_at")
        return await cur.fetchall()


# ── log ────────────────────────────────────────────────────────────────────

async def get_logs(reason: str | None = None, limit: int = 100, offset: int = 0):
    async with await get_db() as db:
        if reason:
            cur = await db.execute(
                "SELECT l.*, u.username FROM log l LEFT JOIN users u ON l.user_id=u.user_id "
                "WHERE l.reason=? ORDER BY l.id DESC LIMIT ? OFFSET ?",
                (reason, limit, offset),
            )
        else:
            cur = await db.execute(
                "SELECT l.*, u.username FROM log l LEFT JOIN users u ON l.user_id=u.user_id "
                "ORDER BY l.id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        return await cur.fetchall()


# ── dashboard stats ────────────────────────────────────────────────────────

async def get_stats() -> dict:
    async with await get_db() as db:
        ymd = today_ymd()
        total_users = (await (await db.execute("SELECT COUNT(*) FROM users")).fetchone())[0]
        total_points = (await (await db.execute("SELECT COALESCE(SUM(points),0) FROM users")).fetchone())[0]
        today_chatters = (
            await (
                await db.execute(
                    "SELECT COUNT(*) FROM daily WHERE ymd=? AND chat_count>0", (ymd,)
                )
            ).fetchone()
        )[0]
        surprise_count = (
            await (
                await db.execute(
                    "SELECT COUNT(*) FROM log WHERE reason='surprise' AND created_at LIKE ?",
                    (ymd + "%",),
                )
            ).fetchone()
        )[0]
        return {
            "total_users": total_users,
            "total_points": total_points,
            "today_chatters": today_chatters,
            "surprise_count": surprise_count,
        }


async def list_users(search: str = "", limit: int = 50, offset: int = 0):
    async with await get_db() as db:
        ymd = today_ymd()
        q = f"%{search}%"
        cur = await db.execute(
            """
            SELECT u.user_id, u.username, u.total_chat, u.points,
                   COALESCE(d.chat_count,0) AS daily_chat
            FROM users u
            LEFT JOIN daily d ON d.user_id=u.user_id AND d.ymd=?
            WHERE u.username LIKE ? OR CAST(u.user_id AS TEXT) LIKE ?
            ORDER BY u.total_chat DESC
            LIMIT ? OFFSET ?
            """,
            (ymd, q, q, limit, offset),
        )
        return await cur.fetchall()
