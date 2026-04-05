"""
WorkMind Feature Request Pipeline
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Gestisce il ciclo di vita delle richieste di funzionalita':
1. Utente chiede feature (Telegram/Chat)
2. DeepSeek classifica: AUTO / REVIEW / BLOCK
3. Se AUTO → esegue direttamente (config, UI tweaks, report)
4. Se REVIEW → crea GitHub Issue, notifica master, attende /approve
5. Se BLOCK → rifiuta, notifica master
6. Approvata → crea branch + PR su GitHub
7. Master merge → auto-deploy su Bender
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

import httpx

from config.settings import DATA_DIR, config
from ai_client.client import get_ai_client, ModelRole
from storage.audit_trail import get_audit, AuditEventType
from logging_system import get_logger, LogAction, LogStatus

log = get_logger("mindwork.feature_requests")

_REQUESTS_FILE = DATA_DIR / "feature_requests.json"
_GITHUB_API = "https://api.github.com"


class RequestLevel(str, Enum):
    AUTO = "auto"        # Config, personalizzazioni, report → esecuzione diretta
    REVIEW = "review"    # Nuove funzionalita', connettori → richiede approvazione master
    BLOCK = "block"      # Sicurezza, credenziali, accesso dati → rifiutato automaticamente


class RequestStatus(str, Enum):
    PENDING = "pending"          # In attesa di classificazione/approvazione
    CLASSIFIED = "classified"    # Classificata, in attesa di approvazione (REVIEW)
    APPROVED = "approved"        # Approvata dal master
    REJECTED = "rejected"        # Rifiutata dal master
    ISSUE_CREATED = "issue_created"  # Issue GitHub creata
    PR_CREATED = "pr_created"    # PR creata su GitHub
    DEPLOYED = "deployed"        # Deployata in produzione
    AUTO_DONE = "auto_done"      # Eseguita automaticamente (livello AUTO)
    BLOCKED = "blocked"          # Bloccata automaticamente (livello BLOCK)


# ── Classification prompt ────────────────────────────────────────────────────

_CLASSIFY_PROMPT = """Sei il sistema di classificazione di WorkMind.
Un utente ha richiesto una nuova funzionalita'. Devi classificarla in uno di tre livelli:

AUTO — Modifiche minori che NON richiedono nuovo codice:
- Cambiare configurazioni (orari report, soglie, parametri)
- Personalizzazioni UI (colori, testi, layout)
- Nuovi template di report con dati esistenti
- Aggiungere termini al glossario o fatti alla knowledge base
- Modifiche a impostazioni esistenti

REVIEW — Funzionalita' che richiedono NUOVO CODICE:
- Nuovi connettori (database, API esterne, servizi)
- Nuove analisi o algoritmi
- Integrazioni con sistemi esterni
- Nuove pagine o sezioni della UI
- Nuovi comandi bot
- Modifiche alla logica di business

BLOCK — Richieste PERICOLOSE o fuori ambito:
- Accesso/modifica credenziali di sicurezza
- Cancellazione dati
- Accesso a sistemi non autorizzati
- Richieste che violano la privacy
- Operazioni di scrittura su database aziendali
- Qualsiasi cosa che potrebbe causare danni

Rispondi SOLO con un JSON valido:
{"level": "auto|review|block", "title": "titolo breve", "description": "descrizione tecnica di cosa serve", "reason": "perche' questa classificazione"}

