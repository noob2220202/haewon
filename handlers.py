import asyncio
import logging
import random
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

log = logging.getLogger(__name__)
router = Router()

# ── in-memory state ─────────────────────────────────────────────────────────
_cooldown: dict[int, float] = {}      # user_id -> expire_ts
_surprise: dict[int, bool] = {}       # msg_id   -> claimed


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
        if not is_admin:
            await db.add_points(uid, -5, "info_view", "/내정보 조회")
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

    if message.chat.type == "private" and not await db.is_admin(uid):
        sent = await message.answer(formats.group_only(), parse_mode="HTML")
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

    if not message.reply_to_message or not message.reply_to_message.from_user:
        sent = await message.answer("❌ <i>대상의 메시지에 답장으로 사용해줘요</i>", parse_mode="HTML")
        asyncio.create_task(delete_after(bot, message.chat.id, sent.message_id, cfg["msg_autodelete_sec"]))
        return

    args = message.text.split(maxsplit=2)
    if len(args) < 2 or not args[1].isdigit():
        cmd = "/당근" if is_add else "/채찍"
        sent = await message.answer(f"❌ <i>사용법: {cmd} 숫자 사유</i>", parse_mode="HTML")
        asyncio.create_task(delete_after(bot, message.chat.id, sent.message_id, cfg["msg_autodelete_sec"]))
        return

    amount = int(args[1])
    memo = args[2] if len(args) >= 3 else ""
    target = message.reply_to_message.from_user
    delta = amount if is_add else -amount

    await db.upsert_user(target.id, target.username)
    await db.add_points(target.id, delta, "admin_edit", memo)

    sent = await message.answer(
        formats.point_cmd_result(target.username, delta, memo),
        parse_mode="HTML",
    )
    asyncio.create_task(delete_after(bot, message.chat.id, sent.message_id, cfg["msg_autodelete_sec"]))


@router.message(Command("당근"))
async def cmd_carrot(message: Message, bot: Bot):
    await _point_cmd(message, bot, is_add=True)


@router.message(Command("채찍"))
async def cmd_whip(message: Message, bot: Bot):
    await _point_cmd(message, bot, is_add=False)
