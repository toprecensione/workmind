"""
WorkMind Hallucination Guard
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Valida gli output dell'AI prima di presentarli al supervisore.
Controlla:
- Coerenza interna (entità menzionate devono esistere nei dati)
- Numeri inventati (importi, date, codici non presenti nel testo originale)
- Fiducia troppo alta su dati ambigui
- Contraddizioni con la KnowledgeBase
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

from ai_client import AIClient, ModelRole
from ai_client.client import get_ai_client
from storage.knowledge_base import get_kb
from logging_system import get_logger, LogAction, LogStatus

log = get_logger("nlp.hallucination_guard")


@dataclass
class ValidationResult:
    is_valid: bool
    confidence: float        # 0.0–1.0: quanto siamo sicuri che NON sia un'allucinazione
    issues: list[str] = field(default_factory=list)
    corrected_text: str = ""  # testo corretto se possibile
    original_text: str = ""


class HallucinationGuard:
    """
    Filtro anti-allucinazione. Ogni output AI passa di qui prima di essere
    mostrato al supervisore.
    """

    def __init__(self, ai: Optional[AIClient] = None) -> None:
        self._ai = ai or get_ai_client()
        self._kb = get_kb()

    def validate(
        self,
        ai_output: str,
        source_text: str,
        context: str = "",
    ) -> ValidationResult:
        """
        Valida l'output AI contro il testo sorgente.

        Args:
            ai_output: il testo generato dall'AI
            source_text: il testo originale del documento
            context: contesto aggiuntivo (tipo doc, query utente, ecc.)
        """
        issues = []

        # Check 1: numeri inventati
        invented = self._check_invented_numbers(ai_output, source_text)
        if invented:
            issues.extend(invented)

        # Check 2: entità non presenti nel source
        phantom = self._check_phantom_entities(ai_output, source_text)
        if phantom:
            issues.extend(phantom)

        # Check 3: contraddizioni con KnowledgeBase
        contradictions = self._check_kb_contradictions(ai_output)
        if contradictions:
            issues.extend(contradictions)

        # Check 4: AI cross-validation (per output critici)
        if not issues and len(ai_output) > 200:
            ai_issues = self._ai_cross_validate(ai_output, source_text, context)
            issues.extend(ai_issues)

        is_valid = len(issues) == 0
        confidence = 1.0 - min(len(issues) * 0.2, 0.9)

        if not is_valid:
            log.warning(
                f"Hallucination guard: {len(issues)} problemi rilevati",
                action=LogAction.VALIDATE, status=LogStatus.WARNING,
                extra={"issues": issues[:3]},
            )

        return ValidationResult(
            is_valid=is_valid,
            confidence=confidence,
            issues=issues,
            original_text=ai_output,
        )

    def validate_entities(self, entities: list[dict], source_text: str) -> list[dict]:
        """Filtra entità probabilmente inventate dall'AI."""
        validated = []
        source_lower = source_text.lower()
        for e in entities:
            value = str(e.get("value", "")).lower()
            if len(value) > 3 and value in source_lower:
                validated.append(e)
            elif e.get("confidence", 0) >= 0.9:
                validated.append(e)
            else:
                log.debug(
                    f"Entità scartata (non trovata nel source): {e.get('value', '')}",
                    action=LogAction.VALIDATE,
                )
        return validated

    # ── Check: numeri inventati ────────────────────────────────────────────────

    @staticmethod
    def _check_invented_numbers(output: str, source: str) -> list[str]:
        issues = []
        # Trova tutti i numeri significativi nell'output (>2 cifre)
        output_numbers = set(re.findall(r'\b\d[\d.,]{2,}\b', output))
        source_numbers = set(re.findall(r'\b\d[\d.,]{2,}\b', source))

        for num in output_numbers:
            # Normalizza: rimuovi separatori migliaia
            normalized = num.replace(".", "").replace(",", ".")
            source_normalized = {n.replace(".", "").replace(",", ".") for n in source_numbers}
            if normalized not in source_normalized and num not in source:
                issues.append(f"Numero '{num}' non trovato nel testo sorgente (possibile allucinazione)")

        return issues

    # ── Check: entità fantasma ────────────────────────────────────────────────

    @staticmethod
    def _check_phantom_entities(output: str, source: str) -> list[str]:
        issues = []
        source_lower = source.lower()

        # Cerca nomi propri nell'output (parole maiuscole che sembrano nomi)
        proper_nouns = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b', output)
        for name in proper_nouns:
            if name.lower() not in source_lower:
                # Verifica che non sia una frase comune
                words = name.split()
                if len(words) <= 3 and all(len(w) > 2 for w in words):
                    issues.append(f"Nome '{name}' non trovato nel testo sorgente")

        return issues

    # ── Check: contraddizioni con KB ──────────────────────────────────────────

    def _check_kb_contradictions(self, output: str) -> list[str]:
        issues = []
        facts = self._kb.get_facts()
        corrections = self._kb.get_corrections()

        output_lower = output.lower()

        for correction in corrections:
            wrong = correction.get("wrong", "").lower()
            if wrong and wrong in output_lower:
                correct = correction.get("correct", "")
                issues.append(
                    f"L'output usa '{wrong}' ma dovrebbe essere '{correct}' "
                    f"(correzione del supervisore)"
                )

        return issues

    # ── AI cross-validation ───────────────────────────────────────────────────

    def _ai_cross_validate(
        self,
        output: str,
        source: str,
        context: str,
    ) -> list[str]:
        """Usa l'AI stessa per verificare coerenza (self-check)."""
        prompt = (
            "Verifica se il seguente output contiene informazioni inventate, "
            "non presenti nel testo sorgente. Rispondi SOLO con un JSON:\n"
            '{"issues": ["problema 1", ...]} oppure {"issues": []}\n\n'
            f"OUTPUT DA VERIFICARE:\n{output[:1500]}\n\n"
            f"TESTO SORGENTE:\n{source[:2000]}"
        )

        try:
            response = self._ai.complete_simple(
                prompt,
                system_prompt="Sei un verificatore di accuratezza. Segnala SOLO problemi certi.",
                role=ModelRole.FAST,
                max_tokens=256,
                temperature=0.0,
            )
            data = json.loads(response.strip() if "{" in response else '{"issues": []}')
            return data.get("issues", [])
        except Exception:
            return []
