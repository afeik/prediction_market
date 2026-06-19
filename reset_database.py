"""One-shot database reset.

Reads DATABASE_URL from .streamlit/secrets.toml, drops every table, and
recreates them with the current schema.

Usage:
    python reset_database.py
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
SECRETS = HERE / ".streamlit" / "secrets.toml"


def load_database_url() -> str:
    if not SECRETS.exists():
        raise SystemExit(f"secrets file not found at {SECRETS}")
    with SECRETS.open("rb") as fh:
        data = tomllib.load(fh)
    url = data.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set in secrets.toml")
    return url


def main() -> None:
    url = load_database_url()
    os.environ["DATABASE_URL"] = url  # db.py reads this on import

    # Import only after the env var is set so the engine binds to Neon.
    from sqlalchemy import inspect

    import db

    host = url.split("@")[-1].split("/")[0]
    print(f"Target database: {host}")
    print("Dropping and recreating all tables ...")
    db.reset_db()

    insp = inspect(db.engine)
    tables = insp.get_table_names()
    market_cols = [c["name"] for c in insp.get_columns("markets")]

    print(f"Tables now present: {sorted(tables)}")
    print(f"markets columns:    {market_cols}")
    assert "close_at" in market_cols, "close_at column missing — schema not updated!"

    with db.SessionLocal() as s:
        from db import Market, Position, Trade, User

        counts = {
            "users": s.query(User).count(),
            "markets": s.query(Market).count(),
            "positions": s.query(Position).count(),
            "trades": s.query(Trade).count(),
        }
    print(f"Row counts (all should be 0): {counts}")
    print("\n✅ Database reset complete — fresh schema with close_at is live.")


if __name__ == "__main__":
    main()
