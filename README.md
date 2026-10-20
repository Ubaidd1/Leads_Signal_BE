# Hiring Intelligence — Backend

FastAPI + PostgreSQL backend for the Hiring Intelligence Next.js app (`../hiring-intelligence-nextjs-tailwind-only`).

**Status: Phase 1 (foundation) complete.** Authentication, sessions, workspaces/memberships/invitations, profile and workspace settings, onboarding preferences, lead and company reads (filters, sorting, pagination), and saved leads. The frontend still runs on fixtures until Phase 2 wires it to this API. See [docs/AUDIT.md](docs/AUDIT.md) for the audit, feature inventory, and phase plan.

## Stack

Python 3.11 · FastAPI · SQLAlchemy 2.1 (sync, psycopg 3) · Alembic · Pydantic v2 / pydantic-settings · Argon2 (argon2-cffi) · Pytest + HTTPX · Ruff

## Layout

```text
app/
  main.py                 app factory, middleware (request ID, logging, security headers, origin check), /health, /ready
  api/deps.py             DB session, session/CSRF resolution, RequestContext, cookies, paging
  api/v1/endpoints/       auth, me, workspace, leads, companies
  core/                   config, security (hashing/tokens), permissions, exceptions, logging, request context
  db/                     declarative base, engine/session
  models/                 SQLAlchemy models (one module per area)
  schemas/                Pydantic request/response models (camelCase JSON)
  repositories/catalog.py tenant-scoped lead/company queries
  services/               auth, workspaces, users, catalog, audit, rate limiting
  integrations/email.py   email adapter (console = development only)
alembic/                  migrations
scripts/seed_demo.py      idempotent demo seed
tests/                    api/ and services/ tests (dedicated *_test database)
docs/AUDIT.md             audit, feature inventory, decisions, phases
```

## Setup

```bash
python3.11 -m venv env && source env/bin/activate
pip install -r requirements.txt
cp .env.example .env                      # then set real DATABASE_URL / TEST_DATABASE_URL
```

Create two databases, one for development and one for tests. **Use UTF-8.** The current local cluster was initialised as `SQL_ASCII` (see *Known issues*).

```sql
CREATE DATABASE hiring_intelligence      OWNER hiring_user ENCODING 'UTF8' TEMPLATE template0;
CREATE DATABASE hiring_intelligence_test OWNER hiring_user ENCODING 'UTF8' TEMPLATE template0;
```

## Commands

| Task | Command |
|---|---|
| Apply migrations | `alembic upgrade head` |
| New migration | `alembic revision --autogenerate -m "..."` (review it; remove duplicated `CheckConstraint` lines that autogenerate emits for enum columns) |
| Detect model/migration drift | `alembic check` |
| Seed demo data (dev only) | `python -m scripts.seed_demo` (set `DEMO_USER_PASSWORD`, or one is generated and printed once) |
| Run API | `uvicorn app.main:app --reload --port 8000` |
| Tests | `pytest` |
| Lint / format | `ruff check . && ruff format --check .` |
| OpenAPI | `http://localhost:8000/docs` and `/api/v1/openapi.json` (disabled in production) |

Tests refuse to run unless `TEST_DATABASE_URL` points at a database whose name ends in `_test`. The suite downgrades the test DB to `base`, upgrades it to `head` (exercising the migrations), and runs each test inside a rolled-back transaction.

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `ENVIRONMENT` | `development` | `development` \| `test` \| `production`. Production refuses insecure cookies and the console email adapter. |
| `DATABASE_URL` | — (required) | `postgresql+psycopg://user:pass@host:5432/db` |
| `TEST_DATABASE_URL` | — | Tests only; DB name must end in `_test`. |
| `FRONTEND_BASE_URL` | `http://localhost:3000` | Used to build reset/invitation links. |
| `TRUSTED_ORIGINS` | `http://localhost:3000` | Comma-separated. Origin allowlist for state-changing requests, and the CORS allowlist. |
| `COOKIE_SECURE` | `false` | Must be `true` in production (HTTPS). |
| `COOKIE_SAMESITE` | `lax` | `lax` \| `strict` \| `none` (`none` requires secure). |
| `COOKIE_DOMAIN` | unset | Leave unset for same-origin deployment. |
| `SESSION_IDLE_TIMEOUT_MINUTES` | `720` | Sliding idle timeout (non-"remember me" sessions). |
| `SESSION_ABSOLUTE_TIMEOUT_HOURS` | `24` | Hard expiry for normal sessions. |
| `SESSION_REMEMBER_ME_DAYS` | `30` | Hard expiry for "remember me" sessions. |
| `ALLOW_REGISTRATION` | `true` | `false` → invitation-only onboarding. |
| `EMAIL_BACKEND` | `console` | Only `console` exists (logs, does not deliver). A real provider is required before production. |
| `LOG_LEVEL` | `INFO` | JSON logs to stdout with `request_id`. |

