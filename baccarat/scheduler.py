"""바카라 게임 루프 (asyncio Task 기반)."""

import asyncio
import logging
import os
import sys

from aiogram import Bot
from aiogram.types import BufferedInputFile, InputMediaPhoto

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import db
from . import game as gm
from . import formats as fmt
from .road import generate_road_image

log = logging.getLogger(__name__)

ROUND_BET_SEC    = 110   # 베팅 창 (초)
COUNTDOWN_SEC    = 10    # 마감 카운트다운
DICE_DELAY_SEC   = 4     # 주사위당 애니메이션 대기
RESULT_PAUSE_SEC = 15    # 결과 공지 후 다음 라운드 전 대기

_state: dict = {
    "active": False,
    "task": None,
    "round_id": None,
    "chat_id": None,
    "thread_id": None,
}


def get_state() -> dict:
    return _state


async def start_game(bot: Bot, chat_id: int, thread_id: int | None = None):
    """idle 상태에서 게임 시작. 이미 실행 중이면 무시."""
    if _state["active"]:
        return
    _state["active"] = True
    _state["chat_id"] = chat_id
    _state["thread_id"] = thread_id
    round_id = await db.baccarat_open_round()
    _state["round_id"] = round_id
    _state["task"] = asyncio.create_task(game_loop(bot, chat_id, round_id))


async def game_loop(bot: Bot, chat_id: int, first_round_id: int):
    round_id = first_round_id
    thread_id = _state["thread_id"]
    try:
        while True:
            # 1. 회차 공지 + 핀 업데이트
            round_row = await db.baccarat_get_round(round_id)
            round_no = round_row["id"]
            totals = await db.baccarat_get_totals(round_id)
            await _update_pin(bot, chat_id, round_no, totals, "betting", thread_id=thread_id)

            # 오픈 공지
            try:
                m = await bot.send_message(chat_id, fmt.round_open(round_no), parse_mode="HTML",
                                           message_thread_id=thread_id)
                asyncio.create_task(_delete_after(bot, chat_id, m.message_id, 30))
            except Exception as e:
                log.warning("round open msg failed: %s", e)

            # 2. 베팅 대기 (10초 단위로 쪼개 핀 캡션 업데이트)
            elapsed = 0
            while elapsed < ROUND_BET_SEC:
                await asyncio.sleep(10)
                elapsed += 10
                remain = max(0, ROUND_BET_SEC - elapsed)
                totals = await db.baccarat_get_totals(round_id)
                await _update_pin_caption_only(bot, chat_id, round_no, totals, "betting", remain)

            # 3. 베팅 마감
            await db.baccarat_close_betting(round_id)
            totals = await db.baccarat_get_totals(round_id)
            await _update_pin_caption_only(bot, chat_id, round_no, totals, "closed")

            try:
                m = await bot.send_message(chat_id, fmt.betting_closed(round_no, totals), parse_mode="HTML",
                                           message_thread_id=thread_id)
                asyncio.create_task(_delete_after(bot, chat_id, m.message_id, 15))
            except Exception as e:
                log.warning("closed msg failed: %s", e)

            await asyncio.sleep(COUNTDOWN_SEC)

            # 4. 베팅 없으면 중단
            bets = await db.baccarat_get_bets(round_id)
            if not bets:
                await db.baccarat_finish_round(round_id, None, None, None)
                _state["active"] = False
                _state["task"] = None
                _state["round_id"] = None
                await _update_pin_caption_only(bot, chat_id, round_no, totals, "done")
                try:
                    await bot.send_message(chat_id, fmt.idle_notice(), parse_mode="HTML",
                                           message_thread_id=thread_id)
                except Exception:
                    pass
                return

            # 5. 주사위 굴리기
            await db.baccarat_set_rolling(round_id)
            await _update_pin_caption_only(bot, chat_id, round_no, totals, "rolling")
            result, p_dice, b_dice = await _roll_all(bot, chat_id)

            # 6. 결과 처리
            payouts = gm.calc_all_payouts(bets, result)
            await db.baccarat_finish_round(round_id, p_dice, b_dice, result)
            await db.baccarat_settle(round_id, result, payouts)

            result_text = fmt.round_result(round_no, p_dice, b_dice, result, bets, payouts)
            try:
                await bot.send_message(chat_id, result_text, parse_mode="HTML",
                                       message_thread_id=thread_id)
            except Exception as e:
                log.warning("result msg failed: %s", e)

            await asyncio.sleep(RESULT_PAUSE_SEC)

            # 7. 다음 회차 (핀은 다음 라운드 오픈 시 이미지 포함 갱신)
            round_id = await db.baccarat_open_round()
            _state["round_id"] = round_id

    except asyncio.CancelledError:
        log.info("game_loop cancelled")
        raise
    except Exception as e:
        log.exception("game_loop error: %s", e)
        _state["active"] = False
        _state["task"] = None
        _state["round_id"] = None


