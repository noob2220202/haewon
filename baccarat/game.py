"""
바카라 게임 로직.

주사위 1~6을 카드값으로 사용, 패 점수 = sum(cards) % 10.
표준 바카라 3번째 카드 규칙 적용.

배당: Player 2x, Banker 1.95x, Tie 6x
"""

PAYOUTS = {"player": 2.0, "banker": 1.95, "tie": 6.0}

SIDE_KOR = {"player": "플레이어", "banker": "뱅커", "tie": "타이"}
SIDE_EMOJI = {"player": "🔴", "banker": "🔵", "tie": "🟢"}


def hand_score(dice: list[int]) -> int:
    return sum(dice) % 10


def is_natural(score: int) -> bool:
    return score >= 8


def player_draws(score: int) -> bool:
    """플레이어 0~5: 드로우, 6~7: 스탠드, 8~9: 내추럴(호출 전 처리)."""
    return score <= 5


def banker_draws(banker_score: int, player_drew: bool, player_3rd: int | None) -> bool:
    """
    표준 바카라 뱅커 드로우 규칙.
    banker_score: 뱅커 초기 2장 점수
    player_drew: 플레이어가 3번째 카드를 뽑았는지
    player_3rd: 플레이어의 3번째 카드 값 (뽑았을 때만)
    """
    if banker_score >= 7:
        return False
    if not player_drew:
        return banker_score <= 5
    p3 = player_3rd
    if banker_score <= 2:
        return True
    if banker_score == 3:
        return p3 != 8
    if banker_score == 4:
        return 2 <= p3 <= 7
    if banker_score == 5:
        return 4 <= p3 <= 7
    if banker_score == 6:
        return 6 <= p3 <= 7
    return False


def determine_result(p_score: int, b_score: int) -> str:
    if p_score > b_score:
        return "player"
    if b_score > p_score:
        return "banker"
    return "tie"


def calc_payout(side: str, amount: int) -> int:
    """베팅금 × 배당 (내림 처리). 손실 시 0 반환."""
    return int(amount * PAYOUTS[side])


def calc_all_payouts(bets: list, result: str) -> dict:
    """
    bets: [{user_id, side, amount}, ...]
    result: 'player' | 'banker' | 'tie'
    Returns {user_id: payout_amount}  — 패배 시 0
    """
    payouts = {}
    for bet in bets:
        uid = bet["user_id"]
        if bet["side"] == result:
            payouts[uid] = calc_payout(result, bet["amount"])
        else:
            payouts[uid] = 0
    return payouts


def dice_label(dice: list[int]) -> str:
    """예: [3, 5] → '[3][5]'"""
    return "".join(f"[{d}]" for d in dice)
