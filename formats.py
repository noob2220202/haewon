import json


def fmt_num(n: int) -> str:
    return f"{n:,}"


def settle_page(all_rewarded: list, page: int, total_pages: int) -> str:
    per_page = 10
    offset = page * per_page
    rows = all_rewarded[offset:offset + per_page]
    lines = [f"<blockquote>📊 <b>어제 정산 완료!</b>  <i>· {offset+1}~{offset+len(rows)}위</i></blockquote>\n"]
    for rank, row, pts in rows:
        name = f"@{row['username']}" if row["username"] else str(row["user_id"])
        chat = fmt_num(row["chat_count"])
        lines.append(f"🥕 <b>{rank}.</b> {name}  {chat}회 → <b>+{fmt_num(pts)}</b>")
    lines.append(f"\n<i>총 {fmt_num(len(all_rewarded))}명 당근 지급 완료 🎉</i>")
    return "\n".join(lines)


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


def lotto_main(ticket_count: int, balance: int, price: int, jackpot: int, pool: int, draw_id: int) -> str:
    total_prize = jackpot + pool
    return (
        f"<blockquote>🎰 <b>로또</b>  |  회차 #{draw_id}</blockquote>\n"
        f"💰 보유 당근: <b>{fmt_num(balance)}🥕</b>\n"
        f"🎫 보유 티켓: <b>{ticket_count}장</b>\n"
        f"🏆 현재 당첨금: <b><u>{fmt_num(total_prize)}🥕</u></b>"
    )


def lotto_prize_info(jackpot: int, pool: int, price: int, mode: str,
                     p3_fixed: int, p4_fixed: int, p5_fixed: int,
                     p3_pct: int, p4_pct: int, p5_pct: int) -> str:
    total = jackpot + pool
    if mode == "pool":
        prize5 = int(total * p5_pct / 100)
        prize4 = int(pool * p4_pct / 100)
        prize3 = int(pool * p3_pct / 100)
        tier5 = f"{fmt_num(prize5)}🥕  ({p5_pct}%)"
        tier4 = f"{fmt_num(prize4)}🥕  ({p4_pct}%)"
        tier3 = f"{fmt_num(prize3)}🥕  ({p3_pct}%)"
    else:
        tier5 = f"{fmt_num(p5_fixed if p5_fixed else total)}🥕" + (" (이월 전액)" if not p5_fixed else "")
        tier4 = f"{fmt_num(p4_fixed)}🥕"
        tier3 = f"{fmt_num(p3_fixed)}🥕"
    tickets = pool // price if price else 0
    return (
        f"<blockquote>💰 <b>당첨금 현황</b></blockquote>\n"
        f"🎫 이번 회차 판매: <b>{fmt_num(pool)}🥕</b>  ({tickets}장)\n"
        f"🔄 이월 잭팟: <b>{fmt_num(jackpot)}🥕</b>\n"
        f"🏆 총 당첨금 풀: <b><u>{fmt_num(total)}🥕</u></b>\n"
        f"━━━━━━━━━\n"
        f"🥇 1등 (5개): <b>{tier5}</b>\n"
        f"🥈 2등 (4개): <b>{tier4}</b>\n"
        f"🥉 3등 (3개): <b>{tier3}</b>"
    )


def lotto_my_tickets(tickets: list, draw_id: int) -> str:
    if not tickets:
        return (
            f"<blockquote>🎫 <b>내 티켓  |  회차 #{draw_id}</b></blockquote>\n"
            f"<i>아직 구매한 티켓이 없어요</i>"
        )
    lines = [f"<blockquote>🎫 <b>내 티켓  |  회차 #{draw_id}  ({len(tickets)}장)</b></blockquote>"]
    for i, t in enumerate(tickets, 1):
        nums = json.loads(t["numbers"])
        lines.append(f"  {i}. <b>{' · '.join(str(n) for n in nums)}</b>")
    return "\n".join(lines)