Rate limits, token lifetimes, and page sizes are also settings (see `app/core/config.py`).

## Authentication and authorization

- **Passwords:** Argon2id (argon2-cffi defaults), minimum 10 characters, maximum 256. Hashes are rehashed on login when parameters change. Login for an unknown email still runs a dummy verification, so response timing does not reveal accounts.
- **Sessions:** an opaque 256-bit token goes in the `hi_session` cookie (`HttpOnly`, `SameSite=lax`, `Secure` in production). Only its SHA-256 digest is stored in `auth_sessions`. There is an idle timeout plus an absolute expiry, and "remember me" makes the cookie persistent with a longer expiry. Login always issues a new session. Logout revokes the session server-side. A password change revokes all *other* sessions; a password reset revokes *all* sessions. Deactivated users are rejected on every request.
- **CSRF:** synchronizer token. Every session has a `csrfToken`, returned by login, register, and `GET /auth/session`. The client keeps it in memory (never `localStorage`) and sends it as `X-CSRF-Token` on POST/PUT/PATCH/DELETE. Separately, any state-changing request whose `Origin` header is not in `TRUSTED_ORIGINS` is rejected (this covers login CSRF).
- **Rate limiting:** PostgreSQL-backed fixed windows, shared across processes. Login: 10 per 5 minutes per email and 50 per IP. Registration: 10 per IP. Password reset: 5 per 15 minutes per email and 20 per IP. Responses are `429` with `Retry-After`.
- **Password reset:** the response is always `202` with the same message. Tokens are single-use, valid for 30 minutes, stored as digests, and only the newest one is valid.
- **Tenancy:** the acting workspace comes from the session (`active_workspace_id`), and membership is re-validated on **every** request. Clients never send a workspace ID on data endpoints; switching workspaces (`PUT /auth/session/workspace`) checks membership. Leads, companies, and hiring signals use `workspace_id IS NULL` for the shared catalogue and a workspace ID for private rows. Every catalogue query filters with `workspace_id IS NULL OR workspace_id = :current`. Records from another workspace return `404`, never `403`, so their existence is not leaked.
- **Roles:**

| Permission | member | admin | owner |
|---|:-:|:-:|:-:|
| View members, save leads, saved searches*, create exports* | ✓ | ✓ | ✓ |
| Update workspace settings, invite/remove/re-role members, manage integrations* and data sources* | | ✓ | ✓ |
| Grant, revoke, or remove the owner role | | | ✓ |

\* Enforced once those features land. A workspace always keeps at least one owner. Any member may leave.

- **Audit log** (`audit_events`): register, login, failed login, logout, password change/reset, profile and email changes, workspace updates, role changes, member removal, invitation create/revoke/accept, lead save/unsave.

## API (Phase 1)

All endpoints are under `/api/v1` and use camelCase JSON. Errors always look like `{"error": {"code", "message", "details?"}}`, with codes `NOT_AUTHENTICATED`, `INVALID_CREDENTIALS`, `PERMISSION_DENIED`, `CSRF_FAILED`, `ORIGIN_NOT_ALLOWED`, `RESOURCE_NOT_FOUND`, `VALIDATION_ERROR`, `CONFLICT`/`EMAIL_TAKEN`/`LAST_OWNER`/…, `RATE_LIMITED`, and `INTERNAL_ERROR`. Full schemas are in OpenAPI at `/docs`.

