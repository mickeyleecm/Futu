const intervalInput = document.getElementById("interval");
const autoRefreshInput = document.getElementById("autoRefresh");
const statusEl = document.getElementById("status");
const expiryTabs = document.getElementById("expiryTabs");
const chainBody = document.getElementById("chainBody");
const underlyingTitle = document.getElementById("underlyingTitle");
const metaEl = document.getElementById("meta");
const stockListEl = document.getElementById("stockList");
const indexListEl = document.getElementById("indexList");
const selectedStockEl = document.getElementById("selectedStock");

let selectedUnderlying = null;
let selectedExpiry = null;
let timer = null;

function fmt(v, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return Number(v).toFixed(digits);
}

function fmtPct(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const n = Number(v);
  const cls = n > 0 ? "up" : n < 0 ? "down" : "";
  return `<span class="${cls}">${n >= 0 ? "+" : ""}${n.toFixed(2)}%</span>`;
}

function fmtOi(v) {
  if (v === null || v === undefined) return "—";
  return `${Math.round(v)}`;
}

function legCells(leg, side) {
  if (!leg) {
    const n = side === "call" ? 9 : 10;
    return Array(n).fill("<td>—</td>").join("");
  }
  if (side === "call") {
    return `
      <td>${fmt(leg.delta, 3)}</td>
      <td>${fmt(leg.iv, 2)}%</td>
      <td>${fmtOi(leg.open_interest)}</td>
      <td>${fmtOi(leg.volume)}</td>
      <td>${fmtPct(leg.change_pct)}</td>
      <td>${fmt(leg.mid, 3)}</td>
      <td>${fmt(leg.ask, 3)}</td>
      <td>${fmt(leg.bid, 3)}</td>
      <td>${fmt(leg.last, 3)}</td>
    `;
  }
  return `
    <td>${fmt(leg.bid, 3)}</td>
    <td>${fmt(leg.ask, 3)}</td>
    <td>${fmt(leg.mid, 3)}</td>
    <td>${fmt(leg.last, 3)}</td>
    <td>${fmtPct(leg.change_pct)}</td>
    <td>${fmtOi(leg.volume)}</td>
    <td>${fmtOi(leg.open_interest)}</td>
    <td>${fmt(leg.iv, 2)}%</td>
    <td>${fmt(leg.delta, 3)}</td>
    <td>${fmt(leg.gamma, 4)}</td>
  `;
}

function setStatus(text, isError = false) {
  statusEl.textContent = text;
  statusEl.style.color = isError ? "#ff4d4f" : "";
}

async function fetchJson(url) {
  const res = await fetch(url);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

function renderChain(data) {
  underlyingTitle.textContent = `${data.underlying_name || data.underlying}  ${fmt(data.underlying_price, 3)}`;
  metaEl.textContent = `Expiry ${data.expiry} · Updated ${data.updated_at || "—"}`;

  const up = data.underlying_price;
  let markerAfter = null;
  if (up != null && data.rows.length) {
    for (let i = 0; i < data.rows.length; i++) {
      const s = data.rows[i].strike;
      const next = data.rows[i + 1]?.strike;
      if (s <= up && (next == null || up < next)) {
        markerAfter = i;
        break;
      }
    }
  }

  chainBody.innerHTML = "";
  if (!data.rows.length) {
    chainBody.innerHTML = `<tr><td colspan="20" class="muted" style="text-align:center;padding:16px">
      No option data for this expiry
    </td></tr>`;
    return;
  }

  data.rows.forEach((row, idx) => {
    const tr = document.createElement("tr");
    tr.className = "call-side put-side";
    if (row.strike === up) tr.classList.add("atm");
    tr.innerHTML = `
      ${legCells(row.call, "call")}
      <td class="strike-col">${fmt(row.strike, 2)}</td>
      ${legCells(row.put, "put")}
    `;
    chainBody.appendChild(tr);
    if (markerAfter === idx) {
      const marker = document.createElement("tr");
      marker.className = "underlying-marker";
      marker.innerHTML = `<td colspan="20" class="muted" style="text-align:center;padding:4px">
        Underlying ${fmt(up, 3)}
      </td>`;
      chainBody.appendChild(marker);
    }
  });
}

function buildListItem(item, onSelect) {
  const li = document.createElement("li");
  li.className = "stock-item";
  li.dataset.code = item.code;
  const name = item.name ? `<span class="stock-name">${item.name}</span>` : "";
  const price =
    item.last_price != null
      ? `<span class="stock-price">${fmt(item.last_price, 3)}</span>`
      : "";
  li.innerHTML = `
    <span class="stock-code">${item.display}</span>
    ${name}
    ${price}
  `;
  li.addEventListener("click", () => onSelect(item.code));
  return li;
}

function highlightSelection(code) {
  document.querySelectorAll(".stock-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.code === code);
  });
}

