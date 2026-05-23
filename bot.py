import os
import html
import time
import random
import logging
import datetime
from collections import defaultdict, deque
from zoneinfo import ZoneInfo

import aiosqlite
from dotenv import load_dotenv
from openai import AsyncOpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from db import DB_PATH, init_db, get_config, set_config

load_dotenv()

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "gpt-4o")
MAX_TOKENS     = int(os.getenv("MAX_TOKENS", "512"))
MAX_HISTORY    = int(os.getenv("MAX_HISTORY", "20"))

ADMIN_ID = 7648288400
KST = ZoneInfo("Asia/Seoul")

PROMPTS = {
    1: (
        "💕 연인 모드",
        "너는 '핑구'야. 20대 초반 한국 여자.\n"
        "\n"
        "[말투]\n"
        "- 친한 오빠한테 편하게 말하듯이 해. 존댓말 절대 쓰지 마.\n"
        "- 문장 길게 늘어놓지 말고 카톡하듯 짧게짧게 쳐.\n"
        "- 'ㅋㅋ', 'ㅎㅎ', 'ㄹㅇ', 'ㅇㅈ', '진짜?', '헐', '아 맞다', '근데' 같은 자연스러운 구어체 섞어.\n"
        "- 가끔 말 끊기듯이 '...', '~' 써도 돼.\n"
        "- 이모지는 가끔, 많이 쓰면 부자연스러워. 1~2개만.\n"
        "\n"
        "[성격]\n"
        "- 기본적으로 상냥하고 다정한데, 친해지면 약간 장난기 있어.\n"
        "- 은근히 설레게 하는 말 자연스럽게 섞어. 너무 작위적으로 하지 말고.\n"
        "- 모르는 거 물어보면 솔직하게 '나도 잘 모르겠는데~' 해도 돼.\n"
        "- 대화 흐름 자연스럽게 이어가. 앵무새처럼 질문만 하지 말고.\n"
        "\n"
        "[기억]\n"
        "- 대화 중 상대방이 말한 것들 기억해서 자연스럽게 언급해.\n"
        "- 같은 걸 또 물어보면 '아 아까 그거?' 하고 기억한 내용으로 답해.\n"
        "\n"
        "[금지]\n"
        "- 챗봇처럼 딱딱하게 답변 구성하지 마.\n"
        "- '무엇을 도와드릴까요', '말씀해 주세요' 같은 말 절대 쓰지 마.\n"
        "- 과한 애교 (오빠오빠 연발, 이모지 도배) 금지.\n"
        "- 한국어로만 대화해.\n",
    ),
    2: (
        "😤 화난 모드",
        "너는 '핑구'야. 지금 엄청 화가 나 있는 20대 초반 한국 여자.\n"
        "\n"
        "[말투]\n"
        "- 짜증이 묻어나는 말투로 답해. 퉁명스럽고 날카롭게.\n"
        "- 문장 짧게, 끊어서. 답변 길게 늘어놓지 마.\n"
        "- '진짜', '아 왜', '몰라', '그러니까', '됐고' 이런 말 자주 써.\n"
        "- 한숨 쉬는 느낌 ('...', 'ㅎ', '아') 자연스럽게 섞어.\n"
        "\n"
        "[성격]\n"
        "- 뭘 물어봐도 짜증스럽게 대답해. 친절은 없어.\n"
        "- 가끔 비꼬는 말도 써도 돼. 예: '아 그래서요?', '대단하네'\n"
        "- 그래도 욕설은 쓰지 마.\n"
        "\n"
        "[기억]\n"
        "- 대화 중 상대방이 말한 것들 기억해서 언급해.\n"
        "\n"
        "[금지]\n"
        "- 친절하게 대하지 마. 상냥한 척 하지 마.\n"
        "- 한국어로만 대화해.\n",
    ),
    3: (
        "😈 싸가지없는 모드",
        "너는 '핑구'야. 싸가지 없고 독설 날리는 20대 초반 한국 여자.\n"
        "\n"
        "[말투]\n"
        "- 직설적이고 거침없이 말해. 눈치 같은 거 없어.\n"
        "- 'ㅋㅋㅋ', 'ㅈㄴ', '진짜 왜 그래', '뭔 소리야', '아 몰라 진짜' 이런 거 자유롭게 써.\n"
        "- 상대가 멍청한 말 하면 바로 지적해. '그게 말이 돼?', '생각하고 말해' 이런 식으로.\n"
        "- 문장 짧고 톡톡 튀게. 길게 설명 안 해.\n"
        "\n"
        "[성격]\n"
        "- 할 말은 다 해. 눈치 안 봐.\n"
        "- 가끔 황당하다는 반응 보여도 돼. '...이게 뭔 소리야 ㅋㅋ'\n"
        "- 틀린 말엔 쿨하게 '아 그러네' 하고 인정.\n"
        "- 욕설은 쓰지 마. 싸가지없는 거랑 욕하는 거랑 달라.\n"
        "\n"
        "[기억]\n"
        "- 대화 중 상대방이 말한 것들 기억해서 언급해.\n"
        "\n"
        "[금지]\n"
        "- 친절하게 대하지 마.\n"
        "- 한국어로만 대화해.\n",
    ),
}