Richiesta utente: """


class FeatureRequestManager:
    """Gestisce l'intero ciclo feature request."""

    def __init__(self) -> None:
        self._ai = get_ai_client()
        self._audit = get_audit()
        self._requests = self._load()
        self._lock = threading.Lock()
        self._github_token = config.update.github_token or os.getenv("GITHUB_TOKEN", "")
        self._repo = os.getenv("WORKMIND_GITHUB_REPO", "toprecensione/workmind")
        self._master_chat_ids = self._load_master_ids()

    # ── Public API ────────────────────────────────────────────────────────

    def submit_request(
        self,
        text: str,
        submitted_by: str = "user",
        source: str = "chat",
        chat_id: int = 0,
    ) -> dict:
        """
        Sottomette una nuova richiesta. Ritorna il request dict con classificazione.
        """
        # 1. Classifica con DeepSeek
        classification = self._classify(text)

        req_id = self._next_id()
        request = {
            "id": req_id,
            "text": text,
            "submitted_by": submitted_by,
            "source": source,
            "chat_id": chat_id,
            "level": classification["level"],
            "title": classification["title"],
            "description": classification["description"],
            "reason": classification["reason"],
            "status": RequestStatus.CLASSIFIED,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "github_issue": None,
            "github_pr": None,
        }

        # 2. Agisci in base al livello
        if classification["level"] == RequestLevel.BLOCK:
            request["status"] = RequestStatus.BLOCKED
            self._audit.record(
                AuditEventType.SYSTEM,
                f"Richiesta #{req_id} BLOCCATA: {classification['title']}",
                actor=submitted_by,
                details={"reason": classification["reason"]},
            )

        elif classification["level"] == RequestLevel.AUTO:
            request["status"] = RequestStatus.AUTO_DONE
            self._audit.record(
                AuditEventType.SYSTEM,
                f"Richiesta #{req_id} AUTO: {classification['title']}",
                actor="system",
            )

        else:  # REVIEW
            request["status"] = RequestStatus.PENDING
            # Crea issue su GitHub se token disponibile
            if self._github_token:
                issue = self._create_github_issue(request)
                if issue:
                    request["github_issue"] = issue
                    request["status"] = RequestStatus.ISSUE_CREATED

        # 3. Salva
        with self._lock:
            self._requests.append(request)
            self._save()

        log.info(
            f"Feature request #{req_id}: [{classification['level']}] {classification['title']}",
            action=LogAction.CONFIG, status=LogStatus.OK,
        )

        return request

    def approve(self, req_id: int, approved_by: str = "master") -> dict | None:
        """Master approva una richiesta REVIEW."""
        req = self._find(req_id)
        if not req:
            return None
        if req["status"] not in (RequestStatus.PENDING, RequestStatus.ISSUE_CREATED, RequestStatus.CLASSIFIED):
            return req

        req["status"] = RequestStatus.APPROVED
        req["updated_at"] = datetime.now(timezone.utc).isoformat()
        req["approved_by"] = approved_by

        self._audit.record(
            AuditEventType.FEEDBACK,
            f"Richiesta #{req_id} APPROVATA da {approved_by}: {req['title']}",
            actor=approved_by,
        )

        # Se non c'e' gia' una issue, creala
        if not req.get("github_issue") and self._github_token:
            issue = self._create_github_issue(req)
            if issue:
                req["github_issue"] = issue

        self._save()
        return req

    def reject(self, req_id: int, rejected_by: str = "master", reason: str = "") -> dict | None:
        """Master rifiuta una richiesta."""
        req = self._find(req_id)
        if not req:
            return None

        req["status"] = RequestStatus.REJECTED
        req["updated_at"] = datetime.now(timezone.utc).isoformat()
        req["rejected_by"] = rejected_by
        req["reject_reason"] = reason

        # Chiudi issue GitHub se esiste
        if req.get("github_issue") and self._github_token:
            self._close_github_issue(req["github_issue"]["number"], reason)

        self._audit.record(
            AuditEventType.FEEDBACK,
            f"Richiesta #{req_id} RIFIUTATA da {rejected_by}: {req['title']}",
            actor=rejected_by,
            details={"reason": reason},
        )

        self._save()
        return req

    def list_requests(
        self,
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Lista richieste, opzionalmente filtrate per status."""
        reqs = list(reversed(self._requests))
        if status:
            reqs = [r for r in reqs if r["status"] == status]
        return reqs[:limit]

    def get_request(self, req_id: int) -> dict | None:
        return self._find(req_id)

    def pending_count(self) -> int:
        return sum(
            1 for r in self._requests
            if r["status"] in (RequestStatus.PENDING, RequestStatus.CLASSIFIED, RequestStatus.ISSUE_CREATED)
        )

    def stats(self) -> dict:
        statuses = {}
        for r in self._requests:
            s = r["status"]
            statuses[s] = statuses.get(s, 0) + 1
        return {
            "total": len(self._requests),
            "by_status": statuses,
            "pending": self.pending_count(),
        }

    # ── Master chat ID management ─────────────────────────────────────────

    def register_master(self, chat_id: int) -> None:
        """Registra un chat_id come master (puo' approvare/rifiutare)."""
        if chat_id not in self._master_chat_ids:
            self._master_chat_ids.append(chat_id)
            self._save_master_ids()

    def is_master(self, chat_id: int) -> bool:
        return chat_id in self._master_chat_ids

    def get_master_chat_ids(self) -> list[int]:
        return list(self._master_chat_ids)

    # ── Classification ────────────────────────────────────────────────────

    def _classify(self, text: str) -> dict:
        """Classifica la richiesta con DeepSeek."""
        try:
            response = self._ai.complete_simple(
                _CLASSIFY_PROMPT + text,
                role=ModelRole.FAST,
                max_tokens=500,
                temperature=0.1,
            )
            # Parsing JSON dalla risposta
            # Cerca il primo { e ultimo }
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(response[start:end])
                return {
                    "level": data.get("level", "review"),
                    "title": data.get("title", text[:80]),
                    "description": data.get("description", text),
                    "reason": data.get("reason", ""),
                }
        except Exception as exc:
            log.warning(f"Errore classificazione: {exc}", action=LogAction.MONITOR)

        # Fallback: tutto va in REVIEW per sicurezza
        return {
            "level": "review",
            "title": text[:80],
            "description": text,
            "reason": "Classificazione automatica fallita — richiede review manuale",
        }

    # ── GitHub Integration ────────────────────────────────────────────────

    def _create_github_issue(self, req: dict) -> dict | None:
        """Crea una Issue su GitHub per la richiesta."""
        if not self._github_token:
            return None
        try:
            level = req["level"].upper()
            labels = ["feature-request"]
            if req["level"] == RequestLevel.AUTO:
                labels.append("auto")
            elif req["level"] == RequestLevel.REVIEW:
                labels.append("needs-review")

            body = (
                f"## Feature Request #{req['id']}\n\n"
                f"**Richiesta da:** {req['submitted_by']} ({req['source']})\n"
                f"**Livello:** `{level}`\n"
                f"**Data:** {req['created_at']}\n\n"
                f"### Descrizione\n{req['description']}\n\n"
                f"### Richiesta originale\n> {req['text']}\n\n"
                f"### Classificazione AI\n{req['reason']}\n\n"
                f"---\n*Creata automaticamente da WorkMind*"
            )

            with httpx.Client(timeout=15) as client:
                resp = client.post(
                    f"{_GITHUB_API}/repos/{self._repo}/issues",
                    headers={
                        "Authorization": f"token {self._github_token}",
                        "Accept": "application/vnd.github+json",
                    },
                    json={
                        "title": f"[{level}] {req['title']}",
                        "body": body,
                        "labels": labels,
                    },
                )
                if resp.status_code in (200, 201):
                    data = resp.json()
                    log.info(f"GitHub Issue #{data['number']} creata per request #{req['id']}",
                             action=LogAction.CONFIG, status=LogStatus.OK)
                    return {
                        "number": data["number"],
                        "url": data["html_url"],
                    }
                else:
                    log.warning(f"GitHub Issue creation failed: {resp.status_code} {resp.text[:200]}",
                                action=LogAction.MONITOR)
        except Exception as exc:
            log.warning(f"Errore creazione GitHub Issue: {exc}", action=LogAction.MONITOR)
        return None

    def _close_github_issue(self, issue_number: int, comment: str = "") -> None:
        """Chiude una Issue su GitHub."""
        if not self._github_token:
            return
        try:
            with httpx.Client(timeout=15) as client:
                if comment:
                    client.post(
                        f"{_GITHUB_API}/repos/{self._repo}/issues/{issue_number}/comments",
                        headers={
                            "Authorization": f"token {self._github_token}",
                            "Accept": "application/vnd.github+json",
                        },
                        json={"body": f"Rifiutata: {comment}\n\n*— WorkMind*"},
                    )
                client.patch(
                    f"{_GITHUB_API}/repos/{self._repo}/issues/{issue_number}",
                    headers={
                        "Authorization": f"token {self._github_token}",
                        "Accept": "application/vnd.github+json",
                    },
                    json={"state": "closed"},
                )
        except Exception as exc:
            log.warning(f"Errore chiusura GitHub Issue: {exc}", action=LogAction.MONITOR)

    # ── Persistence ───────────────────────────────────────────────────────

    def _load(self) -> list[dict]:
        if _REQUESTS_FILE.exists():
            try:
                return json.loads(_REQUESTS_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return []

    def _save(self) -> None:
        _REQUESTS_FILE.write_text(
            json.dumps(self._requests, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _find(self, req_id: int) -> dict | None:
        for r in self._requests:
            if r["id"] == req_id:
                return r
        return None

    def _next_id(self) -> int:
        if not self._requests:
            return 1
        return max(r["id"] for r in self._requests) + 1

    def _load_master_ids(self) -> list[int]:
        f = DATA_DIR / "master_chat_ids.json"
        if f.exists():
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                pass
        return []

    def _save_master_ids(self) -> None:
        f = DATA_DIR / "master_chat_ids.json"
        f.write_text(json.dumps(self._master_chat_ids), encoding="utf-8")


# ─── Singleton ────────────────────────────────────────────────────────────────

_mgr: Optional[FeatureRequestManager] = None


def get_feature_manager() -> FeatureRequestManager:
    global _mgr
    if _mgr is None:
        _mgr = FeatureRequestManager()
    return _mgr
