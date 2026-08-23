import { NextResponse, type NextRequest } from "next/server";

/**
 * Same-origin API proxy.
 *
 * When API_PROXY_TARGET is set, the browser calls /api/... on this origin and
 * this forwards it to the API server-side. No CORS to configure, and nothing
 * environment-specific baked into the client bundle, so one image runs
 * everywhere.
 *
 * Why here and not `rewrites()` in next.config.mjs, which is what this used to
 * be: `rewrites()` is evaluated at BUILD time and serialised into
 * `.next/routes-manifest.json`. With `output: "standalone"` the config file is
 * not even shipped, so setting API_PROXY_TARGET at runtime produced an empty
 * rewrite table and every /api call 404'd on the Next router. Middleware is
 * evaluated per request, so the target really can change with a restart rather
 * than a rebuild — which is what the deployment docs promise.
 */
const target = process.env.API_PROXY_TARGET?.replace(/\/$/, "");

export function middleware(request: NextRequest) {
  if (target) {
    const url = new URL(request.nextUrl.pathname + request.nextUrl.search, target);
    return NextResponse.rewrite(url);
  }

  // Nothing is configured to serve this path. In direct mode the browser talks
  // to the API's own origin and never asks us for /api at all, so a request
  // arriving here means the bundle was built same-origin while the server was
  // started without a target — the exact state a `docker compose up --build web`
  // leaves behind if it drops the share/deploy overlay.
  //
  // Falling through gave a bare 404 per call, which reads like a missing route
  // and sends you hunting through the API. Say what is actually wrong.
  return NextResponse.json(
    {
      detail:
        "This server has no API_PROXY_TARGET configured, so /api requests have " +
        "nowhere to go. Restart the web service with it set (see docs/share-a-link.md).",
    },
    { status: 503 },
  );
}

export const config = {
  // Only the API surface. Everything else is served by Next directly, and
  // running middleware on every asset request would be pure overhead.
  // NOTE: this shadows /api entirely — the app has no Next route handlers
  // there, and adding one would need this matcher narrowed first.
  matcher: ["/api/:path*", "/health"],
};
