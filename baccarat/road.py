"""
바카라 그림장 이미지 생성 (Big Road + Bead Road).
"""

import io
import os
from PIL import Image, ImageDraw, ImageFont

FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "NanumGothicBold.ttf")

# 색상
BG_COLOR       = (18, 38, 18)
GRID_COLOR     = (40, 70, 40)
PLAYER_COLOR   = (200, 50, 50)     # 빨강
BANKER_COLOR   = (50, 100, 220)    # 파랑
TIE_COLOR      = (40, 180, 80)     # 초록
TIE_LINE_COLOR = (40, 180, 80)
TEXT_COLOR     = (240, 240, 240)
HEADER_BG      = (12, 28, 12)
LABEL_COLOR    = (180, 200, 180)
SHADOW_COLOR   = (0, 0, 0, 120)

CELL  = 38   # 셀 크기
PAD   = 10   # 전체 패딩
GAP   = 14   # Big Road / Bead Road 사이 여백
ROWS  = 6
BR_COLS = 25  # Big Road 표시 컬럼 수
BD_COLS = 10  # Bead Road 표시 컬럼 수 (6행 × 10열 = 60개)


def _font(size: int):
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except Exception:
        return ImageFont.load_default()


def _side_color(side: str) -> tuple:
    return {"player": PLAYER_COLOR, "banker": BANKER_COLOR, "tie": TIE_COLOR}.get(side, TEXT_COLOR)


def _draw_circle(draw: ImageDraw.Draw, cx: int, cy: int, r: int, color: tuple, tie_count: int = 0):
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color, outline=(255, 255, 255, 60), width=1)
    letter = {"player": "P", "banker": "B", "tie": "T"}.get(
        {PLAYER_COLOR: "player", BANKER_COLOR: "banker", TIE_COLOR: "tie"}.get(color, ""), ""
    )
    if letter:
        fnt = _font(max(10, r - 4))
        bbox = draw.textbbox((0, 0), letter, font=fnt)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((cx - tw // 2, cy - th // 2 - 1), letter, font=fnt, fill=TEXT_COLOR)
    if tie_count > 0:
        fnt_small = _font(max(8, r - 8))
        label = str(tie_count)
        bbox = draw.textbbox((0, 0), label, font=fnt_small)
        tw2 = bbox[2] - bbox[0]
        draw.text((cx - tw2 // 2 + r - 4, cy - r + 1), label, font=fnt_small, fill=TIE_LINE_COLOR)


def build_big_road(history: list[str]):
    """
    Returns list of columns: each column = list of (result, tie_count).
    Tie attaches to previous cell, does not start new column.
    """
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


def build_bead_road(history: list[str]):
    """Returns flat list of results (latest BD_COLS*ROWS entries), filled col-by-col."""
    return list(history)[-(BD_COLS * ROWS):]


def generate_road_image(history: list[str], round_no: int) -> bytes:
    """
    history: list of 'player'|'banker'|'tie' (oldest first)
    Returns PNG bytes.
    """
    # 크기 계산
    br_w = BR_COLS * CELL
    bd_w = BD_COLS * CELL
    grid_h = ROWS * CELL
    header_h = 28
    label_h = 22

    total_w = PAD + br_w + GAP + bd_w + PAD
    total_h = PAD + header_h + label_h + grid_h + PAD

    img = Image.new("RGB", (total_w, total_h), BG_COLOR)
    draw = ImageDraw.Draw(img, "RGBA")

    fnt_label = _font(12)
    fnt_header = _font(13)

    # 헤더 배경
    draw.rectangle((0, 0, total_w, PAD + header_h), fill=HEADER_BG)

    # 타이틀
    title = f"🎲 바카라  |  제 {round_no}회차"
    draw.text((PAD, PAD + 5), title, font=fnt_header, fill=TEXT_COLOR)

    # 범례
    legend_x = total_w - 130
    legend_y = PAD + 6
    for i, (label, color) in enumerate([("P 플레이어", PLAYER_COLOR), ("B 뱅커", BANKER_COLOR), ("T 타이", TIE_COLOR)]):
        draw.ellipse((legend_x + i * 44, legend_y + 3, legend_x + i * 44 + 9, legend_y + 12), fill=color)
        draw.text((legend_x + i * 44 + 12, legend_y), label[2:], font=_font(9), fill=LABEL_COLOR)

    y_start = PAD + header_h + label_h

    # ─── Big Road ───────────────────────────────────────────────
    br_x = PAD
    draw.text((br_x + 2, PAD + header_h + 3), "빅로드", font=fnt_label, fill=LABEL_COLOR)

    # 격자
    for r in range(ROWS + 1):
        y = y_start + r * CELL
        draw.line((br_x, y, br_x + br_w, y), fill=GRID_COLOR, width=1)
    for c in range(BR_COLS + 1):
        x = br_x + c * CELL
        draw.line((x, y_start, x, y_start + grid_h), fill=GRID_COLOR, width=1)

    columns = build_big_road(history)
    # 표시할 마지막 BR_COLS 컬럼만
    visible_cols = columns[-BR_COLS:] if len(columns) > BR_COLS else columns
    col_offset = BR_COLS - len(visible_cols)

    for ci, col in enumerate(visible_cols):
        for ri, (result, tie_count) in enumerate(col):
            cx = br_x + (col_offset + ci) * CELL + CELL // 2
            cy = y_start + ri * CELL + CELL // 2
            r_px = CELL // 2 - 4
            _draw_circle(draw, cx, cy, r_px, _side_color(result), tie_count)

    # ─── Bead Road ──────────────────────────────────────────────
    bd_x = PAD + br_w + GAP
    draw.text((bd_x + 2, PAD + header_h + 3), "구슬길", font=fnt_label, fill=LABEL_COLOR)

    for r in range(ROWS + 1):
        y = y_start + r * CELL
        draw.line((bd_x, y, bd_x + bd_w, y), fill=GRID_COLOR, width=1)
    for c in range(BD_COLS + 1):
        x = bd_x + c * CELL
        draw.line((x, y_start, x, y_start + grid_h), fill=GRID_COLOR, width=1)

    bead = build_bead_road(history)
    for idx, result in enumerate(bead):
        col_i = idx // ROWS
        row_i = idx % ROWS
        if col_i >= BD_COLS:
            break
        cx = bd_x + col_i * CELL + CELL // 2
        cy = y_start + row_i * CELL + CELL // 2
        r_px = CELL // 2 - 4
        _draw_circle(draw, cx, cy, r_px, _side_color(result))

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
