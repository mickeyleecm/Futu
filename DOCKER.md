# Docker — run option chain + PostgreSQL

OpenD **must stay on Windows** (logged in). Docker runs the **web app** and **PostgreSQL**.

## Architecture

```text
Browser → Docker: futu-option-chain (:8080)
              → host.docker.internal:11111 → FutuOpenD
              → Docker: futu-db (PostgreSQL :5432)
```

## Database

| Setting | Value |
|---------|--------|
| Container | `futu-db` |
| Database | `futu` |
| User | `mickylee` |
| Password | `Mn12345678` |
| Host port | `5432` |

Tables: `statements`, `transactions`, `market_quotes`.

### Statement upload & P&L

1. `docker compose up -d --build`
2. Open **http://localhost:8080/transactions**
3. Upload Futu monthly/daily PDF
4. Filter by date to view trades and P&L by product type

## Option chain

OpenD **must stay on Windows** (logged in). Docker only runs the **web frontend + API**.

## Architecture (quotes)

```text
Browser → Docker container (futu-option-chain :8080)
              → host.docker.internal:11111 → FutuOpenD on desktop
```

## Steps (Docker Desktop)

### 1. Start OpenD

Open **FutuOpenD**, log in, confirm **Connected**, port **11111**.

### 2. Config (if not done)

```powershell
cd "c:\Project\Algo Trading\Futu"
copy config\config.example.yaml config\config.yaml
```

### 3. Build and run container

```powershell
cd "c:\Project\Algo Trading\Futu"
docker compose up -d --build
```

In **Docker Desktop → Containers** you will see:

| Name | Image | Port |
|------|-------|------|
| `futu-option-chain` | `futu-option-chain:latest` | `8080` |

### 4. Open the frontend

**http://localhost:8080**

Set underlying (e.g. `HK.00700`), click **Load**, pick an expiry tab. Auto-update runs every 5 seconds.

### 5. Useful commands

```powershell
# View logs
docker compose logs -f futu-web

# Stop container
docker compose down

# Rebuild after code changes
docker compose up -d --build

# One-off stock price in container (optional)
docker compose run --rm futu-cli 00700
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Container exits immediately | `docker compose logs futu-web` — often OpenD not reachable |
| Cannot connect to OpenD | OpenD on host; check `host.docker.internal` works on Docker Desktop |
| Port 8080 in use | Change in `docker-compose.yml`: `"8090:8080"` and open `localhost:8090` |
| Config not found | Ensure `config/config.yaml` exists on host (mounted into container) |

## Note

Do **not** put OpenD inside Docker — Futu OpenD is a Windows desktop app. Only the Python web app runs in the container.
