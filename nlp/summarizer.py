"""
WorkMind Document Summarizer
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Genera riassunti strutturati di documenti aziendali.
Usa DeepSeek per task di routine, Claude per documenti complessi.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from ai_client import AIClient, ModelRole
from ai_client.client import get_ai_client
from connectors.document_parser import ParsedDocument
from storage.knowledge_base import get_kb
from logging_system import get_logger, LogAction, LogStatus

log = get_logger("nlp.summarizer")


@dataclass
class DocumentSummary:
    title: str
    summary: str             # riassunto breve (2-3 frasi)
    key_points: list[str] = field(default_factory=list)  # punti chiave
    action_items: list[str] = field(default_factory=list)  # azioni richieste
    urgency: str = "normal"  # low | normal | high | critical
    document_type: str = ""
    language: str = "it"


class DocumentSummarizer:
    """
    Genera riassunti concisi e actionable di documenti aziendali.
    """

    def __init__(self, ai: Optional[AIClient] = None) -> None:
        self._ai = ai or get_ai_client()
        self._kb = get_kb()

    def summarize(
        self,
        doc: ParsedDocument,
        doc_type: str = "",
        detail_level: str = "normal",
    ) -> DocumentSummary:
        """
        Genera un riassunto del documento.
        detail_level: "brief" | "normal" | "detailed"
        """
        if not doc.is_ok:
            return DocumentSummary(
                title=doc.filename,
                summary=f"Documento non leggibile: {doc.error}",
            )

        context = self._kb.build_context_prompt()

        length_instruction = {
            "brief": "2-3 frasi",
            "normal": "4-6 frasi",
            "detailed": "8-12 frasi",
        }.get(detail_level, "4-6 frasi")

        system_prompt = (
            "Sei un assistente operativo che genera riassunti di documenti aziendali italiani. "
            "Sii conciso e focalizzato su informazioni actionable.\n"
        )
        if context:
            system_prompt += f"\n{context}\n"

        user_prompt = (
            f"Riassumi questo documento in italiano.\n\n"
            f"File: {doc.filename} (tipo: {doc_type or 'sconosciuto'})\n"
            f"Lunghezza richiesta: {length_instruction}\n\n"
            f"Testo:\n---\n{doc.text[:4000]}\n---\n\n"
            f"Rispondi SOLO con un JSON valido:\n"
            f'{{"title": "...", "summary": "...", '
            f'"key_points": ["punto 1", "punto 2"], '
            f'"action_items": ["azione 1"], '
            f'"urgency": "normal"}}'
        )

        try:
            response = self._ai.complete_simple(
                user_prompt,
                system_prompt=system_prompt,
                role=ModelRole.FAST,
                max_tokens=512,
                temperature=0.2,
            )
            result = self._parse_response(response)
            result.document_type = doc_type
            log.info(
                f"Riassunto generato: {doc.filename} → {result.title}",
                action=LogAction.ANALYSE, status=LogStatus.OK,
            )
            return result
        except Exception as exc:
            log.error(f"Summarization fallita per {doc.filename}: {exc}", action=LogAction.ANALYSE)
            return DocumentSummary(title=doc.filename, summary=f"Errore: {exc}")

    def summarize_batch(self, docs: list[ParsedDocument]) -> list[DocumentSummary]:
        return [self.summarize(doc) for doc in docs]

    def summarize_emails(self, emails: list[dict]) -> str:
        """Genera un digest delle email recenti."""
        if not emails:
            return "Nessuna email recente da riassumere."

        texts = []
        for i, em in enumerate(emails[:20], 1):
            texts.append(f"{i}. Da: {em.get('sender', '?')} | Oggetto: {em.get('subject', '?')}")
            body = em.get("body_plain", em.get("body_text", ""))[:500]
            if body:
                texts.append(f"   {body.strip()[:200]}")

        user_prompt = (
            f"Hai {len(emails)} email recenti. Genera un digest in italiano:\n\n"
            + "\n".join(texts)
            + "\n\nCrea un riassunto breve (max 10 righe) evidenziando email urgenti o importanti."
        )

        try:
            return self._ai.complete_simple(
                user_prompt,
                system_prompt="Sei un assistente che fa il digest delle email aziendali.",
                role=ModelRole.FAST,
                max_tokens=512,
            )
        except Exception as exc:
            return f"Errore generazione digest email: {exc}"

    # ── Parsing ───────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_response(text: str) -> DocumentSummary:
        text = text.strip()
        if "```" in text:
            start = text.find("{")
            end = text.rfind("}") + 1
            text = text[start:end]

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return DocumentSummary(title="Documento", summary=text[:500])

        return DocumentSummary(
            title=data.get("title", "Documento"),
            summary=data.get("summary", ""),
            key_points=data.get("key_points", []),
            action_items=data.get("action_items", []),
            urgency=data.get("urgency", "normal"),
        )
