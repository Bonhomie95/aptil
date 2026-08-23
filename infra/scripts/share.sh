#!/usr/bin/env bash
# Put the local stack behind a public HTTPS URL, for free, for as long as this
# terminal stays open. For showing a tester the app — not a deployment.
#
#   ./infra/scripts/share.sh
#
# Uses a Cloudflare Quick Tunnel: no account, no card, no DNS. The URL is random
# and changes every run. Ctrl-C tears it down and restores the local config.
set -euo pipefail

cd "$(dirname "$0")/../.."
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.share.yml)
LOG="$(mktemp -t aptil-tunnel)"

need() { command -v "$1" >/dev/null 2>&1 || { echo "error: $1 is required"; exit 1; }; }
need docker

if ! command -v cloudflared >/dev/null 2>&1; then
  cat <<'MSG'
error: cloudflared is not installed.

  macOS:  brew install cloudflared
  Linux:  https://github.com/cloudflare/cloudflared/releases  (grab the binary)

It is a single static binary and needs no Cloudflare account for this.
MSG
  exit 1
fi

cleanup() {
  echo
  echo "Tearing the tunnel down…"
  [[ -n "${TUNNEL_PID:-}" ]] && kill "$TUNNEL_PID" 2>/dev/null || true
  echo "Restoring the local build (browser talks to localhost:8000 again)…"
  docker compose up -d --build web >/dev/null 2>&1 || true
  rm -f "$LOG"
  echo "Done."
}
trap cleanup EXIT INT TERM

echo "Starting the tunnel…"
cloudflared tunnel --url "http://localhost:${WEB_HOST_PORT:-3000}" \
  --no-autoupdate >"$LOG" 2>&1 &
TUNNEL_PID=$!

# The URL is only announced once the edge has accepted the connection.
SHARE_URL=""
for _ in $(seq 1 45); do
  SHARE_URL=$(grep -om1 'https://[a-z0-9-]*\.trycloudflare\.com' "$LOG" || true)
  [[ -n "$SHARE_URL" ]] && break
  kill -0 "$TUNNEL_PID" 2>/dev/null || { echo "tunnel exited:"; tail -20 "$LOG"; exit 1; }
  sleep 1
done
[[ -n "$SHARE_URL" ]] || { echo "timed out waiting for a tunnel URL:"; tail -20 "$LOG"; exit 1; }

export SHARE_URL
# The API must believe the X-Forwarded-For the web container sets, or every
# visitor lands in one rate-limit bucket. Trust the compose network only.
SHARE_PROXY_CIDR=$(docker network inspect "$(basename "$PWD")_default" \
  -f '{{range .IPAM.Config}}{{.Subnet}}{{end}}' 2>/dev/null || true)
export SHARE_PROXY_CIDR="${SHARE_PROXY_CIDR:-172.16.0.0/12}"

# Only `web` needs rebuilding — the API base URL is baked into its bundle. The
# api and worker just take new environment, so recreate them without a build.
echo "Rebuilding the web bundle for same-origin API calls…"
"${COMPOSE[@]}" up -d --build web
"${COMPOSE[@]}" up -d --no-build --force-recreate api worker

echo "Waiting for the app to answer through the tunnel…"
for _ in $(seq 1 40); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$SHARE_URL" || true)
  [[ "$code" == "200" ]] && break
  sleep 2
done

cat <<MSG

  ────────────────────────────────────────────────────────────
   Share this:  $SHARE_URL
  ────────────────────────────────────────────────────────────

   API calls  same origin, proxied by Next to the api container
   Rate limit per visitor (trusting XFF from $SHARE_PROXY_CIDR)
   Email links point at the tunnel

   Lives only while this terminal is open. Ctrl-C to stop.

MSG

wait "$TUNNEL_PID"
