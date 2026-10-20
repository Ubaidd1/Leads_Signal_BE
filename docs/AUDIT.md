# Audit & Implementation Plan

Audit date: 2026-10-21. Frontend: `../hiring-intelligence-nextjs-tailwind-only` (Next.js 15 App Router, JS/JSX, Tailwind, lucide-react; no data-fetching library, no TypeScript).

## Key findings

1. **The Next.js `/api/*` route handlers are not used by any screen.** Every page imports fixture modules from `src/data/*` directly or reads/writes `localStorage` (`src/lib/storage.js`). The handlers (`/api/leads`, `/api/companies`, `/api/alerts`, `/api/saved-searches`, `/api/exports`) are dead code that also fabricate results (e.g. `POST /api/exports` always returns `status: "completed"`; `DELETE /api/saved-searches/:id` deletes nothing).
2. **Authentication is fake.** `login/page.js` compares against the hard-coded `demo@hiringintel.ai` / `demo123` and writes `{email, name}` to `localStorage.hi_session`. No route is protected; the header/sidebar show a hard-coded "ZoneX Dev".
3. **All metrics are hard-coded**: dashboard (1,284 leads, 186 high-intent, velocity bars, intent distribution, "Recent Signals"), analytics (4,210 companies, tech/industry shares), sidebar credit usage (1,284/2,000), header "Updated 4 min ago", search builder "487 companies".
4. **Fake success toasts**: "Save search" on Lead Discovery, "Save lead" on lead detail, saved-search "Run", integration connect/disconnect, profile/workspace save (localStorage only).
5. **Exports are client-side blobs**; the export history table is a static array and its Download button re-exports *all* fixture leads regardless of row.
6. **Lead/company detail fall back to the first fixture** when the id is unknown (`getLead(id) || leads[0]`) instead of a 404.
7. **Fixture score breakdowns are synthetic** (derived from `94 - leadScore` deductions) — they are illustrative, not a scoring model.
8. Backend repo: skeleton files only (all `.py` empty), empty `README.md`/`requirements.txt`/`.gitignore`, and `.env.example` contained the real local DB password. PostgreSQL 16 is running locally with an empty `hiring_intelligence` database.

## Filter semantics observed in the frontend

| Filter | Values used | Semantics |
|---|---|---|
| `search` (URL `?search=`) | free text | case-insensitive substring over company name + job title + technologies |
| service | Software Development, AI / ML, Web Development, SEO (+ Mobile Development, PPC, Content, Recruiting in onboarding) | exact match on lead service type |
| technology | React, Node.js, Python, LLM, RAG, AWS, Next.js, SEO, … | lead technologies contains value |
| intent | Strong, Medium (Low on dashboard) | exact match |
| minScore | slider 70–92 (65–95 in builder) | `leadScore >= minScore` |
| geography | Worldwide, United States, Canada, Europe, Pakistan Allowed, International Remote | not implemented in UI filtering yet |
| freshness | 24 hours, 3/7/14/30 days | not implemented in UI filtering yet |
| sort | always `leadScore desc` | — |

## Feature inventory → backend endpoints

All endpoints live under `/api/v1`. ✅ = implemented in Phase 1.

| Screen / action | Current behaviour | Endpoint |
|---|---|---|
| Login | hard-coded creds → localStorage | ✅ `POST /auth/login` |
| Session restore / route guard | none | ✅ `GET /auth/session` |
| Sign out | clears localStorage | ✅ `POST /auth/logout` |
| "Forgot password?" | button does nothing | ✅ `POST /auth/password-reset/request`, `/confirm` |
| New workspace ("Run onboarding") | no account created | ✅ `POST /auth/register` |
| Onboarding preferences | localStorage | ✅ `GET/PUT /me/onboarding` |
| Profile settings | localStorage | ✅ `GET/PATCH /me`, `POST /me/password` |
| Workspace settings | localStorage | ✅ `GET/PATCH /workspace` |
| Workspace members / invitations | not in UI | ✅ `GET /workspace/members`, `PATCH/DELETE /workspace/members/{id}`, `POST/GET/DELETE /workspace/invitations`, `POST /auth/invitations/accept` |
| Switch workspace | not in UI | ✅ `GET /workspaces`, `PUT /auth/session/workspace` |
| Lead Discovery list + filters | fixture filter in memory | ✅ `GET /leads` |
| Lead detail | fixture, falls back to lead-1 | ✅ `GET /leads/{id}` |
| Save / unsave lead | localStorage toggle / fake toast | ✅ `PUT/DELETE /leads/{id}/save`, `GET /saved-leads` |
| Companies list + search | fixture | ✅ `GET /companies` |
| Company detail (+ open roles tab) | fixture, falls back to first | ✅ `GET /companies/{id-or-slug}` |
| Header global search | fixture | ✅ `GET /leads?q=` + `GET /companies?q=` |
| Search builder / saved searches CRUD, duplicate, run, history | localStorage, fake counts | Phase 2 `/saved-searches…` |
| Alerts list, read/unread, pause, delete, mark-all-read | localStorage | Phase 2 `/alerts…` |
| Dashboard, analytics | hard-coded | Phase 2 `/dashboard`, `/analytics/*` |
| Exports create/history/download | client blob, static history | Phase 3 `/exports…` |
| Integrations | toggle + fake toast | Phase 3 `/integrations…` |
| Data sources | static table | Phase 3 `/data-sources…` |
| Health | — | ✅ `GET /health`, `GET /ready` (unversioned) |

## Architecture decisions

- **Integration boundary: same-origin rewrite.** Next.js `rewrites()` forwards `/api/v1/:path*` to FastAPI (`BACKEND_URL`). The browser talks to one origin, so the session cookie is first-party, no CORS is needed in production, and FastAPI stays the single source of truth. The dead Next.js route handlers will be deleted in Phase 2 when the frontend is wired (they currently shadow nothing because the paths are unversioned, but they are a duplicate, fabricated source of truth).
- **JSON field casing: camelCase** in all API payloads, matching the existing frontend objects (`jobTitle`, `leadScore`, …).
- **Leads/companies tenancy:** rows with `workspace_id IS NULL` form the shared catalogue (populated only from permitted sources); rows with a `workspace_id` are private to that workspace (customer CSV imports, demo seed). Every read uses `workspace_id IS NULL OR workspace_id = :current`.
- **Demo fixtures are seeded into a dedicated demo workspace, flagged `is_demo = true`**, so they never appear to real workspaces. Fixture vanity counts (e.g. `totalMatches: 418`) are not seeded.
- **Saved leads are workspace-shared** (a team pipeline), recording who saved each lead. *Product decision to confirm.*
- **Sync SQLAlchemy + psycopg 3**, FastAPI runs sync endpoints in its threadpool. Simpler transactions; no async driver needed at current scale.

## Phases

1. **Foundation** (this delivery): config, DB, Alembic, auth/sessions/CSRF/rate limiting, users, workspaces, memberships, invitations, profile & workspace settings, onboarding prefs, leads/companies reads with filters & pagination, saved leads, audit events, seed script, tests.
2. Saved searches + runs, alerts, dashboard/analytics aggregations, frontend API client and wiring.
3. Exports + worker, scoring engine v1 (needs product sign-off on formulas), source adapters, scheduling, notification delivery, provider integrations.
