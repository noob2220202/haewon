import asyncio
import json
import logging
import random
import re
import time
from aiogram import Router, F, Bot
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.filters import Command

import db
import formats
from config import get_cfg
from db import set_config
from formats import fmt_num

log = logging.getLogger(__name__)
router = Router()

# ── in-memory state ─────────────────────────────────────────────────────────
_cooldown: dict[int, float] = {}      # user_id -> expire_ts
_surprise: dict[int, bool] = {}       # msg_id   -> claimed
_known_chat_id: int | None = None     # 마지막 그룹 chat_id (정산 공지용)
_lotto_select: dict[int, set] = {}    # user_id -> 선택 중인 번호 set


# ── helpers ──────────────────────────────────────────────────────────────────

async def delete_after(bot: Bot, chat_id: int, msg_id: int, delay: int):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, msg_id)
    except Exception:
        pass


def _cleanup_cooldown():
    now = time.monotonic()
    expired = [uid for uid, ts in _cooldown.items() if ts < now]
    for uid in expired:
        del _cooldown[uid]


# ── message counting ──────────────────────────────────────────────────────────

@router.message(F.text & ~F.text.startswith("/"))
async def on_message(message: Message, bot: Bot):
    if not message.from_user:
        return
    if message.chat.type == "private":
        return

    cfg = await get_cfg()
    text = message.text or ""
    if len(text) < cfg["chat_min_len"]:
        return

    uid = message.from_user.id
    now = time.monotonic()

    if uid in _cooldown and _cooldown[uid] > now:
        return

    _cooldown[uid] = now + cfg["chat_cooldown_sec"]
    if len(_cooldown) > 5000:
        _cleanup_cooldown()

    username = message.from_user.username
    await db.increment_chat(uid, username)
    await _surprise_roll(message, bot, cfg)

    global _known_chat_id
    if _known_chat_id != message.chat.id:
        _known_chat_id = message.chat.id
        await set_config("group_chat_id", str(message.chat.id))


async def _surprise_roll(message: Message, bot: Bot, cfg: dict):
    if not cfg["surprise_enabled"]:
        return
    if random.random() >= cfg["surprise_chance"]:
        return

    pts = cfg["surprise_points"]
    expire = cfg["surprise_expire_sec"]
    autodelete = cfg["msg_autodelete_sec"]

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🎁 잡기!", callback_data="surprise_grab")
    ]])
    sent = await bot.send_message(
        message.chat.id,
        formats.surprise_appear(pts),
        parse_mode="HTML",
        reply_markup=kb,
    )
    _surprise[sent.message_id] = False

    async def expire_surprise():
        await asyncio.sleep(expire)
        if _surprise.get(sent.message_id) is False:
            try:
                await bot.delete_message(message.chat.id, sent.message_id)
            except Exception:
                pass
            _surprise.pop(sent.message_id, None)

    asyncio.create_task(expire_surprise())


# ── /내정보 ───────────────────────────────────────────────────────────────────

@router.message(Command("내정보"))
async def cmd_myinfo(message: Message, bot: Bot):
    cfg = await get_cfg()
    uid = message.from_user.id
    await bot.delete_message(message.chat.id, message.message_id)

    if message.chat.type == "private" and not await db.is_admin(uid):
        sent = await message.answer(formats.group_only(), parse_mode="HTML")
        asyncio.create_task(delete_after(bot, message.chat.id, sent.message_id, cfg["msg_autodelete_sec"]))
        return

    is_admin = await db.is_admin(uid)
    user = await db.get_user(uid)

    if user is None:
        sent = await message.answer("아직 채팅 기록이 없어요!", parse_mode="HTML")
    else:
        user = await db.get_user(uid)
        daily = await db.get_daily_count(uid)
        sent = await message.answer(
            formats.my_info(user["username"], daily, user["total_chat"], user["points"]),
            parse_mode="HTML",
        )
    asyncio.create_task(
        delete_after(bot, message.chat.id, sent.message_id, cfg["msg_autodelete_sec"])
    )


# ── /정보 (관리자: 타인 조회) ──────────────────────────────────────────────────

