"""
Reusable Futu OpenAPI client for HK Level-1 market data (stocks, options, indices).

Requires OpenD to be installed, running, and logged in on the same machine.
See: https://openapi.futunn.com/futu-api-doc/en/quick/opend-base.html
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Iterable, Optional

import pandas as pd
import yaml
from futu import (
    AuType,
    IndexOptionType,
    KLType,
    OpenQuoteContext,
    OptionType,
    RET_OK,
    StockQuoteHandlerBase,
    SubType,
)

# Equity / index numeric codes only (skip options, futures like HSImain).
_MA_CODE_RE = re.compile(r"^[A-Z]{2}\.\d+$")

logger = logging.getLogger(__name__)

QuoteCallback = Callable[[object], None]

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "config.yaml"
DEFAULT_SYMBOLS_PATH = Path(__file__).resolve().parent.parent / "config" / "symbols.yaml"


def _load_yaml(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(
            f"Config not found: {path}\n"
            f"Copy the matching .example.yaml file and edit it."
        )
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# Snapshot uses option_* prefix; live quote uses short names — unified below.
_OPTION_FIELD_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("iv", ("option_implied_volatility", "implied_volatility")),
    ("premium", ("option_premium", "premium")),
    ("delta", ("option_delta", "delta")),
    ("gamma", ("option_gamma", "gamma")),
    ("vega", ("option_vega", "vega")),
    ("theta", ("option_theta", "theta")),
    ("rho", ("option_rho", "rho")),
    ("open_interest", ("option_open_interest", "open_interest")),
    ("expiry_days", ("option_expiry_date_distance", "expiry_date_distance")),
)

OPTION_GREEK_DISPLAY_COLUMNS: tuple[str, ...] = (
    "iv",
    "premium",
    "delta",
    "gamma",
    "vega",
    "theta",
    "rho",
    "open_interest",
)


def enrich_option_greeks(df: pd.DataFrame) -> pd.DataFrame:
    """Map Futu option snapshot/quote columns to short names (iv, delta, ...)."""
    if df.empty:
        return df
    out = df.copy()
    for short, sources in _OPTION_FIELD_ALIASES:
        if short in out.columns:
            continue
        for src in sources:
            if src in out.columns:
                out[short] = out[src]
                break
    return out


def add_price_change_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add change_val and change_pct vs previous close.

    Futu returns percentages as numbers (e.g. 1.5 means 1.5%), not decimals.
    """
    if df.empty:
        return df
    out = df.copy()
    last = pd.to_numeric(out.get("last_price"), errors="coerce")
    prev = pd.to_numeric(out.get("prev_close_price"), errors="coerce")

    if "change_val" not in out.columns:
        out["change_val"] = last - prev
    if "change_pct" not in out.columns:
        out["change_pct"] = ((last - prev) / prev * 100).where(prev > 0)

    return out


def _normalize_codes(codes: Iterable[str]) -> list[str]:
    result: list[str] = []
    for raw in codes:
        code = str(raw).strip()
        if not code:
            continue
        if "." not in code:
            code = f"HK.{code}"
        market, symbol = code.split(".", 1)
        if market.upper() == "HK" and symbol.isdigit() and len(symbol) < 5:
            symbol = symbol.zfill(5)
        result.append(f"{market.upper()}.{symbol}")
    return result


class _QuoteHandler(StockQuoteHandlerBase):
    """Forwards Futu quote pushes to a user callback."""

    def __init__(self, on_quote: Optional[QuoteCallback] = None) -> None:
        super().__init__()
        self._on_quote = on_quote

    def on_recv_rsp(self, rsp_pb):
        ret_code, data = super().on_recv_rsp(rsp_pb)
        if ret_code != RET_OK:
            logger.error("Quote push error: %s", data)
            return ret_code, data
        if self._on_quote is not None:
            self._on_quote(data)
        return ret_code, data


