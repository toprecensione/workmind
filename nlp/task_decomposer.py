"""
WorkMind Task Decomposer
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Identifica i processi lavorativi impliciti nei dati osservati e costruisce
un albero gerarchico dei task. Analizza:
- Sequenze di documenti (ordine → conferma → DDT → fattura)
- Pattern temporali di attività
- Relazioni tra entità nei documenti
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from ai_client import AIClient, ModelRole
from ai_client.client import get_ai_client
from storage.knowledge_base import get_kb
from logging_system import get_logger, LogAction, LogStatus

log = get_logger("nlp.task_decomposer")


@dataclass
class Task:
    name: str
    description: str
    status: str = "identified"  # identified | in_progress | completed | blocked
    responsible: str = ""
    parent: str = ""             # nome del task padre
    children: list[str] = field(default_factory=list)
    documents: list[str] = field(default_factory=list)  # documenti coinvolti
    estimated_effort: str = ""   # basso | medio | alto
    frequency: str = ""          # giornaliero | settimanale | mensile | ad-hoc


@dataclass
class ProcessTree:
    name: str
    description: str
    tasks: list[Task] = field(default_factory=list)
    bottlenecks: list[str] = field(default_factory=list)
    automatable_steps: list[str] = field(default_factory=list)

    @property
    def root_tasks(self) -> list[Task]:
        return [t for t in self.tasks if not t.parent]

    def summary(self) -> str:
        lines = [f"Processo: {self.name}", f"  {self.description}", f"  {len(self.tasks)} task"]
        if self.bottlenecks:
            lines.append(f"  Colli di bottiglia: {', '.join(self.bottlenecks)}")
        if self.automatable_steps:
            lines.append(f"  Automatizzabili: {', '.join(self.automatable_steps)}")
        return "\n".join(lines)


class TaskDecomposer:
    """
    Analizza attività osservate e ricostruisce processi impliciti.
    """

    def __init__(self, ai: Optional[AIClient] = None) -> None:
        self._ai = ai or get_ai_client()
        self._kb = get_kb()

    def decompose_from_documents(
        self,
        documents: list[dict],
        db_context: str = "",
    ) -> list[ProcessTree]:
        """
        Analizza un set di documenti recenti e identifica i processi sottostanti.

        Args:
            documents: lista di dict con {filename, type, summary, entities, date}
            db_context: schema/dati dal database gestionale per arricchire l'analisi
        """
        if not documents:
            return []

        context = self._kb.build_context_prompt()
        known_processes = self._kb.get_processes()

        # Prepara il summary dei documenti per l'AI
        doc_summaries = []
        for doc in documents[:30]:
            doc_summaries.append(
                f"- {doc.get('filename', '?')} (tipo: {doc.get('type', '?')}, "
                f"data: {doc.get('date', '?')}): {doc.get('summary', '')[:150]}"
            )

        system_prompt = (
            "Sei un analista di processi aziendali. Analizza i documenti osservati "
            "e identifica i processi lavorativi impliciti. Per ogni processo:\n"
            "1. Identifica la sequenza di attività\n"
            "2. Segna i colli di bottiglia\n"
            "3. Indica gli step automatizzabili\n"
        )
        if known_processes:
            system_prompt += "\nProcessi già noti dell'azienda:\n"
            for p in known_processes:
                system_prompt += f"- {p['name']}: {p['description']}\n"
        if context:
            system_prompt += f"\n{context}\n"

        user_prompt = (
            f"Documenti osservati di recente:\n"
            + "\n".join(doc_summaries)
        )
        if db_context:
            user_prompt += f"\n\nDati dal gestionale:\n{db_context[:1500]}"

        user_prompt += (
            "\n\nIdentifica i processi. Rispondi con un JSON array:\n"
            '[{"name": "Ciclo ordine-fattura", "description": "...", '
            '"tasks": [{"name": "...", "description": "...", "parent": "", '
            '"estimated_effort": "medio", "frequency": "giornaliero"}], '
            '"bottlenecks": ["..."], "automatable_steps": ["..."]}]'
        )

        try:
            response = self._ai.complete_simple(
                user_prompt,
                system_prompt=system_prompt,
                role=ModelRole.ANALYSE,
                max_tokens=2048,
                temperature=0.3,
            )
            processes = self._parse_response(response)
            log.info(
                f"Processi identificati: {len(processes)}",
                action=LogAction.ANALYSE, status=LogStatus.OK,
                extra={"processes": [p.name for p in processes]},
            )
            return processes
        except Exception as exc:
            log.error(f"Task decomposition fallita: {exc}", action=LogAction.ANALYSE)
            return []

    def identify_bottlenecks(self, process: ProcessTree) -> list[str]:
        """Identifica colli di bottiglia in un processo specifico."""
        return process.bottlenecks

    # ── Parsing ───────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_response(text: str) -> list[ProcessTree]:
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

        processes = []
        for item in data:
            tasks = []
            for t in item.get("tasks", []):
                tasks.append(Task(
                    name=t.get("name", ""),
                    description=t.get("description", ""),
                    parent=t.get("parent", ""),
                    estimated_effort=t.get("estimated_effort", ""),
                    frequency=t.get("frequency", ""),
                    documents=t.get("documents", []),
                ))
            processes.append(ProcessTree(
                name=item.get("name", "Processo"),
                description=item.get("description", ""),
                tasks=tasks,
                bottlenecks=item.get("bottlenecks", []),
                automatable_steps=item.get("automatable_steps", []),
            ))

        return processes
