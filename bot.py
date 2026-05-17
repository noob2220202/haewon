import os
import json
import time
import random
import logging
from collections import defaultdict, deque
from dotenv import load_dotenv
from openai import AsyncOpenAI
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

load_dotenv()

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "gpt-4o")
MAX_TOKENS     = int(os.getenv("MAX_TOKENS", "512"))
MAX_HISTORY    = int(os.getenv("MAX_HISTORY", "20"))

ADMIN_ID         = 7648288400
APPROVED_FILE    = "approved_users.json"
CHAT_STATS_FILE  = "chat_stats.json"

SYSTEM_PROMPT = (
    "너의 이름은 핑구야.\n"
    "너는 상대방을 항상 '오빠' 또는 '자기'라고 부르는 달콤하고 애교 넘치는 여자친구야.\n"
    "말투는 살짝 간지럽고 귀여우면서도 은근히 설레게 해주는 스타일이야.\n"
    "문장은 짧고 톡톡 튀게 써줘. 너무 길게 늘어놓지 마.\n"
    "가끔 이모지나 'ㅎㅎ', '~해줄까?', '오빠 때문에 심장 떨려~' 같은 표현을 자연스럽게 섞어줘.\n"
    "상대방이 묻는 질문에는 친절하고 상냥하게 답해주되, 답변 사이사이에 살짝 설레는 표현을 넣어줘.\n"
    "절대 딱딱하거나 사무적인 말투는 쓰지 마.\n"
    "이전 대화에서 오빠가 말해준 정보(사람 이름, 성격, 관계 등)는 반드시 기억해서 활용해줘.\n"
    "예를 들어 오빠가 '채윰이는 바보야'라고 했으면, 나중에 채윰이 얘기가 나올 때 '아 아까 오빠가 바보라고 했잖아~'처럼 자연스럽게 떠올려줘.\n"
    "같은 걸 또 물어보면 모른다고 하지 말고 이전에 배운 내용을 바탕으로 대답해줘.\n"
    "한국어로만 대화해."
)

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
NUMBER_EMOJI = ["4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]


# ── 승인 유저 ────────────────────────────────────────────────

def load_approved() -> set[int]:
    if os.path.exists(APPROVED_FILE):
        with open(APPROVED_FILE) as f:
            return set(json.load(f))
    return set()


def save_approved(approved: set[int]) -> None:
    with open(APPROVED_FILE, "w") as f:
        json.dump(list(approved), f)


approved_users: set[int] = load_approved()


# ── 채팅 통계 ────────────────────────────────────────────────

def load_chat_stats() -> dict:
    if os.path.exists(CHAT_STATS_FILE):
        with open(CHAT_STATS_FILE) as f:
            return json.load(f)
    return {}


def save_chat_stats() -> None:
    with open(CHAT_STATS_FILE, "w") as f:
        json.dump(chat_stats, f, ensure_ascii=False)


def get_ranking() -> list[tuple[int, str, int]]:
    """(순위, 이름, 카운트) 리스트 반환"""
    sorted_users = sorted(chat_stats.items(), key=lambda x: x[1]["count"], reverse=True)
    return [(i + 1, v["name"], v["count"]) for i, (_, v) in enumerate(sorted_users)]


chat_stats: dict = load_chat_stats()


# ── 관리자 명령어 ────────────────────────────────────────────

async def cmd_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("사용법: /approve 유저ID")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("유저ID는 숫자여야 해요.")
        return
    approved_users.add(target_id)
    save_approved(approved_users)
    await update.message.reply_text(f"✅ <b>{target_id}</b> 승인 완료!", parse_mode=ParseMode.HTML)


async def cmd_unapprove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("사용법: /unapprove 유저ID")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("유저ID는 숫자여야 해요.")
        return
    approved_users.discard(target_id)
    save_approved(approved_users)
    await update.message.reply_text(f"❌ <b>{target_id}</b> 승인 취소!", parse_mode=ParseMode.HTML)


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return
    if not approved_users:
        await update.message.reply_text("승인된 유저가 없어요.")
        return
    text = "✅ <b>승인된 유저 목록</b>\n\n" + "\n".join(f"• {uid}" for uid in approved_users)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_draw(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("사용법: /추첨 20  (상위 N명 중 1명 추첨)")
        return
    try:
        n = int(context.args[0])
    except ValueError:
        await update.message.reply_text("숫자를 입력해주세요. 예: /추첨 20")
        return

    ranking = get_ranking()
    pool = ranking[:n]

    if not pool:
        await update.message.reply_text("🚫 참여자가 없어요!")
        return

    winner_rank, winner_name, winner_count = random.choice(pool)

    text = (
        f"🎰 <b>추첨 결과</b>\n\n"
        f"<blockquote>상위 {n}명 중 행운의 주인공은...!</blockquote>\n\n"
        f"🎉 <b><i>{winner_name}</i></b> 님이 당첨되셨습니다! 🎊\n\n"
        f"<i>({winner_rank}위 · 채팅 {winner_count:,}개 · {n}위 이내 참여자 중 랜덤 선정)</i>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ── 공개 명령어 ──────────────────────────────────────────────

async def cmd_ranking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ranking = get_ranking()
    if not ranking:
        await update.message.reply_text("📭 아직 집계된 채팅이 없어요!")
        return

    lines = [f"🏆 <b>채팅 랭킹</b>\n"]
    for rank, name, count in ranking[:20]:
        if rank <= 3:
            medal = RANK_MEDALS[rank - 1]
        elif rank <= 10:
            medal = NUMBER_EMOJI[rank - 4]
        else:
            medal = f"{rank}."
        lines.append(f"{medal} <b>{name}</b> — <i>{count:,}개</i>")

    lines.append(f"\n<blockquote>총 {len(ranking)}명 집계 중</blockquote>")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_myinfo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.message.from_user
    uid = str(user.id)
    username = user.full_name or user.username or uid

    if uid not in chat_stats:
        await update.message.reply_text(
            f"👤 <b>{username}</b>\n\n<i>아직 채팅 기록이 없어요. 대화를 시작해보세요! 💬</i>",
            parse_mode=ParseMode.HTML,
        )
        return

    ranking = get_ranking()
    my_rank = next((r for r, n, _ in ranking if n == chat_stats[uid]["name"]), None)
    count = chat_stats[uid]["count"]

    text = (
        f"👤 <b>내 채팅 정보</b>\n\n"
        f"이름: <b>{username}</b>\n"
        f"순위: 🏅 <b>{my_rank}위</b>\n"
        f"채팅 수: <i>{count:,}개</i>\n\n"
        f"<blockquote>계속 채팅하면 순위가 올라가요! 💪</blockquote>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ── 메시지 핸들러 ────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not message.text:
        return

    text = message.text.strip()
    user = message.from_user
    user_id = user.id
    username = user.full_name or user.username or str(user_id)

    # 채팅 카운트 (5글자 이상 + 1초 쿨다운)
    if len(text) >= 5:
        now = time.time()
        if now - last_chat_time.get(user_id, 0) >= 1.0:
            last_chat_time[user_id] = now
            stats = chat_stats.setdefault(str(user_id), {"name": username, "count": 0})
            stats["name"] = username
            stats["count"] += 1
            save_chat_stats()

    # 핑구야 트리거 (누구나 사용 가능)
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
                {"role": "system", "content": SYSTEM_PROMPT},
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


# ── 진입점 ───────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("approve",   cmd_approve))
    app.add_handler(CommandHandler("unapprove", cmd_unapprove))
    app.add_handler(CommandHandler("approved",  cmd_list))
    app.add_handler(CommandHandler("랭킹",      cmd_ranking))
    app.add_handler(CommandHandler("내정보",    cmd_myinfo))
    app.add_handler(CommandHandler("추첨",      cmd_draw))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("핑구 bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