async def _roll_all(bot: Bot, chat_id: int):
    """주사위 순서대로 전송. 결과 반환: (result, p_dice, b_dice)."""
    thread_id = _state["thread_id"]

    async def send_die(label: str | None = None) -> int:
        if label:
            try:
                lm = await bot.send_message(chat_id, label, message_thread_id=thread_id)
                asyncio.create_task(_delete_after(bot, chat_id, lm.message_id, 20))
            except Exception:
                pass
        msg = await bot.send_dice(chat_id, emoji="🎲", message_thread_id=thread_id)
        await asyncio.sleep(DICE_DELAY_SEC)
        return msg.dice.value

    p1 = await send_die("🔵 <b>플레이어</b>")
    p2 = await send_die()
    p_dice = [p1, p2]
    p_score = gm.hand_score(p_dice)

    b1 = await send_die("🔴 <b>뱅커</b>")
    b2 = await send_die()
    b_dice = [b1, b2]
    b_score = gm.hand_score(b_dice)

    p_natural = gm.is_natural(p_score)
    b_natural = gm.is_natural(b_score)

    p3 = None
    if not (p_natural or b_natural):
        if gm.player_draws(p_score):
            p3 = await send_die("🔵 <b>플레이어 추가카드</b>")
            p_dice.append(p3)
            p_score = gm.hand_score(p_dice)

        if gm.banker_draws(b_score, p3 is not None, p3):
            b3 = await send_die("🔴 <b>뱅커 추가카드</b>")
            b_dice.append(b3)

    result = gm.determine_result(gm.hand_score(p_dice), gm.hand_score(b_dice))
    return result, p_dice, b_dice


async def _update_pin(bot: Bot, chat_id: int, round_no: int, totals: dict, status: str,
                      thread_id: int | None = None):
    """이미지 + 캡션을 함께 교체 (회차 오픈 시)."""
    history_rows = await db.baccarat_get_history(limit=200)
    history = [r["result"] for r in history_rows if r["result"]]
    img_bytes = generate_road_image(history, round_no)
    caption = fmt.pin_caption(round_no, totals, status)

    pin_id_str = await _get_pin_id()
    if pin_id_str:
        try:
            media = InputMediaPhoto(
                media=BufferedInputFile(img_bytes, filename="road.png"),
                caption=caption,
                parse_mode="HTML",
            )
            await bot.edit_message_media(
                chat_id=chat_id,
                message_id=int(pin_id_str),
                media=media,
            )
            return
        except Exception as e:
            log.warning("edit_message_media failed (%s), sending new pin", e)

    # 첫 전송 또는 수정 실패 시
    try:
        msg = await bot.send_photo(
            chat_id,
            photo=BufferedInputFile(img_bytes, filename="road.png"),
            caption=caption,
            parse_mode="HTML",
            message_thread_id=thread_id,
        )
        await bot.pin_chat_message(chat_id, msg.message_id, disable_notification=True)
        await db.set_config("baccarat_pin_msg_id", str(msg.message_id))
    except Exception as e:
        log.warning("send_photo/pin failed: %s", e)


async def _update_pin_caption_only(
    bot: Bot, chat_id: int, round_no: int, totals: dict, status: str, remain_sec: int | None = None
):
    """캡션만 업데이트 (이미지 유지)."""
    pin_id_str = await _get_pin_id()
    if not pin_id_str:
        return
    caption = fmt.pin_caption(round_no, totals, status, remain_sec)
    try:
        await bot.edit_message_caption(
            chat_id=chat_id,
            message_id=int(pin_id_str),
            caption=caption,
            parse_mode="HTML",
        )
    except Exception as e:
        log.debug("edit caption failed: %s", e)


async def update_pin_after_bet(bot: Bot, chat_id: int, round_id: int):
    """베팅 발생 후 핀 캡션 즉시 업데이트."""
    round_row = await db.baccarat_get_round(round_id)
    if not round_row:
        return
    totals = await db.baccarat_get_totals(round_id)
    await _update_pin_caption_only(bot, chat_id, round_row["id"], totals, "betting")


async def _get_pin_id() -> str:
    raw = await db.get_config_raw()
    return raw.get("baccarat_pin_msg_id", "")


async def _delete_after(bot: Bot, chat_id: int, msg_id: int, delay: int):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, msg_id)
    except Exception:
        pass