@router.message(Command("정보"))
async def cmd_info(message: Message, bot: Bot):
    cfg = await get_cfg()
    uid = message.from_user.id
    await bot.delete_message(message.chat.id, message.message_id)

    if not await db.is_admin(uid):
        sent = await message.answer(formats.no_permission(), parse_mode="HTML")
        asyncio.create_task(delete_after(bot, message.chat.id, sent.message_id, cfg["msg_autodelete_sec"]))
        return

    target = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target = await db.get_user(message.reply_to_message.from_user.id)
    else:
        args = message.text.split(maxsplit=1)
        if len(args) >= 2:
            name = args[1].lstrip("@")
            target = await db.get_user_by_username(name)

    if target is None:
        sent = await message.answer("❌ <i>유저를 찾을 수 없어요\n사용법: /정보 @유저명  또는 대상 메시지에 답장</i>", parse_mode="HTML")
        asyncio.create_task(delete_after(bot, message.chat.id, sent.message_id, cfg["msg_autodelete_sec"]))
        return

    daily = await db.get_daily_count(target["user_id"])
    sent = await message.answer(
        formats.my_info(target["username"], daily, target["total_chat"], target["points"]),
        parse_mode="HTML",
    )
    asyncio.create_task(delete_after(bot, message.chat.id, sent.message_id, cfg["msg_autodelete_sec"]))


# ── /랭크 ────────────────────────────────────────────────────────────────────

@router.message(Command("랭크"))
async def cmd_rank(message: Message, bot: Bot):
    cfg = await get_cfg()
    uid = message.from_user.id
    await bot.delete_message(message.chat.id, message.message_id)

    if not await db.is_admin(uid):
        sent = await message.answer(formats.no_permission(), parse_mode="HTML")
        asyncio.create_task(delete_after(bot, message.chat.id, sent.message_id, cfg["msg_autodelete_sec"]))
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📅 당일 랭킹", callback_data="rank_daily_0"),
        InlineKeyboardButton(text="🗂 누적 랭킹", callback_data="rank_total_0"),
    ]])
    await message.answer(formats.rank_select(), parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("rank_"))
