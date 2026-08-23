FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
# `npm ci` respects the lockfile exactly, so a build is reproducible.
RUN npm ci --omit=dev --ignore-scripts || npm install --ignore-scripts

FROM node:22-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --ignore-scripts || npm install --ignore-scripts
COPY . .

# NEXT_PUBLIC_* values are inlined into the client bundle at BUILD time, so they
# must be present here. Passing them only at runtime (env_file in compose) left
# the shipped bundle pointing at http://localhost:8000 in production.
# "/" means same-origin once the trailing slash is stripped, which is right
# behind any reverse proxy or tunnel. It is the safer default than localhost:
# a build that forgets to pass this then works everywhere except a laptop,
# rather than only on one. docker-compose passes the localhost value for local
# dev explicitly.
ARG NEXT_PUBLIC_API_BASE_URL=/
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "server.js"]
