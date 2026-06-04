import json
import logging
import random
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from db import get_daily_rank, add_points, get_config_raw
import db
from config import get_cfg
from datetime import datetime, timezone, timedelta
import formats

log = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))
PER_PAGE = 10


async def calc_settle_rewarded(ymd: str) -> list[tuple[int, dict, int]]:
    cfg = await get_cfg()
    rows = await get_daily_rank(ymd=ymd, limit=100)
    rewards: list[int] = cfg["settle_rewards"]
    ranges = [
        (31, 40,  cfg["settle_range_31_40"]),
        (41, 50,  cfg["settle_range_41_50"]),
        (51, 100, cfg["settle_range_51_100"]),
    ]
    result = []
    for rank, row in enumerate(rows, start=1):
        pts = 0
        if rank <= len(rewards):
            pts = rewards[rank - 1]
        else:
            for lo, hi, p in ranges:
                if lo <= rank <= hi:
                    pts = p
                    break
        if pts > 0:
            result.append((rank, dict(row), pts))
    return result


def _settle_kb(ymd_compact: str, page: int, total_pages: int) -> InlineKeyboardMarkup | None:
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀ 이전", callback_data=f"settle_{ymd_compact}_{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1} / {total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="다음 ▶", callback_data=f"settle_{ymd_compact}_{page+1}"))
    return InlineKeyboardMarkup(inline_keyboard=[nav])


async def settle(bot):
    cfg = await get_cfg()
    if not cfg["settle_enabled"]:
        log.info("settle skipped (disabled)")
        return

    yesterday = (datetime.now(KST) - timedelta(days=1)).strftime("%Y-%m-%d")
    rewarded_list = await calc_settle_rewarded(yesterday)

    for rank, row, pts in rewarded_list:
        await add_points(row["user_id"], pts, "settle", f"{rank}등")
        log.info("settle rank=%d user=%d +%d", rank, row["user_id"], pts)

    log.info("settle done: %d users rewarded", len(rewarded_list))

    if rewarded_list:
        raw = await get_config_raw()
        chat_id_str = raw.get("group_chat_id")
        if chat_id_str:
            try:
                total_pages = max(1, (len(rewarded_list) + PER_PAGE - 1) // PER_PAGE)
                ymd_compact = yesterday.replace("-", "")
                await bot.send_message(
                    int(chat_id_str),
                    formats.settle_page(rewarded_list, 0, total_pages),
                    parse_mode="HTML",
                    reply_markup=_settle_kb(ymd_compact, 0, total_pages),
                )
            except Exception as e:
                log.warning("settle announce failed: %s", e)


def _calc_lotto_prizes(cfg_raw: dict, draw) -> tuple[int, int, int]:
    """(prize_3, prize_4, prize_5_total) — 5는 전체 잭팟 금액, 나머지는 1인당."""
    mode = cfg_raw.get("lotto_prize_mode", "fixed")
    pool = draw["pool"]
    jackpot = draw["jackpot"]
    if mode == "pool":
        pct3 = int(cfg_raw.get("lotto_prize_3_pct", "5"))
        pct4 = int(cfg_raw.get("lotto_prize_4_pct", "15"))
        pct5 = int(cfg_raw.get("lotto_prize_5_pct", "80"))
        return (
            int(pool * pct3 / 100),
            int(pool * pct4 / 100),
            jackpot + int(pool * pct5 / 100),
        )
    else:
        p3 = int(cfg_raw.get("lotto_prize_3_fixed", "500"))
        p4 = int(cfg_raw.get("lotto_prize_4_fixed", "5000"))
        p5 = int(cfg_raw.get("lotto_prize_5_fixed", "50000"))
        return p3, p4, jackpot if p5 == 0 else p5


async def lotto_draw(bot):
    draw = await db.lotto_get_open_draw()
    if not draw:
        log.info("lotto_draw: no open draw, skipping")
        return

    cfg_raw = await get_config_raw()
    if cfg_raw.get("lotto_enabled", "true") != "true":
        log.info("lotto_draw: disabled, skipping")
        return

    winning = sorted(random.sample(range(1, 21), 5))
    tickets = await db.lotto_get_all_tickets(draw["id"])

    prize_3, prize_4, jackpot_total = _calc_lotto_prizes(cfg_raw, draw)

    by_grade: dict[int, list] = {5: [], 4: [], 3: []}
    payouts: dict[int, tuple[int, int]] = {}

    for t in tickets:
        nums = set(json.loads(t["numbers"]))
        matched = len(nums & set(winning))
        payouts[t["id"]] = (matched, 0)
        if matched >= 3:
            by_grade[matched].append(dict(t))

    # 잭팟(5개) 분배
    carry = 0
    if by_grade[5]:
        per_winner = jackpot_total // len(by_grade[5])
        for w in by_grade[5]:
            payouts[w["id"]] = (5, per_winner)
            w["payout"] = per_winner
    else:
        carry = jackpot_total  # 이월

    # 4개 일치
    if by_grade[4] and prize_4 > 0:
        for w in by_grade[4]:
            payouts[w["id"]] = (4, prize_4)
            w["payout"] = prize_4

    # 3개 일치
    if by_grade[3] and prize_3 > 0:
        for w in by_grade[3]:
            payouts[w["id"]] = (3, prize_3)
            w["payout"] = prize_3

    await db.lotto_finish_draw(draw["id"], winning)
    await db.lotto_settle_tickets(draw["id"], payouts)

    log.info("lotto_draw #%d winning=%s carry=%d 5=%d 4=%d 3=%d",
             draw["id"], winning, carry, len(by_grade[5]), len(by_grade[4]), len(by_grade[3]))

    # 그룹 공지
    group_id_str = cfg_raw.get("group_chat_id")
    if group_id_str:
        try:
            text = formats.lotto_result(draw["id"], winning, by_grade, jackpot_total, carry)
            await bot.send_message(int(group_id_str), text, parse_mode="HTML")
        except Exception as e:
            log.warning("lotto group announce failed: %s", e)

    # 당첨자 DM
    for grade in (5, 4, 3):
        for w in by_grade[grade]:
            if w.get("payout", 0) > 0:
                try:
                    nums = json.loads(w["numbers"])
                    text = formats.lotto_win_dm(grade, nums, winning, w["payout"], draw["id"])
                    await bot.send_message(w["user_id"], text, parse_mode="HTML")
                except Exception as e:
                    log.debug("lotto DM failed uid=%s: %s", w["user_id"], e)

    # 다음 회차 생성
    await db.lotto_open_next_draw(carry)


def setup_scheduler(bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
    scheduler.add_job(
        settle, CronTrigger(hour=0, minute=0, timezone="Asia/Seoul"),
        args=[bot],
    )
    scheduler.add_job(
        lotto_draw, CronTrigger(hour=0, minute=1, timezone="Asia/Seoul"),
        args=[bot],
    )
    return scheduler
