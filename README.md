# Aptil

> Land the job, ace the interview. An AI-powered job-application and interview-prep platform.
>
> **Working name — `Aptil` is a placeholder and can be renamed in one pass.** See `docs/naming.md`.

Aptil is a multi-tenant SaaS that (1) discovers relevant jobs from legitimate sources,
tailors the user's résumé per role, and assists applications through official ATS systems
with the user's consent, and (2) runs realistic mock interviews grounded in the user's CV
and the specific job they are targeting.

## Architecture

| Layer | Tech | Notes |
|-------|------|-------|
| Frontend | Next.js (TypeScript, App Router, Tailwind) | Self-hosted, standalone build |
| API | FastAPI (Python 3.12) | Async, Beanie ODM, Pydantic v2 |
| Workers | Celery + Redis | Apply engine, CV parsing, LLM jobs |
| Scheduler | Celery beat | Drives discovery → matching → apply |
| Database | MongoDB 7 | Multi-tenant via app-level `tenant_id` filtering (Beanie) |
| File storage | MinIO / S3 / R2 | Any S3-compatible bucket — see [`docs/storage-s3.md`](docs/storage-s3.md) |
| AI | LiteLLM router | OpenAI / Anthropic / Grok / Groq / Ollama, multi-key + failover |
| Browser automation | Playwright | Headless Chromium in worker containers; Greenhouse / Lever / Ashby |
| Payments | Stripe | Plans + entitlement metering |
| Reverse proxy / TLS | Caddy | Auto-HTTPS on the VPS |
| Runtime | Docker Compose | Single-VPS now; k3s later if scaling |

Everything is self-hostable on a single VPS — that is the intended production shape.
A `render.yaml` Blueprint is also included for throwaway staging deployments; see
[`docs/deploy-render.md`](docs/deploy-render.md).

## Repository layout

```
.
├─ backend/        # FastAPI API + Celery workers (one Python package, multiple entrypoints)
│  ├─ app/
│  │  ├─ core/     # config, security, logging, rate limiting
│  │  ├─ db/       # Mongo client + Beanie init, base documents
│  │  ├─ models/   # Beanie document models
│  │  ├─ schemas/  # Pydantic request/response schemas
│  │  ├─ api/      # HTTP routers (versioned)
│  │  ├─ services/ # business logic (auth, billing, matching, storage, ATS, connectors)
│  │  ├─ ai/       # LiteLLM router + prompt modules
│  │  └─ workers/  # Celery app, beat schedule, tasks
│  └─ tests/       # unit, security, behaviour, and e2e (Playwright) suites
├─ frontend/       # Next.js app
├─ infra/          # Caddy config, deploy/backup scripts
├─ docs/           # architecture, compliance, deployment, storage, UI prompts
├─ docker-compose.yml
└─ render.yaml     # optional: temporary Render deployment
```

## Quick start (local)

Prereqs: Docker + Docker Compose.

```bash
cp .env.example .env
```

Fill in at minimum `SECRET_KEY`, `CREDENTIAL_ENCRYPTION_KEY`, and `MINIO_ROOT_PASSWORD`:

```bash
openssl rand -hex 32
```

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Then bring the stack up:

```bash
docker compose up --build
```

Services:
- Web:     http://localhost:3000
- API:     http://localhost:8000  (docs at /docs in non-production)
- MinIO:   http://localhost:9001  (console)
- MongoDB: localhost:27017
- Redis:   localhost:6379

**A `$` in any secret must be doubled.** `docker compose` substitutes `$NAME`
inside `.env`, so `pa$word` reaches the container as `pa` — SMTP or Stripe then
fail with an opaque authentication error. Write `pa$$word`. The app warns at
startup if it sees a `$$` that was never consumed.

**Port already in use?** If you run a native MongoDB, Redis or Ollama, `compose up`
fails with `ports are not available: ... address already in use`. Every host port is
overridable in `.env` — `MONGO_HOST_PORT`, `REDIS_HOST_PORT`, `MINIO_HOST_PORT`,
`MINIO_CONSOLE_HOST_PORT`, `API_HOST_PORT`, `WEB_HOST_PORT`. These only affect what
*your machine* can reach; containers always talk to each other on the compose
network, so remapping them never breaks the app.

