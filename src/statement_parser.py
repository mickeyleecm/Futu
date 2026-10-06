"""
Parse Futu / Futubull monthly PDF statements (HK Traditional Chinese layout).

Trade rows are often split across multiple lines, e.g.:

  買入平倉 HKD 17 2.0000 13,600.00 -13,693.20
  HKB260828C1 SEHK HKD 2026/08/03 2026/08/04 17 2.0000 13,600.00 -13,693.20
  75000(匯豐 15:00:09
  260828 175.00
  購)
  佣金: 27.20 平台使用費: 15.00 交易系統使用費: 51.00 小計: 93.20
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Optional

import pdfplumber


@dataclass
class ParsedTransaction:
    trade_date: date
    settle_date: Optional[date]
    code: str
    name: Optional[str]
    side: str
    quantity: Decimal
    price: Decimal
    amount: Decimal
    commission: Decimal = Decimal("0")
    stamp_duty: Decimal = Decimal("0")
    trading_fee: Decimal = Decimal("0")
    settlement_fee: Decimal = Decimal("0")
    platform_fee: Decimal = Decimal("0")
    other_fee: Decimal = Decimal("0")
    total_fee: Decimal = Decimal("0")
    net_amount: Decimal = Decimal("0")
    currency: str = "HKD"
    market: Optional[str] = None
    product_type: str = "STOCK"
    remark: Optional[str] = None
    raw_line: Optional[str] = None

    def to_db_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ParseResult:
    transactions: list[ParsedTransaction] = field(default_factory=list)
    statement_month: Optional[date] = None
    account_id: Optional[str] = None
    page_count: int = 0
    raw_text: str = ""
    warnings: list[str] = field(default_factory=list)


_SIDE_RE = re.compile(
    r"^(買入平倉|賣出平倉|買入開倉|賣出開倉|买入平仓|卖出平仓|买入开仓|卖出开仓|買入|賣出|买入|卖出)\b"
)
_DATE_RE = re.compile(r"(20\d{2})[/-](\d{1,2})[/-](\d{1,2})")
_DETAIL_RE = re.compile(
    r"(?P<code_part>[A-Z]{0,6}\d{0,6}[A-Z]?\d*(?:\([^)]*)?)\s+"
    r"(?P<exchange>SEHK|EMLD|MPRL|XCBO|AMXO|ARCO|NASD|NYSE|[A-Z]{2,6})\s+"
    r"(?P<ccy>HKD|USD|CNH|CNY|JPY|SGD|KRW)\s+"
    r"(?P<tdate>20\d{2}[/-]\d{1,2}[/-]\d{1,2})\s+"
    r"(?P<sdate>20\d{2}[/-]\d{1,2}[/-]\d{1,2})\s+"
    r"(?P<qty>[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s+"
    r"(?P<price>[-+]?\d+(?:\.\d+)?)\s+"
    r"(?P<amount>[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s+"
    r"(?P<net>[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?)",
    re.IGNORECASE,
)
_STOCK_CODE_RE = re.compile(r"^(\d{5})\(")
_FEE_RE = re.compile(
    r"(佣金|平台使用費|平台使用费|交易系統使用費|交易系统使用费|交收費|交收费|"
    r"印花稅|印花税|交易費|交易费|證監會徵費|证监会征费|財匯局徵費|财汇局征费|"
    r"期權監管費|期权监管费|期權清算費|期权清算费|期權交收費|期权交收费|"
    r"證監會規費|证监会规费|交易活動費|交易活动费|"
    r"綜合審計跟蹤監管費|综合审计跟踪监管费|小計|小计)\s*[:：]\s*"
    r"([-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?)"
)
_CASH_RE = re.compile(
    r"(?P<date>20\d{2}[/-]\d{1,2}[/-]\d{1,2}).*?(出入金|存款|取款|轉入|转入|轉出|转出).*?"
    r"(?P<ccy>HKD|USD|CNH|CNY)\s*(?P<sign>[-+＋－])?\s*(?P<amt>\d{1,3}(?:,\d{3})*(?:\.\d+)?)",
    re.IGNORECASE,
)
_SKIP_LINE_RE = re.compile(
    r"^(保證金|证券月结|證券月結|製備日期|制备日期|買賣方向|买卖方向|客戶姓名|"
    r"期初|期末|資產|资产|參考匯率|交易-|$)"
)


def _dec(text: str) -> Decimal:
    cleaned = (
        str(text)
        .replace(",", "")
        .replace("，", "")
        .replace("＋", "+")
        .replace("－", "-")
        .strip()
    )
    if cleaned in ("", "-", "—"):
        return Decimal("0")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return Decimal("0")


def _parse_date(text: str) -> Optional[date]:
    m = _DATE_RE.search(text)
    if not m:
        return None
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _map_side(label: str) -> str:
    if "買" in label or "买" in label:
        return "BUY"
    if "賣" in label or "卖" in label:
        return "SELL"
    return "OTHER"


def _clean_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    # Drop trade-time / strike fragments that PDF line-breaks inject into names
    name = re.sub(r"\d{1,2}:\d{2}:\d{2}", "", name)
    # US underlying shown as MU21:33:39… — keep ticker only
    m = re.match(r"^([A-Z]{1,6})\d", name.strip())
    if m and not re.search(r"[\u4e00-\u9fff]", name):
        return m.group(1)
    # Prefer Chinese + latin letters (drops leftover strike digits)
    parts = re.findall(r"[\u4e00-\u9fffA-Za-z]+", name)
    if parts:
        name = "".join(parts)
    # Trailing 購/沽 is option type, not part of the name
    name = re.sub(r"[購沽购]$", "", name)
    name = name.strip(" .")
    return name or None


def classify_product_type(code: str, name: str = "") -> str:
    blob = f"{code} {name}".upper()
    if re.search(r"(C|P)\d{4,}", code.upper()) or any(
        x in blob for x in ("OPTION", "期權", "期权", "購)", "沽)", "购)", "沽)")
    ):
        return "OPTION"
    if any(
        x in name or x in blob
        for x in ("WARRANT", "窩輪", "窝轮", "牛熊", "CBBC", "牛", "熊", "窩", "涡")
    ):
        return "WARRANT"
    if "ETF" in blob or "基金" in name:
        return "ETF"
    if code.upper() in ("HKD", "USD", "CNH", "CNY") or "CASH" in blob or "出入金" in name:
        return "CASH"
    return "STOCK"


def _extract_account(text: str) -> Optional[str]:
    m = re.search(r"(?:賬戶號碼|账户号码|帳戶號碼)\s*[:：]?\s*(\d+)", text)
    return m.group(1) if m else None


def _extract_statement_month(text: str) -> Optional[date]:
    m = re.search(r"證券月結單\s*\n\s*(20\d{2})[/-](\d{1,2})", text)
    if not m:
        m = re.search(r"(20\d{2})[/-](\d{1,2})\s*\n\s*帳戶資料", text)
    if m:
        return date(int(m.group(1)), int(m.group(2)), 1)
    d = _parse_date(text[:1500])
    return date(d.year, d.month, 1) if d else None


def extract_fx_rates(text: str) -> dict[str, float]:
    """Parse 參考匯率 lines, e.g. USD/HKD=7.838800 → {'USDHKD': 7.8388}."""
    rates: dict[str, float] = {}
    for m in re.finditer(
        r"([A-Z]{3})\s*/\s*HKD\s*=\s*([0-9]+(?:\.[0-9]+)?)",
        text or "",
        re.IGNORECASE,
    ):
        ccy = m.group(1).upper()
        try:
            rates[f"{ccy}HKD"] = float(m.group(2))
        except ValueError:
            continue
    return rates


def _reconstruct_code(code_part: str, following_lines: list[str]) -> tuple[str, Optional[str]]:
    """Rebuild option/stock code split across lines; extract name from (...)."""
    # Flatten and remove time-like tokens for matching
    joined = " ".join([code_part] + following_lines)
    compact = re.sub(r"\s+", "", joined)

    # Stock / warrant 5-digit: 00341(大家樂集團) or 67965(恒指…牛…)
    m = re.search(r"(\d{5})\(([^)]*)\)", compact)
    if m and not re.search(r"[A-Z]{2,}\d{6}[CP]", compact, re.I):
        return m.group(1), _clean_name(m.group(2))

    # Full option code already joined: HKB260828C175000(...)
    m = re.search(r"([A-Z]{1,6}\d{6}[CP]\d{3,})(\(([^)]*)\))?", compact, re.I)
    if m:
        return m.group(1).upper(), _clean_name(m.group(3))

    # Split option: prefix HKB260828C1 + next line 75000(
    prefix = re.match(r"^([A-Z]+\d{6}[CP]\d*)", code_part.replace(" ", ""), re.I)
    digits = ""
    name = None
    for line in following_lines:
        s = line.strip()
        dm = re.match(r"^(\d{3,})\(", s)
        if dm:
            digits = dm.group(1)
            nm = re.search(r"\((.+)$", s)
            if nm:
                name = nm.group(1).split(")")[0]
                name = re.sub(r"\d{1,2}:\d{2}:\d{2}", "", name).strip()
            break
    if prefix and digits:
        code = (prefix.group(1) + digits).upper()
        if not name:
            nm = re.search(r"\(([^)]*)\)", compact)
            if nm:
                name = nm.group(1)
        return code, _clean_name(name)

    # Fallback stock digits only
    m = re.match(r"^(\d{5})", code_part.strip())
    if m:
        return m.group(1), None

    token = re.match(r"^([A-Z0-9]+)", code_part.strip(), re.I)
    return (token.group(1).upper() if token else code_part.strip()), None


def _parse_fees(fee_line: str) -> dict[str, Decimal]:
    fees = {
        "commission": Decimal("0"),
        "stamp_duty": Decimal("0"),
        "trading_fee": Decimal("0"),
        "settlement_fee": Decimal("0"),
        "platform_fee": Decimal("0"),
        "other_fee": Decimal("0"),
        "total_fee": Decimal("0"),
    }
    for label, val in _FEE_RE.findall(fee_line):
        amount = _dec(val)
        if "佣金" in label:
            fees["commission"] += amount
        elif "印花" in label:
            fees["stamp_duty"] += amount
        elif "平台" in label:
            fees["platform_fee"] += amount
        elif "交收" in label or "清算" in label:
            fees["settlement_fee"] += amount
        elif "小計" in label or "小计" in label:
            fees["total_fee"] = amount
        else:
            fees["trading_fee"] += amount
            fees["other_fee"] += amount
    if fees["total_fee"] == 0:
        fees["total_fee"] = (
            fees["commission"]
            + fees["stamp_duty"]
            + fees["trading_fee"]
            + fees["settlement_fee"]
            + fees["platform_fee"]
        )
    return fees


def _parse_trade_block(side_label: str, block_lines: list[str]) -> Optional[ParsedTransaction]:
    blob = "\n".join(block_lines)
    detail = None
    detail_idx = -1
    for i, line in enumerate(block_lines):
        m = _DETAIL_RE.search(line)
        if m:
            detail = m
            detail_idx = i
            break
    if not detail:
        return None

    following = block_lines[detail_idx + 1 :]
    # Stop following at fee line for code reconstruction
    follow_for_code: list[str] = []
    fee_line = ""
    for line in following:
        if line.startswith("佣金") or "小計:" in line or "小计:" in line:
            fee_line = line
            break
        follow_for_code.append(line)

    code, name = _reconstruct_code(detail.group("code_part"), follow_for_code)
    # Name sometimes incomplete; try parentheses from blob
    if not name:
        nm = re.search(r"\(([^)]{1,40})\)", blob.replace("\n", ""))
        if nm:
            name = _clean_name(nm.group(1))

    trade_date = _parse_date(detail.group("tdate"))
    settle_date = _parse_date(detail.group("sdate"))
    if not trade_date:
        return None

    qty = _dec(detail.group("qty"))
    price = _dec(detail.group("price"))
    amount = _dec(detail.group("amount"))
    net_change = _dec(detail.group("net"))
    ccy = detail.group("ccy").upper()
    exchange = detail.group("exchange").upper()

    fees = _parse_fees(fee_line) if fee_line else {
        "commission": Decimal("0"),
        "stamp_duty": Decimal("0"),
        "trading_fee": Decimal("0"),
        "settlement_fee": Decimal("0"),
        "platform_fee": Decimal("0"),
        "other_fee": Decimal("0"),
        "total_fee": abs(amount) - abs(net_change)
        if amount and net_change
        else Decimal("0"),
    }

    side = _map_side(side_label)
    market = "HK" if exchange == "SEHK" else ("US" if ccy == "USD" else exchange)
    if code.isdigit() and len(code) <= 5:
        code = f"HK.{code.zfill(5)}"
    elif re.match(r"^[A-Z]+\d+[CP]\d+", code, re.I):
        # option code as-is; prefix market for consistency
        if not code.startswith(("HK.", "US.")):
            code = f"{'US' if ccy == 'USD' else 'HK'}.{code}"

    product_type = classify_product_type(code, name or "")
    remark = side_label

    return ParsedTransaction(
        trade_date=trade_date,
        settle_date=settle_date,
        code=code,
        name=name,
        side=side,
        quantity=qty,
        price=price,
        amount=amount,
        commission=fees["commission"],
        stamp_duty=fees["stamp_duty"],
        trading_fee=fees["trading_fee"],
        settlement_fee=fees["settlement_fee"],
        platform_fee=fees["platform_fee"],
        other_fee=fees["other_fee"],
        total_fee=fees["total_fee"],
        net_amount=abs(net_change) if net_change != 0 else (
            amount + fees["total_fee"] if side == "BUY" else amount - fees["total_fee"]
        ),
        currency=ccy,
        market=market,
        product_type=product_type,
        remark=remark,
        raw_line=blob[:500].replace("\n", " | "),
    )


def _parse_cash_movements(text: str) -> list[ParsedTransaction]:
    rows: list[ParsedTransaction] = []
    for line in text.splitlines():
        if "出入金" not in line and "存款" not in line and "取款" not in line:
            continue
        m = _CASH_RE.search(line)
        if not m:
            continue
        trade_date = _parse_date(m.group("date"))
        if not trade_date:
            continue
        amount = _dec(m.group("amt"))
        sign = m.group("sign") or "+"
        if sign in ("-", "－"):
            side = "WITHDRAW"
            net = amount
        else:
            side = "DEPOSIT"
            net = amount
        rows.append(
            ParsedTransaction(
                trade_date=trade_date,
                settle_date=None,
                code=m.group("ccy").upper(),
                name="出入金",
                side=side,
                quantity=Decimal("0"),
                price=Decimal("0"),
                amount=amount,
                total_fee=Decimal("0"),
                net_amount=net,
                currency=m.group("ccy").upper(),
                market="CASH",
                product_type="CASH",
                remark=line.strip()[:200],
                raw_line=line.strip()[:500],
            )
        )
    return rows


def _iter_trade_blocks(lines: list[str]) -> list[tuple[str, list[str]]]:
    """Split trade section into (side_label, block_lines)."""
    blocks: list[tuple[str, list[str]]] = []
    i = 0
    pending_side: Optional[str] = None
    while i < len(lines):
        line = lines[i].strip()
        if not line or _SKIP_LINE_RE.search(line):
            i += 1
            continue
        if line.startswith("製備日期") or line.startswith("制备日期"):
            i += 1
            continue
        if line.startswith("期末") or line.startswith("期權交易確認"):
            break

        sm = _SIDE_RE.match(line)
        if sm:
            pending_side = sm.group(1)
            block = [line]
            i += 1
            # Collect until next side or after fee line + one more if needed
            while i < len(lines):
                nxt = lines[i].strip()
                if not nxt:
                    i += 1
                    continue
                if nxt.startswith("製備日期") or nxt.startswith("制备日期"):
                    i += 1
                    continue
                if nxt.startswith("買賣方向") or nxt.startswith("买卖方向"):
                    i += 1
                    continue
                if nxt.startswith("保證金") or nxt.startswith("證券月結"):
                    i += 1
                    continue
                if _SIDE_RE.match(nxt):
                    break
                block.append(nxt)
                i += 1
                if nxt.startswith("佣金"):
                    break
            blocks.append((pending_side, block))
            continue

        # Continuation after page break: detail line without side header
        if pending_side and _DETAIL_RE.search(line):
            block = [line]
            i += 1
            while i < len(lines):
                nxt = lines[i].strip()
                if not nxt:
                    i += 1
                    continue
                if nxt.startswith("製備日期") or nxt.startswith("制备日期"):
                    i += 1
                    continue
                if nxt.startswith("買賣方向") or nxt.startswith("买卖方向"):
                    i += 1
                    continue
                if _SIDE_RE.match(nxt):
                    break
                block.append(nxt)
                i += 1
                if nxt.startswith("佣金"):
                    break
            blocks.append((pending_side, block))
            continue

        i += 1
    return blocks


def parse_statement_pdf(path: str | Path) -> ParseResult:
    path = Path(path)
    result = ParseResult()
    pages_text: list[str] = []

    with pdfplumber.open(path) as pdf:
        result.page_count = len(pdf.pages)
        for page in pdf.pages:
            pages_text.append(page.extract_text() or "")

    full = "\n".join(pages_text)
    result.raw_text = full
    result.account_id = _extract_account(full)
    result.statement_month = _extract_statement_month(full)

    # Focus on trade section: from first "交易" after summary until 期末概覽
    trade_start = full.find("交易-股票和股票期權")
    if trade_start < 0:
        trade_start = full.find("交易-股票和股票期权")
    if trade_start < 0:
        trade_start = full.find("\n交易\n")
    trade_end = full.find("期末概覽", trade_start if trade_start >= 0 else 0)
    if trade_end < 0:
        trade_end = full.find("期末概览", trade_start if trade_start >= 0 else 0)
    if trade_end < 0:
        trade_end = len(full)

    trade_text = full[trade_start:trade_end] if trade_start >= 0 else full
    lines = [ln.strip() for ln in trade_text.splitlines() if ln.strip()]

    for side_label, block in _iter_trade_blocks(lines):
        try:
            txn = _parse_trade_block(side_label, block)
        except Exception as exc:  # noqa: BLE001
            result.warnings.append(f"trade skip: {exc}")
            continue
        if txn:
            result.transactions.append(txn)
        else:
            result.warnings.append(
                "unparsed trade block: " + " | ".join(block)[:180]
            )

    # Cash movements from whole document
    result.transactions.extend(_parse_cash_movements(full))

    # Deduplicate
    seen: set[str] = set()
    unique: list[ParsedTransaction] = []
    for t in result.transactions:
        key = f"{t.trade_date}|{t.code}|{t.side}|{t.quantity}|{t.price}|{t.amount}|{t.remark}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(t)
    result.transactions = unique

    if not any(t.product_type != "CASH" for t in result.transactions):
        result.warnings.append(
            "No stock/option trades found — only cash movements (if any)."
        )
    return result


def parse_statement_bytes(data: bytes, filename: str = "statement.pdf") -> ParseResult:
    import tempfile

    suffix = Path(filename).suffix or ".pdf"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    try:
        return parse_statement_pdf(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)
