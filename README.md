# Prediction Market

A self-hosted, play-money prediction market for small teams. Traders buy and sell YES/NO contracts priced by an LMSR market maker.

Built with [Streamlit](https://streamlit.io). Runs locally on SQLite or deploys to Streamlit Cloud with [Neon](https://neon.tech) Postgres.

---

## Features

- LMSR automated market maker (configurable liquidity, no order book)
- Custom starting odds
- Trading deadlines with timezone handling
- Real-time portfolio with mark-to-market P&L
- Leaderboard
- Multi-admin: create, edit, settle, delete markets
- Anonymous public trade tape
- Password auth (PBKDF2, no external dependencies)

---

## Quick start

```bash
git clone https://github.com/afeik/prediction_market.git
cd prediction_market
pip install -r requirements.txt
streamlit run app.py
```

First user to register becomes admin. Uses SQLite by default.

---

## Deploy (Streamlit Cloud + Neon)

1. Create a database at [neon.tech](https://neon.tech)
2. Push to GitHub
3. Deploy `app.py` on [share.streamlit.io](https://share.streamlit.io) with this secret:

```toml
DATABASE_URL = "postgresql://<user>:<pass>@<host>/<db>?sslmode=require"
```

---

## Configuration

| Setting | Location | Default |
|---------|----------|---------|
| Database | `DATABASE_URL` env var or `.streamlit/secrets.toml` | SQLite |
| Starting balance | `market.py` | 1000 |
| Liquidity (b) | `market.py` | 100 |
| Timezone | `app.py` | Europe/Zurich |

---

## References

- Hanson (2003). [Combinatorial Information Market Design](https://mason.gmu.edu/~rhanson/mktscore.pdf)
- Pennock (2006). [Implementing Hanson's Market Maker](http://blog.oddhead.com/2006/10/30/implementing-hansons-market-maker/)

---

MIT License
