"""
WorkMind Chat Server
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Chat per il supervisore aziendale su porta 7860.
Usa Gradio per l'interfaccia web.

Comandi disponibili:
  /teach <fatto>        — insegna un fatto al bot
  /correct <errore> → <corretto> — corregge una classificazione
  /process <nome>: <descrizione> — insegna un processo aziendale
  /glossary <termine>: <definizione> — aggiunge al glossario
  /status              — stato del bot
  /report              — genera report on-demand
  /suggestions         — mostra suggerimenti recenti
  /feedback <id> <confirm|correct|reject> [commento]
  /budget              — mostra spesa AI
  /audit               — ultimi eventi audit trail
  /help                — lista comandi
"""

from __future__ import annotations

import threading
from typing import Optional

from ai_client import AIClient, ModelRole
from ai_client.client import get_ai_client
from ai_client.budget import get_budget
from config.company import get_company_config
from storage.knowledge_base import get_kb
from storage.audit_trail import get_audit
from mindwork.feedback import get_feedback
from nlp.hallucination_guard import HallucinationGuard
from logging_system import get_logger, LogAction, LogStatus

# Keyword che indicano domande fattuali su contatti/dati aziendali
_FACTUAL_KEYWORDS = (
    "contatt", "telefono", "email", "mail", "indirizzo", "sito",
    "website", "url", "numero", "orari", "sede", "p.iva", "partita iva",
    "codice fiscale", "pec", "dove siete", "dove si trova",
)

# Keyword che indicano domande interne di analisi/processo
_ANALYSIS_KEYWORDS = (
    "analizza", "report", "riepilog", "riassumi", "classifica",
    "estrai", "trova", "cerca", "quant", "statistic", "trend",
)

log = get_logger("interface.chat")


