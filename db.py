import aiosqlite
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta

DB_PATH = os.getenv("DB_PATH", "bot.db")
KST = timezone(timedelta(hours=9))


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def today_ymd() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


@asynccontextmanager
async def get_db():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
        yield db


async def init_db():
    async with get_db() as db:
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
                checked_in INTEGER DEFAULT 0,
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
        # 기존 DB에 checked_in 컬럼이 없을 수 있으므로 마이그레이션
        try:
            await db.execute("ALTER TABLE daily ADD COLUMN checked_in INTEGER DEFAULT 0")
            await db.commit()
        except Exception:
            pass  # 이미 존재하면 무시

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
            "checkin_enabled": "true",
            "checkin_points": "30",
        }
        for k, v in defaults.items():
            await db.execute(
                "INSERT OR IGNORE INTO config(key,value) VALUES(?,?)", (k, v)
            )
        await db.commit()
    await baccarat_init_tables()


# ── users ──────────────────────────────────────────────────────────────────

async def upsert_user(user_id: int, username: str | None):
    async with get_db() as db:
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
    async with get_db() as db:
        cur = await db.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        return await cur.fetchone()


async def get_user_by_username(username: str) -> aiosqlite.Row | None:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM users WHERE LOWER(username)=LOWER(?)", (username,)
        )
        return await cur.fetchone()


async def get_daily_count(user_id: int, ymd: str | None = None) -> int:
    ymd = ymd or today_ymd()
    async with get_db() as db:
        cur = await db.execute(
            "SELECT chat_count FROM daily WHERE user_id=? AND ymd=?", (user_id, ymd)
        )
        row = await cur.fetchone()
        return row["chat_count"] if row else 0


async def check_in(user_id: int, username: str | None) -> bool:
    """출석 시도. 이미 했으면 False, 성공 시 True."""
    ymd = today_ymd()
    now = now_kst()
    async with get_db() as db:
        await db.execute(
            "INSERT OR IGNORE INTO users(user_id,username,joined_at,last_seen) VALUES(?,?,?,?)",
            (user_id, username, now, now),
        )
        cur = await db.execute(
            "SELECT checked_in FROM daily WHERE user_id=? AND ymd=?", (user_id, ymd)
        )
        row = await cur.fetchone()
        if row and row["checked_in"]:
            return False
        await db.execute(
            "INSERT INTO daily(user_id,ymd,chat_count,checked_in) VALUES(?,?,0,1) "
            "ON CONFLICT(user_id,ymd) DO UPDATE SET checked_in=1",
            (user_id, ymd),
        )
        await db.commit()
        return True


async def increment_chat(user_id: int, username: str | None):
    ymd = today_ymd()
    now = now_kst()
    async with get_db() as db:
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
    async with get_db() as db:
        await db.execute(
            "UPDATE users SET points=points+? WHERE user_id=?", (delta, user_id)
        )
        await db.execute(
            "INSERT INTO log(user_id,delta,reason,memo,created_at) VALUES(?,?,?,?,?)",
            (user_id, delta, reason, memo, now_kst()),
        )
        await db.commit()


async def set_points(user_id: int, new_points: int, memo: str = ""):
    async with get_db() as db:
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


async def set_user_stats(user_id: int, total_chat: int, daily_chat: int, points: int):
    ymd = today_ymd()
    async with get_db() as db:
        cur = await db.execute("SELECT points FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        old_pts = row["points"] if row else 0
        delta = points - old_pts
        await db.execute(
            "UPDATE users SET total_chat=?, points=? WHERE user_id=?",
            (total_chat, points, user_id),
        )
        await db.execute(
            "INSERT INTO daily(user_id,ymd,chat_count) VALUES(?,?,?) "
            "ON CONFLICT(user_id,ymd) DO UPDATE SET chat_count=?",
            (user_id, ymd, daily_chat, daily_chat),
        )
        if delta != 0:
            await db.execute(
                "INSERT INTO log(user_id,delta,reason,memo,created_at) VALUES(?,?,?,?,?)",
                (user_id, delta, "admin_edit", "웹 관리자 수정", now_kst()),
            )
        await db.commit()


# ── ranking ────────────────────────────────────────────────────────────────

async def get_daily_rank(ymd: str | None = None, limit: int = 50):
    ymd = ymd or today_ymd()
    async with get_db() as db:
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
    async with get_db() as db:
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
    async with get_db() as db:
        cur = await db.execute("SELECT key, value FROM config")
        rows = await cur.fetchall()
        return {r["key"]: r["value"] for r in rows}


async def set_config(key: str, value: str):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO config(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        await db.commit()


# ── admins ─────────────────────────────────────────────────────────────────

async def is_admin(user_id: int) -> bool:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT user_id FROM admins WHERE user_id=?", (user_id,)
        )
        return await cur.fetchone() is not None


async def add_admin(user_id: int, username: str | None):
    async with get_db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO admins(user_id,username,added_at) VALUES(?,?,?)",
            (user_id, username, now_kst()),
        )
        await db.commit()


