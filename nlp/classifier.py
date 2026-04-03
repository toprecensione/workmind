"""
WorkMind Document Classifier
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Classifica documenti aziendali usando AI (DeepSeek per default, Claude per fallback).
Tiene conto delle correzioni del supervisore via KnowledgeBase.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from ai_client import AIClient, ModelRole
from ai_client.client import get_ai_client
from connectors.document_parser import ParsedDocument
from storage.knowledge_base import get_kb
from storage.audit_trail import get_audit, AuditEventType
from logging_system import get_logger, LogAction, LogStatus

log = get_logger("nlp.classifier")


@dataclass
class ClassificationResult:
    document_type: str       # fattura, ordine, contratto, DDT, ...
    confidence: float        # 0.0 – 1.0
    sub_type: str = ""       # sotto-tipo opzionale (es. fattura_attiva, fattura_passiva)
    language: str = ""
    reasoning: str = ""      # motivazione della classificazione


class DocumentClassifier:
    """
    Classifica documenti usando AI con context aziendale dalla KnowledgeBase.
    """

    def __init__(self, ai: Optional[AIClient] = None) -> None:
        self._ai = ai or get_ai_client()
        self._kb = get_kb()
        self._audit = get_audit()

    def classify(self, doc: ParsedDocument) -> ClassificationResult:
        """Classifica un singolo documento."""
        if not doc.is_ok:
            return ClassificationResult(document_type="errore", confidence=0.0, reasoning=doc.error or "")

        # Costruisci il prompt con contesto aziendale
        context = self._kb.build_context_prompt()
        corrections = self._kb.get_corrections()
        from config.company import get_company_config
        company = get_company_config()
        doc_types = company.document_types

        system_prompt = (
            "Sei un classificatore di documenti aziendali italiani. "
            "Analizza il testo e classifica il documento.\n\n"
            f"Tipi di documento validi: {', '.join(doc_types)}\n"
        )
        if context:
            system_prompt += f"\n{context}\n"
        if corrections:
            system_prompt += "\nCorrezioni precedenti (segui queste regole):\n"
            for c in corrections[-5:]:
                system_prompt += f"- '{c['wrong']}' va classificato come '{c['correct']}'\n"

        user_prompt = (
            f"Classifica questo documento.\n\n"
            f"Nome file: {doc.filename}\n"
            f"Estensione: {doc.extension}\n"
            f"Anteprima testo (primi 2000 caratteri):\n"
            f"---\n{doc.text[:2000]}\n---\n\n"
            f"Rispondi SOLO con un JSON valido:\n"
            f'{{"document_type": "...", "confidence": 0.95, "sub_type": "...", '
            f'"language": "it", "reasoning": "..."}}'
        )

        try:
            response = self._ai.complete_simple(
                user_prompt,
                system_prompt=system_prompt,
                role=ModelRole.FAST,
                max_tokens=256,
                temperature=0.1,
            )

            result = self._parse_response(response, doc_types)

            self._audit.record_ai_decision(
                model="classifier",
                prompt_summary=f"Classificazione {doc.filename}",
                output_summary=f"{result.document_type} ({result.confidence:.0%})",
                confidence=result.confidence,
                document_ref=doc.filename,
            )

            log.info(
                f"Classificato: {doc.filename} → {result.document_type} ({result.confidence:.0%})",
                action=LogAction.ANALYSE, status=LogStatus.OK,
            )
            return result

        except Exception as exc:
            log.error(f"Classificazione fallita per {doc.filename}: {exc}", action=LogAction.ANALYSE)
            return ClassificationResult(document_type="errore", confidence=0.0, reasoning=str(exc))

    def classify_batch(self, docs: list[ParsedDocument]) -> list[ClassificationResult]:
        return [self.classify(doc) for doc in docs]

    # ── Parsing risposta AI ───────────────────────────────────────────────────

    @staticmethod
    def _parse_response(text: str, valid_types: list[str]) -> ClassificationResult:
        text = text.strip()
        # Estrai JSON dal testo (potrebbe essere wrappato in markdown)
        if "```" in text:
            start = text.find("{")
            end = text.rfind("}") + 1
            text = text[start:end]

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Tentativo di estrazione manuale
            return ClassificationResult(
                document_type="altro",
                confidence=0.5,
                reasoning=f"Risposta AI non parsabile: {text[:200]}",
            )

        doc_type = data.get("document_type", "altro")
        if doc_type not in valid_types:
            doc_type = "altro"

        return ClassificationResult(
            document_type=doc_type,
            confidence=min(max(float(data.get("confidence", 0.5)), 0.0), 1.0),
            sub_type=data.get("sub_type", ""),
            language=data.get("language", "it"),
            reasoning=data.get("reasoning", ""),
        )