class ChatServer:
    """
    Server chat Gradio per interazione supervisore ↔ bot.
    """

    def __init__(self, ai: Optional[AIClient] = None, port: int = 7860) -> None:
        self._ai = ai or get_ai_client()
        self._kb = get_kb()
        self._audit = get_audit()
        self._budget = get_budget()
        self._feedback = get_feedback()
        self._company = get_company_config()
        self._guard = HallucinationGuard(self._ai)
        self._port = port
        self._history: list[tuple[str, str]] = []

    def start(self) -> None:
        """Avvia il server Gradio in background."""
        t = threading.Thread(target=self._run_gradio, daemon=True, name="ChatServer")
        t.start()
        log.info(
            f"Chat server avviato su porta {self._port}",
            action=LogAction.STARTUP, status=LogStatus.OK,
        )

    def _run_gradio(self) -> None:
        try:
            import gradio as gr
        except ImportError:
            log.error(
                "Gradio non installato — chat non disponibile",
                action=LogAction.STARTUP, status=LogStatus.ERROR,
                suggestion="pip install gradio",
            )
            return

        def respond(message: str, history: list) -> str:
            return self._handle_message(message)

        demo = gr.ChatInterface(
            fn=respond,
            title=f"WorkMind — {self._company.name}",
            description=(
                f"Assistente operativo per {self._company.name}. "
                f"Scrivi /help per la lista comandi."
            ),
        )
        demo.launch(
            server_name="0.0.0.0",
            server_port=self._port,
            share=False,
            show_api=False,
            quiet=True,
        )

    # ── Message handler ───────────────────────────────────────────────────────

    def _handle_message(self, message: str) -> str:
        message = message.strip()

        if not message:
            return "Scrivi un messaggio o usa /help per i comandi."

        # Comandi slash
        if message.startswith("/"):
            return self._handle_command(message)

        # Chat libera con AI
        return self._chat(message)

    def _handle_command(self, message: str) -> str:
        parts = message.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        handlers = {
            "/help":        self._cmd_help,
            "/teach":       self._cmd_teach,
            "/correct":     self._cmd_correct,
            "/process":     self._cmd_process,
            "/glossary":    self._cmd_glossary,
            "/kb":          self._cmd_kb,
            "/status":      self._cmd_status,
            "/report":      self._cmd_report,
            "/suggestions": self._cmd_suggestions,
            "/feedback":    self._cmd_feedback,
            "/budget":      self._cmd_budget,
            "/audit":       self._cmd_audit,
        }

        handler = handlers.get(cmd)
        if handler:
            return handler(arg)
        return f"Comando sconosciuto: {cmd}. Usa /help per la lista."

    # ── Comandi ───────────────────────────────────────────────────────────────

    def _cmd_help(self, _: str) -> str:
        return (
            "**Comandi WorkMind**\n\n"
            "| Comando | Descrizione |\n"
            "|---|---|\n"
            "| `/teach <fatto>` | Insegna un fatto al bot |\n"
            "| `/correct <errore> → <corretto>` | Correggi una classificazione |\n"
            "| `/process <nome>: <descrizione>` | Insegna un processo |\n"
            "| `/glossary <termine>: <definizione>` | Aggiungi al glossario |\n"
            "| `/kb list` | Elenca tutti i fatti in KB |\n"
            "| `/kb search <query>` | Cerca nella KB |\n"
            "| `/kb clear facts` | Cancella tutti i fatti |\n"
            "| `/kb export` | Esporta KB come testo |\n"
            "| `/status` | Stato del bot |\n"
            "| `/report` | Genera report on-demand |\n"
            "| `/suggestions` | Suggerimenti recenti |\n"
            "| `/feedback <id> <confirm/correct/reject> [nota]` | Feedback |\n"
            "| `/budget` | Spesa AI per modello |\n"
            "| `/audit` | Ultimi eventi audit |\n"
        )

    def _cmd_kb(self, arg: str) -> str:
        """Gestione Knowledge Base: list / search / clear / export."""
        parts = arg.strip().split(maxsplit=1)
        subcmd = parts[0].lower() if parts else "list"
        subarg = parts[1] if len(parts) > 1 else ""

        if subcmd == "list":
            facts = self._kb.get_facts()
            procs = self._kb.get_processes()
            gloss = self._kb.get_glossary()
            if not facts and not procs and not gloss:
                return (
                    "**Knowledge Base vuota.**\n\n"
                    "Aggiungi fatti con `/teach <fatto>`\n"
                    "Esempio: `/teach Email contatti: info@faberweb.it`"
                )
            lines = [f"**Knowledge Base — {len(facts)} fatti, "
                     f"{len(procs)} processi, {len(gloss)} termini**\n"]
            if facts:
                lines.append("**Fatti:**")
                for i, f in enumerate(facts[-20:], 1):
                    lines.append(f"  {i}. {f['text']}")
            if procs:
                lines.append("\n**Processi:**")
                for p in procs:
                    lines.append(f"  • **{p['name']}**: {p['description'][:80]}")
            if gloss:
                lines.append("\n**Glossario:**")
                for term, defn in list(gloss.items())[:15]:
                    lines.append(f"  • **{term}**: {defn}")
            return "\n".join(lines)

        elif subcmd == "search":
            if not subarg:
                return "Uso: `/kb search <query>`"
            result = self._kb.lookup_fact(subarg, threshold=0.15)
            if result:
                return f"**Trovato in KB:**\n{result}"
            # Ricerca testuale diretta
            query_lower = subarg.lower()
            matches = []
            for f in self._kb.get_facts():
                if query_lower in f["text"].lower():
                    matches.append(f["text"])
            if matches:
                return "**Corrispondenze:**\n" + "\n".join(f"• {m}" for m in matches[:10])
            return f"Nessun risultato in KB per: *{subarg}*"

        elif subcmd == "clear":
            if subarg == "facts":
                count = len(self._kb.get_facts())
                self._kb._data["facts"] = []
                self._kb._save()
                log.warning("KB facts cancellati via chat",
                            action=LogAction.CONFIG, status=LogStatus.WARNING)
                return f"Cancellati {count} fatti dalla KB."
            elif subarg == "all":
                self._kb._data = {"facts": [], "corrections": [], "processes": [], "glossary": {}}
                self._kb._save()
                return "Knowledge Base completamente svuotata."
            else:
                return "Uso: `/kb clear facts` oppure `/kb clear all`"

        elif subcmd == "export":
            context = self._kb.build_context_prompt()
            if not context:
                return "KB vuota — nulla da esportare."
            summary = self._kb.summary()
            header = (f"# WorkMind Knowledge Base Export\n"
                      f"Fatti: {summary['facts']} | "
                      f"Processi: {summary['processes']} | "
                      f"Glossario: {summary['glossary_terms']}\n\n")
            return header + context

        else:
            return "Sottocomandi: `list` | `search <query>` | `clear facts` | `export`"

    def _cmd_teach(self, arg: str) -> str:
        if not arg:
            return "Uso: `/teach <fatto da insegnare>`"
        self._kb.teach_fact(arg, taught_by="supervisor")
        return f"Fatto memorizzato: \"{arg}\""

    def _cmd_correct(self, arg: str) -> str:
        if "→" not in arg and "->" not in arg:
            return "Uso: `/correct <errore> → <corretto>`"
        sep = "→" if "→" in arg else "->"
        parts = arg.split(sep, 1)
        wrong = parts[0].strip()
        correct = parts[1].strip()
        self._kb.teach_correction(wrong, correct, taught_by="supervisor")
        return f"Correzione salvata: \"{wrong}\" → \"{correct}\""

    def _cmd_process(self, arg: str) -> str:
        if ":" not in arg:
            return "Uso: `/process <nome>: <descrizione>`"
        name, desc = arg.split(":", 1)
        self._kb.teach_process(name.strip(), desc.strip(), taught_by="supervisor")
        return f"Processo \"{name.strip()}\" memorizzato."

    def _cmd_glossary(self, arg: str) -> str:
        if ":" not in arg:
            return "Uso: `/glossary <termine>: <definizione>`"
        term, definition = arg.split(":", 1)
        self._kb.add_glossary_term(term.strip(), definition.strip())
        return f"Glossario: \"{term.strip()}\" aggiunto."

    def _cmd_status(self, _: str) -> str:
        kb_summary = self._kb.summary()
        fb_stats = self._feedback.stats()
        budget = self._budget.daily_summary()

        return (
            f"**WorkMind — {self._company.name}**\n\n"
            f"**Knowledge Base:** {kb_summary['facts']} fatti, "
            f"{kb_summary['corrections']} correzioni, "
            f"{kb_summary['processes']} processi, "
            f"{kb_summary['glossary_terms']} termini glossario\n\n"
            f"**Feedback:** {fb_stats['total']} totali "
            f"({fb_stats['confirmed']} confermati, "
            f"{fb_stats['corrected']} corretti, "
            f"{fb_stats['rejected']} rifiutati) — "
            f"accuratezza: {fb_stats['accuracy_rate']:.0%}\n\n"
            f"**Budget AI oggi:** DeepSeek ${budget.get('deepseek', {}).get('cost_usd', 0):.3f} | "
            f"Claude ${budget.get('claude', {}).get('cost_usd', 0):.3f}\n"
        )

    def _cmd_report(self, _: str) -> str:
        return ("Report on-demand richiesto. Il ciclo scan→analyse→report "
                "verrà eseguito al prossimo ciclo (max 30 min).")

    def _cmd_suggestions(self, _: str) -> str:
        # Placeholder: in produzione leggerà da Redis
        return "Nessun suggerimento recente. Il sistema genera suggerimenti durante i cicli di analisi."

    def _cmd_feedback(self, arg: str) -> str:
        parts = arg.split(maxsplit=2)
        if len(parts) < 2:
            return "Uso: `/feedback <id> <confirm|correct|reject> [commento]`"

        sid = parts[0]
        action = parts[1].lower()
        comment = parts[2] if len(parts) > 2 else ""

        if action == "confirm":
            self._feedback.confirm(sid, comment=comment)
            return f"Suggerimento {sid} confermato."
        elif action == "correct":
            self._feedback.correct(sid, correction=comment, comment="")
            return f"Suggerimento {sid} corretto con: {comment}"
        elif action == "reject":
            self._feedback.reject(sid, reason=comment)
            return f"Suggerimento {sid} rifiutato."
        else:
            return "Azione valida: confirm | correct | reject"

    def _cmd_budget(self, _: str) -> str:
        budget = self._budget.daily_summary()
        lines = ["**Budget AI — Oggi**\n"]
        for provider, data in budget.items():
            lines.append(
                f"**{provider.title()}**: ${data['cost_usd']:.4f} "
                f"(limite: ${data['limit_usd']:.2f}) — "
                f"{data['calls']} chiamate"
            )
        return "\n".join(lines)

    def _cmd_audit(self, _: str) -> str:
        events = self._audit.recent(10)
        if not events:
            return "Nessun evento nell'audit trail."
        lines = ["**Ultimi eventi audit:**\n"]
        for e in events:
            lines.append(
                f"- [{e.get('timestamp', '')[:16]}] "
                f"**{e.get('event_type', '')}** ({e.get('actor', '')}): "
                f"{e.get('summary', '')}"
            )
        return "\n".join(lines)

    # ── Intent detection ──────────────────────────────────────────────────────

    def _detect_intent(self, message: str) -> str:
        """
        Classifica il tipo di query senza chiamare l'AI.
        Ritorna: "factual" | "analysis" | "chat"
        """
        msg_lower = message.lower()
        if any(kw in msg_lower for kw in _FACTUAL_KEYWORDS):
            return "factual"
        if any(kw in msg_lower for kw in _ANALYSIS_KEYWORDS):
            return "analysis"
        return "chat"

    # ── Chat libera ───────────────────────────────────────────────────────────

    def _chat(self, message: str) -> str:
        """
        Chat libera con routing intelligente per tipo di query:
        - factual  → Knowledge Base first, AI solo se non trovato
        - analysis → DeepSeek FAST + HallucinationGuard
        - chat     → Claude Haiku con system prompt blindato
        """
        intent = self._detect_intent(message)

        # ── 1. Query fattuale: vai prima in KB ───────────────────────────────
        if intent == "factual":
            kb_answer = self._kb.lookup_fact(message)
            if kb_answer:
                log.info(
                    "Risposta da KB (no AI call)",
                    action=LogAction.QUERY, status=LogStatus.OK,
                    extra={"intent": "factual", "kb_hit": True},
                )
                return f"{kb_answer}\n\n*[Fonte: Knowledge Base aziendale]*"
            # Non trovato in KB — rispondi onestamente senza inventare
            return (
                "Non ho questa informazione nella Knowledge Base aziendale.\n"
                "Puoi aggiungerla con `/teach <fatto>` — esempio:\n"
                "`/teach Il nostro sito è https://faberweb.it`\n"
                "`/teach Email contatti: info@faberweb.it`"
            )

        # ── 2. Query di analisi: DeepSeek + guard ────────────────────────────
        if intent == "analysis":
            return self._chat_with_guard(
                message,
                role=ModelRole.FAST,
                source_text=self._kb.build_context_prompt() or message,
            )

        # ── 3. Chat libera: Claude Haiku con system prompt blindato ──────────
        return self._chat_with_guard(
            message,
            role=ModelRole.CHAT,
            source_text="",
        )

    def _chat_with_guard(
        self,
        message: str,
        role: ModelRole,
        source_text: str,
    ) -> str:
        """Chiama l'AI e passa l'output attraverso HallucinationGuard."""
        context = self._kb.build_context_prompt()

        # ── System prompt blindato anti-allucinazione ─────────────────────
        system_prompt = (
            f"Sei WorkMind, l'assistente operativo di {self._company.name} "
            f"(settore: {self._company.sector}). "
            f"Rispondi in italiano in modo conciso e actionable.\n\n"
            f"REGOLE FONDAMENTALI — rispetta sempre:\n"
            f"1. NON inventare URL, email, numeri di telefono, indirizzi o dati di contatto.\n"
            f"2. Se non hai un'informazione con certezza, rispondi: "
            f"\"Non ho questa informazione. Aggiungila con /teach.\"\n"
            f"3. Usa SOLO fatti presenti nella Knowledge Base qui sotto o nel testo originale.\n"
            f"4. Non completare con dati plausibili ma non verificati.\n"
            f"5. Il dominio di WorkMind NON è workmind.dev — non esiste un sito pubblico.\n"
        )
        if context:
            system_prompt += f"\n--- KNOWLEDGE BASE AZIENDALE ---\n{context}\n---\n"

        try:
            response = self._ai.complete_simple(
                message,
                system_prompt=system_prompt,
                role=role,
                max_tokens=512,
                temperature=0.2,   # più bassa = meno "creatività" = meno allucinazioni
            )

            # ── Passa per HallucinationGuard ──────────────────────────────
            if source_text:
                result = self._guard.validate(response, source_text, context=message)
                if not result.is_valid:
                    warning = (
                        f"\n\n⚠️ *Attenzione: ho rilevato {len(result.issues)} possibili "
                        f"imprecisioni in questa risposta. Verifica prima di usarla.*"
                    )
                    log.warning(
                        "HallucinationGuard: problemi rilevati in chat",
                        action=LogAction.VALIDATE, status=LogStatus.WARNING,
                        extra={"issues": result.issues[:3]},
                    )
                    return response + warning

            return response

        except Exception as exc:
            log.error(
                f"Errore chat: {exc}",
                action=LogAction.QUERY, status=LogStatus.ERROR,
            )
            return f"Errore AI: {exc}"
