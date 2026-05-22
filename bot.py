import os
import json
import time
import random
import logging
import html
from datetime import datetime
from datetime import time as dtime
import zoneinfo
from collections import defaultdict, deque
from dotenv import load_dotenv
from openai import AsyncOpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes

load_dotenv()

TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
OPENAI_API_KEY   = os.environ["OPENAI_API_KEY"]
OPENAI_MODEL     = os.getenv("OPENAI_MODEL", "gpt-4o")
MAX_TOKENS       = int(os.getenv("MAX_TOKENS", "512"))
MAX_HISTORY      = int(os.getenv("MAX_HISTORY", "20"))
ANNOUNCE_CHAT_ID = int(os.getenv("ANNOUNCE_CHAT_ID", "0"))

ADMINS: set[int] = {7648288400}

CHAT_STATS_FILE   = "chat_stats.json"
DAY_STATS_FILE    = "day_stats.json"
STICKER_TAGS_FILE = "sticker_tags.json"

KST = zoneinfo.ZoneInfo("Asia/Seoul")


def today_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


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
        "- 한국어로만 대화해.\n"
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
        "- 한국어로만 대화해.\n"
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
        "- 한국어로만 대화해.\n"
    ),
}

current_version: int = 1


def get_prompt() -> str:
    return PROMPTS[current_version][1]


openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TRIGGER = "핑구야"

user_histories: dict[int, deque] = defaultdict(lambda: deque(maxlen=MAX_HISTORY))
last_chat_time: dict[int, float] = {}

