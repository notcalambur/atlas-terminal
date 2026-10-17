# Atlas Terminal

Mini financial terminal inspired by Bloomberg's classic look. Black + amber,
dense panels, command bar, function-key tabs. Real data only, no mocks.

## Architecture

```
            ┌──────────────────────┐
            │  Frontend (static)   │   /frontend/{index.html, app.js, style.css}
            │  Hosted on Vercel    │
            └──────────┬───────────┘
                       │ fetch
            ┌──────────▼───────────┐
            │  API (FastAPI)        │   /api/*  → /atlas/api.py
            │  Vercel serverless    │   reads Postgres
            └──────────┬───────────┘
                       │
            ┌──────────▼───────────┐
            │  Postgres (dokploy)   │   schema: atlas
            └──────────▲───────────┘
                       │ writes
            ┌──────────┴───────────┐
            │  Scheduler (cron)     │   /scripts/run_scheduler.sh
            │  on VPS via Dokploy   │   fetcher / edgar / fred / news / sentiment
            └──────────────────────┘
```

The frontend and the API are server-side rendered (Vercel), so visitors never
hit external sources directly. The scheduler runs in the VPS (Dokploy) and
does the heavy lifting (yfinance, SEC EDGAR, FRED, Google News, FinBERT).

## Data sources

| Panel       | Source                                    |
| ----------- | ----------------------------------------- |
| Prices      | yfinance (Yahoo Finance)                  |
| Quotes      | yfinance fast_info                        |
| News        | yfinance Ticker.news + Google News RSS    |
| Sentiment   | FinBERT (ProsusAI/finbert, CPU)          |
| Fundamentals| SEC EDGAR companyfacts + submissions      |
| Macro       | FRED public CSV (no key)                  |

Prices are delayed. The UI labels them "delayed".

## Refresh cadence

| What                  | Cadence                                  |
| --------------------- | ---------------------------------------- |
| Daily OHLCV + quote   | Every 15 min during US market hours      |
| News + sentiment      | Every 30 min                             |
| Fundamentals (EDGAR)  | Once a day                               |
| FRED series           | Once a day                               |

## Endpoints

```
GET /api/health
GET /api/mkts
GET /api/quote/{ticker}?range=1M|6M|1Y|5Y
GET /api/fa/{ticker}
GET /api/risk
GET /api/news/{ticker}
GET /api/eco
```

## Tabs

`MKTS · QUOTE · FA · RISK · NEWS · ECO` (F1–F6).

## Setup

```bash
# 1. Python venv + deps (for the scheduler)
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Init the schema
python3 -m atlas.init_schema

# 3. Seed data (first time only — takes a few minutes)
python3 -m atlas.fetcher            # ~5y history + live quotes
python3 -m atlas.fred                # 6 FRED series
python3 -m atlas.edgar               # 11 tickers' fundamentals + filings
python3 -m atlas.news                # 11 tickers' headlines
python3 -m atlas.sentiment           # score whatever's unscored

# 4. Run the API locally (optional)
uvicorn atlas.api:app --reload

# 5. Open the frontend
cd frontend && python3 -m http.server 5173
```

## Deploy

The frontend (`/frontend`) and the API (`/api/*` → `/atlas/api.py`) are
deployed on Vercel. See `vercel.json` for the rewrite map.

The scheduler runs as a cron in the VPS (`scripts/run_scheduler.sh`). Wire it
up with the cadence table above.

## Tests

```bash
pytest -v
```

Risk metrics are tested against hand-calculated series in `tests/test_risk.py`.
Imports are smoke-tested in `tests/test_imports.py`.

## Quality checks

- **No mocks, no placeholders, no random data.** Every number on screen came
  from yfinance / SEC / FRED / Google News. If a panel has nothing to show,
  it says `data unavailable — {error}` in red.
- **User-Agent on EDGAR.** Every SEC request carries the configured agent.
- **Rate limit.** The scheduler sleeps 150 ms between SEC calls (well under
  the 10 req/s cap) and 200 ms between FRED pulls.
- **FinBERT CPU.** The model loads lazily, only on the scheduler, never in
  the Vercel serverless functions.