class FutuMarketDataClient:
    """
    Connect to OpenD and fetch HK Level-1 quotes for stocks, options, and indices.

    Typical usage::

        with FutuMarketDataClient() as client:
            client.subscribe()
            print(client.get_snapshots())
            client.set_quote_callback(lambda df: print(df))
            client.run(seconds=60)
    """

    def __init__(
        self,
        config_path: Path | str | None = None,
        symbols_path: Path | str | None = None,
    ) -> None:
        self._config_path = Path(config_path or DEFAULT_CONFIG_PATH)
        self._symbols_path = Path(symbols_path or DEFAULT_SYMBOLS_PATH)
        self._config = _load_yaml(self._config_path)
        self._symbols_cfg = _load_yaml(self._symbols_path)

        opend = self._config.get("opend", {})
        self._host: str = os.environ.get(
            "FUTU_OPEND_HOST", opend.get("host", "127.0.0.1")
        )
        self._port: int = int(
            os.environ.get("FUTU_OPEND_PORT", opend.get("port", 11111))
        )

        md = self._config.get("market_data", {})
        self._subscribe_push: bool = bool(md.get("subscribe_push", True))
        self._is_first_push: bool = bool(md.get("is_first_push", True))

        self._quote_ctx: Optional[OpenQuoteContext] = None
        self._handler: Optional[_QuoteHandler] = None
        self._subscribed = False

    @property
    def account(self) -> dict:
        """Account section from config (user_id / password for OpenD login reference)."""
        return self._config.get("account", {})

    @property
    def user_id(self) -> str:
        return str(self.account.get("user_id", ""))

    @property
    def opend_host(self) -> str:
        return self._host

    @property
    def opend_port(self) -> int:
        return self._port

    @property
    def log_level(self) -> str:
        return str(self._config.get("logging", {}).get("level", "INFO"))

    @property
    def is_connected(self) -> bool:
        return self._quote_ctx is not None

    def all_symbols(self) -> list[str]:
        """Merged list of HK stocks, indices, and options from symbols config."""
        codes: list[str] = []
        for key in ("hk_stocks", "indices", "hk_options"):
            codes.extend(self._symbols_cfg.get(key, []) or [])
        return _normalize_codes(codes)

    def symbols_by_category(self) -> dict[str, list[str]]:
        return {
            "hk_stocks": _normalize_codes(self._symbols_cfg.get("hk_stocks", []) or []),
            "indices": _normalize_codes(self._symbols_cfg.get("indices", []) or []),
            "hk_options": _normalize_codes(self._symbols_cfg.get("hk_options", []) or []),
        }

    def connect(self) -> None:
        if self._quote_ctx is not None:
            return
        self._quote_ctx = OpenQuoteContext(host=self._host, port=self._port)
        logger.info("Connected to OpenD at %s:%s", self._host, self._port)

    def disconnect(self) -> None:
        if self._quote_ctx is None:
            return
        try:
            if self._subscribed:
                self._quote_ctx.unsubscribe_all()
        except Exception as exc:  # noqa: BLE001
            logger.warning("unsubscribe_all failed: %s", exc)
        self._quote_ctx.close()
        self._quote_ctx = None
        self._subscribed = False
        logger.info("Disconnected from OpenD")

    def set_quote_callback(self, callback: Optional[QuoteCallback]) -> None:
        """Register a callback for real-time QUOTE pushes (DataFrame)."""
        self._ensure_connected()
        self._handler = _QuoteHandler(on_quote=callback)
        assert self._quote_ctx is not None
        self._quote_ctx.set_handler(self._handler)

    def subscribe(
        self,
        codes: Iterable[str] | None = None,
        *,
        subtype: SubType = SubType.QUOTE,
    ) -> tuple[int, object]:
        """
        Subscribe to Level-1 real-time quotes (SubType.QUOTE).

        HK stocks, options, and indices require LV1 permission on your account.
        """
        self._ensure_connected()
        code_list = _normalize_codes(codes) if codes is not None else self.all_symbols()
        if not code_list:
            raise ValueError("No symbols to subscribe. Check config/symbols.yaml.")

        assert self._quote_ctx is not None
        if self._handler is None:
            self.set_quote_callback(None)

        ret, err = self._quote_ctx.subscribe(
            code_list,
            [subtype],
            is_first_push=self._is_first_push,
            subscribe_push=self._subscribe_push,
        )
        if ret == RET_OK:
            self._subscribed = True
            logger.info("Subscribed to QUOTE for %d symbols", len(code_list))
        else:
            logger.error("Subscribe failed: %s", err)
        return ret, err

    def subscribe_safe(
        self,
        codes: Iterable[str] | None = None,
        *,
        subtype: SubType = SubType.QUOTE,
    ) -> tuple[list[str], dict[str, str]]:
        """
        Subscribe one symbol at a time; skip codes that fail.

        Returns (subscribed_codes, {code: error_message}).
        """
        self._ensure_connected()
        assert self._quote_ctx is not None
        if self._handler is None:
            self.set_quote_callback(None)

        code_list = _normalize_codes(codes) if codes is not None else self.all_symbols()
        ok_codes: list[str] = []
        errors: dict[str, str] = {}
        for code in code_list:
            ret, err = self._quote_ctx.subscribe(
                [code],
                [subtype],
                is_first_push=self._is_first_push,
                subscribe_push=self._subscribe_push,
            )
            if ret == RET_OK:
                ok_codes.append(code)
            else:
                errors[code] = str(err)
                logger.warning("Subscribe failed for %s: %s", code, err)

        if ok_codes:
            self._subscribed = True
            logger.info("Subscribed to QUOTE for %d/%d symbols", len(ok_codes), len(code_list))
        return ok_codes, errors

    def unsubscribe(self, codes: Iterable[str] | None = None) -> tuple[int, object]:
        self._ensure_connected()
        assert self._quote_ctx is not None
        code_list = _normalize_codes(codes) if codes is not None else self.all_symbols()
        ret, err = self._quote_ctx.unsubscribe(code_list, [SubType.QUOTE])
        if ret == RET_OK:
            logger.info("Unsubscribed QUOTE for %d symbols", len(code_list))
        return ret, err

    def get_snapshots(self, codes: Iterable[str] | None = None):
        """
        One-shot market snapshot (no subscription required).

        Returns (ret_code, DataFrame | error_message).
        If any code in the list is invalid, the whole batch fails — use
        get_snapshots_safe() instead.
        """
        self._ensure_connected()
        code_list = _normalize_codes(codes) if codes is not None else self.all_symbols()
        assert self._quote_ctx is not None
        return self._quote_ctx.get_market_snapshot(code_list)

    def get_snapshots_safe(
        self, codes: Iterable[str] | None = None
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        """
        Fetch snapshots one symbol at a time so one bad code does not fail all.

        Returns (combined DataFrame, {code: error_message} for failures).
        """
        self._ensure_connected()
        assert self._quote_ctx is not None
        code_list = _normalize_codes(codes) if codes is not None else self.all_symbols()

        frames: list[pd.DataFrame] = []
        errors: dict[str, str] = {}
        for code in code_list:
            ret, data = self._quote_ctx.get_market_snapshot([code])
            if ret == RET_OK:
                frames.append(data)
            else:
                errors[code] = str(data)
                logger.warning("Snapshot failed for %s: %s", code, data)

        if frames:
            combined = pd.concat(frames, ignore_index=True)
        else:
            combined = pd.DataFrame()
        return combined, errors

    def get_stock_prices(
        self, codes: Iterable[str]
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        """Snapshot prices for specific stock/index codes (no subscription needed)."""
        return self.get_snapshots_safe(codes)

    def get_daily_moving_averages(
        self,
        code: str,
        windows: tuple[int, ...] = (50, 60),
    ) -> dict[str, float | None]:
        """
        Simple moving averages of daily close from OpenD history K-line (QFQ).

        Returns e.g. {"ma50": 454.2, "ma60": 451.3}. Missing windows are None.
        """
        self._ensure_connected()
        assert self._quote_ctx is not None
        code = str(code).strip().upper()
        out: dict[str, float | None] = {f"ma{w}": None for w in windows}
        if not _MA_CODE_RE.match(code):
            return out

        need = max(windows)
        # ~1.6 calendar days per trading day + buffer
        start = (date.today() - timedelta(days=int(need * 1.8) + 30)).isoformat()
        end = date.today().isoformat()
        ret, data, _page = self._quote_ctx.request_history_kline(
            code,
            start=start,
            end=end,
            ktype=KLType.K_DAY,
            autype=AuType.QFQ,
            max_count=need + 10,
        )
        if ret != RET_OK:
            logger.warning("History kline failed for %s: %s", code, data)
            return out
        if data is None or getattr(data, "empty", True):
            return out

        closes = pd.to_numeric(data["close"], errors="coerce").dropna().tolist()
        for w in windows:
            if len(closes) >= w:
                out[f"ma{w}"] = float(sum(closes[-w:]) / w)
        return out

    def get_quotes(self, codes: Iterable[str] | None = None):
        """
        Real-time quote for subscribed symbols (SubType.QUOTE).

        Call subscribe() first.
        """
        self._ensure_connected()
        code_list = _normalize_codes(codes) if codes is not None else self.all_symbols()
        assert self._quote_ctx is not None
        return self._quote_ctx.get_stock_quote(code_list)

    def get_option_expiration_dates(
        self,
        underlying: str,
        *,
        index_option_type: IndexOptionType = IndexOptionType.NORMAL,
    ) -> tuple[int, pd.DataFrame | str]:
        """
        List available expiry dates for an underlying (stock or HSI index).

        Returns (ret_code, DataFrame with strike_time, ...) or error string.
        """
        self._ensure_connected()
        assert self._quote_ctx is not None
        code = _normalize_codes([underlying])[0]
        return self._quote_ctx.get_option_expiration_date(
            code=code, index_option_type=index_option_type
        )

    def get_option_chain(
        self,
        underlying: str,
        expiry: str,
        *,
        option_type: OptionType = OptionType.ALL,
        index_option_type: IndexOptionType = IndexOptionType.NORMAL,
    ) -> tuple[int, pd.DataFrame | str]:
        """
        Option chain for one expiry: CALL / PUT contracts and strike prices.

        expiry format: yyyy-MM-dd (from get_option_expiration_dates).
        """
        self._ensure_connected()
        assert self._quote_ctx is not None
        code = _normalize_codes([underlying])[0]
        return self._quote_ctx.get_option_chain(
            code=code,
            start=expiry,
            end=expiry,
            option_type=option_type,
            index_option_type=index_option_type,
        )

    def get_option_prices(
        self,
        underlying: str,
        expiry: str,
        *,
        option_type: OptionType = OptionType.ALL,
        strike: float | None = None,
        strike_min: float | None = None,
        strike_max: float | None = None,
        index_option_type: IndexOptionType = IndexOptionType.NORMAL,
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        """
        Option chain + live prices (snapshot) for the chosen expiry / type / strike.

        Use strike for one strike, or strike_min / strike_max for a range (inclusive).

        Returns merged DataFrame and any per-contract snapshot errors.
        """
        ret, chain = self.get_option_chain(
            underlying,
            expiry,
            option_type=option_type,
            index_option_type=index_option_type,
        )
        if ret != RET_OK:
            return pd.DataFrame(), {"chain": str(chain)}

        assert isinstance(chain, pd.DataFrame)
        if "strike_price" in chain.columns:
            strikes = pd.to_numeric(chain["strike_price"], errors="coerce")
            if strike is not None:
                chain = chain[strikes == strike]
            else:
                if strike_min is not None:
                    chain = chain[strikes >= strike_min]
                    strikes = pd.to_numeric(chain["strike_price"], errors="coerce")
                if strike_max is not None:
                    chain = chain[strikes <= strike_max]
        if chain.empty:
            return pd.DataFrame(), {}

        prices, errors = self.get_snapshots_safe(chain["code"].tolist())
        if prices.empty:
            return chain, errors

        merged = chain.merge(prices, on="code", how="left", suffixes=("", "_q"))
        return enrich_option_greeks(add_price_change_columns(merged)), errors

    def query_subscription(self):
        self._ensure_connected()
        assert self._quote_ctx is not None
        return self._quote_ctx.query_subscription()

    def run(self, seconds: float = 0) -> None:
        """Keep the connection alive to receive push quotes (blocks)."""
        import time

        self._ensure_connected()
        if seconds <= 0:
            logger.info("Streaming quotes. Press Ctrl+C to stop.")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
        else:
            time.sleep(seconds)

    def _ensure_connected(self) -> None:
        if self._quote_ctx is None:
            raise RuntimeError("Not connected. Call connect() first.")

    def __enter__(self) -> "FutuMarketDataClient":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.disconnect()


def market_display_columns(df: pd.DataFrame, *, include_option_greeks: bool = True) -> list[str]:
    """Column order for printing stocks, indices, or options."""
    base = [
        "code",
        "name",
        "option_type",
        "strike_time",
        "strike_price",
        "last_price",
        "change_val",
        "change_pct",
        "bid_price",
        "ask_price",
        "volume",
        "turnover",
        "prev_close_price",
        "open_price",
        "high_price",
        "low_price",
        "update_time",
    ]
    if include_option_greeks:
        base.extend(OPTION_GREEK_DISPLAY_COLUMNS)
    return [c for c in base if c in df.columns]


def format_market_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Apply price change + option greeks and format change_pct for display."""
    out = enrich_option_greeks(add_price_change_columns(df))
    if "change_pct" in out.columns:
        out = out.copy()
        out["change_pct"] = out["change_pct"].map(
            lambda x: f"{x:+.2f}%" if pd.notna(x) else "N/A"
        )
    if "iv" in out.columns:
        out = out.copy()
        out["iv"] = out["iv"].map(lambda x: f"{x:.2f}%" if pd.notna(x) else "N/A")
    if "premium" in out.columns:
        out = out.copy()
        out["premium"] = out["premium"].map(
            lambda x: f"{x:.2f}%" if pd.notna(x) else "N/A"
        )
    return out