def lotto_buy_menu(balance: int, price: int, bought: int, max_tickets: int) -> str:
    remain = max_tickets - bought
    return (
        f"<blockquote>🎰 <b>구매 방식 선택</b></blockquote>\n"
        f"💰 잔액: <b>{fmt_num(balance)}🥕</b>  |  장당 <b>{fmt_num(price)}🥕</b>\n"
        f"구매 가능 잔여: <b>{remain}장</b>"
    )


def lotto_select_prompt(selected: set, price: int, max_tickets: int, bought: int) -> str:
    cnt = len(selected)
    nums_str = " ".join(str(n) for n in sorted(selected)) if selected else "—"
    remain = max_tickets - bought
    return (
        f"<blockquote>🎰 <b>번호 선택</b>  ({cnt}/5)</blockquote>\n"
        f"선택: <b>{nums_str}</b>\n"
        f"구매 가능 잔여: <b>{remain}장</b>  |  장당 <b>{fmt_num(price)}🥕</b>"
    )


def lotto_bought(numbers: list, balance: int, draw_id: int) -> str:
    nums_str = "  ".join(str(n) for n in numbers)
    return (
        f"<blockquote>✅ <b>로또 구매 완료!</b></blockquote>\n"
        f"🎫 번호: <b>{nums_str}</b>\n"
        f"💰 잔여 당근: <b>{fmt_num(balance)}🥕</b>\n"
        f"<i>추첨은 매일 자정에 진행됩니다 🌙</i>"
    )


def lotto_result(draw_id: int, winning: list, winners: dict, jackpot_total: int, carry: int) -> str:
    nums_str = "  ".join(str(n) for n in winning)
    lines = [
        f"<blockquote>🎰 <b>로또 #{draw_id} 추첨 결과!</b></blockquote>",
        f"🎯 당첨번호: <b>{nums_str}</b>",
        "",
    ]
    if winners.get(5):
        for w in winners[5]:
            name = f"@{w['username']}" if w.get("username") else str(w["user_id"])
            lines.append(f"🥇 <b>{name}</b>  5개 일치 → <b>+{fmt_num(w['payout'])}🥕</b>")
    else:
        lines.append(f"🥇 5개 일치 당첨자 없음 → 잭팟 <b>{fmt_num(carry)}🥕</b> 이월!")
    if winners.get(4):
        for w in winners[4]:
            name = f"@{w['username']}" if w.get("username") else str(w["user_id"])
            lines.append(f"🥈 <b>{name}</b>  4개 일치 → <b>+{fmt_num(w['payout'])}🥕</b>")
    if winners.get(3):
        for w in winners[3]:
            name = f"@{w['username']}" if w.get("username") else str(w["user_id"])
            lines.append(f"🥉 <b>{name}</b>  3개 일치 → <b>+{fmt_num(w['payout'])}🥕</b>")
    if not winners.get(4) and not winners.get(3) and not winners.get(5):
        lines.append("<i>이번 회차 당첨자 없음</i>")
    return "\n".join(lines)


def lotto_win_dm(grade: int, numbers: list, winning: list, payout: int, draw_id: int) -> str:
    medal = {5: "🥇", 4: "🥈", 3: "🥉"}[grade]
    my_nums = "  ".join(str(n) for n in numbers)
    win_nums = "  ".join(str(n) for n in winning)
    matched = sorted(set(numbers) & set(winning))
    match_str = "  ".join(str(n) for n in matched)
    return (
        f"<blockquote>{medal} <b>로또 당첨!</b></blockquote>\n"
        f"회차 #{draw_id}  |  {grade}개 일치\n\n"
        f"내 번호:     <b>{my_nums}</b>\n"
        f"당첨번호: <b>{win_nums}</b>\n"
        f"일치:         <b>{match_str}</b>\n\n"
        f"🥕 <b><u>+{fmt_num(payout)} 🥕</u></b> 지급됐어요 🎉"
    )


def checkin_already(username: str | None) -> str:
    name = f"@{username}" if username else "누군가"
    return (
        f"<blockquote>⏰ <b>이미 출석했어요</b></blockquote>\n"
        f"🏷 <b>{name}</b>\n"
        f"<i>내일 다시 출석해줘요!</i>"
    )
