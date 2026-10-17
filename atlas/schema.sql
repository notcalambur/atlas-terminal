-- Atlas Terminal schema. Idempotent. Run once on init.

CREATE SCHEMA IF NOT EXISTS atlas;

SET search_path TO atlas, public;

-- Daily OHLCV per ticker (one row per trading day).
CREATE TABLE IF NOT EXISTS prices (
    ticker     TEXT        NOT NULL,
    ts         DATE        NOT NULL,
    open       NUMERIC(18,6),
    high       NUMERIC(18,6),
    low        NUMERIC(18,6),
    close      NUMERIC(18,6) NOT NULL,
    adj_close  NUMERIC(18,6) NOT NULL,
    volume     BIGINT,
    source     TEXT NOT NULL DEFAULT 'yfinance',
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, ts)
);
CREATE INDEX IF NOT EXISTS prices_ticker_ts_idx ON prices (ticker, ts DESC);

-- Latest intraday quote per ticker (refreshed every 15m during US hours).
CREATE TABLE IF NOT EXISTS quotes (
    ticker         TEXT PRIMARY KEY,
    last           NUMERIC(18,6),
    prev_close     NUMERIC(18,6),
    change_abs     NUMERIC(18,6),
    change_pct     NUMERIC(18,6),
    volume         BIGINT,
    fetched_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- SEC companyfacts: per-ticker, per-period fundamentals.
CREATE TABLE IF NOT EXISTS fundamentals (
    ticker        TEXT NOT NULL,
    period_end    DATE NOT NULL,
    form          TEXT NOT NULL,            -- 10-K / 10-Q
    revenue       NUMERIC(20,2),
    net_income    NUMERIC(20,2),
    diluted_eps   NUMERIC(12,4),
    gross_margin  NUMERIC(8,4),             -- 0..1
    net_margin    NUMERIC(8,4),
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, period_end, form)
);

-- SEC submissions: latest filings metadata.
CREATE TABLE IF NOT EXISTS filings (
    ticker        TEXT NOT NULL,
    form          TEXT NOT NULL,            -- 10-K / 10-Q / 8-K
    filed_at      DATE NOT NULL,
    period_of_report DATE,
    accession_no  TEXT NOT NULL,
    primary_doc   TEXT,
    url           TEXT NOT NULL,
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, accession_no)
);
CREATE INDEX IF NOT EXISTS filings_ticker_filed_idx ON filings (ticker, filed_at DESC);

-- News headlines + sentiment (pre-computed).
CREATE TABLE IF NOT EXISTS headlines (
    id              BIGSERIAL PRIMARY KEY,
    ticker          TEXT NOT NULL,
    title           TEXT NOT NULL,
    publisher       TEXT,
    published_at    TIMESTAMPTZ NOT NULL,
    url             TEXT NOT NULL,
    source          TEXT NOT NULL,           -- 'yfinance' | 'google_news'
    sentiment_label TEXT,                    -- positive | neutral | negative
    sentiment_score NUMERIC(5,4),            -- 0..1
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS headlines_ticker_pub_idx ON headlines (ticker, published_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS headlines_dedup_idx ON headlines (ticker, url);

-- FRED macro series (generic time-series, one table for any series id).
CREATE TABLE IF NOT EXISTS fred_series (
    series_id   TEXT NOT NULL,
    ts          DATE NOT NULL,
    value       NUMERIC(18,6) NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (series_id, ts)
);

-- Watchlist (which tickers to refresh — driven by this table).
CREATE TABLE IF NOT EXISTS watchlist (
    ticker     TEXT PRIMARY KEY,
    added_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed the fixed ticker universe.
INSERT INTO watchlist (ticker) VALUES
    ('AAPL'), ('MSFT'), ('NVDA'), ('AMZN'), ('GOOGL'),
    ('META'), ('TSLA'), ('JPM'), ('V'), ('SPY'), ('QQQ')
ON CONFLICT (ticker) DO NOTHING;