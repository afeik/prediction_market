"""Business logic: registration/auth, trading against the LMSR market maker,
market creation, resolution, and read helpers for the UI.

Password hashing uses PBKDF2 from the standard library, so there is no
external auth dependency. Each trade runs inside a single transaction and
locks the market row (on Postgres) to keep the market state consistent when
several traders act at once.
"""
from __future__ import annotations

import binascii
import hashlib
import hmac
import os
from datetime import datetime

from sqlalchemy import delete, func, select

import pricing
from db import Market, Position, SessionLocal, Trade, User, init_db

STARTING_BALANCE = 1000.0
DEFAULT_LIQUIDITY = 100.0


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #
def hash_password(password: str, iterations: int = 200_000) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${binascii.hexlify(salt).decode()}${binascii.hexlify(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _algo, iters, salt_hex, hash_hex = stored.split("$")
        salt = binascii.unhexlify(salt_hex)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iters))
        return hmac.compare_digest(binascii.hexlify(dk).decode(), hash_hex)
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #
def user_count() -> int:
    with SessionLocal() as s:
        return int(s.scalar(select(func.count()).select_from(User)) or 0)


def register_user(username: str, password: str, is_admin: bool = False) -> dict:
    username = username.strip()
    if not username or not password:
        raise ValueError("Username and password are required")
    with SessionLocal() as s:
        if s.scalar(select(User).where(User.username == username)):
            raise ValueError("Username already taken")
        u = User(
            username=username,
            password_hash=hash_password(password),
            balance=STARTING_BALANCE,
            is_admin=is_admin,
        )
        s.add(u)
        s.commit()
        return {"id": u.id, "username": u.username, "is_admin": u.is_admin}


def authenticate(username: str, password: str) -> dict | None:
    with SessionLocal() as s:
        u = s.scalar(select(User).where(User.username == username.strip()))
        if u and verify_password(password, u.password_hash):
            return {"id": u.id, "username": u.username, "is_admin": u.is_admin}
        return None


def get_user(user_id: int) -> dict:
    with SessionLocal() as s:
        u = s.get(User, user_id)
        return {
            "id": u.id,
            "username": u.username,
            "balance": u.balance,
            "is_admin": u.is_admin,
        }


# --------------------------------------------------------------------------- #
# Markets
# --------------------------------------------------------------------------- #
def create_market(
    question: str,
    description: str = "",
    b: float = DEFAULT_LIQUIDITY,
    close_at: datetime | None = None,
) -> int:
    question = question.strip()
    if not question:
        raise ValueError("Question is required")
    with SessionLocal() as s:
        m = Market(
            question=question,
            description=description.strip(),
            b=b,
            close_at=close_at,
        )
        s.add(m)
        s.commit()
        return m.id


def update_market(
    market_id: int,
    description: str | None = None,
    b: float | None = None,
    close_at: datetime | None = ...,  # sentinel: ... means 'don't change'
) -> None:
    """Edit parameters of an open market.

    - description: new resolution text (or None to keep current)
    - b: new liquidity (changes mark price if trades exist)
    - close_at: new deadline, None to remove, or ... to leave unchanged
    """
    with SessionLocal() as s:
        m = s.get(Market, market_id, with_for_update=True)
        if m is None or m.status != "open":
            raise ValueError("Market is not open")
        if description is not None:
            m.description = description.strip()
        if b is not None:
            if b < 10:
                raise ValueError("Liquidity b must be at least 10")
            m.b = b
        if close_at is not ...:
            m.close_at = close_at
        s.commit()


def list_markets(status: str | None = None) -> list[dict]:
    with SessionLocal() as s:
        stmt = select(Market)
        if status:
            stmt = stmt.where(Market.status == status)
        markets = s.scalars(stmt.order_by(Market.created_at.desc())).all()
        now = datetime.utcnow()
        out = []
        for m in markets:
            seconds_left = (
                (m.close_at - now).total_seconds() if m.close_at is not None else None
            )
            expired = (
                m.status == "open"
                and m.close_at is not None
                and now >= m.close_at
            )
            out.append(
                {
                    "id": m.id,
                    "question": m.question,
                    "description": m.description,
                    "b": m.b,
                    "q_yes": m.q_yes,
                    "q_no": m.q_no,
                    "status": m.status,
                    "outcome": m.outcome,
                    "prob_yes": pricing.prob_yes(m.q_yes, m.q_no, m.b),
                    "close_at": m.close_at,
                    "seconds_left": seconds_left,
                    "trading_open": m.status == "open" and not expired,
                    "expired": expired,
                }
            )
        return out


