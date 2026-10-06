from collections import Counter, defaultdict

from src.db import list_option_warrant_trades, list_transactions

rows = list_option_warrant_trades()
by = defaultdict(list)
for r in rows:
    by[r["code"]].append(r)

print("remarks deriv", Counter((r.get("remark") or "") for r in rows))
print("=== closes ===")
orphan_closes = []
matched_closes = []
for code, ts in sorted(by.items()):
    for t in ts:
        rem = t.get("remark") or ""
        if "平倉" not in rem:
            continue
        opens = [
            x
            for x in ts
            if x.get("remark")
            and "開倉" in x["remark"]
            and str(x["trade_date"]) <= str(t["trade_date"])
        ]
        info = (
            str(t["trade_date"]),
            t["side"],
            rem,
            code,
            float(t["quantity"]),
            float(t["price"]),
            len(opens),
            len(ts),
        )
        if opens:
            matched_closes.append(info)
        else:
            orphan_closes.append(info)

print("matched_close_trades", len(matched_closes))
for x in matched_closes:
    print(" M", x)
print("orphan_close_trades", len(orphan_closes))
for x in orphan_closes:
    print(" O", x)

# Also check: 開倉 then later same side 平倉 wrongly treated?
print("\nall remarks in DB", Counter((r.get("remark") or "") for r in list_transactions(limit=5000)))

# For orphan 買入平倉: look if same code has 賣出開倉 AFTER close (wrong order) or only close
print("\norphan code detail:")
for info in orphan_closes:
    code = info[3]
    print(code)
    for t in by[code]:
        print(
            " ",
            t["trade_date"],
            t["side"],
            t.get("remark"),
            float(t["quantity"]),
            float(t["price"]),
        )
