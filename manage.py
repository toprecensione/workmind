#!/usr/bin/env python3
"""
WorkMind Management CLI
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Comandi disponibili:
    python manage.py plugin list              - Elenca plugin disponibili/attivi
    python manage.py plugin install <id>      - Abilita un plugin
    python manage.py plugin uninstall <id>    - Disabilita un plugin
    python manage.py plugin status            - Stato plugin caricati

    python manage.py db migrate               - Inizializza/migra storage
    python manage.py db backup                - Crea backup manuale
    python manage.py db restore <file>        - Ripristina backup

    python manage.py user list                - Elenca utenti
    python manage.py user create <email>      - Crea utente
    python manage.py user delete <email>      - Elimina utente
    python manage.py user reset-pw <email>    - Reset password

    python manage.py smtp test                - Testa connessione SMTP

    python manage.py tailscale status         - Stato Tailscale
    python manage.py tailscale ip             - IP Tailscale corrente

    python manage.py version                  - Versione WorkMind
    python manage.py check                    - Verifica dipendenze
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

_G = "\033[32m"; _R = "\033[31m"; _Y = "\033[33m"; _B = "\033[34m"
_W = "\033[1m";  _X = "\033[0m"

def ok(msg):   print(f"{_G}[OK]{_X} {msg}")
def err(msg):  print(f"{_R}[ERR]{_X} {msg}")
def info(msg): print(f"{_B}[..]{_X} {msg}")
def warn(msg): print(f"{_Y}[!!]{_X} {msg}")


# ── Plugin commands ───────────────────────────────────────────────────────────

def cmd_plugin(args):
    if not args:
        print("Uso: manage.py plugin <list|install|uninstall|status>")
        return

    sub = args[0]

    if sub == "list":
        import plugin_loader
        available = plugin_loader.list_available()
        loaded = {p["id"] for p in plugin_loader.status_all()}
        print(f"\n{_W}Plugin disponibili:{_X}\n")
        for p in available:
            enabled = f"{_G}ATTIVO{_X}" if p.get("enabled") else f"{_Y}DISABILITATO{_X}"
            print(f"  {p['id']:25s} v{p.get('version','?'):8s} {enabled}  {p.get('description','')[:50]}")
        print()

    elif sub == "install":
        if len(args) < 2:
            err("Uso: manage.py plugin install <id> [version]")
            return
        pid = args[1]
        ver = args[2] if len(args) > 2 else "latest"
        import plugin_loader
        plugin_loader.enable_plugin(pid, ver)
        ok(f"Plugin '{pid}' abilitato. Riavvia WorkMind per applicare.")

    elif sub == "uninstall":
        if len(args) < 2:
            err("Uso: manage.py plugin uninstall <id>")
            return
        import plugin_loader
        ok_ = plugin_loader.disable_plugin(args[1])
        if ok_:
            ok(f"Plugin '{args[1]}' disabilitato.")
        else:
            err(f"Impossibile disabilitare '{args[1]}' (core plugin o non trovato).")

    elif sub == "status":
        import plugin_loader
        statuses = plugin_loader.status_all()
        if not statuses:
            warn("Nessun plugin caricato (avvia WorkMind prima).")
        for s in statuses:
            color = _G if s["enabled"] else _R
            print(f"  {s['id']:25s} v{s['version']:8s} {color}{s['enabled'] and 'OK' or 'ERR'}{_X} {s.get('error') or ''}")

    else:
        err(f"Sottocomando sconosciuto: {sub}")


# ── DB commands ───────────────────────────────────────────────────────────────

def cmd_db(args):
    sub = args[0] if args else ""

    if sub == "backup":
        from storage.backup import get_backup_manager
        bm = get_backup_manager()
        path = bm.create_backup()
        ok(f"Backup creato: {path}")

    elif sub == "restore":
        if len(args) < 2:
            err("Uso: manage.py db restore <file>")
            return
        from storage.backup import get_backup_manager
        ok_ = get_backup_manager().restore_backup(args[1])
        ok(f"Ripristino {'completato' if ok_ else 'fallito'}.")

    elif sub == "migrate":
        info("Inizializzazione storage...")
        from config.settings import DATA_DIR
        for d in ["chromadb", "mem0_qdrant"]:
            (DATA_DIR / d).mkdir(exist_ok=True)
        ok("Storage inizializzato.")

    else:
        err(f"Sottocomando sconosciuto: {sub}")


# ── User commands ─────────────────────────────────────────────────────────────

def cmd_user(args):
    sub = args[0] if args else ""
    from storage.user_manager import get_user_manager
    um = get_user_manager()

    if sub == "list":
        users = um.list_users()
        print(f"\n{_W}Utenti ({len(users)}):{_X}\n")
        for u in users:
            role_color = _B if u["role"] == "admin" else _X
            status = f"{_G}attivo{_X}" if u.get("active", True) else f"{_R}disattivato{_X}"
            print(f"  {u['email']:35s} {role_color}{u['role']:6s}{_X}  {status}  {u.get('name','')}")
        print()

    elif sub == "create":
        if len(args) < 2:
            err("Uso: manage.py user create <email> [nome] [admin|user]")
            return
        import getpass
        email = args[1]
        name = args[2] if len(args) > 2 else ""
        role = args[3] if len(args) > 3 else "user"
        pw = getpass.getpass(f"Password per {email}: ")
        user = um.create_user(email, pw, name=name, role=role)
        if user:
            ok(f"Utente creato: {email} ({role})")
        else:
            err(f"Utente gia' esistente: {email}")

    elif sub == "delete":
        if len(args) < 2:
            err("Uso: manage.py user delete <email>")
            return
        if um.delete_user(args[1]):
            ok(f"Utente eliminato: {args[1]}")
        else:
            err(f"Impossibile eliminare: {args[1]}")

    elif sub == "reset-pw":
        if len(args) < 2:
            err("Uso: manage.py user reset-pw <email>")
            return
        import getpass
        pw = getpass.getpass(f"Nuova password per {args[1]}: ")
        if um.change_password(args[1], pw):
            ok(f"Password cambiata per {args[1]}")
        else:
            err(f"Utente non trovato: {args[1]}")

    else:
        err(f"Sottocomando sconosciuto: {sub}")


# ── SMTP test ─────────────────────────────────────────────────────────────────

def cmd_smtp(args):
    from storage.user_manager import get_user_manager
    result = get_user_manager().test_smtp()
    if result["ok"]:
        ok(f"SMTP OK — {result['host']}:{result['port']} — {result['user']}")
    else:
        err(f"SMTP ERRORE — {result.get('error')}")


# ── Tailscale ─────────────────────────────────────────────────────────────────

def cmd_tailscale(args):
    import subprocess
    sub = args[0] if args else "status"

    if sub == "status":
        r = subprocess.run(["tailscale", "status"], capture_output=True, text=True)
        print(r.stdout or r.stderr)
    elif sub == "ip":
        r = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True)
        print("Tailscale IP:", r.stdout.strip())
    else:
        err(f"Sottocomando sconosciuto: {sub}")


# ── Version + Check ───────────────────────────────────────────────────────────

def cmd_version():
    try:
        from version import get_full_version
        print(f"WorkMind {get_full_version()}")
    except Exception:
        print("WorkMind (versione sconosciuta)")


def cmd_check():
    print(f"\n{_W}Verifica dipendenze WorkMind:{_X}\n")
    checks = [
        ("flask",          "Flask"),
        ("httpx",          "httpx"),
        ("paramiko",       "paramiko (SSH/SFTP)"),
        ("speech_recognition", "SpeechRecognition (voce)"),
        ("pydub",          "pydub (audio)"),
        ("chromadb",       "ChromaDB (RAG)"),
        ("mem0",           "Mem0 (memoria AI)"),
        ("qdrant_client",  "Qdrant (vector store)"),
        ("sentence_transformers", "sentence-transformers (embeddings)"),
        ("pykeepass",      "pykeepass (KeePass)"),
    ]
    for mod, name in checks:
        try:
            __import__(mod)
            print(f"  {_G}OK{_X}  {name}")
        except ImportError:
            print(f"  {_Y}--{_X}  {name} (non installato — opzionale)")
    print()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return

    cmd = args[0]
    rest = args[1:]

    if   cmd == "plugin":    cmd_plugin(rest)
    elif cmd == "db":        cmd_db(rest)
    elif cmd == "user":      cmd_user(rest)
    elif cmd == "smtp":      cmd_smtp(rest)
    elif cmd == "tailscale": cmd_tailscale(rest)
    elif cmd == "version":   cmd_version()
    elif cmd == "check":     cmd_check()
    else:
        err(f"Comando sconosciuto: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    main()
