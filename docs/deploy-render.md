# Deploying to Render (temporary / staging)

Render is not the intended long-term home for Aptil — the stack is designed to
run on a single VPS via Docker Compose (see the README). But it is a good way to
get a shareable URL up quickly for testing. This is what that takes.

`render.yaml` in the repo root is a Blueprint that creates everything Render can
host. Two pieces have to come from elsewhere, because Render doesn't offer them.

## What runs where

| Piece | Where | Cost |
|-------|-------|------|
| API (FastAPI) | Render Web Service | Starter |
| Web (Next.js) | Render Web Service | Starter |
| Celery worker | Render Background Worker | Starter — **not available on the free plan** |
| Celery beat | Render Background Worker | Starter — **not available on the free plan** |
| Redis | Render Key Value / Redis | Free |
| **MongoDB** | **MongoDB Atlas** (external) | M0 free |
| **Object storage** | **Cloudflare R2** (external) | Free tier |

The worker runs headless Chromium for the apply engine, so it needs roughly 1 GB
of RAM. Don't put it below Starter.

Two Background Workers is the main cost. If you only want to click around the UI
and don't need CV parsing or job discovery, you can skip `aptil-worker` and
`aptil-beat` entirely — the app degrades honestly (uploads are stored but marked
unparsed, "Find new matches" returns a clear "temporarily unavailable"), and the
rest of the product works.

## Before you start

**1. MongoDB Atlas.** Create a free M0 cluster. Under Network Access, allow
`0.0.0.0/0` (Render doesn't publish static egress IPs on lower plans). Copy the
`mongodb+srv://...` connection string.

**2. Cloudflare R2.** Create a bucket named `aptil-uploads` and an API token with
Object Read & Write. You get an Access Key ID, a Secret Access Key, and an
endpoint like `<account-id>.r2.cloudflarestorage.com`.

`app/services/storage.py` talks to a plain `endpoint_url`, so R2, Backblaze B2,
and real S3 all work through the same `MINIO_*` variables. Only two things
differ from local MinIO:

```
MINIO_ENDPOINT=<account-id>.r2.cloudflarestorage.com   # no scheme
MINIO_ROOT_USER=<R2 Access Key ID>
MINIO_ROOT_PASSWORD=<R2 Secret Access Key>
MINIO_BUCKET=aptil-uploads
MINIO_SECURE=true                                       # R2 is HTTPS
MINIO_REGION=auto                                       # R2 only accepts "auto"
```

`MINIO_REGION` is easy to miss and fails obscurely: it is part of the SigV4
signature, so the wrong value returns `SignatureDoesNotMatch` rather than
anything that points at the region. R2 wants `auto`; AWS S3 wants the bucket's
real region.

**3. A Fernet key.** Render's `generateValue` won't produce a valid one, so
generate it yourself and paste it in:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**4. SMTP.** `ENVIRONMENT=production` refuses to boot without `SMTP_HOST` — by
design, because otherwise verification and password-reset links are only written
to the log and no one can finish signing up.

## Deploy

1. Render Dashboard → **New** → **Blueprint** → pick the repo.
2. Render reads `render.yaml` and prompts for every variable marked
   `sync: false`. Fill them all in.
3. After the first deploy, attach the `aptil-shared` env group to
   `aptil-worker` and `aptil-beat` if Render didn't do it automatically, and
   paste in the same `SECRET_KEY` / `REDIS_URL` the API got.
4. **Seed the plans.** Nothing works until you do this — new accounts are put on
   the free plan and every entitlement check reads its limits:

   ```
   Render → aptil-api → Shell →  python -m scripts.seed
   ```

5. Check it's alive: `https://<api-host>/health/ready` should report
   `{"status":"ok","checks":{"mongo":"ok"}}`.

## How the browser reaches the API

The web service sets `API_PROXY_TARGET` to the API's internal address, and
`frontend/src/middleware.ts` proxies `/api/*` through to it. So the browser only
ever talks to one origin.

This matters on Render specifically. `NEXT_PUBLIC_*` values are inlined into the
JavaScript bundle **at build time**, so if the frontend called the API directly
you'd have to rebuild the image every time the API's URL changed — and a wrong
value fails silently in the browser with no server-side error. Proxying avoids
that entirely, and removes CORS from the picture.

Two footguns worth knowing, both of which produced a silently broken deploy:

- The proxy is **middleware**, not `rewrites()` in `next.config.mjs`. Rewrites are
  resolved at build time into `.next/routes-manifest.json`, and `output: "standalone"`
  does not even ship the config file — so a runtime-only `API_PROXY_TARGET` gave an
  empty rewrite table and every `/api` call 404'd on the Next router.
- Set `NEXT_PUBLIC_API_BASE_URL` to `"/"`, **not** `""`. Docker treats an empty build
  arg as absent and falls back to the Dockerfile's `ARG` default, which bakes
  `http://localhost:8000` into the shipped bundle. `"/"` becomes an empty base once
  the trailing slash is stripped, which is what same-origin means.

## Trust the proxy, or rate limiting misfires

`TRUSTED_PROXY_IPS` is set in the Blueprint to Render's private ranges. Don't
remove it. The rate limiter only believes `X-Forwarded-For` when the request
arrives from a trusted peer; behind Render's proxy (and behind the Next proxy)
every request otherwise looks like it came from one IP, and a single noisy
visitor would burn the login/signup budget for everybody.

## Things to expect

- **Cold starts.** Free web services sleep after 15 minutes idle and take ~50s to
  wake. Starter services don't sleep.
- **Google OAuth** needs `GOOGLE_REDIRECT_URI` set to
  `https://<api-host>/api/v1/auth/google/callback`, and that exact URL registered
  in the Google Cloud console. Leave the client id/secret empty and the sign-in
  button hides itself.
- **Stripe** is optional. Without `STRIPE_SECRET_KEY` the free plan still works
  and paid plans show "Coming soon". If you do add Stripe, set
  `STRIPE_WEBHOOK_SECRET` too — unsigned webhooks are rejected outright, so
  without it no subscription will ever activate.
- **Discovery finds nothing until you configure it.** Set `SOURCING_JOBS_JSON` on
  the shared env group, e.g.:

  ```json
  [{"source":"greenhouse","query":{"board":"stripe","company":"Stripe"}},
   {"source":"lever","query":{"company":"spotify","company_name":"Spotify"}},
   {"source":"ashby","query":{"board":"ramp","company":"Ramp"}}]
  ```

  Greenhouse and Lever board endpoints are public and need no API key, which
  makes them the easiest sources to test with. Adzuna and USAJOBS need keys.
- **The apply engine will mostly park applications.** That's correct behaviour:
  it only reports `submitted` when the ATS confirmation page says so, and parks
  anything it can't evidence (or that shows a CAPTCHA). Expect `needs_info` rows
  on the dashboard rather than a wall of green.

## Tearing it down

Delete the Blueprint in Render to stop the Background Worker billing, then drop
the Atlas cluster and the R2 bucket. Nothing else persists.
