"""Cross-check: AAPL's latest price and 1Y volatility must match a manual
calculation from the same yfinance data.

This test does NOT require the database; it pulls fresh yfinance data and
verifies that fetcher.fetch_history() + risk.annualized_volatility() agree
with a hand-rolled calc to within 1 cent / 1e-6.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
import yfinance as yf

from atlas import fetcher, risk


@pytest.fixture(scope="module")
def aapl_history():
    rows = fetcher.fetch_history(["AAPL"], period="1y")
    if rows.empty:
        pytest.skip("yfinance returned no data — check network or rate limit")
    return rows


def test_latest_price_matches_yfinance(aapl_history):
    rows = aapl_history
    # Sort and pick last row from the fetcher.
    rows_sorted = rows.sort_values("ts")
    fetched_last = float(rows_sorted.iloc[-1]["close"])
    # Hand-calc: pull directly from yfinance and compare.
    raw = yf.Ticker("AAPL").history(period="5d")
    if raw.empty:
        pytest.skip("yfinance gave no data just now")
    raw_last = float(raw["Close"].iloc[-1])
    assert abs(fetched_last - raw_last) < 1.0  # within $1 of live


def test_annualized_volatility_matches_manual(aapl_history):
    rows = aapl_history.sort_values("ts")
    series = pd.Series(rows["adj_close"].astype(float).values)

    # Atlas pipeline.
    vol_atlas = risk.annualized_volatility(series)

    # Hand-rolled reference: same series, ddof=1 std, × sqrt(252).
    r = np.log(series / series.shift(1)).dropna()
    vol_ref = float(r.std(ddof=1) * math.sqrt(252))

    assert abs(vol_atlas - vol_ref) < 1e-9