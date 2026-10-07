"""Fetch ATM ± N strike option quotes into option_market_data."""

from __future__ import annotations

import logging
import math
import re
import time
from datetime import datetime
from typing import Any, Optional

import pandas as pd
from futu import OptionType, RET_OK

from .db import upsert_option_market_data
from .futu_market_data import (
    FutuMarketDataClient,
    add_price_change_columns,
    enrich_option_greeks,
)

logger = logging.getLogger(__name__)

_EQUITY_RE = re.compile(r"^[A-Z]{2}\.\d+$")

# OpenD: option chain ≤10 / 30s; snapshot ≤60 / 30s — pace underlyings.
_CHAIN_PAUSE_SEC = 3.2


def is_option_underlying_code(code: str) -> bool:
    """HK/US numeric equity or index codes that may have listed options."""
    return bool(_EQUITY_RE.match(str(code).strip().upper()))


def _f(*vals: Any) -> float | None:
    for v in vals:
        if v is None:
            continue
        try:
            if isinstance(v, float) and math.isnan(v):
                continue
            if isinstance(v, str) and v.upper() in ("N/A", "NAN", ""):
                continue
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _i(*vals: Any) -> int | None:
    f = _f(*vals)
    return int(f) if f is not None else None


def _s(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _parse_dt(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    s = str(v).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(s[:26], fmt)
        except ValueError:
            continue
    return None


def pick_expiry(
    expirations: pd.DataFrame,
    *,
    prefer_month: bool = True,
) -> Optional[dict[str, Any]]:
    """Nearest MONTH cycle if available, else nearest expiry."""
    if expirations is None or expirations.empty:
        return None
    rows: list[dict[str, Any]] = []
    for _, r in expirations.iterrows():
        st = str(r.get("strike_time", ""))[:10]
        try:
            days = int(r.get("option_expiry_date_distance") or 0)
        except (TypeError, ValueError):
            days = 0
        cycle = str(r.get("expiration_cycle", "") or "").upper()
        rows.append({"expiry": st, "days": days, "cycle": cycle})
    if not rows:
        return None
    if prefer_month:
        months = [x for x in rows if "MONTH" in x["cycle"]]
        if months:
            months.sort(key=lambda x: x["days"])
            return months[0]
    rows.sort(key=lambda x: x["days"])
    return rows[0]


def select_atm_strikes(
    strikes: list[float],
    underlying_price: float,
    *,
    spread: int = 4,
) -> tuple[list[float], float, dict[float, int]]:
    """
    Strikes within ±spread steps of ATM, ATM strike, and offset map.
    offset: negative = below ATM, 0 = ATM, positive = above.
    """
    if not strikes:
        return [], float("nan"), {}
    sorted_strikes = sorted(float(s) for s in strikes)
    atm = min(sorted_strikes, key=lambda s: abs(s - underlying_price))
    atm_i = sorted_strikes.index(atm)
    lo = max(0, atm_i - spread)
    hi = min(len(sorted_strikes), atm_i + spread + 1)
    selected = sorted_strikes[lo:hi]
    offsets = {s: sorted_strikes.index(s) - atm_i for s in selected}
    return selected, atm, offsets


def _row_to_option_payload(
    row: Any,
    *,
    underlying: str,
    underlying_price: float | None,
    expiry: str,
    cycle: str | None,
    strike_offset: int | None,
) -> dict[str, Any] | None:
    code = str(row.get("code") or "").strip()
    if not code:
        return None
    try:
        strike_f = float(row.get("strike_price"))
    except (TypeError, ValueError):
        return None

    opt_type = str(row.get("option_type") or "").upper()
    if "CALL" in opt_type:
        opt_type = "CALL"
    elif "PUT" in opt_type:
        opt_type = "PUT"
    else:
        return None

    bid = _f(row.get("bid_price"))
    ask = _f(row.get("ask_price"))
    mid = None
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        mid = round((bid + ask) / 2, 6)

    return {
        "code": code,
        "name": _s(row.get("name")),
        "underlying": underlying,
        "underlying_price": underlying_price,
        "option_type": opt_type,
        "strike_price": strike_f,
        "expiry": expiry[:10],
        "expiration_cycle": cycle,
        "strike_offset": strike_offset,
        "last_price": _f(row.get("last_price")),
        "bid_price": bid,
        "ask_price": ask,
        "mid_price": mid,
        "prev_close": _f(row.get("prev_close_price"), row.get("prev_close")),
        "change_val": _f(row.get("change_val")),
        "change_pct": _f(row.get("change_pct")),
        "volume": _f(row.get("volume")),
        "turnover": _f(row.get("turnover")),
        "open_interest": _f(row.get("open_interest"), row.get("option_open_interest")),
        "iv": _f(row.get("iv"), row.get("option_implied_volatility")),
        "delta": _f(row.get("delta"), row.get("option_delta")),
        "gamma": _f(row.get("gamma"), row.get("option_gamma")),
        "vega": _f(row.get("vega"), row.get("option_vega")),
        "theta": _f(row.get("theta"), row.get("option_theta")),
        "rho": _f(row.get("rho"), row.get("option_rho")),
        "premium": _f(row.get("premium"), row.get("option_premium")),
        "lot_size": _i(row.get("lot_size")),
        "contract_size": _f(row.get("option_contract_size")),
        "expiry_days": _i(
            row.get("expiry_days"), row.get("option_expiry_date_distance")
        ),
        "suspension": 1 if bool(row.get("suspension")) else 0,
        "quote_time": _parse_dt(row.get("update_time")),
        "source": "opend",
    }


def fetch_atm_option_rows(
    client: FutuMarketDataClient,
    underlying: str,
    *,
    spread: int = 4,
    prefer_month: bool = True,
    expiry: str | None = None,
) -> dict[str, Any]:
    """
    Pull CALL+PUT for ATM ± spread strikes for one underlying.

    Returns {ok, underlying, expiry, underlying_price, rows: [...], error?}
    """
    underlying = str(underlying).strip().upper()
    cycle: str | None = None

    if expiry is None:
        ret, dates = client.get_option_expiration_dates(underlying)
        if ret != RET_OK:
            return {
                "ok": False,
                "underlying": underlying,
                "error": str(dates),
                "rows": [],
            }
        picked = pick_expiry(dates, prefer_month=prefer_month)
        if not picked:
            return {
                "ok": False,
                "underlying": underlying,
                "error": "No option expiries",
                "rows": [],
            }
        expiry = picked["expiry"]
        cycle = picked.get("cycle")

    assert expiry is not None
    ret, chain = client.get_option_chain(
        underlying, expiry, option_type=OptionType.ALL
    )
    if ret != RET_OK:
        return {
            "ok": False,
            "underlying": underlying,
            "expiry": expiry,
            "error": str(chain),
            "rows": [],
        }
    assert isinstance(chain, pd.DataFrame)
    if chain.empty:
        return {
            "ok": False,
            "underlying": underlying,
            "expiry": expiry,
            "error": "Empty option chain",
            "rows": [],
        }

    u_ret, u_data = client.get_snapshots([underlying])
    underlying_price = None
    if u_ret == RET_OK and not u_data.empty:
        underlying_price = _f(u_data.iloc[0].get("last_price"))
    if underlying_price is None:
        # Fallback to last stock_market_data quote (OpenD may rate-limit)
        try:
            from .db import list_stock_market_data

            for r in list_stock_market_data(limit=500):
                if str(r.get("code") or "").upper() == underlying and r.get("last_price"):
                    underlying_price = _f(r.get("last_price"))
                    break
        except Exception:  # noqa: BLE001
            pass
    if underlying_price is None:
        return {
            "ok": False,
            "underlying": underlying,
            "expiry": expiry,
            "error": "No underlying price",
            "rows": [],
        }

    strikes = [float(s) for s in chain["strike_price"].dropna().unique()]
    selected, atm, offsets = select_atm_strikes(
        strikes, underlying_price, spread=spread
    )
    if not selected:
        return {
            "ok": False,
            "underlying": underlying,
            "expiry": expiry,
            "error": "No strikes selected",
            "rows": [],
        }

    sub = chain[chain["strike_price"].isin(selected)].copy()
    codes = sub["code"].astype(str).tolist()
    # One batch snapshot (≤18 for ATM±4) — avoid per-code spam (60/30s limit)
    snap_errors: dict[str, str] = {}
    ret_p, prices = client.get_snapshots(codes)
    if ret_p != RET_OK:
        prices, snap_errors = client.get_snapshots_safe(codes)
    if prices is None or getattr(prices, "empty", True):
        return {
            "ok": False,
            "underlying": underlying,
            "expiry": expiry,
            "underlying_price": underlying_price,
            "error": f"No option snapshots ({snap_errors or prices})",
            "rows": [],
        }

    merged = sub.merge(prices, on="code", how="left", suffixes=("", "_q"))
    merged = enrich_option_greeks(add_price_change_columns(merged))

    rows: list[dict[str, Any]] = []
    for _, row in merged.iterrows():
        try:
            strike_f = float(row["strike_price"])
        except (TypeError, ValueError):
            continue
        payload = _row_to_option_payload(
            row,
            underlying=underlying,
            underlying_price=underlying_price,
            expiry=expiry,
            cycle=cycle,
            strike_offset=offsets.get(strike_f),
        )
        if payload:
            rows.append(payload)

    return {
        "ok": True,
        "underlying": underlying,
        "expiry": expiry,
        "expiration_cycle": cycle,
        "underlying_price": underlying_price,
        "atm_strike": atm,
        "strike_count": len(selected),
        "rows": rows,
        "errors": snap_errors,
    }


def sync_favourite_options(
    client: FutuMarketDataClient,
    underlyings: list[str],
    *,
    spread: int = 4,
    prefer_month: bool = True,
) -> dict[str, Any]:
    """Fetch ATM±spread options for each underlying and upsert to DB."""
    ok_u = 0
    fail_u = 0
    upserted = 0
    errors: list[str] = []

    for i, code in enumerate(underlyings):
        if i > 0:
            time.sleep(_CHAIN_PAUSE_SEC)
        result = fetch_atm_option_rows(
            client,
            code,
            spread=spread,
            prefer_month=prefer_month,
        )
        if not result.get("ok"):
            fail_u += 1
            errors.append(f"{code}: {result.get('error')}")
            logger.warning("Options skip %s: %s", code, result.get("error"))
            continue
        for row in result["rows"]:
            upsert_option_market_data(row)
            upserted += 1
        ok_u += 1
        logger.info(
            "Options %s expiry=%s atm=%s contracts=%d",
            code,
            result.get("expiry"),
            result.get("atm_strike"),
            len(result["rows"]),
        )

    return {
        "ok_underlyings": ok_u,
        "fail_underlyings": fail_u,
        "upserted": upserted,
        "errors": errors[:20],
    }
