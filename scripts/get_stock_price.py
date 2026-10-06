"""
Get live snapshot price for one or more HK stocks (OpenD must be running on host).

Examples (from project root):
  py scripts/get_stock_price.py 00700
  py scripts/get_stock_price.py 700 00005 HK.09888
  py scripts/get_stock_price.py 00700 --stream --seconds 30

From Docker (OpenD on Windows host):
  docker compose run --rm futu-client 00700
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.futu_market_data import (
    FutuMarketDataClient,
    format_market_dataframe,
    market_display_columns,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Get HK stock prices via OpenD")
    parser.add_argument("codes", nargs="+", help="Stock codes, e.g. 00700 or HK.00700")
    parser.add_argument("--stream", action="store_true", help="Subscribe and stream quotes")
    parser.add_argument("--seconds", type=float, default=30, help="Stream duration")
    args = parser.parse_args()

    with FutuMarketDataClient() as client:
        print(f"OpenD: {client.opend_host}:{client.opend_port}")

        if not args.stream:
            df, errors = client.get_stock_prices(args.codes)
            if errors:
                for code, msg in errors.items():
                    print(f"Warning {code}: {msg}", file=sys.stderr)
            if df.empty:
                print("No data. Is OpenD running and logged in?", file=sys.stderr)
                return 1
            show = format_market_dataframe(df)
            print(show[market_display_columns(show)].to_string(index=False))
            return 0

        ok, errors = client.subscribe_safe(args.codes)
        if errors:
            for code, msg in errors.items():
                print(f"Warning {code}: {msg}", file=sys.stderr)
        if not ok:
            print("Subscribe failed.", file=sys.stderr)
            return 1

        def on_quote(df) -> None:
            show = format_market_dataframe(df)
            print("\n--- update ---")
            print(show[market_display_columns(show)].to_string(index=False))

        client.set_quote_callback(on_quote)
        client.run(seconds=args.seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
