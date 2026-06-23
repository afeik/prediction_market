"""Streamlit front-end for the prediction market.

Run locally:
    streamlit run app.py

Traders register accounts, start with 1000 virtual coins, and trade YES/NO
contracts against an LMSR market maker. Admins create and settle markets,
manage users, and can reset the game.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import market as mkt
import pricing
from db import init_db

# Scheduling/display timezone. We persist UTC in the database and present
# everything to traders in Zurich local time (CET in winter, CEST in summer).
ZURICH = ZoneInfo("Europe/Zurich")
UTC = ZoneInfo("UTC")


def to_zurich(dt_utc: datetime | None) -> datetime | None:
    """Naive-UTC datetime (as stored) -> timezone-aware Zurich datetime."""
    if dt_utc is None:
        return None
    return dt_utc.replace(tzinfo=UTC).astimezone(ZURICH)


def zurich_to_utc(dt_local: datetime) -> datetime:
    """Naive Zurich wall-clock datetime -> naive UTC for storage."""
    return dt_local.replace(tzinfo=ZURICH).astimezone(UTC).replace(tzinfo=None)


def fmt_zurich(dt_utc: datetime | None) -> str:
    """Format naive-UTC as Zurich local time, e.g. '18 Jun 2026, 20:00 CEST'."""
    z = to_zurich(dt_utc)
    return z.strftime("%d %b %Y, %H:%M %Z") if z else ""


st.set_page_config(
    page_title="Repubblica dei Pronostici",
    page_icon="📈",
    layout="wide",
)


# --------------------------------------------------------------------------- #
# Bootstrap & caching (keeps reruns snappy against remote Postgres)
# --------------------------------------------------------------------------- #
@st.cache_resource
def _bootstrap(_v: int = 3) -> bool:
    init_db()
    return True


_bootstrap()


@st.cache_data(ttl=2, show_spinner=False)
def cached_markets(status: str | None = "open"):
    return mkt.list_markets(status)


@st.cache_data(ttl=2, show_spinner=False)
def cached_leaderboard():
    return mkt.leaderboard()


@st.cache_data(ttl=2, show_spinner=False)
def cached_trades(market_id: int, limit: int = 8):
    return mkt.recent_trades(market_id, limit)


@st.cache_data(ttl=2, show_spinner=False)
def cached_proposals(status: str | None = None):
    return mkt.list_proposals(status)


def refresh() -> None:
    """Invalidate cached reads after a write, then rerun."""
    st.cache_data.clear()
    st.rerun()


# --------------------------------------------------------------------------- #
# Styling — sleek dark "trading terminal" look
# --------------------------------------------------------------------------- #
def inject_css() -> None:
    st.markdown(
        """
        <style>
        .block-container {padding-top: 2.0rem; max-width: 1160px;}
        [data-testid="stMetricValue"] {font-variant-numeric: tabular-nums; font-weight: 600;
            letter-spacing:.01em;}
        [data-testid="stMetricLabel"] {color: #7d8590; text-transform: uppercase;
            letter-spacing: .06em; font-size: .7rem; font-weight: 600;}
        .pill {display:inline-block; padding:3px 11px; border-radius:6px;
            font-weight:600; font-size:.82rem; font-variant-numeric: tabular-nums; letter-spacing:.02em;}
        .pill-yes {background:rgba(63,185,80,.12); color:#3fb950; border:1px solid rgba(63,185,80,.35);}
        .pill-no  {background:rgba(229,83,75,.12); color:#e5534b; border:1px solid rgba(229,83,75,.35);}
        .pill-closed {background:rgba(125,134,144,.12); color:#7d8590;
            border:1px solid rgba(125,134,144,.35);}
        .tkr {font-size:1.02rem; font-weight:600; letter-spacing:.01em; color:#e6edf3;}
        .muted {color:#7d8590;}
        .pos {color:#3fb950; font-variant-numeric: tabular-nums; font-weight:600;}
        .neg {color:#e5534b; font-variant-numeric: tabular-nums; font-weight:600;}
        .mono {font-variant-numeric: tabular-nums;}
        .market-card {border:1px solid #30363d; border-radius:.6rem;
            padding:1rem 1.15rem; margin-bottom:.75rem; background:#161b22;}
        .market-closed {opacity:.55;}
        hr {margin: .8rem 0; border-color: #30363d;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def pnl_html(value: float, prefix: str = "") -> str:
    cls = "pos" if value >= 0 else "neg"
    sign = "+" if value >= 0 else "−"
    return f'<span class="{cls}">{prefix}{sign}{abs(value):,.0f}</span>'


def render_tape(market_id: int) -> None:
    trades = cached_trades(market_id, 8)
    if trades:
        df = pd.DataFrame(trades)
        df["Time"] = pd.to_datetime(df["time"]).apply(
            lambda t: t.replace(tzinfo=UTC).astimezone(ZURICH).strftime("%d %b %H:%M")
        )
        df["Mark"] = (df["prob_after"] * 100).round(0).astype(int).astype(str) + "%"
        df["Side"] = df["side"].str.upper()
        df["Payout"] = df["shares"].round(0)
        df["Stake"] = df["cost"].round(0)
        st.caption("Recent trades")
        st.dataframe(
            df.rename(columns={"action": "Action"})[
                ["Time", "Action", "Side", "Payout", "Stake", "Mark"]
            ],
            hide_index=True,
            width="stretch",
            height=150,
        )
    else:
        st.caption("No trades yet.")


if "user" not in st.session_state:
    st.session_state.user = None



# --------------------------------------------------------------------------- #
# Auth screen
# --------------------------------------------------------------------------- #
def auth_screen() -> None:
    inject_css()
    st.title("La Repubblica dei Pronostici")
    st.caption("A play-money prediction market. Trade YES/NO contracts on anything — no real cash.")

    first_user = mkt.user_count() == 0
    if first_user:
        st.info("You're the first to register, so your account will be the administrator "
                "(create and settle markets, manage the market).")

    tab_login, tab_register = st.tabs(["Log in", "Register"])

    with tab_login:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Log in", type="primary", width="stretch"):
                user = mkt.authenticate(username, password)
                if user:
                    st.session_state.user = user
                    refresh()
                else:
                    st.error("Wrong username or password.")

    with tab_register:
        with st.form("register_form"):
            username = st.text_input("Choose a username")
            password = st.text_input("Choose a password", type="password")
            if st.form_submit_button("Create account", type="primary", width="stretch"):
                try:
                    user = mkt.register_user(username, password, is_admin=first_user)
                    st.session_state.user = user
                    refresh()
                except ValueError as exc:
                    st.error(str(exc))


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
def sidebar(user: dict, equity: float, cash: float) -> None:
    with st.sidebar:
        st.markdown(f"### {user['username']}")
        st.caption("Administrator" if user["is_admin"] else "Trader")
        st.metric("Equity", f"{equity:,.0f}")
        st.metric("Buying power", f"{cash:,.0f}")
        st.divider()
        if st.button("Refresh", width="stretch"):
            refresh()
        if st.button("Log out", width="stretch"):
            st.session_state.user = None
            refresh()
        st.markdown(
            "<div style='position:fixed;bottom:1rem;left:1rem;font-size:.7rem;color:#7d8590'>"
            "Created by Andreas Feik</div>",
            unsafe_allow_html=True,
        )


# --------------------------------------------------------------------------- #
# Markets tab
# --------------------------------------------------------------------------- #
def markets_tab(user: dict, cash: float, positions: dict) -> None:
    uid = user["id"]
    open_markets = cached_markets("open")

    if not open_markets:
        st.info("No markets are open. An administrator can create one in the Admin tab.")
        return

    # Category filter
    categories = sorted({m.get("category", "Other") for m in open_markets})
    if len(categories) > 1:
        selected = st.pills("Filter", ["All"] + categories, default="All", key="cat_filter")
        if selected and selected != "All":
            open_markets = [m for m in open_markets if m.get("category", "Other") == selected]

    live = [m for m in open_markets if m["trading_open"]]
    closed = [m for m in open_markets if not m["trading_open"]]

    # Sort: expiring soonest first, then markets with no deadline
    live.sort(key=lambda m: (m["close_at"] is None, m["close_at"] or datetime.max))

    for m in live:
        p = m["prob_yes"]
        pos = positions.get(m["id"])
        held_yes = pos["yes_shares"] if pos else 0.0
        held_no = pos["no_shares"] if pos else 0.0

        with st.container(border=True):
            # ---- Always-visible compact summary ---- #
            head_l, head_r = st.columns([4, 1])
            with head_l:
                st.markdown(f"<span class='tkr'>{m['question']}</span>", unsafe_allow_html=True)
                if m["description"]:
                    st.markdown(f"<span class='muted'>{m['description']}</span>", unsafe_allow_html=True)
            with head_r:
                extras = ""
                if held_yes > 0 or held_no > 0:
                    legs = []
                    if held_yes > 0:
                        legs.append(f"YES {held_yes:,.0f}")
                    if held_no > 0:
                        legs.append(f"NO {held_no:,.0f}")
                    extras += (
                        f"<div class='muted' style='font-size:.72rem;margin-top:3px'>"
                        f"📊 {' · '.join(legs)}</div>"
                    )
                if m.get("close_at") is not None:
                    extras += (
                        f"<div class='muted' style='font-size:.72rem;margin-top:3px'>"
                        f"Expires {fmt_zurich(m['close_at'])}</div>"
                    )
                if p >= 0.5:
                    pill = f"<span class='pill pill-yes'>YES {p*100:.0f}%</span>"
                else:
                    pill = f"<span class='pill pill-no'>NO {(1-p)*100:.0f}%</span>"
                st.markdown(
                    f"<div style='text-align:right'>{pill}{extras}</div>",
                    unsafe_allow_html=True,
                )
            yes_pct = p * 100
            no_pct = (1 - p) * 100
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:6px;font-size:.78rem;font-weight:600'>"
                f"<span style='color:#3fb950'>{yes_pct:.0f}%</span>"
                f"<div style='flex:1;display:flex;border-radius:6px;overflow:hidden;height:3px'>"
                f"<div style='background:#3fb950;width:{yes_pct:.1f}%'></div>"
                f"<div style='background:#e5534b;width:{no_pct:.1f}%'></div>"
                f"</div>"
                f"<span style='color:#e5534b'>{no_pct:.0f}%</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

            # ---- Collapsible trade / position panel ---- #
            with st.expander("Trade / Position"):
                trade_col, pos_col = st.columns([3, 2], gap="large")

                # ----- Order ticket (buy) ---------------------------------- #
                with trade_col:
                    st.markdown("##### Trade")
                    amount = st.number_input(
                        "Stake (coins)",
                        min_value=1.0,
                        max_value=max(1.0, float(cash)),
                        value=min(25.0, max(1.0, float(cash))),
                        step=5.0,
                        key=f"amt_{m['id']}",
                    )
                    yes_payout = pricing.shares_for_budget(m["q_yes"], m["q_no"], m["b"], "yes", amount)
                    no_payout = pricing.shares_for_budget(m["q_yes"], m["q_no"], m["b"], "no", amount)
                    p_yes_after = pricing.prob_yes(m["q_yes"] + yes_payout, m["q_no"], m["b"])
                    p_no_after = pricing.prob_yes(m["q_yes"], m["q_no"] + no_payout, m["b"])

                    st.markdown(
                        f"<span class='pill pill-yes'>YES</span> &nbsp;payout "
                        f"<b class='mono'>{yes_payout:,.0f}</b> "
                        f"<span class='muted'>· avg {amount/yes_payout*100:.0f}¢ · mark "
                        f"{p*100:.0f}→{p_yes_after*100:.0f}%</span>",
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f"<span class='pill pill-no'>NO</span> &nbsp;payout "
                        f"<b class='mono'>{no_payout:,.0f}</b> "
                        f"<span class='muted'>· avg {amount/no_payout*100:.0f}¢ · mark "
                        f"{(1-p)*100:.0f}→{(1-p_no_after)*100:.0f}%</span>",
                        unsafe_allow_html=True,
                    )

                    by, bn = st.columns(2)
                    if by.button("Buy YES", key=f"yes_{m['id']}", type="primary", width="stretch"):
                        try:
                            mkt.execute_trade(uid, m["id"], "yes", "buy", yes_payout)
                            refresh()
                        except ValueError as exc:
                            st.error(str(exc))
                    if bn.button("Buy NO", key=f"no_{m['id']}", width="stretch"):
                        try:
                            mkt.execute_trade(uid, m["id"], "no", "buy", no_payout)
                            refresh()
                        except ValueError as exc:
                            st.error(str(exc))

                # ----- Current position (hold / sell) ---------------------- #
                with pos_col:
                    st.markdown("##### Your position")
                    if held_yes > 0 or held_no > 0:
                        for leg_side, qty in (("YES", held_yes), ("NO", held_no)):
                            if qty <= 0:
                                continue
                            sell_side = leg_side.lower()
                            proceeds = pricing.proceeds_from_sell(
                                m["q_yes"], m["q_no"], m["b"], sell_side, qty
                            )
                            st.markdown(
                                f"<span class='pill pill-{sell_side}'>{leg_side}</span> "
                                f"payout <b class='mono'>{qty:,.0f}</b>",
                                unsafe_allow_html=True,
                            )
                            if st.button(
                                f"Close {leg_side} for ≈ {proceeds:,.0f}",
                                key=f"close_{sell_side}_{m['id']}",
                                width="stretch",
                            ):
                                mkt.execute_trade(uid, m["id"], sell_side, "sell", qty)
                                refresh()
                        st.markdown(
                            f"<div style='margin-top:.4rem'>"
                            f"<span class='muted'>Mark value</span> <b class='mono'>{pos['value']:,.0f}</b>"
                            f" · <span class='muted'>P&amp;L</span> {pnl_html(pos['pnl'])}</div>",
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown(
                            "<span class='muted'>No position yet. Buy YES or NO to open one.</span>",
                            unsafe_allow_html=True,
                        )

                render_tape(m["id"])

    if closed:
        st.markdown("##### Closed — awaiting settlement")
        for m in closed:
            p = m["prob_yes"]
            pos = positions.get(m["id"])
            posline = ""
            held = []
            if pos:
                if pos["yes_shares"] > 0:
                    held.append(("YES", pos["yes_shares"]))
                if pos["no_shares"] > 0:
                    held.append(("NO", pos["no_shares"]))
            if held:
                legs_html = " ".join(
                    f"<span class='pill pill-{s.lower()}'>{s}</span> "
                    f"payout <b class='mono'>{q:,.0f}</b>"
                    for s, q in held
                )
                posline = (
                    f"<div style='margin-top:.5rem'><span class='muted'>Your position:</span> "
                    f"{legs_html} · <span class='muted'>P&amp;L</span> {pnl_html(pos['pnl'])}</div>"
                )
            desc = f"<div class='muted'>{m['description']}</div>" if m["description"] else ""
            closed_line = "Awaiting settlement by an administrator."
            if m.get("close_at") is not None:
                closed_line = f"Closed {fmt_zurich(m['close_at'])} · awaiting settlement."
            st.markdown(
                f"""<div class='market-card market-closed'>
  <div style='display:flex;justify-content:space-between;align-items:flex-start'>
    <span class='tkr'>{m['question']}</span>
    <span class='pill pill-closed'>Trading closed</span>
  </div>
  {desc}
  <div style='display:flex;align-items:center;gap:6px;font-size:.78rem;font-weight:600;margin:.45rem 0 .2rem'>
    <span style='color:#3fb950'>{p*100:.0f}%</span>
    <div style='flex:1;display:flex;border-radius:6px;overflow:hidden;height:3px'>
      <div style='background:#3fb950;width:{p*100:.1f}%'></div>
      <div style='background:#e5534b;width:{(1-p)*100:.1f}%'></div>
    </div>
    <span style='color:#e5534b'>{(1-p)*100:.0f}%</span>
  </div>
  {posline}
  <div class='muted' style='margin-top:.55rem;font-size:.85rem'>{closed_line}</div>
</div>""",
                unsafe_allow_html=True,
            )
            render_tape(m["id"])



# --------------------------------------------------------------------------- #
# Portfolio tab
# --------------------------------------------------------------------------- #
def portfolio_tab(cash: float, positions_list: list) -> None:
    active = [
        p for p in positions_list
        if p["status"] == "open" and (p["yes_shares"] > 0 or p["no_shares"] > 0)
    ]
    pos_value = sum(p["value"] for p in active)
    invested = sum(p["invested"] for p in active)
    open_pnl = sum(p["pnl"] for p in active)
    equity = cash + pos_value

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Equity", f"{equity:,.0f}")
    c2.metric("Buying power", f"{cash:,.0f}")
    c3.metric("Market value", f"{pos_value:,.0f}")
    c4.metric("Open P&L", f"{open_pnl:+,.0f}", delta=f"{open_pnl:+,.0f}")

    st.markdown("#### Open positions")
    if not active:
        st.info("No open positions. Open the Markets tab to put on a trade.")
        return

    for p in active:
        ret = (p["pnl"] / p["invested"] * 100) if p["invested"] else 0.0
        legs = [("YES", p["yes_shares"]), ("NO", p["no_shares"])]
        held = [(s, q) for s, q in legs if q > 0]
        sides_html = " ".join(
            f"<span class='pill pill-{s.lower()}'>{s}</span> "
            f"<b class='mono'>{q:,.0f}</b>"
            for s, q in held
        )
        st.markdown(
            f"<div style='display:flex;justify-content:space-between;align-items:center;"
            f"padding:.35rem 0;border-bottom:1px solid #30363d'>"
            f"<span>{sides_html} &nbsp;<b>{p['question']}</b></span>"
            f"<span class='muted'>cost <b class='mono'>{p['invested']:,.0f}</b> · "
            f"value <b class='mono'>{p['value']:,.0f}</b> · "
            f"P&amp;L {pnl_html(p['pnl'])} ({ret:+.0f}%)</span>"
            f"</div>",
            unsafe_allow_html=True,
        )


# --------------------------------------------------------------------------- #
# Leaderboard tab
# --------------------------------------------------------------------------- #
def leaderboard_tab(current_user: dict) -> None:
    rows = cached_leaderboard()
    if not rows:
        st.info("No traders yet.")
        return
    st.markdown("#### Standings — ranked by equity")
    df = pd.DataFrame(rows)
    df.insert(0, "#", range(1, len(df) + 1))
    df["Trader"] = df.apply(
        lambda r: r["username"] + ("  ·  admin" if r["is_admin"] else ""), axis=1
    )
    df["Equity"] = df["net_worth"].round(0)
    df["P&L"] = (df["net_worth"] - mkt.STARTING_BALANCE).round(0)
    show = df[["#", "Trader", "Equity", "P&L"]]
    st.dataframe(
        show,
        hide_index=True,
        width="stretch",
        column_config={
            "P&L": st.column_config.NumberColumn(format="%+d"),
        },
    )
    st.caption(
        f"Equity = buying power + mark-to-market value of open positions. "
        f"Everyone starts at {mkt.STARTING_BALANCE:,.0f}."
    )


# --------------------------------------------------------------------------- #
# History tab
# --------------------------------------------------------------------------- #
def history_tab(user: dict) -> None:
    resolved = cached_markets("resolved")
    if not resolved:
        st.info("No settled markets yet. Once an admin resolves a market, your results appear here.")
        return

    # Get this user's history (only markets they traded in)
    history = mkt.get_history(user["id"])
    traded = {h["market_id"]: h for h in history}

    # Summary metrics (only for markets the user participated in)
    if traded:
        total_pnl = sum(h["pnl"] for h in history)
        wins = sum(1 for h in history if h["pnl"] > 0)
        losses = sum(1 for h in history if h["pnl"] < 0)
        hit_rate = wins / max(1, wins + losses) * 100

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Realised P&L", f"{total_pnl:+,.0f}")
        c2.metric("Wins", str(wins))
        c3.metric("Losses", str(losses))
        c4.metric("Hit rate", f"{hit_rate:.0f}%")

    st.markdown("#### Settled markets")
    for m in resolved:
        h = traded.get(m["id"])
        outcome = (m["outcome"] or "").upper()
        outcome_pill = "pill-yes" if outcome == "YES" else "pill-no"

        if h:
            # ---- Market the user traded in -------------------------------- #
            won = h["pnl"] >= 0
            result_cls = "pos" if won else "neg"
            result_sign = "+" if won else "−"
            # P&L bar — width proportional to |pnl| relative to cost (capped at 100%)
            bar_pct = min(100, abs(h["pnl"]) / max(1, abs(h["cost"])) * 100)
            bar_color = "#3fb950" if won else "#e5534b"

            st.markdown(
                f"""<div class='market-card'>
  <div style='display:flex;justify-content:space-between;align-items:flex-start'>
    <div>
      <span class='tkr'>{m['question']}</span>
      <div style='margin-top:.4rem'>
        <span class='pill {outcome_pill}'>{outcome}</span>
        &nbsp;
        <span class='{result_cls}' style='font-size:.95rem'>{result_sign}{abs(h['pnl']):,.0f} P&amp;L</span>
      </div>
    </div>
    <div style='text-align:right'>
      <div class='muted' style='font-size:.78rem'>Your side: {h['side']}</div>
      <div class='muted' style='font-size:.78rem'>Shares: {h['shares_at_settle']:,.0f}</div>
      <div class='muted' style='font-size:.78rem'>Cost: {h['cost']:,.0f} → Payout: {h['payout']:,.0f}</div>
    </div>
  </div>
  <div style='margin-top:.6rem;background:#21262d;border-radius:6px;height:3px;overflow:hidden'>
    <div style='background:{bar_color};height:100%;width:{bar_pct:.0f}%'></div>
  </div>
</div>""",
                unsafe_allow_html=True,
            )

            with st.expander("Trade log"):
                d1, d2, d3, d4 = st.columns(4)
                d1.metric("Side", h["side"])
                d2.metric("Shares", f"{h['shares_at_settle']:,.0f}")
                d3.metric("Payout", f"{h['payout']:,.0f}")
                d4.metric("Realised P&L", f"{h['pnl']:+,.0f}")

                trades = mkt.recent_trades(market_id=m["id"], limit=50)
                user_trades = [t for t in trades if t["user"] == user["username"]]
                if user_trades:
                    df = pd.DataFrame(user_trades)
                    df["Time"] = pd.to_datetime(df["time"]).apply(
                        lambda t: t.replace(tzinfo=UTC).astimezone(ZURICH).strftime("%d %b %H:%M")
                    )
                    df["Mark"] = (df["prob_after"] * 100).round(0).astype(int).astype(str) + "%"
                    df["Side"] = df["side"].str.upper()
                    df["Payout"] = df["shares"].round(0)
                    df["Stake"] = df["cost"].round(0)
                    st.caption("Your trades")
                    st.dataframe(
                        df.rename(columns={"action": "Action"})[
                            ["Time", "Action", "Side", "Payout", "Stake", "Mark"]
                        ],
                        hide_index=True,
                        width="stretch",
                        height=150,
                    )
                else:
                    st.caption("No trades found.")

        else:
            # ---- Market the user did NOT trade in (greyed out) ------------ #
            desc = f" — {m['description']}" if m.get("description") else ""
            st.markdown(
                f"""<div class='market-card market-closed'>
  <div style='display:flex;justify-content:space-between;align-items:center'>
    <span class='tkr'>{m['question']}</span>
    <span class='pill {outcome_pill}'>{outcome}</span>
  </div>
  <div class='muted' style='font-size:.82rem;margin-top:.3rem'>You did not trade in this market.{desc}</div>
</div>""",
                unsafe_allow_html=True,
            )


# --------------------------------------------------------------------------- #
# Help / FAQ tab
# --------------------------------------------------------------------------- #
def faq_tab() -> None:
    st.markdown("#### How the market works")
    st.write(
        "Each market is a binary contract that settles at 100 if the event "
        "happens (YES) or 0 if it does not (NO). The quoted price sits between "
        "0 and 100% and reads as the market-implied probability. Everyone "
        "trades play money, so no real cash is at stake."
    )

    with st.expander("How are prices set? (the market maker)", expanded=True):
        st.write(
            "There's no order book and no waiting for someone to take the other "
            "side of your trade. An automated **market maker** is always there "
            "to trade with you. It uses a well-known formula called the "
            "**Logarithmic Market Scoring Rule (LMSR)**, designed by economist "
            "Robin Hanson."
        )
        st.write(
            "The idea is intuitive: the YES price is just the share of all bets "
            "sitting on YES, so it always lands between 0 and 100% and the two "
            "sides add up to 100%. In one line, if you like formulas:"
        )
        st.latex(
            r"p_{\text{YES}} = \frac{e^{\,q_{\text{YES}}/b}}"
            r"{e^{\,q_{\text{YES}}/b} + e^{\,q_{\text{NO}}/b}}"
        )
        st.write(
            "where *q* is the total quantity bought on each side and *b* is a "
            "liquidity parameter (see below)."
        )
        st.write(
            "Everything is priced from a single **cost function**:"
        )
        st.latex(
            r"C(q_Y,\, q_N) \;=\; b \;\ln\!\bigl(e^{\,q_Y/b} + e^{\,q_N/b}\bigr)"
        )
        st.write(
            "When you buy Δ YES shares, you pay the *difference* in C before "
            "and after your trade:"
        )
        st.latex(
            r"\text{cost} = C(q_Y + \Delta,\; q_N) \;-\; C(q_Y,\; q_N)"
        )
        st.write(
            "Because the price rises as you buy (your own trade pushes "
            "*q* up), you end up paying the area under the price curve rather "
            "than the starting price. That's your **slippage**, and your average "
            "fill price is simply cost ÷ Δ."
        )
        st.markdown(
            "**Further reading:**\n\n"
            "- [Prediction market — Wikipedia](https://en.wikipedia.org/wiki/Prediction_market) "
            "(general overview)\n"
            "- [A Practical Guide to LMSR — David Pennock's blog]"
            "(http://blog.oddhead.com/2006/10/30/implementing-hansons-market-maker/) "
            "(step-by-step walk-through of the exact pricing rule this app uses)\n"
            "- [Hanson's original paper (PDF)]"
            "(https://mason.gmu.edu/~rhanson/mktscore.pdf) "
            "(academic source, short and readable)"
        )

    with st.expander("What are shares? (with a worked example)"):
        st.write(
            "A **share** is a ticket that pays exactly **1 coin** if you're on "
            "the winning side at settlement, and **0** if you're not."
        )
        st.write("Here's a concrete example:")
        st.markdown(
            """
| Step | What happens |
|------|------|
| Market opens | *"Will it rain tomorrow?"* — starts at **50 / 50** |
| You buy YES, stake 25 coins | You get **45 YES shares** (avg price 56¢ each). Mark moves to 61%. |
| Another trader buys NO, stakes 10 | They get **23 NO shares** (avg price 43¢). Mark goes back to 55%. |
| Admin settles → **YES** | Your 45 shares pay **45 coins**. You spent 25, so **profit = +20**. The NO trader's shares pay 0 — their 10 coins go to fund your winnings. |
"""
        )
        st.write(
            "**Key points:**"
        )
        st.markdown(
            "- You don't buy \"1 share at a fixed price\". Your stake buys *as many* "
            "shares as it can afford — but the price rises as you buy, so bigger "
            "stakes get slightly worse average prices (slippage).\n"
            "- The **payout** number in the order ticket is your shares — that's "
            "exactly how many coins you'd receive if you win.\n"
            "- Your **profit** = payout − cost. If you buy 45 shares for 25 coins "
            "and win, you make 20. If you lose, you get 0 and lose the 25.\n"
            "- You can **sell (close)** any time before settlement at the current "
            "mark price — you don't have to wait for the outcome."
        )
        st.write(
            "**Think of it like betting odds:** a 60% price means you pay 60¢ per "
            "share to win 1 coin — similar to 1.67× odds. The cheaper the price "
            "(less likely event), the bigger the payout if you're right."
        )

    with st.expander("What is the liquidity setting b?"):
        st.write(
            "b controls how deep the market is. A larger b means each trade "
            "barely moves the price (good for busy markets); a smaller b means "
            "prices swing sharply on each trade. It also caps how much the "
            "market maker can ever subsidise — at most about 0.69 × b coins on a "
            "yes/no market — which is effectively the prize money the organiser "
            "puts up."
        )

    with st.expander("Where does my profit come from?"):
        st.write(
            "Winning shares are funded by the stakes of the losing side, topped "
            "up by a bounded subsidy from the market maker. If the crowd "
            "forecasts well the maker pays out slightly more than it took in; "
            "that shortfall, capped at about 0.69 × b, is effectively the prize "
            "pool the organiser puts up. There is no built-in house edge."
        )

    with st.expander("How is my P&L calculated?"):
        st.write(
            "Open positions are marked to market: value = shares × current "
            "price. Unrealised P&L is value − cost basis. Closing a position "
            "realises that number. At settlement, winning shares pay 100 each "
            "and losing shares pay 0."
        )

    with st.expander("Should I close early or hold to settlement?"):
        st.write(
            "Closing sells back to the maker at the current mark, locking in "
            "today's value. Holding a winning position to settlement pays the "
            "full 100 per share — more than the mark whenever the price is "
            "below 100. The trade-off is risk: until settlement the outcome can "
            "still move against you."
        )

    with st.expander("Who settles markets?"):
        st.write(
            "An administrator records the outcome from the Admin panel. Winning "
            "shares are paid out to traders' equity automatically and the "
            "market closes."
        )


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    user = st.session_state.user
    if user is None:
        auth_screen()
        return

    inject_css()

    # Single round-trip per rerun for the account snapshot.
    cash = mkt.get_user(user["id"])["balance"]
    positions_list = mkt.get_positions(user["id"])
    positions = {p["market_id"]: p for p in positions_list}
    equity = cash + sum(
        p["value"] for p in positions_list
        if p["status"] == "open" and (p["yes_shares"] > 0 or p["no_shares"] > 0)
    )

    sidebar(user, equity, cash)
    st.markdown("## La Repubblica dei Pronostici")
    st.caption("Internal prediction market")

    tabs = ["Markets", "Portfolio", "History", "Leaderboard", "Propose", "FAQ"]
    if user["is_admin"]:
        tabs.append("Admin")
    rendered = st.tabs(tabs)

    with rendered[0]:
        markets_tab(user, cash, positions)
    with rendered[1]:
        portfolio_tab(cash, positions_list)
    with rendered[2]:
        history_tab(user)
    with rendered[3]:
        leaderboard_tab(user)
    with rendered[4]:
        propose_tab(user)
    with rendered[5]:
        faq_tab()
    if user["is_admin"]:
        with rendered[6]:
            admin_tab(user)


# --------------------------------------------------------------------------- #
# Propose tab (visible to all users)
# --------------------------------------------------------------------------- #
def propose_tab(user: dict) -> None:
    st.markdown("#### Propose a market")
    st.caption("Suggest a question. An admin will review and can list it as a live market.")

    with st.form("propose_form"):
        question = st.text_input("Question", placeholder="Will we ship feature X by Friday?")
        description = st.text_area(
            "Resolution criteria (optional)",
            placeholder="How should the admin decide YES or NO?",
        )
        if st.form_submit_button("Submit proposal", type="primary"):
            try:
                mkt.create_proposal(user["id"], question, description)
                refresh()
            except ValueError as exc:
                st.error(str(exc))

    proposals = cached_proposals()
    my = [p for p in proposals if p["username"] == user["username"]]
    if my:
        st.markdown("#### Your proposals")
        for p in my:
            status_pill = {
                "pending": "⏳ Pending",
                "approved": "✅ Approved",
                "rejected": "❌ Rejected",
            }.get(p["status"], p["status"])
            st.markdown(
                f"<div style='padding:.4rem 0;border-bottom:1px solid #30363d'>"
                f"<span class='tkr'>{p['question']}</span>"
                f"<span class='muted' style='float:right'>{status_pill}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )


# --------------------------------------------------------------------------- #
# Admin tab
# --------------------------------------------------------------------------- #
def admin_tab(user: dict) -> None:
    sec_new, sec_edit, sec_settle, sec_delete, sec_proposals, sec_activity, sec_admins, sec_danger = st.tabs(
        ["New market", "Edit", "Settle", "Delete", "Proposals", "Activity", "Admins", "Reset"]
    )

    # ----- Create ------------------------------------------------------------ #
    with sec_new:
        with st.form("create_market"):
            question = st.text_input("Market question", placeholder="Will Italy beat Spain?")
            description = st.text_area(
                "Settlement / resolution criteria",
                placeholder="Result after 90 minutes + stoppage time. Extra time excluded.",
            )
            category = st.selectbox("Category", mkt.CATEGORIES)
            init_prob = st.slider(
                "Starting probability (YES %)",
                1, 99, 50, step=1,
                help="Opening odds — e.g. 70 means the market starts at YES 70% / NO 30%.",
            )
            b = st.slider(
                "Liquidity b (higher = deeper book, less slippage)",
                20, 400, 100, step=10,
            )
            set_deadline = st.checkbox("Set a trading deadline")
            now_z = datetime.now(ZURICH)
            dl1, dl2 = st.columns(2)
            close_date = dl1.date_input(
                "Close date (Zurich)", value=(now_z + timedelta(days=1)).date()
            )
            close_time = dl2.time_input(
                "Close time (Zurich)", value=time(20, 0), step=timedelta(minutes=1)
            )
            st.caption(
                "Trading stops at this Zurich (CET/CEST) date & time. "
                "Leave unchecked for a market with no deadline."
            )
            if st.form_submit_button("List market", type="primary"):
                close_at = None
                valid = True
                if set_deadline:
                    close_at = zurich_to_utc(datetime.combine(close_date, close_time))
                    if close_at <= datetime.utcnow():
                        st.error("That deadline is in the past (Zurich time).")
                        valid = False
                if valid:
                    try:
                        mkt.create_market(
                            question, description, float(b),
                            close_at=close_at, initial_prob=init_prob / 100,
                            category=category,
                        )
                        refresh()
                    except ValueError as exc:
                        st.error(str(exc))

    # ----- Edit -------------------------------------------------------------- #
    with sec_edit:
        open_markets = cached_markets("open")
        if not open_markets:
            st.info("No open markets to edit.")
        else:
            edit_labels = {m["question"]: m for m in open_markets}
            chosen_q = st.selectbox("Market to edit", list(edit_labels.keys()), key="edit_sel")
            em = edit_labels[chosen_q]

            with st.form(f"edit_market_{em['id']}"):
                new_question = st.text_input(
                    "Market question",
                    value=em["question"],
                )
                new_desc = st.text_area(
                    "Description / resolution criteria",
                    value=em["description"],
                )
                new_category = st.selectbox(
                    "Category",
                    mkt.CATEGORIES,
                    index=mkt.CATEGORIES.index(em.get("category", "Other")),
                )

                st.markdown("**Deadline**")
                has_deadline = st.checkbox(
                    "Has a trading deadline",
                    value=em["close_at"] is not None,
                )
                now_z = datetime.now(ZURICH)
                current_close_z = to_zurich(em["close_at"]) if em["close_at"] else None
                edl1, edl2 = st.columns(2)
                edit_date = edl1.date_input(
                    "Close date (Zurich)",
                    value=current_close_z.date() if current_close_z else (now_z + timedelta(days=1)).date(),
                )
                edit_time = edl2.time_input(
                    "Close time (Zurich)",
                    value=current_close_z.time() if current_close_z else time(20, 0),
                    step=timedelta(minutes=1),
                )

                st.markdown("**Liquidity**")
                new_b = st.slider(
                    "b (higher = deeper book)",
                    20, 400, int(em["b"]), step=10,
                )
                if em["q_yes"] != 0 or em["q_no"] != 0:
                    st.caption(
                        "Changing b on a market with existing trades will shift "
                        "the displayed mark price. Traders' shares don't change, "
                        "but their mark-to-market values will."
                    )

                if st.form_submit_button("Save changes", type="primary"):
                    close_at_val = ...  # sentinel: don't change
                    valid = True
                    if has_deadline:
                        close_at_val = zurich_to_utc(datetime.combine(edit_date, edit_time))
                        if close_at_val <= datetime.utcnow():
                            st.error("That deadline is in the past.")
                            valid = False
                    else:
                        close_at_val = None
                    if valid:
                        try:
                            mkt.update_market(
                                em["id"],
                                question=new_question,
                                description=new_desc,
                                category=new_category,
                                b=float(new_b),
                                close_at=close_at_val,
                            )
                            refresh()
                        except ValueError as exc:
                            st.error(str(exc))

    # ----- Settle ------------------------------------------------------------ #
    with sec_settle:
        open_markets = cached_markets("open")
        if not open_markets:
            st.info("No open markets to settle.")
        else:
            labels = {}
            for m in open_markets:
                tag = "" if m["trading_open"] else "  — trading closed"
                labels[f"{m['question']} (YES {m['prob_yes']*100:.0f}%){tag}"] = m["id"]
            choice = st.selectbox("Market", list(labels.keys()))
            st.caption("Settlement pays winning shares 100 each; losing shares expire at 0.")
            c1, c2 = st.columns(2)
            if c1.button("Settle YES", type="primary", width="stretch"):
                mkt.resolve_market(labels[choice], "yes")
                refresh()
            if c2.button("Settle NO", width="stretch"):
                mkt.resolve_market(labels[choice], "no")
                refresh()

    # ----- Delete ------------------------------------------------------------ #
    with sec_delete:
        open_markets = cached_markets("open")
        if not open_markets:
            st.info("No open markets to delete.")
        else:
            del_labels = {}
            for m in open_markets:
                tag = "" if m["trading_open"] else "  — trading closed"
                del_labels[f"{m['question']} (YES {m['prob_yes']*100:.0f}%){tag}"] = m["id"]
            del_choice = st.selectbox("Market", list(del_labels.keys()), key="del_sel")
            st.warning(
                "Deleting a market **refunds every trader** their net cost and "
                "removes the market completely — it will no longer appear anywhere. "
                "This cannot be undone."
            )
            confirm_del = st.text_input("Type DELETE to confirm", key="del_confirm")
            if st.button(
                "Delete market", type="primary",
                disabled=confirm_del != "DELETE",
            ):
                try:
                    q = mkt.delete_market(del_labels[del_choice])
                    st.success(f"Deleted: {q}. All traders have been refunded.")
                    refresh()
                except ValueError as exc:
                    st.error(str(exc))

    # ----- Proposals --------------------------------------------------------- #
    with sec_proposals:
        pending = cached_proposals("pending")
        if not pending:
            st.info("No pending proposals.")
        else:
            for p in pending:
                with st.container(border=True):
                    st.markdown(
                        f"<span class='tkr'>{p['question']}</span>"
                        f"<div class='muted' style='font-size:.82rem'>"
                        f"by {p['username']} · {fmt_zurich(p['created_at'])}</div>",
                        unsafe_allow_html=True,
                    )
                    if p["description"]:
                        st.markdown(f"<span class='muted'>{p['description']}</span>", unsafe_allow_html=True)
                    c_approve, c_reject = st.columns(2)
                    if c_approve.button("✅ Approve & create", key=f"approve_{p['id']}", type="primary", width="stretch"):
                        data = mkt.approve_proposal(p["id"])
                        mkt.create_market(data["question"], data["description"])
                        refresh()
                    if c_reject.button("❌ Reject", key=f"reject_{p['id']}", width="stretch"):
                        mkt.reject_proposal(p["id"])
                        refresh()

        # Show recently handled proposals
        handled = [p for p in cached_proposals() if p["status"] != "pending"]
        if handled:
            with st.expander(f"Handled ({len(handled)})"):
                for p in handled[:20]:
                    icon = "✅" if p["status"] == "approved" else "❌"
                    st.markdown(
                        f"{icon} **{p['question']}** — {p['username']}",
                    )

    # ----- Activity ---------------------------------------------------------- #
    with sec_activity:
        all_markets = (cached_markets("open") or []) + (cached_markets("resolved") or [])
        if not all_markets:
            st.info("No markets yet.")
        else:
            market_labels = {m["question"]: m["id"] for m in all_markets}
            chosen = st.selectbox(
                "Select market", list(market_labels.keys()), key="activity_market"
            )
            mid = market_labels[chosen]

            trades = mkt.recent_trades(market_id=mid, limit=200)
            if not trades:
                st.caption("No trades on this market yet.")
            else:
                df = pd.DataFrame(trades)
                # Summary
                vol = df["cost"].abs().sum()
                n_traders = df["user"].nunique()
                c1, c2, c3 = st.columns(3)
                c1.metric("Trades", str(len(df)))
                c2.metric("Volume", f"{vol:,.0f}")
                c3.metric("Traders", str(n_traders))

                # P&L breakdown
                breakdown = mkt.market_pnl_breakdown(mid)
                st.markdown("##### P&L by trader")
                if breakdown["traders"]:
                    pnl_df = pd.DataFrame(breakdown["traders"])
                    pnl_df["Side"] = pnl_df["side"]
                    pnl_df["Shares"] = pnl_df["shares"].round(0)
                    pnl_df["Cost"] = pnl_df["cost"].round(1)
                    pnl_df["Payout"] = pnl_df["payout"].round(1)
                    pnl_df["P&L"] = pnl_df["pnl"].round(1)
                    st.dataframe(
                        pnl_df.rename(columns={"username": "Trader"})[
                            ["Trader", "Side", "Shares", "Cost", "Payout", "P&L"]
                        ],
                        hide_index=True,
                        width="stretch",
                        column_config={
                            "P&L": st.column_config.NumberColumn(format="%+.1f"),
                        },
                    )

                # Market maker line
                maker_sign = "+" if breakdown["maker_pnl"] >= 0 else "−"
                maker_cls = "pos" if breakdown["maker_pnl"] >= 0 else "neg"
                status_note = "(realised)" if breakdown["status"] == "resolved" else "(mark-to-market)"
                st.markdown(
                    f"<div style='margin-top:.6rem;padding:.5rem .7rem;"
                    f"background:#21262d;border-radius:6px;display:flex;"
                    f"justify-content:space-between;align-items:center'>"
                    f"<span class='muted'>Market maker P&amp;L {status_note}</span>"
                    f"<span class='{maker_cls}' style='font-size:1.05rem'>"
                    f"{maker_sign}{abs(breakdown['maker_pnl']):,.1f}</span>"
                    f"</div>"
                    f"<div class='muted' style='font-size:.75rem;margin-top:.25rem'>"
                    f"Max possible loss: {breakdown['max_loss']:,.0f} (b × ln2)</div>",
                    unsafe_allow_html=True,
                )

                st.markdown("##### Trade tape")
                # Full trade tape
                df["Time"] = pd.to_datetime(df["time"]).dt.strftime("%d %b %H:%M")
                df["Side"] = df["side"].str.upper()
                df["Shares"] = df["shares"].round(0)
                df["Stake"] = df["cost"].round(1)
                df["Mark"] = (df["prob_after"] * 100).round(0).astype(int).astype(str) + "%"
                st.dataframe(
                    df.rename(columns={"user": "Trader", "action": "Action"})[
                        ["Time", "Trader", "Action", "Side", "Shares", "Stake", "Mark"]
                    ],
                    hide_index=True,
                    width="stretch",
                    height=400,
                )

    # ----- Admins ------------------------------------------------------------ #
    with sec_admins:
        users = mkt.list_users()
        st.markdown("##### Members")
        df = pd.DataFrame(users)
        df["Role"] = df["is_admin"].map({True: "admin", False: "trader"})
        st.dataframe(
            df.rename(columns={"username": "User"})[["User", "Role"]],
            hide_index=True,
            width="stretch",
        )

        traders = [u["username"] for u in users if not u["is_admin"]]
        admins = [u["username"] for u in users if u["is_admin"]]

        col_promote, col_demote = st.columns(2)
        with col_promote:
            st.markdown("**Promote to admin**")
            if traders:
                who = st.selectbox("Trader", traders, key="promote_sel")
                if st.button("Grant admin", width="stretch"):
                    mkt.set_admin(who, True)
                    refresh()
            else:
                st.caption("No traders to promote.")
        with col_demote:
            st.markdown("**Revoke admin**")
            demotable = [a for a in admins]
            if len(admins) > 1 and demotable:
                who = st.selectbox("Admin", demotable, key="demote_sel")
                if st.button("Revoke admin", width="stretch"):
                    try:
                        mkt.set_admin(who, False)
                        refresh()
                    except ValueError as exc:
                        st.error(str(exc))
            else:
                st.caption("Need at least one admin at all times.")

    # ----- Danger zone ------------------------------------------------------- #
    with sec_danger:
        st.warning(
            "Resets are irreversible. They wipe live markets, positions and trade history."
        )
        mode = st.radio(
            "Reset scope",
            [
                "Soft reset — wipe markets & trades, reset everyone to 1,000",
                "Hard reset — also delete all accounts except admins",
                "Nuke — delete everything except me",
            ],
        )
        confirm = st.text_input("Type RESET to confirm")
        if st.button("Execute reset", type="primary", disabled=confirm != "RESET"):
            if mode.startswith("Soft"):
                mkt.reset_game(delete_accounts=False)
            elif mode.startswith("Hard"):
                mkt.reset_game(delete_accounts=True, keep_admins=True)
            else:
                mkt.reset_game(delete_accounts=True, keep_user_id=user["id"])
            st.success("Market reset.")
            refresh()


main()
