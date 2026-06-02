"""
바카라 그림장 이미지 생성 (Big Road + Bead Road).
슈퍼샘플링(2x) 렌더링으로 부드러운 원과 선 표현.
"""

import io
import math
import os
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "NanumGothicBold.ttf")

# ── 색상 팔레트 (럭셔리 다크 카지노) ──────────────────────────────────────
BG          = (9,  13,  28)       # 짙은 네이비 배경
PANEL       = (14, 20,  42)       # 패널 배경
PANEL_DARK  = (10, 15,  32)       # 어두운 패널
BORDER      = (38, 55,  100)      # 패널 테두리
GRID        = (28, 40,  75)       # 격자선
HEADER_TOP  = (18, 28,  62)       # 헤더 상단
HEADER_BOT  = (10, 16,  38)       # 헤더 하단
GOLD        = (255, 200, 80)      # 골드 강조
TEXT        = (215, 225, 248)     # 기본 텍스트
MUTED       = (100, 120, 175)     # 음소거 텍스트
DIVIDER     = (35, 50, 95)        # 구분선

PLAYER_C    = (48,  108, 245)     # 파랑 (플레이어)
PLAYER_H    = (100, 150, 255)     # 파랑 하이라이트
BANKER_C    = (215,  42,  62)     # 빨강 (뱅커)
BANKER_H    = (255, 100, 115)     # 빨강 하이라이트
TIE_C       = (32,  190,  95)     # 초록 (타이)
TIE_H       = (90,  230, 140)     # 초록 하이라이트

# ── 레이아웃 ──────────────────────────────────────────────────────────────
SCALE    = 2          # 슈퍼샘플링 배율
CELL     = 36         # 셀 크기 (1x 기준)
ROWS     = 6
BR_COLS  = 22         # Big Road 컬럼 수
BD_COLS  = 9          # Bead Road 컬럼 수
PAD      = 14         # 외곽 패딩
GAP      = 14         # Big Road ↔ Bead Road 간격
HDR_H    = 46         # 헤더 높이
LBL_H    = 20         # 섹션 레이블 높이
STATS_H  = 30         # 하단 통계 바 높이
RADIUS   = 8          # 패널 모서리 반경


def _font(size: int):
    try:
        return ImageFont.truetype(FONT_PATH, int(size * SCALE))
    except Exception:
        return ImageFont.load_default()


def _side_info(side: str):
    return {
        "player": (PLAYER_C, PLAYER_H, "P"),
        "banker": (BANKER_C, BANKER_H, "B"),
        "tie":    (TIE_C,    TIE_H,    "T"),
    }.get(side, (MUTED, MUTED, "?"))


def _s(v):
    """1x 값을 2x 스케일로 변환."""
    return int(v * SCALE)


# ── 원 그리기 (글로시 효과) ────────────────────────────────────────────────

