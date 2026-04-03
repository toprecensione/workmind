"""
WorkMind Pattern Detector
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Rileva pattern temporali, ricorrenze e anomalie nei dati osservati:
- Attività ricorrenti (giornaliere, settimanali, mensili)
- Colli di bottiglia temporali (ritardi sistematici)
- Deviazioni dai pattern normali (anomaly detection avanzata)
- Procedure potenzialmente automatizzabili
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from ai_client import AIClient, ModelRole
from ai_client.client import get_ai_client
from storage.redis_store import get_store
from logging_system import get_logger, LogAction, LogStatus

log = get_logger("nlp.pattern_detector")


@dataclass
class Pattern:
    name: str
    type: str           # recurring | bottleneck | anomaly | automatable
    description: str
    frequency: str = ""  # daily | weekly | monthly | ad-hoc
    severity: str = ""   # low | medium | high
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)  # dati che supportano il pattern
    suggestion: str = ""


@dataclass
class PatternReport:
    patterns: list[Pattern] = field(default_factory=list)
    period_start: str = ""
    period_end: str = ""
    data_points: int = 0

    @property
    def anomalies(self) -> list[Pattern]:
        return [p for p in self.patterns if p.type == "anomaly"]

    @property
    def bottlenecks(self) -> list[Pattern]:
        return [p for p in self.patterns if p.type == "bottleneck"]

    @property
    def automatable(self) -> list[Pattern]:
        return [p for p in self.patterns if p.type == "automatable"]

    def summary(self) -> str:
        lines = [
            f"Pattern rilevati: {len(self.patterns)}",
            f"  Anomalie: {len(self.anomalies)}",
            f"  Colli di bottiglia: {len(self.bottlenecks)}",
            f"  Automatizzabili: {len(self.automatable)}",
        ]
        return "\n".join(lines)


class PatternDetector:
    """
    Analizza serie storiche di attività per trovare pattern e anomalie.
    Combina analisi statistica (z-score) e AI per interpretazione.
    """

    def __init__(self, ai: Optional[AIClient] = None) -> None:
        self._ai = ai or get_ai_client()
        self._store = get_store()

    def detect(
        self,
        activities: list[dict],
        db_data: Optional[list[dict]] = None,
        email_data: Optional[list[dict]] = None,
    ) -> PatternReport:
        """
        Rileva pattern da attività osservate.

        activities: lista di dict con {timestamp, type, description, entities, ...}
        db_data: dati recenti dal database gestionale
        email_data: email recenti
        """
        if not activities:
            return PatternReport()

        # Fase 1: analisi statistica base
        stat_patterns = self._statistical_analysis(activities)

        # Fase 2: analisi AI per interpretazione e pattern complessi
        ai_patterns = self._ai_analysis(activities, db_data, email_data)

        all_patterns = stat_patterns + ai_patterns
        all_patterns = self._deduplicate(all_patterns)

        report = PatternReport(
            patterns=all_patterns,
            period_start=activities[-1].get("timestamp", "") if activities else "",
            period_end=activities[0].get("timestamp", "") if activities else "",
            data_points=len(activities),
        )

        log.info(
            f"Pattern detection: {len(all_patterns)} pattern trovati su {len(activities)} attività",
            action=LogAction.ANALYSE, status=LogStatus.OK,
        )
        return report

    # ── Analisi statistica ────────────────────────────────────────────────────

    def _statistical_analysis(self, activities: list[dict]) -> list[Pattern]:
        patterns = []

        # Raggruppa per tipo
        by_type: dict[str, list] = {}
        for a in activities:
            atype = a.get("type", "unknown")
            by_type.setdefault(atype, []).append(a)

        for atype, items in by_type.items():
            if len(items) < 3:
                continue

            # Frequenza: quante volte al giorno/settimana
            timestamps = []
            for it in items:
                ts = it.get("timestamp", "")
                if ts:
                    try:
                        timestamps.append(datetime.fromisoformat(ts).timestamp())
                    except (ValueError, TypeError):
                        pass

            if len(timestamps) >= 3:
                timestamps.sort()
                intervals = [timestamps[i+1] - timestamps[i] for i in range(len(timestamps)-1)]
                if intervals:
                    mean_interval = statistics.mean(intervals)
                    if len(intervals) >= 3:
                        stdev = statistics.stdev(intervals)
                        # Pattern ricorrente se bassa varianza
                        cv = stdev / mean_interval if mean_interval > 0 else float("inf")
                        if cv < 0.5:
                            freq = self._interval_to_frequency(mean_interval)
                            patterns.append(Pattern(
                                name=f"Attività ricorrente: {atype}",
                                type="recurring",
                                description=f"{atype} si ripete ogni ~{self._format_interval(mean_interval)}",
                                frequency=freq,
                                confidence=min(1.0 - cv, 0.95),
                                evidence=[f"{len(items)} occorrenze osservate"],
                            ))

                        # Anomalia: outlier negli intervalli (z-score > 2.5)
                        for i, interval in enumerate(intervals):
                            if stdev > 0:
                                z = abs(interval - mean_interval) / stdev
                                if z > 2.5:
                                    patterns.append(Pattern(
                                        name=f"Anomalia temporale: {atype}",
                                        type="anomaly",
                                        description=f"Intervallo anomalo di {self._format_interval(interval)} per {atype} (atteso ~{self._format_interval(mean_interval)})",
                                        severity="high" if z > 4 else "medium",
                                        confidence=min(z / 5, 0.95),
                                    ))

        return patterns

    # ── Analisi AI ────────────────────────────────────────────────────────────

    def _ai_analysis(
        self,
        activities: list[dict],
        db_data: Optional[list[dict]],
        email_data: Optional[list[dict]],
    ) -> list[Pattern]:
        # Prepara sommario attività
        activity_lines = []
        for a in activities[:50]:
            activity_lines.append(
                f"- [{a.get('timestamp', '')}] {a.get('type', '?')}: "
                f"{a.get('description', '')[:120]}"
            )

        user_prompt = "Attività recenti osservate:\n" + "\n".join(activity_lines)

        if db_data:
            user_prompt += "\n\nDati gestionale:\n"
            for d in db_data[:10]:
                user_prompt += f"- {json.dumps(d, ensure_ascii=False, default=str)[:200]}\n"

        if email_data:
            user_prompt += "\n\nEmail recenti:\n"
            for e in email_data[:10]:
                user_prompt += f"- [{e.get('sender', '')}] {e.get('subject', '')}\n"

        user_prompt += (
            "\n\nIdentifica pattern, anomalie, colli di bottiglia e procedure automatizzabili. "
            "Rispondi con un JSON array:\n"
            '[{"name": "...", "type": "recurring|bottleneck|anomaly|automatable", '
            '"description": "...", "frequency": "daily", "severity": "medium", '
            '"confidence": 0.8, "suggestion": "..."}]'
        )

        try:
            response = self._ai.complete_simple(
                user_prompt,
                system_prompt=(
                    "Sei un analista operativo. Identifica pattern significativi nelle attività aziendali. "
                    "Focus su colli di bottiglia, anomalie e opportunità di automazione."
                ),
                role=ModelRole.ANALYSE,
                max_tokens=1024,
                temperature=0.3,
            )
            return self._parse_patterns(response)
        except Exception as exc:
            log.warning(f"Analisi AI pattern fallita: {exc}", action=LogAction.ANALYSE)
            return []

    # ── Utility ───────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_patterns(text: str) -> list[Pattern]:
        text = text.strip()
        if "```" in text:
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                text = text[start:end]
        try:
            data = json.loads(text)
            if not isinstance(data, list):
                return []
        except json.JSONDecodeError:
            return []

        patterns = []
        for item in data:
            patterns.append(Pattern(
                name=item.get("name", ""),
                type=item.get("type", "recurring"),
                description=item.get("description", ""),
                frequency=item.get("frequency", ""),
                severity=item.get("severity", "low"),
                confidence=float(item.get("confidence", 0.5)),
                suggestion=item.get("suggestion", ""),
            ))
        return patterns

    @staticmethod
    def _deduplicate(patterns: list[Pattern]) -> list[Pattern]:
        seen = set()
        result = []
        for p in patterns:
            key = (p.type, p.name.lower())
            if key not in seen:
                seen.add(key)
                result.append(p)
        return result

    @staticmethod
    def _interval_to_frequency(seconds: float) -> str:
        if seconds < 7200:
            return "hourly"
        if seconds < 172800:
            return "daily"
        if seconds < 1209600:
            return "weekly"
        return "monthly"

    @staticmethod
    def _format_interval(seconds: float) -> str:
        if seconds < 3600:
            return f"{seconds/60:.0f} minuti"
        if seconds < 86400:
            return f"{seconds/3600:.1f} ore"
        return f"{seconds/86400:.1f} giorni"
