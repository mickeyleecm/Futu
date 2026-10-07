-- 50 / 60 day simple moving averages (from OpenD daily K-line)
ALTER TABLE stock_market_data
    ADD COLUMN IF NOT EXISTS ma50 DECIMAL(20, 8) NULL COMMENT '50-day SMA (daily close, QFQ)' AFTER last_price,
    ADD COLUMN IF NOT EXISTS ma60 DECIMAL(20, 8) NULL COMMENT '60-day SMA (daily close, QFQ)' AFTER ma50;
