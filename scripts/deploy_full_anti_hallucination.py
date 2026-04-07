#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deploy completo sistema anti-allucinazione su Bender."""
import sys, os, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import paramiko

BENDER_HOST = "100.116.199.50"
BENDER_USER = "emanuele"
BENDER_KEY  = os.path.expanduser("~/.ssh/workmind_hub")
REMOTE_DIR  = "/home/emanuele/workmind"
LOCAL_BASE  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
print("[*] Connessione a Bender (SSH key)...")
ssh.connect(BENDER_HOST, username=BENDER_USER, key_filename=BENDER_KEY, timeout=10)
sftp = ssh.open_sftp()
print("[+] Connesso\n")

def run(cmd, timeout=60):
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    for ln in out.split("\n")[-5:]:
        if ln: print(f"  {ln}")
    return out, err

def upload(rel):
    local = os.path.join(LOCAL_BASE, rel.replace("/", os.sep))
    if not os.path.exists(local):
        print(f"  SKIP (non trovato): {rel}")
        return
    remote = f"{REMOTE_DIR}/{rel}"
    rdir = "/".join(remote.split("/")[:-1])
    try: sftp.stat(rdir)
    except FileNotFoundError: run(f"mkdir -p {rdir}")
    sftp.put(local, remote)
    print(f"  OK  {rel}")

print("=== Upload file aggiornati ===")
for f in [
    "ai_client/budget.py",
    "ai_client/client.py",
    "interface/chat_server.py",
    "interface/telegram_bot.py",
    "interface/whatsapp_bot.py",
    "interface/web_ui.py",
    "storage/knowledge_base.py",
    "nlp/hallucination_guard.py",
]:
    upload(f)

print("\n=== Riavvio WorkMind ===")
run("echo '195183_crea' | sudo -S systemctl restart workmind 2>&1", timeout=30)
time.sleep(7)
out, _ = run("echo '195183_crea' | sudo -S systemctl is-active workmind 2>&1")
print(f"  WorkMind: {out.strip()}")

if out.strip() != "active":
    print("  [!] Controllo log...")
    run("echo '195183_crea' | sudo -S journalctl -u workmind -n 20 --no-pager 2>&1")

print("\n=== Health check ===")
time.sleep(3)
out, _ = run("curl -sk -o /dev/null -w '%{http_code}' https://localhost/login")
print(f"  HTTPS /login -> HTTP {out}")

print("\n=== Test KB anti-allucinazione ===")
run(f"python3 -c \"import sys; sys.path.insert(0, '{REMOTE_DIR}'); "
    f"from storage.knowledge_base import get_kb; "
    f"kb = get_kb(); s = kb.summary(); "
    f"print(f'KB: {{s[\\\"facts\\\"]}} fatti, {{s[\\\"glossary_terms\\\"]}} glossario'); "
    f"r = kb.lookup_fact('sito workmind'); "
    f"print(f'Lookup workmind: {{r[:80] if r else \\\"NOT FOUND\\\"}}')\"",
    timeout=20)

sftp.close(); ssh.close()
print("\n=== DEPLOY COMPLETATO ===")
print("  Sistema anti-allucinazione attivo su tutti i canali:")
print("  - Web UI  (chat + KB CRUD page)")
print("  - Telegram (grounding + /kb comandi)")
print("  - WhatsApp (guard + KB-first factual)")
print("  - Chat server (/kb list/search/clear/export)")
print("  - Budget tracking per modello (Haiku/Sonnet/DeepSeek)")
print("  - Claude API key: attiva")
