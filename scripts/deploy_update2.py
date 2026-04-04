#!/usr/bin/env python3
"""Deploy all new features to Bender and restart service."""
import paramiko
import os
import sys

REMOTE_DIR = "/home/emanuele/workmind"
LOCAL_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('Bender', username='emanuele', password='195183_crea', timeout=10)
sftp = ssh.open_sftp()

def run(cmd, timeout=60):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    for line in out.strip().split('\n'):
        if line:
            sys.stdout.buffer.write((line + '\n').encode('utf-8', errors='replace'))
    if err.strip():
        for line in err.strip().split('\n')[-5:]:
            if line and 'WARNING' not in line:
                sys.stdout.buffer.write(('STDERR: ' + line + '\n').encode('utf-8', errors='replace'))

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

# 1. Upload all updated/new files
print("=== Uploading files ===")
files = [
    "main.py",
    "wsgi.py",
    "interface/web_ui.py",
    "interface/telegram_bot.py",
    "interface/telegram_notifications.py",
    "storage/vector_store.py",
    "storage/backup.py",
    "scripts/gunicorn_conf.py",
    "scripts/nginx_workmind.conf",
    "scripts/setup_https.sh",
]
for f in files:
    upload(f)

# 2. Install new Python packages
print("\n=== Installing new packages ===")
run(f"{REMOTE_DIR}/venv/bin/pip install SpeechRecognition pydub chromadb 2>&1 | tail -5", timeout=120)

# 3. Install ffmpeg for voice transcription
print("\n=== Checking ffmpeg ===")
run("which ffmpeg || (echo '195183_crea' | sudo -S apt-get install -y -qq ffmpeg 2>&1 | tail -3)")

# 4. Restart service
print("\n=== Restarting WorkMind ===")
run("echo '195183_crea' | sudo -S systemctl restart workmind 2>&1; sleep 5; echo '195183_crea' | sudo -S systemctl status workmind 2>&1 | head -25")

# 5. Health check
print("\n=== Health check ===")
import time; time.sleep(3)
run("curl -s -o /dev/null -w '%{http_code}' http://localhost:7860/login 2>&1")

sftp.close()
ssh.close()
print("\n=== DEPLOY COMPLETE ===")
print("UI: http://192.168.0.141:7860 (login: admin / workmind)")
print("Telegram: vocali + notifiche attive")
print("RAG: ChromaDB indicizzazione abilitata")
print("Backup: automatico ogni 24h")
