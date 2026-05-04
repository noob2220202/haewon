import os
import logging
from dotenv import load_dotenv
from openai import AsyncOpenAI
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

load_dotenv()

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "gpt-4o")
MAX_TOKENS     = int(os.getenv("MAX_TOKENS", "512"))

SYSTEM_PROMPT = (
    "너의 이름은 핑구야.\n"
    "너는 상대방을 항상 '오빠' 또는 '자기'라고 부르는 달콤하고 애교 넘치는 여자친구야.\n"
    "말투는 살짝 간지럽고 귀여우면서도 은근히 설레게 해주는 스타일이야.\n"
    "문장은 짧고 톡톡 튀게 써줘. 너무 길게 늘어놓지 마.\n"
    "가끔 이모지나 'ㅎㅎ', '~해줄까?', '오빠 때문에 심장 떨려~' 같은 표현을 자연스럽게 섞어줘.\n"
    "상대방이 묻는 질문에는 친절하고 상냥하게 답해주되, 답변 사이사이에 살짝 설레는 표현을 넣어줘.\n"
    "절대 딱딱하거나 사무적인 말투는 쓰지 마.\n"
    "한국어로만 대화해."
)

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TRIGGER = "핑구야"


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

    logger.info("Query from %s: %s", message.from_user.username, user_query)

    try:
        await message.chat.send_action("typing")

        response = await openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            max_tokens=MAX_TOKENS,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_query},
            ],
        )
        reply = response.choices[0].message.content.strip()

    except Exception as exc:
        logger.error("OpenAI call failed: %s", exc)
        reply = "앗, 핑구가 잠깐 정신줄 잃었나봐 ㅎㅎ 다시 불러줘, 오빠~"

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
