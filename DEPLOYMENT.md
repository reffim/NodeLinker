# NodeLinker – Deployment Guide

## Architecture

```
Browser
  │
  ▼
Nginx :80  ──── /api/* ──────► FastAPI backend :8000
  │                                     │
  │             /ws/*  ──────►  WebSocket  │
  │                                     │
  └── /* (SPA) ──► served from /usr/share/nginx/html
                                         │
                              ┌──────────┴──────────┐
                           PostgreSQL            Redis
                                              ┌────┴────┐
                                        Celery Worker  Beat
```

All external traffic enters through **Nginx** on port 80.  
The backend, database, and Redis are **not** exposed to the host.

---

## Prerequisites

- Docker ≥ 24  
- Docker Compose plugin ≥ 2.20  

---

## Quick Start (Production)

```bash
# 1. Clone the repository
git clone <repo-url>
cd project_nodelinker

# 2. Configure environment
cp .env.example .env
# Edit .env – at minimum set:
#   POSTGRES_PASSWORD  (strong password)
#   JWT_SECRET_KEY     (random 32-byte hex – see below)
python3 -c "import secrets; print(secrets.token_hex(32))"

# 3. Build and start
docker compose up -d --build

# 4. Check health
curl http://localhost/api/health
```

The app will be available at **http://localhost** (or the IP/domain of your server).

---

## Development (Hot-reload)

Use the dev override to mount source code and enable hot-reload:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

This additionally:
- Exposes PostgreSQL on `5432` and Redis on `6379` for direct access
- Exposes the backend on `8000` for API debugging
- Mounts `./backend` into the container for live code reload

For frontend-only development without Docker:

```bash
cd frontend
npm install
npm run dev   # Vite dev server on http://localhost:5173
              # API requests proxied to http://localhost:8000
```

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `POSTGRES_USER` | | `nodelinker` | DB username |
| `POSTGRES_PASSWORD` | **Yes** | — | DB password |
| `POSTGRES_DB` | | `nodelinker` | DB name |
| `DEBUG` | | `false` | Enable debug mode (never true in prod) |
| `HTTP_PORT` | | `80` | Host port Nginx listens on |
| `JWT_SECRET_KEY` | **Yes** | — | Secret for signing JWTs |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | | `15` | Access token lifetime |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | | `7` | Refresh token lifetime |
| `CORS_ORIGINS` | | `["http://localhost:80"]` | Allowed CORS origins (JSON list) |
| `OIDC_ENABLED` | | `false` | Enable OIDC SSO |
| `OIDC_CLIENT_ID` | OIDC only | — | OIDC client ID |
| `OIDC_CLIENT_SECRET` | OIDC only | — | OIDC client secret |
| `OIDC_DISCOVERY_URL` | OIDC only | — | OIDC discovery endpoint |
| `OIDC_REDIRECT_URI` | OIDC only | — | Callback URL (must match provider) |

---

## Production Hardening Checklist

- [ ] `JWT_SECRET_KEY` is a random 32+ byte value (never the default)
- [ ] `POSTGRES_PASSWORD` is a strong, unique password
- [ ] `DEBUG=false`
- [ ] `CORS_ORIGINS` is set to your actual domain(s)
- [ ] Running behind TLS (see below)
- [ ] `.env` is **not** committed to version control (it is in `.gitignore`)

### Adding TLS (HTTPS)

For production, put a TLS terminator in front of Nginx, or configure Nginx directly.

**Option A – Traefik (recommended for Docker):**

Add Traefik labels to the `nginx` service in a `docker-compose.prod.yml` override and let Traefik handle Let's Encrypt certificates.

**Option B – Certbot + Nginx directly:**

1. Obtain a certificate with Certbot.
2. Mount the cert into the `nginx` service.
3. Update `nginx/nginx.conf` to add an `ssl` server block and redirect HTTP → HTTPS.

---

## Database Migrations

Migrations run automatically on backend startup (`alembic upgrade head`).

To run manually:

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend alembic revision --autogenerate -m "description"
```

---

## Useful Commands

```bash
# View logs
docker compose logs -f backend
docker compose logs -f nginx

# Open a backend shell
docker compose exec backend bash

# Run a database shell
docker compose exec db psql -U nodelinker nodelinker

# Scale Celery workers
docker compose up -d --scale celery-worker=3

# Restart a single service
docker compose restart backend

# Stop everything and remove volumes (DATA LOSS)
docker compose down -v
```

---

## Secrets Management

For production deployments with secrets managers (Vault, AWS Secrets Manager, etc.):

1. Inject secrets as environment variables at runtime.
2. Do **not** bake secrets into Docker images.
3. Use Docker Secrets or a secrets manager sidecar if running on Docker Swarm or Kubernetes.

The `.env` file pattern is suitable for single-host deployments where the file is protected by OS-level permissions (`chmod 600 .env`).
