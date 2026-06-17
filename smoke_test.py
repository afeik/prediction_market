"""End-to-end smoke test of the market logic (no Streamlit, no browser).

Simulates several traders, runs buys/sells against the LMSR market maker,
resolves a market, and prints balances + leaderboard so we can confirm the
maths and the money conservation are correct.

Run with a throwaway database so it never touches real data:
    DATABASE_URL="sqlite:///smoke.db" python smoke_test.py
"""
from __future__ import annotations

import os

# Use an isolated DB file for the test run.
os.environ.setdefault("DATABASE_URL", "sqlite:///smoke.db")

import pricing  # noqa: E402
from db import init_db  # noqa: E402
import market as mkt  # noqa: E402


def main() -> None:
    # Fresh database
    if os.path.exists("smoke.db"):
        os.remove("smoke.db")
    init_db()

    # --- LMSR sanity checks ---------------------------------------------- #
    assert abs(pricing.prob_yes(0, 0, 100) - 0.5) < 1e-9, "empty market should be 50%"
    cost20 = pricing.cost_to_buy(0, 0, 100, "yes", 20)
    print(f"Cost to buy 20 YES from 50%: {cost20:.3f} coins")
    p_after = pricing.prob_yes(20, 0, 100)
    print(f"Price after buying 20 YES:   {p_after * 100:.2f}%")
    assert 0.5 < p_after < 0.6

    # Buying then immediately selling the same shares should be ~cost-neutral
    back = pricing.proceeds_from_sell(20, 0, 100, "yes", 20)
    assert abs(back - cost20) < 1e-6, "round-trip should conserve coins"

    # --- Users ----------------------------------------------------------- #
    andreas = mkt.register_user("andreas", "pw1", is_admin=True)
    marco = mkt.register_user("marco", "pw2")
    luca = mkt.register_user("luca", "pw3")
    print("\nRegistered:", [u["username"] for u in (andreas, marco, luca)])

    assert mkt.authenticate("marco", "pw2") is not None
    assert mkt.authenticate("marco", "wrong") is None
    print("Auth check passed.")

    total_start = sum(mkt.get_user(u["id"])["balance"] for u in (andreas, marco, luca))

    # --- Market + trading ------------------------------------------------ #
    mid = mkt.create_market("Will Italy beat Spain?", "90 min + stoppage.", b=100)

    mkt.execute_trade(andreas["id"], mid, "yes", "buy", 40)   # bullish on Italy
    mkt.execute_trade(marco["id"], mid, "no", "buy", 25)      # backs Spain
    mkt.execute_trade(luca["id"], mid, "yes", "buy", 10)
    mkt.execute_trade(marco["id"], mid, "no", "buy", 15)

    market_state = mkt.list_markets()[0]
    print(f"\nMarket price now: YES {market_state['prob_yes'] * 100:.1f}%")

    print("\nLeaderboard (mark-to-market):")
    for i, row in enumerate(mkt.leaderboard(), 1):
        print(f"  {i}. {row['username']:<8} net {row['net_worth']:8.2f}  (cash {row['cash']:8.2f})")

    # --- Resolve YES (Italy wins) ---------------------------------------- #
    mkt.resolve_market(mid, "yes")
    print("\nResolved YES (Italy won). Final balances:")
    final_rows = mkt.leaderboard()
    for i, row in enumerate(final_rows, 1):
        print(f"  {i}. {row['username']:<8} {row['cash']:8.2f} coins")

    total_end = sum(r["cash"] for r in final_rows)
    subsidy = total_end - total_start
    print(f"\nCoins before: {total_start:.2f}  after: {total_end:.2f}")
    print(f"Market-maker subsidy paid out: {subsidy:.2f} "
          f"(bounded by b*ln2 = {pricing.max_market_maker_loss(100):.2f})")
    assert subsidy <= pricing.max_market_maker_loss(100) + 1e-6

    print("\n✅ All smoke-test checks passed.")


if __name__ == "__main__":
    main()