| Method | Path | Auth | Request → Response |
|---|---|---|---|
| POST | `/auth/register` | — | `{email, password, fullName, workspaceName}` → `201 Session` + cookie |
| POST | `/auth/login` | — | `{email, password, rememberMe?}` → `Session` + cookie |
| POST | `/auth/logout` | session | → `204`, cookie cleared |
| GET | `/auth/session` | session | → `Session {user, workspace{id,name,role,isDemo}, permissions[], csrfToken, expiresAt}` |
| PUT | `/auth/session/workspace` | session | `{workspaceId}` → `Session` |
| POST | `/auth/password-reset/request` | — | `{email}` → `202 {message}` |
| POST | `/auth/password-reset/confirm` | — | `{token, newPassword}` → `204` |
| POST | `/auth/invitations/accept` | optional | `{token, fullName?, password?}` → `{workspaceId, signedIn}` (+ cookie for new accounts) |
| GET / PATCH | `/me` | session | `{fullName?, jobTitle?, timezone?, email?, currentPassword?}` → `User` (email change needs `currentPassword`) |
| POST | `/me/password` | session | `{currentPassword, newPassword}` → `204` |
| GET / PUT | `/me/onboarding` | session | `{services[], technologies[], region, freshnessDays}` → `{preferences, completedAt}` |
| GET | `/workspaces` | session | → `[{id, name, role, isDemo}]` |
| GET / PATCH | `/workspace` | session (PATCH: admin+) | `{name?, defaultCurrency?, defaultGeography?}` → `Workspace` |
| GET | `/workspace/members` | session | → `[{id, userId, email, fullName, role, joinedAt}]` |
| PATCH / DELETE | `/workspace/members/{membershipId}` | admin+ (DELETE self: any) | `{role}` → `Member` / `204` |
| GET / POST | `/workspace/invitations` | admin+ | `{email, role}` → `201 Invitation` |
| DELETE | `/workspace/invitations/{id}` | admin+ | → `204` |
| GET | `/leads` | session | query below → `Page<LeadSummary>` |
| GET | `/leads/{id}` | session | → `LeadDetail` (company, sources, score breakdown, timeline, `isSaved`) |
| PUT / DELETE | `/leads/{id}/save` | session | → `{leadId, isSaved, savedAt}` / `204` (both idempotent) |
| GET | `/saved-leads` | session | `page, pageSize` → `Page<{savedAt, savedByUserId, lead}>` |
| GET | `/companies` | session | `q, industry, technology[], intent[], sort, order, page, pageSize` → `Page<CompanySummary>` |
| GET | `/companies/{id-or-slug}` | session | → `CompanyDetail` (overview, activity, visible leads, signals) |
| GET | `/health`, `/ready` (unversioned) | — | liveness; readiness checks the DB and that migrations are at head (`503` otherwise) |

**`GET /leads` query:** `q` (substring of title, company, or technologies; case-insensitive) · `serviceType[]` · `technology[]` with `technologyMatch=any|all` (default `any`) · `intent[]` (`strong|medium|low`) · `region[]` (`worldwide, united-states, canada, latam, europe, united-kingdom, pakistan-allowed, international-remote`; leads tagged `worldwide` match every region) · `freshnessDays` (posted within N days) · `minScore` · `companyId` · `saved` · `sort` (`score|postedAt|lastVerifiedAt|companyName|title`, default `score`) · `order` (`asc|desc`, default `desc`) · `page` · `pageSize` (1–100, default 25). Sorting puts NULLs last and breaks ties by id, so pagination is deterministic. Closed leads are hidden from lists but still reachable by id.

`Page<T>` = `{items, total, page, pageSize, totalPages}`. Enum values are lowercase (`strong`, `high_confidence`, …). Timestamps are ISO-8601 UTC, and the frontend formats relative times ("2 days ago").

