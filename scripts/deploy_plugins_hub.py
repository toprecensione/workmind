#!/usr/bin/env python3
"""Deploy plugin loader + hub system to Bender."""
import paramiko, os, sys

REMOTE_DIR = "/home/emanuele/workmind"
LOCAL_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('Bender', username='emanuele', password='195183_crea', timeout=10)
sftp = ssh.open_sftp()

def run(cmd, t=180):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=t)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    for line in out.strip().split('\n'):
        if line: sys.stdout.buffer.write((line+'\n').encode('utf-8','replace'))
    if err.strip():
        for line in err.strip().split('\n')[-3:]:
            if line and 'WARNING' not in line:
                sys.stdout.buffer.write(('ERR: '+line+'\n').encode('utf-8','replace'))
    return out.strip(), err.strip()

def upload(local_rel, remote_rel=None):
    local = os.path.join(LOCAL_BASE, local_rel.replace('/', os.sep))
    remote = f"{REMOTE_DIR}/{remote_rel or local_rel}"
    rdir = '/'.join(remote.split('/')[:-1])
    try: sftp.stat(rdir)
    except FileNotFoundError: run(f"mkdir -p {rdir}")
    sftp.put(local, remote)
    print(f"  OK: {local_rel}")

print("=== Uploading Plugin Loader + Hub ===")
files = [
    "plugin_loader.py",
    "plugins/__init__.py",
    "plugins/base.py",
    "hub/__init__.py",
    "hub/hub_manager.py",
    "hub/clients.json",
    "scripts/setup_client.sh",
    "main.py",
    "interface/web_ui.py",
]
for f in files: upload(f)

print("\n=== Restarting WorkMind ===")
run("echo '195183_crea' | sudo -S systemctl restart workmind 2>&1; sleep 8; echo '195183_crea' | sudo -S systemctl status workmind 2>&1 | head -20")

print("\n=== Health check ===")
import time; time.sleep(3)
run("curl -s -o /dev/null -w '%{http_code}' http://localhost:7860/login 2>&1")

sftp.close(); ssh.close()
print("\n=== DEPLOY COMPLETE ===")
print("Sistema multi-client attivo:")
print("  Tailscale: workmind-bender @ 100.116.199.50")
print("  Plugin loader: data/plugins_enabled.json")
print("  Hub: python hub/hub_manager.py status")
print("  Setup nuovo client: scripts/setup_client.sh")