The `ollama` service sits behind a profile and does not start by default (it is a
multi-GB image and only needed if `LLM_DEFAULT_MODEL` names an `ollama/...` model).
Start it with `docker compose --profile ollama up`.

**Seed the plans — this is required, not optional.** New accounts are provisioned onto the
`free` plan, and entitlement checks read their limits from it. Without seeded plans, users
can't run interviews or applications:

```bash
docker compose exec api python -m scripts.seed
```

MongoDB is schemaless — Beanie creates collections and indexes automatically on startup,
so there is no migration step.

### Making the pipeline actually do something

Discovery, matching, and applying run on a schedule (the `beat` service). Beat only
sources jobs from connector queries you configure, so set `SOURCING_JOBS_JSON` in `.env`:

```bash
SOURCING_JOBS_JSON=[{"source":"greenhouse","query":{"board":"stripe","company":"Stripe"}},{"source":"lever","query":{"company":"spotify","company_name":"Spotify"}},{"source":"ashby","query":{"board":"ramp","company":"Ramp"}}]
```

With that empty (the default), no jobs are ever discovered and the dashboard stays empty.
Users can also trigger a match run on demand from the dashboard ("Find new matches").

Workday is also supported for **discovery**, using the same public JSON feed each
customer's own careers page calls. Take the tokens from the careers URL
`https://{tenant}.{dc}.myworkdayjobs.com/en-US/{site}/…`:

```bash
{"source":"workday","query":{"tenant":"nvidia","dc":"wd5","site":"NVIDIAExternalCareerSite","company":"NVIDIA"}}
```

Those postings are matched and shown like any other, but Aptil does **not** submit
them: Workday's application is a five-page wizard, and reporting a submission we
cannot evidence is forbidden (`docs/compliance.md` §2a). Workday rows park with a
"multi-page application" reason and a link, so the user finishes them.

Sweep intervals are configurable — set any to `0` to disable it:
`SOURCING_INTERVAL_MINUTES`, `MATCHING_INTERVAL_MINUTES`, `APPLY_INTERVAL_MINUTES`.

## Match quality and diversity

Matching is a transparent weighted blend (skills 50%, title 30%, location 20%)
and every result carries a human-readable reason. Two guards keep the results
useful rather than merely numerous:

- `MIN_MATCH_SCORE` (default `0.55`) — weak matches are dropped, not shown.
- `MAX_MATCHES_PER_COMPANY` (default `3`) — no employer can take over the
  dashboard. Combined with `MAX_POSTINGS_PER_SOURCE`, this stops whichever board
  has the most openings from dominating everyone's results.

The same role listed in several offices is shown once.

Skill scoring gives full credit at three matched skills rather than scoring
"fraction of everything you listed" — otherwise a thorough profile scores worse
than a sparse one for the same job.

## Résumés are .docx, not markdown

Both the "build one for me" résumé and each per-job tailored version are
rendered to **.docx** (`app/services/resume_docx.py`). They used to be `.md`,
which every ATS résumé field rejects — so the apply engine attached a file the
form refused, the submission bounced, and the row parked as unconfirmed. The
markdown is still kept as the document's `extracted_text`, since that is what
matching and tailoring read.

## Voice mock interviews

The interview page can read questions aloud and take spoken answers, using the
browser's built-in `speechSynthesis` and `SpeechRecognition`. No audio leaves the
machine and there is no per-minute cost. Firefox has no `SpeechRecognition`, so
the UI says so and falls back to typing.

## Design system

The interface is near-monochrome warm grey with a single blue, and the rule that
holds it together is that **`primary` (near-black) means *action* and `accent`
(blue) means *information***. Blue appears on match scores, active navigation,
links and focus rings — never on a button. Tokens are CSS custom properties in
`frontend/src/app/globals.css`, named for components in `tailwind.config.ts`, so
a regenerated palette drops in without touching a component. Every
foreground/background pair meets WCAG AA in both themes.

Three components carry the product's argument and live in
`frontend/src/components/signals.tsx`:

- **Score arc** — match quality as a thin arc around a tabular number, grey below
  70% and accent above. The only circular element on screen.
- **Status rail** — a 2px hairline down each application row, filled to show how
  far it has travelled. A text label always rides alongside, so state never
  depends on colour alone.
- **Working line** — a 1px hairline crossing the top of the page while background
  work runs. It replaces the spinner for work the user did not directly request,
  which is most of what this product does.

