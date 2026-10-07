# Docker — run option chain + MariaDB

OpenD **must stay on Windows** (logged in). Docker runs the **web app** and **MariaDB**.

## Architecture

```text
Browser → Docker: futu-option-chain (:8080)
              → host.docker.internal:11111 → FutuOpenD
              → Docker: futu-db (MariaDB :3306)
```

## Database

| Setting | Value |
|---------|--------|
| Engine | MariaDB 11.4 |
| Container | `futu-db` |
| Database | `futu` |
| User | `mickylee` |
| Password | from `.env` (`MYSQL_PASSWORD`) |
| Host port | `3309` → container `3306` |

Tables: `statements`, `transactions`, `market_quotes`.

### GUI connection (MySQL / MariaDB client)

| Field | Value |
|-------|--------|
| Host | `localhost` |
| Port | **`3309`** |
| Username | `mickylee` |
| Password | same as `.env` |
| Database | `futu` |

### Statement upload & P&L

1. Copy `.env.example` → `.env` and set passwords
2. `docker compose up -d --build`
3. Open **http://localhost:8080/transactions**
4. Upload Futu monthly/daily PDF

## Option chain

OpenD **must stay on Windows** (logged in). Docker only runs the **web frontend + API**.

## Steps (Docker Desktop)

### 1. Start OpenD

Open **FutuOpenD**, log in, confirm **Connected**, port **11111**.

### 2. Config (if not done)

```powershell
cd "c:\Project\Algo Trading\Futu"
copy config\config.example.yaml config\config.yaml
copy .env.example .env
```

### 3. Build and run

```powershell
cd "c:\Project\Algo Trading\Futu"
docker compose up -d --build
```

| Name | Image | Port |
|------|-------|------|
| `futu-db` | `mariadb:11.4` | `3309` |
| `futu-option-chain` | `futu-option-chain:latest` | `8080` |

### 4. Open the frontend

**http://localhost:8080**

### 5. Useful commands

```powershell
docker compose logs -f futu-web
docker compose down
docker compose up -d --build
docker compose run --rm futu-cli 00700
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Container exits immediately | `docker compose logs futu-web` |
| Cannot connect to OpenD | OpenD on host; check `host.docker.internal` |
| Port 3306 in use | Change mapping in `docker-compose.yml` |
| Wrong client type | Use **MySQL/MariaDB**, not PostgreSQL |

## Note

Do **not** put OpenD inside Docker — Futu OpenD is a Windows desktop app.