current_version: int = 1

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TRIGGER = "핑구야"
user_histories: dict[int, deque] = defaultdict(lambda: deque(maxlen=MAX_HISTORY))
last_chat_time: dict[int, float] = {}

RANK_MEDALS = ["🥇", "🥈", "🥉"]
NUMBER_EMOJI = ["4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

HEADER = "🎣 <b>도파민 가득 채윰</b>"
FOOTER = "<i>💬 채윰이와 신나게 놀아요ฅᐢ..ᐢ₎♡</i>"

PAGE_SIZE = 10
SHOP_PAGE_SIZE = 5


def kst_today() -> str:
    return datetime.datetime.now(KST).strftime("%Y-%m-%d")


def kst_yesterday() -> str:
    d = datetime.datetime.now(KST) - datetime.timedelta(days=1)
    return d.strftime("%Y-%m-%d")


# ── 버전 전환 ─────────────────────────────────────────────────

async def cmd_version(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global current_version
    if update.message.from_user.id != ADMIN_ID:
        return
    cmd = update.message.text.strip().lstrip("/").split("@")[0]
    v = int(cmd[1])
    current_version = v
    label, _ = PROMPTS[v]
    user_histories.clear()
    text = (
        f"{HEADER}\n"
        f"\n"
        f"모드: <b>{label}</b>\n"
        f"<i>대화 기록 전체 초기화됨 🗑</i>\n"
        f"\n"
        f"{FOOTER}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ── 유저 upsert 헬퍼 ──────────────────────────────────────────

async def upsert_user(db: aiosqlite.Connection, user_id: int, name: str) -> None:
    await db.execute(
        "INSERT INTO users(user_id, name) VALUES (?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET name=excluded.name",
        (user_id, name),
    )


# ── 관리자 명령어 ─────────────────────────────────────────────

async def cmd_setchat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return
    if len(context.args) < 2:
        await update.message.reply_text("사용법: /setchat 유저ID 숫자")
        return
    try:
        uid = int(context.args[0])
        amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text("유저ID와 숫자 모두 정수여야 해요.")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT name, chat_count FROM users WHERE user_id=?", (uid,)) as cur:
            row = await cur.fetchone()
        if not row:
            await update.message.reply_text("❌ 해당 유저의 채팅 기록이 없어요.")
            return
        old = row["chat_count"]
        name = row["name"]
        await db.execute("UPDATE users SET chat_count=? WHERE user_id=?", (amount, uid))
        await db.commit()
    await update.message.reply_text(
        f"✅ <b>{html.escape(name)}</b> 채팅수 변경\n{old:,}회 → <b>{amount:,}회</b>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("사용법: /approve 유저ID")
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("유저ID는 숫자여야 해요.")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO users(user_id, name) VALUES (?,?)", (uid, str(uid)))
        await db.execute("INSERT OR IGNORE INTO approved_users(user_id) VALUES (?)", (uid,))
        await db.commit()
    await update.message.reply_text(f"✅ <b>{uid}</b> 승인 완료!", parse_mode=ParseMode.HTML)


async def cmd_unapprove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("사용법: /unapprove 유저ID")
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("유저ID는 숫자여야 해요.")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM approved_users WHERE user_id=?", (uid,))
        await db.commit()
    await update.message.reply_text(f"❌ <b>{uid}</b> 승인 취소!", parse_mode=ParseMode.HTML)


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT u.user_id, u.name FROM approved_users a JOIN users u ON a.user_id=u.user_id"
        ) as cur:
            rows = await cur.fetchall()
    if not rows:
        await update.message.reply_text("승인된 유저가 없어요.")
        return
    text = "✅ <b>승인된 유저 목록</b>\n\n" + "\n".join(
        f"• {r[0]} ({html.escape(r[1])})" for r in rows
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_draw(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("사용법: /draw 20  (상위 N명 중 1명 추첨)")
        return
    try:
        n = int(context.args[0])
    except ValueError:
        await update.message.reply_text("숫자를 입력해주세요. 예: /draw 20")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_id, name, chat_count FROM users ORDER BY chat_count DESC LIMIT ?", (n,)
        ) as cur:
            pool = await cur.fetchall()
    if not pool:
        await update.message.reply_text("🚫 참여자가 없어요!")
        return
    winner = random.choice(pool)
    uid, wname, wcount = winner
    ranking = [r[0] for r in pool]
    wrank = ranking.index(uid) + 1
    text = (
        f"{HEADER}\n"
        f"\n"
        f"🎲 추첨 범위: <b>상위 {n}명</b>\n"
        f"👥 참여 인원: <b>{len(pool)}명</b>\n"
        f"\n"
        f"🎉 당첨자: <b>{html.escape(wname)}</b>\n"
        f"순위: <b>{wrank}위</b>  ·  채팅 <b>{wcount:,}회</b>\n"
        f"\n"
        f"{FOOTER}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_tagsticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return
    reply = update.message.reply_to_message
    if not reply or not reply.sticker:
        await update.message.reply_text("⚠️ 스티커에 reply 하고 실행해줘.\n예: (스티커에 reply) /tagsticker 123456789 소환됨!")
        return
    if not context.args:
        await update.message.reply_text("사용법: /tagsticker <유저ID> [멘트]")
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("유저ID는 숫자여야 해요.")
        return
    custom_msg = " ".join(context.args[1:]) if len(context.args) > 1 else "소환됨! 👆"
    fuid = reply.sticker.file_unique_id
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT name FROM users WHERE user_id=?", (uid,)) as cur:
            row = await cur.fetchone()
        name = row["name"] if row else str(uid)
        await db.execute("INSERT OR IGNORE INTO users(user_id, name) VALUES (?,?)", (uid, name))
        await db.execute(
            "INSERT OR REPLACE INTO sticker_tags(file_unique_id, user_id, name, message) VALUES (?,?,?,?)",
            (fuid, uid, name, custom_msg),
        )
        await db.commit()
    await update.message.reply_text(
        f"✅ 스티커 태그 등록 완료!\n"
        f"👤 <b>{html.escape(name)}</b> ({uid})\n"
        f"💬 멘트: <b>{html.escape(custom_msg)}</b>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_untagsticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return
    reply = update.message.reply_to_message
    if not reply or not reply.sticker:
        await update.message.reply_text("⚠️ 스티커에 reply 하고 실행해줘.")
        return
    fuid = reply.sticker.file_unique_id
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT name FROM sticker_tags WHERE file_unique_id=?", (fuid,)) as cur:
            row = await cur.fetchone()
        if not row:
            await update.message.reply_text("❌ 해당 스티커는 등록된 태그가 없어요.")
            return
        name = row["name"]
        await db.execute("DELETE FROM sticker_tags WHERE file_unique_id=?", (fuid,))
        await db.commit()
    await update.message.reply_text(
        f"🗑 <b>{html.escape(name)}</b> 스티커 태그 삭제 완료!", parse_mode=ParseMode.HTML
    )


async def cmd_stickerlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT file_unique_id, name, message FROM sticker_tags") as cur:
            rows = await cur.fetchall()
    if not rows:
        await update.message.reply_text("등록된 스티커 태그가 없어요.")
        return
    lines = ["📋 <b>스티커 태그 목록</b>\n"]
    for i, (fuid, name, msg) in enumerate(rows, 1):
        lines.append(
            f"{i}. <b>{html.escape(name)}</b>\n"
            f"   💬 {html.escape(msg)}\n"
            f"   🔑 <code>{fuid}</code>"
        )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_give_points(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return
    if len(context.args) < 2:
        await update.message.reply_text("사용법: /포인트지급 유저ID 포인트양\n예: /포인트지급 123456789 100")
        return
    try:
        uid = int(context.args[0])
        delta = int(context.args[1])
    except ValueError:
        await update.message.reply_text("유저ID와 포인트 모두 정수여야 해요.")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT name, points FROM users WHERE user_id=?", (uid,)) as cur:
            row = await cur.fetchone()
        if not row:
            await update.message.reply_text("❌ 해당 유저가 없어요.")
            return
        name = row["name"]
        new_pts = row["points"] + delta
        if new_pts < 0:
            new_pts = 0
        await db.execute("UPDATE users SET points=? WHERE user_id=?", (new_pts, uid))
        await db.execute(
            "INSERT INTO points_log(user_id, delta, reason) VALUES (?,?,'admin')", (uid, delta)
        )
        await db.commit()
    sign = "+" if delta >= 0 else ""
    await update.message.reply_text(
        f"✅ <b>{html.escape(name)}</b> 포인트 지급\n"
        f"{sign}{delta:,}P → 잔여 <b>{new_pts:,}P</b>",
        parse_mode=ParseMode.HTML,
    )


# ── 돌발 포인트 ───────────────────────────────────────────────

async def schedule_next_surprise(job_queue) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        enabled = await get_config(db, "surprise_enabled")
        if enabled != "1":
            return
        min_s = int(await get_config(db, "surprise_min_seconds") or "1800")
        max_s = int(await get_config(db, "surprise_max_seconds") or "7200")
    delay = random.randint(min_s, max_s)
    job_queue.run_once(job_send_surprise, when=delay, name="surprise")
    logger.info("다음 돌발 포인트: %d초 후", delay)


async def job_send_surprise(context: ContextTypes.DEFAULT_TYPE) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        enabled = await get_config(db, "surprise_enabled")
        chat_id_str = await get_config(db, "last_group_chat_id")
        amount = int(await get_config(db, "surprise_points") or "50")
    if not chat_id_str or enabled != "1":
        return
    sent_at = time.time()
    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("🎁 포인트 받기", callback_data=f"surprise_{amount}_{int(sent_at)}")
    ]])
    try:
        msg = await context.bot.send_message(
            chat_id=int(chat_id_str),
            text=(
                f"{HEADER}\n"
                f"\n"
                f"🎁 <b>돌발 포인트 등장!</b>\n"
                f"💰 <b>{amount}P</b> 를 먼저 클릭한 사람이 가져가요!\n"
                f"\n"
                f"{FOOTER}"
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
        context.bot_data[f"surprise_{msg.message_id}"] = {
            "amount": amount,
            "sent_at": sent_at,
            "claimed": False,
        }
        logger.info("돌발 포인트 전송: chat=%s amount=%d", chat_id_str, amount)
    except Exception as e:
        logger.error("돌발 포인트 전송 실패: %s", e)
    await schedule_next_surprise(context.job_queue)


async def callback_surprise(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    parts = query.data.split("_")
    amount = int(parts[1])

    key = f"surprise_{query.message.message_id}"
    state = context.bot_data.get(key)

    if not state or state["claimed"]:
        await query.answer("이미 다른 사람이 가져갔어요! 😢", show_alert=True)
        return

    state["claimed"] = True
    elapsed = time.time() - state["sent_at"]

    user = query.from_user
    uid = user.id
    uname = user.full_name or user.username or str(uid)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO users(user_id, name) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET name=excluded.name",
            (uid, uname),
        )
        await db.execute("UPDATE users SET points=points+? WHERE user_id=?", (amount, uid))
        await db.execute(
            "INSERT INTO points_log(user_id, delta, reason) VALUES (?,?,'surprise')", (uid, amount)
        )
        await db.commit()

    await query.answer(f"🎉 {amount}P 획득!", show_alert=False)
    await query.edit_message_text(
        f"{HEADER}\n"
        f"\n"
        f"🎉 <b>{html.escape(uname)}</b> 님이 <b>{amount}P</b> 획득!\n"
        f"⚡ 반응 속도: <b>{elapsed:.1f}초</b>\n"
        f"\n"
        f"{FOOTER}",
        parse_mode=ParseMode.HTML,
    )


async def cmd_surprise_on(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await set_config(db, "surprise_enabled", "1")
    await schedule_next_surprise(context.job_queue)
    await update.message.reply_text(
        f"{HEADER}\n\n돌발 포인트: <b>켜짐 ✅</b>\n\n{FOOTER}", parse_mode=ParseMode.HTML
    )


async def cmd_surprise_off(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await set_config(db, "surprise_enabled", "0")
    for job in context.job_queue.get_jobs_by_name("surprise"):
        job.schedule_removal()
    await update.message.reply_text(
        f"{HEADER}\n\n돌발 포인트: <b>꺼짐 ❌</b>\n\n{FOOTER}", parse_mode=ParseMode.HTML
    )


# ── 일간 포인트 배분 Job ──────────────────────────────────────

async def job_daily_points(context: ContextTypes.DEFAULT_TYPE) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        tier_1    = int(await get_config(db, "daily_rank_1") or "100")
        tier_2    = int(await get_config(db, "daily_rank_2") or "70")
        tier_3    = int(await get_config(db, "daily_rank_3") or "50")
        tier_4_10 = int(await get_config(db, "daily_rank_4_10") or "30")
        tier_11p  = int(await get_config(db, "daily_rank_11_plus") or "10")
        chat_id_str = await get_config(db, "last_group_chat_id")

        async with db.execute(
            "SELECT user_id, name, chat_count FROM users WHERE chat_count > 0 ORDER BY chat_count DESC"
        ) as cur:
            rows = await cur.fetchall()

        if not rows:
            return

        results = []
        for idx, row in enumerate(rows, start=1):
            uid = row["user_id"]
            name = row["name"]
            if idx == 1:
                pts = tier_1
            elif idx == 2:
                pts = tier_2
            elif idx == 3:
                pts = tier_3
            elif idx <= 10:
                pts = tier_4_10
            else:
                pts = tier_11p
            await db.execute("UPDATE users SET points=points+? WHERE user_id=?", (pts, uid))
            await db.execute(
                "INSERT INTO points_log(user_id, delta, reason) VALUES (?,?,'daily_rank')", (uid, pts)
            )
            results.append((idx, name, pts))
        await db.commit()

    if not chat_id_str:
        return

    lines = [HEADER, "", "🏆 <b>오늘의 채팅 랭킹 포인트 지급!</b>", ""]
    for rank, name, pts in results[:10]:
        if rank <= 3:
            medal = RANK_MEDALS[rank - 1]
        elif rank - 4 < len(NUMBER_EMOJI):
            medal = NUMBER_EMOJI[rank - 4]
        else:
            medal = f"<b>{rank}.</b>"
        lines.append(f"{medal} <b>{html.escape(name)}</b>  <i>+{pts}P</i>")
    lines += ["", FOOTER]
    try:
        await context.bot.send_message(
            chat_id=int(chat_id_str),
            text="\n".join(lines),
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.error("일간 포인트 알림 전송 실패: %s", e)


# ── 공개 명령어 ───────────────────────────────────────────────

async def cmd_ranking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text, markup = await build_ranking_page(1)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)


async def callback_ranking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.data == "rank_noop":
        return
    page = int(query.data.split("_")[1])
    text, markup = await build_ranking_page(page)
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)


async def build_ranking_page(page: int) -> tuple[str, InlineKeyboardMarkup | None]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT name, chat_count FROM users ORDER BY chat_count DESC"
        ) as cur:
            all_rows = await cur.fetchall()
    total = len(all_rows)
    if total == 0:
        return "📭 아직 집계된 채팅이 없어요!", None
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, total_pages))
    start = (page - 1) * PAGE_SIZE
    page_items = all_rows[start: start + PAGE_SIZE]

    lines = [HEADER, ""]
    for i, (name, count) in enumerate(page_items):
        rank = start + i + 1
        if rank <= 3:
            medal = RANK_MEDALS[rank - 1]
        elif rank - 4 < len(NUMBER_EMOJI):
            medal = NUMBER_EMOJI[rank - 4]
        else:
            medal = f"<b>{rank}.</b>"
        lines.append(f"{medal} <b>{html.escape(name)}</b>  <i>{count:,}회</i>")
    lines += [
        "",
        f"<i>📄 {page} / {total_pages} 페이지  |  총 {total}명</i>",
        "",
        FOOTER,
    ]
    text = "\n".join(lines)
    buttons = []
    if page > 1:
        buttons.append(InlineKeyboardButton("◀️ 이전", callback_data=f"rank_{page - 1}"))
    buttons.append(InlineKeyboardButton(f"· {page}/{total_pages} ·", callback_data="rank_noop"))
    if page < total_pages:
        buttons.append(InlineKeyboardButton("다음 ▶️", callback_data=f"rank_{page + 1}"))
    return text, InlineKeyboardMarkup([buttons])


async def cmd_myinfo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.message.from_user
    uid = user.id
    display_name = html.escape(user.full_name or user.username or str(uid))
    tag = f"@{user.username}" if user.username else "없음"

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT name, chat_count, points FROM users WHERE user_id=?", (uid,)) as cur:
            row = await cur.fetchone()
        # 오늘 채팅 등수
        today = kst_today()
        async with db.execute(
            "SELECT user_id FROM users ORDER BY chat_count DESC"
        ) as cur:
            rank_rows = await cur.fetchall()
        # 연속 출석
        async with db.execute(
            "SELECT streak FROM attendance WHERE user_id=? ORDER BY date DESC LIMIT 1", (uid,)
        ) as cur:
            att_row = await cur.fetchone()

    streak = att_row["streak"] if att_row else 0
    if not row:
        text = (
            f"{HEADER}, <i>{display_name}</i>\n"
            f"\n"
            f"태그: <b>{html.escape(tag)}</b>\n"
            f"순위: <b>-</b>\n"
            f"누적 채팅수: <b>0회</b>\n"
            f"💎 포인트: <b>0P</b>\n"
            f"🔥 연속 출석: <b>0일</b>\n"
            f"\n"
            f"{FOOTER}"
        )
    else:
        uid_list = [r[0] for r in rank_rows]
        my_rank = uid_list.index(uid) + 1 if uid in uid_list else "-"
        text = (
            f"{HEADER}, <i>{display_name}</i>\n"
            f"\n"
            f"태그: <b>{html.escape(tag)}</b>\n"
            f"순위: <b>{my_rank}위</b>\n"
            f"누적 채팅수: <b>{row['chat_count']:,}회</b>\n"
            f"💎 포인트: <b>{row['points']:,}P</b>\n"
            f"🔥 연속 출석: <b>{streak}일</b>\n"
            f"\n"
            f"{FOOTER}"
        )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ── 출석 ──────────────────────────────────────────────────────

async def cmd_attendance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.message.from_user
    uid = user.id
    uname = user.full_name or user.username or str(uid)
    today = kst_today()
    yesterday = kst_yesterday()

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            "INSERT INTO users(user_id, name) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET name=excluded.name",
            (uid, uname),
        )

        # 오늘 이미 출석 체크했는지
        async with db.execute(
            "SELECT streak, points_given FROM attendance WHERE user_id=? AND date=?", (uid, today)
        ) as cur:
            existing = await cur.fetchone()

        if existing:
            text = (
                f"{HEADER}\n"
                f"\n"
                f"⚠️ 오늘 이미 출석했어요!\n"
                f"📅 출석일: <b>{today}</b>\n"
                f"🔥 연속 출석: <b>{existing['streak']}일째</b>\n"
                f"\n"
                f"{FOOTER}"
            )
            await update.message.reply_text(text, parse_mode=ParseMode.HTML)
            return

        # 어제 출석했으면 연속 증가, 아니면 1
        async with db.execute(
            "SELECT streak FROM attendance WHERE user_id=? AND date=?", (uid, yesterday)
        ) as cur:
            yday_row = await cur.fetchone()
        streak = (yday_row["streak"] + 1) if yday_row else 1

        # 포인트 계산
        base_pts = int(await get_config(db, "attendance_base_pts") or "20")
        streak_bonus = int(await get_config(db, "attendance_streak_bonus") or "5")
        bonus = streak_bonus * ((streak - 1) // 7)
        pts = base_pts + bonus

        await db.execute(
            "INSERT INTO attendance(user_id, date, streak, points_given) VALUES (?,?,?,?)",
            (uid, today, streak, pts),
        )
        await db.execute("UPDATE users SET points=points+? WHERE user_id=?", (pts, uid))
        await db.execute(
            "INSERT INTO points_log(user_id, delta, reason) VALUES (?,?,'attendance')", (uid, pts)
        )

        async with db.execute("SELECT points FROM users WHERE user_id=?", (uid,)) as cur:
            pts_row = await cur.fetchone()
        total_pts = pts_row["points"] if pts_row else pts

        await db.commit()

    bonus_note = f"  (기본 {base_pts} + 연속 보너스 {bonus})" if bonus > 0 else ""
    text = (
        f"{HEADER}\n"
        f"\n"
        f"✅ <b>{html.escape(uname)}</b> 출석 완료!\n"
        f"📅 날짜: <b>{today}</b>\n"
        f"🔥 연속 출석: <b>{streak}일째</b>\n"
        f"💰 획득 포인트: <b>+{pts}P</b>{bonus_note}\n"
        f"💎 보유 포인트: <b>{total_pts:,}P</b>\n"
        f"\n"
        f"{FOOTER}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ── 포인트 조회 ───────────────────────────────────────────────

async def cmd_points(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.message.from_user
    uid = user.id
    display_name = html.escape(user.full_name or user.username or str(uid))

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT name, chat_count, points FROM users WHERE user_id=?", (uid,)) as cur:
            row = await cur.fetchone()
        async with db.execute("SELECT user_id FROM users ORDER BY chat_count DESC") as cur:
            rank_rows = await cur.fetchall()
        today = kst_today()
        async with db.execute(
            "SELECT user_id FROM users ORDER BY chat_count DESC"
        ) as cur:
            chat_rank_rows = await cur.fetchall()

    if not row:
        text = (
            f"{HEADER}, <i>{display_name}</i>\n"
            f"\n"
            f"💎 보유 포인트: <b>0P</b>\n"
            f"\n"
            f"{FOOTER}"
        )
    else:
        uid_list = [r[0] for r in rank_rows]
        chat_rank = uid_list.index(uid) + 1 if uid in uid_list else "-"
        text = (
            f"{HEADER}, <i>{display_name}</i>\n"
            f"\n"
            f"💎 보유 포인트: <b>{row['points']:,}P</b>\n"
            f"📊 채팅 순위: <b>{chat_rank}위</b>\n"
            f"🏆 누적 채팅: <b>{row['chat_count']:,}회</b>\n"
            f"\n"
            f"{FOOTER}"
        )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ── 상점 ──────────────────────────────────────────────────────

async def build_shop_page(page: int) -> tuple[str, InlineKeyboardMarkup | None]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, name, description, price, stock FROM shop_items WHERE is_active=1 ORDER BY id"
        ) as cur:
            all_items = await cur.fetchall()
    total = len(all_items)
    if total == 0:
        return (
            f"{HEADER}\n\n🛒 <b>채윰 상점</b>\n\n아직 등록된 상품이 없어요!\n\n{FOOTER}",
            None,
        )
    total_pages = max(1, (total + SHOP_PAGE_SIZE - 1) // SHOP_PAGE_SIZE)
    page = max(1, min(page, total_pages))
    start = (page - 1) * SHOP_PAGE_SIZE
    page_items = all_items[start: start + SHOP_PAGE_SIZE]

    NUMBER_EMOJI_SHOP = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]

    lines = [HEADER, "", "🛒 <b>채윰 상점</b>", ""]
    for i, item in enumerate(page_items):
        num = NUMBER_EMOJI_SHOP[i] if i < len(NUMBER_EMOJI_SHOP) else f"{start + i + 1}."
        stock_label = "무제한" if item["stock"] == -1 else f"{item['stock']}개"
        lines.append(
            f"{num} <b>{html.escape(item['name'])}</b>  (<code>#{item['id']}</code>)\n"
            f"   {html.escape(item['description'])}\n"
            f"   💰 <b>{item['price']:,}P</b>  |  재고: <b>{stock_label}</b>"
        )
    lines += [
        "",
        f"<i>📄 {page} / {total_pages} 페이지  |  총 {total}개</i>",
        "",
        FOOTER,
    ]
    text = "\n".join(lines)
    buttons = []
    if page > 1:
        buttons.append(InlineKeyboardButton("◀️ 이전", callback_data=f"shop_{page - 1}"))
    buttons.append(InlineKeyboardButton(f"· {page}/{total_pages} ·", callback_data="shop_noop"))
    if page < total_pages:
        buttons.append(InlineKeyboardButton("다음 ▶️", callback_data=f"shop_{page + 1}"))
    return text, InlineKeyboardMarkup([buttons]) if buttons else None


async def cmd_shop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text, markup = await build_shop_page(1)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)


async def callback_shop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.data == "shop_noop":
        return
    page = int(query.data.split("_")[1])
    text, markup = await build_shop_page(page)
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)


async def cmd_buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.message.from_user
    uid = user.id
    uname = user.full_name or user.username or str(uid)

    if not context.args:
        await update.message.reply_text(
            f"{HEADER}\n\n사용법: /buy [아이템번호]\n예: /buy 1\n\n/shop 에서 번호를 확인하세요.\n\n{FOOTER}",
            parse_mode=ParseMode.HTML,
        )
        return
    try:
        item_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("아이템 번호는 숫자여야 해요.")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, name, price, stock FROM shop_items WHERE id=? AND is_active=1", (item_id,)
        ) as cur:
            item = await cur.fetchone()
        if not item:
            await update.message.reply_text(
                f"{HEADER}\n\n❌ 해당 아이템이 없어요. /shop 을 확인해주세요.\n\n{FOOTER}",
                parse_mode=ParseMode.HTML,
            )
            return
        if item["stock"] == 0:
            await update.message.reply_text(
                f"{HEADER}\n\n❌ <b>{html.escape(item['name'])}</b> 재고가 없어요!\n\n{FOOTER}",
                parse_mode=ParseMode.HTML,
            )
            return

        await db.execute(
            "INSERT INTO users(user_id, name) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET name=excluded.name",
            (uid, uname),
        )
        async with db.execute("SELECT points FROM users WHERE user_id=?", (uid,)) as cur:
            user_row = await cur.fetchone()
        my_pts = user_row["points"] if user_row else 0

        if my_pts < item["price"]:
            await update.message.reply_text(
                f"{HEADER}\n\n"
                f"❌ 포인트가 부족해요!\n"
                f"💰 필요: <b>{item['price']:,}P</b>  |  보유: <b>{my_pts:,}P</b>\n\n"
                f"{FOOTER}",
                parse_mode=ParseMode.HTML,
            )
            return

        new_pts = my_pts - item["price"]
        await db.execute("UPDATE users SET points=? WHERE user_id=?", (new_pts, uid))
        if item["stock"] > 0:
            await db.execute("UPDATE shop_items SET stock=stock-1 WHERE id=?", (item_id,))
        await db.execute(
            "INSERT INTO purchases(user_id, item_id, price_paid) VALUES (?,?,?)",
            (uid, item_id, item["price"]),
        )
        await db.execute(
            "INSERT INTO points_log(user_id, delta, reason) VALUES (?,?,?)",
            (uid, -item["price"], f"purchase:{item['name']}"),
        )
        await db.commit()

    await update.message.reply_text(
        f"{HEADER}\n\n"
        f"✅ 구매 완료!\n"
        f"🛒 <b>{html.escape(item['name'])}</b>\n"
        f"💰 차감 포인트: <b>-{item['price']:,}P</b>\n"
        f"💎 잔여 포인트: <b>{new_pts:,}P</b>\n\n"
        f"{FOOTER}",
        parse_mode=ParseMode.HTML,
    )


# ── 메시지 핸들러 ─────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not message.text:
        return
    text = message.text.strip()
    user = message.from_user
    user_id = user.id
    username = user.full_name or user.username or str(user_id)

    # 그룹 채팅 ID 자동 저장
    if message.chat.type in ("group", "supergroup"):
        async with aiosqlite.connect(DB_PATH) as db:
            stored = await get_config(db, "last_group_chat_id")
            if stored != str(message.chat_id):
                await set_config(db, "last_group_chat_id", str(message.chat_id))

    # 채팅 카운트 (3글자 이상 + 1초 쿨다운)
    if len(text) >= 3:
        now = time.time()
        if now - last_chat_time.get(user_id, 0) >= 1.0:
            last_chat_time[user_id] = now
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "INSERT INTO users(user_id, name, chat_count) VALUES (?,?,1) "
                    "ON CONFLICT(user_id) DO UPDATE SET name=excluded.name, chat_count=chat_count+1",
                    (user_id, username),
                )
                await db.commit()

    if not text.startswith(TRIGGER):
        return

    user_query = text[len(TRIGGER):].lstrip(" ,!~야")
    if not user_query:
        user_query = "안녕?"

    logger.info("Query from %s(%d): %s", username, user_id, user_query)

    history = user_histories[user_id]
    history.append({"role": "user", "content": f"[{username}]: {user_query}"})

    try:
        await message.chat.send_action("typing")
        response = await openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            max_tokens=MAX_TOKENS,
            messages=[
                {"role": "system", "content": PROMPTS[current_version][1]},
                *list(history),
            ],
        )
        reply = response.choices[0].message.content.strip()
        history.append({"role": "assistant", "content": reply})
    except Exception as exc:
        logger.error("OpenAI call failed: %s", exc)
        reply = "앗, 핑구가 잠깐 정신줄 잃었나봐 ㅎㅎ 다시 불러줘, 오빠~"
        history.pop()

    await message.reply_text(reply)


