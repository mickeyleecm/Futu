-- Futu trading / market-data schema
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS statements (
    id              BIGSERIAL PRIMARY KEY,
    filename        TEXT NOT NULL,
    file_sha256     CHAR(64) NOT NULL UNIQUE,
    statement_month DATE,
    account_id      TEXT,
    uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    page_count      INT,
    raw_text_preview TEXT,
    parse_status    TEXT NOT NULL DEFAULT 'ok',
    parse_message   TEXT
);

CREATE TABLE IF NOT EXISTS transactions (
    id              BIGSERIAL PRIMARY KEY,
    statement_id    BIGINT REFERENCES statements(id) ON DELETE CASCADE,
    trade_date      DATE NOT NULL,
    settle_date     DATE,
    code            TEXT NOT NULL,
    name            TEXT,
    side            TEXT NOT NULL CHECK (side IN ('BUY', 'SELL', 'DIVIDEND', 'FEE', 'DEPOSIT', 'WITHDRAW', 'OTHER')),
    quantity        NUMERIC(20, 6) DEFAULT 0,
    price           NUMERIC(20, 8) DEFAULT 0,
    amount          NUMERIC(20, 6) DEFAULT 0,
    commission      NUMERIC(20, 6) DEFAULT 0,
    stamp_duty      NUMERIC(20, 6) DEFAULT 0,
    trading_fee     NUMERIC(20, 6) DEFAULT 0,
    settlement_fee  NUMERIC(20, 6) DEFAULT 0,
    platform_fee    NUMERIC(20, 6) DEFAULT 0,
    other_fee       NUMERIC(20, 6) DEFAULT 0,
    total_fee       NUMERIC(20, 6) DEFAULT 0,
    net_amount      NUMERIC(20, 6) DEFAULT 0,
    currency        TEXT NOT NULL DEFAULT 'HKD',
    market          TEXT,
    product_type    TEXT NOT NULL DEFAULT 'STOCK',
    remark          TEXT,
    raw_line        TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_transactions_trade_date ON transactions(trade_date);
CREATE INDEX IF NOT EXISTS idx_transactions_code ON transactions(code);
CREATE INDEX IF NOT EXISTS idx_transactions_product_type ON transactions(product_type);
CREATE INDEX IF NOT EXISTS idx_transactions_statement ON transactions(statement_id);

-- For future Futu market data persistence
CREATE TABLE IF NOT EXISTS market_quotes (
    id              BIGSERIAL PRIMARY KEY,
    code            TEXT NOT NULL,
    name            TEXT,
    quote_time      TIMESTAMPTZ NOT NULL,
    last_price      NUMERIC(20, 8),
    open_price      NUMERIC(20, 8),
    high_price      NUMERIC(20, 8),
    low_price       NUMERIC(20, 8),
    prev_close      NUMERIC(20, 8),
    change_val      NUMERIC(20, 8),
    change_pct      NUMERIC(20, 8),
    volume          NUMERIC(20, 4),
    turnover        NUMERIC(20, 4),
    bid_price       NUMERIC(20, 8),
    ask_price       NUMERIC(20, 8),
    product_type    TEXT,
    source          TEXT DEFAULT 'opend',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_market_quotes_code_time ON market_quotes(code, quote_time DESC);
