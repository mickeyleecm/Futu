const statusEl = document.getElementById("status");
const uploadForm = document.getElementById("uploadForm");
const pdfFile = document.getElementById("pdfFile");
const uploadResult = document.getElementById("uploadResult");
const dateFrom = document.getElementById("dateFrom");
const dateTo = document.getElementById("dateTo");
const productType = document.getElementById("productType");
const codeFilter = document.getElementById("codeFilter");
const btnSearch = document.getElementById("btnSearch");
const pnlBody = document.getElementById("pnlBody");
const pairBody = document.getElementById("pairBody");
const openBody = document.getElementById("openBody");
const openTotalsAmount = document.getElementById("openTotalsAmount");
const statClosedCount = document.getElementById("statClosedCount");
const statMatchedCount = document.getElementById("statMatchedCount");
const statClosedPnlHkd = document.getElementById("statClosedPnlHkd");
const statClosedPnlUsd = document.getElementById("statClosedPnlUsd");
const statClosedPnlHkdBase = document.getElementById("statClosedPnlHkdBase");
const statOptionPnl = document.getElementById("statOptionPnl");
const statWarrantPnl = document.getElementById("statWarrantPnl");
const statOpenCount = document.getElementById("statOpenCount");
const statWinRate = document.getElementById("statWinRate");
const pairTotalsPnl = document.getElementById("pairTotalsPnl");
const txBody = document.getElementById("txBody");
const txCount = document.getElementById("txCount");
const stmtBody = document.getElementById("stmtBody");
const monthlyBody = document.getElementById("monthlyBody");

function fmt(v, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
  return Number(v).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function setStatus(text, isError = false) {
  statusEl.textContent = text;
  statusEl.style.color = isError ? "#ff4d4f" : "";
}

async function fetchJson(url, options) {
  const res = await fetch(url, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || res.statusText);
  }
  return data;
}

