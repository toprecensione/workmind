#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deploy fix anti-allucinazione su Bender."""
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
print(f"[*] Connessione a Bender...")
ssh.connect(BENDER_HOST, username=BENDER_USER, key_filename=BENDER_KEY, timeout=10)
sftp = ssh.open_sftp()
print("[+] Connesso (SSH key, no password)\n")

def run(cmd, timeout=60):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    for ln in out.split("\n")[-5:]:
        if ln: print(f"  {ln}")
    return out, err

def upload(local_rel):
    local  = os.path.join(LOCAL_BASE, local_rel.replace("/", os.sep))
    remote = f"{REMOTE_DIR}/{local_rel}"
    rdir   = "/".join(remote.split("/")[:-1])
    try: sftp.stat(rdir)
    except FileNotFoundError: run(f"mkdir -p {rdir}")
    sftp.put(local, remote)
    print(f"  OK  {local_rel}")

print("=== Upload file aggiornati ===")
for f in [
    "interface/chat_server.py",
    "ai_client/client.py",
    "storage/knowledge_base.py",
]:
    upload(f)

print("\n=== Riavvio WorkMind ===")
run("echo '195183_crea' | sudo -S systemctl restart workmind 2>&1", timeout=30)
time.sleep(7)
out, _ = run("echo '195183_crea' | sudo -S systemctl is-active workmind 2>&1")
print(f"  WorkMind: {out.strip()}")

print("\n=== Health check ===")
time.sleep(3)
out, _ = run("curl -sk -o /dev/null -w '%{http_code}' https://localhost/login 2>&1")
print(f"  HTTPS /login -> HTTP {out.strip()}")

sftp.close(); ssh.close()
print("\n=== Deploy anti-allucinazione completato ===")
