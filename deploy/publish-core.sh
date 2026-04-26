#!/usr/bin/env bash
# Publish core WorkMind to the public GitHub repo (workmind).
# Orphan branch — clean history, no secrets, no node_modules.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

WORK_DIR="$(mktemp -d)"
echo "Working in: $WORK_DIR"

# Export clean tree — respects .gitignore
git checkout-index -a --prefix="$WORK_DIR/"

cd "$WORK_DIR"
git init
git checkout -b main

# Strip everything not wanted in the public repo
rm -rf workmind-api/clients/medic/
rm -rf "workmind-frontend/src/routes/(medic)/"
rm -rf workmind-frontend/node_modules/
rm -rf workmind-frontend/.svelte-kit/
rm -rf workmind-frontend/build/
rm -f  workmind-frontend/.env workmind-frontend/.env.production
rm -f  .env .env.bender .env.staging .env.local
rm -f  workmind-api/app/dependencies.py.bak
rm -rf workmind-worker/ 2>/dev/null || true

# Ensure node_modules is gitignored in the published version
grep -q 'node_modules' workmind-frontend/.gitignore 2>/dev/null || \
  echo -e "\nnode_modules/\nbuild/\n.svelte-kit/" >> workmind-frontend/.gitignore

# Add clients/README
mkdir -p workmind-api/clients
cat > workmind-api/clients/README.md << 'MDEOF'
# Client Extensions

Domain-specific modules. Each client is a self-contained package:

```
clients/<name>/
├── __init__.py
├── models.py    # SQLAlchemy models (Base from app.db.base)
├── routes.py    # FastAPI router + ROUTE_PREFIX + SECTOR
├── tasks.py     # Celery tasks (optional)
└── skills/      # Custom skills (optional)
```

app/main.py auto-discovers and loads every clients/<name>/routes.py.
Frontend pages go in src/routes/(<name>)/, built with VITE_CLIENT=<name>.
MDEOF

git add -A
git commit -m "feat: WorkMind v2 — AI business assistant platform

Core features:
- FastAPI + SQLAlchemy 2.x async API
- Auth: JWT tokens, 2FA TOTP, password reset via email
- Chat: SSE streaming, multi-model AI routing (DeepSeek/Ollama/OpenAI)
- Knowledge Base: document ingestion, vector search (pgvector), RAG
- Admin: users, orgs, connectors, audit log, system metrics, Prometheus
- Multi-client: plug-in domain extensions via clients/<name>/routes.py
- SvelteKit frontend with VITE_CLIENT build-time client selector

Stack: Python 3.13, FastAPI, PostgreSQL+pgvector, Redis, Celery, SvelteKit"

git remote add origin git@github-core:toprecensione/workmind.git
git push origin main --force

cd "$REPO_ROOT"
rm -rf "$WORK_DIR"
echo "Done: https://github.com/toprecensione/workmind"
