"""바카라봇 핸들러."""

import asyncio
import logging
import os
import re
import sys

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db
from . import formats as fmt
from . import scheduler

log = logging.getLogger(__name__)
router = Router()


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


# ── /베팅 <금액> ──────────────────────────────────────────────────────────

@router.message(Command("베팅"))
async def cmd_bet(message: Message, bot: Bot):
    if message.chat.type == "private":
        await _reply_del(message, bot, "❌ 그룹 채팅에서만 사용할 수 있어요.")
        return

    # 금액 파싱
    args = (message.text or "").split()[1:]
    if not args:
        await _reply_del(message, bot, "사용법: <b>/베팅 1000</b>", delay=7)
        return

    raw = args[0].replace(",", "").replace("🥕", "")
    if not raw.isdigit():
        await _reply_del(message, bot, fmt.bet_error("숫자로 금액을 입력하세요. 예) /베팅 1000"))
        return

    amount = int(raw)

    cfg_raw = await db.get_config_raw()
    min_bet = int(cfg_raw.get("baccarat_min_bet", "100"))
    max_bet = int(cfg_raw.get("baccarat_max_bet", "0"))

    if amount < min_bet:
        await _reply_del(message, bot, fmt.bet_error(f"최소 베팅 금액은 <b>{min_bet:,}🥕</b>입니다."))
        return
    if max_bet > 0 and amount > max_bet:
        await _reply_del(message, bot, fmt.bet_error(f"최대 베팅 금액은 <b>{max_bet:,}🥕</b>입니다."))
        return

    await db.upsert_user(message.from_user.id, message.from_user.username)

    user_row = await db.get_user(message.from_user.id)
    balance = user_row["points"] if user_row else 0
    if amount > balance:
        await _reply_del(message, bot, fmt.bet_error(f"잔액 부족. 현재 잔액: <b>{balance:,}🥕</b>"))
        return

    # 활성 회차 확인 (없으면 게임 시작)
    round_row = await db.baccarat_get_active_round()
    if not round_row:
        await scheduler.start_game(bot, message.chat.id)
        await asyncio.sleep(0.3)
        round_row = await db.baccarat_get_active_round()

    if not round_row:
        await _reply_del(message, bot, "❌ 회차를 시작하지 못했어요. 잠시 후 다시 시도해주세요.")
        return

    # 이미 베팅했으면 안내
    existing = await db.baccarat_get_user_bet(round_row["id"], message.from_user.id)
    if existing:
        kor = {"player": "플레이어", "banker": "뱅커", "tie": "타이"}[existing["side"]]
        await _reply_del(message, bot, f"이미 <b>{kor}</b>에 <b>{existing['amount']:,}🥕</b> 베팅하셨어요!")
        return

    uid = message.from_user.id
    round_id = round_row["id"]

    # 금액을 callback_data에 인코딩 → 버튼 클릭만으로 즉시 베팅
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text=f"🔵 플레이어  ×2.0",
            callback_data=f"bv2_{uid}_{round_id}_{amount}_player",
        ),
        InlineKeyboardButton(
            text=f"🟢 타이  ×6.0",
            callback_data=f"bv2_{uid}_{round_id}_{amount}_tie",
        ),
        InlineKeyboardButton(
            text=f"🔴 뱅커  ×1.95",
            callback_data=f"bv2_{uid}_{round_id}_{amount}_banker",
        ),
    ]])

    sent = await message.reply(
        fmt.bet_select_prompt(amount, balance),
        reply_markup=kb,
        parse_mode="HTML",
    )
    # 30초 후 버튼 메시지 자동 삭제
    asyncio.create_task(_delete_after(bot, message.chat.id, sent.message_id, 30))
    asyncio.create_task(_delete_after(bot, message.chat.id, message.message_id, 5))


# ── 사이드 선택 콜백 (즉시 베팅) ─────────────────────────────────────────

_BET_V2 = re.compile(r"^bv2_(\d+)_(\d+)_(\d+)_(player|tie|banker)$")


@router.callback_query(F.data.regexp(_BET_V2))
async def cb_place_bet(cb: CallbackQuery, bot: Bot):
    m = _BET_V2.match(cb.data)
    owner_id, round_id, amount, side = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)

    # 본인 확인
    if cb.from_user.id != owner_id:
        await cb.answer("본인만 사용 가능합니다 🚫", show_alert=True)
        return

    # 회차 상태 확인
    round_row = await db.baccarat_get_round(round_id)
    if not round_row or round_row["status"] != "betting":
        await cb.answer("베팅 기간이 종료됐어요 ⛔", show_alert=True)
        try:
            await cb.message.delete()
        except Exception:
            pass
        return

    # 중복 베팅 확인
    existing = await db.baccarat_get_user_bet(round_id, cb.from_user.id)
    if existing:
        await cb.answer("이미 베팅하셨어요!", show_alert=True)
        try:
            await cb.message.delete()
        except Exception:
            pass
        return

    # 잔액 재확인
    user_row = await db.get_user(cb.from_user.id)
    balance = user_row["points"] if user_row else 0
    if amount > balance:
        await cb.answer(f"잔액 부족 ({balance:,}🥕)", show_alert=True)
        return

    # 포인트 차감 + 베팅 등록
    await db.add_points(cb.from_user.id, -amount, "baccarat_bet", f"round#{round_id}")
    ok = await db.baccarat_place_bet(round_id, cb.from_user.id, side, amount)
    if not ok:
        # 중복 race condition → 환불
        await db.add_points(cb.from_user.id, amount, "baccarat_refund", f"dup round#{round_id}")
        await cb.answer("이미 베팅하셨거나 오류가 발생했어요.", show_alert=True)
        try:
            await cb.message.delete()
        except Exception:
            pass
        return

    # 성공: 메시지 교체 후 5초 뒤 삭제
    await cb.message.edit_text(fmt.bet_success(side, amount), parse_mode="HTML")
    asyncio.create_task(_delete_after(bot, cb.message.chat.id, cb.message.message_id, 5))
    await cb.answer()

    # 핀 캡션 업데이트
    asyncio.create_task(
        scheduler.update_pin_after_bet(bot, cb.message.chat.id, round_id)
    )