## Frontend integration strategy (implemented in Phase 2)

Chosen approach: **a same-origin proxy via Next.js `rewrites`**, with FastAPI as the single source of truth.

```js
// next.config.mjs
async rewrites() {
  return [{ source: "/api/v1/:path*", destination: `${process.env.BACKEND_URL}/api/v1/:path*` }];
}
```

- The browser only talks to the Next.js origin, so cookies are first-party, `SameSite=lax` works, and no CORS is needed in production.
- Run uvicorn with `--proxy-headers --forwarded-allow-ips=<next server IP>` so rate limiting and audit logs see the real client IP rather than the proxy's.
- Errors pass through unchanged, including the standard error body and `X-Request-ID`.
- The fixture-backed Next.js route handlers in `src/app/api/*` are dead code (no page calls them) and will be deleted rather than kept as a second source of truth.
- A small `src/lib/api.js` client will call `/api/v1/...` with `credentials: "include"`, hold `csrfToken` in memory from `GET /auth/session`, attach `X-CSRF-Token`, and map `401` to a redirect to `/login`. Page URLs stay unchanged. Lead and company links will use UUIDs, and company pages also accept slugs (`/companies/novastack-labs` keeps working).
- Frontend environment variable: `BACKEND_URL` (server-side only), e.g. `http://localhost:8000`.

## Demo data

`scripts/seed_demo.py` loads the prototype's 8 companies and 8 leads (with timelines and score breakdowns) into a dedicated demo workspace owned by `demo@hiringintel.ai`. Every row is flagged `is_demo` and is private to that workspace, so real workspaces never see fixtures. The seed is idempotent, and re-running it does not touch existing rows' timestamps. It refuses to run in production. Two pieces are deliberately labelled rather than passed off as real: provenance is recorded as `source_type=demo_fixture` instead of the prototype's invented "Company Careers / Partner Feed", and the score breakdown is versioned `demo-fixture`. Saved searches and alerts will be seeded in Phase 2, when their tables exist. The prototype's vanity counts (e.g. "418 total matches") will not be seeded.

## Known issues and outstanding decisions

**Environment**
- The local PostgreSQL cluster (and therefore both databases) uses **`SQL_ASCII` encoding with `C` collation**. The app forces `client_encoding=utf8` so text round-trips correctly, but Postgres does not validate UTF-8, and case-insensitive search does not fold non-ASCII characters. Recreate both databases as UTF-8 (commands above) and re-run `alembic upgrade head` and the seed. Production must use UTF-8.
- The local `.env` previously contained the dev DB password in `.env.example`. That file now holds placeholders, and `.env` is git-ignored. Rotate that password if the folder was ever shared.

**Product decisions needed**
1. Saved leads are **workspace-shared** (a team pipeline, recording who saved each one). Confirm, or switch to per-user.
2. Region semantics: a `worldwide` lead matches every region filter. Confirm.
3. Scoring formulas: the prototype's breakdowns are illustrative, and the fixture components don't even sum to the displayed total. Scoring engine v1 (Phase 3) needs signed-off definitions for every component.
4. Whether self-service registration stays open in production (`ALLOW_REGISTRATION`).

**Deployment requirements (not yet met)**
- A real email provider adapter (password reset and invitations). Production config refuses to start without one.
- HTTPS termination, `COOKIE_SECURE=true`, `TRUSTED_ORIGINS` set to the production frontend origin, and uvicorn `--proxy-headers` behind the proxy.
- A scheduled cleanup job (Phase 3 worker) for expired sessions, reset tokens, and rate-limit buckets (`services.rate_limit.purge_expired`).
- Backups: daily `pg_dump --format=custom` plus WAL/PITR from the managed provider. Restore with `pg_restore --clean --no-owner -d <db> <dump>`, then `alembic upgrade head`. Test restores periodically.

**Not yet implemented:** saved searches and runs, alerts, dashboard and analytics (Phase 2); exports, the scoring engine, ingestion adapters, scheduling, notification delivery, and CRM/Slack/webhook integrations (Phase 3); frontend wiring (Phase 2).
