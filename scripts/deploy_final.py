#!/usr/bin/env python3
"""
WorkMind — Deploy Finale
Installa Nginx + Gunicorn + HTTPS, carica tutti i file aggiornati,
crea plugins_enabled.json, configura SSH key Hub→Bender.

Eseguire da Windows: python scripts/deploy_final.py
"""
import paramiko, os, sys, time, json

BENDER_HOST   = "100.116.199.50"   # Tailscale IP
BENDER_USER   = "emanuele"
BENDER_PASS   = "195183_crea"
REMOTE_DIR    = "/home/emanuele/workmind"
LOCAL_BASE    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── SSH ────────────────────────────────────────────────────────────────
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
print(f"[*] Connessione a Bender ({BENDER_HOST})...")
ssh.connect(BENDER_HOST, username=BENDER_USER, password=BENDER_PASS, timeout=15)
sftp = ssh.open_sftp()
print("[+] Connesso\n")

def run(cmd, timeout=120, show_all=False):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    lines = out.strip().split("\n") if out.strip() else []
    if show_all:
        for ln in lines:
            if ln: sys.stdout.buffer.write((ln + "\n").encode("utf-8", "replace"))
    else:
        for ln in lines[-5:]:
            if ln: sys.stdout.buffer.write((ln + "\n").encode("utf-8", "replace"))
    if err.strip():
        for ln in err.strip().split("\n")[-3:]:
            if ln and "WARNING" not in ln and "NOTICE" not in ln:
                sys.stdout.buffer.write(("  ERR: " + ln + "\n").encode("utf-8", "replace"))
    sys.stdout.flush()
    return out.strip(), err.strip()

def upload(local_rel, remote_rel=None):
    local  = os.path.join(LOCAL_BASE, local_rel.replace("/", os.sep))
    remote = f"{REMOTE_DIR}/{remote_rel or local_rel}"
    rdir   = "/".join(remote.split("/")[:-1])
    try:
        sftp.stat(rdir)
    except FileNotFoundError:
        run(f"mkdir -p {rdir}")
    sftp.put(local, remote)
    sys.stdout.buffer.write(f"  OK  {local_rel}\n".encode("utf-8", "replace"))
    sys.stdout.flush()

# ══════════════════════════════════════════════════════════════════════
# 1. Upload tutti i file aggiornati
# ══════════════════════════════════════════════════════════════════════
print("=" * 60)
print("STEP 1 — Upload file aggiornati")
print("=" * 60)

files_to_upload = [
    # Core
    "main.py",
    "manage.py",
    "plugin_loader.py",
    ".gitignore",
    "wsgi.py",
    # Web UI
    "interface/web_ui.py",
    # Plugins — base
    "plugins/__init__.py",
    "plugins/base.py",
    # Plugin: feature_requests
    "plugins/feature_requests/plugin.py",
    "plugins/feature_requests/manifest.json",
    # Plugin: whatsapp
    "plugins/whatsapp/plugin.py",
    "plugins/whatsapp/manifest.json",
    # Plugin: telegram_notifications
    "plugins/telegram_notifications/plugin.py",
    "plugins/telegram_notifications/manifest.json",
    # Plugin: backup
    "plugins/backup/plugin.py",
    "plugins/backup/manifest.json",
    # Plugin: voice_telegram
    "plugins/voice_telegram/plugin.py",
    "plugins/voice_telegram/manifest.json",
    # Hub
    "hub/__init__.py",
    "hub/hub_manager.py",
    "hub/clients.json",
    # Scripts
    "scripts/setup_client.sh",
    "scripts/setup_https.sh",
    "scripts/nginx_workmind.conf",
    "scripts/gunicorn_conf.py",
]

for f in files_to_upload:
    local_path = os.path.join(LOCAL_BASE, f.replace("/", os.sep))
    if os.path.exists(local_path):
        upload(f)
    else:
        print(f"  SKIP (non trovato): {f}")

# ══════════════════════════════════════════════════════════════════════
# 2. Crea data/plugins_enabled.json su Bender
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("STEP 2 — Crea plugins_enabled.json")
print("=" * 60)

plugins_enabled = {
    "plugins": [
        {"id": "feature_requests",       "version": "1.0.0", "enabled": True},
        {"id": "voice_telegram",         "version": "1.0.0", "enabled": True},
        {"id": "whatsapp",               "version": "1.0.0", "enabled": True},
        {"id": "telegram_notifications", "version": "1.0.0", "enabled": True},
        {"id": "backup",                 "version": "1.0.0", "enabled": True},
    ]
}