# --------------------------------------------------------------------------- #
# Trading
# --------------------------------------------------------------------------- #
def execute_trade(user_id: int, market_id: int, side: str, action: str, shares: float) -> dict:
    """Buy or sell `shares` of `side` ('yes'|'no'). One atomic transaction."""
    side = side.lower()
    action = action.lower()
    if side not in ("yes", "no") or action not in ("buy", "sell"):
        raise ValueError("Invalid trade")
    if shares <= 0:
        raise ValueError("Amount must be positive")

    with SessionLocal() as s:
        m = s.get(Market, market_id, with_for_update=True)
        if m is None or m.status != "open":
            raise ValueError("Market is not open")
        if m.close_at is not None and datetime.utcnow() >= m.close_at:
            raise ValueError("Trading has closed for this market")
        u = s.get(User, user_id, with_for_update=True)

        pos = s.scalar(
            select(Position).where(
                Position.user_id == user_id, Position.market_id == market_id
            )
        )
        if pos is None:
            pos = Position(
                user_id=user_id, market_id=market_id, yes_shares=0.0, no_shares=0.0
            )
            s.add(pos)

        if action == "buy":
            delta = pricing.cost_to_buy(m.q_yes, m.q_no, m.b, side, shares)
            if delta > u.balance + 1e-9:
                raise ValueError("Insufficient balance")
            u.balance -= delta
            if side == "yes":
                m.q_yes += shares
                pos.yes_shares += shares
            else:
                m.q_no += shares
                pos.no_shares += shares
            cost_signed = delta
        else:  # sell
            held = pos.yes_shares if side == "yes" else pos.no_shares
            if shares > held + 1e-9:
                raise ValueError("Cannot sell more shares than you own")
            proceeds = pricing.proceeds_from_sell(m.q_yes, m.q_no, m.b, side, shares)
            u.balance += proceeds
            if side == "yes":
                m.q_yes -= shares
                pos.yes_shares -= shares
            else:
                m.q_no -= shares
                pos.no_shares -= shares
            cost_signed = -proceeds

        prob_after = pricing.prob_yes(m.q_yes, m.q_no, m.b)
        s.add(
            Trade(
                user_id=user_id,
                market_id=market_id,
                side=side,
                action=action,
                shares=shares,
                cost=cost_signed,
                prob_after=prob_after,
            )
        )
        s.commit()
        return {"cost": cost_signed, "prob_after": prob_after, "balance": u.balance}


def resolve_market(market_id: int, outcome: str) -> None:
    """Settle a market. Winning shares pay 1 coin each; losing shares pay 0."""
    outcome = outcome.lower()
    if outcome not in ("yes", "no"):
        raise ValueError("Outcome must be 'yes' or 'no'")
    with SessionLocal() as s:
        m = s.get(Market, market_id, with_for_update=True)
        if m is None or m.status != "open":
            raise ValueError("Market is not open")
        positions = s.scalars(
            select(Position).where(Position.market_id == market_id)
        ).all()
        for pos in positions:
            u = s.get(User, pos.user_id, with_for_update=True)
            u.balance += pos.yes_shares if outcome == "yes" else pos.no_shares
            pos.yes_shares = 0.0
            pos.no_shares = 0.0
        m.status = "resolved"
        m.outcome = outcome
        s.commit()


# --------------------------------------------------------------------------- #
# Portfolio & leaderboard
# --------------------------------------------------------------------------- #
def get_positions(user_id: int) -> list[dict]:
    with SessionLocal() as s:
        rows = s.scalars(select(Position).where(Position.user_id == user_id)).all()
        if not rows:
            return []
        market_ids = {pos.market_id for pos in rows}
        markets = {
            m.id: m
            for m in s.scalars(select(Market).where(Market.id.in_(market_ids))).all()
        }
        # Net invested per market (buys are +cost, sells are -proceeds).
        invested: dict[int, float] = {}
        for t in s.scalars(
            select(Trade).where(Trade.user_id == user_id)
        ).all():
            invested[t.market_id] = invested.get(t.market_id, 0.0) + t.cost

        out = []
        for pos in rows:
            if pos.yes_shares == 0 and pos.no_shares == 0:
                continue
            m = markets[pos.market_id]
            p = pricing.prob_yes(m.q_yes, m.q_no, m.b)
            value = pos.yes_shares * p + pos.no_shares * (1 - p)
            cost_basis = invested.get(pos.market_id, 0.0)
            out.append(
                {
                    "market_id": m.id,
                    "question": m.question,
                    "status": m.status,
                    "outcome": m.outcome,
                    "yes_shares": pos.yes_shares,
                    "no_shares": pos.no_shares,
                    "prob_yes": p,
                    "value": value,
                    "invested": cost_basis,
                    "pnl": value - cost_basis,
                }
            )
        return out


