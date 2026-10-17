"""yfinance fetcher. Reads + writes into Postgres. Used by scheduler only."""
from __future__ import annotations

import datetime as dt
from typing import Iterable

import pandas as pd
import yfinance as yf

from .config import TICKERS
from .db import execute


def _norm(s: str) -> str:
    """yfinance sometimes returns columns with MultiIndex tuples; flatten."""
    if isinstance(s, tuple):
        return s[0]
    return s


def fetch_history(tickers: Iterable[str], period: str = "5y") -> pd.DataFrame:
    """Bulk-download daily OHLCV for `tickers`. Returns long-form DataFrame."""
    tickers = list(tickers)
    raw = yf.download(
        tickers,
        period=period,
        interval="1d",
        auto_adjust=False,
        progress=False,
        group_by="column",
    )
    # When `tickers` has length > 1, columns are MultiIndex (Field, Ticker).
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [_norm(c) for c in raw.columns.get_level_values(0)], raw.columns.get_level_values(1)
    out = []
    for t in tickers:
        if isinstance(raw.columns, pd.MultiIndex):
            sub = raw.xs(t, axis=1, level=1)
        else:
            sub = raw.copy()
        sub = sub.rename_axis("ts").reset_index()
        for _, row in sub.iterrows():
            if pd.isna(row["Close"]):
                continue
            out.append((
                t,
                row["ts"].date() if hasattr(row["ts"], "date") else row["ts"],
                float(row["Open"]) if not pd.isna(row["Open"]) else None,
                float(row["High"]) if not pd.isna(row["High"]) else None,
                float(row["Low"]) if not pd.isna(row["Low"]) else None,
                float(row["Close"]),
                float(row["Adj Close"]),
                int(row["Volume"]) if not pd.isna(row["Volume"]) else 0,
            ))
    return pd.DataFrame(out, columns=[
        "ticker", "ts", "open", "high", "low", "close", "adj_close", "volume"
    ])


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
    with __import__("psycopg").connect(__import__("os").environ.get(
        "DATABASE_URL",
        "postgresql://jesse_user:jesse_password@dokploy-postgres:5432/atlas"
    )) as conn:
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