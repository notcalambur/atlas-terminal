"""Vercel serverless entrypoint. Single FastAPI app, one file.

Vercel's Python runtime looks for an `app` callable. We use the mangum
adapter so the same ASGI app works under uvicorn locally and under AWS
Lambda-style invocation on Vercel.

Endpoints (all read-only — the API never fetches from external sources):
  GET /api/health
  GET /api/mkts
  GET /api/quote/{ticker}?range=1M|6M|1Y|5Y
  GET /api/fa/{ticker}
  GET /api/risk
  GET /api/news/{ticker}
  GET /api/eco
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

from . import config, db, fred, risk as risk_mod


app = FastAPI(title="Atlas Terminal API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _err(ticker: str, msg: str, code: int = 503) -> dict:
    """Standard 'data unavailable' envelope."""
    raise HTTPException(status_code=code, detail={
        "ticker": ticker, "error": msg, "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat()
    })


# ---------- health ----------------------------------------------------------

@app.get("/api/health")
def health():
    try:
        row = db.fetch_one("SELECT now() AS now, current_database() AS db")
        return {"ok": True, "db_time": str(row["now"]), "database": row["db"]}
    except Exception as e:
        raise HTTPException(status_code=503, detail={"ok": False, "error": str(e)})


# ---------- MKTS ------------------------------------------------------------

@app.get("/api/mkts")
def mkts():
    # Indices & watchlist quotes are pulled from atlas.quotes.
    index_rows = db.fetch_all(
        "SELECT ticker, last, change_abs, change_pct, fetched_at FROM atlas.quotes "
        "WHERE ticker = ANY(%s) ORDER BY ticker",
        (list(config.INDICES),),
    )
    watch_rows = db.fetch_all(
        "SELECT q.ticker, q.last, q.change_abs, q.change_pct, q.fetched_at "
        "FROM atlas.quotes q JOIN atlas.watchlist w ON q.ticker = w.ticker "
        "ORDER BY q.ticker"
    )
    dff = fred.latest("DFF")
    ust10 = fred.latest("DGS10")
    ust2 = fred.latest("DGS2")
    cpi = fred.latest("CPIAUCSL")
    cpi_prior = db.fetch_one(
        "SELECT value FROM atlas.fred_series WHERE series_id = 'CPIAUCSL' "
        "AND ts < (SELECT MAX(ts) FROM atlas.fred_series WHERE series_id='CPIAUCSL') "
        "ORDER BY ts DESC LIMIT 1"
    )
    cpi_yoy = None
    if cpi and cpi_prior:
        cpi_yoy = (cpi[1] - cpi_prior["value"]) / cpi_prior["value"] * 100
    spread = (ust10[1] - ust2[1]) if (ust10 and ust2) else None
    return {
        "indices": index_rows,
        "watchlist": watch_rows,
        "macro": {
            "fed_funds": dff[1] if dff else None,
            "ust10": ust10[1] if ust10 else None,
            "ust2s10s": spread,
            "cpi_yoy": cpi_yoy,
        },
        "source": "yfinance (quotes) + FRED (macro)",
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


# ---------- QUOTE -----------------------------------------------------------

_RANGE_DAYS = {"1M": 30, "6M": 182, "1Y": 365, "5Y": 5 * 365}


@app.get("/api/quote/{ticker}")
def quote(ticker: str, range: str = Query("1Y", pattern="^(1M|6M|1Y|5Y)$")):
    days = _RANGE_DAYS[range]
    rows = db.fetch_all(
        "SELECT ts, close, adj_close, volume FROM atlas.prices "
        "WHERE ticker = %s ORDER BY ts DESC LIMIT %s",
        (ticker.upper(), days + 1),
    )
    if not rows:
        _err(ticker, "no price data")
    rows = list(reversed(rows))  # oldest first
    series = pd.Series([float(r["adj_close"]) for r in rows])
    ma50 = float(series.rolling(50).mean().iloc[-1]) if len(series) >= 50 else None
    ma200 = float(series.rolling(200).mean().iloc[-1]) if len(series) >= 200 else None
    high_52w = float(series.tail(min(252, len(series))).max())
    low_52w = float(series.tail(min(252, len(series))).min())
    q = db.fetch_one(
        "SELECT last, prev_close, change_abs, change_pct, volume, fetched_at "
        "FROM atlas.quotes WHERE ticker = %s", (ticker.upper(),),
    )
    if not q:
        _err(ticker, "no live quote")
    return {
        "ticker": ticker.upper(),
        "range": range,
        "last": float(q["last"]),
        "change_abs": float(q["change_abs"]),
        "change_pct": float(q["change_pct"]),
        "high_52w": high_52w, "low_52w": low_52w,
        "volume": int(q["volume"] or 0),
        "ma50": ma50, "ma200": ma200,
        "series": [
            {"ts": str(r["ts"]), "close": float(r["close"]),
             "adj_close": float(r["adj_close"]), "volume": int(r["volume"] or 0)}
            for r in rows
        ],
        "source": "yfinance",
        "fetched_at": q["fetched_at"].isoformat() if q.get("fetched_at") else None,
    }


# ---------- FA --------------------------------------------------------------

@app.get("/api/fa/{ticker}")
def fa(ticker: str):
    ticker = ticker.upper()
    quarters = db.fetch_all(
        "SELECT period_end, form, revenue, net_income, diluted_eps, gross_margin, net_margin "
        "FROM atlas.fundamentals WHERE ticker = %s "
        "ORDER BY period_end DESC LIMIT 8",
        (ticker,),
    )
    filings = db.fetch_all(
        "SELECT form, filed_at, period_of_report, url "
        "FROM atlas.filings WHERE ticker = %s "
        "ORDER BY filed_at DESC LIMIT 8",
        (ticker,),
    )
    if not quarters and not filings:
        _err(ticker, "no SEC data")
    return {
        "ticker": ticker,
        "quarters": [
            {**q, "period_end": str(q["period_end"]),
             "revenue": float(q["revenue"]) if q["revenue"] is not None else None,
             "net_income": float(q["net_income"]) if q["net_income"] is not None else None,
             "diluted_eps": float(q["diluted_eps"]) if q["diluted_eps"] is not None else None,
             "gross_margin": float(q["gross_margin"]) if q["gross_margin"] is not None else None,
             "net_margin": float(q["net_margin"]) if q["net_margin"] is not None else None}
            for q in quarters
        ],
        "filings": [
            {**f, "filed_at": str(f["filed_at"]),
             "period_of_report": str(f["period_of_report"]) if f["period_of_report"] else None}
            for f in filings
        ],
        "source": "SEC EDGAR",
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


# ---------- RISK ------------------------------------------------------------

@app.get("/api/risk")
def risk():
    # Pull last 253 trading days per watchlist ticker.
    end = db.fetch_one("SELECT MAX(ts) AS m FROM atlas.prices")
    if not end or not end["m"]:
        raise HTTPException(503, detail={"error": "no price data"})
    start = end["m"] - dt.timedelta(days=365 * 2)
    rows = db.fetch_all(
        "SELECT ticker, ts, adj_close FROM atlas.prices "
        "WHERE ts BETWEEN %s AND %s AND ticker IN (SELECT ticker FROM atlas.watchlist) "
        "ORDER BY ticker, ts",
        (start, end["m"]),
    )
    if not rows:
        raise HTTPException(503, detail={"error": "no price data"})
    prices_by_ticker: dict[str, pd.Series] = {}
    for r in rows:
        prices_by_ticker.setdefault(r["ticker"], pd.Series(dtype=float))
        s = prices_by_ticker[r["ticker"]]
        prices_by_ticker[r["ticker"]] = pd.concat([
            s, pd.Series([float(r["adj_close"])])
        ]).reset_index(drop=True)

    dgs3mo = fred.latest("DGS3MO")
    rfr = (dgs3mo[1] / 100.0) if dgs3mo else 0.0
    spy = prices_by_ticker.get("SPY")
    out_rows = []
    for t, s in prices_by_ticker.items():
        if len(s) < 30:
            continue
        out_rows.append({
            "ticker": t,
            "ann_return": risk_mod.annualized_return(s),
            "ann_vol": risk_mod.annualized_volatility(s),
            "sharpe": risk_mod.sharpe_ratio(s, rfr),
            "beta_spy": risk_mod.beta_vs_spy(s, spy) if spy is not None else None,
            "max_drawdown": risk_mod.max_drawdown(s),
        })

    corr = risk_mod.correlation_matrix(prices_by_ticker)
    return {
        "tickers": out_rows,
        "rfr": rfr,
        "correlation": {
            "tickers": list(corr.columns),
            "matrix": corr.round(4).values.tolist(),
        },
        "source": "yfinance (computed on last 252d)",
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


# ---------- NEWS ------------------------------------------------------------

@app.get("/api/news/{ticker}")
def news_endpoint(ticker: str):
    ticker = ticker.upper()
    rows = db.fetch_all(
        "SELECT title, publisher, published_at, url, source, sentiment_label, sentiment_score "
        "FROM atlas.headlines WHERE ticker = %s "
        "ORDER BY published_at DESC LIMIT 10",
        (ticker,),
    )
    scored = [r for r in rows if r.get("sentiment_label")]
    avg_label = None
    avg_score = None
    if scored:
        # Numeric score: positive=+1, neutral=0, negative=-1
        m = {"positive": 1, "neutral": 0, "negative": -1}
        signed = [m.get(r["sentiment_label"], 0) * float(r["sentiment_score"] or 0) for r in scored]
        s = sum(signed) / len(signed)
        avg_score = sum(float(r["sentiment_score"] or 0) for r in scored) / len(scored)
        if s > 0.15:
            avg_label = "positive"
        elif s < -0.15:
            avg_label = "negative"
        else:
            avg_label = "neutral"
    if not rows:
        _err(ticker, "no headlines")
    return {
        "ticker": ticker,
        "headlines": [
            {**r, "published_at": r["published_at"].isoformat()}
            for r in rows
        ],
        "avg_sentiment": {"label": avg_label, "score": avg_score},
        "source": "yfinance + Google News (sentiment: FinBERT)",
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


# ---------- ECO -------------------------------------------------------------

@app.get("/api/eco")
def eco():
    out = {}
    for sid in config.FRED_SERIES:
        rows = db.fetch_all(
            "SELECT ts, value FROM atlas.fred_series WHERE series_id = %s ORDER BY ts",
            (sid,),
        )
        out[sid] = [{"ts": str(r["ts"]), "value": float(r["value"])} for r in rows]

    # CPI YoY series.
    cpi_rows = out.get("CPIAUCSL", [])
    cpi_yoy = []
    for i in range(12, len(cpi_rows)):
        prev = cpi_rows[i - 12]["value"]
        cur = cpi_rows[i]["value"]
        if prev:
            cpi_yoy.append({"ts": cpi_rows[i]["ts"], "value": (cur - prev) / prev * 100})

    # Yield curve from latest values.
    def _latest(rows):
        return rows[-1]["value"] if rows else None

    yield_curve = {
        "3M": _latest(out.get("DGS3MO", [])),
        "2Y": _latest(out.get("DGS2", [])),
        "10Y": _latest(out.get("DGS10", [])),
    }
    return {
        "dff": out.get("DFF", []),
        "cpi_yoy": cpi_yoy,
        "unrate": out.get("UNRATE", []),
        "yield_curve": yield_curve,
        "source": "FRED (public CSV)",
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


# Vercel handler.
handler = Mangum(app, lifespan="off")