async def cb_rank(cb: CallbackQuery):
    parts = cb.data.split("_")
    kind = parts[1]
    page = int(parts[2])

    per_page = 10
    offset = page * per_page

    if kind == "daily":
        rows_all = await db.get_daily_rank(limit=100)
        title = "📅 당일 랭킹"
        value_key = "chat_count"
    else:
        rows_all = await db.get_total_rank(limit=100)
        title = "🗂 누적 랭킹"
        value_key = "total_chat"

    total_pages = max(1, (len(rows_all) + per_page - 1) // per_page)
    rows = rows_all[offset: offset + per_page]

    text = formats.rank_page(title, rows, page, total_pages, value_key)

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀ 이전", callback_data=f"rank_{kind}_{page-1}"))
    nav_buttons.append(InlineKeyboardButton(text=f"{page+1} / {total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="다음 ▶", callback_data=f"rank_{kind}_{page+1}"))

    kb = InlineKeyboardMarkup(inline_keyboard=[nav_buttons])
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery):
    await cb.answer()


# ── 정산 페이지 ────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("settle_"))
async def cb_settle(cb: CallbackQuery):
    parts = cb.data.split("_")   # settle_{YYYYMMDD}_{page}
    ymd_compact = parts[1]
    page = int(parts[2])
    ymd = f"{ymd_compact[:4]}-{ymd_compact[4:6]}-{ymd_compact[6:]}"

    from scheduler import calc_settle_rewarded, _settle_kb, PER_PAGE
    rewarded_list = await calc_settle_rewarded(ymd)
    total_pages = max(1, (len(rewarded_list) + PER_PAGE - 1) // PER_PAGE)

    await cb.message.edit_text(
        formats.settle_page(rewarded_list, page, total_pages),
        parse_mode="HTML",
        reply_markup=_settle_kb(ymd_compact, page, total_pages),
    )
    await cb.answer()


# ── 돌발 버튼 ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "surprise_grab")
async def cb_surprise(cb: CallbackQuery, bot: Bot):
    cfg = await get_cfg()
    msg_id = cb.message.message_id

    if msg_id not in _surprise:
        await cb.answer("이미 끝났어요 😢", show_alert=False)
        return

    if _surprise[msg_id] is True:
        await cb.answer("이미 누군가 가져갔어요!", show_alert=False)
        return

    _surprise[msg_id] = True
    uid = cb.from_user.id
    username = cb.from_user.username
    pts = cfg["surprise_points"]

    await db.upsert_user(uid, username)
    await db.add_points(uid, pts, "surprise", "돌발포인트")

    winner_text = formats.surprise_winner(username, pts)
    await cb.message.edit_text(winner_text, parse_mode="HTML", reply_markup=None)
    await cb.answer(f"+{pts} P 획득! 🎉")

    asyncio.create_task(
        delete_after(bot, cb.message.chat.id, msg_id, cfg["msg_autodelete_sec"])
    )


# ── /추첨 ─────────────────────────────────────────────────────────────────────

@router.message(Command("추첨"))
async def cmd_lottery(message: Message, bot: Bot):
    cfg = await get_cfg()
    uid = message.from_user.id

    if not await db.is_admin(uid):
        sent = await message.answer(formats.no_permission(), parse_mode="HTML")
        await bot.delete_message(message.chat.id, message.message_id)
        asyncio.create_task(
            delete_after(bot, message.chat.id, sent.message_id, cfg["msg_autodelete_sec"])
        )
        return

    await bot.delete_message(message.chat.id, message.message_id)

    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        sent = await message.answer("사용법: /추첨 <등수>  예) /추첨 5", parse_mode="HTML")
        asyncio.create_task(
            delete_after(bot, message.chat.id, sent.message_id, cfg["msg_autodelete_sec"])
        )
        return

    n = int(args[1])
    rows = await db.get_daily_rank(limit=n)
    if not rows:
        sent = await message.answer("오늘 채팅 기록이 없어요!", parse_mode="HTML")
        asyncio.create_task(
            delete_after(bot, message.chat.id, sent.message_id, cfg["msg_autodelete_sec"])
        )
        return

    winner = random.choice(rows)
    await message.answer(
        formats.lottery_result(n, winner["username"]),
        parse_mode="HTML",
    )


# ── /출석 ─────────────────────────────────────────────────────────────────────

@router.message(Command("출석"))
async def cmd_checkin(message: Message, bot: Bot):
    cfg = await get_cfg()
    uid = message.from_user.id
    username = message.from_user.username
    await bot.delete_message(message.chat.id, message.message_id)

    if message.chat.type == "private" and not await db.is_admin(uid):
        sent = await message.answer(formats.group_only(), parse_mode="HTML")
        asyncio.create_task(delete_after(bot, message.chat.id, sent.message_id, cfg["msg_autodelete_sec"]))
        return

    if not cfg["checkin_enabled"]:
        sent = await message.answer("❌ <i>출석 체크가 비활성화되어 있어요</i>", parse_mode="HTML")
        asyncio.create_task(delete_after(bot, message.chat.id, sent.message_id, cfg["msg_autodelete_sec"]))
        return

    pts = cfg["checkin_points"]
    success = await db.check_in(uid, username)
    if success:
        await db.add_points(uid, pts, "checkin", "출석 체크")
        sent = await message.answer(formats.checkin_success(username, pts), parse_mode="HTML")
    else:
        sent = await message.answer(formats.checkin_already(username), parse_mode="HTML")
    asyncio.create_task(delete_after(bot, message.chat.id, sent.message_id, cfg["msg_autodelete_sec"]))


# ── /당근 /채찍 (관리자 포인트 지급/차감) ────────────────────────────────────────

async def _point_cmd(message: Message, bot: Bot, is_add: bool):
    cfg = await get_cfg()
    uid = message.from_user.id

    if not await db.is_admin(uid):
        sent = await message.answer(formats.no_permission(), parse_mode="HTML")
        await bot.delete_message(message.chat.id, message.message_id)
        asyncio.create_task(delete_after(bot, message.chat.id, sent.message_id, cfg["msg_autodelete_sec"]))
        return

    await bot.delete_message(message.chat.id, message.message_id)

    cmd = "/당근" if is_add else "/채찍"
    args = message.text.split(maxsplit=3)

    # 모드 1: /당근 @태그|유저ID 개수 [사유]
    if len(args) >= 3 and (args[1].startswith("@") or args[1].isdigit()):
        target_arg = args[1]
        if not args[2].isdigit():
            sent = await message.answer(f"❌ <i>사용법: {cmd} @태그/고번 개수 사유</i>", parse_mode="HTML")
            asyncio.create_task(delete_after(bot, message.chat.id, sent.message_id, cfg["msg_autodelete_sec"]))
            return
        amount = int(args[2])
        memo = args[3] if len(args) >= 4 else ""

        if target_arg.isdigit():
            target_row = await db.get_user(int(target_arg))
        else:
            target_row = await db.get_user_by_username(target_arg.lstrip("@"))

        if not target_row:
            sent = await message.answer("❌ <i>유저를 찾을 수 없어요. 먼저 채팅방에서 대화한 유저만 조회됩니다.</i>", parse_mode="HTML")
            asyncio.create_task(delete_after(bot, message.chat.id, sent.message_id, cfg["msg_autodelete_sec"]))
            return

        target_id = target_row["user_id"]
        target_username = target_row["username"]

    # 모드 2: 답장 + /당근 개수 [사유]  (기존 방식)
    elif message.reply_to_message and message.reply_to_message.from_user:
        if len(args) < 2 or not args[1].isdigit():
            sent = await message.answer(f"❌ <i>사용법: {cmd} 숫자 사유</i>", parse_mode="HTML")
            asyncio.create_task(delete_after(bot, message.chat.id, sent.message_id, cfg["msg_autodelete_sec"]))
            return
        amount = int(args[1])
        memo = args[2] if len(args) >= 3 else ""
        target = message.reply_to_message.from_user
        await db.upsert_user(target.id, target.username)
        target_id = target.id
        target_username = target.username

    else:
        sent = await message.answer(
            f"❌ <i>사용법:\n{cmd} @태그/고번 개수 사유\n또는 메시지에 답장 후 {cmd} 개수 사유</i>",
            parse_mode="HTML",
        )
        asyncio.create_task(delete_after(bot, message.chat.id, sent.message_id, cfg["msg_autodelete_sec"]))
        return

    delta = amount if is_add else -amount
    await db.add_points(target_id, delta, "admin_edit", memo)

    sent = await message.answer(
        formats.point_cmd_result(target_username, delta, memo),
        parse_mode="HTML",
    )
    asyncio.create_task(delete_after(bot, message.chat.id, sent.message_id, cfg["msg_autodelete_sec"]))


@router.message(Command("당근"))
async def cmd_carrot(message: Message, bot: Bot):
    await _point_cmd(message, bot, is_add=True)


@router.message(Command("채찍"))
async def cmd_whip(message: Message, bot: Bot):
    await _point_cmd(message, bot, is_add=False)


# ── /로또 ─────────────────────────────────────────────────────────────────────

def _lotto_main_kb(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 당첨금 현황", callback_data=f"ltp_{uid}"),
            InlineKeyboardButton(text="🎫 내 티켓", callback_data=f"ltmt_{uid}"),
        ],
        [InlineKeyboardButton(text="🎰 구매하기", callback_data=f"ltb_{uid}")],
    ])


def _lotto_kb(uid: int, selected: set) -> InlineKeyboardMarkup:
    rows = []
    for row_start in range(1, 21, 5):
        row = []
        for n in range(row_start, row_start + 5):
            label = f"✅{n}" if n in selected else str(n)
            row.append(InlineKeyboardButton(text=label, callback_data=f"ltn_{uid}_{n}"))
        rows.append(row)
    cnt = len(selected)
    go_text = f"넘어가기 ({cnt}/5)" if cnt < 5 else "✅ 넘어가기"
    rows.append([InlineKeyboardButton(text=go_text, callback_data=f"ltg_{uid}")])
    rows.append([InlineKeyboardButton(text="◀ 뒤로", callback_data=f"ltc_{uid}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _lotto_main_text_kb(uid: int, cfg: dict):
    draw = await db.lotto_get_or_create_open_draw()
    ticket_count = await db.lotto_count_user_tickets(draw["id"], uid)
    user = await db.get_user(uid)
    balance = user["points"] if user else 0
    text = formats.lotto_main(ticket_count, balance, cfg["lotto_price"], draw["jackpot"], draw["pool"], draw["id"])
    return text, _lotto_main_kb(uid)


@router.message(Command("로또"))
async def cmd_lotto(message: Message, bot: Bot):
    if message.chat.type != "private":
        try:
            await bot.delete_message(message.chat.id, message.message_id)
        except Exception:
            pass
        sent = await message.answer("❌ 로또는 개인 DM에서만 사용 가능합니다.")
        asyncio.create_task(delete_after(bot, message.chat.id, sent.message_id, 5))
        return

    cfg = await get_cfg()
    if not cfg["lotto_enabled"]:
        await message.answer("❌ 로또가 비활성화되어 있습니다.")
        return

    uid = message.from_user.id
    await db.upsert_user(uid, message.from_user.username)

    text, kb = await _lotto_main_text_kb(uid, cfg)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


_RE_LTP  = re.compile(r"^ltp_(\d+)$")
_RE_LTMT = re.compile(r"^ltmt_(\d+)$")
_RE_LTB  = re.compile(r"^ltb_(\d+)$")
_RE_LTA  = re.compile(r"^lta_(\d+)$")
_RE_LTN  = re.compile(r"^ltn_(\d+)_(\d+)$")
_RE_LTG  = re.compile(r"^ltg_(\d+)$")
_RE_LTC  = re.compile(r"^ltc_(\d+)$")


@router.callback_query(F.data.regexp(_RE_LTP))
async def cb_lotto_prize(cb: CallbackQuery, bot: Bot):
    uid = int(_RE_LTP.match(cb.data).group(1))
    if cb.from_user.id != uid:
        await cb.answer("본인만 사용 가능합니다 🚫", show_alert=True)
        return

    cfg = await get_cfg()
    draw = await db.lotto_get_or_create_open_draw()
    text = formats.lotto_prize_info(
        draw["jackpot"], draw["pool"], cfg["lotto_price"],
        cfg["lotto_prize_mode"],
        cfg["lotto_prize_3_fixed"], cfg["lotto_prize_4_fixed"], cfg["lotto_prize_5_fixed"],
        cfg["lotto_prize_3_pct"], cfg["lotto_prize_4_pct"], cfg["lotto_prize_5_pct"],
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="◀ 뒤로", callback_data=f"ltc_{uid}")
    ]])
    await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.regexp(_RE_LTMT))