function toLocalIso(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function defaultDates() {
  // Prefer latest statement month when available; else show all.
  dateFrom.value = "";
  dateTo.value = "";
}

function setStatementMonthFilter(monthIso) {
  if (!monthIso) return;
  const [y, m] = monthIso.split("-").map(Number);
  if (!y || !m) return;
  dateFrom.value = toLocalIso(new Date(y, m - 1, 1));
  dateTo.value = toLocalIso(new Date(y, m, 0)); // last day of month
}

function latestStatementMonth(statements) {
  let best = null;
  for (const s of statements || []) {
    const m = s.statement_month;
    if (!m) continue;
    if (!best || String(m) > String(best)) best = m;
  }
  return best ? String(best).slice(0, 10) : null;
}

function renderPnl(rows) {
  pnlBody.innerHTML = "";
  if (!rows.length) {
    pnlBody.innerHTML = `<tr><td colspan="10" class="muted">No data</td></tr>`;
    return;
  }
  rows.forEach((r) => {
    const pnl = Number(r.realized_pnl || 0);
    const cls = pnl >= 0 ? "pnl-pos" : "pnl-neg";
    const basis =
      r.pnl_basis === "closed_pairs_only" ? "closed pairs only" : "cash-flow";
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${r.product_type}</td>
      <td>${r.currency || "—"}</td>
      <td>${r.trade_count}</td>
      <td>${fmt(r.buy_qty, 0)}</td>
      <td>${fmt(r.sell_qty, 0)}</td>
      <td>${fmt(r.buy_amount)}</td>
      <td>${fmt(r.sell_amount)}</td>
      <td>${fmt(r.total_fees)}</td>
      <td class="${cls}">${fmt(pnl)}</td>
      <td class="muted">${basis}</td>
    `;
    pnlBody.appendChild(tr);
  });
}

function renderPairs(payload) {
  const pairs = (payload && payload.pairs) || [];
  const opens = (payload && payload.open_lots) || [];
  const byCcy = (payload && payload.realized_pnl_by_currency) || {};
  const byProdCcy = (payload && payload.realized_pnl_by_product_currency) || {};
  const hkd = Number(byCcy.HKD || 0);
  const usd = Number(byCcy.USD || 0);
  const opt = byProdCcy.OPTION || {};
  const war = byProdCcy.WARRANT || {};
  const optHkd = Number(opt.HKD || 0);
  const optUsd = Number(opt.USD || 0);
  const warHkd = Number(war.HKD || 0);
  const warUsd = Number(war.USD || 0);

  const matched = Number(
    (payload && payload.closed_with_open_count) != null
      ? payload.closed_with_open_count
      : pairs.filter((p) => !p.prior_open_missing).length
  );
  if (statClosedCount) statClosedCount.textContent = String(pairs.length);
  if (statMatchedCount) statMatchedCount.textContent = String(matched);
  if (statClosedPnlHkd) {
    statClosedPnlHkd.textContent = fmt(hkd);
    statClosedPnlHkd.className = `stat-value ${hkd >= 0 ? "pnl-pos" : "pnl-neg"}`;
  }
  if (statClosedPnlUsd) {
    statClosedPnlUsd.textContent = fmt(usd);
    statClosedPnlUsd.className = `stat-value ${usd >= 0 ? "pnl-pos" : "pnl-neg"}`;
  }
  const rate = Number((payload && payload.usd_hkd_rate) || 7.8);
  const hkdBase = Number(
    (payload && payload.total_realized_pnl_hkd_base) != null
      ? payload.total_realized_pnl_hkd_base
      : hkd + usd * rate
  );
  if (statClosedPnlHkdBase) {
    statClosedPnlHkdBase.innerHTML =
      `${fmt(hkdBase)} <span class="muted" style="font-size:11px;font-weight:500">(@${rate.toFixed(4)})</span>`;
    statClosedPnlHkdBase.className = `stat-value ${hkdBase >= 0 ? "pnl-pos" : "pnl-neg"}`;
  }
  if (statOptionPnl) {
    statOptionPnl.innerHTML = `<span class="${optHkd >= 0 ? "pnl-pos" : "pnl-neg"}">${fmt(optHkd)}</span> / <span class="${optUsd >= 0 ? "pnl-pos" : "pnl-neg"}">${fmt(optUsd)}</span>`;
    statOptionPnl.className = "stat-value";
  }
  if (statWarrantPnl) {
    statWarrantPnl.innerHTML = `<span class="${warHkd >= 0 ? "pnl-pos" : "pnl-neg"}">${fmt(warHkd)}</span> / <span class="${warUsd >= 0 ? "pnl-pos" : "pnl-neg"}">${fmt(warUsd)}</span>`;
    statWarrantPnl.className = "stat-value";
  }
  if (statOpenCount) statOpenCount.textContent = String(opens.length);
  if (statWinRate) {
    const wins = Number(
      (payload && payload.win_count) != null
        ? payload.win_count
        : pairs.filter((p) => !p.prior_open_missing && Number(p.realized_pnl) > 0).length
    );
    const losses = Number(
      (payload && payload.loss_count) != null
        ? payload.loss_count
        : pairs.filter((p) => !p.prior_open_missing && Number(p.realized_pnl) < 0).length
    );
    const ratePct =
      payload && payload.win_rate_pct != null
        ? Number(payload.win_rate_pct)
        : wins + losses > 0
          ? (wins / (wins + losses)) * 100
          : null;
    if (ratePct == null) {
      statWinRate.textContent = "—";
      statWinRate.className = "stat-value muted";
    } else {
      statWinRate.innerHTML =
        `<span class="pnl-pos">${wins} win</span> ` +
        `<span class="pnl-neg">${losses} lost</span>` +
        `<div style="font-size:16px;margin-top:4px">${fmt(ratePct, 1)}%</div>`;
      statWinRate.className = `stat-value ${ratePct >= 50 ? "pnl-pos" : "pnl-neg"}`;
    }
  }
  if (pairTotalsPnl) {
    const baseCls = hkdBase >= 0 ? "pnl-pos" : "pnl-neg";
    pairTotalsPnl.innerHTML =
      `HKD ${fmt(hkd)} · USD ${fmt(usd)} · ` +
      `<span class="${baseCls}">HKD base ${fmt(hkdBase)}</span>` +
      ` <span class="muted">(@${rate.toFixed(4)})</span>`;
    pairTotalsPnl.className = "";
  }

  pairBody.innerHTML = "";
  if (!pairs.length) {
    pairBody.innerHTML = `<tr><td colspan="16" class="muted">No closed option/warrant pairs in this period</td></tr>`;
  } else {
    pairs.forEach((p, idx) => {
      const missing = !!p.prior_open_missing;
      const pnl = p.realized_pnl;
      const pnlNum = pnl === null || pnl === undefined ? null : Number(pnl);
      const cls =
        pnlNum === null ? "muted" : pnlNum >= 0 ? "pnl-pos" : "pnl-neg";
      const pnlText = pnlNum === null ? "— (need prior open)" : fmt(pnlNum);

      let buyDate = p.buy_date;
      let sellDate = p.sell_date;
      let buyPrice = p.buy_price;
      let sellPrice = p.sell_price;
      if (!buyDate || !sellDate) {
        if (p.open_side === "BUY") {
          buyDate = p.open_date;
          sellDate = p.close_date;
          buyPrice = p.open_price;
          sellPrice = p.close_price;
        } else {
          sellDate = p.open_date;
          buyDate = p.close_date;
          sellPrice = p.open_price;
          buyPrice = p.close_price;
        }
      }

      const label = p.product_label || p.name || "—";
      const groupClass = idx % 2 === 0 ? "pair-group-a" : "pair-group-b";

      // Chronological: earlier leg first (buy or sell depending on direction)
      const openLeg = {
        leg: "OPEN",
        side: missing ? "—" : p.open_side || "—",
        date: missing ? "—" : p.open_date || "—",
        price: missing ? null : p.open_price,
        amount: missing ? null : p.open_amount,
        fee: missing ? null : p.open_fee,
      };
      const closeLeg = {
        leg: "CLOSE",
        side: p.close_side || "—",
        date: p.close_date || "—",
        price: p.close_price,
        amount: p.close_amount,
        fee: p.close_fee,
      };
      const legs =
        !missing && p.open_date && p.close_date && p.open_date > p.close_date
          ? [closeLeg, openLeg]
          : [openLeg, closeLeg];

      legs.forEach((leg, legIdx) => {
        const isLast = legIdx === legs.length - 1;
        const sideCls =
          leg.side === "BUY" ? "side-buy" : leg.side === "SELL" ? "side-sell" : "";
        const tr = document.createElement("tr");
        tr.className = `${groupClass}${missing ? " pair-missing-open" : ""}${
          isLast ? " pair-group-end" : " pair-group-start"
        }`;
        tr.innerHTML = `
          <td>${sellDate || "—"}</td>
          <td>${buyDate || "—"}</td>
          <td>${p.close_date || "—"}</td>
          <td class="${sideCls}">${leg.side}</td>
          <td>${p.code || "—"}</td>
          <td>${label}</td>
          <td>${p.expiry_ymd || "—"}</td>
          <td>${p.product_type || "—"}</td>
          <td>${p.direction || "—"}</td>
          <td>${leg.leg}</td>
          <td>${fmt(p.quantity, 2)}</td>
          <td>${leg.price == null ? "—" : fmt(leg.price, 3)}</td>
          <td>${leg.amount == null ? "—" : fmt(leg.amount)}</td>
          <td>${leg.fee == null ? "—" : fmt(leg.fee)}</td>
          <td class="${isLast ? cls : "muted"}">${isLast ? pnlText : ""}</td>
          <td>${p.currency || "—"}</td>
        `;
        pairBody.appendChild(tr);
      });
    });
  }

  openBody.innerHTML = "";
  if (!opens.length) {
    openBody.innerHTML = `<tr><td colspan="11" class="muted">No unmatched open lots</td></tr>`;
    if (openTotalsAmount) openTotalsAmount.textContent = "—";
    return;
  }
  let openHkd = 0;
  let openUsd = 0;
  opens.forEach((p) => {
    const amt = Number(p.open_amount || 0);
    const ccy = String(p.currency || "HKD").toUpperCase();
    if (ccy === "USD") openUsd += amt;
    else if (ccy === "HKD") openHkd += amt;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${p.open_date || "—"}</td>
      <td>${p.code || "—"}</td>
      <td>${p.product_label || p.name || "—"}</td>
      <td>${p.expiry_ymd || "—"}</td>
      <td>${p.product_type || "—"}</td>
      <td>${p.direction || "—"}</td>
      <td class="${p.side === "BUY" ? "side-buy" : "side-sell"}">${p.side}</td>
      <td>${fmt(p.quantity, 2)}</td>
      <td>${fmt(p.open_price, 3)}</td>
      <td>${fmt(p.open_amount)}</td>
      <td>${p.currency || "—"}</td>
    `;
    openBody.appendChild(tr);
  });
  if (openTotalsAmount) {
    const rate = Number((payload && payload.usd_hkd_rate) || 7.8);
    const hkdBase = openHkd + openUsd * rate;
    openTotalsAmount.innerHTML =
      `HKD ${fmt(openHkd)} · USD ${fmt(openUsd)} · ` +
      `HKD base ${fmt(hkdBase)}` +
      ` <span class="muted">(@${rate.toFixed(4)})</span>`;
  }
}

function renderTx(rows) {
  txBody.innerHTML = "";
  txCount.textContent = `(${rows.length})`;
  if (!rows.length) {
    txBody.innerHTML = `<tr><td colspan="12" class="muted">No transactions in this period</td></tr>`;
    return;
  }
  rows.forEach((r) => {
    const sideCls = r.side === "BUY" ? "side-buy" : r.side === "SELL" ? "side-sell" : "";
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${r.trade_date || "—"}</td>
      <td>${r.code || "—"}</td>
      <td>${r.product_label || r.name || "—"}</td>
      <td>${r.expiry_ymd || "—"}</td>
      <td class="${sideCls}">${r.side}</td>
      <td>${r.product_type}</td>
      <td>${fmt(r.quantity, 2)}</td>
      <td>${fmt(r.price, 3)}</td>
      <td>${fmt(r.amount)}</td>
      <td>${fmt(r.total_fee)}</td>
      <td>${fmt(r.net_amount)}</td>
      <td>${r.currency || "—"}</td>
    `;
    txBody.appendChild(tr);
  });
}

function renderMonthly(rows) {
  if (!monthlyBody) return;
  monthlyBody.innerHTML = "";
  if (!rows || !rows.length) {
    monthlyBody.innerHTML = `<tr><td colspan="8" class="muted">No monthly data</td></tr>`;
    return;
  }
  rows.forEach((r) => {
    const hkd = Number(r.closed_pnl_hkd || 0);
    const usd = Number(r.closed_pnl_usd || 0);
    const base = Number(r.closed_pnl_hkd_base || 0);
    const wins = Number(r.win_count || 0);
    const losses = Number(r.loss_count || 0);
    const rate = r.win_rate_pct;
    const rateText =
      rate === null || rate === undefined ? "—" : `${fmt(rate, 1)}%`;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${r.month_label || r.month || "—"}</td>
      <td>${r.transaction_count ?? 0}</td>
      <td>${r.closed_pairs ?? 0}</td>
      <td class="${hkd >= 0 ? "pnl-pos" : "pnl-neg"}">${fmt(hkd)}</td>
      <td class="${usd >= 0 ? "pnl-pos" : "pnl-neg"}">${fmt(usd)}</td>
      <td class="${base >= 0 ? "pnl-pos" : "pnl-neg"}">${fmt(base)}</td>
      <td><span class="pnl-pos">${wins} win</span> / <span class="pnl-neg">${losses} lost</span></td>
      <td class="${rate == null ? "muted" : Number(rate) >= 50 ? "pnl-pos" : "pnl-neg"}">${rateText}</td>
    `;
    monthlyBody.appendChild(tr);
  });
}

function renderStatements(rows) {
  stmtBody.innerHTML = "";
  if (!rows.length) {
    stmtBody.innerHTML = `<tr><td colspan="5" class="muted">No statements uploaded yet</td></tr>`;
    return;
  }
  rows.forEach((r) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${(r.uploaded_at || "").replace("T", " ").slice(0, 19)}</td>
      <td>${r.filename}</td>
      <td>${r.statement_month || "—"}</td>
      <td>${r.txn_count ?? 0}</td>
      <td>${r.parse_status}${r.parse_message ? " · " + r.parse_message : ""}</td>
    `;
    stmtBody.appendChild(tr);
  });
}

async function loadStatements() {
  const data = await fetchJson("/api/statements");
  renderStatements(data.statements || []);
  return data.statements || [];
}

async function search() {
  const params = new URLSearchParams();
  if (dateFrom.value) params.set("date_from", dateFrom.value);
  if (dateTo.value) params.set("date_to", dateTo.value);
  if (productType.value) params.set("product_type", productType.value);
  if (codeFilter.value.trim()) params.set("code", codeFilter.value.trim());
  setStatus("Loading transactions…");
  const data = await fetchJson(`/api/transactions?${params}`);
  renderPnl(data.pnl_by_product || []);
  renderPairs(data.pair_pnl || {});
  renderTx(data.transactions || []);
  renderMonthly(data.monthly_summary || []);
  setStatus(`Loaded ${data.count} transactions`);
}

uploadForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!pdfFile.files.length) return;
  const fd = new FormData();
  fd.append("file", pdfFile.files[0]);
  uploadResult.textContent = "Uploading…";
  setStatus("Importing statement…");
  try {
    const data = await fetchJson("/api/statements/upload", { method: "POST", body: fd });
    uploadResult.textContent = JSON.stringify(
      {
        statement_id: data.statement_id,
        month: data.statement_month,
        trades: data.transactions_inserted,
        warnings: data.warnings,
        sample: data.sample,
      },
      null,
      2
    );
    setStatus(`Imported ${data.transactions_inserted} trades`);
    setStatementMonthFilter(data.statement_month);
    codeFilter.value = "";
    productType.value = "";
    await loadStatements();
    await search();
  } catch (err) {
    uploadResult.textContent = String(err.message || err);
    setStatus(err.message, true);
  }
});

btnSearch.addEventListener("click", () => {
  search().catch((err) => setStatus(err.message, true));
});

const btnShowAll = document.getElementById("btnShowAll");
if (btnShowAll) {
  btnShowAll.addEventListener("click", () => {
    dateFrom.value = "";
    dateTo.value = "";
    productType.value = "";
    codeFilter.value = "";
    search().catch((err) => setStatus(err.message, true));
  });
}

async function init() {
  defaultDates();
  try {
    const health = await fetchJson("/api/health");
    setStatus(
      `DB ${health.database ? "ok" : "down"} · OpenD ${
        health.connected ? health.opend : "offline"
      }`
    );
    const stmts = await loadStatements();
    const latest = latestStatementMonth(stmts);
    if (latest) setStatementMonthFilter(latest);
    await search();
  } catch (err) {
    setStatus(err.message, true);
  }
}

init();
