"""Risk metrics — exact definitions per the spec.

All functions take a pandas Series of adjusted close prices and return scalars.
Purity is deliberate: the only IO these functions do is on numbers. That
makes the unit tests in tests/test_risk.py both possible and meaningful.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def log_returns(prices: pd.Series) -> pd.Series:
    """Daily log returns r_t = ln(P_t / P_{t-1}). First value is NaN."""
    prices = pd.Series(prices).astype(float)
    out = np.log(prices / prices.shift(1))
    out.iloc[0] = np.nan
    return out


def annualized_volatility(prices: pd.Series) -> float:
    r = log_returns(prices).dropna()
    return float(r.std(ddof=1) * np.sqrt(252))


def annualized_return(prices: pd.Series) -> float:
    r = log_returns(prices).dropna()
    return float(r.mean() * 252)


def sharpe_ratio(prices: pd.Series, risk_free_rate: float) -> float:
    """Sharpe = (annualized_return - rfr) / annualized_volatility."""
    vol = annualized_volatility(prices)
    # Use an absolute epsilon — a 5-day geometric series produces vol on the
    # order of 1e-16 from floating-point noise alone.
    if vol < 1e-9:
        return 0.0
    return (annualized_return(prices) - risk_free_rate) / vol


def beta_vs_spy(stock_prices: pd.Series, spy_prices: pd.Series) -> float:
    r_s = log_returns(stock_prices).dropna()
    r_b = log_returns(spy_prices).dropna()
    # Align by date index.
    common = r_s.index.intersection(r_b.index)
    r_s = r_s.loc[common]
    r_b = r_b.loc[common]
    if len(r_s) < 2:
        return 0.0
    cov = float(np.cov(r_s, r_b, ddof=1)[0, 1])
    var_b = float(r_b.var(ddof=1))
    if var_b == 0:
        return 0.0
    return cov / var_b


def max_drawdown(prices: pd.Series) -> float:
    """Largest peak-to-trough decline over the period, as a negative number."""
    p = pd.Series(prices).astype(float)
    running_max = p.cummax()
    drawdown = (p - running_max) / running_max
    return float(drawdown.min())


def correlation_matrix(prices_by_ticker: dict[str, pd.Series]) -> pd.DataFrame:
    """Daily-return correlation matrix across the watchlist."""
    rets = pd.DataFrame({
        t: log_returns(s).dropna() for t, s in prices_by_ticker.items()
    })
    return rets.corr()


def last_252d_returns_window(prices: pd.Series, n: int = 252) -> pd.Series:
    """Trim a price series to the last `n` trading days (returns-based window)."""
    if len(prices) <= n + 1:
        return prices
    return prices.iloc[-(n + 1):]