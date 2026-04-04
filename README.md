# FreelanceCFO

AI-powered financial management for UK freelancers. Handles transaction tracking, invoicing, UK tax estimation, cash flow forecasting, and an AI CFO assistant.

---

## Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 16, React 19, Tailwind CSS 4, shadcn/ui |
| Backend | FastAPI, SQLAlchemy 2.0 (async), Alembic |
| Database | PostgreSQL 15 (multi-tenant schema isolation) |
| Queue | Celery 5 + Redis 7 (redbeat for persistent schedule) |
| AI | Google Gemini 2.5 Flash-Lite |
| Payments | Stripe Connect |
| Email | SendGrid |
| Storage | AWS S3 (invoice PDFs) |
| Bot | Telegram |
| Proxy | nginx |

---

## Local Development

### Prerequisites
- Docker + Docker Compose
- Git

### Setup

```bash
git clone https://github.com/anmoldp/freelancecfo.git
cd freelancecfo

# Create your local env file
cp .env.example .env
# Edit .env — at minimum set SECRET_KEY and ENCRYPTION_KEY (see comments in file)

# Start all services
docker compose up
```

Services:

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |
| Flower (Celery) | http://localhost:5555 |
| pgAdmin | http://localhost:5050 |
| Redis Commander | http://localhost:8081 |

### Run tests

```bash
cd backend
pip install -r requirements.txt
pytest tests/ -v --cov=app
```

---

## Production Deployment

Deployment is automated via GitHub Actions on push to `main`:
1. Tests run (must pass ≥80% coverage)
2. Docker images built and pushed to GitHub Container Registry (GHCR)
3. EC2 pulls new images and restarts services

### One-time EC2 setup

```bash
# SSH in
ssh -i your-key.pem ubuntu@YOUR_EC2_IP

# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker ubuntu
newgrp docker
sudo apt-get install -y docker-compose-plugin

# Clone repo
git clone https://github.com/anmoldp/freelancecfo.git
cd freelancecfo

# Create prod env file
cp .env.example .env.prod
nano .env.prod   # fill in all values

# Create backups directory
mkdir -p backups
```

### Required GitHub Secrets

Go to repo → Settings → Secrets and variables → Actions:

| Secret | Value |
|--------|-------|
| `EC2_HOST` | EC2 public IP (e.g. `13.53.56.157`) |
| `EC2_USER` | SSH username (e.g. `ubuntu`) |
| `EC2_SSH_KEY` | Full contents of your `.pem` key file |
| `GHCR_TOKEN` | GitHub PAT with `read:packages` scope |

Create the PAT at: github.com/settings/tokens → Generate new token (classic) → tick `read:packages`.

### EC2 Security Group — required inbound rules

| Port | Source | Purpose |
|------|--------|---------|
| 80 | 0.0.0.0/0 | HTTP (nginx) |
| 22 | Your IP only | SSH |

Ports 3000, 8000, 5432, 6379 must **not** be open publicly.

### Required `.env.prod` values

```env
POSTGRES_USER=freelancecfo
POSTGRES_PASSWORD=<strong password>
POSTGRES_DB=freelancecfo_db
DATABASE_URL=postgresql+asyncpg://freelancecfo:<password>@db:5432/freelancecfo_db
REDIS_URL=redis://redis:6379/0
SECRET_KEY=<python3 -c "import secrets; print(secrets.token_hex(32))">
ENCRYPTION_KEY=<python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
ENVIRONMENT=production
FRONTEND_URL=http://YOUR_EC2_IP
GITHUB_OWNER=anmoldp
GEMINI_API_KEY=
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
SENDGRID_API_KEY=
TELEGRAM_BOT_TOKEN=
AWS_S3_BUCKET=
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
```

### Deploy

```bash
git push origin main
# Watch progress at: github.com/anmoldp/freelancecfo/actions
```

### Verify

```bash
curl http://YOUR_EC2_IP/health
# → {"status":"ok","service":"freelancecfo-api"}
```

---

## Database Backups

Daily pg_dump runs automatically in the `backup` container. Files land at `./backups/backup_YYYYMMDD_HHMMSS.sql.gz` on the EC2 host. Last 7 days are kept.

To restore:

```bash
gunzip -c backups/backup_20260404_090000.sql.gz | \
  docker compose -f docker-compose.prod.yml exec -T db \
  psql -U freelancecfo freelancecfo_db
```

---

## Architecture

```
Browser / Telegram
      │
      ▼
   nginx :80
   ├── /          → frontend:3000  (Next.js)
   ├── /api/      → app:8000       (FastAPI)
   └── /ws/       → app:8000       (WebSocket)
         │
         ├── PostgreSQL (multi-tenant schemas)
         ├── Redis (pub/sub, Celery broker, token blacklist)
         └── Celery workers (CSV/PDF parsing, invoice email, scheduled tasks)
```

### Multi-tenancy

Each user gets a private PostgreSQL schema (`tenant_{uuid}`). All transaction, invoice, tax, and forecast data is isolated per user at the schema level.

---

## API Reference

Interactive docs available at `http://localhost:8000/docs` (dev) or via SSH tunnel in prod.

Key endpoints:

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/auth/register` | Register (5/min rate limit) |
| POST | `/api/v1/auth/login` | Login (10/min rate limit) |
| GET | `/api/v1/transactions` | List transactions (paginated) |
| POST | `/api/v1/transactions/import/csv` | Async CSV import |
| POST | `/api/v1/invoices` | Create invoice |
| POST | `/api/v1/invoices/{id}/send` | Send invoice by email |
| GET | `/api/v1/tax/estimate` | UK Self Assessment estimate |
| GET | `/api/v1/forecast/cashflow` | 13-week cash flow projection |
| POST | `/api/v1/cfo/chat` | AI CFO assistant |
| WS | `/ws/cfo/chat` | Streaming CFO chat |
| WS | `/ws/payments` | Real-time payment notifications |
