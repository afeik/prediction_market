"""La Repubblica dei Pronostici — an internal, multi-user prediction market.

Run locally:
    streamlit run app.py

Traders register their own accounts (the first account becomes admin),
start with 1000 virtual coins, and trade YES/NO shares against an LMSR
market maker. The admin creates and resolves markets.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import market as mkt
import pricing
from db import init_db

st.set_page_config(page_title="Repubblica dei Pronostici", page_icon="🎲", layout="wide")
init_db()

if "user" not in st.session_state:
    st.session_state.user = None


# --------------------------------------------------------------------------- #
# Auth screen
# --------------------------------------------------------------------------- #
def auth_screen() -> None:
    st.title("🎲 La Repubblica dei Pronostici")
    st.caption("Trade predictions with friends using virtual coins.")

    first_user = mkt.user_count() == 0
    if first_user:
        st.info("No accounts yet — the first account you create becomes the **admin**.")

    tab_login, tab_register = st.tabs(["Log in", "Register"])

    with tab_login:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Log in", width="stretch"):
                user = mkt.authenticate(username, password)
                if user:
                    st.session_state.user = user
                    st.rerun()
                else:
                    st.error("Wrong username or password.")

    with tab_register:
        with st.form("register_form"):
            username = st.text_input("Choose a username")
            password = st.text_input("Choose a password", type="password")
            if st.form_submit_button("Create account", width="stretch"):
                try:
                    user = mkt.register_user(username, password, is_admin=first_user)
                    st.session_state.user = user
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
def sidebar(user: dict) -> None:
    with st.sidebar:
        st.markdown(f"### 👤 {user['username']}")
        balance = mkt.get_user(user["id"])["balance"]
        st.metric("Balance", f"{balance:,.1f} coins")
        if user["is_admin"]:
            st.caption("🛠️ admin")
        if st.button("Log out", width="stretch"):
            st.session_state.user = None
            st.rerun()


# --------------------------------------------------------------------------- #
# Markets tab
# --------------------------------------------------------------------------- #
def markets_tab(user: dict) -> None:
    uid = user["id"]
    balance = mkt.get_user(uid)["balance"]
    positions = {p["market_id"]: p for p in mkt.get_positions(uid)}
    open_markets = mkt.list_markets(status="open")

    if not open_markets:
        st.info("No open markets yet. Ask the admin to create one.")
        return

    for m in open_markets:
        p = m["prob_yes"]
        with st.expander(f"{m['question']}  ·  YES {p * 100:.1f}%", expanded=True):
            if m["description"]:
                st.caption(m["description"])
            st.progress(p, text=f"YES {p * 100:.1f}%   |   NO {(1 - p) * 100:.1f}%")

            trade_col, pos_col = st.columns([3, 2])

            with trade_col:
                st.markdown("**Place a trade**")
                side = st.radio(
                    "Outcome", ["YES", "NO"], horizontal=True, key=f"side_{m['id']}"
                ).lower()
                spend = st.number_input(
                    "Spend (coins)",
                    min_value=1.0,
                    max_value=max(1.0, float(balance)),
                    value=min(25.0, max(1.0, float(balance))),
                    step=5.0,
                    key=f"spend_{m['id']}",
                )
                shares = pricing.shares_for_budget(m["q_yes"], m["q_no"], m["b"], side, spend)
                if side == "yes":
                    p_after = pricing.prob_yes(m["q_yes"] + shares, m["q_no"], m["b"])
                else:
                    p_after = pricing.prob_yes(m["q_yes"], m["q_no"] + shares, m["b"])

                st.write(
                    f"≈ **{shares:.1f} {side.upper()}** shares  ·  "
                    f"price **{p * 100:.1f}% → {p_after * 100:.1f}%**"
                )
                st.caption(f"Max payout if {side.upper()} wins: {shares:.1f} coins")

                if st.button(f"Buy {side.upper()} for {spend:.0f}", key=f"buy_{m['id']}"):
                    try:
                        mkt.execute_trade(uid, m["id"], side, "buy", shares)
                        st.success(f"Bought {shares:.1f} {side.upper()} shares.")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))

            with pos_col:
                st.markdown("**Your position**")
                pos = positions.get(m["id"])
                if pos and (pos["yes_shares"] > 0 or pos["no_shares"] > 0):
                    st.write(
                        f"YES: **{pos['yes_shares']:.1f}**  ·  NO: **{pos['no_shares']:.1f}**"
                    )
                    st.caption(f"Mark-to-market value: {pos['value']:.1f} coins")
                    sc1, sc2 = st.columns(2)
                    with sc1:
                        if pos["yes_shares"] > 0 and st.button(
                            "Sell all YES", key=f"sell_yes_{m['id']}"
                        ):
                            mkt.execute_trade(uid, m["id"], "yes", "sell", pos["yes_shares"])
                            st.rerun()
                    with sc2:
                        if pos["no_shares"] > 0 and st.button(
                            "Sell all NO", key=f"sell_no_{m['id']}"
                        ):
                            mkt.execute_trade(uid, m["id"], "no", "sell", pos["no_shares"])
                            st.rerun()
                else:
                    st.caption("No shares yet.")

            trades = mkt.recent_trades(market_id=m["id"], limit=8)
            if trades:
                st.markdown("**Recent activity**")
                df = pd.DataFrame(trades)
                df["price"] = (df["prob_after"] * 100).round(1)
                st.dataframe(
                    df[["user", "action", "side", "shares", "cost", "price"]].round(1),
                    hide_index=True,
                    width="stretch",
                )


# --------------------------------------------------------------------------- #
# Portfolio tab
# --------------------------------------------------------------------------- #
def portfolio_tab(user: dict) -> None:
    info = mkt.get_user(user["id"])
    positions = mkt.get_positions(user["id"])
    pos_value = sum(p["value"] for p in positions)

    c1, c2, c3 = st.columns(3)
    c1.metric("Cash", f"{info['balance']:,.1f}")
    c2.metric("Open positions value", f"{pos_value:,.1f}")
    c3.metric("Net worth", f"{info['balance'] + pos_value:,.1f}")

    if positions:
        df = pd.DataFrame(positions)
        df["YES %"] = (df["prob_yes"] * 100).round(1)
        show = df[["question", "yes_shares", "no_shares", "YES %", "value", "status"]]
        st.dataframe(show.round(1), hide_index=True, width="stretch")
    else:
        st.info("You don't hold any shares yet.")


# --------------------------------------------------------------------------- #
# Leaderboard tab
# --------------------------------------------------------------------------- #
def leaderboard_tab() -> None:
    rows = mkt.leaderboard()
    df = pd.DataFrame(rows)
    df.index = range(1, len(df) + 1)
    df.index.name = "Rank"
    st.dataframe(
        df.rename(columns={"username": "Trader", "cash": "Cash", "net_worth": "Net worth"}).round(1),
        width="stretch",
    )


# --------------------------------------------------------------------------- #
# Admin tab
# --------------------------------------------------------------------------- #
def admin_tab() -> None:
    st.markdown("### Create a market")
    with st.form("create_market"):
        question = st.text_input("Question", placeholder="Will Italy beat Spain?")
        description = st.text_area(
            "Resolution rules",
            placeholder="Resolved by the result after 90 minutes + stoppage time.",
        )
        b = st.slider("Liquidity (b) — higher = harder to move price", 20, 400, 100, step=10)
        if st.form_submit_button("Create market"):
            try:
                mkt.create_market(question, description, float(b))
                st.success("Market created.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    st.markdown("### Resolve a market")
    open_markets = mkt.list_markets(status="open")
    if not open_markets:
        st.info("No open markets to resolve.")
        return
    labels = {f"{m['question']} (YES {m['prob_yes'] * 100:.0f}%)": m["id"] for m in open_markets}
    choice = st.selectbox("Market", list(labels.keys()))
    c1, c2 = st.columns(2)
    if c1.button("Resolve YES", width="stretch"):
        mkt.resolve_market(labels[choice], "yes")
        st.success("Resolved YES — winners paid out.")
        st.rerun()
    if c2.button("Resolve NO", width="stretch"):
        mkt.resolve_market(labels[choice], "no")
        st.success("Resolved NO — winners paid out.")
        st.rerun()


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    user = st.session_state.user
    if user is None:
        auth_screen()
        return

    sidebar(user)
    st.title("🎲 La Repubblica dei Pronostici")

    tabs = ["📈 Markets", "💼 Portfolio", "🏆 Leaderboard"]
    if user["is_admin"]:
        tabs.append("🛠️ Admin")
    rendered = st.tabs(tabs)

    with rendered[0]:
        markets_tab(user)
    with rendered[1]:
        portfolio_tab(user)
    with rendered[2]:
        leaderboard_tab()
    if user["is_admin"]:
        with rendered[3]:
            admin_tab()


main()