The full brief, including the prompt that regenerates the system, is in
[`docs/ui-prompts.md`](docs/ui-prompts.md).

## Stored site credentials

Most sites Aptil applies through — Greenhouse, Lever, Ashby — accept applications
with no account at all. A few (Workday, iCIMS, Taleo) hide the form behind a
sign-in. For those, **the user creates the account and Aptil signs in with it;
Aptil never registers anywhere on anyone's behalf.** There is no registration code
path, and a test fails if an adapter grows one. A login is attempted once and
parks on failure — retrying a wrong password is how an account gets locked.

Passwords are **envelope encrypted**: a random per-secret data key encrypts the
password, and `CREDENTIAL_ENCRYPTION_KEY` encrypts that data key. Compromising one
data key exposes one credential, and rotating the outer key re-wraps 32 bytes per
row rather than decrypting the whole table:

```bash
docker compose exec api python -m scripts.rotate_credential_key --apply
```

Because Aptil generates these passwords, the user has no other copy and must be
able to read one back. `POST /onboarding/credentials/{id}/reveal` returns it, but
only after re-entering the account password — a stolen session token is not
enough. Reveals are rate limited, audit logged, and the UI hides the value again
after a minute.

## Plans and entitlements

| Plan | Price | Applications / mo | Interviews / mo |
|------|-------|-------------------|-----------------|
| Free | $0 | 5 | 1 |
| Starter | $19 | 30 | 2 |
| Pro | $49 | 120 | 8 |
| Accelerate | $99 | 400 | 20 |

Limits are enforced at the point of spend: `create_interview` and the apply engine both
check `billing.can_*` and meter usage on success. Paid plans need a `stripe_price_id` on
the `Plan` document before they can be purchased; the UI shows them as "Coming soon" until
then. The plan catalogue is served from `/api/v1/plans` and drives both the marketing page
and the in-app picker, so the two cannot drift apart.

## Operational notes

**Email never blocks a request.** Verification and reset mail is queued to the
worker (`email.send`, retried at 1m/4m/15m) rather than sent inline — against a
real relay an inline send cost ~8s per signup. If the broker is unreachable the
API falls back to sending it itself, because losing a verification link strands
an account.

**`/health/ready` covers every dependency**, not just Mongo: Redis and object
storage are probed too. Mongo failing marks the instance *down*; Redis or
storage failing marks it *degraded* but still serving, because the app works
without them and flapping instances out of the pool would cause the outage the
probe exists to prevent. It also reports whether an AI provider key is present —
without one, CV parsing quietly falls back to a name/email/phone regex.

## Security model

- **Passwords**: Argon2id. Login is timing-equalised so a wrong email and a wrong password
  cost the same (no account enumeration).
- **Sessions**: short-lived access JWT + rotating refresh token. Refresh tokens are stored
  server-side and revoked on use; replaying a rotated token revokes the whole family
  (theft detection). Changing or resetting a password bumps `token_version`, invalidating
  every token already issued.
- **Rate limiting**: Redis fixed-window per route + caller. `X-Forwarded-For` is honoured
  only when the direct peer is in `TRUSTED_PROXY_IPS` — set it when running behind Caddy.
- **Uploads**: size-capped, content sniffed by magic bytes (not the client-declared type),
  and filenames sanitised so they cannot escape the tenant's object-storage prefix.
- **Site credentials**: unique password per site, Fernet-encrypted at rest, never returned
  by any endpoint.
- **Multi-tenancy**: MongoDB has no RLS, so every tenant-scoped query filters on
  `tenant_id` / `user_id` in the application layer. Tests pin this.
- **Production config**: the app refuses to boot in `ENVIRONMENT=production` with
  placeholder secrets, a short `SECRET_KEY`, or unset SMTP.
- **Headers**: the API sets `nosniff`, `DENY` framing, `no-referrer` and HSTS; Caddy adds
  a CSP for the web app.

## Compliance guardrails

Read `docs/compliance.md` before touching the apply engine. In short:

- We apply through the company's own ATS form. We never pilot a user's logged-in
  LinkedIn/Indeed session.
- We never solve or evade CAPTCHAs. Any challenge parks the application in `NEEDS_INFO`
  for the user to finish.
- We only report an application as `submitted` when the page actually confirms it — a
  clicked button is not evidence.