RANK_MEDALS  = ["🥇", "🥈", "🥉"]
NUMBER_EMOJI = ["4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]


# ── 어드민 체크 ──────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    return user_id in ADMINS


# ── 채팅 통계 (누적) ─────────────────────────────────────────

def load_chat_stats() -> dict:
    if os.path.exists(CHAT_STATS_FILE):
        with open(CHAT_STATS_FILE) as f:
            return json.load(f)
    return {}


def save_chat_stats() -> None:
    with open(CHAT_STATS_FILE, "w") as f:
        json.dump(chat_stats, f, ensure_ascii=False)


chat_stats: dict = load_chat_stats()


# ── 채팅 통계 (일일) ─────────────────────────────────────────

def load_day_stats() -> dict:
    today = today_kst()
    if os.path.exists(DAY_STATS_FILE):
        with open(DAY_STATS_FILE) as f:
            data = json.load(f)
        if data.get("date") == today:
            return data
    return {"date": today, "stats": {}}


def save_day_stats() -> None:
    with open(DAY_STATS_FILE, "w") as f:
        json.dump(day_stats, f, ensure_ascii=False)


def ensure_day_reset() -> None:
    global day_stats
    if day_stats.get("date") != today_kst():
        day_stats = {"date": today_kst(), "stats": {}}
        save_day_stats()


day_stats: dict = load_day_stats()


# ── 스티커 태그 ──────────────────────────────────────────────

def load_sticker_tags() -> dict:
    if os.path.exists(STICKER_TAGS_FILE):
        with open(STICKER_TAGS_FILE) as f:
            return json.load(f)
    return {}


def save_sticker_tags() -> None:
    with open(STICKER_TAGS_FILE, "w") as f:
        json.dump(sticker_tags, f, ensure_ascii=False)


sticker_tags: dict = load_sticker_tags()


# ── 랭킹 헬퍼 ────────────────────────────────────────────────

def get_ranking(stats_dict: dict) -> list[tuple[int, str, int]]:
    sorted_users = sorted(stats_dict.items(), key=lambda x: x[1]["count"], reverse=True)
    return [(i + 1, v["name"], v["count"]) for i, (_, v) in enumerate(sorted_users)]


# ── 자정 일일 결과 발송 ───────────────────────────────────────

async def job_midnight_ranking(context) -> None:
    global day_stats

    if not ANNOUNCE_CHAT_ID:
        day_stats = {"date": today_kst(), "stats": {}}
        save_day_stats()
        return

    stats      = day_stats.get("stats", {})
    date_label = day_stats.get("date", today_kst())

    try:
        dt = datetime.strptime(date_label, "%Y-%m-%d")
        date_str = dt.strftime("%m월 %d일")
    except Exception:
        date_str = date_label

    ranking = get_ranking(stats)

    if not ranking:
        text = (
            f"🎣 <b>도파민 가득 채윰</b>\n"
            f"\n"
            f"📅 <b>{date_str} 일일 결과</b>\n"
            f"\n"
            f"오늘은 채팅 기록이 없어요 😢\n"
            f"\n"
            f"<i>💬 채윰이와 신나게 놀아요ฅᐢ..ᐢ₎♡</i>"
        )
    else:
        lines = [
            f"🎣 <b>도파민 가득 채윰</b>",
            f"",
            f"📅 <b>{date_str} 일일 결과</b>",
            f"",
        ]
        for rank, name, count in ranking[:20]:
            if rank <= 3:
                medal = RANK_MEDALS[rank - 1]
            elif rank - 4 < len(NUMBER_EMOJI):
                medal = NUMBER_EMOJI[rank - 4]
            else:
                medal = f"{rank}."
            lines.append(f"{medal} <b>{html.escape(name)}</b>  <i>{count:,}회</i>")
        lines += [
            f"",
            f"<i>총 {len(ranking)}명 참여</i>",
            f"",
            f"<i>💬 채윰이와 신나게 놀아요ฅᐢ..ᐢ₎♡</i>",
        ]
        text = "\n".join(lines)

    try:
        await context.bot.send_message(
            chat_id=ANNOUNCE_CHAT_ID,
            text=text,
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.error("자정 랭킹 발송 실패: %s", e)

    day_stats = {"date": today_kst(), "stats": {}}
    save_day_stats()
    logger.info("일일 통계 초기화 완료 → %s", today_kst())


# ── 버전 전환 ────────────────────────────────────────────────

async def cmd_version(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global current_version
    if not is_admin(update.message.from_user.id):
        return
    cmd = update.message.text.strip().lstrip("/").split("@")[0]
    v = int(cmd[1])
    current_version = v
    label, _ = PROMPTS[v]
    user_histories.clear()
    text = (
        f"🎣 <b>도파민 가득 채윰</b>\n"
        f"\n"
        f"모드: <b>{label}</b>\n"
        f"<i>대화 기록 전체 초기화됨 🗑</i>\n"
        f"\n"
        f"<i>💬 채윰이와 신나게 놀아요ฅᐢ..ᐢ₎♡</i>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ── 관리자 명령어 ────────────────────────────────────────────

async def cmd_setchat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.message.from_user.id):
        return
    if len(context.args) < 2:
        await update.message.reply_text("사용법: /setchat 유저ID 숫자\n예: /setchat 123456789 500")
        return
    try:
        target_id = str(int(context.args[0]))
        amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text("유저ID와 숫자 모두 정수여야 해요.")
        return
    if target_id not in chat_stats:
        await update.message.reply_text("❌ 해당 유저의 채팅 기록이 없어요.")
        return
    old = chat_stats[target_id]["count"]
    chat_stats[target_id]["count"] = amount
    save_chat_stats()
    name = chat_stats[target_id]["name"]
    await update.message.reply_text(
        f"✅ <b>{html.escape(name)}</b> 누적 채팅수 변경\n{old:,}회 → <b>{amount:,}회</b>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_setdayrank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.message.from_user.id):
        return
    if len(context.args) < 2:
        await update.message.reply_text("사용법: /setdayrank 유저ID 숫자\n예: /setdayrank 123456789 50")
        return
    try:
        target_id = str(int(context.args[0]))
        amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text("유저ID와 숫자 모두 정수여야 해요.")
        return
    ensure_day_reset()
    if target_id not in day_stats["stats"]:
        await update.message.reply_text("❌ 해당 유저의 오늘 채팅 기록이 없어요.")
        return
    old = day_stats["stats"][target_id]["count"]
    day_stats["stats"][target_id]["count"] = amount
    save_day_stats()
    name = day_stats["stats"][target_id]["name"]
    await update.message.reply_text(
        f"✅ <b>{html.escape(name)}</b> 오늘 채팅수 변경\n{old:,}회 → <b>{amount:,}회</b>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_draw(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.message.from_user.id):
        return
    if not context.args:
        await update.message.reply_text("사용법: /draw 20  (누적 상위 N명 중 1명 추첨)")
        return
    try:
        n = int(context.args[0])
    except ValueError:
        await update.message.reply_text("숫자를 입력해주세요. 예: /draw 20")
        return

    ranking = get_ranking(chat_stats)
    pool = ranking[:n]
    if not pool:
        await update.message.reply_text("🚫 참여자가 없어요!")
        return

    winner_rank, winner_name, winner_count = random.choice(pool)
    text = (
        f"🎣 <b>도파민 가득 채윰</b>\n"
        f"\n"
        f"📊 누적 추첨\n"
        f"🎲 추첨 범위: <b>상위 {n}명</b>\n"
        f"👥 참여 인원: <b>{len(pool)}명</b>\n"
        f"\n"
        f"🎉 당첨자: <b>{html.escape(winner_name)}</b>\n"
        f"순위: <b>{winner_rank}위</b>  ·  채팅 <b>{winner_count:,}회</b>\n"
        f"\n"
        f"<i>💬 채윰이와 신나게 놀아요ฅᐢ..ᐢ₎♡</i>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_drawday(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.message.from_user.id):
        return
    if not context.args:
        await update.message.reply_text("사용법: /drawday 20  (오늘 상위 N명 중 1명 추첨)")
        return
    try:
        n = int(context.args[0])
    except ValueError:
        await update.message.reply_text("숫자를 입력해주세요. 예: /drawday 20")
        return

    ensure_day_reset()
    ranking = get_ranking(day_stats["stats"])
    pool = ranking[:n]
    if not pool:
        await update.message.reply_text("🚫 오늘 채팅한 참여자가 없어요!")
        return

    winner_rank, winner_name, winner_count = random.choice(pool)
    date_str = datetime.now(KST).strftime("%m월 %d일")
    text = (
        f"🎣 <b>도파민 가득 채윰</b>\n"
        f"\n"
        f"📅 오늘({date_str}) 추첨\n"
        f"🎲 추첨 범위: <b>상위 {n}명</b>\n"
        f"👥 참여 인원: <b>{len(pool)}명</b>\n"
        f"\n"
        f"🎉 당첨자: <b>{html.escape(winner_name)}</b>\n"
        f"오늘 순위: <b>{winner_rank}위</b>  ·  오늘 채팅 <b>{winner_count:,}회</b>\n"
        f"\n"
        f"<i>💬 채윰이와 신나게 놀아요ฅᐢ..ᐢ₎♡</i>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_tagsticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.message.from_user.id):
        return
    reply = update.message.reply_to_message
    if not reply or not reply.sticker:
        await update.message.reply_text("⚠️ 스티커에 reply 하고 실행해줘.\n예: (스티커에 reply) /tagsticker 123456789 소환됨!")
        return
    if not context.args:
        await update.message.reply_text("사용법: /tagsticker <유저ID> [멘트]\n예: /tagsticker 123456789 어서오세요~")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("유저ID는 숫자여야 해요.")
        return

    custom_msg = " ".join(context.args[1:]) if len(context.args) > 1 else "소환됨! 👆"
    name = chat_stats.get(str(target_id), {}).get("name", str(target_id))
    fuid = reply.sticker.file_unique_id

    sticker_tags[fuid] = {"user_id": target_id, "name": name, "message": custom_msg}
    save_sticker_tags()

    await update.message.reply_text(
        f"✅ 스티커 태그 등록 완료!\n"
        f"👤 <b>{html.escape(name)}</b> ({target_id})\n"
        f"💬 멘트: <b>{html.escape(custom_msg)}</b>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_untagsticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.message.from_user.id):
        return
    reply = update.message.reply_to_message
    if not reply or not reply.sticker:
        await update.message.reply_text("⚠️ 스티커에 reply 하고 실행해줘.")
        return
    fuid = reply.sticker.file_unique_id
    if fuid not in sticker_tags:
        await update.message.reply_text("❌ 해당 스티커는 등록된 태그가 없어요.")
        return
    name = sticker_tags[fuid]["name"]
    del sticker_tags[fuid]
    save_sticker_tags()
    await update.message.reply_text(f"🗑 <b>{html.escape(name)}</b> 스티커 태그 삭제 완료!", parse_mode=ParseMode.HTML)


async def cmd_stickerlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.message.from_user.id):
        return
    if not sticker_tags:
        await update.message.reply_text("등록된 스티커 태그가 없어요.")
        return
    lines = ["📋 <b>스티커 태그 목록</b>\n"]
    for i, (fuid, info) in enumerate(sticker_tags.items(), 1):
        lines.append(
            f"{i}. <b>{html.escape(info['name'])}</b> ({info['user_id']})\n"
            f"   💬 {html.escape(info['message'])}\n"
            f"   🔑 <code>{fuid}</code>"
        )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


# ── 공개 명령어 ──────────────────────────────────────────────

PAGE_SIZE = 10


def build_ranking_page(page: int, stats_dict: dict, title: str, cb_prefix: str) -> tuple[str, InlineKeyboardMarkup | None]:
    ranking = get_ranking(stats_dict)
    total = len(ranking)

    if total == 0:
        return "📭 아직 집계된 채팅이 없어요!", None

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, total_pages))
    start = (page - 1) * PAGE_SIZE
    page_items = ranking[start: start + PAGE_SIZE]

    lines = [
        f"🎣 <b>도파민 가득 채윰</b>",
        f"<i>{title}</i>",
        f"",
    ]
    for rank, name, count in page_items:
        if rank <= 3:
            medal = RANK_MEDALS[rank - 1]
        elif rank - 4 < len(NUMBER_EMOJI):
            medal = NUMBER_EMOJI[rank - 4]
        else:
            medal = f"{rank}."
        lines.append(f"{medal} <b>{html.escape(name)}</b>  <i>{count:,}회</i>")

    lines += [
        f"",
        f"<i>📄 {page} / {total_pages} 페이지  |  총 {total}명</i>",
        f"",
        f"<i>💬 채윰이와 신나게 놀아요ฅᐢ..ᐢ₎♡</i>",
    ]
    text = "\n".join(lines)

    buttons = []
    if page > 1:
        buttons.append(InlineKeyboardButton("◀️ 이전", callback_data=f"{cb_prefix}_{page - 1}"))
    buttons.append(InlineKeyboardButton(f"· {page}/{total_pages} ·", callback_data=f"{cb_prefix}_noop"))
    if page < total_pages:
        buttons.append(InlineKeyboardButton("다음 ▶️", callback_data=f"{cb_prefix}_{page + 1}"))

    markup = InlineKeyboardMarkup([buttons])
    return text, markup


async def cmd_ranking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text, markup = build_ranking_page(1, chat_stats, "📊 누적 순위", "rank")
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)


async def cmd_dayrank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ensure_day_reset()
    date_str = datetime.now(KST).strftime("%m월 %d일")
    text, markup = build_ranking_page(1, day_stats["stats"], f"📅 오늘({date_str}) 순위", "dayrank")
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)


async def callback_ranking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data
    if data.endswith("_noop"):
        return

    if data.startswith("dayrank_"):
        page = int(data.split("_")[1])
        ensure_day_reset()
        date_str = datetime.now(KST).strftime("%m월 %d일")
        text, markup = build_ranking_page(page, day_stats["stats"], f"📅 오늘({date_str}) 순위", "dayrank")
    else:
        page = int(data.split("_")[1])
        text, markup = build_ranking_page(page, chat_stats, "📊 누적 순위", "rank")

    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)


async def cmd_myinfo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ensure_day_reset()
    user = update.message.from_user
    uid = str(user.id)
    tag = f"@{user.username}" if user.username else "없음"

    count     = chat_stats.get(uid, {}).get("count", 0)
    day_count = day_stats["stats"].get(uid, {}).get("count", 0)

    ranking     = get_ranking(chat_stats)
    day_ranking = get_ranking(day_stats["stats"])

    my_rank     = next((r for r, n, _ in ranking     if n == chat_stats.get(uid, {}).get("name")), "-") if uid in chat_stats else "-"
    my_day_rank = next((r for r, n, _ in day_ranking if n == day_stats["stats"].get(uid, {}).get("name")), "-") if uid in day_stats["stats"] else "-"

    date_str = datetime.now(KST).strftime("%m월 %d일")
    text = (
        f"🎣 <b>도파민 가득 채윰</b>\n"
        f"\n"
        f"태그: <b>{html.escape(tag)}</b>\n"
        f"누적 순위: <b>{my_rank}위</b>  ·  <b>{count:,}회</b>\n"
        f"오늘({date_str}) 순위: <b>{my_day_rank}위</b>  ·  <b>{day_count:,}회</b>\n"
        f"\n"
        f"<i>💬 채윰이와 신나게 놀아요ฅᐢ..ᐢ₎♡</i>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ── 메시지 핸들러 ────────────────────────────────────────────

async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not message.sticker:
        return
    fuid = message.sticker.file_unique_id
    info = sticker_tags.get(fuid)
    if not info:
        return
    uid = info["user_id"]
    name = html.escape(info["name"])
    msg = html.escape(info["message"])
    mention = f'<a href="tg://user?id={uid}">{name}</a>'
    await message.reply_text(f"{mention} {msg}", parse_mode=ParseMode.HTML)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not message.text:
        return

    text = message.text.strip()
    user = message.from_user
    user_id = user.id
    username = user.full_name or user.username or str(user_id)

    if len(text) >= 3:
        now = time.time()
        if now - last_chat_time.get(user_id, 0) >= 1.0:
            last_chat_time[user_id] = now

            stats = chat_stats.setdefault(str(user_id), {"name": username, "count": 0})
            stats["name"] = username
            stats["count"] += 1
            save_chat_stats()

            ensure_day_reset()
            dstats = day_stats["stats"].setdefault(str(user_id), {"name": username, "count": 0})
            dstats["name"] = username
            dstats["count"] += 1
            save_day_stats()

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
                {"role": "system", "content": get_prompt()},
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

    app.job_queue.run_daily(
        job_midnight_ranking,
        time=dtime(hour=0, minute=0, second=0, tzinfo=KST),
    )

    app.add_handler(CommandHandler(["v1", "v2", "v3"], cmd_version))
    app.add_handler(CommandHandler("setchat",      cmd_setchat))
    app.add_handler(CommandHandler("setdayrank",   cmd_setdayrank))
    app.add_handler(CommandHandler("tagsticker",   cmd_tagsticker))
    app.add_handler(CommandHandler("untagsticker", cmd_untagsticker))
    app.add_handler(CommandHandler("stickerlist",  cmd_stickerlist))
    app.add_handler(CommandHandler("rank",         cmd_ranking))
    app.add_handler(CommandHandler("dayrank",      cmd_dayrank))
    app.add_handler(CallbackQueryHandler(callback_ranking, pattern=r"^(rank|dayrank)_"))
    app.add_handler(CommandHandler("my",           cmd_myinfo))
    app.add_handler(CommandHandler("draw",         cmd_draw))
    app.add_handler(CommandHandler("drawday",      cmd_drawday))
    app.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("핑구 bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