async def cb_lotto_my_tickets(cb: CallbackQuery, bot: Bot):
    uid = int(_RE_LTMT.match(cb.data).group(1))
    if cb.from_user.id != uid:
        await cb.answer("본인만 사용 가능합니다 🚫", show_alert=True)
        return

    draw = await db.lotto_get_or_create_open_draw()
    tickets = await db.lotto_get_user_tickets(draw["id"], uid)
    text = formats.lotto_my_tickets(tickets, draw["id"])
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="◀ 뒤로", callback_data=f"ltc_{uid}")
    ]])
    await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.regexp(_RE_LTB))
async def cb_lotto_buy(cb: CallbackQuery, bot: Bot):
    uid = int(_RE_LTB.match(cb.data).group(1))
    if cb.from_user.id != uid:
        await cb.answer("본인만 사용 가능합니다 🚫", show_alert=True)
        return

    cfg = await get_cfg()
    if not cfg["lotto_enabled"]:
        await cb.answer("로또가 비활성화되어 있습니다.", show_alert=True)
        return

    draw = await db.lotto_get_or_create_open_draw()
    bought = await db.lotto_count_user_tickets(draw["id"], uid)
    if bought >= cfg["lotto_max_per_draw"]:
        await cb.answer(f"이번 회차 최대 {cfg['lotto_max_per_draw']}장까지 구매 가능합니다.", show_alert=True)
        return

    user = await db.get_user(uid)
    balance = user["points"] if user else 0
    if balance < cfg["lotto_price"]:
        await cb.answer(f"당근이 부족합니다. (잔액: {balance:,}🥕)", show_alert=True)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🤖 자동 선택", callback_data=f"lta_{uid}"),
            InlineKeyboardButton(text="✍️ 수동 선택", callback_data=f"ltm_{uid}"),
        ],
        [InlineKeyboardButton(text="◀ 뒤로", callback_data=f"ltc_{uid}")],
    ])
    await cb.message.edit_text(
        formats.lotto_buy_menu(balance, cfg["lotto_price"], bought, cfg["lotto_max_per_draw"]),
        reply_markup=kb,
        parse_mode="HTML",
    )
    await cb.answer()