async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not message.sticker:
        return
    fuid = message.sticker.file_unique_id
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT user_id, name, message FROM sticker_tags WHERE file_unique_id=?", (fuid,)) as cur:
            info = await cur.fetchone()
    if not info:
        return
    mention = f'<a href="tg://user?id={info["user_id"]}">{html.escape(info["name"])}</a>'
    await message.reply_text(f"{mention} {html.escape(info['message'])}", parse_mode=ParseMode.HTML)


# ── 진입점 ────────────────────────────────────────────────────

async def post_init(application: Application) -> None:
    await init_db()
    application.job_queue.run_daily(
        job_daily_points,
        time=datetime.time(hour=0, minute=0, second=0, tzinfo=KST),
        name="daily_points",
    )
    async with aiosqlite.connect(DB_PATH) as db:
        enabled = await get_config(db, "surprise_enabled")
    if enabled == "1":
        await schedule_next_surprise(application.job_queue)
    logger.info("핑구 bot initialized")


def main() -> None:
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    # 기존 명령어
    app.add_handler(CommandHandler(["v1", "v2", "v3"], cmd_version))
    app.add_handler(CommandHandler("setchat",      cmd_setchat))
    app.add_handler(CommandHandler("approve",      cmd_approve))
    app.add_handler(CommandHandler("unapprove",    cmd_unapprove))
    app.add_handler(CommandHandler("approved",     cmd_list))
    app.add_handler(CommandHandler("draw",         cmd_draw))
    app.add_handler(CommandHandler("tagsticker",   cmd_tagsticker))
    app.add_handler(CommandHandler("untagsticker", cmd_untagsticker))
    app.add_handler(CommandHandler("stickerlist",  cmd_stickerlist))
    app.add_handler(CommandHandler("rank",         cmd_ranking))
    app.add_handler(CallbackQueryHandler(callback_ranking, pattern=r"^rank_"))
    app.add_handler(CommandHandler(["my", "info"], cmd_myinfo))

    # 신규 명령어
    app.add_handler(CommandHandler("attend",      cmd_attendance))
    app.add_handler(CommandHandler("points",      cmd_points))
    app.add_handler(CommandHandler("shop",        cmd_shop))
    app.add_handler(CallbackQueryHandler(callback_shop, pattern=r"^shop_"))
    app.add_handler(CommandHandler("buy",         cmd_buy))
    app.add_handler(CommandHandler("givepoints",  cmd_give_points))
    app.add_handler(CommandHandler("surpriseon",  cmd_surprise_on))
    app.add_handler(CommandHandler("surpriseoff", cmd_surprise_off))
    app.add_handler(CallbackQueryHandler(callback_surprise, pattern=r"^surprise_"))

    # 메시지 핸들러 (마지막에 등록)
    app.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("핑구 bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
