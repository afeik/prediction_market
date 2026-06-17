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

from sqlalchemy import func, select

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
def create_market(question: str, description: str = "", b: float = DEFAULT_LIQUIDITY) -> int:
    question = question.strip()
    if not question:
        raise ValueError("Question is required")
    with SessionLocal() as s:
        m = Market(question=question, description=description.strip(), b=b)
        s.add(m)
        s.commit()
        return m.id


def list_markets(status: str | None = None) -> list[dict]:
    with SessionLocal() as s:
        stmt = select(Market)
        if status:
            stmt = stmt.where(Market.status == status)
        markets = s.scalars(stmt.order_by(Market.created_at.desc())).all()
        return [
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
            }
            for m in markets
        ]


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
        out = []
        for pos in rows:
            if pos.yes_shares == 0 and pos.no_shares == 0:
                continue
            m = s.get(Market, pos.market_id)
            p = pricing.prob_yes(m.q_yes, m.q_no, m.b)
            out.append(
                {
                    "market_id": m.id,
                    "question": m.question,
                    "status": m.status,
                    "outcome": m.outcome,
                    "yes_shares": pos.yes_shares,
                    "no_shares": pos.no_shares,
                    "prob_yes": p,
                    "value": pos.yes_shares * p + pos.no_shares * (1 - p),
                }
            )
        return out


def leaderboard() -> list[dict]:
    """Net worth = cash + mark-to-market value of open positions."""
    with SessionLocal() as s:
        users = s.scalars(select(User)).all()
        rows = []
        for u in users:
            net = u.balance
            positions = s.scalars(select(Position).where(Position.user_id == u.id)).all()
            for pos in positions:
                m = s.get(Market, pos.market_id)
                if m.status == "open":
                    p = pricing.prob_yes(m.q_yes, m.q_no, m.b)
                    net += pos.yes_shares * p + pos.no_shares * (1 - p)
            rows.append(
                {"username": u.username, "cash": u.balance, "net_worth": net}
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


if __name__ == "__main__":
    init_db()
    print("Database initialised at:", os.environ.get("DATABASE_URL", "sqlite:///market.db"))
