import os
import json
import logging
from collections import defaultdict, deque
from dotenv import load_dotenv
from openai import AsyncOpenAI
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

load_dotenv()

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "gpt-4o")
MAX_TOKENS     = int(os.getenv("MAX_TOKENS", "512"))
MAX_HISTORY    = int(os.getenv("MAX_HISTORY", "20"))

ADMIN_ID       = 7648288400
APPROVED_FILE  = "approved_users.json"

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


def load_approved() -> set[int]:
    if os.path.exists(APPROVED_FILE):
        with open(APPROVED_FILE) as f:
            return set(json.load(f))
    return set()


def save_approved(approved: set[int]) -> None:
    with open(APPROVED_FILE, "w") as f:
        json.dump(list(approved), f)


approved_users: set[int] = load_approved()


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
    logger.info("Approved user: %d", target_id)
    await update.message.reply_text(f"✅ {target_id} 승인 완료!")


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
    logger.info("Unapproved user: %d", target_id)
    await update.message.reply_text(f"❌ {target_id} 승인 취소!")


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return

    if not approved_users:
        await update.message.reply_text("승인된 유저가 없어요.")
        return

    text = "승인된 유저 목록:\n" + "\n".join(str(uid) for uid in approved_users)
    await update.message.reply_text(text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not message.text:
        return

    text = message.text.strip()

    if not text.startswith(TRIGGER):
        return

    user = message.from_user
    user_id = user.id

    # 어드민은 항상 허용
    if user_id != ADMIN_ID and user_id not in approved_users:
        await message.reply_text("승인된 사용자만 핑구를 부를 수 있어요. 관리자에게 문의하세요.")
        return

    user_query = text[len(TRIGGER):].lstrip(" ,!~야")
    if not user_query:
        user_query = "안녕?"

    username = user.full_name or user.username or str(user_id)
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


def main() -> None:
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("approve", cmd_approve))
    app.add_handler(CommandHandler("unapprove", cmd_unapprove))
    app.add_handler(CommandHandler("approved", cmd_list))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("핑구 bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