def get_history(user_id: int) -> list[dict]:
    """Return resolved markets the user traded in, with realised P&L.

    Since positions are zeroed at settlement, we reconstruct from trade records:
    - net_cost = sum of trade.cost (buys positive, sells negative)
    - payout = shares held at settlement × 1 (if winning side) or 0

    We derive shares-at-settlement as net bought minus net sold per side.
    """
    with SessionLocal() as s:
        # All resolved markets
        resolved = {
            m.id: m
            for m in s.scalars(select(Market).where(Market.status == "resolved")).all()
        }
        if not resolved:
            return []

        # All trades by this user on resolved markets
        trades = s.scalars(
            select(Trade).where(
                Trade.user_id == user_id,
                Trade.market_id.in_(resolved.keys()),
            )
        ).all()

        # Aggregate per market
        by_market: dict[int, dict] = {}
        for t in trades:
            rec = by_market.setdefault(t.market_id, {"cost": 0.0, "yes": 0.0, "no": 0.0})
            rec["cost"] += t.cost
            sign = 1.0 if t.action == "buy" else -1.0
            if t.side == "yes":
                rec["yes"] += sign * t.shares
            else:
                rec["no"] += sign * t.shares

        out = []
        for mid, agg in by_market.items():
            m = resolved[mid]
            # Shares held at settlement (should be >= 0 after sells)
            held_yes = max(0.0, agg["yes"])
            held_no = max(0.0, agg["no"])
            # Payout at settlement
            payout = held_yes if m.outcome == "yes" else held_no
            realised_pnl = payout - agg["cost"]
            side = "YES" if held_yes > held_no else "NO" if held_no > 0 else "-"
            out.append(
                {
                    "market_id": m.id,
                    "question": m.question,
                    "outcome": m.outcome.upper() if m.outcome else "-",
                    "side": side,
                    "shares_at_settle": held_yes if side == "YES" else held_no,
                    "cost": agg["cost"],
                    "payout": payout,
                    "pnl": realised_pnl,
                    "created_at": m.created_at,
                }
            )
        out.sort(key=lambda r: r["created_at"], reverse=True)
        return out


def leaderboard() -> list[dict]:
    """Equity = cash + mark-to-market value of open positions."""
    with SessionLocal() as s:
        users = s.scalars(select(User)).all()
        markets = {m.id: m for m in s.scalars(select(Market)).all()}
        pos_by_user: dict[int, list] = {}
        for pos in s.scalars(select(Position)).all():
            pos_by_user.setdefault(pos.user_id, []).append(pos)

        rows = []
        for u in users:
            net = u.balance
            for pos in pos_by_user.get(u.id, []):
                m = markets.get(pos.market_id)
                if m and m.status == "open":
                    p = pricing.prob_yes(m.q_yes, m.q_no, m.b)
                    net += pos.yes_shares * p + pos.no_shares * (1 - p)
            rows.append(
                {
                    "username": u.username,
                    "cash": u.balance,
                    "net_worth": net,
                    "is_admin": u.is_admin,
                }
            )
        rows.sort(key=lambda r: r["net_worth"], reverse=True)
        return rows


def recent_trades(market_id: int | None = None, limit: int = 20) -> list[dict]:
    with SessionLocal() as s:
        stmt = select(Trade, User.username).join(User, Trade.user_id == User.id)
        if market_id is not None:
            stmt = stmt.where(Trade.market_id == market_id)
        stmt = stmt.order_by(Trade.created_at.desc()).limit(limit)
        out = []
        for t, username in s.execute(stmt).all():
            out.append(
                {
                    "time": t.created_at,
                    "user": username,
                    "action": t.action,
                    "side": t.side,
                    "shares": t.shares,
                    "cost": t.cost,
                    "prob_after": t.prob_after,
                }
            )
        return out


