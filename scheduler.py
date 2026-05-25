import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from db import get_daily_rank, add_points, today_ymd
from config import get_cfg
from datetime import datetime, timezone, timedelta

log = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))


async def settle():
    cfg = await get_cfg()
    if not cfg["settle_enabled"]:
        log.info("settle skipped (disabled)")
        return

    from datetime import datetime, timedelta, timezone
    yesterday = (datetime.now(KST) - timedelta(days=1)).strftime("%Y-%m-%d")
    rows = await get_daily_rank(ymd=yesterday, limit=100)

    rewards: list[int] = cfg["settle_rewards"]  # 30개 (1~30등)
    ranges = [
        (31, 40,  cfg["settle_range_31_40"]),
        (41, 50,  cfg["settle_range_41_50"]),
        (51, 100, cfg["settle_range_51_100"]),
    ]
    rewarded = 0
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
            rewarded += 1

    log.info("settle done: %d users rewarded", rewarded)


def setup_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
    scheduler.add_job(settle, CronTrigger(hour=0, minute=0, timezone="Asia/Seoul"))
    return scheduler
