"""Build option chain board data (calls | strike | puts) for the web UI."""

from __future__ import annotations

import math
from typing import Any, Optional

import pandas as pd
from futu import OptionType, RET_OK

from .futu_market_data import (
    FutuMarketDataClient,
    add_price_change_columns,
    enrich_option_greeks,
)


def _num(value: Any) -> Optional[float]:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    try:
        v = float(value)
        if math.isnan(v):
            return None
        return v
    except (TypeError, ValueError):
        return None


def _leg_row(df: pd.DataFrame) -> Optional[dict[str, Any]]:
    if df.empty:
        return None
    r = df.iloc[0]
    bid = _num(r.get("bid_price"))
    ask = _num(r.get("ask_price"))
    mid = None
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        mid = round((bid + ask) / 2, 3)
    oi = _num(r.get("open_interest"))
    if oi is None:
        oi = _num(r.get("option_open_interest"))
    return {
        "code": str(r.get("code", "")),
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "last": _num(r.get("last_price")),
        "change_pct": _num(r.get("change_pct")),
        "volume": _num(r.get("volume")),
        "open_interest": oi,
        "iv": _num(r.get("iv")),
        "delta": _num(r.get("delta")),
        "gamma": _num(r.get("gamma")),
        "vega": _num(r.get("vega")),
        "theta": _num(r.get("theta")),
    }


def build_option_chain_board(
    client: FutuMarketDataClient,
    underlying: str,
    expiry: str,
) -> dict[str, Any]:
    """
    Full option chain with live prices for one expiry (CALL + PUT per strike).
    """
    ret, chain = client.get_option_chain(
        underlying, expiry, option_type=OptionType.ALL
    )
    if ret != RET_OK:
        return {"ok": False, "error": str(chain)}

    assert isinstance(chain, pd.DataFrame)
    if chain.empty:
        return {"ok": False, "error": "No contracts for this expiry"}

    prices, errors = client.get_snapshots_safe(chain["code"].tolist())
    u_ret, u_data = client.get_snapshots([underlying])
    underlying_price = None
    underlying_name = underlying
    if u_ret == RET_OK and not u_data.empty:
        underlying_price = _num(u_data.iloc[0].get("last_price"))
        underlying_name = str(u_data.iloc[0].get("name", underlying))

    if not prices.empty:
        merged = chain.merge(prices, on="code", how="left", suffixes=("", "_q"))
        merged = enrich_option_greeks(add_price_change_columns(merged))
    else:
        merged = chain

    if "option_type" in merged.columns:
        merged["_side"] = merged["option_type"].astype(str).str.upper()
    else:
        merged["_side"] = ""

    strikes = sorted(merged["strike_price"].dropna().unique())
    rows: list[dict[str, Any]] = []
    for strike in strikes:
        sub = merged[merged["strike_price"] == strike]
        rows.append(
            {
                "strike": _num(strike),
                "call": _leg_row(sub[sub["_side"] == "CALL"]),
                "put": _leg_row(sub[sub["_side"] == "PUT"]),
            }
        )

    return {
        "ok": True,
        "underlying": underlying,
        "underlying_name": underlying_name,
        "underlying_price": underlying_price,
        "expiry": expiry,
        "updated_at": prices.iloc[0].get("update_time") if not prices.empty else None,
        "errors": errors,
        "rows": rows,
    }


def list_expirations(client: FutuMarketDataClient, underlying: str) -> dict[str, Any]:
    ret, dates = client.get_option_expiration_dates(underlying)
    if ret != RET_OK:
        return {"ok": False, "error": str(dates)}
    items = []
    if not dates.empty:
        for _, row in dates.iterrows():
            items.append(
                {
                    "strike_time": str(row.get("strike_time", "")),
                    "days": row.get("option_expiry_date_distance"),
                    "cycle": str(row.get("expiration_cycle", "")),
                }
            )
    return {"ok": True, "underlying": underlying, "expirations": items}
