from collections import Counter
from pathlib import Path

from src.statement_parser import parse_statement_pdf

uploads = Path("/app/uploads")
for pdf in sorted(uploads.glob("Futu-*-statement.pdf")):
    r = parse_statement_pdf(pdf)
    rem = Counter()
    codes_hkb = []
    for t in r.transactions:
        if t.product_type in ("OPTION", "WARRANT"):
            rem[t.remark or ""] += 1
            if t.code and "HKB260828C175" in t.code:
                codes_hkb.append((t.trade_date, t.side, t.remark, t.code, t.quantity, t.price))
    print(pdf.name, "tx", len(r.transactions), dict(rem))
    if codes_hkb:
        print("  HKB260828C175:", codes_hkb)
