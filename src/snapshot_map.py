"""Map Futu get_market_snapshot rows into stock_market_data payloads."""

from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_NAMES_ZH_PATH = Path(__file__).resolve().parent.parent / "config" / "stock_names_zh.yaml"


@lru_cache(maxsize=1)
def load_zh_names() -> dict[str, str]:
    """OpenD Python snapshot only returns English names; map TC names locally."""
    if not _NAMES_ZH_PATH.exists():
        return {}
    data = yaml.safe_load(_NAMES_ZH_PATH.read_text(encoding="utf-8")) or {}
    return {str(k): str(v) for k, v in data.items()}


def zh_name_for(code: str) -> str | None:
    return load_zh_names().get(code)


def _has(row: Any, key: str) -> bool:
    if hasattr(row, "index"):
        return key in row.index
    return key in row


def _num(row: Any, *keys: str) -> float | None:
    for k in keys:
        if not _has(row, k):
            continue
        v = row[k]
        try:
            if v is None:
                continue
            if isinstance(v, str) and v.upper() in ("N/A", "NAN", ""):
                continue
            f = float(v)
            if f != f:  # NaN
                continue
            return f
        except (TypeError, ValueError):
            continue
    return None


def _int(row: Any, *keys: str) -> int | None:
    v = _num(row, *keys)
    return int(v) if v is not None else None


def _str(row: Any, *keys: str) -> str | None:
    for k in keys:
        if not _has(row, k):
            continue
        v = row[k]
        if v is None:
            continue
        s = str(v).strip()
        if not s or s.upper() in ("N/A", "NAN", "NONE"):
            continue
        return s
    return None


def _date(row: Any, *keys: str) -> date | None:
    s = _str(row, *keys)
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _bool01(row: Any, *keys: str) -> int | None:
    for k in keys:
        if not _has(row, k):
            continue
        v = row[k]
        if v is None:
            continue
        if isinstance(v, str) and v.upper() in ("N/A", "NAN", ""):
            continue
        return 1 if bool(v) else 0
    return None


def snapshot_row_to_stock_data(row: Any, *, is_favourite: int = 1) -> dict[str, Any]:
    code = _str(row, "code") or ""
    last = _num(row, "last_price")
    prev = _num(row, "prev_close_price", "prev_close")
    chg = (last - prev) if last is not None and prev is not None else None
    pct = (chg / prev * 100.0) if chg is not None and prev else None
    quote_time = _str(row, "update_time")
    if not quote_time:
        quote_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Prefer API Chinese fields if SDK ever exposes them; else local map.
    name_zh = (
        _str(row, "tc_name", "sc_name", "name_cn", "name_zh")
        or zh_name_for(code)
    )

    return {
        "code": code,
        "name": _str(row, "name"),
        "name_zh": name_zh,
        "market": code.split(".")[0] if "." in code else None,
        "last_price": last,
        "open_price": _num(row, "open_price"),
        "high_price": _num(row, "high_price"),
        "low_price": _num(row, "low_price"),
        "prev_close": prev,
        "change_val": chg,
        "change_pct": pct,
        "volume": _num(row, "volume"),
        "turnover": _num(row, "turnover"),
        "bid_price": _num(row, "bid_price"),
        "ask_price": _num(row, "ask_price"),
        "avg_price": _num(row, "avg_price"),
        "amplitude": _num(row, "amplitude"),
        "volume_ratio": _num(row, "volume_ratio"),
        "bid_ask_ratio": _num(row, "bid_ask_ratio"),
        "bid_vol": _num(row, "bid_vol"),
        "ask_vol": _num(row, "ask_vol"),
        "pe_ratio": _num(row, "pe_ratio"),
        "pe_ttm_ratio": _num(row, "pe_ttm_ratio"),
        "pb_ratio": _num(row, "pb_ratio"),
        "total_market_val": _num(row, "total_market_val"),
        "circular_market_val": _num(row, "circular_market_val"),
        "issued_shares": _num(row, "issued_shares"),
        "outstanding_shares": _num(row, "outstanding_shares"),
        "turnover_rate": _num(row, "turnover_rate"),
        "lot_size": _int(row, "lot_size"),
        "highest52weeks_price": _num(row, "highest52weeks_price"),
        "lowest52weeks_price": _num(row, "lowest52weeks_price"),
        "highest_history_price": _num(row, "highest_history_price"),
        "lowest_history_price": _num(row, "lowest_history_price"),
        "dividend_ttm": _num(row, "dividend_ttm"),
        "dividend_ratio_ttm": _num(row, "dividend_ratio_ttm"),
        "dividend_lfy": _num(row, "dividend_lfy"),
        "dividend_lfy_ratio": _num(row, "dividend_lfy_ratio"),
        "earning_per_share": _num(row, "earning_per_share"),
        "net_asset_per_share": _num(row, "net_asset_per_share"),
        "listing_date": _date(row, "listing_date"),
        "sec_status": _str(row, "sec_status"),
        "suspension": _bool01(row, "suspension"),
        "quote_time": quote_time,
        "is_favourite": is_favourite,
        "source": "opend",
    }
