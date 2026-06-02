"""바카라봇 메시지 포맷."""

from .game import SIDE_EMOJI, SIDE_KOR, dice_label, hand_score


def _fmt(n: int) -> str:
    return f"{n:,}"


def pin_caption(round_no: int, totals: dict, status: str = "betting", remain_sec: int | None = None) -> str:
    """
    totals: {side: (total_amount, bettor_count)}
    status: 'betting' | 'closed' | 'rolling' | 'done'
    """
    p_amt, p_cnt = totals.get("player", (0, 0))
    t_amt, t_cnt = totals.get("tie", (0, 0))
    b_amt, b_cnt = totals.get("banker", (0, 0))

    if status == "betting":
        if remain_sec is not None:
            m, s = divmod(remain_sec, 60)
            time_str = f"{m}분 {s:02d}초" if m else f"{s}초"
            status_str = f"⏳ 베팅 마감까지 {time_str}"
        else:
            status_str = "⏳ 베팅 진행중"
    elif status == "closed":
        status_str = "🔒 베팅 마감"
    elif status == "rolling":
        status_str = "🎲 주사위 굴리는 중..."
    else:
        status_str = "✅ 결과 확정"

    return (
        f"🎲 바카라  |  제 <b>{round_no}</b>회차  |  {status_str}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📊 베팅 현황\n"
        f"🔵 플레이어: <b>{_fmt(p_amt)}🥕</b> ({p_cnt}명)\n"
        f"🟢 타이: <b>{_fmt(t_amt)}🥕</b> ({t_cnt}명)\n"
        f"🔴 뱅커: <b>{_fmt(b_amt)}🥕</b> ({b_cnt}명)\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💡 /베팅 [금액] → 버튼 선택"
    )


def round_open(round_no: int) -> str:
    return (
        f"🎲 <b>제 {round_no}회차 시작!</b>\n"
        f"베팅 기간: <b>1분 50초</b>\n"
        f"<i>/베팅 명령어로 참여하세요</i>"
    )


def betting_closed(round_no: int, totals: dict) -> str:
    p_amt, p_cnt = totals.get("player", (0, 0))
    t_amt, t_cnt = totals.get("tie", (0, 0))
    b_amt, b_cnt = totals.get("banker", (0, 0))
    return (
        f"🔒 <b>제 {round_no}회차 베팅 마감!</b>\n"
        f"10초 후 주사위를 굴립니다.\n\n"
        f"🔵 플레이어: <b>{_fmt(p_amt)}🥕</b> ({p_cnt}명)\n"
        f"🟢 타이: <b>{_fmt(t_amt)}🥕</b> ({t_cnt}명)\n"
        f"🔴 뱅커: <b>{_fmt(b_amt)}🥕</b> ({b_cnt}명)"
    )


def round_result(round_no: int, p_dice: list, b_dice: list, result: str, bets: list, payouts: dict) -> str:
    p_score = hand_score(p_dice)
    b_score = hand_score(b_dice)

    result_line = {
        "player": "🔵 <b>플레이어 승!</b>",
        "banker": "🔴 <b>뱅커 승!</b>",
        "tie":    "🟢 <b>타이!</b>",
    }[result]

    lines = [
        f"🎲 <b>제 {round_no}회차 결과</b>",
        "",
        f"🔵 플레이어  {dice_label(p_dice)} = <b>{p_score}점</b>",
        f"🔴 뱅커      {dice_label(b_dice)} = <b>{b_score}점</b>",
        "━━━━━━━━━",
        result_line,
    ]

    # 타이 시 플레이어/뱅커 베팅은 push(원금반환)도 포함
    paid = [(b, payouts.get(b["user_id"], 0)) for b in bets if payouts.get(b["user_id"], 0) > 0]
    if paid:
        lines.append("")
        lines.append("💰 지급 내역")
        for bet, payout in paid:
            name = bet["username"] or str(bet["user_id"])
            if result == "tie" and bet["side"] != "tie":
                lines.append(f"🔄 <b>{name}</b>  {_fmt(bet['amount'])}🥕 → <b>{_fmt(payout)}🥕</b> (반환)")
            else:
                lines.append(f"🏷 <b>{name}</b>  {_fmt(bet['amount'])}🥕 → <b>{_fmt(payout)}🥕</b>")

    return "\n".join(lines)


def idle_notice() -> str:
    return (
        "😴 <b>베팅이 없어 게임을 중단합니다.</b>\n"
        "<i>/베팅 명령어로 다시 시작할 수 있습니다.</i>"
    )


def bet_select_prompt(amount: int, balance: int) -> str:
    return (
        f"베팅 금액: <b>{_fmt(amount)}🥕</b>  |  잔액: <b>{_fmt(balance)}🥕</b>\n"
        f"베팅할 곳을 선택하세요:"
    )


def bet_side_selected(side: str, balance: int) -> str:
    kor = {"player": "플레이어", "banker": "뱅커", "tie": "타이"}[side]
    emoji = {"player": "🔵", "banker": "🔴", "tie": "🟢"}[side]
    return (
        f"{emoji} <b>{kor}</b> 선택됨\n"
        f"잔액: <b>{_fmt(balance)}🥕</b>\n"
        f"베팅 금액을 입력하세요:"
    )


def bet_success(side: str, amount: int) -> str:
    kor = {"player": "플레이어", "banker": "뱅커", "tie": "타이"}[side]
    emoji = {"player": "🔵", "banker": "🔴", "tie": "🟢"}[side]
    return f"✅ {emoji} <b>{kor}</b>에 <b>{_fmt(amount)}🥕</b> 베팅 완료!"


def bet_error(msg: str) -> str:
    return f"❌ {msg}"