def market_pnl_breakdown(market_id: int) -> dict:
    """Compute per-trader P&L and market-maker P&L for a market.

    For resolved markets: payout = shares on winning side.
    For open markets: payout = mark-to-market value.
    Market maker P&L = total collected - total paid out.
    """
    with SessionLocal() as s:
        m = s.get(Market, market_id)
        if m is None:
            return {"traders": [], "maker_pnl": 0.0, "status": "unknown"}

        trades = s.scalars(
            select(Trade).where(Trade.market_id == market_id)
        ).all()

        # Aggregate per user
        by_user: dict[int, dict] = {}
        for t in trades:
            rec = by_user.setdefault(t.user_id, {"cost": 0.0, "yes": 0.0, "no": 0.0})
            rec["cost"] += t.cost
            sign = 1.0 if t.action == "buy" else -1.0
            if t.side == "yes":
                rec["yes"] += sign * t.shares
            else:
                rec["no"] += sign * t.shares

        # Resolve usernames
        user_ids = list(by_user.keys())
        usernames = {}
        if user_ids:
            for u in s.scalars(select(User).where(User.id.in_(user_ids))).all():
                usernames[u.id] = u.username

        # Compute payout per trader
        traders = []
        total_collected = 0.0
        total_paid = 0.0

        for uid, agg in by_user.items():
            held_yes = max(0.0, agg["yes"])
            held_no = max(0.0, agg["no"])
            cost = agg["cost"]
            total_collected += cost

            if m.status == "resolved":
                payout = held_yes if m.outcome == "yes" else held_no
            else:
                # Mark-to-market for open markets
                p = pricing.prob_yes(m.q_yes, m.q_no, m.b)
                payout = held_yes * p + held_no * (1 - p)

            total_paid += payout
            traders.append({
                "username": usernames.get(uid, f"user_{uid}"),
                "side": "YES" if held_yes >= held_no else "NO",
                "shares": held_yes if held_yes >= held_no else held_no,
                "cost": cost,
                "payout": payout,
                "pnl": payout - cost,
            })

        traders.sort(key=lambda r: r["pnl"], reverse=True)
        maker_pnl = total_collected - total_paid

        return {
            "traders": traders,
            "maker_pnl": maker_pnl,
            "status": m.status,
            "max_loss": m.b * 0.6931,  # b * ln2
        }


# --------------------------------------------------------------------------- #
# Admin: user management & resets
# --------------------------------------------------------------------------- #
def list_users() -> list[dict]:
    with SessionLocal() as s:
        users = s.scalars(select(User).order_by(User.username)).all()
        return [
            {
                "id": u.id,
                "username": u.username,
                "is_admin": u.is_admin,
                "balance": u.balance,
            }
            for u in users
        ]


def admin_count() -> int:
    with SessionLocal() as s:
        return int(
            s.scalar(
                select(func.count()).select_from(User).where(User.is_admin.is_(True))
            )
            or 0
        )


def set_admin(username: str, make_admin: bool) -> None:
    """Promote or demote a user. Refuses to remove the last remaining admin."""
    username = username.strip()
    with SessionLocal() as s:
        u = s.scalar(select(User).where(User.username == username))
        if u is None:
            raise ValueError(f"No user named {username!r}")
        if u.is_admin and not make_admin:
            remaining = s.scalar(
                select(func.count()).select_from(User).where(User.is_admin.is_(True))
            )
            if remaining <= 1:
                raise ValueError("Can't remove the last admin")
        u.is_admin = make_admin
        s.commit()


def reset_game(
    delete_accounts: bool = False,
    keep_user_id: int | None = None,
    keep_admins: bool = False,
) -> None:
    """Wipe all markets, positions and trades and reset every remaining balance
    to the starting amount.

    Modes:
        delete_accounts=False               -> soft reset (keep all accounts)
        delete_accounts=True, keep_admins   -> remove non-admin accounts only
        delete_accounts=True, keep_user_id  -> remove everyone except that user
    """
    with SessionLocal() as s:
        s.execute(delete(Trade))
        s.execute(delete(Position))
        s.execute(delete(Market))
        if delete_accounts:
            stmt = delete(User)
            if keep_admins:
                stmt = stmt.where(User.is_admin.is_(False))
            elif keep_user_id is not None:
                stmt = stmt.where(User.id != keep_user_id)
            s.execute(stmt)
        for u in s.scalars(select(User)).all():
            u.balance = STARTING_BALANCE
        s.commit()


if __name__ == "__main__":
    init_db()
    print("Database initialised at:", os.environ.get("DATABASE_URL", "sqlite:///market.db"))
