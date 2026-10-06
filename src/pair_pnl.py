"""
FIFO open/close pairing for OPTION and WARRANT trades.

Uses Futu remarks when present:
  賣出開倉 / 買入開倉 → open a lot
  買入平倉 / 賣出平倉 → close opposite lots (never open a new lot)

Realized P&L (cash):
  short then buy-to-close:  (sell_amount - sell_fee) - (buy_amount + buy_fee)
  long then sell-to-close:  (sell_amount - sell_fee) - (buy_amount + buy_fee)
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import date
from decimal import Decimal
from typing import Any, Optional


def _d(v: Any) -> Decimal:
    if v is None:
        return Decimal("0")
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def _iso(d: Any) -> Optional[str]:
    if d is None:
        return None
    if isinstance(d, date):
        return d.isoformat()
    return str(d)[:10]


def _action(remark: str | None, side: str) -> str:
    """Return 'OPEN', 'CLOSE', or 'AUTO' (BUY/SELL FIFO)."""
    r = remark or ""
    if "平倉" in r or "平仓" in r:
        return "CLOSE"
    if "開倉" in r or "开仓" in r:
        return "OPEN"
    return "AUTO"


def _make_pair(
    *,
    code: str,
    name: Any,
    product_type: Any,
    currency: Any,
    matched: Decimal,
    open_side: str,
    open_date: Optional[str],
    open_price: Optional[Decimal],
    open_amount: Decimal,
    open_fee: Decimal,
    open_trade_id: Any,
    close_side: str,
    close_date: Optional[str],
    close_price: Decimal,
    close_amount: Decimal,
    close_fee: Decimal,
    close_trade_id: Any,
    prior_missing: bool = False,
) -> dict[str, Any]:
    if open_side == "SELL":
        sell_amount, sell_fee = open_amount, open_fee
        buy_amount, buy_fee = close_amount, close_fee
    else:
        buy_amount, buy_fee = open_amount, open_fee
        sell_amount, sell_fee = close_amount, close_fee

    pnl = (sell_amount - sell_fee) - (buy_amount + buy_fee)
    buy_date = open_date if open_side == "BUY" else close_date
    sell_date = open_date if open_side == "SELL" else close_date
    buy_price = open_price if open_side == "BUY" else close_price
    sell_price = open_price if open_side == "SELL" else close_price
    return {
        "code": code,
        "name": name,
        "product_type": product_type,
        "currency": currency,
        "quantity": matched,
        "direction": "SHORT" if open_side == "SELL" else "LONG",
        "open_side": open_side,
        "open_date": open_date,
        "open_price": open_price,
        "open_amount": open_amount,
        "open_fee": open_fee,
        "close_side": close_side,
        "close_date": close_date,
        "close_price": close_price,
        "close_amount": close_amount,
        "close_fee": close_fee,
        "buy_date": buy_date,
        "sell_date": sell_date,
        "buy_price": buy_price,
        "sell_price": sell_price,
        "fees": open_fee + close_fee,
        "realized_pnl": None if prior_missing else pnl,
        "close_cash_pnl": float(-close_amount - close_fee)
        if close_side == "BUY"
        else float(close_amount - close_fee),
        "prior_open_missing": prior_missing,
        "open_trade_id": open_trade_id,
        "close_trade_id": close_trade_id,
        "status": "CLOSED_PRIOR_UNKNOWN" if prior_missing else "CLOSED",
    }


def pair_option_warrant_trades(
    rows: list[dict[str, Any]],
    *,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> dict[str, Any]:
    """
    Match open/close lots per code for OPTION and WARRANT.

    Prefer full multi-month history in `rows` so 平倉 can match earlier 開倉.
    Pairs whose close date falls outside [date_from, date_to] are filtered out
    when those bounds are set.
    """
    by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        pt = (r.get("product_type") or "").upper()
        if pt not in ("OPTION", "WARRANT"):
            continue
        side = (r.get("side") or "").upper()
        if side not in ("BUY", "SELL"):
            continue
        qty = _d(r.get("quantity"))
        if qty <= 0:
            continue
        by_code[str(r.get("code") or "")].append(r)

    pairs: list[dict[str, Any]] = []
    open_lots: list[dict[str, Any]] = []

    for code, trades in sorted(by_code.items()):
        trades = sorted(
            trades,
            key=lambda t: (
                _iso(t.get("trade_date")) or "",
                int(t.get("id") or 0),
            ),
        )
        opens: deque[dict[str, Any]] = deque()
        name = trades[0].get("name")
        product_type = trades[0].get("product_type")
        currency = trades[0].get("currency") or "HKD"

        for t in trades:
            side = t["side"].upper()
            qty = _d(t["quantity"])
            amount = _d(t.get("amount"))
            fee = _d(t.get("total_fee"))
            amt_u = amount / qty
            fee_u = fee / qty
            remaining = qty
            name = t.get("name") or name
            currency = t.get("currency") or currency
            action = _action(t.get("remark"), side)
            close_date = _iso(t.get("trade_date"))
            close_price = _d(t.get("price"))

            if action == "OPEN":
                opens.append(
                    {
                        "id": t.get("id"),
                        "side": side,
                        "qty": remaining,
                        "price": close_price,
                        "amt_u": amt_u,
                        "fee_u": fee_u,
                        "date": close_date,
                        "name": name,
                        "product_type": product_type,
                        "currency": currency,
                    }
                )
                continue

            # CLOSE or AUTO: try to match opposite opens
            while remaining > 0 and opens and opens[0]["side"] != side:
                op = opens[0]
                matched = min(remaining, op["qty"])
                pairs.append(
                    _make_pair(
                        code=code,
                        name=name,
                        product_type=product_type,
                        currency=currency,
                        matched=matched,
                        open_side=op["side"],
                        open_date=op["date"],
                        open_price=op["price"],
                        open_amount=op["amt_u"] * matched,
                        open_fee=op["fee_u"] * matched,
                        open_trade_id=op["id"],
                        close_side=side,
                        close_date=close_date,
                        close_price=close_price,
                        close_amount=amt_u * matched,
                        close_fee=fee_u * matched,
                        close_trade_id=t.get("id"),
                    )
                )
                op["qty"] -= matched
                remaining -= matched
                if op["qty"] <= 0:
                    opens.popleft()

            if remaining <= 0:
                continue

            if action == "CLOSE":
                # 平倉 with no prior 開倉 in DB — still count as a closed pair
                inferred_open = "SELL" if side == "BUY" else "BUY"
                pairs.append(
                    _make_pair(
                        code=code,
                        name=name,
                        product_type=product_type,
                        currency=currency,
                        matched=remaining,
                        open_side=inferred_open,
                        open_date=None,
                        open_price=None,
                        open_amount=Decimal("0"),
                        open_fee=Decimal("0"),
                        open_trade_id=None,
                        close_side=side,
                        close_date=close_date,
                        close_price=close_price,
                        close_amount=amt_u * remaining,
                        close_fee=fee_u * remaining,
                        close_trade_id=t.get("id"),
                        prior_missing=True,
                    )
                )
            else:
                # AUTO leftover becomes a new open lot
                opens.append(
                    {
                        "id": t.get("id"),
                        "side": side,
                        "qty": remaining,
                        "price": close_price,
                        "amt_u": amt_u,
                        "fee_u": fee_u,
                        "date": close_date,
                        "name": name,
                        "product_type": product_type,
                        "currency": currency,
                    }
                )

        for op in opens:
            open_lots.append(
                {
                    "code": code,
                    "name": op["name"],
                    "product_type": op["product_type"],
                    "currency": op["currency"],
                    "side": op["side"],
                    "direction": "SHORT" if op["side"] == "SELL" else "LONG",
                    "quantity": op["qty"],
                    "open_date": op["date"],
                    "open_price": op["price"],
                    "open_amount": op["amt_u"] * op["qty"],
                    "open_fee": op["fee_u"] * op["qty"],
                    "realized_pnl": None,
                    "status": "OPEN",
                }
            )

    def _in_range(close_date: Optional[str]) -> bool:
        if not close_date:
            return True
        d = date.fromisoformat(close_date[:10])
        if date_from and d < date_from:
            return False
        if date_to and d > date_to:
            return False
        return True

    if date_from or date_to:
        pairs = [p for p in pairs if _in_range(p.get("close_date"))]

    pairs.sort(key=lambda p: (p.get("close_date") or "", p.get("code") or ""), reverse=True)
    open_lots.sort(key=lambda p: (p.get("open_date") or "", p.get("code") or ""), reverse=True)

    known = [p for p in pairs if not p.get("prior_open_missing")]
    unknown = [p for p in pairs if p.get("prior_open_missing")]
    wins = [p for p in known if _d(p["realized_pnl"]) > 0]
    losses = [p for p in known if _d(p["realized_pnl"]) < 0]
    flats = [p for p in known if _d(p["realized_pnl"]) == 0]
    decided = len(wins) + len(losses)
    win_rate = (float(len(wins)) / decided * 100.0) if decided else None

    by_type: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    by_type_ccy: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: defaultdict(lambda: Decimal("0"))
    )
    by_ccy: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for p in known:
        pt = str(p["product_type"])
        ccy = str(p.get("currency") or "HKD").upper()
        pnl = _d(p["realized_pnl"])
        by_type[pt] += pnl
        by_type_ccy[pt][ccy] += pnl
        by_ccy[ccy] += pnl

    return {
        "pairs": [_serialize(p) for p in pairs],
        "open_lots": [_serialize(p) for p in open_lots],
        "pair_count": len(pairs),
        "closed_with_open_count": len(known),
        "closed_prior_unknown_count": len(unknown),
        "open_count": len(open_lots),
        "win_count": len(wins),
        "loss_count": len(losses),
        "flat_count": len(flats),
        "win_rate_pct": win_rate,
        # Note: total mixes currencies — prefer realized_pnl_by_currency
        "total_realized_pnl": float(sum(by_ccy.values(), Decimal("0"))),
        "realized_pnl_by_currency": {k: float(v) for k, v in sorted(by_ccy.items())},
        "realized_pnl_by_product": {k: float(v) for k, v in sorted(by_type.items())},
        "realized_pnl_by_product_currency": {
            pt: {ccy: float(v) for ccy, v in sorted(ccys.items())}
            for pt, ccys in sorted(by_type_ccy.items())
        },
    }


def _serialize(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in row.items():
        if isinstance(v, Decimal):
            out[k] = float(v)
        elif isinstance(v, date):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out
