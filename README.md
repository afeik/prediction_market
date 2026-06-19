# 📈 La Repubblica dei Pronostici

A self-hosted, play-money prediction market for teams. Trade YES/NO contracts on anything — no real cash, just bragging rights and a leaderboard.

Built with **Streamlit**, powered by an **LMSR market maker** (no order book needed), and deployable in minutes on [Streamlit Cloud](https://streamlit.io/cloud) with a free [Neon](https://neon.tech) Postgres database.

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

---

## ✨ Features

| Category | What you get |
|----------|------|
| **Trading** | Buy/sell YES and NO shares against an automated market maker — instant fills, no counterparty needed |
| **LMSR Pricing** | Logarithmic Market Scoring Rule with configurable liquidity (`b`). Prices always sum to 100% |
| **Custom starting odds** | Open markets at any probability (not just 50/50) |
| **Deadlines** | Optional trading deadlines with Zurich timezone display (auto CET/CEST) |
| **Portfolios** | Real-time P&L, mark-to-market valuations, close positions anytime |
| **History** | Full trade history with realised P&L for settled markets |
| **Leaderboard** | Equity-ranked standings — cash + open position value |
| **Multi-admin** | Promote/demote admins, create & settle markets, view per-trader activity |
| **Market management** | Edit questions/deadlines/liquidity, delete markets (auto-refund), settle YES/NO |
| **Dark UI** | Professional trading-terminal aesthetic with green/red probability bars |
| **Anonymous tape** | Public trade tape shows activity without revealing who traded |
| **Zero dependencies on external auth** | PBKDF2 password hashing from the standard library |

---

## 🚀 Quick start (local)

```bash
# Clone
git clone https://github.com/afeik/prediction_market.git
cd prediction_market

# Create environment (conda, venv, whatever you prefer)
conda create -n pronostici python=3.12 -y
conda activate pronostici

# Install
pip install -r requirements.txt

# Run (uses local SQLite by default)
streamlit run app.py
```

The first user to register becomes the admin.

---

## 🌐 Deploy to Streamlit Cloud + Neon Postgres

### 1. Create a Neon database

Sign up at [neon.tech](https://neon.tech) (free tier is plenty). Copy your connection string.

### 2. Push to GitHub

```bash
git remote add origin https://github.com/<you>/prediction_market.git
git push -u origin main
```

### 3. Deploy on Streamlit Cloud

1. Go to [share.streamlit.io](https://share.streamlit.io)
2. Point it at your repo, branch `main`, file `app.py`
3. In **Advanced settings → Secrets**, add:

```toml
[database]
url = "postgresql://<user>:<pass>@<host>/<db>?sslmode=require"
```

4. Hit **Deploy**. Done.

---

## 🗂️ Project structure

```
├── app.py              # Streamlit UI (auth, markets, portfolio, history, admin)
├── market.py           # Business logic (trading, resolution, leaderboard, admin ops)
├── pricing.py          # LMSR math (prob, cost_to_buy, proceeds_from_sell, shares_for_budget)
├── db.py               # SQLAlchemy models & engine (Postgres or SQLite)
├── reset_database.py   # Standalone script to wipe & recreate tables
├── smoke_test.py       # Basic sanity checks
├── requirements.txt    # Python dependencies
└── .streamlit/
    ├── config.toml     # Dark theme settings
    └── secrets.toml    # Local secrets (not committed)
```

---

## 🧮 How LMSR pricing works

The market maker uses the **Logarithmic Market Scoring Rule** (Hanson, 2003):

$$C(q_Y, q_N) = b \cdot \ln\left(e^{q_Y/b} + e^{q_N/b}\right)$$

The price (probability) of YES is:

$$p_{YES} = \frac{e^{q_Y/b}}{e^{q_Y/b} + e^{q_N/b}}$$

When you buy Δ shares of YES, you pay:

$$\text{cost} = C(q_Y + \Delta,\; q_N) - C(q_Y,\; q_N)$$

**Key properties:**
- Prices always between 0% and 100%, always sum to 100%
- Larger `b` = deeper liquidity = less slippage per trade
- Maximum market-maker loss is bounded: `b × ln(2) ≈ 0.693 × b`
- No order book, no waiting — every trade fills instantly

---

## ⚙️ Configuration

| Setting | Where | Default |
|---------|-------|---------|
| Database URL | `DATABASE_URL` env var or `.streamlit/secrets.toml` | `sqlite:///market.db` |
| Starting balance | `market.py` → `STARTING_BALANCE` | 1000 |
| Default liquidity | `market.py` → `DEFAULT_LIQUIDITY` | 100 |
| Theme | `.streamlit/config.toml` | Dark (GitHub-style) |
| Timezone | `app.py` → `ZURICH` | `Europe/Zurich` |

---

## 🛡️ Admin capabilities

- **Create markets** with custom question, description, starting odds, liquidity, and deadline
- **Edit** question text, description, deadline, and liquidity on live markets
- **Settle** markets as YES or NO (winning shares pay 1 coin each)
- **Delete** markets (refunds all traders automatically)
- **Activity view** — per-market trade tape, P&L by trader, market-maker P&L
- **Promote/demote** admins (last-admin protection)
- **Reset** — soft (wipe markets), hard (also delete non-admin accounts), or nuke

---

## 🤝 Contributing

PRs welcome. The codebase is small (~650 lines backend, ~1100 lines frontend) and intentionally dependency-light.

---

## 📚 Further reading

- [Prediction Markets — Wikipedia](https://en.wikipedia.org/wiki/Prediction_market)
- [A Practical Guide to LMSR — David Pennock](http://blog.oddhead.com/2006/10/30/implementing-hansons-market-maker/)
- [Hanson's original paper (PDF)](https://mason.gmu.edu/~rhanson/mktscore.pdf)

---

## 📄 License

MIT — do whatever you want with it.