def _draw_circle(draw: ImageDraw.Draw, cx: int, cy: int, r: int,
                 base_c: tuple, hi_c: tuple, letter: str = "",
                 tie_count: int = 0):
    """글로시 원 그리기. cx/cy/r 은 2x 스케일 좌표."""

    # 그림자
    shadow_off = max(2, r // 6)
    for i in range(3, 0, -1):
        alpha = 60 - i * 15
        draw.ellipse(
            (cx - r + shadow_off + i, cy - r + shadow_off + i,
             cx + r + shadow_off + i, cy + r + shadow_off + i),
            fill=(*BG, alpha),
        )

    # 메인 원
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=base_c)

    # 상단 하이라이트 아크 (광택)
    hi_r = int(r * 0.65)
    hi_x = cx - hi_r // 2
    hi_y = cy - int(r * 0.55)
    draw.ellipse(
        (hi_x, hi_y, hi_x + hi_r, hi_y + int(hi_r * 0.7)),
        fill=(*hi_c, 70),
    )

    # 테두리 (얇은 흰색)
    draw.ellipse(
        (cx - r, cy - r, cx + r, cy + r),
        outline=(*TEXT, 40), width=max(1, r // 12),
    )

    # 글자
    if letter:
        fnt = _font(max(7, (r - 4) // SCALE))
        bbox = draw.textbbox((0, 0), letter, font=fnt)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        # 그림자
        draw.text((cx - tw // 2 + 1, cy - th // 2 + 1), letter, font=fnt, fill=(0, 0, 0, 100))
        draw.text((cx - tw // 2, cy - th // 2 - 1), letter, font=fnt, fill=(*TEXT, 230))

    # 타이 횟수 표시 (오른쪽 상단 녹색 점)
    if tie_count > 0:
        dot_r = max(4, r // 5)
        dot_cx = cx + r - dot_r
        dot_cy = cy - r + dot_r
        draw.ellipse(
            (dot_cx - dot_r, dot_cy - dot_r, dot_cx + dot_r, dot_cy + dot_r),
            fill=TIE_C,
        )
        if tie_count > 1:
            fnt_t = _font(max(5, dot_r // SCALE))
            tc_str = str(tie_count)
            tb = draw.textbbox((0, 0), tc_str, font=fnt_t)
            tw2 = tb[2] - tb[0]
            th2 = tb[3] - tb[1]
            draw.text((dot_cx - tw2 // 2, dot_cy - th2 // 2 - 1), tc_str, font=fnt_t, fill=TEXT)


# ── 빅로드 / 구슬길 계산 ───────────────────────────────────────────────────

def build_big_road(history: list[str]) -> list[list[tuple]]:
    columns: list[list[tuple]] = []
    last_non_tie: str | None = None
    current_row = 0

    for result in history:
        if result == "tie":
            if columns and columns[-1]:
                r, tc = columns[-1][-1]
                columns[-1][-1] = (r, tc + 1)
            continue
        if result != last_non_tie:
            columns.append([])
            current_row = 0
            last_non_tie = result
        elif current_row >= ROWS:
            columns.append([])
            current_row = 0
        columns[-1].append((result, 0))
        current_row += 1

    return columns


def build_bead_road(history: list[str]) -> list[str]:
    return list(history)[-(BD_COLS * ROWS):]


# ── 라운드 모서리 사각형 ───────────────────────────────────────────────────

def _rounded_rect(draw: ImageDraw.Draw, x0, y0, x1, y1, r, fill=None, outline=None, width=1):
    draw.rounded_rectangle((x0, y0, x1, y1), radius=r, fill=fill, outline=outline, width=width)


# ── 메인 이미지 생성 ───────────────────────────────────────────────────────

def generate_road_image(history: list[str], round_no: int) -> bytes:
    br_w  = BR_COLS * CELL
    bd_w  = BD_COLS * CELL
    grid_h = ROWS * CELL

    total_w = PAD + br_w + GAP + bd_w + PAD
    total_h = PAD + HDR_H + LBL_H + grid_h + STATS_H + PAD

    # 2x 해상도로 렌더링
    W, H = _s(total_w), _s(total_h)
    img = Image.new("RGBA", (W, H), (*BG, 255))
    draw = ImageDraw.Draw(img, "RGBA")

    # ── 배경 그라데이션 효과 (상단 약간 밝게) ─────────────────────────────
    for row in range(H // 3):
        alpha = int(18 * (1 - row / (H // 3)))
        draw.line((0, row, W, row), fill=(*HEADER_TOP, alpha))

    # ── 헤더 ─────────────────────────────────────────────────────────────
    hdr_y0, hdr_y1 = _s(PAD), _s(PAD + HDR_H)
    _rounded_rect(draw, _s(PAD - 4), hdr_y0, _s(total_w - PAD + 4), hdr_y1,
                  r=_s(RADIUS), fill=HEADER_TOP, outline=BORDER, width=_s(1))

    # 골드 좌측 액센트 바
    draw.rounded_rectangle(
        (_s(PAD - 4), hdr_y0, _s(PAD + 3), hdr_y1),
        radius=_s(RADIUS // 2), fill=GOLD,
    )

    fnt_title  = _font(11)
    fnt_sub    = _font(8)
    fnt_legend = _font(7)

    p_cnt  = history.count("player")
    b_cnt  = history.count("banker")
    t_cnt  = history.count("tie")
    total  = len(history)

    title_text = f"BACCARAT  |  #{round_no}"
    draw.text((_s(PAD + 10), _s(PAD + 7)),  title_text, font=fnt_title, fill=GOLD)
    draw.text((_s(PAD + 10), _s(PAD + 24)), f"총 {total}회  P:{p_cnt}  B:{b_cnt}  T:{t_cnt}",
              font=fnt_sub, fill=MUTED)

    # 범례 (헤더 오른쪽)
    leg_x = _s(total_w - PAD - 160)
    leg_y = _s(PAD + 10)
    for i, (lbl, base, hi) in enumerate([
        ("플레이어", PLAYER_C, PLAYER_H),
        ("뱅커",    BANKER_C, BANKER_H),
        ("타이",    TIE_C,    TIE_H),
    ]):
        lx = leg_x + _s(i * 54)
        r_leg = _s(6)
        _draw_circle(draw, lx + r_leg, leg_y + r_leg, r_leg, base, hi, "PBT"[i])
        draw.text((lx + _s(14), leg_y + _s(2)), lbl, font=fnt_legend, fill=MUTED)

    # ── Big Road 패널 ──────────────────────────────────────────────────────
    br_x0 = PAD
    br_y0 = PAD + HDR_H + LBL_H
    br_x1 = br_x0 + br_w
    br_y1 = br_y0 + grid_h

    _rounded_rect(draw, _s(br_x0 - 2), _s(PAD + HDR_H + 2),
                  _s(br_x1 + 2), _s(br_y1 + 2),
                  r=_s(5), fill=PANEL, outline=BORDER, width=_s(1))

    fnt_lbl = _font(7)
    draw.text((_s(br_x0 + 2), _s(PAD + HDR_H + 4)), "BIG ROAD", font=fnt_lbl, fill=GOLD)

    # 격자
    for r in range(ROWS + 1):
        y = _s(br_y0 + r * CELL)
        lw = _s(1) if r % ROWS else _s(1)
        draw.line((_s(br_x0), y, _s(br_x1), y), fill=(*GRID, 180), width=lw)
    for c in range(BR_COLS + 1):
        x = _s(br_x0 + c * CELL)
        draw.line((x, _s(br_y0), x, _s(br_y1)), fill=(*GRID, 180), width=_s(1))

    # Big Road 원 그리기
    columns = build_big_road(history)
    visible = columns[-BR_COLS:] if len(columns) > BR_COLS else columns
    col_offset = BR_COLS - len(visible)

    for ci, col in enumerate(visible):
        for ri, (result, tie_count) in enumerate(col):
            base, hi, letter = _side_info(result)
            cx = _s(br_x0 + (col_offset + ci) * CELL + CELL // 2)
            cy = _s(br_y0 + ri * CELL + CELL // 2)
            r_px = _s(CELL // 2 - 5)
            _draw_circle(draw, cx, cy, r_px, base, hi, letter, tie_count)

    # ── Bead Road 패널 ─────────────────────────────────────────────────────
    bd_x0 = br_x1 + GAP
    bd_x1 = bd_x0 + bd_w
    bd_y0 = br_y0

    _rounded_rect(draw, _s(bd_x0 - 2), _s(PAD + HDR_H + 2),
                  _s(bd_x1 + 2), _s(br_y1 + 2),
                  r=_s(5), fill=PANEL_DARK, outline=BORDER, width=_s(1))

    draw.text((_s(bd_x0 + 2), _s(PAD + HDR_H + 4)), "BEAD ROAD", font=fnt_lbl, fill=MUTED)

    for r in range(ROWS + 1):
        y = _s(bd_y0 + r * CELL)
        draw.line((_s(bd_x0), y, _s(bd_x1), y), fill=(*GRID, 180), width=_s(1))
    for c in range(BD_COLS + 1):
        x = _s(bd_x0 + c * CELL)
        draw.line((x, _s(bd_y0), x, _s(br_y1)), fill=(*GRID, 180), width=_s(1))

    bead = build_bead_road(history)
    for idx, result in enumerate(bead):
        col_i = idx // ROWS
        row_i = idx % ROWS
        if col_i >= BD_COLS:
            break
        base, hi, letter = _side_info(result)
        cx = _s(bd_x0 + col_i * CELL + CELL // 2)
        cy = _s(bd_y0 + row_i * CELL + CELL // 2)
        r_px = _s(CELL // 2 - 5)
        _draw_circle(draw, cx, cy, r_px, base, hi, letter)

    # ── 하단 통계 바 ───────────────────────────────────────────────────────
    stats_y = _s(br_y1 + 4)
    fnt_stats = _font(7)

    if total > 0:
        p_pct = p_cnt / total * 100
        b_pct = b_cnt / total * 100
        t_pct = t_cnt / total * 100

        bar_x0 = _s(PAD)
        bar_x1 = _s(total_w - PAD)
        bar_w  = bar_x1 - bar_x0
        bar_h  = _s(6)
        bar_y  = stats_y + _s(4)

        # 배경
        draw.rounded_rectangle((bar_x0, bar_y, bar_x1, bar_y + bar_h),
                                radius=bar_h // 2, fill=PANEL)

        # P 바
        pw = int(bar_w * p_cnt / total)
        if pw > 0:
            draw.rounded_rectangle((bar_x0, bar_y, bar_x0 + pw, bar_y + bar_h),
                                    radius=bar_h // 2, fill=PLAYER_C)
        # B 바
        bw = int(bar_w * b_cnt / total)
        if bw > 0:
            bx = bar_x0 + pw
            draw.rounded_rectangle((bx, bar_y, bx + bw, bar_y + bar_h),
                                    radius=bar_h // 2, fill=BANKER_C)
        # T 바
        tw_bar = bar_w - pw - bw
        if tw_bar > 0:
            tx = bar_x0 + pw + bw
            draw.rounded_rectangle((tx, bar_y, tx + tw_bar, bar_y + bar_h),
                                    radius=bar_h // 2, fill=TIE_C)

        # 텍스트
        stats_txt = (
            f"🔵 {p_cnt}회 ({p_pct:.0f}%)    "
            f"🔴 {b_cnt}회 ({b_pct:.0f}%)    "
            f"🟢 {t_cnt}회 ({t_pct:.0f}%)"
        )
        draw.text((_s(PAD), stats_y + _s(12)), stats_txt, font=fnt_stats, fill=MUTED)

    # ── 슈퍼샘플링 다운스케일 ─────────────────────────────────────────────
    out = img.convert("RGB").resize((total_w, total_h), Image.LANCZOS)

    buf = io.BytesIO()
    out.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
