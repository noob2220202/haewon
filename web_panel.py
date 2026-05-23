import os
import sqlite3
from datetime import datetime, timedelta
from functools import wraps

from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "changeme")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")
WEB_PORT = int(os.environ.get("WEB_PORT", "5001"))

DB_PATH = "haewon.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def get_config(conn, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_config(conn, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO config(key,value) VALUES (?,?)", (key, value))


# ── 인증 ──────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        flash("비밀번호가 틀렸어요.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ── 대시보드 ──────────────────────────────────────────────────

@app.route("/")
@login_required
def dashboard():
    conn = get_db()
    total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    total_points = conn.execute("SELECT COALESCE(SUM(points),0) FROM users").fetchone()[0]
    today = datetime.now().strftime("%Y-%m-%d")
    today_attendance = conn.execute(
        "SELECT COUNT(*) FROM attendance WHERE date=?", (today,)
    ).fetchone()[0]
    surprise_enabled = get_config(conn, "surprise_enabled", "0") == "1"
    total_purchases = conn.execute("SELECT COUNT(*) FROM purchases").fetchone()[0]
    recent_points = conn.execute(
        "SELECT u.name, p.delta, p.reason, p.created_at "
        "FROM points_log p JOIN users u ON p.user_id=u.user_id "
        "ORDER BY p.id DESC LIMIT 10"
    ).fetchall()
    conn.close()
    return render_template(
        "dashboard.html",
        total_users=total_users,
        total_points=total_points,
        today_attendance=today_attendance,
        surprise_enabled=surprise_enabled,
        total_purchases=total_purchases,
        recent_points=recent_points,
    )


@app.route("/surprise_toggle", methods=["POST"])
@login_required
def surprise_toggle():
    conn = get_db()
    current = get_config(conn, "surprise_enabled", "0")
    new_val = "0" if current == "1" else "1"
    set_config(conn, "surprise_enabled", new_val)
    conn.commit()
    conn.close()
    status = "켜짐" if new_val == "1" else "꺼짐"
    flash(f"돌발 포인트가 {status}으로 변경됐어요. (봇 프로세스 재시작 시 적용)")
    return redirect(url_for("dashboard"))


# ── 사용자 관리 ───────────────────────────────────────────────

@app.route("/users")
@login_required
def users():
    page = request.args.get("page", 1, type=int)
    search = request.args.get("q", "")
    sort = request.args.get("sort", "chat_count")
    order = request.args.get("order", "desc")
    allowed_sorts = {"chat_count", "points", "name", "user_id"}
    if sort not in allowed_sorts:
        sort = "chat_count"
    order_sql = "DESC" if order == "desc" else "ASC"

    per_page = 20
    conn = get_db()
    if search:
        total = conn.execute(
            "SELECT COUNT(*) FROM users WHERE name LIKE ?", (f"%{search}%",)
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT user_id, name, chat_count, points FROM users "
            f"WHERE name LIKE ? ORDER BY {sort} {order_sql} LIMIT ? OFFSET ?",
            (f"%{search}%", per_page, (page - 1) * per_page),
        ).fetchall()
    else:
        total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        rows = conn.execute(
            f"SELECT user_id, name, chat_count, points FROM users "
            f"ORDER BY {sort} {order_sql} LIMIT ? OFFSET ?",
            (per_page, (page - 1) * per_page),
        ).fetchall()
    conn.close()
    total_pages = max(1, (total + per_page - 1) // per_page)
    return render_template(
        "users.html",
        rows=rows,
        page=page,
        total_pages=total_pages,
        total=total,
        search=search,
        sort=sort,
        order=order,
    )


@app.route("/users/<int:uid>/edit", methods=["POST"])
@login_required
def user_edit(uid: int):
    field = request.form.get("field")
    value = request.form.get("value", "0")
    try:
        v = int(value)
    except ValueError:
        flash("숫자를 입력해주세요.")
        return redirect(url_for("users"))
    if field not in ("points", "chat_count"):
        flash("잘못된 필드입니다.")
        return redirect(url_for("users"))
    conn = get_db()
    conn.execute(f"UPDATE users SET {field}=? WHERE user_id=?", (v, uid))
    if field == "points":
        conn.execute(
            "INSERT INTO points_log(user_id, delta, reason) VALUES (?,?,'admin_edit')",
            (uid, v),
        )
    conn.commit()
    conn.close()
    flash(f"사용자 {uid} {field} 변경 완료!")
    return redirect(url_for("users"))


# ── 랭킹 ──────────────────────────────────────────────────────

@app.route("/rankings")
@login_required
def rankings():
    conn = get_db()
    overall = conn.execute(
        "SELECT ROW_NUMBER() OVER (ORDER BY chat_count DESC) as rank, user_id, name, chat_count, points "
        "FROM users ORDER BY chat_count DESC LIMIT 50"
    ).fetchall()
    today = datetime.now().strftime("%Y-%m-%d")
    daily = conn.execute(
        "SELECT ROW_NUMBER() OVER (ORDER BY d.count DESC) as rank, u.name, d.count "
        "FROM daily_chat d JOIN users u ON d.user_id=u.user_id "
        "WHERE d.date=? ORDER BY d.count DESC LIMIT 50",
        (today,),
    ).fetchall()
    conn.close()
    return render_template("rankings.html", overall=overall, daily=daily, today=today)


# ── 상점 관리 ─────────────────────────────────────────────────

@app.route("/shop")
@login_required
def shop():
    conn = get_db()
    items = conn.execute(
        "SELECT id, name, description, price, stock, is_active FROM shop_items ORDER BY id"
    ).fetchall()
    conn.close()
    return render_template("shop.html", items=items)


@app.route("/shop/new", methods=["POST"])
@login_required
def shop_new():
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    try:
        price = int(request.form.get("price", 0))
        stock = int(request.form.get("stock", -1))
    except ValueError:
        flash("가격과 재고는 숫자여야 해요.")
        return redirect(url_for("shop"))
    if not name:
        flash("아이템 이름을 입력해주세요.")
        return redirect(url_for("shop"))
    conn = get_db()
    conn.execute(
        "INSERT INTO shop_items(name, description, price, stock) VALUES (?,?,?,?)",
        (name, description, price, stock),
    )
    conn.commit()
    conn.close()
    flash(f"'{name}' 아이템이 등록됐어요!")
    return redirect(url_for("shop"))


@app.route("/shop/<int:item_id>/edit", methods=["POST"])
@login_required
def shop_edit(item_id: int):
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    try:
        price = int(request.form.get("price", 0))
        stock = int(request.form.get("stock", -1))
        is_active = int(request.form.get("is_active", 1))
    except ValueError:
        flash("가격과 재고는 숫자여야 해요.")
        return redirect(url_for("shop"))
    conn = get_db()
    conn.execute(
        "UPDATE shop_items SET name=?, description=?, price=?, stock=?, is_active=? WHERE id=?",
        (name, description, price, stock, is_active, item_id),
    )
    conn.commit()
    conn.close()
    flash("아이템이 수정됐어요!")
    return redirect(url_for("shop"))


@app.route("/shop/<int:item_id>/delete", methods=["POST"])
@login_required
def shop_delete(item_id: int):
    conn = get_db()
    conn.execute("DELETE FROM shop_items WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    flash("아이템이 삭제됐어요.")
    return redirect(url_for("shop"))


# ── 출석 관리 ─────────────────────────────────────────────────

@app.route("/attendance")
@login_required
def attendance():
    date = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))
    conn = get_db()
    records = conn.execute(
        "SELECT u.name, a.date, a.streak, a.points_given "
        "FROM attendance a JOIN users u ON a.user_id=u.user_id "
        "WHERE a.date=? ORDER BY a.streak DESC",
        (date,),
    ).fetchall()
    top_streaks = conn.execute(
        "SELECT u.name, a.streak, a.date "
        "FROM attendance a JOIN users u ON a.user_id=u.user_id "
        "WHERE a.date=(SELECT MAX(date) FROM attendance a2 WHERE a2.user_id=a.user_id) "
        "ORDER BY a.streak DESC LIMIT 20"
    ).fetchall()
    total_today = len(records)
    conn.close()
    return render_template(
        "attendance.html",
        records=records,
        top_streaks=top_streaks,
        date=date,
        total_today=total_today,
    )


