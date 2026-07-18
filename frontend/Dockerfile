# Multi-stage production Dockerfile for the Next.js (App Router) frontend.
#
# NOTE: written before the Next.js app itself existed, so it targets the standard
# `create-next-app` (TypeScript + App Router) layout with a plain `next start` runner rather
# than assuming `output: "standalone"` is configured in next.config.ts. If standalone output
# is enabled later, this can be slimmed down to copy only `.next/standalone`, `.next/static`,
# and `public/` into the runner stage per Next.js's documented standalone Docker pattern.

# ---- deps: install dependencies with a reproducible, lockfile-pinned install ----
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

# ---- build: compile the production build ----
FROM node:20-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# NEXT_PUBLIC_* variables are inlined into the client bundle at build time, so the API base
# URL has to be available here (not just as a runtime env var) for the built app to call the
# right backend.
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

RUN npm run build

# ---- runner: slim image that just runs `next start` ----
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

# Plain `next start` runner: copy the whole app (node_modules, .next, public, package.json)
# rather than cherry-picking standalone output, since that requires next.config.ts to opt in
# with `output: "standalone"`.
COPY --from=build /app ./

EXPOSE 3000

CMD ["npm", "start"]
