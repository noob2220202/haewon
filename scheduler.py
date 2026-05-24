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
    rows = await get_daily_rank(ymd=yesterday, limit=len(cfg["settle_rewards"]))

    rewards: list[int] = cfg["settle_rewards"]
    for rank, row in enumerate(rows, start=1):
        if rank > len(rewards):
            break
        pts = rewards[rank - 1]
        await add_points(row["user_id"], pts, "settle", f"{rank}등")
        log.info("settle rank=%d user=%d +%d", rank, row["user_id"], pts)

    log.info("settle done: %d users rewarded", min(len(rows), len(rewards)))


def setup_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
    scheduler.add_job(settle, CronTrigger(hour=0, minute=0, timezone="Asia/Seoul"))
    return scheduler
