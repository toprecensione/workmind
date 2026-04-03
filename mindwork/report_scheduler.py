"""
WorkMind Report Scheduler
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Genera report automatici:
- Giornaliero alle 22:00: attività del giorno, anomalie, suggerimenti
- Settimanale (venerdì): trend, KPI, confronto con settimana precedente
- On-demand: via comando /report nella chat

I report vengono salvati in JSON + Markdown nella directory reports/.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config.settings import config, REPORT_DIR
from config.company import get_company_config
from ai_client import AIClient, ModelRole
from ai_client.client import get_ai_client
from ai_client.budget import get_budget
from storage.knowledge_base import get_kb
from storage.audit_trail import get_audit
from mindwork.feedback import get_feedback
from logging_system import get_logger, LogAction, LogStatus

log = get_logger("mindwork.report_scheduler")


class ReportScheduler:
    """
    Scheduler per report giornalieri e settimanali.
    Usa APScheduler per la pianificazione.
    """

    def __init__(self, ai: Optional[AIClient] = None) -> None:
        self._ai = ai or get_ai_client()
        self._company = get_company_config()
        self._budget = get_budget()
        self._kb = get_kb()
        self._audit = get_audit()
        self._feedback = get_feedback()
        self._scheduler = None

    def start(self) -> None:
        """Avvia lo scheduler per report automatici."""
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
        except ImportError:
            log.error(
                "APScheduler non installato",
                action=LogAction.STARTUP, status=LogStatus.ERROR,
                suggestion="pip install apscheduler",
            )
            return

        self._scheduler = BackgroundScheduler()

        # Report giornaliero
        hour, minute = self._parse_time(self._company.report_time_daily)
        self._scheduler.add_job(
            self.generate_daily,
            CronTrigger(hour=hour, minute=minute, timezone=self._company.timezone),
            id="daily_report",
            name="Report Giornaliero",
        )

        # Report settimanale
        day_map = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                   "friday": 4, "saturday": 5, "sunday": 6}
        day_of_week = day_map.get(self._company.report_day_weekly.lower(), 4)
        self._scheduler.add_job(
            self.generate_weekly,
            CronTrigger(day_of_week=day_of_week, hour=hour, minute=minute,
                        timezone=self._company.timezone),
            id="weekly_report",
            name="Report Settimanale",
        )

        self._scheduler.start()
        log.info(
            f"Report scheduler avviato: giornaliero alle {hour:02d}:{minute:02d}, "
            f"settimanale il {self._company.report_day_weekly}",
            action=LogAction.STARTUP, status=LogStatus.OK,
        )

    def stop(self) -> None:
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            log.info("Report scheduler fermato", action=LogAction.SHUTDOWN, status=LogStatus.STOPPED)

    # ── Report giornaliero ────────────────────────────────────────────────────

    def generate_daily(self) -> Path:
        """Genera il report giornaliero."""
        log.info("Generazione report giornaliero...", action=LogAction.REPORT, status=LogStatus.STARTED)

        now = datetime.now(timezone.utc)
        audit_events = self._audit.recent(100)
        budget = self._budget.daily_summary()
        kb_summary = self._kb.summary()
        fb_stats = self._feedback.stats()

        # Prepara dati per l'AI
        today_events = [
            e for e in audit_events
            if e.get("timestamp", "")[:10] == now.strftime("%Y-%m-%d")
        ]

        system_prompt = (
            f"Sei l'assistente operativo di {self._company.name}. "
            "Genera un report giornaliero in italiano. Sii conciso e actionable."
        )

        user_prompt = (
            f"Genera il report giornaliero per {self._company.name}.\n\n"
            f"Data: {now.strftime('%d/%m/%Y')}\n"
            f"Eventi oggi: {len(today_events)}\n"
            f"Budget AI: DeepSeek ${budget.get('deepseek', {}).get('cost_usd', 0):.4f}, "
            f"Claude ${budget.get('claude', {}).get('cost_usd', 0):.4f}\n"
            f"KB: {kb_summary}\n"
            f"Feedback: {fb_stats}\n\n"
            f"Eventi principali:\n"
        )
        for e in today_events[:20]:
            user_prompt += f"- [{e.get('event_type', '')}] {e.get('summary', '')}\n"

        user_prompt += (
            "\nGenera un report con: panoramica, attività principali, "
            "anomalie, suggerimenti, e prossimi passi."
        )

        try:
            ai_report = self._ai.complete_simple(
                user_prompt,
                system_prompt=system_prompt,
                role=ModelRole.ANALYSE,
                max_tokens=1500,
            )
        except Exception as exc:
            ai_report = f"Errore generazione AI: {exc}"

        report_data = {
            "type": "daily",
            "company": self._company.name,
            "node_id": config.node.node_id,
            "generated_at": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "events_count": len(today_events),
            "budget": budget,
            "kb_summary": kb_summary,
            "feedback_stats": fb_stats,
            "ai_report": ai_report,
        }

        return self._save_report(report_data, f"daily_{now.strftime('%Y%m%d')}")

    # ── Report settimanale ────────────────────────────────────────────────────

    def generate_weekly(self) -> Path:
        """Genera il report settimanale con trend e KPI."""
        log.info("Generazione report settimanale...", action=LogAction.REPORT, status=LogStatus.STARTED)

        now = datetime.now(timezone.utc)
        audit_events = self._audit.recent(500)
        budget = self._budget.daily_summary()
        fb_stats = self._feedback.stats()

        system_prompt = (
            f"Sei l'assistente operativo di {self._company.name}. "
            "Genera un report settimanale strategico in italiano con trend, KPI e confronti."
        )

        user_prompt = (
            f"Report settimanale per {self._company.name}.\n\n"
            f"Settimana terminante il {now.strftime('%d/%m/%Y')}\n"
            f"Eventi totali settimana: {len(audit_events)}\n"
            f"Feedback: {fb_stats}\n\n"
            "Genera: executive summary, KPI principali, trend rispetto alle settimane precedenti, "
            "anomalie ricorrenti, suggerimenti strategici, e priorità per la prossima settimana."
        )

        try:
            ai_report = self._ai.complete_simple(
                user_prompt,
                system_prompt=system_prompt,
                role=ModelRole.ANALYSE,
                max_tokens=2048,
            )
        except Exception as exc:
            ai_report = f"Errore generazione AI: {exc}"

        report_data = {
            "type": "weekly",
            "company": self._company.name,
            "node_id": config.node.node_id,
            "generated_at": now.isoformat(),
            "week_ending": now.strftime("%Y-%m-%d"),
            "events_count": len(audit_events),
            "feedback_stats": fb_stats,
            "ai_report": ai_report,
        }

        return self._save_report(report_data, f"weekly_{now.strftime('%Y%m%d')}")

    # ── Salvataggio ───────────────────────────────────────────────────────────

    def _save_report(self, data: dict, name: str) -> Path:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)

        # JSON
        json_path = REPORT_DIR / f"{name}.json"
        json_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # Markdown
        md_path = REPORT_DIR / f"{name}.md"
        md_content = self._to_markdown(data)
        md_path.write_text(md_content, encoding="utf-8")

        self._audit.record(
            event_type=__import__("storage.audit_trail", fromlist=["AuditEventType"]).AuditEventType.REPORT_GENERATED,
            summary=f"Report {data['type']}: {name}",
            actor="report_scheduler",
        )

        log.info(
            f"Report salvato: {json_path.name}",
            action=LogAction.REPORT, status=LogStatus.OK,
        )
        return json_path

    @staticmethod
    def _to_markdown(data: dict) -> str:
        report_type = data.get("type", "").title()
        lines = [
            f"# WorkMind Report {report_type}",
            f"**Azienda:** {data.get('company', '')}",
            f"**Nodo:** {data.get('node_id', '')}",
            f"**Generato:** {data.get('generated_at', '')[:16]}",
            "",
            "---",
            "",
            data.get("ai_report", "Nessun contenuto AI disponibile."),
            "",
            "---",
            f"*Report generato automaticamente da WorkMind*",
        ]
        return "\n".join(lines)

    @staticmethod
    def _parse_time(time_str: str) -> tuple[int, int]:
        try:
            parts = time_str.split(":")
            return int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            return 22, 0