_RE_LTM = re.compile(r"^ltm_(\d+)$")


@router.callback_query(F.data.regexp(_RE_LTM))
async def cb_lotto_manual(cb: CallbackQuery, bot: Bot):
    uid = int(_RE_LTM.match(cb.data).group(1))
    if cb.from_user.id != uid:
        await cb.answer("본인만 사용 가능합니다 🚫", show_alert=True)
        return

    cfg = await get_cfg()
    draw = await db.lotto_get_or_create_open_draw()
    bought = await db.lotto_count_user_tickets(draw["id"], uid)
    _lotto_select[uid] = set()
    await cb.message.edit_text(
        formats.lotto_select_prompt(set(), cfg["lotto_price"], cfg["lotto_max_per_draw"], bought),
        reply_markup=_lotto_kb(uid, set()),
        parse_mode="HTML",
    )
    await cb.answer()


_RE_LTAQ = re.compile(r"^ltaq_(\d+)_(\d+)$")


@router.callback_query(F.data.regexp(_RE_LTA))
async def cb_lotto_auto(cb: CallbackQuery, bot: Bot):
    """자동구매 수량 선택 화면"""
    uid = int(_RE_LTA.match(cb.data).group(1))
    if cb.from_user.id != uid:
        await cb.answer("본인만 사용 가능합니다 🚫", show_alert=True)
        return

    cfg = await get_cfg()
    draw = await db.lotto_get_or_create_open_draw()
    if not draw or draw["status"] != "open":
        await cb.answer("현재 진행 중인 회차가 없습니다.", show_alert=True)
        return

    bought = await db.lotto_count_user_tickets(draw["id"], uid)
    remain = cfg["lotto_max_per_draw"] - bought
    if remain <= 0:
        await cb.answer(f"이번 회차 최대 {cfg['lotto_max_per_draw']}장까지 구매 가능합니다.", show_alert=True)
        return

    user = await db.get_user(uid)
    balance = user["points"] if user else 0
    price = cfg["lotto_price"]
    if balance < price:
        await cb.answer(f"당근이 부족합니다. (잔액: {balance:,}🥕)", show_alert=True)
        return

    max_afford = balance // price
    can_buy = min(remain, max_afford)

    candidates = [1, 3, 5, 10]
    qty_row = [
        InlineKeyboardButton(text=f"{n}장", callback_data=f"ltaq_{uid}_{n}")
        for n in candidates if n <= can_buy
    ]
    if can_buy not in candidates and can_buy > 0:
        qty_row.append(InlineKeyboardButton(text=f"최대 {can_buy}장", callback_data=f"ltaq_{uid}_{can_buy}"))
    elif can_buy > 0 and can_buy == candidates[-1]:
        qty_row.append(InlineKeyboardButton(text=f"최대 {can_buy}장", callback_data=f"ltaq_{uid}_{can_buy}"))

    kb = InlineKeyboardMarkup(inline_keyboard=[
        qty_row,
        [InlineKeyboardButton(text="◀ 뒤로", callback_data=f"ltb_{uid}")],
    ])
    await cb.message.edit_text(
        formats.lotto_auto_qty_menu(balance, price, remain),
        reply_markup=kb,
        parse_mode="HTML",
    )
    await cb.answer()


