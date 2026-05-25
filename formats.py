def fmt_num(n: int) -> str:
    return f"{n:,}"


def my_info(username: str | None, daily: int, total: int, points: int) -> str:
    name = f"@{username}" if username else "알 수 없음"
    return (
        f"<blockquote>👤 <b>내 정보</b></blockquote>\n"
        f"🗣 <b>{name}</b>\n\n"
        f"✉️ <i>오늘 채팅</i>      <b>{fmt_num(daily)}</b>\n"
        f"📮 <i>누적 채팅</i>      <b>{fmt_num(total)}</b>\n\n"
        f"🥕 <i>보유 당근</i>   <b><u>{fmt_num(points)} 🥕</u></b>"
    )


def rank_select() -> str:
    return (
        "<blockquote>🏆 <b>랭킹</b></blockquote>\n"
        "<i>보고 싶은 랭킹을 골라줘 👇</i>"
    )


MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


def rank_page(title: str, rows: list, page: int, total_pages: int, value_key: str = "chat_count") -> str:
    offset = page * 10
    lines = [f"<blockquote>{title}  <i>· {offset+1}~{offset+len(rows)}위</i></blockquote>\n"]
    for i, row in enumerate(rows):
        rank = offset + i + 1
        name = f"@{row['username']}" if row["username"] else str(row["user_id"])
        val = fmt_num(row[value_key])
        medal = MEDALS.get(rank)
        if medal:
            lines.append(f"{medal} <b>{name}</b>  —  <b>{val}</b>")
        else:
            lines.append(f"<b>{rank}.</b> {name}  —  {val}")
    if title.startswith("📅"):
        lines.append("\n<i>🕛 자정에 1위부터 당근 차등 지급</i>")
    return "\n".join(lines)


def surprise_appear(points: int) -> str:
    return (
        f"⚡️돌발 포인트!\n"
        f"🥕 +{fmt_num(points)}"
    )


def surprise_winner(username: str | None, points: int) -> str:
    name = f"@{username}" if username else "누군가"
    return (
        f"<blockquote>🎉 <b>당첨!</b></blockquote>\n"
        f"🏷 <b>{name}</b> 님이\n"
        f"🥕 <b><u>+{fmt_num(points)} 🥕</u></b> 획득 ⚡️"
    )


def lottery_result(n: int, winner_username: str | None) -> str:
    name = f"@{winner_username}" if winner_username else "알 수 없음"
    return (
        f"<blockquote>🎲 <b>추첨 결과</b></blockquote>\n"
        f"<i>당일 채팅 1~{n}위 중에서…</i>\n\n"
        f"🎯 당첨자 → <b>{name}</b> 🎉\n"
        f"<tg-spoiler>두구두구… 축하해요!</tg-spoiler>"
    )


def no_permission() -> str:
    return "❌ <i>관리자만 쓸 수 있어요</i>"


def group_only() -> str:
    return "❌ <i>그룹에서만 사용할 수 있어요</i>"


def point_cmd_result(username: str | None, delta: int, memo: str) -> str:
    name = f"@{username}" if username else "유저"
    sign = "+" if delta >= 0 else ""
    emoji = "🥕" if delta >= 0 else "🔴"
    reason = f"\n📝 <i>{memo}</i>" if memo else ""
    return (
        f"<blockquote>{emoji} <b>당근 {'지급' if delta >= 0 else '차감'}</b></blockquote>\n"
        f"🏷 <b>{name}</b>\n"
        f"🥕 <b><u>{sign}{fmt_num(delta)} 🥕</u></b>{reason}"
    )


def checkin_success(username: str | None, points: int) -> str:
    name = f"@{username}" if username else "누군가"
    return (
        f"<blockquote>✅ <b>출석 완료!</b></blockquote>\n"
        f"🏷 <b>{name}</b>\n"
        f"🥕 <b><u>+{fmt_num(points)} 🥕</u></b> 지급됐어요 🎉"
    )


def checkin_already(username: str | None) -> str:
    name = f"@{username}" if username else "누군가"
    return (
        f"<blockquote>⏰ <b>이미 출석했어요</b></blockquote>\n"
        f"🏷 <b>{name}</b>\n"
        f"<i>내일 다시 출석해줘요!</i>"
    )
