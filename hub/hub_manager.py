"""
WorkMind Hub Manager
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Pannello di gestione centralizzato per tutti i client WorkMind.
Connette via SSH (attraverso Tailscale VPN) a ogni macchina client.

Uso:
    python hub/hub_manager.py status          # Stato di tutti i client
    python hub/hub_manager.py deploy all      # Deploy aggiornamento a tutti
    python hub/hub_manager.py deploy bender   # Deploy a client specifico
    python hub/hub_manager.py logs bender     # Ultimi log di un client
    python hub/hub_manager.py plugin bender install whatsapp
    python hub/hub_manager.py shell bender    # Shell SSH interattiva
    python hub/hub_manager.py add-client      # Wizard aggiungi client
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

try:
    import paramiko
    HAS_PARAMIKO = True
except ImportError:
    HAS_PARAMIKO = False

HUB_DIR = Path(__file__).parent
CLIENTS_FILE = HUB_DIR / "clients.json"
WORKMIND_ROOT = HUB_DIR.parent

# Colori terminale
_G = "\033[32m"   # verde
_R = "\033[31m"   # rosso
_Y = "\033[33m"   # giallo
_B = "\033[34m"   # blu
_C = "\033[36m"   # ciano
_W = "\033[1m"    # bold
_X = "\033[0m"    # reset


def _print(msg: str, color: str = "") -> None:
    print(f"{color}{msg}{_X}")


# ── Client Registry ───────────────────────────────────────────────────────────

def load_clients() -> list[dict]:
    if CLIENTS_FILE.exists():
        return json.loads(CLIENTS_FILE.read_text(encoding="utf-8")).get("clients", [])
    return []


def save_clients(clients: list[dict]) -> None:
    CLIENTS_FILE.write_text(
        json.dumps({"clients": clients}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def get_client(client_id: str) -> Optional[dict]:
    for c in load_clients():
        if c["id"] == client_id or c["name"].lower() == client_id.lower():
            return c
    return None


# ── SSH Connection ────────────────────────────────────────────────────────────

def _ssh_connect(client: dict) -> "paramiko.SSHClient":
    if not HAS_PARAMIKO:
        raise RuntimeError("Installa paramiko: pip install paramiko")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    # Usa Tailscale IP se disponibile, altrimenti hostname
    host = client.get("tailscale_ip") or client.get("hostname")
    port = client.get("ssh_port", 22)
    user = client.get("ssh_user", "ubuntu")

    # Cerca chiave SSH
    key_path = os.path.expanduser("~/.ssh/id_rsa")
    if os.path.exists(key_path):
        ssh.connect(host, port=port, username=user, key_filename=key_path, timeout=15)
    else:
        # Chiede password (fallback)
        import getpass
        pwd = getpass.getpass(f"Password per {user}@{host}: ")
        ssh.connect(host, port=port, username=user, password=pwd, timeout=15)

    return ssh


def _run_remote(ssh: "paramiko.SSHClient", cmd: str, timeout: int = 60) -> tuple[str, str, int]:
    """Esegue comando remoto. Ritorna (stdout, stderr, exit_code)."""
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    return out.strip(), err.strip(), code


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_status(client_id: Optional[str] = None) -> None:
    """Mostra stato di tutti i client (o uno specifico)."""
    clients = load_clients()
    if client_id:
        clients = [c for c in clients if c["id"] == client_id or c["name"].lower() == client_id.lower()]

    _print(f"\n{'='*60}", _W)
    _print(f"  WorkMind Hub — Stato Client", _W)
    _print(f"{'='*60}\n", _W)

    for client in clients:
        _print(f"  {_C}{client['name']}{_X}  ({client['company']})")
        host = client.get("tailscale_ip") or client.get("hostname")
        _print(f"  Host: {host}:{client.get('ssh_port', 22)}")

        try:
            ssh = _ssh_connect(client)
            # Controlla stato servizio
            wm_dir = client.get("workmind_dir", "/home/ubuntu/workmind")
            svc = client.get("systemd_service", "workmind")
            out, _, _ = _run_remote(ssh,
                f"systemctl is-active {svc} 2>/dev/null && "
                f"curl -s -o /dev/null -w '%{{http_code}}' http://localhost:{client.get('workmind_port', 7860)}/login 2>/dev/null && "
                f"cat {wm_dir}/version.py 2>/dev/null | grep __version__ | head -1"
            )
            lines = out.split("\n")
            svc_status = lines[0].strip() if lines else "unknown"
            http_code = lines[1].strip() if len(lines) > 1 else "?"
            version = lines[2].strip() if len(lines) > 2 else "?"

            color = _G if svc_status == "active" else _R
            _print(f"  Servizio: {color}{svc_status}{_X}  HTTP: {http_code}  {version}")

            # Plugin attivi
            plugins_out, _, _ = _run_remote(ssh,
                f"cat {wm_dir}/data/plugins_enabled.json 2>/dev/null | python3 -c 'import sys,json; d=json.load(sys.stdin); print(\",\".join(d.keys()))' 2>/dev/null"
            )
            if plugins_out:
                _print(f"  Plugin: {_C}{plugins_out}{_X}")

            # Tailscale status
            ts_out, _, ts_code = _run_remote(ssh, "tailscale status --json 2>/dev/null | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get(\"BackendState\",\"?\"))' 2>/dev/null")
            ts_ip, _, _ = _run_remote(ssh, "tailscale ip -4 2>/dev/null")
            ts_color = _G if ts_out == "Running" else _Y
            _print(f"  Tailscale: {ts_color}{ts_out or 'non installato'}{_X}  IP: {ts_ip or 'N/A'}")

            ssh.close()
        except Exception as exc:
            _print(f"  {_R}OFFLINE{_X} — {exc}")

        print()


def cmd_deploy(client_id: str, branch: str = "main") -> None:
    """Aggiorna WorkMind su un client (git pull + restart)."""
    if client_id == "all":
        for c in load_clients():
            _deploy_single(c, branch)
    else:
        client = get_client(client_id)
        if not client:
            _print(f"Client '{client_id}' non trovato", _R)
            return
        _deploy_single(client, branch)


def _deploy_single(client: dict, branch: str = "main") -> None:
    name = client["name"]
    wm_dir = client.get("workmind_dir", "/home/ubuntu/workmind")
    svc = client.get("systemd_service", "workmind")
    venv_python = client.get("venv_python", f"{wm_dir}/venv/bin/python")

    _print(f"\n→ Deploy su {name}...", _B)
    try:
        ssh = _ssh_connect(client)

        # 1. Git pull
        out, err, code = _run_remote(ssh, f"cd {wm_dir} && git pull origin {branch} 2>&1", timeout=120)
        _print(f"  git pull: {'OK' if code == 0 else 'ERRORE'}")
        if out:
            for line in out.split("\n")[-5:]:
                if line.strip():
                    print(f"    {line}")

        # 2. Pip install (se requirements aggiornati)
        out, _, code = _run_remote(ssh,
            f"cd {wm_dir} && {venv_python} -m pip install -q -r requirements.txt 2>&1 | tail -3",
            timeout=180)
        _print(f"  pip install: {'OK' if code == 0 else 'ERRORE'}")

        # 3. Restart servizio
        out, _, code = _run_remote(ssh, f"sudo systemctl restart {svc} 2>&1 && sleep 5 && systemctl is-active {svc}", timeout=30)
        status = out.strip().split("\n")[-1] if out else "unknown"
        color = _G if status == "active" else _R
        _print(f"  Restart: {color}{status}{_X}")

        ssh.close()
        _print(f"  {_G}✓ Deploy completato su {name}{_X}")
    except Exception as exc:
        _print(f"  {_R}✗ Deploy fallito su {name}: {exc}{_X}")


def cmd_logs(client_id: str, lines: int = 50) -> None:
    """Mostra gli ultimi log di un client."""
    client = get_client(client_id)
    if not client:
        _print(f"Client '{client_id}' non trovato", _R)
        return
    svc = client.get("systemd_service", "workmind")
    try:
        ssh = _ssh_connect(client)
        out, _, _ = _run_remote(ssh, f"journalctl -u {svc} -n {lines} --no-pager 2>/dev/null", timeout=15)
        print(out)
        ssh.close()
    except Exception as exc:
        _print(f"Errore: {exc}", _R)


def cmd_plugin(client_id: str, action: str, plugin_id: str) -> None:
    """Gestisce plugin su un client: install/uninstall/list."""
    client = get_client(client_id)
    if not client:
        _print(f"Client '{client_id}' non trovato", _R)
        return

    wm_dir = client.get("workmind_dir", "/home/ubuntu/workmind")
    venv_python = client.get("venv_python", f"{wm_dir}/venv/bin/python")
    plugins_file = f"{wm_dir}/data/plugins_enabled.json"

    try:
        ssh = _ssh_connect(client)

        if action == "list":
            out, _, _ = _run_remote(ssh, f"cat {plugins_file} 2>/dev/null || echo '{{}}'")
            _print(f"Plugin attivi su {client['name']}:")
            try:
                data = json.loads(out)
                for pid, ver in data.items():
                    _print(f"  {_G}✓{_X} {pid} ({ver})")
            except Exception:
                print(out)

        elif action == "install":
            out, _, _ = _run_remote(ssh,
                f"cd {wm_dir} && {venv_python} -c \""
                f"import json, sys; "
                f"p=json.load(open('{plugins_file}')) if __import__('os').path.exists('{plugins_file}') else {{}}; "
                f"p['{plugin_id}']='latest'; "
                f"json.dump(p, open('{plugins_file}','w'), indent=2)"
                f"\" 2>&1"
            )
            _print(f"Plugin {plugin_id} aggiunto alla lista.")
            # Restart per caricare
            svc = client.get("systemd_service", "workmind")
            _run_remote(ssh, f"sudo systemctl restart {svc}")
            _print(f"{_G}✓ Plugin {plugin_id} installato e servizio riavviato{_X}")

        elif action == "uninstall":
            out, _, _ = _run_remote(ssh,
                f"cd {wm_dir} && {venv_python} -c \""
                f"import json, os; "
                f"p=json.load(open('{plugins_file}')) if os.path.exists('{plugins_file}') else {{}}; "
                f"p.pop('{plugin_id}', None); "
                f"json.dump(p, open('{plugins_file}','w'), indent=2)"
                f"\" 2>&1"
            )
            svc = client.get("systemd_service", "workmind")
            _run_remote(ssh, f"sudo systemctl restart {svc}")
            _print(f"{_G}✓ Plugin {plugin_id} rimosso{_X}")

        ssh.close()
    except Exception as exc:
        _print(f"Errore: {exc}", _R)


def cmd_shell(client_id: str) -> None:
    """Apre una sessione SSH interattiva sul client."""
    client = get_client(client_id)
    if not client:
        _print(f"Client '{client_id}' non trovato", _R)
        return
    host = client.get("tailscale_ip") or client.get("hostname")
    port = client.get("ssh_port", 22)
    user = client.get("ssh_user", "ubuntu")
    _print(f"Connessione SSH a {user}@{host}:{port}...", _B)
    os.execvp("ssh", ["ssh", "-p", str(port), f"{user}@{host}"])


def cmd_add_client() -> None:
    """Wizard interattivo per aggiungere un nuovo client."""
    _print("\n=== Aggiungi Nuovo Client WorkMind ===\n", _W)

    client_id = input("ID client (es. client-mario): ").strip()
    name = input("Nome descrittivo (es. Mario SRL): ").strip()
    company = input("Nome azienda: ").strip()
    tailscale_ip = input("IP Tailscale (es. 100.64.x.x, invio se non ancora noto): ").strip() or None
    hostname = input("Hostname/IP locale (fallback se no Tailscale): ").strip()
    ssh_user = input("Utente SSH (default: ubuntu): ").strip() or "ubuntu"
    ssh_port = int(input("Porta SSH (default: 22): ").strip() or "22")
    wm_dir = input(f"Directory WorkMind (default: /home/{ssh_user}/workmind): ").strip() or f"/home/{ssh_user}/workmind"

    clients = load_clients()
    new_client = {
        "id": client_id,
        "name": name,
        "company": company,
        "hostname": hostname,
        "tailscale_ip": tailscale_ip,
        "ssh_user": ssh_user,
        "ssh_port": ssh_port,
        "workmind_port": 7860,
        "workmind_dir": wm_dir,
        "venv_python": f"{wm_dir}/venv/bin/python",
        "systemd_service": "workmind",
        "plugins_enabled": ["feature_requests", "voice_telegram", "telegram_notifications", "backup"],
        "workmind_version": "latest",
        "status": "active",
        "notes": "",
    }
    clients.append(new_client)
    save_clients(clients)

    _print(f"\n{_G}✓ Client '{client_id}' aggiunto.{_X}")
    _print(f"\nPer installare WorkMind + Tailscale sul client, esegui su {hostname}:")
    _print(f"  curl -fsSL https://raw.githubusercontent.com/toprecensione/workmind/main/scripts/setup_client.sh | bash", _C)
    _print(f"\nDopo l'installazione, aggiorna il Tailscale IP con:")
    _print(f"  python hub/hub_manager.py status {client_id}", _C)


def cmd_tailscale_info(client_id: str) -> None:
    """Mostra info Tailscale di un client e aggiorna il registro."""
    client = get_client(client_id)
    if not client:
        _print(f"Client '{client_id}' non trovato", _R)
        return
    try:
        ssh = _ssh_connect(client)
        ts_ip, _, _ = _run_remote(ssh, "tailscale ip -4 2>/dev/null")
        ts_status, _, _ = _run_remote(ssh, "tailscale status 2>/dev/null | head -5")
        ssh.close()

        _print(f"\nTailscale su {client['name']}:")
        _print(f"  IP: {_G}{ts_ip}{_X}")
        print(ts_status)

        if ts_ip:
            # Aggiorna il registro
            clients = load_clients()
            for c in clients:
                if c["id"] == client["id"]:
                    c["tailscale_ip"] = ts_ip.strip()
            save_clients(clients)
            _print(f"\n{_G}✓ IP Tailscale aggiornato nel registro: {ts_ip.strip()}{_X}")
    except Exception as exc:
        _print(f"Errore: {exc}", _R)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]
    if not args:
        _print(__doc__, _W)
        return

    cmd = args[0]

    if cmd == "status":
        cmd_status(args[1] if len(args) > 1 else None)

    elif cmd == "deploy":
        if len(args) < 2:
            _print("Uso: hub_manager.py deploy <client_id|all> [branch]", _Y)
            return
        branch = args[2] if len(args) > 2 else "main"
        cmd_deploy(args[1], branch)

    elif cmd == "logs":
        if len(args) < 2:
            _print("Uso: hub_manager.py logs <client_id> [n_lines]", _Y)
            return
        lines = int(args[2]) if len(args) > 2 else 50
        cmd_logs(args[1], lines)

    elif cmd == "plugin":
        if len(args) < 4:
            _print("Uso: hub_manager.py plugin <client_id> <install|uninstall|list> [plugin_id]", _Y)
            return
        cmd_plugin(args[1], args[2], args[3] if len(args) > 3 else "")

    elif cmd == "shell":
        if len(args) < 2:
            _print("Uso: hub_manager.py shell <client_id>", _Y)
            return
        cmd_shell(args[1])

    elif cmd == "add-client":
        cmd_add_client()

    elif cmd == "tailscale":
        if len(args) < 2:
            _print("Uso: hub_manager.py tailscale <client_id>", _Y)
            return
        cmd_tailscale_info(args[1])

    else:
        _print(f"Comando sconosciuto: {cmd}", _R)
        _print("Comandi: status, deploy, logs, plugin, shell, add-client, tailscale")


if __name__ == "__main__":
    main()
