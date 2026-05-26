import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from db import get_daily_rank, add_points, today_ymd, get_config_raw
from config import get_cfg
from datetime import datetime, timezone, timedelta
import formats

log = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))


async def settle(bot):
    cfg = await get_cfg()
    if not cfg["settle_enabled"]:
        log.info("settle skipped (disabled)")
        return

    yesterday = (datetime.now(KST) - timedelta(days=1)).strftime("%Y-%m-%d")
    rows = await get_daily_rank(ymd=yesterday, limit=100)

    rewards: list[int] = cfg["settle_rewards"]
    ranges = [
        (31, 40,  cfg["settle_range_31_40"]),
        (41, 50,  cfg["settle_range_41_50"]),
        (51, 100, cfg["settle_range_51_100"]),
    ]
    rewarded_list: list[tuple[int, dict, int]] = []
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
            await add_points(row["user_id"], pts, "settle", f"{rank}등")
            log.info("settle rank=%d user=%d +%d", rank, row["user_id"], pts)
            rewarded_list.append((rank, dict(row), pts))

    log.info("settle done: %d users rewarded", len(rewarded_list))

    if rewarded_list:
        raw = await get_config_raw()
        chat_id_str = raw.get("group_chat_id")
        if chat_id_str:
            try:
                await bot.send_message(
                    int(chat_id_str),
                    formats.settle_announce(rewarded_list),
                    parse_mode="HTML",
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
