"""Extract display fields from option / warrant product codes."""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Optional

# HK.HKB260828C175000 / US.MU260828P650000 → YYMMDD before C/P
_OPTION_EXPIRY_RE = re.compile(
    r"(?:^|\.)([A-Z]{1,6})(\d{6})[CP]\d+",
    re.IGNORECASE,
)


def extract_expiry_ymd(code: str | None) -> Optional[str]:
    """Return expiry as YYYYMMDD from an option code, else None."""
    if not code:
        return None
    m = _OPTION_EXPIRY_RE.search(code.replace(" ", ""))
    if not m:
        return None
    yymmdd = m.group(2)
    try:
        yy, mm, dd = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
        d = date(2000 + yy, mm, dd)
    except ValueError:
        return None
    return d.strftime("%Y%m%d")


def extract_expiry_iso(code: str | None) -> Optional[str]:
    ymd = extract_expiry_ymd(code)
    if not ymd:
        return None
    return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"


def enrich_product_fields(row: dict[str, Any]) -> dict[str, Any]:
    """Add expiry_ymd / expiry / product_label onto a transaction-like dict."""
    code = row.get("code")
    name = row.get("name") or ""
    expiry_ymd = extract_expiry_ymd(code)
    out = dict(row)
    out["expiry_ymd"] = expiry_ymd
    out["expiry"] = extract_expiry_iso(code)
    if expiry_ymd:
        label_name = name.strip() if name else (code or "")
        out["product_label"] = f"{label_name} {expiry_ymd}".strip()
    else:
        out["product_label"] = name or code or ""
    return out
