"""
Fetch HK option prices by underlying, expiry, call/put, and optional strike.

OpenD must be running and logged in.

Examples:
  # List expiry dates for Tencent options
  py scripts/get_option_prices.py HK.00700 --list-expiry

  # All calls for one expiry
  py scripts/get_option_prices.py HK.00700 --expiry 2026-05-29 --type CALL

  # One put at strike 500
  py scripts/get_option_prices.py HK.00700 --expiry 2026-05-29 --type PUT --strike 500

  # Tencent (700) calls, expiry 22 May, strikes 430–490
  py scripts/get_option_prices.py HK.00700 --expiry 2026-05-22 --type CALL --strike-min 430 --strike-max 490

  # HSI index options
  py scripts/get_option_prices.py HK.800000 --list-expiry
  py scripts/get_option_prices.py HK.800000 --expiry 2026-05-29 --type CALL --strike 24000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from futu import OptionType

from src.futu_market_data import (
    FutuMarketDataClient,
    format_market_dataframe,
    market_display_columns,
)


def _parse_option_type(value: str) -> OptionType:
    key = value.upper()
    if key == "CALL":
        return OptionType.CALL
    if key == "PUT":
        return OptionType.PUT
    if key == "ALL":
        return OptionType.ALL
    raise argparse.ArgumentTypeError("type must be CALL, PUT, or ALL")


def _print_prices(df) -> None:
    show = format_market_dataframe(df)
    print(show[market_display_columns(show)].to_string(index=False))


def main() -> int:
    parser = argparse.ArgumentParser(description="HK option prices via Futu OpenAPI")
    parser.add_argument("underlying", help="Underlying code, e.g. HK.00700 or HK.800000")
    parser.add_argument("--list-expiry", action="store_true", help="Show expiry dates only")
    parser.add_argument("--expiry", help="Expiry date yyyy-MM-dd")
    parser.add_argument("--type", type=_parse_option_type, default=OptionType.ALL)
    parser.add_argument("--strike", type=float, help="Filter to one strike price")
    parser.add_argument("--strike-min", type=float, help="Minimum strike (inclusive)")
    parser.add_argument("--strike-max", type=float, help="Maximum strike (inclusive)")
    args = parser.parse_args()

    with FutuMarketDataClient() as client:
        ret, dates = client.get_option_expiration_dates(args.underlying)
        if ret != 0:
            print("Error:", dates, file=sys.stderr)
            return 1

        if args.list_expiry or not args.expiry:
            print(f"Expiry dates for {args.underlying}:")
            print(dates.to_string(index=False))
            if not args.expiry:
                print("\nRe-run with --expiry yyyy-MM-dd --type CALL|PUT", file=sys.stderr)
            return 0

        df, errors = client.get_option_prices(
            args.underlying,
            args.expiry,
            option_type=args.type,
            strike=args.strike,
            strike_min=args.strike_min,
            strike_max=args.strike_max,
        )
        if errors:
            print("Warnings:", file=sys.stderr)
            for k, v in errors.items():
                print(f"  {k}: {v}", file=sys.stderr)
        if df.empty:
            print("No options matched.", file=sys.stderr)
            return 1

        _print_prices(df)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
