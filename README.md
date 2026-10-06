# Futu HK Market Data (Level 1)

Python client for **Hong Kong stocks**, **HK options**, and **HSI index** quotes via [Futu OpenAPI](https://openapi.futunn.com/). Designed for **Level 1 (LV1)** subscription on **Windows**.

## Architecture

```text
Your Python script  -->  OpenD (local gateway)  -->  Futu servers
                         (login here)
```

- **OpenD** must be installed, running, and logged in before you run this project.
- This script connects to OpenD at `127.0.0.1:11111`; it does not send your password over the API.
- Credentials in `config/config.yaml` are for your reference and for configuring OpenD; store them only locally.

## Setup (Windows)

### 1. Install OpenD

1. Download [OpenD for Windows](https://www.futunn.com/download/openAPI?lang=en-US).
2. Install and open **FutuOpenD** (visual mode is easiest).
3. Log in with your **Futu ID** and **password**.
4. Confirm the API port is **11111** (default).

### 2. Python environment

From the project folder in PowerShell or Cursor terminal:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. Configuration

```powershell
copy config\config.example.yaml config\config.yaml
copy config\symbols.example.yaml config\symbols.yaml
```

Edit `config/config.yaml`:

- `account.user_id` — your Futu / Futubull ID  
- `account.password` — your login password (for OpenD; kept local, gitignored)

Edit `config/symbols.yaml`:

| Section      | Example        | Description              |
|-------------|----------------|--------------------------|
| `hk_stocks` | `HK.00700`     | HK listed stocks         |
| `indices`   | `HK.800000`    | Hang Seng Index (HSI)    |
| `hk_options`| `HK.HSI260330C24000000` | Full option contract code |

Find option codes in the Futu app or via `get_option_chain` in the API.

## Run

```powershell
# Real-time push (default, 30 seconds)
python main.py --mode stream --seconds 60

# One-shot snapshot (no subscription quota used for streaming)
python main.py --mode snapshot

# Poll subscribed quotes every 5 seconds
python main.py --mode poll --poll-interval 5 --seconds 120
```

## Use as a class elsewhere

```python
from src.futu_market_data import FutuMarketDataClient

with FutuMarketDataClient() as client:
    client.subscribe()
    ret, df = client.get_snapshots()
    if ret == 0:
        print(df[["code", "last_price", "update_time"]])
```

## Option chain web UI (auto-update)

Live **call | strike | put** board in the browser (like Futubull options chain). **Quote only — no trading.**

```powershell
# OpenD running + logged in, then:
pip install -r requirements.txt
py run_web.py
```

Open **http://127.0.0.1:8080**

- Default underlying: `HK.00823` (Link REIT / 領展) — change in the top bar
- Click expiry tabs (e.g. `11/27`)
- Auto-refresh every 5 seconds (adjustable)

Examples: `HK.00700` (Tencent), `HK.00823` (Link REIT)

## Option Greeks (IV, delta, gamma, vega, theta, rho)

Greeks come from `get_market_snapshot` / live quote after you have a valid option contract code.

```powershell
py scripts/get_option_prices.py HK.00700 --expiry 2026-05-29 --type CALL --strike 500
```

Output includes `iv`, `delta`, `gamma`, `vega`, `theta`, `rho`, `premium`, and `open_interest` when Futu provides them (HK options LV1+).

## Level 1 notes

- Subscriptions use `SubType.QUOTE` only (basic bid/ask/last; no order book).
- HK market requires **LV1 or above**; BMP-only permission cannot subscribe.
- Each subscribed symbol uses **subscription quota**; check with `query_subscription()`.

## Troubleshooting

| Issue | Action |
|-------|--------|
| Connection refused | Start OpenD and log in |
| Subscribe failed | Check LV1 rights for HK stocks/options in OpenD |
| Invalid code | Use `HK.` prefix, e.g. `HK.00700`, `HK.800000` |
| Config not found | Copy `*.example.yaml` to `config.yaml` / `symbols.yaml` |

## Project layout

```text
config/
  config.example.yaml    # template for account + OpenD host/port
  symbols.example.yaml   # template for stock/option/index lists
src/
  futu_market_data.py    # FutuMarketDataClient class
main.py                  # CLI entry point
requirements.txt
```
