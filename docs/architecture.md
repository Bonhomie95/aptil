# Architecture

## Decision: web-first, desktop companion later

- The apply engine must run **server-side, 24/7** (it applies while the user is away) — this
  cannot live in a desktop app. So the core is a **web SaaS + background workers**.
- Global hotkeys and native low-latency audio for the interview-practice copilot need OS
  access a browser can't give — that becomes a **Tauri desktop companion in Phase 2**, talking
  to the same backend.

## Components

```
                         ┌────────────┐
   Browser ──────────────►  Caddy (TLS) │
                         └──────┬───────┘
                    /api/*      │      everything else
              ┌─────────────────┴──────────────────┐
              ▼                                     ▼
      ┌───────────────┐                     ┌──────────────┐
      │  FastAPI (api)│                     │ Next.js (web)│
      └──────┬────────┘                     └──────────────┘
             │ enqueue
             ▼
      ┌───────────────┐   broker   ┌──────────────┐
      │ Redis (BullMQ │◄──────────►│ Celery worker│
      │  equiv: Celery)│           │  - cv parse  │
      └───────────────┘            │  - discovery │
             ▲                     │  - apply     │
   Beanie    │                     └──────┬───────┘
             ▼                            │
      ┌───────────────┐  files     ┌──────▼───────┐   LLMs
      │ MongoDB       │            │ MinIO (S3)   │   via LiteLLM →
      │ (multi-tenant)│            └──────────────┘   OpenAI/Anthropic/
      └───────────────┘                               Grok/Groq/Ollama
```

## Multi-tenancy

MongoDB (via the Beanie ODM). Every tenant-scoped document carries a `tenant_id`
(`TenantDocument` base), and isolation is enforced in the **application layer** — every
tenant-scoped query filters by `tenant_id` (or the owning `user_id`). MongoDB has no
Row-Level Security, so this discipline is the boundary; keep tenant filters on every read
and write. A signup creates one `Tenant` + one `User` (1:1 now; the model allows teams later).

## Request → application lifecycle

1. User onboards; CV parsed → `Profile`. The profile is created *before* the parse task is
   queued, or the worker would race the request and discard what it extracted.
2. Celery beat (`scheduler.run_all_sources`) fans out to the connectors configured in
   `SOURCING_JOBS_JSON`; postings are deduped into the shared `Job` pool by `fingerprint`.
3. `scheduler.match_all_users` → `matching.match_jobs_for_user` creates `JobApplication`
   rows (`MATCHED`) with a `match_score` and human-readable `match_reasons`.
4. `apply.enqueue_for_user` queues up to 2 *including work already in flight*; when the
   user's strategy is `tailored`, tailoring is chained before submission.
5. The ATS adapter submits and then verifies the confirmation page, or parks the
   application in `NEEDS_INFO`. Only a confirmed submission meters entitlement and emails
   the user.

Nothing in steps 2-4 is reachable without the `beat` service running (or a user pressing
"Find new matches"), so a deployment without it discovers no jobs at all.

## Scheduling

`app/workers/celery_app.py` builds the beat schedule from `SOURCING_INTERVAL_MINUTES`,
`MATCHING_INTERVAL_MINUTES` and `APPLY_INTERVAL_MINUTES`; any of them set to `0` disables
that sweep. Sweeps only consider users who are active, email-verified, and have finished
onboarding - the apply engine acts on someone's behalf, so it must never run for an account
that has not completed consent.

## AI routing

`app/ai/router.py` wraps LiteLLM: per-provider **key pools** (round-robin), **model failover**
(default → fallbacks), and **Ollama** for a future self-hosted model. Callers use
`chat()` / `chat_json()` and never hard-code a provider (spec point 18).
