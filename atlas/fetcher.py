"""yfinance fetcher. Reads + writes into Postgres. Used by scheduler only.

Compatible with yfinance >= 1.0. For a single ticker the columns are flat
(Open/High/Low/Close/Adj Close/Volume). For multiple tickers they come back
as a MultiIndex (Ticker, Field). Both shapes are normalised into a single
long-form DataFrame here.
"""
from __future__ import annotations

import datetime as dt
from typing import Iterable

import pandas as pd
import yfinance as yf

from .config import TICKERS
from .db import execute, get_connection


def fetch_history(tickers: Iterable[str], period: str = "5y") -> pd.DataFrame:
    """Bulk-download daily OHLCV for `tickers`. Returns long-form DataFrame."""
    tickers = list(tickers)
    raw = yf.download(
        tickers,
        period=period,
        interval="1d",
        auto_adjust=False,
        progress=False,
    )
    if raw.empty:
        return pd.DataFrame(columns=[
            "ticker", "ts", "open", "high", "low", "close", "adj_close", "volume"
        ])

    multi = isinstance(raw.columns, pd.MultiIndex)
    out = []
    for t in tickers:
        if multi:
            try:
                sub = raw.xs(t, axis=1, level=1)
            except KeyError:
                continue
        else:
            sub = raw if t == tickers[0] else raw.iloc[0:0]
        for idx, row in sub.iterrows():
            ts = idx.date() if hasattr(idx, "date") else idx
            try:
                close = float(row["Close"])
            except (KeyError, TypeError, ValueError):
                continue
            if pd.isna(close):
                continue
            out.append((
                t,
                ts,
                _safe_float(row.get("Open")),
                _safe_float(row.get("High")),
                _safe_float(row.get("Low")),
                close,
                _safe_float(row.get("Adj Close"), default=close),
                _safe_int(row.get("Volume")),
            ))
    return pd.DataFrame(out, columns=[
        "ticker", "ts", "open", "high", "low", "close", "adj_close", "volume"
    ])


def _safe_float(v, default=None):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if not pd.isna(f) else default


def _safe_int(v, default=0):
    try:
        i = int(v)
    except (TypeError, ValueError):
        return default
    return i if not pd.isna(i) else default


def upsert_prices(rows: pd.DataFrame) -> int:
    if rows.empty:
        return 0
    sql = """
        INSERT INTO atlas.prices (ticker, ts, open, high, low, close, adj_close, volume, source)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'yfinance')
        ON CONFLICT (ticker, ts) DO UPDATE SET
            open       = EXCLUDED.open,
            high       = EXCLUDED.high,
            low        = EXCLUDED.low,
            close      = EXCLUDED.close,
            adj_close  = EXCLUDED.adj_close,
            volume     = EXCLUDED.volume,
            fetched_at = now()
    """
    payload = list(rows.itertuples(index=False, name=None))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, payload)
        conn.commit()
    return len(payload)


def fetch_intraday_quote(ticker: str) -> dict | None:
    """Latest intraday quote. Returns None on failure (caller surfaces 'data unavailable')."""
    t = yf.Ticker(ticker)
    info = {}
    try:
        info = t.fast_info
    except Exception:
        return None
    last = getattr(info, "last_price", None)
    prev = getattr(info, "previous_close", None)
    if last is None or prev is None:
        return None
    return {
        "ticker": ticker,
        "last": float(last),
        "prev_close": float(prev),
        "change_abs": float(last) - float(prev),
        "change_pct": (float(last) - float(prev)) / float(prev) if prev else 0.0,
        "volume": int(getattr(info, "last_volume", 0) or 0),
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def upsert_quote(q: dict) -> None:
    execute(
        """
        INSERT INTO atlas.quotes (ticker, last, prev_close, change_abs, change_pct, volume, fetched_at)
        VALUES (%(ticker)s, %(last)s, %(prev_close)s, %(change_abs)s, %(change_pct)s, %(volume)s, now())
        ON CONFLICT (ticker) DO UPDATE SET
            last       = EXCLUDED.last,
            prev_close = EXCLUDED.prev_close,
            change_abs = EXCLUDED.change_abs,
            change_pct = EXCLUDED.change_pct,
            volume     = EXCLUDED.volume,
            fetched_at = now()
        """,
        q,
    )


def run_full_refresh(tickers: Iterable[str] = TICKERS, period: str = "5y") -> dict:
    """End-to-end: download + upsert daily prices + every ticker quote."""
    tickers = list(tickers)
    rows = fetch_history(tickers, period=period)
    n = upsert_prices(rows)
    quotes = 0
    for t in tickers:
        q = fetch_intraday_quote(t)
        if q is not None:
            upsert_quote(q)
            quotes += 1
    return {"prices_rows": n, "quotes_updated": quotes}


if __name__ == "__main__":
    import sys
    print(run_full_refresh(period=sys.argv[1] if len(sys.argv) > 1 else "5y"))