- Users can export everything we hold and delete their account from **Settings**.
- Terms and Privacy are presented and consent is recorded at signup.

## Testing

```bash
cd backend
uv pip install -e ".[dev]"
```

Unit, security, and behaviour suites (need MongoDB + Redis; they skip themselves if
neither is reachable):

```bash
pytest -q
```

Browser end-to-end suite (needs the web app and API running):

```bash
pytest tests/e2e -q
```

It also needs to reach the running stack's **Redis** from the host, to reset
rate-limit windows between tests — the limiter allows 5 signups per 5 minutes
per IP, so without that reset every test after the fifth fails on a 429 rather
than on anything real. It finds Redis automatically via `REDIS_HOST_PORT` (the
port docker-compose publishes); set `E2E_REDIS_URL` if yours lives elsewhere.
When it cannot reach one, the suite skips with that message rather than
reporting a wall of unrelated-looking UI failures.

The suites cover, among other things: tenant isolation, JWT tampering and `alg=none`,
refresh-token rotation and reuse detection, upload sniffing and size limits, Stripe webhook
signature enforcement, rate-limit window behaviour, entitlement metering, and — in the
browser — navigation across every page, responsive layout at four viewports, form
validation messages, keyboard/skip-link accessibility, and the full
signup → onboarding → dashboard journey.

Install browsers once for the e2e suite:

```bash
playwright install chromium
```

## Development phases

- **Phase 1 (current):** Web SaaS — accounts, onboarding, CV parsing, job discovery + dedupe,
  consent-based apply engine, plans/billing, dashboard, in-browser mock interviews.
- **Phase 2:** Tauri desktop companion — live interview-practice copilot with global hotkeys
  and native audio.

See `docs/roadmap.md` and `docs/compliance.md` (read the latter before touching the apply engine).

## Deploying

```bash
./infra/scripts/deploy.sh
```

It refuses to run with placeholder secrets, brings up the production overlay (Caddy + TLS,
no source mounts, no exposed database ports), seeds plans, and checks readiness.

Back up nightly — Mongo **and** MinIO, since the object store holds every CV:

```bash
./infra/scripts/backup.sh
```

### How the browser reaches the API

Two supported modes:

- **Same-origin proxy (recommended).** Set `API_PROXY_TARGET` on the web service to the
  API's internal URL. The browser calls `/api/...` on the web origin and
  `frontend/src/middleware.ts` forwards it server-side. Nothing about the API URL is
  baked into the client bundle, so one image works everywhere, and there is no CORS to
  configure. Middleware runs per request, so changing the target needs a restart, not a
  rebuild. (It deliberately is *not* `rewrites()` in `next.config.mjs` — those are frozen
  into the build, so a runtime-only value silently produced an empty rewrite table.)
- **Direct.** Set `NEXT_PUBLIC_API_BASE_URL` at **build** time (docker-compose passes it as
  a build arg). This is the local default. Because it is inlined into the browser bundle,
  changing it requires rebuilding the `web` image. Use `"/"` — not `""` — to mean
  same-origin: Docker ignores an empty build arg and falls back to the Dockerfile default.

If you put the app behind any proxy, also set `TRUSTED_PROXY_IPS` — the rate limiter
ignores `X-Forwarded-For` from untrusted peers, so without it every visitor shares a single
rate-limit bucket.

### Share a link without deploying

To put the local stack behind a public HTTPS URL for a tester — free, no account,
no card:

```bash
./infra/scripts/share.sh
```

It opens a Cloudflare Quick Tunnel, switches the build to same-origin API calls,
trusts the proxy so per-visitor rate limiting still works, and points email links
at the tunnel. Ctrl-C restores the local setup. It lives only while that terminal
is open. See [`docs/share-a-link.md`](docs/share-a-link.md), which also covers the
free-tier hosting options and what each one cannot run.

### Other hosts

`render.yaml` + [`docs/deploy-render.md`](docs/deploy-render.md) cover a Render
deployment (needs MongoDB Atlas and an S3-compatible bucket, since Render provides
neither). Note that Render **Blueprints are a paid feature** and Background Workers
have no free tier — a free Render setup runs the app but not the apply engine.
[`docs/share-a-link.md`](docs/share-a-link.md) compares the alternatives.

## License

Proprietary — all rights reserved (placeholder; set before open-sourcing anything).