@router.callback_query(F.data.regexp(_RE_LTAQ))
async def cb_lotto_auto_qty(cb: CallbackQuery, bot: Bot):
    """자동구매 N장 실행"""
    m = _RE_LTAQ.match(cb.data)
    uid, count = int(m.group(1)), int(m.group(2))
    if cb.from_user.id != uid:
        await cb.answer("본인만 사용 가능합니다 🚫", show_alert=True)
        return

    cfg = await get_cfg()
    draw = await db.lotto_get_or_create_open_draw()
    if not draw or draw["status"] != "open":
        await cb.answer("현재 진행 중인 회차가 없습니다.", show_alert=True)
        return

    bought = await db.lotto_count_user_tickets(draw["id"], uid)
    remain = cfg["lotto_max_per_draw"] - bought
    price = cfg["lotto_price"]
    user = await db.get_user(uid)
    balance = user["points"] if user else 0

    actual = min(count, remain, balance // price)
    if actual <= 0:
        await cb.answer("구매할 수 없습니다. (잔액 또는 한도 초과)", show_alert=True)
        return

    tickets_bought = []
    for _ in range(actual):
        nums = sorted(random.sample(range(1, 21), 5))
        await db.add_points(uid, -price, "lotto_buy", f"draw#{draw['id']}")
        await db.lotto_buy_ticket(draw["id"], uid, nums)
        await db.lotto_add_pool(draw["id"], price)
        tickets_bought.append(nums)

    lines = [
        f"<blockquote>✅ <b>자동구매 완료  {actual}장</b></blockquote>",
        f"💰 잔여 당근: <b>{fmt_num(balance - price * actual)}🥕</b>",
        "",
    ]
    for i, nums in enumerate(tickets_bought, 1):
        lines.append(f"  {i}. <b>{' · '.join(str(n) for n in nums)}</b>")
    lines.append("\n<i>추첨은 매일 자정에 진행됩니다 🌙</i>")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 추가 구매", callback_data=f"ltb_{uid}")],
        [InlineKeyboardButton(text="◀ 처음으로", callback_data=f"ltc_{uid}")],
    ])
    await cb.message.edit_text("\n".join(lines), reply_markup=kb, parse_mode="HTML")
    await cb.answer(f"✅ {actual}장 구매 완료!")


