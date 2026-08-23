# Share a link, for free

You want a tester to click something. You don't want a hosting bill, a card on
file, or a deployment to babysit. Three options, cheapest effort first.

---

## 1. Tunnel the local stack (recommended for a demo)

```bash
./infra/scripts/share.sh
```

Prints an `https://<random>.trycloudflare.com` URL and holds it open until you
press Ctrl-C. **No Cloudflare account, no card, no DNS.** Needs `cloudflared`:

```bash
brew install cloudflared
```

What the script does, and why each part is needed:

| Step | Why |
|---|---|
| Rebuilds `web` with `NEXT_PUBLIC_API_BASE_URL=/` | The bundle must call the API on the **same origin**. Baked-in `localhost:8000` is exactly what breaks through a tunnel. |
| Sets `API_PROXY_TARGET=http://api:8000` | `src/middleware.ts` forwards `/api/*` to the API container, so one tunnel serves the whole app and there is no CORS. |
| Sets `TRUSTED_PROXY_IPS` to the compose subnet | Otherwise every visitor arrives as the web container's IP and shares **one** rate-limit bucket — your testers would lock each other out. |
| Sets `FRONTEND_BASE_URL` to the tunnel URL | Verification and password-reset links have to point at the tunnel, not `localhost`. |
| Restores the local build on exit | So `docker compose up` keeps working the way it did. |

**What it is not.** It lives only while your machine is awake and that terminal
is open, and the URL changes every run. It is for showing someone the app, not
for running it.

Two things to know before you send the link:

- Anyone with the URL can register. Real emails go out through your configured
  SMTP, and every signup lands in your real database. Use a throwaway
  `MONGO_DB` if that matters.
- The tunnel is HTTPS end to end, but it is a public URL to a machine on your
  desk. Don't leave it up unattended.

### Pinning the URL

A Quick Tunnel's hostname is random. If a tester needs a stable link, put a
domain on Cloudflare (free) and use a named tunnel:

```bash
cloudflared tunnel login
cloudflared tunnel create aptil
cloudflared tunnel route dns aptil demo.yourdomain.com
cloudflared tunnel run --url http://localhost:3000 aptil
```

Then run the app with `SHARE_URL=https://demo.yourdomain.com` and the same
overlay:

```bash
SHARE_URL=https://demo.yourdomain.com SHARE_PROXY_CIDR=172.16.0.0/12 \
  docker compose -f docker-compose.yml -f docker-compose.share.yml up -d --build
```

Still free; the domain is the only cost.

---

## 2. Real hosting, free tier

Render's **Blueprints** (`render.yaml`) are a paid feature, but individual free
services are not — you just create them by hand. The catch is that this stack
needs six things, and only some of them are free:

| Piece | Free option | Catch |
|---|---|---|
| Web (Next.js) | Render free web service | Sleeps after 15 min idle; ~50s cold start |
| API (FastAPI) | Render free web service | Same |
| **Celery worker** | **none on Render** | Background Workers are paid-only |
| Redis | Render Key Value free tier | Small, and free instances expire |
| MongoDB | **MongoDB Atlas M0** | Genuinely free, 512 MB, no expiry |
| Object storage | **Cloudflare R2** | Genuinely free to 10 GB, no egress fee |

So a free Render deployment gets you the app but **no worker** — meaning no job
discovery, no résumé parsing, no apply engine. Fine for showing the UI and the
signup/onboarding flow; not fine for demonstrating what the product does.

If you want the worker, the cheapest honest options are:

- **Fly.io** — one small shared-CPU machine per process, pay-as-you-go, a few
  dollars a month for all three; scales to zero.
- **A $5–6 VPS** (Hetzner CX22, DigitalOcean) — `docker compose up` and you're
  done, which is what this repo is actually built for. See `infra/scripts/deploy.sh`.

Both need `MONGO_URL` (Atlas) and the R2 variables — see
[`docs/storage-s3.md`](storage-s3.md).

---

## 3. Frontend only

If all you need is design feedback, deploy just the Next app to **Vercel** or
**Cloudflare Pages** (both free) and point `NEXT_PUBLIC_API_BASE_URL` at an API
running elsewhere. Marketing, auth screens, onboarding chrome and the legal
pages all render; anything that needs data will show its error state, which is
at least an honest one.

---

## Which to pick

- **Showing someone the app today:** option 1. One command, nothing to clean up.
- **A link that survives you closing your laptop:** option 2, on Fly or a VPS.
- **Design review only:** option 3.
