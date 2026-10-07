/** Show strikes within ± this many price points of spot (e.g. 152.10 → 142.10..162.10). */
const PRICE_SPREAD = 10;
const CHAIN_COLSPAN = 9;

function displayCode(code) {
  if (!code) return "—";
  const s = String(code);
  return s.includes(".") ? s.split(".", 2)[1] : s;
}

function fmtPrice(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
  const n = Number(v);
  if (Math.abs(n) >= 100) return n.toFixed(2);
  return n.toFixed(3);
}

function fmtOpt(v, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
  return Number(v).toFixed(digits);
}

function fmtVol(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
  return String(Math.round(Number(v)));
}

function fmtChg(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
  const n = Number(v);
  const sign = n > 0 ? "+" : "";
  return `${sign}${fmtPrice(n)}`;
}

function fmtPct(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
  const n = Number(v);
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}%`;
}

function dayClass(changePct) {
  if (changePct === null || changePct === undefined || Number.isNaN(Number(changePct))) {
    return "flat";
  }
  const n = Number(changePct);
  if (n > 0) return "raise";
  if (n < 0) return "drop";
  return "flat";
}

function vsMaClass(last, ma) {
  if (
    last === null || last === undefined || Number.isNaN(Number(last)) ||
    ma === null || ma === undefined || Number.isNaN(Number(ma))
  ) {
    return "flat";
  }
  const a = Number(last);
  const b = Number(ma);
  if (a > b) return "raise";
  if (a < b) return "drop";
  return "flat";
}

function tdNum(text, cls) {
  return `<td class="num ${cls || "flat"}">${text}</td>`;
}

let marketRows = [];
let selectedCode = null;
let selectedExpiry = null;
let expirations = [];
let optionsLoadSeq = 0;

function renderRows(rows) {
  marketRows = rows || [];
  const body = document.getElementById("marketBody");
  const empty = document.getElementById("empty");
  body.innerHTML = "";
  if (!marketRows.length) {
    empty.hidden = false;
    selectedCode = null;
    clearOptionsPanel("No favourite stocks.");
    return;
  }
  empty.hidden = true;

  if (!selectedCode || !marketRows.some((r) => r.code === selectedCode)) {
    selectedCode = marketRows[0].code;
  }

  marketRows.forEach((r) => {
    const tr = document.createElement("tr");
    if (r.code === selectedCode) tr.classList.add("selected");
    tr.dataset.code = r.code;
    tr.addEventListener("click", () => {
      if (selectedCode === r.code) return;
      selectedCode = r.code;
      selectedExpiry = null;
      body.querySelectorAll("tr").forEach((x) => x.classList.remove("selected"));
      tr.classList.add("selected");
      loadOptionsFor(r.code);
    });
    const cls = dayClass(r.change_pct);
    const zh = r.name_zh || "—";
    tr.innerHTML = `
      <td class="code">${displayCode(r.code)}</td>
      <td class="name">${zh}</td>
      ${tdNum(fmtPrice(r.last_price), cls)}
      ${tdNum(fmtPrice(r.ma50), vsMaClass(r.last_price, r.ma50))}
      ${tdNum(fmtPrice(r.ma60), vsMaClass(r.last_price, r.ma60))}
      ${tdNum(fmtPrice(r.bid_price), cls)}
      ${tdNum(fmtPrice(r.ask_price), cls)}
      ${tdNum(fmtPrice(r.open_price))}
      ${tdNum(fmtChg(r.change_val), cls)}
      ${tdNum(fmtPct(r.change_pct), cls)}
      ${tdNum(fmtPrice(r.highest52weeks_price))}
      ${tdNum(fmtPrice(r.lowest52weeks_price))}
    `;
    body.appendChild(tr);
  });

  loadOptionsFor(selectedCode);
}

function clearOptionsPanel(msg) {
  document.getElementById("optionsTitle").textContent = "Option Price";
  document.getElementById("optionsMeta").textContent = msg || "Click a stock to load options";
  document.getElementById("expiryTabs").innerHTML = "";
  document.getElementById("optionsEmpty").hidden = false;
  document.getElementById("optionsEmpty").textContent =
    msg || "Click a stock code to show option prices (spot ±10).";
  document.getElementById("optionsTableWrap").hidden = true;
  document.getElementById("optionsBody").innerHTML = "";
}

/** Keep strikes in [spot - spread, spot + spread] by absolute price. */
function filterPriceBandRows(rows, underlyingPrice, spread = PRICE_SPREAD) {
  if (!rows || !rows.length) return [];
  if (underlyingPrice == null || Number.isNaN(Number(underlyingPrice))) return rows;
  const spot = Number(underlyingPrice);
  const lo = spot - spread;
  const hi = spot + spread;
  return rows
    .filter((r) => {
      const s = Number(r.strike);
      return !Number.isNaN(s) && s >= lo && s <= hi;
    })
    .sort((a, b) => Number(a.strike) - Number(b.strike));
}

function midOf(leg) {
  if (!leg) return null;
  if (leg.mid != null) return leg.mid;
  const b = leg.bid;
  const a = leg.ask;
  if (b != null && a != null && b > 0 && a > 0) return (Number(b) + Number(a)) / 2;
  return null;
}

function callCells(leg) {
  if (!leg) {
    return "<td>—</td><td>—</td><td>—</td><td>—</td>";
  }
  return `
    <td>${fmtOpt(midOf(leg), 3)}</td>
    <td>${fmtOpt(leg.ask, 3)}</td>
    <td>${fmtOpt(leg.bid, 3)}</td>
    <td>${fmtOpt(leg.last, 3)}</td>
  `;
}

function putCells(leg) {
  if (!leg) {
    return "<td>—</td><td>—</td><td>—</td><td>—</td>";
  }
  return `
    <td>${fmtOpt(leg.bid, 3)}</td>
    <td>${fmtOpt(leg.ask, 3)}</td>
    <td>${fmtOpt(leg.last, 3)}</td>
    <td>${fmtOpt(midOf(leg), 3)}</td>
  `;
}

/** Keep only MONTH cycle expiries for this calendar month + next month. */
function filterNearMonthExpiries(items) {
  const now = new Date();
  const y = now.getFullYear();
  const m = now.getMonth();
  const curKey = `${y}-${String(m + 1).padStart(2, "0")}`;
  const next = new Date(y, m + 1, 1);
  const nextKey = `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, "0")}`;

  const monthly = (items || []).filter((e) => {
    const cycle = String(e.cycle || "").toUpperCase();
    // Prefer explicit MONTH; exclude WEEK / empty weeklies
    if (cycle.includes("WEEK")) return false;
    if (cycle && !cycle.includes("MONTH")) return false;
    const key = String(e.strike_time || "").slice(0, 7);
    return key === curKey || key === nextKey;
  });

  // If cycle field missing, fall back to latest expiry date in each month (usually monthly)
  let list = monthly;
  if (!list.length) {
    const byMonth = new Map();
    for (const e of items || []) {
      const cycle = String(e.cycle || "").toUpperCase();
      if (cycle.includes("WEEK")) continue;
      const key = String(e.strike_time || "").slice(0, 7);
      if (key !== curKey && key !== nextKey) continue;
      const prev = byMonth.get(key);
      if (!prev || e.strike_time > prev.strike_time) byMonth.set(key, e);
    }
    list = [...byMonth.values()];
  }

  list.sort((a, b) => String(a.strike_time).localeCompare(String(b.strike_time)));
  // At most one per month → current + next
  const seen = new Set();
  const out = [];
  for (const e of list) {
    const key = String(e.strike_time).slice(0, 7);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(e);
    if (out.length >= 2) break;
  }
  return out;
}

function renderExpiryTabs(items, activeExpiry) {
  const tabs = document.getElementById("expiryTabs");
  tabs.innerHTML = "";
  items.forEach((ex) => {
    const btn = document.createElement("button");
    btn.type = "button";
    const days = ex.days != null ? ` (${ex.days}d)` : "";
    btn.textContent = `${ex.strike_time}${days}`;
    if (ex.strike_time === activeExpiry) btn.classList.add("active");
    btn.addEventListener("click", () => {
      if (selectedExpiry === ex.strike_time) return;
      selectedExpiry = ex.strike_time;
      loadChain(selectedCode, selectedExpiry);
    });
    tabs.appendChild(btn);
  });
}

function renderChainBoard(data) {
  const titleEl = document.getElementById("optionsTitle");
  const meta = document.getElementById("optionsMeta");
  const empty = document.getElementById("optionsEmpty");
  const wrap = document.getElementById("optionsTableWrap");
  const body = document.getElementById("optionsBody");

  const stock = marketRows.find((r) => r.code === data.underlying);
  const zhName = stock?.name_zh || "";
  const zh = zhName ? ` · ${zhName}` : "";
  // Prefer live market last_price for the spot band / marker
  const spot =
    stock?.last_price != null && !Number.isNaN(Number(stock.last_price))
      ? Number(stock.last_price)
      : data.underlying_price != null
        ? Number(data.underlying_price)
        : null;

  titleEl.textContent = `${data.underlying}${zh}`;
  meta.textContent = `Expiry ${data.expiry || "—"} · Spot ${fmtOpt(spot, 3)} · ±${PRICE_SPREAD} · Updated ${data.updated_at || "—"}`;

  const rows = filterPriceBandRows(data.rows || [], spot, PRICE_SPREAD);
  if (!rows.length) {
    empty.hidden = false;
    empty.textContent = `No option strikes within spot ±${PRICE_SPREAD}.`;
    wrap.hidden = true;
    body.innerHTML = "";
    return;
  }

  empty.hidden = true;
  wrap.hidden = false;
  body.innerHTML = "";

  // Insert spot marker after the last strike that is still ≤ spot
  let markerAfter = -1;
  if (spot != null) {
    for (let i = 0; i < rows.length; i++) {
      if (Number(rows[i].strike) <= spot) markerAfter = i;
      else break;
    }
  }

  const label = zhName || displayCode(data.underlying) || data.underlying;

  rows.forEach((row, idx) => {
    const tr = document.createElement("tr");
    tr.className = "call-side put-side";
    const strike = Number(row.strike);
    tr.innerHTML = `
      ${callCells(row.call)}
      <td class="strike-col">${fmtOpt(strike, 2)}</td>
      ${putCells(row.put)}
    `;
    body.appendChild(tr);

    if (markerAfter === idx) {
      const marker = document.createElement("tr");
      marker.className = "spot-marker";
      marker.innerHTML = `
        <td colspan="${CHAIN_COLSPAN}">
          <div class="spot-marker-inner">
            <span class="spot-marker-line"></span>
            <span class="spot-marker-label">${label}&nbsp;&nbsp;${fmtOpt(spot, 3)}</span>
            <span class="spot-marker-line"></span>
          </div>
        </td>
      `;
      body.appendChild(marker);
    }
  });

  // Spot below all strikes (deep ITM puts only) — still show marker at bottom
  if (spot != null && markerAfter === rows.length - 1) {
    /* already inserted after last row */
  } else if (spot != null && markerAfter < 0) {
    // Spot below the lowest strike — marker on top
    const marker = document.createElement("tr");
    marker.className = "spot-marker";
    marker.innerHTML = `
      <td colspan="${CHAIN_COLSPAN}">
        <div class="spot-marker-inner">
          <span class="spot-marker-line"></span>
          <span class="spot-marker-label">${label}&nbsp;&nbsp;${fmtOpt(spot, 3)}</span>
          <span class="spot-marker-line"></span>
        </div>
      </td>
    `;
    body.insertBefore(marker, body.firstChild);
  }
}

/** Convert DB option_market_data rows into chain board shape. */
function dbRowsToChain(code, dbRows) {
  const byStrike = new Map();
  let underlyingPrice = null;
  let expiry = null;
  let updated = null;
  for (const r of dbRows) {
    underlyingPrice = r.underlying_price ?? underlyingPrice;
    expiry = r.expiry || expiry;
    updated = r.quote_time || updated;
    const k = Number(r.strike_price);
    if (!byStrike.has(k)) byStrike.set(k, { strike: k, call: null, put: null });
    const cell = byStrike.get(k);
    const leg = {
      bid: r.bid_price,
      ask: r.ask_price,
      last: r.last_price,
      mid: r.mid_price,
      volume: r.volume,
      iv: r.iv,
      change_pct: r.change_pct,
    };
    if (String(r.option_type).toUpperCase() === "CALL") cell.call = leg;
    else if (String(r.option_type).toUpperCase() === "PUT") cell.put = leg;
  }
  return {
    underlying: code,
    underlying_price: underlyingPrice,
    expiry,
    updated_at: updated,
    rows: [...byStrike.values()].sort((a, b) => a.strike - b.strike),
  };
}

async function fetchJson(url) {
  const res = await fetch(url);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

async function loadChain(code, expiry) {
  const seq = ++optionsLoadSeq;
  const meta = document.getElementById("optionsMeta");
  meta.textContent = `Loading ${code} · ${expiry}…`;
  try {
    const data = await fetchJson(
      `/api/chain?underlying=${encodeURIComponent(code)}&expiry=${encodeURIComponent(expiry)}`
    );
    if (seq !== optionsLoadSeq) return;
    renderExpiryTabs(expirations, expiry);
    renderChainBoard(data);
  } catch (err) {
    if (seq !== optionsLoadSeq) return;
    // Fallback to cached DB rows
    try {
      const cached = await fetchJson(
        `/api/market/options?underlying=${encodeURIComponent(code)}`
      );
      if (seq !== optionsLoadSeq) return;
      const rows = (cached.rows || []).filter(
        (r) => !expiry || String(r.expiry).slice(0, 10) === String(expiry).slice(0, 10)
      );
      if (rows.length) {
        renderExpiryTabs(expirations, expiry);
        renderChainBoard(dbRowsToChain(code, rows.length ? rows : cached.rows));
        meta.textContent += " · (cached)";
        return;
      }
    } catch (_) {
      /* ignore */
    }
    clearOptionsPanel(String(err.message || err));
    document.getElementById("optionsTitle").textContent = code;
  }
}

async function loadOptionsFor(code) {
  const seq = ++optionsLoadSeq;
  if (!code) {
    clearOptionsPanel();
    return;
  }
  const stock = marketRows.find((r) => r.code === code);
  const zh = stock?.name_zh ? ` · ${stock.name_zh}` : "";
  document.getElementById("optionsTitle").textContent = `${code}${zh}`;
  document.getElementById("optionsMeta").textContent = "Loading expiries…";
  document.getElementById("expiryTabs").innerHTML = "";
  document.getElementById("optionsEmpty").hidden = false;
  document.getElementById("optionsEmpty").textContent =
    "Loading option chain (spot ±10)…";
  document.getElementById("optionsTableWrap").hidden = true;

  try {
    const expData = await fetchJson(
      `/api/expirations?underlying=${encodeURIComponent(code)}`
    );
    if (seq !== optionsLoadSeq) return;
    const allExpiries = (expData.expirations || []).map((e) => ({
      strike_time: String(e.strike_time).slice(0, 10),
      days: e.days,
      cycle: e.cycle,
    }));
    // Current month + next month only (no weeklies)
    expirations = filterNearMonthExpiries(allExpiries);
    if (!expirations.length) {
      // try DB cache only
      const cached = await fetchJson(
        `/api/market/options?underlying=${encodeURIComponent(code)}`
      );
      if (seq !== optionsLoadSeq) return;
      if (cached.rows && cached.rows.length) {
        const exSet = [...new Set(cached.rows.map((r) => String(r.expiry).slice(0, 10)))];
        expirations = filterNearMonthExpiries(
          exSet.map((e) => ({ strike_time: e, days: null, cycle: "MONTH" }))
        );
        if (!expirations.length) {
          expirations = exSet.slice(0, 2).map((e) => ({
            strike_time: e,
            days: null,
            cycle: "MONTH",
          }));
        }
        selectedExpiry = expirations[0].strike_time;
        renderExpiryTabs(expirations, selectedExpiry);
        renderChainBoard(dbRowsToChain(code, cached.rows));
        return;
      }
      clearOptionsPanel("No monthly option expiries for this stock.");
      document.getElementById("optionsTitle").textContent = `${code}${zh}`;
      return;
    }

    if (!selectedExpiry || !expirations.some((e) => e.strike_time === selectedExpiry)) {
      selectedExpiry = expirations[0].strike_time;
    }
    renderExpiryTabs(expirations, selectedExpiry);
    await loadChain(code, selectedExpiry);
  } catch (err) {
    if (seq !== optionsLoadSeq) return;
    // DB fallback
    try {
      const cached = await fetchJson(
        `/api/market/options?underlying=${encodeURIComponent(code)}`
      );
      if (seq !== optionsLoadSeq) return;
      if (cached.rows && cached.rows.length) {
        const exSet = [...new Set(cached.rows.map((r) => String(r.expiry).slice(0, 10)))];
        expirations = exSet.map((e) => ({ strike_time: e, days: null, cycle: "" }));
        selectedExpiry = expirations[0].strike_time;
        renderExpiryTabs(expirations, selectedExpiry);
        renderChainBoard(dbRowsToChain(code, cached.rows));
        return;
      }
    } catch (_) {
      /* ignore */
    }
    clearOptionsPanel(String(err.message || err));
    document.getElementById("optionsTitle").textContent = `${code}${zh}`;
  }
}

async function loadMarket({ refresh = false } = {}) {
  const status = document.getElementById("status");
  const btn = document.getElementById("btnRefresh");
  btn.disabled = true;
  status.textContent = refresh ? "Refreshing from OpenD…" : "Loading…";
  try {
    const url = refresh
      ? "/api/market/favourites?refresh=1"
      : "/api/market/favourites";
    const res = await fetch(url);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || res.statusText);
    renderRows(data.rows || []);
    const n = (data.rows || []).length;
    const extra = data.refreshed
      ? ` · updated ${data.ok_count || 0} quotes` +
        (data.ma_ok != null ? `, ${data.ma_ok} MAs` : "")
      : "";
    status.textContent = `${n} favourites${extra}`;
  } catch (err) {
    status.textContent = String(err.message || err);
  } finally {
    btn.disabled = false;
  }
}

document.getElementById("btnRefresh").addEventListener("click", () => {
  loadMarket({ refresh: true });
});

loadMarket();