@router.callback_query(F.data.regexp(_RE_LTN))
async def cb_lotto_num(cb: CallbackQuery, bot: Bot):
    m = _RE_LTN.match(cb.data)
    uid, num = int(m.group(1)), int(m.group(2))
    if cb.from_user.id != uid:
        await cb.answer("본인만 사용 가능합니다 🚫", show_alert=True)
        return

    sel = _lotto_select.get(uid, set())
    if num in sel:
        sel.discard(num)
    elif len(sel) < 5:
        sel.add(num)
    else:
        await cb.answer("이미 5개 선택됐어요!", show_alert=True)
        return
    _lotto_select[uid] = sel

    cfg = await get_cfg()
    draw = await db.lotto_get_or_create_open_draw()
    bought = await db.lotto_count_user_tickets(draw["id"], uid)
    try:
        await cb.message.edit_text(
            formats.lotto_select_prompt(sel, cfg["lotto_price"], cfg["lotto_max_per_draw"], bought),
            reply_markup=_lotto_kb(uid, sel),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await cb.answer(f"{len(sel)}/5 선택")


@router.callback_query(F.data.regexp(_RE_LTG))
async def cb_lotto_go(cb: CallbackQuery, bot: Bot):
    uid = int(_RE_LTG.match(cb.data).group(1))
    if cb.from_user.id != uid:
        await cb.answer("본인만 사용 가능합니다 🚫", show_alert=True)
        return

    sel = _lotto_select.get(uid)
    if not sel or len(sel) != 5:
        await cb.answer("번호 5개를 선택해주세요!", show_alert=True)
        return

    cfg = await get_cfg()
    draw = await db.lotto_get_or_create_open_draw()
    if not draw or draw["status"] != "open":
        await cb.answer("현재 진행 중인 회차가 없습니다.", show_alert=True)
        return

    bought = await db.lotto_count_user_tickets(draw["id"], uid)
    if bought >= cfg["lotto_max_per_draw"]:
        await cb.answer(f"이번 회차 최대 {cfg['lotto_max_per_draw']}장까지 구매 가능합니다.", show_alert=True)
        return

    user = await db.get_user(uid)
    balance = user["points"] if user else 0
    price = cfg["lotto_price"]
    if balance < price:
        await cb.answer(f"당근이 부족합니다. (잔액: {balance:,}🥕)", show_alert=True)
        return

    sorted_nums = sorted(sel)
    await db.add_points(uid, -price, "lotto_buy", f"draw#{draw['id']}")
    await db.lotto_buy_ticket(draw["id"], uid, sorted_nums)
    await db.lotto_add_pool(draw["id"], price)
    _lotto_select.pop(uid, None)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 한 장 더", callback_data=f"ltb_{uid}")],
        [InlineKeyboardButton(text="◀ 처음으로", callback_data=f"ltc_{uid}")],
    ])
    await cb.message.edit_text(
        formats.lotto_bought(sorted_nums, balance - price, draw["id"]),
        reply_markup=kb,
        parse_mode="HTML",
    )
    await cb.answer("✅ 구매 완료!")


@router.callback_query(F.data.regexp(_RE_LTC))
async def cb_lotto_back(cb: CallbackQuery, bot: Bot):
    uid = int(_RE_LTC.match(cb.data).group(1))
    if cb.from_user.id != uid:
        await cb.answer("본인만 사용 가능합니다 🚫", show_alert=True)
        return

    _lotto_select.pop(uid, None)
    cfg = await get_cfg()
    text, kb = await _lotto_main_text_kb(uid, cfg)
    await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await cb.answer()
