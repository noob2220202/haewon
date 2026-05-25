import json
import time
from db import get_config_raw, set_config

_cache: dict = {}
_cache_ts: float = 0.0
_CACHE_TTL = 10  # seconds


async def get_cfg() -> dict:
    global _cache, _cache_ts
    if time.monotonic() - _cache_ts > _CACHE_TTL:
        raw = await get_config_raw()
        _cache = {
            "settle_enabled": raw.get("settle_enabled", "true") == "true",
            "settle_rewards": json.loads(raw.get("settle_rewards", "[100,90,80,70,60,50,40,30,20,10]")),
            "surprise_enabled": raw.get("surprise_enabled", "true") == "true",
            "surprise_points": int(raw.get("surprise_points", "50")),
            "surprise_chance": float(raw.get("surprise_chance", "0.001")),
            "surprise_expire_sec": int(raw.get("surprise_expire_sec", "5")),
            "chat_min_len": int(raw.get("chat_min_len", "3")),
            "chat_cooldown_sec": int(raw.get("chat_cooldown_sec", "1")),
            "msg_autodelete_sec": int(raw.get("msg_autodelete_sec", "5")),
            "checkin_enabled": raw.get("checkin_enabled", "true") == "true",
            "checkin_points": int(raw.get("checkin_points", "30")),
        }
        _cache_ts = time.monotonic()
    return _cache


def invalidate():
    global _cache_ts
    _cache_ts = 0.0


async def save_cfg(updates: dict):
    for k, v in updates.items():
        if isinstance(v, bool):
            await set_config(k, "true" if v else "false")
        elif isinstance(v, (list, dict)):
            await set_config(k, json.dumps(v))
        else:
            await set_config(k, str(v))
    invalidate()
