# LeanStock — Inventory Management System

Backend built with **FastAPI + SQLModel + PostgreSQL + Redis + Celery**.

## Quick Start (Docker — recommended)

### 1. Copy the environment file
```bash
cp .env.example .env
```

Open `.env` and fill in your email credentials (see "Email setup" below).
Everything else works out of the box with Docker.

### 2. Start everything
```bash
docker compose up --build
```

This starts:
- **PostgreSQL 15** on port 5432
- **Redis 7** on port 6379
- **FastAPI app** on port 8000 (runs `alembic upgrade head` automatically)
- **Celery worker** — processes background jobs (email, decay)
- **Celery beat** — runs scheduled jobs (daily increment, 72h decay)

### 3. Open the API docs
```
http://localhost:8000/docs
```

---

## Email Setup (Gmail)

1. Go to your Google Account → **Security** → **2-Step Verification** → enable it.
2. Go to **App Passwords** → create a new app password for "Mail".
3. Copy the 16-character password.
4. In `.env`:
```
SMTP_USER=your-gmail@gmail.com
SMTP_PASSWORD=abcd efgh ijkl mnop   ← paste here (no spaces needed)
SMTP_FROM=your-gmail@gmail.com
```

---

## Running Tests

Make sure Docker is running first (tests use a real PostgreSQL database):

```bash
# Create the test database
docker exec -it leanstock-db-1 psql -U postgres -c "CREATE DATABASE leanstock_test;"

# Install dependencies locally
pip install -r requirements.txt

# Run tests
pytest tests/ -v
```

---

## API Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/health` | — | Health check |
| POST | `/auth/register` | — | Register + sends verification email |
| GET | `/auth/verify-email/{token}` | — | Verify email |
| POST | `/auth/login` | — | Login, returns JWT tokens |
| POST | `/auth/refresh` | — | Get new access token |
| POST | `/auth/logout` | — | Revoke refresh token |
| POST | `/auth/forgot-password` | — | Send password reset email |
| POST | `/auth/reset-password` | — | Reset password |
| GET | `/auth/me` | Bearer | Get current user |
| GET | `/products` | Bearer | List products (cursor pagination) |
| POST | `/products` | Manager+ | Create product |
| GET | `/products/{id}` | Bearer | Get product |
| PUT | `/products/{id}` | Manager+ | Update product |
| DELETE | `/products/{id}` | Manager+ | Deactivate product |
| GET | `/locations` | Bearer | List locations |
| POST | `/locations` | Manager+ | Create location |
| GET | `/locations/{id}` | Bearer | Get location |
| DELETE | `/locations/{id}` | Manager+ | Deactivate location |
| GET | `/inventory` | Bearer | List inventory (cursor pagination) |
| POST | `/inventory/set` | Manager+ | Set inventory quantity |
| POST | `/inventory/transfer` | Manager+ | Transfer inventory (SELECT FOR UPDATE) |
| GET | `/inventory/transfers` | Bearer | Transfer history |
| GET | `/inventory/dead-stock` | Bearer | Products in inventory >30 days |
| GET | `/admin/users` | Admin | List users in tenant |
| PUT | `/admin/users/{id}/role` | Admin | Promote/demote user |
| GET | `/admin/audit-logs` | Admin | View audit log |
| POST | `/admin/trigger-decay` | Admin | Manually trigger decay job |
| POST | `/admin/trigger-increment-days` | Admin | Manually trigger day counter |

---

## Postman

Import `postman/LeanStock.postman_collection.json` into Postman.
After you log in, the Login endpoint auto-saves the tokens to collection variables,
so all protected requests work immediately.

---

## Architecture

```
app/
├── config.py          # Pydantic Settings — reads .env, fails if SECRET_KEY missing
├── database.py        # SQLModel engine + get_session() dependency
├── main.py            # FastAPI app, CORS, lifespan
├── models/
│   ├── user.py        # Tenant, User, RefreshToken, EmailVerification, PasswordResetToken
│   ├── product.py     # Product (with days_in_inventory, current_discount)
│   └── inventory.py   # Location, Inventory, InventoryTransfer, AuditLog
├── routers/
│   ├── auth.py        # Register/login/logout/refresh/verify/forgot-password/reset
│   ├── products.py    # Product CRUD (tenant-scoped)
│   ├── locations.py   # Location CRUD (tenant-scoped)
│   ├── inventory.py   # Inventory ops + atomic transfer (SELECT FOR UPDATE)
│   └── admin.py       # Admin panel: users, audit logs, manual job triggers
├── core/
│   ├── security.py    # bcrypt + JWT (python-jose)
│   ├── dependencies.py # get_current_user, require_admin, require_manager
│   └── rate_limit.py  # Redis-based rate limiter (5 req/min on auth endpoints)
├── services/
│   └── email_service.py # SMTP email sending (verification, reset, transfer notif)
└── workers/
    ├── celery_app.py  # Celery + Redis broker, beat schedule
    └── tasks.py       # increment_days_in_inventory (daily), dead_stock_decay (72h)
```

### Key Design Decisions

**Multi-tenancy**: Every query filters by `tenant_id`. First user in a new tenant becomes admin automatically.

**SELECT FOR UPDATE**: The transfer endpoint locks the source inventory row so two concurrent transfers can't both read the same quantity and cause overselling.

**Dead stock decay**: Celery beat runs every 72 hours and applies +10% discount (configurable) to any product with `days_in_inventory > 30`, capped at 90%.

**Refresh tokens**: Stored in the database with `is_revoked` flag. Logout sets this flag — no need for a token blacklist in Redis.

**Rate limiting**: Redis increments a counter per IP per minute. If Redis is down, requests are allowed (fail-open — don't lock users out because of infra issues).
