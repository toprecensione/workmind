#!/usr/bin/env python3
"""Deploy feature request pipeline to Bender."""
import paramiko
import os
import sys

REMOTE_DIR = "/home/emanuele/workmind"
LOCAL_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('Bender', username='emanuele', password='195183_crea', timeout=10)
sftp = ssh.open_sftp()

def run(cmd, timeout=180):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    for line in out.strip().split('\n'):
        if line:
            sys.stdout.buffer.write((line + '\n').encode('utf-8', errors='replace'))
    if err.strip():
        for line in err.strip().split('\n')[-3:]:
            if line and 'WARNING' not in line:
                sys.stdout.buffer.write(('ERR: ' + line + '\n').encode('utf-8', errors='replace'))

def upload(local_rel):
    local = os.path.join(LOCAL_BASE, local_rel.replace('/', os.sep))
    remote = f"{REMOTE_DIR}/{local_rel}"
    remote_dir = '/'.join(remote.split('/')[:-1])
    try:
        sftp.stat(remote_dir)
    except FileNotFoundError:
        run(f"mkdir -p {remote_dir}")
    sftp.put(local, remote)
    print(f"  OK: {local_rel}")

print("=== Uploading Feature Request Pipeline ===")
files = [
    "mindwork/feature_requests.py",
    "interface/web_ui.py",
    "interface/telegram_bot.py",
]
for f in files:
    upload(f)

print("\n=== Restarting WorkMind ===")
run("echo '195183_crea' | sudo -S systemctl restart workmind 2>&1; sleep 8; echo '195183_crea' | sudo -S systemctl status workmind 2>&1 | head -25")

print("\n=== Health check ===")
import time; time.sleep(3)
run("curl -s -o /dev/null -w '%{http_code}' http://localhost:7860/login 2>&1")

sftp.close()
ssh.close()
print("\n=== DEPLOY COMPLETE ===")
print("Feature Request Pipeline attivo:")
print("  - Classificazione AI (DeepSeek): AUTO/REVIEW/BLOCK")
print("  - Telegram: /request, /approve, /reject, /requests, /master")
print("  - Web UI: Pagina Richieste con submit/approve/reject")
print("  - GitHub Issues: creazione automatica per richieste REVIEW")
print("  - Auto-deploy webhook: /webhook/github")
