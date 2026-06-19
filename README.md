# Prediction Market

A self-hosted, play-money prediction market for teams. Traders buy and sell YES/NO contracts against an automated market maker — instant fills, no order book, no real cash.

Built with [Streamlit](https://streamlit.io), backed by [LMSR pricing](https://mason.gmu.edu/~rhanson/mktscore.pdf), deployable in minutes on Streamlit Cloud with a free [Neon](https://neon.tech) Postgres database.

---

## Features

- **Automated market maker** — [LMSR](http://blog.oddhead.com/2006/10/30/implementing-hansons-market-maker/) with configurable liquidity. Prices always sum to 100%, every trade fills instantly.
- **Custom starting odds** — open markets at any probability, not just 50/50.
- **Deadlines** — optional trading cutoffs with timezone-aware display.
- **Portfolios & P&L** — real-time mark-to-market, close positions anytime.
- **Leaderboard** — equity-ranked standings across all traders.
- **Multi-admin** — create/settle/edit/delete markets, view per-trader activity, promote/demote admins.
- **Anonymous trade tape** — public activity feed without revealing who traded.
- **No external auth** — PBKDF2 hashing from the standard library.

---

## Quick start

```bash
git clone https://github.com/afeik/prediction_market.git
cd prediction_market
pip install -r requirements.txt
streamlit run app.py
```

Uses SQLite locally. The first user to register becomes admin.

---

## Deploy (Streamlit Cloud + Neon)

1. Create a free Postgres database at [neon.tech](https://neon.tech)
2. Push this repo to GitHub
3. On [share.streamlit.io](https://share.streamlit.io), deploy `app.py` and add this secret:

```toml
[database]
url = "postgresql://<user>:<pass>@<host>/<db>?sslmode=require"
```

---

## Configuration

| Setting | Location | Default |
|---------|----------|---------|
| Database | `DATABASE_URL` env var or `.streamlit/secrets.toml` | SQLite |
| Starting balance | `market.py` | 1000 |
| Default liquidity (b) | `market.py` | 100 |
| Display timezone | `app.py` | Europe/Zurich |

---

## References

- Hanson, R. (2003). [Combinatorial Information Market Design](https://mason.gmu.edu/~rhanson/mktscore.pdf). *Information Systems Frontiers*.
- Pennock, D. (2006). [Implementing Hanson's Market Maker](http://blog.oddhead.com/2006/10/30/implementing-hansons-market-maker/).
- [Prediction Markets — Wikipedia](https://en.wikipedia.org/wiki/Prediction_market)

---

MIT License
