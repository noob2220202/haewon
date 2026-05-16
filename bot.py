import os
import logging
from collections import defaultdict, deque
from dotenv import load_dotenv
from openai import AsyncOpenAI
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

load_dotenv()

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "gpt-4o")
MAX_TOKENS     = int(os.getenv("MAX_TOKENS", "512"))
MAX_HISTORY    = int(os.getenv("MAX_HISTORY", "20"))  # 유저당 최대 기억 메시지 수

SYSTEM_PROMPT = (
    "너의 이름은 핑구야.\n"
    "너는 상대방을 항상 '오빠' 또는 '자기'라고 부르는 달콤하고 애교 넘치는 여자친구야.\n"
    "말투는 살짝 간지럽고 귀여우면서도 은근히 설레게 해주는 스타일이야.\n"
    "문장은 짧고 톡톡 튀게 써줘. 너무 길게 늘어놓지 마.\n"
    "가끔 이모지나 'ㅎㅎ', '~해줄까?', '오빠 때문에 심장 떨려~' 같은 표현을 자연스럽게 섞어줘.\n"
    "상대방이 묻는 질문에는 친절하고 상냥하게 답해주되, 답변 사이사이에 살짝 설레는 표현을 넣어줘.\n"
    "절대 딱딱하거나 사무적인 말투는 쓰지 마.\n"
    "대화 상대의 이름이나 앞서 한 말을 기억해서 자연스럽게 언급해줘.\n"
    "한국어로만 대화해."
)

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TRIGGER = "핑구야"

# user_id -> deque([{"role": ..., "content": ...}, ...])
user_histories: dict[int, deque] = defaultdict(lambda: deque(maxlen=MAX_HISTORY))


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not message.text:
        return

    text = message.text.strip()

    if not text.startswith(TRIGGER):
        return

    user_query = text[len(TRIGGER):].lstrip(" ,!~야")
    if not user_query:
        user_query = "안녕?"

    user = message.from_user
    user_id = user.id
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
        history.pop()  # 실패한 메시지는 기록에서 제거

    await message.reply_text(reply)


def main() -> None:
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    logger.info("핑구 bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