async def remove_admin(user_id: int):
    async with get_db() as db:
        await db.execute("DELETE FROM admins WHERE user_id=?", (user_id,))
        await db.commit()


async def list_admins():
    async with get_db() as db:
        cur = await db.execute("SELECT * FROM admins ORDER BY added_at")
        return await cur.fetchall()


# ── log ────────────────────────────────────────────────────────────────────

async def get_logs(reason: str | None = None, limit: int = 100, offset: int = 0):
    async with get_db() as db:
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
    async with get_db() as db:
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


# ── baccarat ───────────────────────────────────────────────────────────────

async def baccarat_init_tables():
    async with get_db() as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS baccarat_rounds (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                status      TEXT NOT NULL DEFAULT 'betting',
                player_dice TEXT DEFAULT NULL,
                banker_dice TEXT DEFAULT NULL,
                result      TEXT DEFAULT NULL,
                created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                done_at     TEXT DEFAULT NULL
            );
            CREATE TABLE IF NOT EXISTS baccarat_bets (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                round_id   INTEGER NOT NULL REFERENCES baccarat_rounds(id),
                user_id    INTEGER NOT NULL REFERENCES users(user_id),
                side       TEXT NOT NULL,
                amount     INTEGER NOT NULL,
                payout     INTEGER DEFAULT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                UNIQUE(round_id, user_id)
            );
        """)
        bac_defaults = {
            "baccarat_min_bet": "100",
            "baccarat_max_bet": "0",
            "baccarat_pin_msg_id": "",
        }
        for k, v in bac_defaults.items():
            await db.execute(
                "INSERT OR IGNORE INTO config(key,value) VALUES(?,?)", (k, v)
            )
        await db.commit()


async def baccarat_cleanup_stale():
    """봇 재시작 시 미완료 회차 환불 처리."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT id FROM baccarat_rounds WHERE status IN ('betting','closed','rolling')"
        )
        stale = await cur.fetchall()
        for row in stale:
            rid = row["id"]
            bets = await (await db.execute(
                "SELECT user_id, amount FROM baccarat_bets WHERE round_id=? AND payout IS NULL", (rid,)
            )).fetchall()
            for bet in bets:
                await db.execute(
                    "UPDATE users SET points=points+? WHERE user_id=?",
                    (bet["amount"], bet["user_id"]),
                )
                await db.execute(
                    "INSERT INTO log(user_id,delta,reason,memo,created_at) VALUES(?,?,?,?,?)",
                    (bet["user_id"], bet["amount"], "baccarat_refund", f"stale round#{rid}", now_kst()),
                )
            await db.execute(
                "UPDATE baccarat_rounds SET status='done', done_at=? WHERE id=?",
                (now_kst(), rid),
            )
        await db.commit()
        return len(stale)


async def baccarat_open_round() -> int:
    async with get_db() as db:
        cur = await db.execute(
            "INSERT INTO baccarat_rounds(status,created_at) VALUES('betting',?) RETURNING id",
            (now_kst(),),
        )
        row = await cur.fetchone()
        await db.commit()
        return row["id"]


async def baccarat_get_round(round_id: int):
    async with get_db() as db:
        cur = await db.execute("SELECT * FROM baccarat_rounds WHERE id=?", (round_id,))
        return await cur.fetchone()


