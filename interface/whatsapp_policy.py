"""
WorkMind WhatsApp Policy & Consent Manager
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Gestisce:
- Opt-in / opt-out dei contatti (GDPR compliant)
- Limiti messaggi per contatto (anti-spam)
- Consenso esplicito per comunicazioni commerciali
- Audit trail di tutti i consensi
- Policy ordini: cosa puo' e non puo' fare il bot
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from config.settings import DATA_DIR
from storage.audit_trail import get_audit, AuditEventType
from logging_system import get_logger, LogAction, LogStatus

log = get_logger("interface.whatsapp_policy")

_CONSENT_FILE = DATA_DIR / "whatsapp_consents.json"
_POLICY_FILE = DATA_DIR / "whatsapp_policy.json"

# Limiti di default
_MAX_MSGS_PER_CONTACT_PER_DAY = 20
_MAX_PROACTIVE_PER_DAY = 3  # Messaggi non richiesti (es. notifiche ordini)


class ConsentType(str, Enum):
    CHAT = "chat"              # Conversazione bidirezionale
    ORDERS = "orders"          # Ricezione/gestione ordini
    NOTIFICATIONS = "notifications"  # Notifiche proattive (spedizioni, conferme)
    MARKETING = "marketing"    # Comunicazioni promozionali


class ConsentStatus(str, Enum):
    GRANTED = "granted"
    REVOKED = "revoked"
    PENDING = "pending"


class WhatsAppPolicyManager:
    """Gestisce consensi, limiti e policy per WhatsApp Business."""

    def __init__(self) -> None:
        self._audit = get_audit()
        self._lock = threading.Lock()
        self._consents = self._load_consents()
        self._policy = self._load_policy()
        self._daily_counts: dict[str, dict[str, int]] = {}  # phone -> {date: count}

    # ── Consent Management ───────────────────────────────────────────────

    def request_consent(self, phone: str, consent_type: ConsentType, context: str = "") -> dict:
        """Registra richiesta di consenso (stato PENDING fino a conferma)."""
        with self._lock:
            key = f"{phone}:{consent_type}"
            entry = {
                "phone": phone,
                "type": consent_type,
                "status": ConsentStatus.PENDING,
                "requested_at": datetime.now(timezone.utc).isoformat(),
                "granted_at": None,
                "revoked_at": None,
                "context": context,
            }
            self._consents[key] = entry
            self._save_consents()

        self._audit.record(
            AuditEventType.SYSTEM,
            f"WhatsApp consenso richiesto: {consent_type} per {self._mask_phone(phone)}",
            actor="system",
            details={"context": context},
        )
        return entry

    def grant_consent(self, phone: str, consent_type: ConsentType) -> dict:
        """L'utente ha confermato il consenso."""
        with self._lock:
            key = f"{phone}:{consent_type}"
            entry = self._consents.get(key, {
                "phone": phone,
                "type": consent_type,
                "requested_at": datetime.now(timezone.utc).isoformat(),
                "context": "",
            })
            entry["status"] = ConsentStatus.GRANTED
            entry["granted_at"] = datetime.now(timezone.utc).isoformat()
            entry["revoked_at"] = None
            self._consents[key] = entry
            self._save_consents()

        self._audit.record(
            AuditEventType.FEEDBACK,
            f"WhatsApp consenso CONCESSO: {consent_type} da {self._mask_phone(phone)}",
            actor=phone,
        )
        log.info(f"Consenso {consent_type} concesso da {self._mask_phone(phone)}",
                 action=LogAction.CONFIG, status=LogStatus.OK)
        return entry

    def revoke_consent(self, phone: str, consent_type: ConsentType | None = None) -> list[str]:
        """Revoca consenso. Se consent_type=None, revoca TUTTI i consensi."""
        revoked = []
        with self._lock:
            for key, entry in self._consents.items():
                if entry["phone"] != phone:
                    continue
                if consent_type and entry["type"] != consent_type:
                    continue
                entry["status"] = ConsentStatus.REVOKED
                entry["revoked_at"] = datetime.now(timezone.utc).isoformat()
                revoked.append(entry["type"])
            self._save_consents()

        for ct in revoked:
            self._audit.record(
                AuditEventType.FEEDBACK,
                f"WhatsApp consenso REVOCATO: {ct} da {self._mask_phone(phone)}",
                actor=phone,
            )

        log.info(f"Consensi revocati per {self._mask_phone(phone)}: {revoked}",
                 action=LogAction.CONFIG, status=LogStatus.OK)
        return revoked

    def has_consent(self, phone: str, consent_type: ConsentType) -> bool:
        """Verifica se il contatto ha consenso attivo per il tipo specificato."""
        key = f"{phone}:{consent_type}"
        entry = self._consents.get(key)
        return entry is not None and entry.get("status") == ConsentStatus.GRANTED

    def get_consents(self, phone: str) -> list[dict]:
        """Ritorna tutti i consensi di un contatto."""
        return [e for e in self._consents.values() if e["phone"] == phone]

    def get_all_consented(self, consent_type: ConsentType) -> list[str]:
        """Ritorna tutti i numeri con consenso attivo per un tipo."""
        return [
            e["phone"] for e in self._consents.values()
            if e["type"] == consent_type and e["status"] == ConsentStatus.GRANTED
        ]

    # ── Rate Limiting ────────────────────────────────────────────────────

    def can_send(self, phone: str, is_proactive: bool = False) -> bool:
        """Verifica se possiamo inviare un messaggio al contatto."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        counts = self._daily_counts.get(phone, {})
        total_today = counts.get(today, 0)

        if is_proactive:
            proactive_key = f"{today}_proactive"
            proactive_today = counts.get(proactive_key, 0)
            if proactive_today >= _MAX_PROACTIVE_PER_DAY:
                return False

        return total_today < _MAX_MSGS_PER_CONTACT_PER_DAY

    def record_send(self, phone: str, is_proactive: bool = False) -> None:
        """Registra un messaggio inviato per rate limiting."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if phone not in self._daily_counts:
            self._daily_counts[phone] = {}
        counts = self._daily_counts[phone]
        counts[today] = counts.get(today, 0) + 1
        if is_proactive:
            proactive_key = f"{today}_proactive"
            counts[proactive_key] = counts.get(proactive_key, 0) + 1

    # ── Order Policy ─────────────────────────────────────────────────────

    def can_accept_orders(self, phone: str) -> bool:
        """Verifica se il contatto puo' effettuare ordini via WhatsApp."""
        if not self.has_consent(phone, ConsentType.ORDERS):
            return False
        # Verifica che ordini siano abilitati nella policy
        return self._policy.get("orders_enabled", True)

    def get_order_policy(self) -> dict:
        """Ritorna la policy per gli ordini."""
        return {
            "enabled": self._policy.get("orders_enabled", True),
            "require_confirmation": self._policy.get("order_require_confirmation", True),
            "max_order_value": self._policy.get("max_order_value", 0),  # 0 = no limit
            "allowed_categories": self._policy.get("order_categories", []),
            "blocked_words": self._policy.get("blocked_words", []),
            "business_hours_only": self._policy.get("business_hours_only", False),
            "business_hours": self._policy.get("business_hours", {"start": "09:00", "end": "18:00"}),
        }

    def update_policy(self, updates: dict) -> dict:
        """Aggiorna la policy WhatsApp."""
        with self._lock:
            self._policy.update(updates)
            self._save_policy()
        self._audit.record(
            AuditEventType.SYSTEM,
            f"WhatsApp policy aggiornata: {list(updates.keys())}",
            actor="admin",
        )
        return self._policy

    # ── Privacy Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _mask_phone(phone: str) -> str:
        """Maschera numero per i log (GDPR)."""
        if len(phone) > 6:
            return phone[:3] + "***" + phone[-3:]
        return "***"

    @staticmethod
    def opt_out_keywords() -> list[str]:
        """Parole chiave che triggerano opt-out automatico."""
        return ["stop", "annulla", "cancella", "unsubscribe", "basta", "esci", "no grazie"]

    # ── Persistence ──────────────────────────────────────────────────────

    def _load_consents(self) -> dict:
        if _CONSENT_FILE.exists():
            try:
                return json.loads(_CONSENT_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_consents(self) -> None:
        _CONSENT_FILE.write_text(
            json.dumps(self._consents, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _load_policy(self) -> dict:
        if _POLICY_FILE.exists():
            try:
                return json.loads(_POLICY_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "orders_enabled": True,
            "order_require_confirmation": True,
            "max_order_value": 0,
            "order_categories": [],
            "blocked_words": [],
            "business_hours_only": False,
            "business_hours": {"start": "09:00", "end": "18:00"},
            "welcome_message": (
                "Ciao! Sono l'assistente di {company_name}.\n\n"
                "Posso aiutarti con:\n"
                "- Informazioni sui nostri prodotti/servizi\n"
                "- Stato dei tuoi ordini\n"
                "- Assistenza generale\n\n"
                "Invia STOP in qualsiasi momento per disiscriverti."
            ),
            "consent_message": (
                "Per poterti assistere, ho bisogno del tuo consenso.\n\n"
                "Rispondi con:\n"
                "✅ SI — Accetto di ricevere messaggi\n"
                "📦 ORDINI — Voglio anche gestire ordini\n"
                "❌ NO — Non desidero comunicare\n\n"
                "Puoi revocare il consenso in qualsiasi momento con STOP."
            ),
        }

    def _save_policy(self) -> None:
        _POLICY_FILE.write_text(
            json.dumps(self._policy, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


# ─── Singleton ───────────────────────────────────────────────────────────────

_mgr: Optional[WhatsAppPolicyManager] = None


def get_wa_policy() -> WhatsAppPolicyManager:
    global _mgr
    if _mgr is None:
        _mgr = WhatsAppPolicyManager()
    return _mgr
