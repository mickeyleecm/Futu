from src.db import monthly_pair_summaries

for r in monthly_pair_summaries():
    wr = r["win_rate_pct"]
    wr_s = f"{wr:.1f}%" if wr is not None else "—"
    print(
        r["month_label"],
        "tx",
        r["transaction_count"],
        "pairs",
        r["closed_pairs"],
        "HKD",
        round(r["closed_pnl_hkd"], 2),
        "USD",
        round(r["closed_pnl_usd"], 2),
        "base",
        round(r["closed_pnl_hkd_base"], 2),
        f"{r['win_count']}W/{r['loss_count']}L",
        wr_s,
    )
