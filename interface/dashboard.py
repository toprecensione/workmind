"""
WorkMind Dashboard Server
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Dashboard HTML multi-bot per monitorare tutti i nodi WorkMind
da un'unica interfaccia web. Servita come app Flask leggera.

Mostra:
- Stato di ogni bot (online/offline, ultimo heartbeat)
- Report recenti per bot
- Budget AI giornaliero
- Suggerimenti attivi
- Anomalie rilevate
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Optional

from config.settings import config, REPORT_DIR
from config.company import get_company_config
from ai_client.budget import get_budget
from storage.audit_trail import get_audit
from storage.knowledge_base import get_kb
from mindwork.feedback import get_feedback
from logging_system import get_logger, LogAction, LogStatus

log = get_logger("interface.dashboard")

_DASHBOARD_PORT = 7861


class DashboardServer:
    """
    Dashboard web per monitoraggio multi-bot.
    """

    def __init__(self, port: int = _DASHBOARD_PORT) -> None:
        self._port = port
        self._company = get_company_config()
        self._budget = get_budget()
        self._audit = get_audit()
        self._kb = get_kb()
        self._feedback = get_feedback()

    def start(self) -> None:
        t = threading.Thread(target=self._run, daemon=True, name="Dashboard")
        t.start()
        log.info(
            f"Dashboard avviata su porta {self._port}",
            action=LogAction.STARTUP, status=LogStatus.OK,
        )

    def _run(self) -> None:
        try:
            from flask import Flask, jsonify, render_template_string
        except ImportError:
            log.error(
                "Flask non installato — dashboard non disponibile",
                action=LogAction.STARTUP, status=LogStatus.ERROR,
                suggestion="pip install flask",
            )
            return

        app = Flask("workmind-dashboard")

        @app.route("/")
        def index():
            return render_template_string(
                _DASHBOARD_HTML,
                company=self._company.name,
                node_id=config.node.node_id,
                node_label=config.node.node_label,
            )

        @app.route("/api/status")
        def api_status():
            return jsonify(self._get_status())

        @app.route("/api/budget")
        def api_budget():
            return jsonify(self._budget.daily_summary())

        @app.route("/api/audit")
        def api_audit():
            events = self._audit.recent(20)
            return jsonify(events)

        @app.route("/api/feedback")
        def api_feedback():
            return jsonify(self._feedback.stats())

        @app.route("/api/kb")
        def api_kb():
            return jsonify(self._kb.summary())

        @app.route("/api/reports")
        def api_reports():
            return jsonify(self._get_recent_reports())

        app.run(host="0.0.0.0", port=self._port, debug=False, use_reloader=False)

    def _get_status(self) -> dict:
        return {
            "node_id": config.node.node_id,
            "node_label": config.node.node_label,
            "company": self._company.name,
            "sector": self._company.sector,
            "environment": config.node.environment,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "online",
            "kb": self._kb.summary(),
            "feedback": self._feedback.stats(),
        }

    def _get_recent_reports(self) -> list[dict]:
        reports = []
        report_dir = REPORT_DIR
        if report_dir.exists():
            for f in sorted(report_dir.glob("*.json"), reverse=True)[:10]:
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    reports.append({
                        "filename": f.name,
                        "generated_at": data.get("generated_at", ""),
                        "health_score": data.get("health_score", 0),
                    })
                except Exception:
                    pass
        return reports


# ─── Template HTML ────────────────────────────────────────────────────────────

_DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>WorkMind Dashboard — {{ company }}</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               background: #0f172a; color: #e2e8f0; }
        .header { background: #1e293b; padding: 1.5rem 2rem; border-bottom: 1px solid #334155;
                  display: flex; justify-content: space-between; align-items: center; }
        .header h1 { font-size: 1.5rem; color: #38bdf8; }
        .header .node { color: #94a3b8; font-size: 0.9rem; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
                gap: 1.5rem; padding: 2rem; }
        .card { background: #1e293b; border-radius: 12px; padding: 1.5rem;
                border: 1px solid #334155; }
        .card h2 { font-size: 1.1rem; color: #38bdf8; margin-bottom: 1rem;
                   display: flex; align-items: center; gap: 0.5rem; }
        .stat { display: flex; justify-content: space-between; padding: 0.5rem 0;
                border-bottom: 1px solid #334155; }
        .stat:last-child { border-bottom: none; }
        .stat .label { color: #94a3b8; }
        .stat .value { color: #f1f5f9; font-weight: 600; }
        .status-badge { display: inline-block; padding: 2px 12px; border-radius: 9999px;
                       font-size: 0.8rem; font-weight: 600; }
        .status-online { background: #064e3b; color: #34d399; }
        .status-offline { background: #450a0a; color: #f87171; }
        .event-list { max-height: 300px; overflow-y: auto; }
        .event { padding: 0.5rem 0; border-bottom: 1px solid #1e293b; font-size: 0.85rem; }
        .event .time { color: #64748b; font-size: 0.75rem; }
        .event .type { color: #38bdf8; font-weight: 600; }
        .refresh-btn { background: #0f766e; color: white; border: none; padding: 0.5rem 1rem;
                      border-radius: 6px; cursor: pointer; font-size: 0.85rem; }
        .refresh-btn:hover { background: #0d9488; }
    </style>
</head>
<body>
    <div class="header">
        <h1>WorkMind Dashboard</h1>
        <div class="node">
            <span class="status-badge status-online" id="status-badge">ONLINE</span>
            {{ node_label }} ({{ node_id }})
        </div>
    </div>

    <div class="grid">
        <div class="card">
            <h2>Stato Bot</h2>
            <div id="status-container">
                <div class="stat"><span class="label">Azienda</span><span class="value" id="s-company">-</span></div>
                <div class="stat"><span class="label">Settore</span><span class="value" id="s-sector">-</span></div>
                <div class="stat"><span class="label">Ambiente</span><span class="value" id="s-env">-</span></div>
                <div class="stat"><span class="label">Ultimo check</span><span class="value" id="s-time">-</span></div>
            </div>
        </div>

        <div class="card">
            <h2>Budget AI Oggi</h2>
            <div id="budget-container">
                <div class="stat"><span class="label">DeepSeek</span><span class="value" id="b-deepseek">-</span></div>
                <div class="stat"><span class="label">Claude</span><span class="value" id="b-claude">-</span></div>
            </div>
        </div>

        <div class="card">
            <h2>Knowledge Base</h2>
            <div id="kb-container">
                <div class="stat"><span class="label">Fatti</span><span class="value" id="kb-facts">-</span></div>
                <div class="stat"><span class="label">Correzioni</span><span class="value" id="kb-corrections">-</span></div>
                <div class="stat"><span class="label">Processi</span><span class="value" id="kb-processes">-</span></div>
                <div class="stat"><span class="label">Glossario</span><span class="value" id="kb-glossary">-</span></div>
            </div>
        </div>

        <div class="card">
            <h2>Feedback</h2>
            <div id="fb-container">
                <div class="stat"><span class="label">Totale</span><span class="value" id="fb-total">-</span></div>
                <div class="stat"><span class="label">Confermati</span><span class="value" id="fb-confirmed">-</span></div>
                <div class="stat"><span class="label">Corretti</span><span class="value" id="fb-corrected">-</span></div>
                <div class="stat"><span class="label">Accuratezza</span><span class="value" id="fb-accuracy">-</span></div>
            </div>
        </div>

        <div class="card" style="grid-column: span 2;">
            <h2>Audit Trail Recente <button class="refresh-btn" onclick="loadAll()">Aggiorna</button></h2>
            <div class="event-list" id="audit-container"></div>
        </div>
    </div>

    <script>
        async function loadAll() {
            try {
                const [status, budget, kb, fb, audit] = await Promise.all([
                    fetch('/api/status').then(r => r.json()),
                    fetch('/api/budget').then(r => r.json()),
                    fetch('/api/kb').then(r => r.json()),
                    fetch('/api/feedback').then(r => r.json()),
                    fetch('/api/audit').then(r => r.json()),
                ]);

                document.getElementById('s-company').textContent = status.company;
                document.getElementById('s-sector').textContent = status.sector || '-';
                document.getElementById('s-env').textContent = status.environment;
                document.getElementById('s-time').textContent = new Date(status.timestamp).toLocaleString('it-IT');

                const ds = budget.deepseek || {};
                const cl = budget.claude || {};
                document.getElementById('b-deepseek').textContent =
                    `$${(ds.cost_usd || 0).toFixed(4)} (${ds.calls || 0} calls)`;
                document.getElementById('b-claude').textContent =
                    `$${(cl.cost_usd || 0).toFixed(4)} (${cl.calls || 0} calls)`;

                document.getElementById('kb-facts').textContent = kb.facts || 0;
                document.getElementById('kb-corrections').textContent = kb.corrections || 0;
                document.getElementById('kb-processes').textContent = kb.processes || 0;
                document.getElementById('kb-glossary').textContent = kb.glossary_terms || 0;

                document.getElementById('fb-total').textContent = fb.total || 0;
                document.getElementById('fb-confirmed').textContent = fb.confirmed || 0;
                document.getElementById('fb-corrected').textContent = fb.corrected || 0;
                document.getElementById('fb-accuracy').textContent =
                    ((fb.accuracy_rate || 0) * 100).toFixed(0) + '%';

                const auditHtml = audit.map(e =>
                    `<div class="event">
                        <span class="time">${(e.timestamp || '').slice(0, 16)}</span>
                        <span class="type">${e.event_type}</span>
                        ${e.summary}
                    </div>`
                ).join('');
                document.getElementById('audit-container').innerHTML = auditHtml || '<p>Nessun evento</p>';
            } catch (err) {
                console.error('Dashboard load error:', err);
            }
        }
        loadAll();
        setInterval(loadAll, 30000);
    </script>
</body>
</html>
"""
