"""Copy statements/transactions from Postgres (temp) into MariaDB."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymysql
import psycopg2
import psycopg2.extras


def main() -> int:
    pg = psycopg2.connect(
        host=os.environ.get("PG_HOST", "127.0.0.1"),
        port=int(os.environ.get("PG_PORT", "5433")),
        dbname=os.environ.get("PG_DB", "futu"),
        user=os.environ.get("PG_USER", "mickylee"),
        password=os.environ.get("PG_PASSWORD", "Mn12345678"),
    )
    maria = pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("MYSQL_PORT", "3309")),
        database=os.environ.get("MYSQL_DATABASE", "futu"),
        user=os.environ.get("MYSQL_USER", "mickylee"),
        password=os.environ.get("MYSQL_PASSWORD", "Mn12345678"),
        charset="utf8mb4",
        autocommit=False,
    )
    try:
        with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as pcur:
            pcur.execute("SELECT * FROM statements ORDER BY id")
            stmts = [dict(r) for r in pcur.fetchall()]
            pcur.execute("SELECT * FROM transactions ORDER BY id")
            txns = [dict(r) for r in pcur.fetchall()]

        print(f"Read PG: statements={len(stmts)} transactions={len(txns)}")

        with maria.cursor() as cur:
            cur.execute("SET FOREIGN_KEY_CHECKS=0")
            cur.execute("TRUNCATE TABLE transactions")
            cur.execute("TRUNCATE TABLE statements")
            cur.execute("TRUNCATE TABLE market_quotes")

            for r in stmts:
                cur.execute(
                    """
                    INSERT INTO statements (
                        id, filename, file_sha256, statement_month, account_id,
                        uploaded_at, page_count, raw_text_preview, parse_status, parse_message
                    ) VALUES (
                        %(id)s, %(filename)s, %(file_sha256)s, %(statement_month)s, %(account_id)s,
                        %(uploaded_at)s, %(page_count)s, %(raw_text_preview)s, %(parse_status)s, %(parse_message)s
                    )
                    """,
                    r,
                )

            for r in txns:
                cur.execute(
                    """
                    INSERT INTO transactions (
                        id, statement_id, trade_date, settle_date, code, name, side,
                        quantity, price, amount, commission, stamp_duty, trading_fee,
                        settlement_fee, platform_fee, other_fee, total_fee, net_amount,
                        currency, market, product_type, remark, raw_line, created_at
                    ) VALUES (
                        %(id)s, %(statement_id)s, %(trade_date)s, %(settle_date)s, %(code)s, %(name)s, %(side)s,
                        %(quantity)s, %(price)s, %(amount)s, %(commission)s, %(stamp_duty)s, %(trading_fee)s,
                        %(settlement_fee)s, %(platform_fee)s, %(other_fee)s, %(total_fee)s, %(net_amount)s,
                        %(currency)s, %(market)s, %(product_type)s, %(remark)s, %(raw_line)s, %(created_at)s
                    )
                    """,
                    r,
                )

            max_s = max((r["id"] for r in stmts), default=0)
            max_t = max((r["id"] for r in txns), default=0)
            cur.execute(f"ALTER TABLE statements AUTO_INCREMENT = {int(max_s) + 1}")
            cur.execute(f"ALTER TABLE transactions AUTO_INCREMENT = {int(max_t) + 1}")
            cur.execute("SET FOREIGN_KEY_CHECKS=1")
        maria.commit()
        print(f"OK MariaDB import complete")
        return 0
    except Exception as exc:  # noqa: BLE001
        maria.rollback()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        pg.close()
        maria.close()


if __name__ == "__main__":
    raise SystemExit(main())
