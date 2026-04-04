#!/usr/bin/env python3
"""Deploy updated files to Bender and restart service."""
import paramiko
import os
import sys

REMOTE_DIR = "/home/emanuele/workmind"
LOCAL_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('Bender', username='emanuele', password='195183_crea', timeout=10)
sftp = ssh.open_sftp()

def run(cmd, timeout=30):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    for line in out.strip().split('\n'):
        if line:
            sys.stdout.buffer.write((line + '\n').encode('utf-8', errors='replace'))
    if err.strip():
        for line in err.strip().split('\n')[-5:]:
            if line:
                sys.stdout.buffer.write(('STDERR: ' + line + '\n').encode('utf-8', errors='replace'))

def upload(local_rel):
    local = os.path.join(LOCAL_BASE, local_rel.replace('/', os.sep))
    remote = f"{REMOTE_DIR}/{local_rel}"
    # Ensure remote dir exists
    remote_dir = '/'.join(remote.split('/')[:-1])
    try:
        sftp.stat(remote_dir)
    except FileNotFoundError:
        run(f"mkdir -p {remote_dir}")
    sftp.put(local, remote)
    print(f"  Uploaded: {local_rel}")

# 1. Upload updated files
print("=== Uploading updated files ===")
files_to_upload = [
    "main.py",
    "interface/web_ui.py",
    "interface/telegram_bot.py",
    "interface/chat_server.py",
]
for f in files_to_upload:
    upload(f)

# 2. Update .env with API keys
print("\n=== Updating .env ===")
run(r"""
cd /home/emanuele/workmind
# Add DEEPSEEK_API_KEY if empty
sed -i 's/^DEEPSEEK_API_KEY=$/DEEPSEEK_API_KEY=sk-77878ed0a77f480aa296b667d2293067/' .env
# Add TELEGRAM_BOT_TOKEN if not present
if ! grep -q TELEGRAM_BOT_TOKEN .env; then
    echo 'TELEGRAM_BOT_TOKEN=8349603082:AAH_-ks3h8xLPCu41T1-BXJGZU2w8Pde0_k' >> .env
fi
# Show relevant keys (masked)
grep -E 'DEEPSEEK_API_KEY|TELEGRAM_BOT_TOKEN' .env | sed 's/=.*/=***/'
echo ENV_UPDATED
""")

# 3. Install Flask if needed
print("\n=== Checking Flask ===")
run("/home/emanuele/workmind/venv/bin/pip install flask httpx 2>&1 | tail -3")

# 4. Restart service
print("\n=== Restarting WorkMind service ===")
run("echo '195183_crea' | sudo -S systemctl restart workmind 2>&1; sleep 4; echo '195183_crea' | sudo -S systemctl status workmind 2>&1 | head -20")

# 5. Create desktop shortcut
print("\n=== Creating desktop shortcut ===")
run("""
mkdir -p /home/emanuele/Desktop
cat > /home/emanuele/Desktop/WorkMind.desktop << 'DESKTOP'
[Desktop Entry]
Version=1.0
Type=Application
Name=WorkMind
Comment=WorkMind Operational Assistant
Exec=xdg-open http://localhost:7860
Icon=applications-internet
Terminal=false
Categories=Network;Application;
DESKTOP
chmod +x /home/emanuele/Desktop/WorkMind.desktop
# Also trust it for GNOME
gio set /home/emanuele/Desktop/WorkMind.desktop metadata::trusted true 2>/dev/null || true
echo DESKTOP_OK
""")

# 6. Quick health check
print("\n=== Health check ===")
import time
time.sleep(2)
run("curl -s -o /dev/null -w '%{http_code}' http://localhost:7860/ 2>&1 || echo 'UI not yet ready'")

sftp.close()
ssh.close()
print("\n=== DEPLOY COMPLETE ===")
print("UI: http://192.168.0.141:7860")
print("Telegram bot: attivo (cerca @WorkMind)")
