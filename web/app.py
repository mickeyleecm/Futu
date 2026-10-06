"""
Web server: live HK option chain + statement upload / transactions / P&L.

Run (OpenD optional for statement pages; required for live quotes):
  py run_web.py
  Open http://127.0.0.1:8080
       http://127.0.0.1:8080/transactions
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.db import (
    delete_transactions_for_statement,
    file_sha256,
    get_usd_hkd_rate,
    insert_statement,
    insert_transactions,
    is_db_available,
    list_option_warrant_trades,
    list_statements,
    list_transactions,
    monthly_pair_summaries,
    pnl_by_product,
)
from src.futu_market_data import FutuMarketDataClient
from src.option_chain_board import build_option_chain_board, list_expirations
from src.pair_pnl import pair_option_warrant_trades
from src.product_info import enrich_product_fields
from src.statement_parser import parse_statement_bytes

logger = logging.getLogger(__name__)

STATIC = Path(__file__).resolve().parent / "static"
UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

_client: FutuMarketDataClient | None = None


def _symbol_display(code: str) -> str:
    if "." in code:
        return code.split(".", 1)[1]
    return code


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Do not block startup on OpenD — quotes connect lazily; statements use DB only."""
    global _client
    _client = None
    logger.info("Web started. OpenD connects on first quote request. DB=%s", is_db_available())
    yield
    if _client is not None:
        try:
            _client.disconnect()
        except Exception:  # noqa: BLE001
            pass
        _client = None


app = FastAPI(title="Futu Market & Statements", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def _ensure_quote_client() -> FutuMarketDataClient:
    global _client
    if _client is not None and _client.is_connected:
        return _client
    try:
        client = FutuMarketDataClient()
        client.connect()
        _client = client
        return client
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            503,
            f"OpenD not connected ({exc}). Start FutuOpenD for live quotes.",
        ) from exc


def _client_or_raise() -> FutuMarketDataClient:
    return _ensure_quote_client()


def _db_or_raise() -> None:
    if not is_db_available():
        raise HTTPException(503, "Database not available")


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/transactions")
async def transactions_page():
    return FileResponse(STATIC / "transactions.html")


@app.get("/api/health")
async def health():
    opend = None
    connected = False
    if _client is not None:
        opend = f"{_client.opend_host}:{_client.opend_port}"
        connected = _client.is_connected
    return {
        "ok": True,
        "opend": opend or f"{__import__('os').environ.get('FUTU_OPEND_HOST', 'host.docker.internal')}:{__import__('os').environ.get('FUTU_OPEND_PORT', '11111')}",
        "connected": connected,
        "database": is_db_available(),
    }


@app.get("/api/symbols")
async def symbols():
    c = _client_or_raise()
    cats = c.symbols_by_category()
    hk_stocks = cats.get("hk_stocks", [])
    indices = cats.get("indices", [])

    all_codes = hk_stocks + indices
    names: dict[str, str] = {}
    prices: dict[str, float | None] = {}
    if all_codes:
        df, _ = c.get_snapshots_safe(all_codes)
        if not df.empty:
            for _, row in df.iterrows():
                code = str(row.get("code", ""))
                names[code] = str(row.get("name", "") or "")
                lp = row.get("last_price")
                prices[code] = float(lp) if lp is not None and str(lp) != "nan" else None

    def _items(codes: list[str]) -> list[dict]:
        return [
            {
                "code": code,
                "display": _symbol_display(code),
                "name": names.get(code, ""),
                "last_price": prices.get(code),
            }
            for code in codes
        ]

    return {
        "ok": True,
        "hk_stocks": _items(hk_stocks),
        "indices": _items(indices),
    }


@app.get("/api/expirations")
async def expirations(underlying: str = Query(..., description="e.g. HK.00823")):
    result = list_expirations(_client_or_raise(), underlying)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "Failed"))
    return result


@app.get("/api/chain")
async def chain(
    underlying: str = Query(..., description="e.g. HK.00823"),
    expiry: str = Query(..., description="yyyy-MM-dd"),
):
    result = build_option_chain_board(_client_or_raise(), underlying, expiry)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "Failed"))
    return result


