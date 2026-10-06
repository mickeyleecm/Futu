"""
List HK option contract codes for an underlying (run with OpenD logged in).

Examples:
  py scripts/list_hk_options.py HK.800000
  py scripts/list_hk_options.py HK.00700
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from futu import RET_OK
from src.futu_market_data import FutuMarketDataClient


def main() -> int:
    underlying = sys.argv[1] if len(sys.argv) > 1 else "HK.800000"
    with FutuMarketDataClient() as client:
        assert client._quote_ctx is not None
        ctx = client._quote_ctx
        ret, dates = ctx.get_option_expiration_date(code=underlying)
        if ret != RET_OK:
            print("Error:", dates, file=sys.stderr)
            return 1
        print(f"Expiration dates for {underlying}:")
        print(dates.to_string(index=False))
        if dates.empty:
            return 0
        expiry = str(dates["strike_time"].iloc[0])
        ret, chain = ctx.get_option_chain(code=underlying, start=expiry, end=expiry)
        if ret != RET_OK:
            print("Chain error:", chain, file=sys.stderr)
            return 1
        cols = [c for c in ("code", "name", "option_type", "strike_price") if c in chain.columns]
        print(f"\nSample contracts (nearest expiry {expiry}):")
        print(chain[cols].head(20).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
