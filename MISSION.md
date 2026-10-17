# Mission — Atlas Terminal

## In scope

Mini Bloomberg-style web terminal for Fede's fixed ticker universe:
AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, JPM, V, SPY, QQQ.

Six tabs: MKTS · QUOTE · FA · RISK · NEWS · ECO.

Real data only: yfinance (prices/quotes), SEC EDGAR (fundamentals/filings),
FRED (macro), Google News RSS (news fallback), FinBERT (sentiment).

Frontend + serverless API on Vercel. Scheduler on VPS (Dokploy cron).
Postgres on dokploy-postgres, schema `atlas`.

## Out of scope (for now)

- Trading / order routing.
- Real-time tick data (prices are delayed by Yahoo's terms).
- Options chains, crypto, FX, futures.
- Multi-user accounts / auth — this is a read-only public terminal.
- Mobile-native apps.

## Definition of done

1. All six tabs render real data or "data unavailable — {error}" in red.
2. No fake numbers anywhere.
3. `pytest -v` passes.
4. Frontend + API live on Vercel.
5. Repo on GitHub (`notcalambur/atlas-terminal`) with `federicopinan`
   as a collaborator.
6. Scheduler documented and ready to cron on the VPS.