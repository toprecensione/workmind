"""
WorkMind PII Masker
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Rileva e maschera dati personali (PII) nei log e nei report:
- Email → ***@***.***
- Telefono → ***-****
- Codice fiscale → ******XXXXXX
- IBAN → IT**-****-****-****-****
- Nomi propri (opzionale, basato su pattern)
- Indirizzi IP interni
"""

from __future__ import annotations

import re
from typing import Optional

from logging_system import get_logger, LogAction, LogStatus

log = get_logger("security.pii_masker")


class PiiMasker:
    """
    Maschera PII nel testo. Usato da:
    - Logger: prima di scrivere su file log
    - Reporter: prima di generare report
    - Chat: prima di inviare output al supervisore (opzionale)
    """

    def __init__(self, mask_names: bool = False) -> None:
        self._mask_names = mask_names
        self._patterns = self._build_patterns()

    def mask(self, text: str) -> str:
        """Maschera tutti i PII rilevati nel testo."""
        for pattern, replacement in self._patterns:
            text = pattern.sub(replacement, text)
        return text

    def detect(self, text: str) -> list[dict]:
        """Rileva PII senza mascherarli. Ritorna lista di {type, value, position}."""
        findings = []
        for pattern, _ in self._patterns:
            for m in pattern.finditer(text):
                findings.append({
                    "type": pattern.pattern[:30],
                    "value": m.group()[:20] + "...",
                    "position": m.start(),
                })
        return findings

    def has_pii(self, text: str) -> bool:
        """Ritorna True se il testo contiene PII."""
        for pattern, _ in self._patterns:
            if pattern.search(text):
                return True
        return False

    # ── Pattern ───────────────────────────────────────────────────────────────

    def _build_patterns(self) -> list[tuple[re.Pattern, str]]:
        patterns = [
            # Email
            (
                re.compile(r'\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b'),
                "***@***.***"
            ),
            # Codice Fiscale italiano
            (
                re.compile(r'\b[A-Z]{6}\d{2}[A-EHLMPRST]\d{2}[A-Z]\d{3}[A-Z]\b'),
                "CF:****"
            ),
            # IBAN
            (
                re.compile(r'\b[A-Z]{2}\d{2}\s?[A-Z0-9]{4}(?:\s?\d{4}){5}(?:\s?\d{1,4})?\b'),
                "IBAN:****"
            ),
            # Partita IVA (11 cifre precedute opzionalmente da IT)
            (
                re.compile(r'\b(?:IT)?\d{11}\b'),
                "PIVA:****"
            ),
            # Telefono italiano (+39, prefisso area, cellulare)
            (
                re.compile(r'\b(?:\+39\s?)?(?:0\d{1,4}[\s\-]?\d{4,8}|3\d{2}[\s\-]?\d{6,7})\b'),
                "TEL:****"
            ),
            # Carta di credito (4 gruppi di 4 cifre)
            (
                re.compile(r'\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b'),
                "CC:****"
            ),
            # IP interni (192.168.x.x, 10.x.x.x, 172.16-31.x.x)
            (
                re.compile(
                    r'\b(?:192\.168\.\d{1,3}\.\d{1,3}|'
                    r'10\.\d{1,3}\.\d{1,3}\.\d{1,3}|'
                    r'172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b'
                ),
                "IP:***"
            ),
        ]

        return patterns


# ─── Singleton ────────────────────────────────────────────────────────────────

_masker: Optional[PiiMasker] = None


def get_masker() -> PiiMasker:
    global _masker
    if _masker is None:
        _masker = PiiMasker()
    return _masker
