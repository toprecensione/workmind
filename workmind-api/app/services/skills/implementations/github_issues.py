"""GitHub issues skill — create/list issues from WorkMind."""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


async def create_issue(
    token: str,
    repo: str,
    title: str,
    body: str,
    labels: list[str] | None = None,
) -> dict | None:
    import httpx
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            f"https://api.github.com/repos/{repo}/issues",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"title": title, "body": body, "labels": labels or []},
        )
        if r.status_code == 201:
            data = r.json()
            return {"number": data["number"], "url": data["html_url"], "title": title}
        logger.error(f"GitHub issue creation failed {r.status_code}: {r.text}")
        return None


async def list_open_issues(
    token: str, repo: str, label: str | None = None
) -> list[dict]:
    import httpx
    params: dict = {"state": "open", "per_page": 20}
    if label:
        params["labels"] = label
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"https://api.github.com/repos/{repo}/issues",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            params=params,
        )
        if r.status_code == 200:
            return [
                {"number": i["number"], "title": i["title"], "url": i["html_url"]}
                for i in r.json()
            ]
        return []


async def run_anomaly_check(org_id: str, config: dict, db) -> dict:
    """Check for anomalies and auto-create GitHub issues."""
    from sqlalchemy import select, func
    from app.db.models import AuditLog
    from app.services.connectors import get_connector_registry
    from uuid import UUID
    from datetime import datetime, timezone, timedelta

    token = config.get("github_token", "")
    repo = config.get("repo", config.get("repository", ""))

    # Fall back to connector config if no inline token
    if not token:
        gh_cfg = await get_connector_registry().get_config(db, org_id, "github")
        if gh_cfg:
            token = gh_cfg.get("token", "")
            if not repo:
                repo = config.get("repo", "")

    if not token or not repo:
        return {"skipped": True, "reason": "no token/repo configured"}

    # Check for recent errors in audit log
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    errors = await db.scalar(
        select(func.count(AuditLog.id)).where(
            AuditLog.org_id == UUID(org_id),
            AuditLog.created_at >= since,
            AuditLog.event_type == "error",
        )
    )
    if errors and errors > int(config.get("error_threshold", 10)):
        issue = await create_issue(
            token,
            repo,
            f"⚠️ Anomalia rilevata — {errors} errori nelle ultime 24h",
            (
                f"WorkMind ha rilevato {errors} eventi di errore nelle ultime 24 ore.\n\n"
                f"Org: `{org_id}`\n"
                f"Data: {datetime.now().isoformat()}"
            ),
            labels=["workmind", "anomaly"],
        )
        return {"issue_created": issue}
    return {"errors_24h": errors or 0, "threshold": config.get("error_threshold", 10)}


def make_github_issues_job(org_id: str, config: dict):
    async def _run():
        from app.db.engine import get_session_factory
        SessionLocal = get_session_factory()
        async with SessionLocal() as db:
            return await run_anomaly_check(org_id, config, db)

    return _run
