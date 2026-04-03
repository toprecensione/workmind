"""
WorkMind Suggestion Engine
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Genera suggerimenti operativi per il supervisore basati su:
- Anomalie rilevate dal PatternDetector
- Colli di bottiglia dal TaskDecomposer
- Trend nei dati del gestionale
- Conoscenza accumulata nella KnowledgeBase

Ogni suggerimento ha uno scoring impatto/effort e simulazioni what-if.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from ai_client import AIClient, ModelRole
from ai_client.client import get_ai_client
from storage.knowledge_base import get_kb
from storage.audit_trail import get_audit, AuditEventType
from logging_system import get_logger, LogAction, LogStatus

log = get_logger("mindwork.suggestion_engine")


@dataclass
class Suggestion:
    id: str
    title: str
    description: str
    category: str = ""       # efficiency | quality | cost | risk | automation
    impact: str = ""         # low | medium | high | critical
    effort: str = ""         # low | medium | high
    priority_score: float = 0.0   # 0.0–10.0 (calcolato da impatto/effort)
    evidence: list[str] = field(default_factory=list)
    what_if: str = ""        # simulazione: "Se implementi questo, allora..."
    status: str = "proposed"  # proposed | accepted | rejected | implemented
    created_at: str = ""
    feedback: str = ""       # commento del supervisore


@dataclass
class SuggestionReport:
    suggestions: list[Suggestion] = field(default_factory=list)
    generated_at: str = ""

    @property
    def top_priority(self) -> list[Suggestion]:
        return sorted(self.suggestions, key=lambda s: s.priority_score, reverse=True)[:5]

    @property
    def by_category(self) -> dict[str, list[Suggestion]]:
        result: dict[str, list[Suggestion]] = {}
        for s in self.suggestions:
            result.setdefault(s.category, []).append(s)
        return result


class SuggestionEngine:
    """
    Genera suggerimenti actionable con scoring impatto/effort.
    """

    _IMPACT_SCORE = {"low": 1, "medium": 3, "high": 5, "critical": 8}
    _EFFORT_SCORE = {"low": 1, "medium": 3, "high": 5}

    def __init__(self, ai: Optional[AIClient] = None) -> None:
        self._ai = ai or get_ai_client()
        self._kb = get_kb()
        self._audit = get_audit()
        self._counter = 0

    def generate(
        self,
        anomalies: list[dict] = None,
        bottlenecks: list[dict] = None,
        patterns: list[dict] = None,
        db_summary: str = "",
    ) -> SuggestionReport:
        """
        Genera suggerimenti basati sui dati analizzati.
        """
        anomalies = anomalies or []
        bottlenecks = bottlenecks or []
        patterns = patterns or []

        context = self._kb.build_context_prompt()

        # Costruisci il prompt con tutti i dati disponibili
        data_parts = []
        if anomalies:
            data_parts.append("ANOMALIE RILEVATE:")
            for a in anomalies[:10]:
                data_parts.append(f"  - {a.get('name', '')}: {a.get('description', '')}")

        if bottlenecks:
            data_parts.append("\nCOLLI DI BOTTIGLIA:")
            for b in bottlenecks[:10]:
                data_parts.append(f"  - {b.get('name', '')}: {b.get('description', '')}")

        if patterns:
            data_parts.append("\nPATTERN RILEVATI:")
            for p in patterns[:10]:
                data_parts.append(f"  - [{p.get('type', '')}] {p.get('name', '')}: {p.get('description', '')}")

        if db_summary:
            data_parts.append(f"\nDATI GESTIONALE:\n{db_summary[:1000]}")

        if not data_parts:
            return SuggestionReport(generated_at=_now())

        system_prompt = (
            "Sei un consulente operativo aziendale. Genera suggerimenti concreti e actionable "
            "per migliorare l'efficienza operativa. Per ogni suggerimento:\n"
            "1. Titolo chiaro e specifico\n"
            "2. Descrizione con azione concreta\n"
            "3. Valutazione impatto (low/medium/high/critical)\n"
            "4. Stima effort (low/medium/high)\n"
            "5. Categoria (efficiency/quality/cost/risk/automation)\n"
            "6. Simulazione what-if: cosa succede se viene implementato\n"
        )
        if context:
            system_prompt += f"\n{context}\n"

        user_prompt = "\n".join(data_parts) + (
            "\n\nGenera suggerimenti. Rispondi con un JSON array:\n"
            '[{"title": "...", "description": "...", "category": "efficiency", '
            '"impact": "high", "effort": "low", '
            '"evidence": ["dato 1"], "what_if": "Se implementato..."}]'
        )

        try:
            response = self._ai.complete_simple(
                user_prompt,
                system_prompt=system_prompt,
                role=ModelRole.ANALYSE,
                max_tokens=2048,
                temperature=0.4,
            )
            suggestions = self._parse_response(response)

            # Calcola priority score
            for s in suggestions:
                s.priority_score = self._calc_priority(s.impact, s.effort)
                s.created_at = _now()

            # Registra in audit trail
            for s in suggestions:
                self._audit.record(
                    AuditEventType.AI_DECISION,
                    summary=f"Suggerimento: {s.title}",
                    actor="suggestion_engine",
                    details={"impact": s.impact, "effort": s.effort, "score": s.priority_score},
                )

            report = SuggestionReport(suggestions=suggestions, generated_at=_now())
            log.info(
                f"Generati {len(suggestions)} suggerimenti",
                action=LogAction.ANALYSE, status=LogStatus.OK,
            )
            return report

        except Exception as exc:
            log.error(f"Generazione suggerimenti fallita: {exc}", action=LogAction.ANALYSE)
            return SuggestionReport(generated_at=_now())

    def _calc_priority(self, impact: str, effort: str) -> float:
        i = self._IMPACT_SCORE.get(impact, 2)
        e = self._EFFORT_SCORE.get(effort, 3)
        # Priorità = impatto / effort, normalizzato 0-10
        return round(min((i / max(e, 0.5)) * 3, 10.0), 1)

    def _next_id(self) -> str:
        self._counter += 1
        return f"SUG-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{self._counter:03d}"

    def _parse_response(self, text: str) -> list[Suggestion]:
        text = text.strip()
        if "```" in text:
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                text = text[start:end]

        try:
            data = json.loads(text)
            if not isinstance(data, list):
                data = [data]
        except json.JSONDecodeError:
            return []

        suggestions = []
        for item in data:
            suggestions.append(Suggestion(
                id=self._next_id(),
                title=item.get("title", ""),
                description=item.get("description", ""),
                category=item.get("category", "efficiency"),
                impact=item.get("impact", "medium"),
                effort=item.get("effort", "medium"),
                evidence=item.get("evidence", []),
                what_if=item.get("what_if", ""),
            ))
        return suggestions


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