run(f"mkdir -p {REMOTE_DIR}/data")
json_content = json.dumps(plugins_enabled, indent=2, ensure_ascii=False)
# Write via heredoc
escaped = json_content.replace("'", "'\\''")
run(f"echo '{escaped}' > {REMOTE_DIR}/data/plugins_enabled.json")
print("  OK  data/plugins_enabled.json creato")

# Verifica
out, _ = run(f"cat {REMOTE_DIR}/data/plugins_enabled.json")
print(f"  Contenuto: {out[:80]}...")

# ══════════════════════════════════════════════════════════════════════
# 3. Installa Nginx + Gunicorn + HTTPS
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("STEP 3 — Installa Nginx + Gunicorn + HTTPS")
print("=" * 60)

# Verifica se nginx e' gia' installato
out, _ = run("which nginx 2>/dev/null || echo MISSING")
nginx_installed = "MISSING" not in out

if nginx_installed:
    print("  Nginx gia' installato")
else:
    print("  Installando nginx...")
    run("echo '195183_crea' | sudo -S apt-get install -y nginx > /dev/null 2>&1", timeout=120)
    print("  OK  nginx installato")

# Verifica/genera certificato SSL
out, _ = run("test -f /etc/ssl/workmind/workmind.crt && echo EXISTS || echo MISSING")
if "EXISTS" in out:
    print("  Certificato SSL gia' presente")
else:
    print("  Generando certificato SSL self-signed...")
    run("echo '195183_crea' | sudo -S mkdir -p /etc/ssl/workmind")
    run(
        "echo '195183_crea' | sudo -S openssl req -x509 -nodes -days 730 "
        "-newkey rsa:2048 "
        "-keyout /etc/ssl/workmind/workmind.key "
        "-out /etc/ssl/workmind/workmind.crt "
        "-subj '/C=IT/ST=Italy/O=WorkMind/CN=workmind.local' 2>/dev/null"
    )
    run("echo '195183_crea' | sudo -S chmod 600 /etc/ssl/workmind/workmind.key")
    print("  OK  certificato SSL creato (730 giorni)")

# Configura nginx
print("  Configurando nginx...")
run(
    f"echo '195183_crea' | sudo -S cp "
    f"{REMOTE_DIR}/scripts/nginx_workmind.conf "
    f"/etc/nginx/sites-available/workmind"
)
run(
    "echo '195183_crea' | sudo -S ln -sf "
    "/etc/nginx/sites-available/workmind "
    "/etc/nginx/sites-enabled/workmind"
)
run("echo '195183_crea' | sudo -S rm -f /etc/nginx/sites-enabled/default")

# Testa config nginx
out, err = run("echo '195183_crea' | sudo -S nginx -t 2>&1")
if "successful" in out.lower() or "successful" in err.lower() or "ok" in out.lower():
    print("  OK  nginx config valida")
else:
    print(f"  WARN config nginx: {out[:100]}")

# Installa gunicorn nel venv
print("  Installando gunicorn...")
run(f"{REMOTE_DIR}/venv/bin/pip install gunicorn --quiet", timeout=60)
print("  OK  gunicorn installato")

