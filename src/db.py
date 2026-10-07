"""MariaDB helpers for statements, transactions, and market quotes."""

from __future__ import annotations

import hashlib
import logging
import os
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterator, Optional

import pymysql
from pymysql.cursors import DictCursor

logger = logging.getLogger(__name__)


def db_config() -> dict[str, Any]:
    return {
        "host": os.environ.get("MYSQL_HOST", "127.0.0.1"),
        "port": int(os.environ.get("MYSQL_PORT", "3306")),
        "database": os.environ.get("MYSQL_DATABASE", "futu"),
        "user": os.environ.get("MYSQL_USER", "mickylee"),
        "password": os.environ.get("MYSQL_PASSWORD", "Mn12345678"),
        "charset": "utf8mb4",
        "autocommit": False,
        "cursorclass": DictCursor,
    }


def is_db_available() -> bool:
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Database unavailable: %s", exc)
        return False


@contextmanager
def get_conn() -> Iterator[Any]:
    conn = pymysql.connect(**db_config())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def file_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def insert_statement(
    *,
    filename: str,
    file_sha256_hex: str,
    statement_month: Optional[date],
    account_id: Optional[str],
    page_count: int,
    raw_text_preview: str,
    parse_status: str,
    parse_message: Optional[str],
) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO statements (
                    filename, file_sha256, statement_month, account_id,
                    page_count, raw_text_preview, parse_status, parse_message
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                    id = LAST_INSERT_ID(id),
                    uploaded_at = CURRENT_TIMESTAMP(6),
                    filename = VALUES(filename),
                    statement_month = VALUES(statement_month),
                    account_id = VALUES(account_id),
                    page_count = VALUES(page_count),
                    raw_text_preview = VALUES(raw_text_preview),
                    parse_status = VALUES(parse_status),
                    parse_message = VALUES(parse_message)
                """,
                (
                    filename,
                    file_sha256_hex,
                    statement_month,
                    account_id,
                    page_count,
                    raw_text_preview[:5000] if raw_text_preview else None,
                    parse_status,
                    parse_message,
                ),
            )
            return int(cur.lastrowid)


def delete_transactions_for_statement(statement_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM transactions WHERE statement_id = %s", (statement_id,)
            )


def insert_transactions(statement_id: int, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    sql = """
        INSERT INTO transactions (
            statement_id, trade_date, settle_date, code, name, side,
            quantity, price, amount, commission, stamp_duty, trading_fee,
            settlement_fee, platform_fee, other_fee, total_fee, net_amount,
            currency, market, product_type, remark, raw_line
        ) VALUES (
            %(statement_id)s, %(trade_date)s, %(settle_date)s, %(code)s, %(name)s, %(side)s,
            %(quantity)s, %(price)s, %(amount)s, %(commission)s, %(stamp_duty)s, %(trading_fee)s,
            %(settlement_fee)s, %(platform_fee)s, %(other_fee)s, %(total_fee)s, %(net_amount)s,
            %(currency)s, %(market)s, %(product_type)s, %(remark)s, %(raw_line)s
        )
    """
    payload = [{**r, "statement_id": statement_id} for r in rows]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, payload)
            return len(rows)


def list_transactions(
    *,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    product_type: Optional[str] = None,
    code: Optional[str] = None,
    limit: int = 2000,
) -> list[dict[str, Any]]:
    clauses = ["1=1"]
    params: list[Any] = []
    if date_from:
        clauses.append("trade_date >= %s")
        params.append(date_from)
    if date_to:
        clauses.append("trade_date <= %s")
        params.append(date_to)
    if product_type:
        clauses.append("product_type = %s")
        params.append(product_type)
    if code:
        clauses.append("code LIKE %s")
        params.append(f"%{code}%")
    params.append(limit)
    sql = f"""
        SELECT id, statement_id, trade_date, settle_date, code, name, side,
               quantity, price, amount, commission, stamp_duty, trading_fee,
               settlement_fee, platform_fee, other_fee, total_fee, net_amount,
               currency, market, product_type, remark
        FROM transactions
        WHERE {' AND '.join(clauses)}
        ORDER BY trade_date DESC, id DESC
        LIMIT %s
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [_serialize_row(r) for r in cur.fetchall()]


def list_option_warrant_trades(
    *,
    code: Optional[str] = None,
    limit: int = 10000,
) -> list[dict[str, Any]]:
    """All OPTION/WARRANT rows (full history) for FIFO pair matching."""
    clauses = ["product_type IN ('OPTION', 'WARRANT')", "side IN ('BUY', 'SELL')"]
    params: list[Any] = []
    if code:
        clauses.append("code LIKE %s")
        params.append(f"%{code}%")
    params.append(limit)
    sql = f"""
        SELECT id, statement_id, trade_date, settle_date, code, name, side,
               quantity, price, amount, total_fee, net_amount,
               currency, market, product_type, remark
        FROM transactions
        WHERE {' AND '.join(clauses)}
        ORDER BY trade_date ASC, id ASC
        LIMIT %s
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [_serialize_row(r) for r in cur.fetchall()]


def pnl_by_product(
    *,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> list[dict[str, Any]]:
    """
    Cash-flow style P&L by product type for the period:
      BUY / FEE / WITHDRAW contribute negative cash
      SELL / DIVIDEND / DEPOSIT contribute positive cash
    """
    clauses = ["1=1"]
    params: list[Any] = []
    if date_from:
        clauses.append("trade_date >= %s")
        params.append(date_from)
    if date_to:
        clauses.append("trade_date <= %s")
        params.append(date_to)
    sql = f"""
        SELECT
            product_type,
            COALESCE(NULLIF(UPPER(currency), ''), 'HKD') AS currency,
            COUNT(*) AS trade_count,
            SUM(CASE WHEN side = 'BUY' THEN quantity ELSE 0 END) AS buy_qty,
            SUM(CASE WHEN side = 'SELL' THEN quantity ELSE 0 END) AS sell_qty,
            SUM(CASE WHEN side = 'BUY' THEN amount ELSE 0 END) AS buy_amount,
            SUM(CASE WHEN side = 'SELL' THEN amount ELSE 0 END) AS sell_amount,
            SUM(total_fee) AS total_fees,
            SUM(CASE
                WHEN side IN ('SELL', 'DIVIDEND', 'DEPOSIT') THEN COALESCE(net_amount, amount)
                WHEN side IN ('BUY', 'FEE', 'WITHDRAW') THEN -ABS(COALESCE(net_amount, amount))
                ELSE COALESCE(net_amount, 0)
            END) AS realized_pnl
        FROM transactions
        WHERE {' AND '.join(clauses)}
        GROUP BY product_type, COALESCE(NULLIF(UPPER(currency), ''), 'HKD')
        ORDER BY product_type, currency
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [_serialize_row(r) for r in cur.fetchall()]


def list_statements(limit: int = 50) -> list[dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT s.*,
                       (SELECT COUNT(*) FROM transactions t WHERE t.statement_id = s.id) AS txn_count
                FROM statements s
                ORDER BY s.uploaded_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            return [_serialize_row(r) for r in cur.fetchall()]


def get_usd_hkd_rate(
    *,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    default: float = 7.8,
) -> float:
    """
    Prefer 參考匯率 USD/HKD from the latest statement in range
    (falls back to any statement, then default).
    """
    from src.statement_parser import extract_fx_rates

    clauses = ["raw_text_preview IS NOT NULL"]
    params: list[Any] = []
    if date_from:
        clauses.append(
            "(statement_month IS NULL OR statement_month >= DATE_FORMAT(%s, '%%Y-%%m-01'))"
        )
        params.append(date_from)
    if date_to:
        clauses.append("(statement_month IS NULL OR statement_month <= %s)")
        params.append(date_to)
    sql = f"""
        SELECT raw_text_preview
        FROM statements
        WHERE {' AND '.join(clauses)}
        ORDER BY statement_month IS NULL, statement_month DESC, uploaded_at DESC
        LIMIT 5
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            if not rows:
                cur.execute(
                    """
                    SELECT raw_text_preview FROM statements
                    WHERE raw_text_preview IS NOT NULL
                    ORDER BY statement_month IS NULL, statement_month DESC, uploaded_at DESC
                    LIMIT 5
                    """
                )
                rows = cur.fetchall()
    for row in rows:
        preview = row["raw_text_preview"] if isinstance(row, dict) else row[0]
        rates = extract_fx_rates(preview or "")
        if "USDHKD" in rates:
            return float(rates["USDHKD"])
    return default


def transaction_counts_by_month() -> dict[str, int]:
    """Map 'YYYY-MM-01' → transaction count for that calendar month."""
    # No query params here — use single % for DATE_FORMAT (do not escape as %%).
    sql = """
        SELECT DATE_FORMAT(trade_date, '%Y-%m-01') AS month, COUNT(*) AS cnt
        FROM transactions
        GROUP BY 1
        ORDER BY 1
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            out: dict[str, int] = {}
            for r in cur.fetchall():
                month = r["month"]
                if not month:
                    continue
                if hasattr(month, "isoformat"):
                    out[month.isoformat()] = int(r["cnt"])
                else:
                    out[str(month)] = int(r["cnt"])
            return out


def monthly_pair_summaries(
    *,
    start_month: Optional[date] = None,
) -> list[dict[str, Any]]:
    """
    Per-month closed option/warrant pair stats from April (or earliest data).
    Uses full trade history for FIFO matching; attributes P&L by close month.
    """
    from calendar import monthrange

    from src.pair_pnl import pair_option_warrant_trades

    deriv = list_option_warrant_trades()
    txn_counts = transaction_counts_by_month()

    months: set[date] = set()
    for key in txn_counts:
        months.add(date.fromisoformat(key))
    for t in deriv:
        td = t.get("trade_date")
        if td is None:
            continue
        if isinstance(td, str):
            td = date.fromisoformat(td[:10])
        months.add(date(td.year, td.month, 1))

    if not months:
        return []

    last = max(months)
    april = start_month or date(min(m.year for m in months), 4, 1)

    out: list[dict[str, Any]] = []
    y, m = april.year, april.month
    end = date(last.year, last.month, 1)
    while date(y, m, 1) <= end:
        month_start = date(y, m, 1)
        month_end = date(y, m, monthrange(y, m)[1])
        key = month_start.isoformat()
        pairs = pair_option_warrant_trades(
            deriv, date_from=month_start, date_to=month_end
        )
        by_ccy = pairs.get("realized_pnl_by_currency") or {}
        hkd = float(by_ccy.get("HKD") or 0)
        usd = float(by_ccy.get("USD") or 0)
        rate = get_usd_hkd_rate(date_from=month_start, date_to=month_end)
        out.append(
            {
                "month": key,
                "month_label": month_start.strftime("%Y-%m"),
                "transaction_count": int(txn_counts.get(key, 0)),
                "closed_pairs": int(pairs.get("pair_count") or 0),
                "closed_pnl_hkd": hkd,
                "closed_pnl_usd": usd,
                "usd_hkd_rate": rate,
                "closed_pnl_hkd_base": hkd + usd * rate,
                "win_count": int(pairs.get("win_count") or 0),
                "loss_count": int(pairs.get("loss_count") or 0),
                "win_rate_pct": pairs.get("win_rate_pct"),
            }
        )
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return out


def insert_market_quote(row: dict[str, Any]) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO market_quotes (
                    code, name, quote_time, last_price, open_price, high_price, low_price,
                    prev_close, change_val, change_pct, volume, turnover, bid_price, ask_price,
                    product_type, source
                ) VALUES (
                    %(code)s, %(name)s, %(quote_time)s, %(last_price)s, %(open_price)s,
                    %(high_price)s, %(low_price)s, %(prev_close)s, %(change_val)s, %(change_pct)s,
                    %(volume)s, %(turnover)s, %(bid_price)s, %(ask_price)s, %(product_type)s, %(source)s
                )
                """,
                row,
            )


_STOCK_SNAPSHOT_COLS = (
    "code",
    "name",
    "name_zh",
    "market",
    "product_type",
    "last_price",
    "ma50",
    "ma60",
    "open_price",
    "high_price",
    "low_price",
    "prev_close",
    "change_val",
    "change_pct",
    "volume",
    "turnover",
    "bid_price",
    "ask_price",
    "avg_price",
    "amplitude",
    "volume_ratio",
    "bid_ask_ratio",
    "bid_vol",
    "ask_vol",
    "pe_ratio",
    "pe_ttm_ratio",
    "pb_ratio",
    "total_market_val",
    "circular_market_val",
    "issued_shares",
    "outstanding_shares",
    "turnover_rate",
    "lot_size",
    "highest52weeks_price",
    "lowest52weeks_price",
    "highest_history_price",
    "lowest_history_price",
    "dividend_ttm",
    "dividend_ratio_ttm",
    "dividend_lfy",
    "dividend_lfy_ratio",
    "earning_per_share",
    "net_asset_per_share",
    "listing_date",
    "sec_status",
    "suspension",
    "currency",
    "quote_time",
    "is_favourite",
    "remark",
    "source",
)


def upsert_stock_market_data(row: dict[str, Any]) -> None:
    """Insert or update one symbol in stock_market_data (keeps is_favourite unless provided)."""
    payload = {c: row.get(c) for c in _STOCK_SNAPSHOT_COLS}
    payload["code"] = row["code"]
    payload["product_type"] = row.get("product_type") or "STOCK"
    payload["is_favourite"] = row.get("is_favourite", 0)
    payload["source"] = row.get("source") or "opend"

    cols = ", ".join(_STOCK_SNAPSHOT_COLS)
    placeholders = ", ".join(f"%({c})s" for c in _STOCK_SNAPSHOT_COLS)
    updates = []
    for c in _STOCK_SNAPSHOT_COLS:
        if c == "code":
            continue
        if c == "is_favourite":
            updates.append(
                "is_favourite = IF(VALUES(is_favourite) IS NULL, is_favourite, VALUES(is_favourite))"
            )
        else:
            # Partial updates (e.g. MA-only) must not NULL out existing quote fields
            updates.append(f"{c} = COALESCE(VALUES({c}), {c})")

    sql = f"""
        INSERT INTO stock_market_data ({cols})
        VALUES ({placeholders})
        ON DUPLICATE KEY UPDATE {', '.join(updates)}
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, payload)


def set_stock_favourite(code: str, is_favourite: bool = True) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO stock_market_data (code, is_favourite)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE is_favourite = VALUES(is_favourite)
                """,
                (code, 1 if is_favourite else 0),
            )


def list_stock_market_data(
    *,
    favourites_only: bool = False,
    market: Optional[str] = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    clauses = ["1=1"]
    params: list[Any] = []
    if favourites_only:
        clauses.append("is_favourite = 1")
    if market:
        clauses.append("market = %s")
        params.append(market)
    params.append(limit)
    sql = f"""
        SELECT *
        FROM stock_market_data
        WHERE {' AND '.join(clauses)}
        ORDER BY is_favourite DESC, code ASC
        LIMIT %s
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [_serialize_row(r) for r in cur.fetchall()]


_OPTION_MARKET_COLS = (
    "code",
    "name",
    "underlying",
    "underlying_price",
    "option_type",
    "strike_price",
    "expiry",
    "expiration_cycle",
    "strike_offset",
    "last_price",
    "bid_price",
    "ask_price",
    "mid_price",
    "prev_close",
    "change_val",
    "change_pct",
    "volume",
    "turnover",
    "open_interest",
    "iv",
    "delta",
    "gamma",
    "vega",
    "theta",
    "rho",
    "premium",
    "lot_size",
    "contract_size",
    "expiry_days",
    "suspension",
    "quote_time",
    "source",
)


def upsert_option_market_data(row: dict[str, Any]) -> None:
    """Insert or update one option contract in option_market_data."""
    payload = {c: row.get(c) for c in _OPTION_MARKET_COLS}
    payload["code"] = row["code"]
    payload["underlying"] = row["underlying"]
    payload["option_type"] = row["option_type"]
    payload["strike_price"] = row["strike_price"]
    payload["expiry"] = row["expiry"]
    payload["source"] = row.get("source") or "opend"

    cols = ", ".join(_OPTION_MARKET_COLS)
    placeholders = ", ".join(f"%({c})s" for c in _OPTION_MARKET_COLS)
    updates = []
    for c in _OPTION_MARKET_COLS:
        if c == "code":
            continue
        updates.append(f"{c} = COALESCE(VALUES({c}), {c})")

    sql = f"""
        INSERT INTO option_market_data ({cols})
        VALUES ({placeholders})
        ON DUPLICATE KEY UPDATE {', '.join(updates)}
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, payload)


def list_option_market_data(
    *,
    underlying: Optional[str] = None,
    expiry: Optional[str] = None,
    limit: int = 2000,
) -> list[dict[str, Any]]:
    clauses = ["1=1"]
    params: list[Any] = []
    if underlying:
        clauses.append("underlying = %s")
        params.append(underlying)
    if expiry:
        clauses.append("expiry = %s")
        params.append(expiry)
    params.append(limit)
    sql = f"""
        SELECT *
        FROM option_market_data
        WHERE {' AND '.join(clauses)}
        ORDER BY underlying ASC, expiry ASC, strike_price ASC, option_type ASC
        LIMIT %s
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [_serialize_row(r) for r in cur.fetchall()]


def _serialize_row(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in dict(row).items():
        if isinstance(v, Decimal):
            out[k] = float(v)
        elif isinstance(v, (date, datetime)):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out
