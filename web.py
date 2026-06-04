import json
import os
import logging
from fastapi import FastAPI, Request, Form, Response, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from dotenv import load_dotenv

import db
from config import get_cfg, save_cfg

load_dotenv()
log = logging.getLogger(__name__)

WEB_PASSWORD = "love"
SECRET_KEY = os.getenv("WEB_SECRET", "default-secret-change-me")
COOKIE_NAME = "session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 days

app = FastAPI()
templates = Jinja2Templates(directory="templates")

if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

_signer = URLSafeTimedSerializer(SECRET_KEY)


def make_session() -> str:
    return _signer.dumps({"auth": True})


def check_session(request: Request) -> bool:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return False
    try:
        _signer.loads(token, max_age=SESSION_MAX_AGE)
        return True
    except (BadSignature, SignatureExpired):
        return False


def require_auth(request: Request):
    if not check_session(request):
        raise HTTPException(status_code=303, headers={"Location": "/login"})


# ── auth ───────────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if check_session(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("panel.html", {"request": request, "page": "login", "error": None})


@app.post("/login")
async def login_post(request: Request, password: str = Form(...)):
    if password == WEB_PASSWORD:
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(COOKIE_NAME, make_session(), max_age=SESSION_MAX_AGE, httponly=True, path="/", samesite="lax")
        return resp
    return templates.TemplateResponse("panel.html", {"request": request, "page": "login", "error": "비밀번호가 틀렸어요"})


@app.get("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(COOKIE_NAME)
    return resp


# ── dashboard ──────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not check_session(request):
        return RedirectResponse("/login", status_code=303)
    stats = await db.get_stats()
    logs = await db.get_logs(limit=10)
    return templates.TemplateResponse("panel.html", {
        "request": request, "page": "dashboard",
        "stats": stats, "logs": [dict(r) for r in logs],
    })


# ── users ──────────────────────────────────────────────────────────────────

@app.get("/users", response_class=HTMLResponse)
async def users_page(request: Request, q: str = ""):
    if not check_session(request):
        return RedirectResponse("/login", status_code=303)
    users = await db.list_users(search=q)
    return templates.TemplateResponse("panel.html", {
        "request": request, "page": "users",
        "users": [dict(u) for u in users], "q": q,
    })


@app.post("/users/{user_id}/edit")
async def update_user(
    request: Request, user_id: int,
    total_chat: int = Form(...),
    daily_chat: int = Form(...),
    points: int = Form(...),
):
    if not check_session(request):
        raise HTTPException(status_code=401)
    await db.set_user_stats(user_id, total_chat, daily_chat, points)
    return RedirectResponse(f"/users?q={request.query_params.get('q','')}", status_code=303)


# ── config: settle ─────────────────────────────────────────────────────────

@app.get("/settle", response_class=HTMLResponse)
async def settle_page(request: Request):
    if not check_session(request):
        return RedirectResponse("/login", status_code=303)
    cfg = await get_cfg()
    return templates.TemplateResponse("panel.html", {"request": request, "page": "settle", "cfg": cfg})


@app.post("/settle")
async def settle_save(request: Request):
    if not check_session(request):
        raise HTTPException(status_code=401)
    form = await request.form()
    def _int(v, default=0):
        try: return max(0, int(v))
        except: return default

    rewards = [_int(form.get(f"r{i}", 0)) for i in range(1, 31)]
    enabled = form.get("settle_enabled") == "on"
    checkin_enabled = form.get("checkin_enabled") == "on"
    await save_cfg({
        "settle_enabled": enabled,
        "settle_rewards": rewards,
        "settle_range_31_40":  _int(form.get("range_31_40", 0)),
        "settle_range_41_50":  _int(form.get("range_41_50", 0)),
        "settle_range_51_100": _int(form.get("range_51_100", 0)),
        "checkin_enabled": checkin_enabled,
        "checkin_points": _int(form.get("checkin_points", 30), 30),
    })
    return RedirectResponse("/settle", status_code=303)


# ── config: surprise ───────────────────────────────────────────────────────

@app.get("/surprise", response_class=HTMLResponse)
async def surprise_page(request: Request):
    if not check_session(request):
        return RedirectResponse("/login", status_code=303)
    cfg = await get_cfg()
    return templates.TemplateResponse("panel.html", {"request": request, "page": "surprise", "cfg": cfg})


@app.post("/surprise")
async def surprise_save(request: Request):
    if not check_session(request):
        raise HTTPException(status_code=401)
    form = await request.form()
    enabled = form.get("surprise_enabled") == "on"
    await save_cfg({
        "surprise_enabled": enabled,
        "surprise_points": int(form.get("surprise_points", 50)),
        "surprise_chance": float(form.get("surprise_chance", 0.1)) / 100,
        "surprise_expire_sec": int(form.get("surprise_expire_sec", 5)),
    })
    return RedirectResponse("/surprise", status_code=303)


# ── admins ─────────────────────────────────────────────────────────────────

@app.get("/admins", response_class=HTMLResponse)
async def admins_page(request: Request):
    if not check_session(request):
        return RedirectResponse("/login", status_code=303)
    admins = await db.list_admins()
    return templates.TemplateResponse("panel.html", {
        "request": request, "page": "admins",
        "admins": [dict(a) for a in admins],
    })


@app.post("/admins/add")
async def admin_add(request: Request, user_id: int = Form(...), username: str = Form(default="")):
    if not check_session(request):
        raise HTTPException(status_code=401)
    await db.add_admin(user_id, username or None)
    return RedirectResponse("/admins", status_code=303)


@app.post("/admins/{user_id}/delete")
async def admin_delete(request: Request, user_id: int):
    if not check_session(request):
        raise HTTPException(status_code=401)
    await db.remove_admin(user_id)
    return RedirectResponse("/admins", status_code=303)


# ── logs ───────────────────────────────────────────────────────────────────

@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request, reason: str = ""):
    if not check_session(request):
        return RedirectResponse("/login", status_code=303)
    logs = await db.get_logs(reason=reason or None, limit=100)
    return templates.TemplateResponse("panel.html", {
        "request": request, "page": "logs",
        "logs": [dict(l) for l in logs], "reason": reason,
    })