async def baccarat_get_active_round():
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM baccarat_rounds WHERE status='betting' ORDER BY id DESC LIMIT 1"
        )
        return await cur.fetchone()


async def baccarat_close_betting(round_id: int):
    async with get_db() as db:
        await db.execute(
            "UPDATE baccarat_rounds SET status='closed' WHERE id=?", (round_id,)
        )
        await db.commit()


async def baccarat_set_rolling(round_id: int):
    async with get_db() as db:
        await db.execute(
            "UPDATE baccarat_rounds SET status='rolling' WHERE id=?", (round_id,)
        )
        await db.commit()


async def baccarat_finish_round(round_id: int, player_dice, banker_dice, result):
    import json as _json
    p = _json.dumps(player_dice) if player_dice else None
    b = _json.dumps(banker_dice) if banker_dice else None
    async with get_db() as db:
        await db.execute(
            "UPDATE baccarat_rounds SET status='done', player_dice=?, banker_dice=?, result=?, done_at=? WHERE id=?",
            (p, b, result, now_kst(), round_id),
        )
        await db.commit()


async def baccarat_place_bet(round_id: int, user_id: int, side: str, amount: int) -> bool:
    """성공 시 True, 이미 베팅했으면 False."""
    try:
        async with get_db() as db:
            await db.execute(
                "INSERT INTO baccarat_bets(round_id,user_id,side,amount,created_at) VALUES(?,?,?,?,?)",
                (round_id, user_id, side, amount, now_kst()),
            )
            await db.commit()
        return True
    except Exception:
        return False


async def baccarat_get_user_bet(round_id: int, user_id: int):
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM baccarat_bets WHERE round_id=? AND user_id=?",
            (round_id, user_id),
        )
        return await cur.fetchone()


async def baccarat_get_bets(round_id: int):
    async with get_db() as db:
        cur = await db.execute(
            "SELECT b.*, u.username FROM baccarat_bets b JOIN users u ON b.user_id=u.user_id WHERE b.round_id=?",
            (round_id,),
        )
        return await cur.fetchall()


async def baccarat_get_totals(round_id: int) -> dict:
    """Returns {side: (total_amount, bettor_count)}"""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT side, SUM(amount) as total, COUNT(*) as cnt FROM baccarat_bets WHERE round_id=? GROUP BY side",
            (round_id,),
        )
        rows = await cur.fetchall()
    result = {"player": (0, 0), "banker": (0, 0), "tie": (0, 0)}
    for r in rows:
        result[r["side"]] = (r["total"], r["cnt"])
    return result


async def baccarat_settle(round_id: int, result: str, payouts: dict):
    """payouts: {user_id: payout_amount}"""
    async with get_db() as db:
        for uid, payout in payouts.items():
            await db.execute(
                "UPDATE baccarat_bets SET payout=? WHERE round_id=? AND user_id=?",
                (payout, round_id, uid),
            )
            if payout > 0:
                await db.execute(
                    "UPDATE users SET points=points+? WHERE user_id=?", (payout, uid)
                )
                await db.execute(
                    "INSERT INTO log(user_id,delta,reason,memo,created_at) VALUES(?,?,?,?,?)",
                    (uid, payout, "baccarat_win", f"round#{round_id}", now_kst()),
                )
        await db.commit()


async def baccarat_get_history(limit: int = 100):
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM baccarat_rounds WHERE status='done' AND result IS NOT NULL ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = await cur.fetchall()
        return list(reversed(rows))


async def baccarat_get_recent_rounds(limit: int = 20):
    async with get_db() as db:
        cur = await db.execute(
            """SELECT r.id, r.result, r.done_at,
                      COALESCE(SUM(b.amount),0) as total_bet,
                      COUNT(b.id) as bet_count
               FROM baccarat_rounds r
               LEFT JOIN baccarat_bets b ON b.round_id=r.id
               WHERE r.status='done'
               GROUP BY r.id ORDER BY r.id DESC LIMIT ?""",
            (limit,),
        )
        return await cur.fetchall()


async def list_users(search: str = "", limit: int = 50, offset: int = 0):
    async with get_db() as db:
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
