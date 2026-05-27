"""
어제 상위 30명에게 채팅 횟수만큼 당근 추가 지급
사용법: python3 give_chat_bonus.py
날짜 지정: python3 give_chat_bonus.py 2026-05-26
"""
import asyncio
import sys
import aiosqlite
from datetime import datetime, timezone, timedelta
import os
from dotenv import load_dotenv

load_dotenv()
DB_PATH = os.getenv("DB_PATH", "bot.db")
KST = timezone(timedelta(hours=9))


async def main():
    if len(sys.argv) >= 2:
        ymd = sys.argv[1]
    else:
        ymd = (datetime.now(KST) - timedelta(days=1)).strftime("%Y-%m-%d")

    print(f"대상 날짜: {ymd}\n")

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")

        cur = await db.execute("""
            SELECT d.user_id, u.username, d.chat_count
            FROM daily d JOIN users u ON d.user_id = u.user_id
            WHERE d.ymd = ? AND d.chat_count > 0
            ORDER BY d.chat_count DESC
            LIMIT 30
        """, (ymd,))
        rows = await cur.fetchall()

        if not rows:
            print("해당 날짜 채팅 기록이 없어요.")
            return

        now = datetime.now(KST).isoformat(timespec="seconds")
        total = 0
        for rank, row in enumerate(rows, 1):
            pts = row["chat_count"]
            name = f"@{row['username']}" if row["username"] else str(row["user_id"])
            await db.execute(
                "UPDATE users SET points = points + ? WHERE user_id = ?",
                (pts, row["user_id"]),
            )
            await db.execute(
                "INSERT INTO log(user_id, delta, reason, memo, created_at) VALUES (?,?,?,?,?)",
                (row["user_id"], pts, "admin_edit", f"채팅수 추가지급 ({ymd} {rank}등)", now),
            )
            print(f"{rank:>3}. {name:<30} {row['chat_count']:>6,}회 → 🥕+{pts:,}")
            total += pts

        await db.commit()
        print(f"\n✅ {len(rows)}명 / 총 🥕{total:,} 지급 완료")


asyncio.run(main())
