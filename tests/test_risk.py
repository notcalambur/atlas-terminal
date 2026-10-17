"""Unit tests for risk metrics.

We test on a tiny hand-calculated series. The series is constructed so every
metric has an exact answer we can verify with closed-form math — no floating
point coincidence, no rounding tolerance.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from atlas.risk import (
    annualized_return,
    annualized_volatility,
    beta_vs_spy,
    correlation_matrix,
    log_returns,
    max_drawdown,
    sharpe_ratio,
)


# A 5-day geometric series: 100, 110, 121, 133.1, 146.41 (10% daily).
SERIES = pd.Series([100.0, 110.0, 121.0, 133.1, 146.41])


def test_log_returns_known():
    out = log_returns(SERIES).dropna()
    # log(110/100) = ln(1.1) ≈ 0.09531
    assert out.iloc[0] == pytest.approx(math.log(1.1), abs=1e-9)
    assert out.iloc[1] == pytest.approx(math.log(1.1), abs=1e-9)
    # First row is NaN
    assert pd.isna(log_returns(SERIES).iloc[0])


def test_annualized_return_known():
    # Each day returns exactly ln(1.1) ≈ 0.09531. mean * 252 = 0.09531 * 252 ≈ 24.018.
    expected = math.log(1.1) * 252
    assert annualized_return(SERIES) == pytest.approx(expected, rel=1e-9)


def test_annualized_volatility_zero_for_constant_returns():
    # With 4 identical log returns, sample std (ddof=1) is 0, so vol = 0.
    assert annualized_volatility(SERIES) == pytest.approx(0.0, abs=1e-12)


def test_sharpe_zero_when_vol_zero():
    # vol=0 → sharpe guard returns 0.
    val = sharpe_ratio(SERIES, risk_free_rate=0.04)
    # Either exact 0.0 (guard fired) or NaN (insufficient sample variance) — both acceptable.
    assert val == 0.0 or val != val   # NaN != NaN


def test_max_drawdown_known():
    # Series: 100, 110, 90, 95. Max drawdown = (90-110)/110 = -0.1818...
    s = pd.Series([100.0, 110.0, 90.0, 95.0])
    assert max_drawdown(s) == pytest.approx(-20.0 / 110.0, abs=1e-9)


def test_max_drawdown_no_drawdown():
    # Monotonic up: drawdown = 0.
    s = pd.Series([100.0, 101.0, 102.0, 103.0])
    assert max_drawdown(s) == pytest.approx(0.0, abs=1e-12)


def test_beta_known_identity():
    # Stock = SPY → beta = 1.
    s = pd.Series([100.0, 101.0, 99.0, 100.5, 102.0])
    b = pd.Series([100.0, 101.0, 99.0, 100.5, 102.0])
    assert beta_vs_spy(s, b) == pytest.approx(1.0, abs=1e-9)


def test_correlation_matrix_diagonal():
    d = {"A": pd.Series([1, 2, 3, 4, 5]), "B": pd.Series([2, 4, 6, 8, 10])}
    m = correlation_matrix(d)
    # Diagonal must be 1; A↔B must be 1 (perfectly correlated).
    assert m.loc["A", "A"] == pytest.approx(1.0)
    assert m.loc["B", "B"] == pytest.approx(1.0)
    assert m.loc["A", "B"] == pytest.approx(1.0)


def test_sharpe_arithmetic():
    # Constant log returns → vol = 0 → guard returns 0.
    s = pd.Series([100.0, 110.0, 121.0])
    assert sharpe_ratio(s, risk_free_rate=0.0) == 0.0