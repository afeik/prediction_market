"""LMSR (Logarithmic Market Scoring Rule) pricing for binary YES/NO markets.

Market state is two share quantities (q_yes, q_no) and a liquidity
parameter b. The market maker always quotes a price, so trades execute
instantly without needing a matching counterparty — ideal for a small group.
"""
from __future__ import annotations

import math


def _logsumexp(a: float, b: float) -> float:
    """Numerically stable log(exp(a) + exp(b))."""
    m = max(a, b)
    return m + math.log(math.exp(a - m) + math.exp(b - m))


def cost(q_yes: float, q_no: float, b: float) -> float:
    """LMSR cost function C(q) = b * log(exp(q_yes/b) + exp(q_no/b))."""
    return b * _logsumexp(q_yes / b, q_no / b)


def prob_yes(q_yes: float, q_no: float, b: float) -> float:
    """Current YES probability (the market price), a stable softmax."""
    m = max(q_yes, q_no) / b
    ey = math.exp(q_yes / b - m)
    en = math.exp(q_no / b - m)
    return ey / (ey + en)


def cost_to_buy(q_yes: float, q_no: float, b: float, side: str, shares: float) -> float:
    """Coins required to buy `shares` of `side` ('yes' or 'no')."""
    base = cost(q_yes, q_no, b)
    if side == "yes":
        return cost(q_yes + shares, q_no, b) - base
    return cost(q_yes, q_no + shares, b) - base


def proceeds_from_sell(q_yes: float, q_no: float, b: float, side: str, shares: float) -> float:
    """Coins received for selling `shares` of `side` back to the market maker."""
    base = cost(q_yes, q_no, b)
    if side == "yes":
        return base - cost(q_yes - shares, q_no, b)
    return base - cost(q_yes, q_no - shares, b)


def shares_for_budget(
    q_yes: float, q_no: float, b: float, side: str, budget: float, tol: float = 1e-9
) -> float:
    """Invert the cost function: how many shares `budget` coins buys (bisection)."""
    if budget <= 0:
        return 0.0
    lo, hi = 0.0, 1.0
    while cost_to_buy(q_yes, q_no, b, side, hi) < budget:
        hi *= 2
        if hi > 1e9:
            break
    for _ in range(200):
        mid = (lo + hi) / 2
        if cost_to_buy(q_yes, q_no, b, side, mid) < budget:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    return (lo + hi) / 2


def max_market_maker_loss(b: float) -> float:
    """Worst-case subsidy the market maker can lose on a binary market."""
    return b * math.log(2)
