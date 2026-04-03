"""
WorkMind Entity Extractor
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Estrae entità strutturate dai documenti aziendali:
- Nomi (persone, aziende)
- Date
- Importi / valute
- Codici (articolo, commessa, cliente, fattura)
- Indirizzi
- Entità custom definite dall'azienda
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

from ai_client import AIClient, ModelRole
from ai_client.client import get_ai_client
from connectors.document_parser import ParsedDocument
from storage.knowledge_base import get_kb
from logging_system import get_logger, LogAction, LogStatus

log = get_logger("nlp.extractor")


@dataclass
class Entity:
    type: str          # person, company, date, amount, code, address, custom
    value: str
    label: str = ""    # sotto-tipo (es. "codice_articolo", "data_scadenza")
    confidence: float = 0.0
    position: int = -1  # posizione nel testo (indice carattere)


@dataclass
class ExtractionResult:
    entities: list[Entity] = field(default_factory=list)
    raw_json: str = ""

    @property
    def persons(self) -> list[Entity]:
        return [e for e in self.entities if e.type == "person"]

    @property
    def companies(self) -> list[Entity]:
        return [e for e in self.entities if e.type == "company"]

    @property
    def dates(self) -> list[Entity]:
        return [e for e in self.entities if e.type == "date"]

    @property
    def amounts(self) -> list[Entity]:
        return [e for e in self.entities if e.type == "amount"]

    @property
    def codes(self) -> list[Entity]:
        return [e for e in self.entities if e.type == "code"]

    def by_type(self, entity_type: str) -> list[Entity]:
        return [e for e in self.entities if e.type == entity_type]

    def summary(self) -> dict:
        result = {}
        for e in self.entities:
            result.setdefault(e.type, []).append({"value": e.value, "label": e.label})
        return result


class EntityExtractor:
    """
    Estrae entità dai documenti usando AI + regex di supporto.
    """

    def __init__(self, ai: Optional[AIClient] = None) -> None:
        self._ai = ai or get_ai_client()
        self._kb = get_kb()

    def extract(self, doc: ParsedDocument, doc_type: str = "") -> ExtractionResult:
        """Estrae entità da un documento parsato."""
        if not doc.is_ok:
            return ExtractionResult()

        # Fase 1: regex veloce per entità ovvie
        regex_entities = self._regex_extract(doc.text)

        # Fase 2: AI per entità complesse
        ai_entities = self._ai_extract(doc, doc_type)

        # Merge e deduplica
        all_entities = self._merge(regex_entities, ai_entities)

        log.info(
            f"Estratte {len(all_entities)} entità da {doc.filename}",
            action=LogAction.ANALYSE, status=LogStatus.OK,
        )
        return ExtractionResult(entities=all_entities)

    # ── Regex extraction (veloce, senza AI) ───────────────────────────────────

    def _regex_extract(self, text: str) -> list[Entity]:
        entities = []

        # Date italiane: dd/mm/yyyy, dd-mm-yyyy, dd.mm.yyyy
        for m in re.finditer(r'\b(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})\b', text):
            entities.append(Entity(type="date", value=m.group(1), label="data", confidence=0.9, position=m.start()))

        # Importi: € 1.234,56 oppure EUR 1234.56 oppure 1.234,56 €
        for m in re.finditer(
            r'(?:€|EUR)\s*([\d.]+,\d{2})|'
            r'([\d.]+,\d{2})\s*(?:€|EUR)|'
            r'(?:euro|Euro|EURO)\s*([\d.]+,\d{2})',
            text
        ):
            value = m.group(1) or m.group(2) or m.group(3)
            if value:
                entities.append(Entity(type="amount", value=f"€ {value}", label="importo", confidence=0.85, position=m.start()))

        # Codice fiscale italiano
        cf_pattern = r'\b[A-Z]{6}\d{2}[A-EHLMPRST]\d{2}[A-Z]\d{3}[A-Z]\b'
        for m in re.finditer(cf_pattern, text):
            entities.append(Entity(type="code", value=m.group(), label="codice_fiscale", confidence=0.95, position=m.start()))

        # Partita IVA
        for m in re.finditer(r'\b(?:IT)?\d{11}\b', text):
            entities.append(Entity(type="code", value=m.group(), label="partita_iva", confidence=0.7, position=m.start()))

        # Email
        for m in re.finditer(r'\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b', text):
            entities.append(Entity(type="contact", value=m.group(), label="email", confidence=0.95, position=m.start()))

        # Telefono italiano
        for m in re.finditer(r'\b(?:\+39\s?)?(?:0\d{1,4}[\s\-]?\d{4,8}|\d{3}[\s\-]?\d{6,7})\b', text):
            entities.append(Entity(type="contact", value=m.group(), label="telefono", confidence=0.7, position=m.start()))

        # IBAN
        for m in re.finditer(r'\b[A-Z]{2}\d{2}\s?[A-Z0-9]{4}(?:\s?\d{4}){5}(?:\s?\d{1,4})?\b', text):
            entities.append(Entity(type="code", value=m.group(), label="iban", confidence=0.9, position=m.start()))

        return entities

    # ── AI extraction ─────────────────────────────────────────────────────────

    def _ai_extract(self, doc: ParsedDocument, doc_type: str) -> list[Entity]:
        from config.company import get_company_config
        company = get_company_config()
        custom_entities = company.custom_entities

        context = self._kb.build_context_prompt()

        system_prompt = (
            "Sei un estrattore di entità per documenti aziendali italiani. "
            "Estrai tutte le entità rilevanti dal testo.\n\n"
            "Tipi di entità: person, company, date, amount, code, address, custom\n"
        )
        if custom_entities:
            system_prompt += f"Entità custom aziendali da cercare: {', '.join(custom_entities)}\n"
        if context:
            system_prompt += f"\n{context}\n"

        user_prompt = (
            f"Documento: {doc.filename} (tipo: {doc_type or 'sconosciuto'})\n\n"
            f"Testo:\n---\n{doc.text[:3000]}\n---\n\n"
            f"Estrai le entità. Rispondi SOLO con un JSON array:\n"
            f'[{{"type": "person", "value": "Mario Rossi", "label": "mittente", "confidence": 0.9}}, ...]'
        )

        try:
            response = self._ai.complete_simple(
                user_prompt,
                system_prompt=system_prompt,
                role=ModelRole.FAST,
                max_tokens=1024,
                temperature=0.1,
            )
            return self._parse_ai_entities(response)
        except Exception as exc:
            log.warning(f"Estrazione AI fallita per {doc.filename}: {exc}", action=LogAction.ANALYSE)
            return []

    @staticmethod
    def _parse_ai_entities(text: str) -> list[Entity]:
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

        entities = []
        for item in data:
            if isinstance(item, dict) and "type" in item and "value" in item:
                entities.append(Entity(
                    type=item["type"],
                    value=str(item["value"]),
                    label=item.get("label", ""),
                    confidence=min(max(float(item.get("confidence", 0.5)), 0.0), 1.0),
                ))
        return entities

    # ── Merge e dedup ─────────────────────────────────────────────────────────

    @staticmethod
    def _merge(regex_entities: list[Entity], ai_entities: list[Entity]) -> list[Entity]:
        seen = set()
        merged = []
        for e in regex_entities + ai_entities:
            key = (e.type, e.value.strip().lower())
            if key not in seen:
                seen.add(key)
                merged.append(e)
        return merged