async function selectUnderlying(code) {
  selectedUnderlying = code;
  selectedExpiry = null;
  highlightSelection(code);
  selectedStockEl.textContent = code;
  selectedStockEl.classList.remove("muted");

  expiryTabs.innerHTML = "";
  chainBody.innerHTML = "";
  underlyingTitle.textContent = "Loading…";
  metaEl.textContent = "";

  setStatus(`Loading options for ${code}…`);
  try {
    const data = await fetchJson(`/api/expirations?underlying=${encodeURIComponent(code)}`);
    expiryTabs.innerHTML = "";
    data.expirations.forEach((ex) => {
      const btn = document.createElement("button");
      const label = ex.days != null ? `${ex.strike_time} (${ex.days}d)` : ex.strike_time;
      btn.textContent = label;
      btn.dataset.expiry = ex.strike_time;
      btn.addEventListener("click", () => selectExpiry(ex.strike_time));
      expiryTabs.appendChild(btn);
    });
    if (data.expirations.length) {
      selectExpiry(data.expirations[0].strike_time);
    } else {
      setStatus("No option expirations for this symbol", true);
      underlyingTitle.textContent = code;
    }
  } catch (e) {
    setStatus(e.message, true);
  }
}

async function loadChain() {
  if (!selectedExpiry || !selectedUnderlying) return;
  setStatus(`Updating ${selectedUnderlying}…`);
  try {
    const data = await fetchJson(
      `/api/chain?underlying=${encodeURIComponent(selectedUnderlying)}&expiry=${encodeURIComponent(selectedExpiry)}`
    );
    renderChain(data);
    setStatus(`Live · ${new Date().toLocaleTimeString()}`);
  } catch (e) {
    setStatus(e.message, true);
  }
}

function selectExpiry(expiry) {
  selectedExpiry = expiry;
  expiryTabs.querySelectorAll("button").forEach((b) => {
    b.classList.toggle("active", b.dataset.expiry === expiry);
  });
  loadChain();
  scheduleTimer();
}

function scheduleTimer() {
  if (timer) clearInterval(timer);
  if (!autoRefreshInput.checked || !selectedUnderlying) return;
  const sec = Math.max(2, Number(intervalInput.value) || 5);
  timer = setInterval(loadChain, sec * 1000);
}

async function loadSymbolLists() {
  const data = await fetchJson("/api/symbols");
  stockListEl.innerHTML = "";
  indexListEl.innerHTML = "";

  data.hk_stocks.forEach((item) => {
    stockListEl.appendChild(buildListItem(item, selectUnderlying));
  });
  data.indices.forEach((item) => {
    indexListEl.appendChild(buildListItem(item, selectUnderlying));
  });

  document.querySelector(".indices-title").style.display =
    data.indices.length ? "" : "none";
  indexListEl.style.display = data.indices.length ? "" : "none";

  const first = data.hk_stocks[0]?.code || data.indices[0]?.code;
  if (first) {
    await selectUnderlying(first);
  }
}

async function init() {
  try {
    const health = await fetchJson("/api/health");
    setStatus(`OpenD ${health.opend}`);
    await loadSymbolLists();
  } catch (e) {
    setStatus(`Cannot reach server: ${e.message}`, true);
  }
}

autoRefreshInput.addEventListener("change", scheduleTimer);
intervalInput.addEventListener("change", scheduleTimer);

init();
