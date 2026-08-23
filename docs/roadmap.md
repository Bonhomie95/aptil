# Roadmap

## Phase 1 — Web SaaS (in progress)

**Done (scaffolded and runnable):**
- Monorepo, Docker Compose (Postgres, Redis, MinIO, Ollama, API, worker, web), Caddy prod overlay.
- Backend core: config, async DB, structured logging, security (Argon2, JWT, Fernet).
- Multi-tenant data model (Tenant, User, Profile, ResumeDocument, SiteCredential, Plan,
  Subscription, Job, JobApplication, InterviewSession).
- Auth: register + email verification + login/refresh + `/me`. (Google OAuth stubbed.)
- Resumable onboarding API + CV upload → background parse → profile autofill.
- AI layer: LiteLLM multi-provider router (OpenAI/Anthropic/Grok/Groq/Ollama) + prompts.
- Celery worker + tasks: CV parsing, discovery/dedupe (fingerprint), apply-engine scaffold.
- Interview API: generate questions + score answers, grounded in CV + job.
- Frontend shell: landing, register, login, onboarding, dashboard.

**Also done (Phase 1 completion — this pass):**
- ✅ **Google OAuth** — `oauth_service` (Authlib) + `/auth/google/{login,callback}`.
- ✅ **MongoDB + Beanie** data layer (replaced Postgres/SQLAlchemy/Alembic). Schemaless —
  Beanie creates collections + indexes on startup; multi-tenancy is app-level `tenant_id`
  filtering (no RLS — see `docs/compliance.md`).
- ✅ **Job connectors** (`app/services/connectors/`): Adzuna, Greenhouse, Lever, Ashby, USAJOBS.
- ✅ **Matching service** (`app/services/matching.py`) + `sourcing` tasks → creates `JobApplication` rows.
- ✅ **ATS apply adapters** (`app/services/ats/`) with Playwright; CAPTCHA → `NEEDS_INFO` (never bypassed).
- ✅ **Résumé tailoring** task (`app/workers/tasks/tailoring.py`) + generated-résumé storage.
- ✅ **Billing**: Stripe checkout + webhooks + entitlement-metering helpers (`app/services/billing.py`).
- ✅ **Rate limiting** (`app/core/ratelimit.py`, applied to login) + **CI** (`.github/workflows/ci.yml`).
- ✅ **Premium UI**: glassmorphism design system, light/dark theme, animated landing (aurora +
  particle field), and themed onboarding / plans / dashboard / mock-interview screens.

**Remaining (next milestones):**
1. **Enforce** `can_apply`/`can_interview` metering at the apply task + interview-create route
   (helpers exist in `billing.py`; wire them once Stripe is live so dev isn't blocked).
2. **WebSocket** dashboard live updates (currently fetch-on-load).
3. **Scheduler**: periodic `sourcing.run_source` + `match_for_user` (Celery beat).
4. **Admin panel** + **observability** (self-hosted Sentry), structured request logging.
5. **Interview UX**: voice (WebRTC + STT/TTS) — lands with the Phase-2 desktop app.
6. Fine-grained **onboarding editors** for work history / certifications (currently confirm-only).

## Phase 2 — Desktop companion (Tauri)

- Live interview-**practice** copilot: global hotkeys (stop/pause/resume/restart/quit),
  low-latency mic capture, streaming STT + TTS. Talks to the same backend.

## Non-goals (see docs/compliance.md)

- No CAPTCHA/bot-detection bypass.
- No auto-piloting users' logged-in LinkedIn/Indeed sessions.
- No covert interception/recording of live third-party interview calls.
