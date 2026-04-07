"""
WorkMind Request Advisor
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

"Product manager virtuale" che guida l'utente da un'idea vaga a una
richiesta strutturata, senza tecnicismi.

Flusso conversazionale:
  1. DETECTING  — intercetta l'intenzione dall'utente
  2. CLARIFYING — fa 2-3 domande mirate per capire il bisogno reale
  3. PROPOSING  — presenta 2-3 soluzioni concrete in linguaggio semplice
  4. CONFIRMED  — formalizza e invia la richiesta al pipeline

Canali supportati: web, telegram, whatsapp
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from ai_client.client import get_ai_client, ModelRole
from storage.knowledge_base import get_kb
from config.company import get_company_config
from logging_system import get_logger, LogAction, LogStatus

log = get_logger("mindwork.request_advisor")


# ── Parole chiave che segnalano un bisogno/richiesta ────────────────────────
_INTENT_TRIGGERS = (
    "vorrei", "volevo", "potrebbe", "si potrebbe", "sarebbe utile",
    "sarebbe bello", "mi servirebbe", "avrei bisogno", "manca",
    "mancano", "non c'è", "non esiste", "come faccio", "è possibile",
    "si può", "posso", "voglio che", "voglio poter", "vorrei che",
    "ho bisogno", "serve", "servono", "/idea", "/voglio", "/bisogno",
    "aggiungere", "aggiungerei", "implementare", "integrare",
    "collegare", "connettere", "automatizzare", "avvisarmi",
    "notificarmi", "ricevere", "mandare", "esportare", "importare",
)

# ── Categorie di intento (determinano le domande giuste) ────────────────────
_INTENT_CATEGORIES = {
    "notifica":     "Vuole ricevere avvisi o notifiche automatiche",
    "report":       "Vuole analisi, riepiloghi o statistiche periodiche",
    "integrazione": "Vuole collegare un sistema o servizio esterno",
    "automazione":  "Vuole automatizzare un'attività ripetitiva",
    "comunicazione":"Vuole gestire comunicazioni (email, WhatsApp, ecc.)",
    "visualizzazione":"Vuole vedere dati in modo diverso o su nuova schermata",
    "export_import":"Vuole importare o esportare dati in vari formati",
    "accesso":      "Vuole gestire utenti, permessi o accessi",
    "altro":        "Richiesta generica o non classificabile",
}

# ── Domande di chiarimento per categoria ────────────────────────────────────
_CLARIFYING_QUESTIONS: dict[str, list[str]] = {
    "notifica": [
        "Quando vorresti ricevere questo avviso? (es. subito, ogni ora, ogni giorno...)",
        "Come preferisci ricevere la notifica? (WhatsApp, Telegram, email, schermo...)",
        "Deve avvisare solo te, o anche altre persone?",
        "Ci sono condizioni particolari? (es. solo se supera un certo importo, solo certi clienti...)",
    ],
    "report": [
        "Con che frequenza ti serve questo riepilogo? (ogni giorno, settimana, mese...)",
        "Che informazioni deve contenere? (es. vendite, ordini, clienti nuovi...)",
        "Come lo vuoi ricevere? (email, PDF, schermata nell'app...)",
        "Serve confrontare con periodi precedenti?",
    ],
    "integrazione": [
        "Con quale sistema vuoi collegarti? (es. gestionale, e-commerce, banca...)",
        "Cosa deve succedere quando si connettono? (es. aggiornamento automatico, importazione dati...)",
        "I dati devono andare in una direzione sola o in entrambe?",
    ],
    "automazione": [
        "Cosa scatena l'azione automatica? (es. un nuovo ordine, un orario fisso, un evento...)",
        "Cosa deve fare esattamente il sistema in automatico?",
        "Cosa succede se l'operazione automatica va storta? Vuoi essere avvisato?",
    ],
    "comunicazione": [
        "A chi devono arrivare questi messaggi? (clienti, fornitori, colleghi...)",
        "Tramite quale canale? (WhatsApp, email, Telegram, tutti...)",
        "I messaggi devono essere sempre uguali o personalizzati per ciascuno?",
        "Devono partire in automatico o vuoi avviare tu ogni volta?",
    ],
    "visualizzazione": [
        "Che dati vorresti vedere in questa nuova schermata?",
        "Chi la userebbe? Solo tu, o anche altri?",
        "Hai in mente come dovrebbe essere organizzata? (tabella, grafico, lista...)",
    ],
    "export_import": [
        "Che tipo di file ti serve? (Excel, PDF, CSV...)",
        "Quali dati vuoi includere?",
        "Deve succedere automaticamente o quando lo richiedi tu?",
    ],
    "accesso": [
        "Quante persone dovrebbero avere accesso?",
        "Cosa devono poter fare e cosa no?",
        "Devono poter vedere tutto o solo alcune sezioni?",
    ],
    "altro": [
        "Puoi descrivere cosa succede adesso e cosa vorresti che succedesse?",
        "Chi userebbe questa funzione, principalmente tu o anche altri?",
        "Con che frequenza pensi che si userebbe?",
    ],
}


# ── Stato sessione ───────────────────────────────────────────────────────────

class Phase(str, Enum):
    CLARIFYING = "clarifying"
    PROPOSING  = "proposing"
    CONFIRMED  = "confirmed"
    CANCELLED  = "cancelled"


@dataclass
class AdvisorSession:
    user_id: str
    channel: str                          # web | telegram | whatsapp
    raw_text: str                         # testo originale dell'utente
    intent_category: str = "altro"
    intent_summary: str = ""              # sintesi intento in italiano semplice
    answers: list[str] = field(default_factory=list)
    questions_asked: list[str] = field(default_factory=list)
    proposals: list[dict] = field(default_factory=list)  # [{label, title, description, complexity}]
    selected_proposal: Optional[int] = None
    phase: Phase = Phase.CLARIFYING
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def touch(self):
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def to_full_description(self) -> str:
        """Ricostruisce la descrizione completa per il pipeline feature request."""
        lines = [f"RICHIESTA UTENTE: {self.raw_text}"]
        if self.intent_summary:
            lines.append(f"BISOGNO REALE: {self.intent_summary}")
        if self.questions_asked and self.answers:
            lines.append("\nDETTAGLI RACCOLTI:")
            for q, a in zip(self.questions_asked, self.answers):
                lines.append(f"  Q: {q}")
                lines.append(f"  A: {a}")
        if self.selected_proposal is not None and self.proposals:
            p = self.proposals[self.selected_proposal]
            lines.append(f"\nSOLUZIONE SCELTA: [{p['label']}] {p['title']}")
            lines.append(f"DESCRIZIONE: {p['description']}")
        return "\n".join(lines)


@dataclass
class AdvisorResponse:
    message: str                         # testo da inviare all'utente
    phase: Phase                         # fase corrente dopo l'elaborazione
    request_submitted: bool = False      # True se la richiesta è stata inviata
    request_id: Optional[int] = None
    request_level: Optional[str] = None  # auto | review | block


# ── Advisor ──────────────────────────────────────────────────────────────────

class FeatureRequestAdvisor:
    """
    Conduce una conversazione guidata per raccogliere i requisiti di una
    nuova funzionalità, poi li formalizza nel pipeline feature request.
    """

    # Timeout sessione: 10 minuti di inattività = sessione scartata
    _SESSION_TIMEOUT_S = 600

    def __init__(self) -> None:
        self._ai = get_ai_client()
        self._kb = get_kb()
        self._company = get_company_config()
        self._sessions: dict[str, AdvisorSession] = {}
        self._lock = threading.Lock()
        # Cleanup thread
        threading.Thread(target=self._cleanup_loop, daemon=True).start()

    # ── Punto di ingresso principale ─────────────────────────────────────────

    def has_active_session(self, user_id: str) -> bool:
        with self._lock:
            s = self._sessions.get(user_id)
            if not s:
                return False
            # Controlla timeout
            elapsed = time.time() - datetime.fromisoformat(s.updated_at).timestamp()
            if elapsed > self._SESSION_TIMEOUT_S:
                del self._sessions[user_id]
                return False
            return s.phase not in (Phase.CONFIRMED, Phase.CANCELLED)

    def is_intent_trigger(self, text: str) -> bool:
        """Rileva se il messaggio esprime un bisogno/richiesta."""
        t = text.lower().strip()
        return any(trigger in t for trigger in _INTENT_TRIGGERS)

    def start(self, user_id: str, channel: str, text: str) -> AdvisorResponse:
        """Avvia una nuova sessione di raccolta requisiti."""
        # Analizza intento con AI
        intent_cat, intent_summary = self._detect_intent(text)

        session = AdvisorSession(
            user_id=user_id,
            channel=channel,
            raw_text=text,
            intent_category=intent_cat,
            intent_summary=intent_summary,
        )

        # Seleziona le prime 2 domande più rilevanti
        questions = _CLARIFYING_QUESTIONS.get(intent_cat, _CLARIFYING_QUESTIONS["altro"])
        first_questions = questions[:2]
        session.questions_asked = first_questions

        with self._lock:
            self._sessions[user_id] = session

        # Messaggio iniziale
        intro = self._build_intro(intent_summary, intent_cat)
        questions_text = self._format_questions(first_questions)
        message = f"{intro}\n\n{questions_text}"

        log.info(
            f"Advisor: nuova sessione per {user_id} (categoria: {intent_cat})",
            action=LogAction.QUERY, status=LogStatus.OK,
        )
        return AdvisorResponse(message=message, phase=Phase.CLARIFYING)

    def process(self, user_id: str, text: str) -> AdvisorResponse:
        """Processa una risposta dell'utente in una sessione attiva."""
        text = text.strip()

        # Annullamento esplicito
        if text.lower() in ("annulla", "cancel", "esci", "stop", "basta", "no"):
            return self._cancel(user_id)

        with self._lock:
            session = self._sessions.get(user_id)
        if not session:
            return AdvisorResponse(
                message="Sessione scaduta. Puoi ripetere la tua richiesta.",
                phase=Phase.CANCELLED,
            )

        session.touch()

        if session.phase == Phase.CLARIFYING:
            return self._handle_clarification(session, text)
        elif session.phase == Phase.PROPOSING:
            return self._handle_selection(session, text)
        else:
            return AdvisorResponse(message="Richiesta già completata.", phase=session.phase)

    def cancel(self, user_id: str) -> None:
        """Annulla la sessione corrente."""
        with self._lock:
            self._sessions.pop(user_id, None)

    # ── Step 1: Detect intent ────────────────────────────────────────────────

    def _detect_intent(self, text: str) -> tuple[str, str]:
        """Classifica il tipo di richiesta e sintetizza il bisogno reale."""
        categories_list = "\n".join(
            f"- {k}: {v}" for k, v in _INTENT_CATEGORIES.items()
        )
        prompt = (
            f"Un utente di un'azienda ({self._company.sector}) ha scritto:\n"
            f'"{text}"\n\n'
            f"Classifica il bisogno in una di queste categorie:\n{categories_list}\n\n"
            f"Rispondi SOLO con JSON:\n"
            f'{{"category": "nome_categoria", "summary": "descrizione bisogno in 1 frase semplice, senza tecnicismi"}}'
        )
        try:
            resp = self._ai.complete_simple(
                prompt, role=ModelRole.FAST,
                max_tokens=150, temperature=0.1,
            )
            data = json.loads(resp.strip())
            cat = data.get("category", "altro")
            if cat not in _INTENT_CATEGORIES:
                cat = "altro"
            return cat, data.get("summary", text[:100])
        except Exception:
            return "altro", text[:100]

    # ── Step 2: Handle clarification answers ────────────────────────────────

    def _handle_clarification(self, session: AdvisorSession, answer: str) -> AdvisorResponse:
        """Raccoglie risposte e decide se fare altre domande o passare alle proposte."""
        session.answers.append(answer)

        # Abbiamo abbastanza informazioni? (max 3 domande totali)
        questions_pool = _CLARIFYING_QUESTIONS.get(
            session.intent_category, _CLARIFYING_QUESTIONS["altro"]
        )
        total_asked = len(session.questions_asked)
        has_enough = total_asked >= 2 or len(session.answers) >= 2

        if not has_enough and total_asked < len(questions_pool):
            # Fai un'altra domanda
            next_q = questions_pool[total_asked]
            session.questions_asked.append(next_q)
            return AdvisorResponse(
                message=f"Capito! Ultima cosa:\n\n**{next_q}**",
                phase=Phase.CLARIFYING,
            )

        # Passa alla fase proposte
        return self._generate_proposals(session)

    # ── Step 3: Generate proposals ───────────────────────────────────────────

    def _generate_proposals(self, session: AdvisorSession) -> AdvisorResponse:
        """Genera 2-3 proposte concrete basate sulle informazioni raccolte."""
        # Costruisci il contesto completo
        context_parts = [f"Bisogno utente: {session.raw_text}"]
        if session.intent_summary:
            context_parts.append(f"Bisogno reale: {session.intent_summary}")
        for q, a in zip(session.questions_asked, session.answers):
            context_parts.append(f"D: {q} → R: {a}")
        full_context = "\n".join(context_parts)

        kb_context = self._kb.build_context_prompt()
        prompt = (
            f"Sei un consulente che propone soluzioni semplici a un'azienda "
            f"nel settore {self._company.sector}.\n\n"
            f"BISOGNO RACCOLTO:\n{full_context}\n\n"
            + (f"DATI AZIENDA:\n{kb_context}\n\n" if kb_context else "")
            + "Proponi 2 o 3 soluzioni DIVERSE (dalla più semplice alla più completa).\n"
            f"Per ciascuna:\n"
            f"- Spiega cosa fa in modo semplice, senza tecnicismi\n"
            f"- Indica quanto è immediata: 'Subito', 'In pochi giorni', 'Qualche settimana'\n"
            f"- Non inventare funzionalità che non esistono nel sistema\n\n"
            f"Rispondi SOLO con JSON:\n"
            f'{{"proposals": [{{'
            f'"label": "A", "title": "nome breve", '
            f'"description": "cosa fa in 2 frasi semplici", '
            f'"timeline": "Subito|In pochi giorni|Qualche settimana"'
            f'}}]}}'
        )

        try:
            resp = self._ai.complete_simple(
                prompt, role=ModelRole.CHAT,
                max_tokens=600, temperature=0.4,
            )
            # Estrai JSON (può essere dentro backtick)
            raw = resp.strip()
            if "```" in raw:
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw)
            proposals = data.get("proposals", [])
        except Exception as exc:
            log.warning(f"Advisor: errore generazione proposte: {exc}",
                        action=LogAction.QUERY)
            proposals = [{
                "label": "A",
                "title": "Richiesta personalizzata",
                "description": (
                    "Implementiamo esattamente quello che hai descritto. "
                    "Il team valuterà i dettagli tecnici."
                ),
                "timeline": "In pochi giorni",
            }]

        # Massimo 3 proposte
        proposals = proposals[:3]
        session.proposals = proposals
        session.phase = Phase.PROPOSING

        return AdvisorResponse(
            message=self._format_proposals(proposals),
            phase=Phase.PROPOSING,
        )

    # ── Step 4: Handle selection ─────────────────────────────────────────────

    def _handle_selection(self, session: AdvisorSession, text: str) -> AdvisorResponse:
        """Gestisce la scelta della proposta e invia la richiesta."""
        text_upper = text.upper().strip()
        labels = [p["label"] for p in session.proposals]

        # Riconosce selezione (A, B, C / 1, 2, 3 / "prima", "seconda"...)
        selected_idx = None
        if text_upper in labels:
            selected_idx = labels.index(text_upper)
        elif text in ("1", "2", "3") and int(text) - 1 < len(session.proposals):
            selected_idx = int(text) - 1
        elif any(w in text.lower() for w in ("prima", "opzione a", "soluzione a")):
            selected_idx = 0
        elif any(w in text.lower() for w in ("seconda", "opzione b", "soluzione b")):
            selected_idx = min(1, len(session.proposals) - 1)
        elif any(w in text.lower() for w in ("terza", "opzione c", "soluzione c")):
            selected_idx = min(2, len(session.proposals) - 1)
        elif any(w in text.lower() for w in ("tutte", "entrambe", "tutti")):
            selected_idx = len(session.proposals) - 1  # La più completa

        if selected_idx is None:
            # Non ha capito — ripropone
            label_list = " / ".join(labels)
            return AdvisorResponse(
                message=(
                    f"Scusa, non ho capito la scelta. Rispondi con **{label_list}** "
                    f"(oppure scrivi 'annulla' per uscire)."
                ),
                phase=Phase.PROPOSING,
            )

        session.selected_proposal = selected_idx
        session.phase = Phase.CONFIRMED

        # Invia al pipeline feature request
        return self._submit_to_pipeline(session)

    # ── Submit to pipeline ────────────────────────────────────────────────────

    def _submit_to_pipeline(self, session: AdvisorSession) -> AdvisorResponse:
        """Formalizza e invia la richiesta al FeatureRequestManager."""
        try:
            from mindwork.feature_requests import get_feature_manager
            fm = get_feature_manager()

            full_description = session.to_full_description()
            req = fm.submit_request(
                text=full_description,
                submitted_by=f"{session.channel}_{session.user_id}",
                source=f"advisor_{session.channel}",
            )

            level = req.get("level", "review")
            status = req.get("status", "")
            req_id = req.get("id", 0)
            title = req.get("title", "Richiesta")

            # Pulisci sessione
            with self._lock:
                self._sessions.pop(session.user_id, None)

            # Messaggio finale in base al livello
            if status == "auto_done":
                msg = (
                    f"✅ **Fatto!** Ho già applicato la modifica.\n\n"
                    f"**{title}**\n\n"
                    f"Puoi verificare subito. Se non è come ti aspettavi, "
                    f"scrivimi e sistemiamo."
                )
            elif level == "block":
                msg = (
                    f"⛔ Questa richiesta non posso gestirla autonomamente — "
                    f"riguarda aree protette del sistema.\n\n"
                    f"Ho avvisato l'amministratore, che la valuterà."
                )
            else:
                msg = (
                    f"📋 **Richiesta #{req_id} registrata!**\n\n"
                    f"**{title}**\n\n"
                    f"L'ho inoltrata all'amministratore per l'approvazione. "
                    f"Riceverai una notifica quando verrà presa in carico.\n\n"
                    f"Nel frattempo puoi continuare a usare il sistema normalmente."
                )

            return AdvisorResponse(
                message=msg,
                phase=Phase.CONFIRMED,
                request_submitted=True,
                request_id=req_id,
                request_level=level,
            )

        except Exception as exc:
            log.error(f"Advisor: errore submit: {exc}", action=LogAction.QUERY)
            return AdvisorResponse(
                message=(
                    "Ho registrato la tua richiesta, ma c'è stato un piccolo problema "
                    "tecnico. L'amministratore è stato avvisato.\n\n"
                    f"Dettaglio: {str(exc)[:100]}"
                ),
                phase=Phase.CONFIRMED,
                request_submitted=False,
            )

    # ── Cancellation ──────────────────────────────────────────────────────────

    def _cancel(self, user_id: str) -> AdvisorResponse:
        with self._lock:
            self._sessions.pop(user_id, None)
        return AdvisorResponse(
            message=(
                "Ok, lasciamo perdere per ora. "
                "Se vuoi riprendere basta scrivermi di nuovo!"
            ),
            phase=Phase.CANCELLED,
        )

    # ── Formatting helpers ────────────────────────────────────────────────────

    def _build_intro(self, intent_summary: str, category: str) -> str:
        """Costruisce il messaggio introduttivo."""
        intros = {
            "notifica":     "Capisco, vuoi essere avvisato in modo automatico.",
            "report":       "Capisco, vuoi avere un riepilogo dei dati periodicamente.",
            "integrazione": "Capisco, vuoi collegare un sistema esterno.",
            "automazione":  "Capisco, vuoi automatizzare qualcosa che fai a mano.",
            "comunicazione":"Capisco, vuoi gestire le comunicazioni in modo diverso.",
            "visualizzazione":"Capisco, vuoi vedere le informazioni in modo diverso.",
            "export_import":"Capisco, vuoi spostare o convertire dei dati.",
            "accesso":      "Capisco, vuoi gestire chi può accedere a cosa.",
            "altro":        "Interessante, vediamo come posso aiutarti.",
        }
        intro = intros.get(category, "Capisco.")
        return (
            f"{intro}\n\n"
            f"Per proporti la soluzione giusta ho bisogno di capire "
            f"un po' meglio la situazione. Qualche domanda veloce:"
        )

    def _format_questions(self, questions: list[str]) -> str:
        if len(questions) == 1:
            return f"**{questions[0]}**"
        lines = []
        for i, q in enumerate(questions, 1):
            lines.append(f"**{i}.** {q}")
        return "\n".join(lines)

    def _format_proposals(self, proposals: list[dict]) -> str:
        lines = [
            "Perfetto! In base a quello che mi hai detto, "
            "ecco cosa posso fare:\n"
        ]
        for p in proposals:
            timeline_icon = {"Subito": "⚡", "In pochi giorni": "📅",
                             "Qualche settimana": "🗓️"}.get(p.get("timeline", ""), "📌")
            lines.append(
                f"**[{p['label']}] {p['title']}** {timeline_icon} *{p.get('timeline', '')}*\n"
                f"{p['description']}\n"
            )
        label_list = " / ".join(p["label"] for p in proposals)
        lines.append(
            f"Quale preferisci? Rispondi con **{label_list}** "
            f"(o scrivi 'annulla' per lasciare perdere)."
        )
        return "\n".join(lines)

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def _cleanup_loop(self) -> None:
        """Rimuove sessioni scadute ogni 5 minuti."""
        while True:
            time.sleep(300)
            try:
                now = time.time()
                with self._lock:
                    expired = [
                        uid for uid, s in self._sessions.items()
                        if now - datetime.fromisoformat(s.updated_at).timestamp()
                        > self._SESSION_TIMEOUT_S
                    ]
                    for uid in expired:
                        del self._sessions[uid]
                if expired:
                    log.info(f"Advisor: rimosso {len(expired)} sessioni scadute",
                             action=LogAction.MONITOR)
            except Exception:
                pass


# ── Singleton ─────────────────────────────────────────────────────────────────

_advisor: Optional[FeatureRequestAdvisor] = None
_advisor_lock = threading.Lock()


def get_advisor() -> FeatureRequestAdvisor:
    global _advisor
    if _advisor is None:
        with _advisor_lock:
            if _advisor is None:
                _advisor = FeatureRequestAdvisor()
    return _advisor