# ── baccarat config ────────────────────────────────────────────────────────

@app.get("/baccarat", response_class=HTMLResponse)
async def baccarat_page(request: Request):
    if not check_session(request):
        return RedirectResponse("/login", status_code=303)
    cfg = await db.get_config_raw()
    rounds = await db.baccarat_get_recent_rounds(limit=20)
    return templates.TemplateResponse("panel.html", {
        "request": request, "page": "baccarat",
        "bac_min_bet": int(cfg.get("baccarat_min_bet", "100")),
        "bac_max_bet": int(cfg.get("baccarat_max_bet", "0")),
        "rounds": [dict(r) for r in rounds],
    })


@app.post("/baccarat")
async def baccarat_save(request: Request):
    if not check_session(request):
        raise HTTPException(status_code=401)
    form = await request.form()
    def _int(v, default=0):
        try: return max(0, int(v))
        except: return default
    await db.set_config("baccarat_min_bet", str(_int(form.get("baccarat_min_bet", "100"), 100)))
    await db.set_config("baccarat_max_bet", str(_int(form.get("baccarat_max_bet", "0"), 0)))
    return RedirectResponse("/baccarat", status_code=303)


# ── lotto config ──────────────────────────────────────────────────────────

@app.get("/lotto", response_class=HTMLResponse)
async def lotto_page(request: Request):
    if not check_session(request):
        return RedirectResponse("/login", status_code=303)
    cfg = await get_cfg()
    draw = await db.lotto_get_open_draw()
    recent = await db.lotto_get_recent_draws(limit=15)
    return templates.TemplateResponse("panel.html", {
        "request": request, "page": "lotto",
        "cfg": cfg,
        "draw": dict(draw) if draw else None,
        "recent_draws": [dict(r) for r in recent],
    })


@app.post("/lotto")
async def lotto_save(request: Request):
    if not check_session(request):
        raise HTTPException(status_code=401)
    form = await request.form()
    def _int(v, default=0):
        try: return max(0, int(v))
        except: return default
    await save_cfg({
        "lotto_enabled":       form.get("lotto_enabled") == "on",
        "lotto_price":         _int(form.get("lotto_price"), 1000),
        "lotto_max_per_draw":  _int(form.get("lotto_max_per_draw"), 10),
        "lotto_prize_mode":    form.get("lotto_prize_mode", "fixed"),
        "lotto_prize_3_fixed": _int(form.get("lotto_prize_3_fixed"), 500),
        "lotto_prize_4_fixed": _int(form.get("lotto_prize_4_fixed"), 5000),
        "lotto_prize_5_fixed": _int(form.get("lotto_prize_5_fixed"), 50000),
        "lotto_prize_3_pct":   _int(form.get("lotto_prize_3_pct"), 5),
        "lotto_prize_4_pct":   _int(form.get("lotto_prize_4_pct"), 15),
        "lotto_prize_5_pct":   _int(form.get("lotto_prize_5_pct"), 80),
    })
    return RedirectResponse("/lotto", status_code=303)


# ── run ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    import asyncio

    async def startup():
        from db import init_db
        await init_db()

    asyncio.run(startup())
    uvicorn.run("web:app", host="0.0.0.0", port=8000, reload=False)
