"""바카라봇 핸들러 및 FSM."""

import asyncio
import logging
import os
import sys
import re

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import db
from . import formats as fmt
from . import scheduler

log = logging.getLogger(__name__)
router = Router()

BACCARAT_GROUP_ID = int(os.environ.get("BACCARAT_GROUP_ID", "0"))


class BetFlow(StatesGroup):
    waiting_amount = State()


async def _delete_after(bot: Bot, chat_id: int, msg_id: int, delay: int = 5):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, msg_id)
    except Exception:
        pass


async def _reply_del(message: Message, bot: Bot, text: str, delay: int = 5) -> Message:
    sent = await message.reply(text, parse_mode="HTML")
    asyncio.create_task(_delete_after(bot, message.chat.id, sent.message_id, delay))
    asyncio.create_task(_delete_after(bot, message.chat.id, message.message_id, delay))
    return sent


# ── /베팅 ─────────────────────────────────────────────────────────────────

@router.message(Command("베팅"))
async def cmd_bet(message: Message, state: FSMContext, bot: Bot):
    if message.chat.type == "private":
        await _reply_del(message, bot, "❌ 그룹 채팅에서만 사용할 수 있어요.")
        return

    await db.upsert_user(message.from_user.id, message.from_user.username)

    # 현재 활성 회차 확인
    round_row = await db.baccarat_get_active_round()

    if not round_row:
        # 게임이 idle 상태 → 시작
        await scheduler.start_game(bot, message.chat.id)
        await asyncio.sleep(0.2)
        round_row = await db.baccarat_get_active_round()

    if not round_row:
        await _reply_del(message, bot, "❌ 베팅 회차를 시작하지 못했어요. 잠시 후 다시 시도해주세요.")
        return

    # 이미 베팅했는지 확인
    existing = await db.baccarat_get_user_bet(round_row["id"], message.from_user.id)
    if existing:
        side_kor = {"player": "플레이어", "banker": "뱅커", "tie": "타이"}[existing["side"]]
        await _reply_del(message, bot, f"이미 <b>{side_kor}</b>에 <b>{existing['amount']:,}🥕</b> 베팅하셨어요!")
        return

    # 기존 FSM 상태 초기화
    await state.clear()

    uid = message.from_user.id
    round_id = round_row["id"]

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔴 플레이어 (2배)", callback_data=f"bet_player_{uid}_{round_id}"),
        InlineKeyboardButton(text="🟢 타이 (6배)",    callback_data=f"bet_tie_{uid}_{round_id}"),
        InlineKeyboardButton(text="🔵 뱅커 (1.95배)", callback_data=f"bet_banker_{uid}_{round_id}"),
    ]])

    sent = await message.reply(fmt.bet_select_prompt(), reply_markup=kb)
    await state.update_data(
        prompt_msg_id=sent.message_id,
        cmd_msg_id=message.message_id,
        round_id=round_id,
        chat_id=message.chat.id,
    )

    # 30초 후 메시지 + 명령어 자동 삭제 (FSM 타임아웃 역할도 겸함)
    asyncio.create_task(_delete_after(bot, message.chat.id, sent.message_id, 30))
    asyncio.create_task(_delete_after(bot, message.chat.id, message.message_id, 5))


# ── 사이드 선택 콜백 ──────────────────────────────────────────────────────

_BET_PATTERN = re.compile(r"^bet_(player|tie|banker)_(\d+)_(\d+)$")


@router.callback_query(F.data.regexp(_BET_PATTERN))
async def cb_select_side(cb: CallbackQuery, state: FSMContext, bot: Bot):
    m = _BET_PATTERN.match(cb.data)
    side, owner_id, round_id = m.group(1), int(m.group(2)), int(m.group(3))

    if cb.from_user.id != owner_id:
        await cb.answer("본인만 사용 가능합니다 🚫", show_alert=True)
        return

    # 회차 상태 재확인
    round_row = await db.baccarat_get_round(round_id)
    if not round_row or round_row["status"] != "betting":
        await cb.answer("베팅 기간이 종료됐어요 ⛔", show_alert=True)
        try:
            await cb.message.delete()
        except Exception:
            pass
        await state.clear()
        return

    # 이미 베팅 여부 재확인
    existing = await db.baccarat_get_user_bet(round_id, cb.from_user.id)
    if existing:
        await cb.answer("이미 베팅하셨어요!", show_alert=True)
        try:
            await cb.message.delete()
        except Exception:
            pass
        await state.clear()
        return

    balance = 0
    user_row = await db.get_user(cb.from_user.id)
    if user_row:
        balance = user_row["points"]

    await state.update_data(selected_side=side, round_id=round_id, chat_id=cb.message.chat.id)
    await state.set_state(BetFlow.waiting_amount)

    await cb.message.edit_text(
        fmt.bet_side_selected(side, balance),
        parse_mode="HTML",
    )
    await cb.answer()


