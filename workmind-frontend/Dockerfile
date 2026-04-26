# ── Stage 1: build ────────────────────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app
COPY package.json ./
RUN npm install

COPY . .
RUN npm run build

# ── Stage 2: serve (just the static output) ───────────────────────────────────
# The build output is copied into an nginx-served volume at deploy time.
# This stage exposes the /app/build directory for the compose copy step.
FROM alpine:3.19 AS dist
COPY --from=builder /app/build /dist
