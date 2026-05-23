"""
기존 JSON 파일을 SQLite로 마이그레이션합니다.
최초 1회만 실행하세요: python migrate.py
"""
import json
import os
import sqlite3
from db import DB_PATH, SCHEMA_SQL


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA_SQL)

    migrated = {"users": 0, "approved": 0, "stickers": 0}

    # chat_stats.json → users
    if os.path.exists("chat_stats.json"):
        with open("chat_stats.json", encoding="utf-8") as f:
            stats = json.load(f)
        for uid_str, v in stats.items():
            conn.execute(
                "INSERT OR IGNORE INTO users(user_id, name, chat_count) VALUES (?,?,?)",
                (int(uid_str), v["name"], v["count"]),
            )
            migrated["users"] += 1
        print(f"  users: {migrated['users']}명 이관")
    else:
        print("  chat_stats.json 없음 — 건너뜀")

    # approved_users.json → approved_users
    if os.path.exists("approved_users.json"):
        with open("approved_users.json", encoding="utf-8") as f:
            ids = json.load(f)
        for uid in ids:
            conn.execute(
                "INSERT OR IGNORE INTO users(user_id, name) VALUES (?,?)",
                (uid, str(uid)),
            )
            conn.execute(
                "INSERT OR IGNORE INTO approved_users(user_id) VALUES (?)", (uid,)
            )
            migrated["approved"] += 1
        print(f"  approved_users: {migrated['approved']}명 이관")
    else:
        print("  approved_users.json 없음 — 건너뜀")

    # sticker_tags.json → sticker_tags
    if os.path.exists("sticker_tags.json"):
        with open("sticker_tags.json", encoding="utf-8") as f:
            tags = json.load(f)
        for fuid, info in tags.items():
            uid = info["user_id"]
            name = info.get("name", str(uid))
            conn.execute(
                "INSERT OR IGNORE INTO users(user_id, name) VALUES (?,?)", (uid, name)
            )
            conn.execute(
                "INSERT OR REPLACE INTO sticker_tags(file_unique_id, user_id, name, message) "
                "VALUES (?,?,?,?)",
                (fuid, uid, name, info["message"]),
            )
            migrated["stickers"] += 1
        print(f"  sticker_tags: {migrated['stickers']}개 이관")
    else:
        print("  sticker_tags.json 없음 — 건너뜀")

    conn.commit()
    conn.close()
    print("\n마이그레이션 완료!")


if __name__ == "__main__":
    main()