# ── 설정 ──────────────────────────────────────────────────────

CONFIG_LABELS = {
    "surprise_enabled":        ("돌발 포인트 활성화 (1=켜짐, 0=꺼짐)", "text"),
    "surprise_min_seconds":    ("돌발 최소 간격 (초)", "number"),
    "surprise_max_seconds":    ("돌발 최대 간격 (초)", "number"),
    "surprise_points":         ("돌발 포인트 양", "number"),
    "daily_rank_1":            ("일간 1위 포인트", "number"),
    "daily_rank_2":            ("일간 2위 포인트", "number"),
    "daily_rank_3":            ("일간 3위 포인트", "number"),
    "daily_rank_4_10":         ("일간 4-10위 포인트", "number"),
    "daily_rank_11_plus":      ("일간 11위 이하 포인트", "number"),
    "attendance_base_pts":     ("출석 기본 포인트", "number"),
    "attendance_streak_bonus": ("연속 출석 보너스 (7일마다)", "number"),
    "last_group_chat_id":      ("메인 그룹 채팅 ID", "text"),
}


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    conn = get_db()
    if request.method == "POST":
        for key in CONFIG_LABELS:
            val = request.form.get(key, "")
            if val != "":
                set_config(conn, key, val)
        conn.commit()
        flash("설정이 저장됐어요!")
        return redirect(url_for("settings"))

    current = {key: get_config(conn, key) for key in CONFIG_LABELS}
    conn.close()
    return render_template("settings.html", current=current, labels=CONFIG_LABELS)


# ── 포인트 내역 ───────────────────────────────────────────────

@app.route("/points")
@login_required
def points_log():
    page = request.args.get("page", 1, type=int)
    per_page = 30
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM points_log").fetchone()[0]
    rows = conn.execute(
        "SELECT u.name, p.delta, p.reason, p.created_at "
        "FROM points_log p JOIN users u ON p.user_id=u.user_id "
        "ORDER BY p.id DESC LIMIT ? OFFSET ?",
        (per_page, (page - 1) * per_page),
    ).fetchall()
    conn.close()
    total_pages = max(1, (total + per_page - 1) // per_page)
    return render_template(
        "points_log.html",
        rows=rows,
        page=page,
        total_pages=total_pages,
        total=total,
    )


if __name__ == "__main__":
    from db import init_db_sync
    init_db_sync()
    app.run(host="0.0.0.0", port=WEB_PORT, debug=False)
