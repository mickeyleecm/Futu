"""
Entry point: connect to OpenD and stream HK Level-1 market data.

Prerequisites:
  1. Install and start OpenD (FutuOpenD) on Windows.
  2. Log in with your Futu ID and password in OpenD.
  3. Copy config/config.example.yaml -> config/config.yaml
  4. Copy config/symbols.example.yaml -> config/symbols.yaml
  5. pip install -r requirements.txt
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Allow running from project root without installing as a package
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.futu_market_data import (
    FutuMarketDataClient,
    DEFAULT_CONFIG_PATH,
    DEFAULT_SYMBOLS_PATH,
    format_market_dataframe,
    market_display_columns,
)


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def _print_snapshot_columns(df) -> None:
    show = format_market_dataframe(df)
    cols = market_display_columns(show)
    print(show[cols].to_string(index=False))


def main() -> int:
    parser = argparse.ArgumentParser(description="Futu HK Level-1 market data")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--symbols", type=Path, default=DEFAULT_SYMBOLS_PATH)
    parser.add_argument(
        "--mode",
        choices=("snapshot", "stream", "poll"),
        default="stream",
        help="snapshot=one-shot; stream=push callbacks; poll=periodic get_stock_quote",
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=30,
        help="Run duration for stream/poll (0 = until Ctrl+C)",
    )
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument(
        "--codes",
        nargs="+",
        metavar="CODE",
        help="Stock codes to query (e.g. 00700 HK.00005). Overrides symbols.yaml",
    )
    args = parser.parse_args()

    codes = args.codes

    try:
        client = FutuMarketDataClient(config_path=args.config, symbols_path=args.symbols)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1

    _setup_logging(client.log_level)

    print(f"OpenD: {client.opend_host}:{client.opend_port}")
    if codes:
        print("Codes:", codes)
    else:
        print("Symbols:", client.symbols_by_category())
    acct = client.account
    if acct.get("user_id"):
        print(
            "Config account user_id:",
            acct.get("user_id"),
            "(login is done in OpenD, not in this script)",
        )

    with client:
        if args.mode == "snapshot":
            data, errors = client.get_snapshots_safe(codes)
            if errors:
                print("Skipped invalid or unavailable symbols:", file=sys.stderr)
                for code, msg in errors.items():
                    print(f"  {code}: {msg}", file=sys.stderr)
            if data.empty:
                print("No snapshot data returned.", file=sys.stderr)
                return 1
            _print_snapshot_columns(data)
            return 0

        subscribed, sub_errors = client.subscribe_safe(codes)
        if sub_errors:
            print("Skipped symbols (subscribe failed):", file=sys.stderr)
            for code, msg in sub_errors.items():
                print(f"  {code}: {msg}", file=sys.stderr)
        if not subscribed:
            print("No symbols subscribed.", file=sys.stderr)
            return 1

        print("Subscribed:", subscribed)
        print("Subscription quota:", client.query_subscription())

        if args.mode == "stream":

            def on_quote(df) -> None:
                print("\n--- Quote update ---")
                _print_snapshot_columns(df)

            client.set_quote_callback(on_quote)
            client.run(seconds=args.seconds)
        else:
            import time

            end = None if args.seconds <= 0 else time.time() + args.seconds
            while end is None or time.time() < end:
                ret, data = client.get_quotes(codes)
                if ret == 0:
                    print("\n--- Polled quote ---")
                    _print_snapshot_columns(data)
                else:
                    print("Poll error:", data, file=sys.stderr)
                time.sleep(args.poll_interval)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
