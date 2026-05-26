import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from db import get_daily_rank, add_points, get_config_raw
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


def setup_scheduler(bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
    scheduler.add_job(
        settle, CronTrigger(hour=0, minute=0, timezone="Asia/Seoul"),
        args=[bot],
    )
    return scheduler