@app.post("/api/statements/upload")
async def upload_statement(file: UploadFile = File(...)):
    _db_or_raise()
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Please upload a PDF statement file")

    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")

    sha = file_sha256(data)
    save_path = UPLOAD_DIR / f"{sha}_{Path(file.filename).name}"
    save_path.write_bytes(data)

    parsed = parse_statement_bytes(data, file.filename)
    status = "ok" if parsed.transactions else "partial"
    message = "; ".join(parsed.warnings) if parsed.warnings else None

    statement_id = insert_statement(
        filename=file.filename,
        file_sha256_hex=sha,
        statement_month=parsed.statement_month,
        account_id=parsed.account_id,
        page_count=parsed.page_count,
        raw_text_preview=parsed.raw_text[:3000],
        parse_status=status,
        parse_message=message,
    )
    # Re-import: replace previous transactions for this statement file
    delete_transactions_for_statement(statement_id)
    rows = [t.to_db_row() for t in parsed.transactions]
    inserted = insert_transactions(statement_id, rows)

    return {
        "ok": True,
        "statement_id": statement_id,
        "filename": file.filename,
        "statement_month": parsed.statement_month.isoformat()
        if parsed.statement_month
        else None,
        "account_id": parsed.account_id,
        "page_count": parsed.page_count,
        "transactions_inserted": inserted,
        "warnings": parsed.warnings,
        "sample": rows[:5],
    }


@app.get("/api/statements")
async def statements():
    _db_or_raise()
    return {"ok": True, "statements": list_statements()}


@app.get("/api/transactions")
async def transactions(
    date_from: str | None = Query(None, description="yyyy-MM-dd"),
    date_to: str | None = Query(None, description="yyyy-MM-dd"),
    product_type: str | None = Query(None),
    code: str | None = Query(None),
    limit: int = Query(2000, ge=1, le=10000),
):
    _db_or_raise()

    def _d(s: str | None) -> date | None:
        if not s:
            return None
        return datetime.strptime(s, "%Y-%m-%d").date()

    try:
        df = _d(date_from)
        dt = _d(date_to)
    except ValueError as exc:
        raise HTTPException(400, f"Invalid date: {exc}") from exc

    rows = [
        enrich_product_fields(r)
        for r in list_transactions(
            date_from=df, date_to=dt, product_type=product_type, code=code, limit=limit
        )
    ]
    # Match pairs on full OPTION/WARRANT history; filter closed pairs by date range
    deriv = list_option_warrant_trades(code=code)
    if product_type and product_type.upper() not in ("OPTION", "WARRANT", ""):
        pairs_payload = {
            "pairs": [],
            "open_lots": [],
            "pair_count": 0,
            "closed_with_open_count": 0,
            "closed_prior_unknown_count": 0,
            "open_count": 0,
            "total_realized_pnl": 0.0,
            "realized_pnl_by_product": {},
        }
    else:
        pairs_payload = pair_option_warrant_trades(
            deriv, date_from=df, date_to=dt
        )
        pairs_payload["pairs"] = [
            enrich_product_fields(p) for p in pairs_payload.get("pairs", [])
        ]
        pairs_payload["open_lots"] = [
            enrich_product_fields(p) for p in pairs_payload.get("open_lots", [])
        ]

    # OPTION/WARRANT P&L = closed pairs only, split by currency
    pnl = pnl_by_product(date_from=df, date_to=dt)
    closed_by_ccy = pairs_payload.get("realized_pnl_by_product_currency") or {}
    for row in pnl:
        pt = (row.get("product_type") or "").upper()
        ccy = (row.get("currency") or "HKD").upper()
        if pt in ("OPTION", "WARRANT"):
            row["realized_pnl"] = float((closed_by_ccy.get(pt) or {}).get(ccy, 0.0))
            row["pnl_basis"] = "closed_pairs_only"
        else:
            row["pnl_basis"] = "cash_flow"

    usd_hkd = get_usd_hkd_rate(date_from=df, date_to=dt)
    by_ccy = pairs_payload.get("realized_pnl_by_currency") or {}
    hkd_pnl = float(by_ccy.get("HKD") or 0)
    usd_pnl = float(by_ccy.get("USD") or 0)
    pairs_payload["usd_hkd_rate"] = usd_hkd
    pairs_payload["total_realized_pnl_hkd_base"] = hkd_pnl + usd_pnl * usd_hkd

    return {
        "ok": True,
        "count": len(rows),
        "transactions": rows,
        "pnl_by_product": pnl,
        "pair_pnl": pairs_payload,
        "usd_hkd_rate": usd_hkd,
        "monthly_summary": monthly_pair_summaries(),
    }