# ── Aggiorna systemd service ──────────────────────────────────────────
print("  Aggiornando servizio systemd...")
service_content = f"""[Unit]
Description=WorkMind Operational Assistant
After=network.target redis-server.service
Wants=redis-server.service

[Service]
Type=simple
User=emanuele
Group=emanuele
WorkingDirectory={REMOTE_DIR}
EnvironmentFile={REMOTE_DIR}/.env
ExecStart={REMOTE_DIR}/venv/bin/python main.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""
run(
    f"echo '195183_crea' | sudo -S tee /etc/systemd/system/workmind.service > /dev/null << 'EOSVC'\n"
    f"{service_content}\nEOSVC"
)
run("echo '195183_crea' | sudo -S systemctl daemon-reload")
run("echo '195183_crea' | sudo -S systemctl enable workmind nginx")
print("  OK  systemd configurato")

# ══════════════════════════════════════════════════════════════════════
# 4. Setup SSH key Hub (Windows) → Bender
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("STEP 4 — Setup SSH key Hub → Bender")
print("=" * 60)

# Genera chiave SSH sul Windows se non esiste
ssh_key_path = os.path.expanduser("~/.ssh/workmind_hub")
ssh_pub_path = ssh_key_path + ".pub"

if not os.path.exists(ssh_key_path):
    print("  Generando coppia SSH key (Ed25519)...")
    import subprocess
    result = subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-f", ssh_key_path, "-N", "",
         "-C", "workmind-hub@windows"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"  OK  SSH key generata: {ssh_key_path}")
    else:
        print(f"  ERR generazione key: {result.stderr}")
else:
    print(f"  SSH key gia' presente: {ssh_key_path}")

# Leggi la chiave pubblica
if os.path.exists(ssh_pub_path):
    with open(ssh_pub_path, "r") as f:
        pub_key = f.read().strip()
    print(f"  Pub key: {pub_key[:60]}...")

    # Aggiungi a authorized_keys su Bender
    run(f"mkdir -p /home/{BENDER_USER}/.ssh && chmod 700 /home/{BENDER_USER}/.ssh")
    # Verifica se gia' presente
    out, _ = run(f"grep -F '{pub_key[:40]}' /home/{BENDER_USER}/.ssh/authorized_keys 2>/dev/null || echo MISSING")
    if "MISSING" in out:
        run(f"echo '{pub_key}' >> /home/{BENDER_USER}/.ssh/authorized_keys")
        run(f"chmod 600 /home/{BENDER_USER}/.ssh/authorized_keys")
        print("  OK  Chiave pubblica aggiunta a Bender authorized_keys")
    else:
        print("  Chiave pubblica gia' presente in authorized_keys")

    # Verifica connessione passwordless
    print("  Verificando connessione SSH passwordless...")
    ssh2 = paramiko.SSHClient()
    ssh2.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh2.connect(BENDER_HOST, username=BENDER_USER, key_filename=ssh_key_path, timeout=10)
        _, out2, _ = ssh2.exec_command("echo SSH_OK")
        result2 = out2.read().decode().strip()
        if "SSH_OK" in result2:
            print("  OK  Connessione SSH senza password funzionante!")
        ssh2.close()
    except Exception as e:
        print(f"  WARN connessione passwordless: {e}")
else:
    print("  WARN: impossibile trovare chiave pubblica SSH")

# ══════════════════════════════════════════════════════════════════════
# 5. Riavvia tutti i servizi
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("STEP 5 — Riavvio servizi")
print("=" * 60)

print("  Riavviando WorkMind...")
run("echo '195183_crea' | sudo -S systemctl restart workmind 2>&1", timeout=30)
time.sleep(6)

out, _ = run("echo '195183_crea' | sudo -S systemctl is-active workmind 2>&1")
status_wm = out.strip()
print(f"  WorkMind: {status_wm}")

print("  Riavviando Nginx...")
run("echo '195183_crea' | sudo -S systemctl restart nginx 2>&1", timeout=20)
time.sleep(2)

out, _ = run("echo '195183_crea' | sudo -S systemctl is-active nginx 2>&1")
status_ng = out.strip()
print(f"  Nginx:    {status_ng}")

# Health check
print("\n  Health check...")
time.sleep(3)
out, _ = run("curl -sk -o /dev/null -w '%{http_code}' https://localhost/login 2>&1")
http_code = out.strip()
print(f"  HTTPS /login → HTTP {http_code}")

out, _ = run("curl -s -o /dev/null -w '%{http_code}' http://localhost/login 2>&1")
http_redir = out.strip()
print(f"  HTTP  /login → HTTP {http_redir} (atteso 301)")

# ══════════════════════════════════════════════════════════════════════
# RIEPILOGO
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("DEPLOY FINALE COMPLETATO")
print("=" * 60)
print(f"  WorkMind:     {'OK' if status_wm == 'active' else status_wm}")
print(f"  Nginx:        {'OK' if status_ng == 'active' else status_ng}")
print(f"  HTTPS:        https://100.116.199.50 (cert self-signed)")
print(f"  SSH key:      {ssh_key_path}")
print(f"  Plugins:      {REMOTE_DIR}/data/plugins_enabled.json")
print(f"  Admin UI:     https://100.116.199.50/login")
print(f"  Hub CLI:      python hub/hub_manager.py status")
print("=" * 60)

sftp.close()
ssh.close()
