/** @type {import('next').NextConfig} */

// Where the browser should send API calls.
//
// Two supported modes:
//
//  1. SAME-ORIGIN PROXY (recommended for Render, a tunnel, and anywhere behind
//     one host). Set API_PROXY_TARGET to the API's internal URL. The browser
//     then calls /api/... on this origin and src/middleware.ts forwards it
//     server-side. No CORS, and nothing about the API URL is baked into the
//     client bundle, so the same image works in every environment.
//
//     The proxy lives in middleware, NOT in rewrites() here: rewrites are
//     resolved at build time into .next/routes-manifest.json, so a runtime-only
//     API_PROXY_TARGET silently produced an empty rewrite table.
//
//  2. DIRECT (the local docker-compose default). Set NEXT_PUBLIC_API_BASE_URL
//     at BUILD time; it is inlined into the browser bundle. Set it to "/" to
//     mean same-origin — an empty string does not survive a Docker build arg,
//     which falls back to the Dockerfile's ARG default.

const nextConfig = {
  // Standalone output for a small, self-contained Docker image (no Vercel needed).
  output: "standalone",
  reactStrictMode: true,
  // Do not emit AGENTS.md / CLAUDE.md into the repo on every build.
  agentRules: false,

  // The API sets its own headers; these cover the pages Next serves directly.
  // In production Caddy layers the CSP on top (see infra/caddy/Caddyfile).
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          {
            key: "Permissions-Policy",
            value: "geolocation=(), microphone=(), camera=()",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