# ── 금액 입력 ─────────────────────────────────────────────────────────────

@router.message(BetFlow.waiting_amount, F.text)
async def receive_amount(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    chat_id = data.get("chat_id", message.chat.id)
    round_id = data.get("round_id")

    # 회차 상태 재확인
    round_row = await db.baccarat_get_round(round_id) if round_id else None
    if not round_row or round_row["status"] != "betting":
        await state.clear()
        sent = await message.reply("❌ 베팅 기간이 종료됐어요.")
        asyncio.create_task(_delete_after(bot, chat_id, sent.message_id, 5))
        asyncio.create_task(_delete_after(bot, chat_id, message.message_id, 5))
        return

    # 금액 파싱
    raw = message.text.strip().replace(",", "").replace("🥕", "")
    if not raw.isdigit():
        sent = await message.reply(fmt.bet_error("숫자를 입력해주세요. (예: 1000)"))
        asyncio.create_task(_delete_after(bot, chat_id, sent.message_id, 5))
        asyncio.create_task(_delete_after(bot, chat_id, message.message_id, 5))
        return

    amount = int(raw)

    # 설정값 가져오기
    cfg_raw = await db.get_config_raw()
    min_bet = int(cfg_raw.get("baccarat_min_bet", "100"))
    max_bet = int(cfg_raw.get("baccarat_max_bet", "0"))

    if amount < min_bet:
        sent = await message.reply(fmt.bet_error(f"최소 베팅 금액은 <b>{min_bet:,}🥕</b>입니다."), parse_mode="HTML")
        asyncio.create_task(_delete_after(bot, chat_id, sent.message_id, 5))
        asyncio.create_task(_delete_after(bot, chat_id, message.message_id, 5))
        return

    if max_bet > 0 and amount > max_bet:
        sent = await message.reply(fmt.bet_error(f"최대 베팅 금액은 <b>{max_bet:,}🥕</b>입니다."), parse_mode="HTML")
        asyncio.create_task(_delete_after(bot, chat_id, sent.message_id, 5))
        asyncio.create_task(_delete_after(bot, chat_id, message.message_id, 5))
        return

    user_row = await db.get_user(message.from_user.id)
    balance = user_row["points"] if user_row else 0

    if amount > balance:
        sent = await message.reply(fmt.bet_error(f"잔액이 부족해요. 현재 잔액: <b>{balance:,}🥕</b>"), parse_mode="HTML")
        asyncio.create_task(_delete_after(bot, chat_id, sent.message_id, 5))
        asyncio.create_task(_delete_after(bot, chat_id, message.message_id, 5))
        return

    side = data["selected_side"]

    # 포인트 차감 먼저 (실패 시 중단)
    await db.add_points(message.from_user.id, -amount, "baccarat_bet", f"round#{round_id}")

    # 베팅 등록
    ok = await db.baccarat_place_bet(round_id, message.from_user.id, side, amount)
    if not ok:
        # 중복 베팅 → 포인트 환불
        await db.add_points(message.from_user.id, amount, "baccarat_refund", f"duplicate round#{round_id}")
        sent = await message.reply("❌ 이미 베팅하셨거나 오류가 발생했어요.")
        asyncio.create_task(_delete_after(bot, chat_id, sent.message_id, 5))
        asyncio.create_task(_delete_after(bot, chat_id, message.message_id, 5))
        await state.clear()
        return

    await state.clear()

    # 성공 응답
    sent = await message.reply(fmt.bet_success(side, amount), parse_mode="HTML")
    asyncio.create_task(_delete_after(bot, chat_id, sent.message_id, 5))
    asyncio.create_task(_delete_after(bot, chat_id, message.message_id, 5))

    # 핀 캡션 업데이트
    asyncio.create_task(
        scheduler.update_pin_after_bet(bot, chat_id, round_id)
    )
