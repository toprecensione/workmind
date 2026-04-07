#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deploy Step 4+5: SSH key setup + riavvio servizi."""
import sys, os, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import paramiko

BENDER_HOST = "100.116.199.50"
BENDER_USER = "emanuele"
BENDER_PASS = "195183_crea"
REMOTE_DIR  = "/home/emanuele/workmind"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
print(f"[*] Connessione a Bender ({BENDER_HOST})...")
ssh.connect(BENDER_HOST, username=BENDER_USER, password=BENDER_PASS, timeout=15)
print("[+] Connesso\n")

def run(cmd, timeout=60):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    if out:
        for ln in out.split("\n")[-8:]:
            if ln: print(f"  {ln}")
    if err:
        for ln in err.split("\n")[-3:]:
            if ln and "WARNING" not in ln and "authenticate" not in ln.lower():
                print(f"  ERR: {ln}")
    return out, err

# ── Step 4: SSH key Hub -> Bender ────────────────────────────────────
print("=" * 55)
print("STEP 4 -- Setup SSH key Hub -> Bender")
print("=" * 55)

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
        print(f"  ERR generazione key: {result.stderr[:200]}")
else:
    print(f"  SSH key gia' presente: {ssh_key_path}")

if os.path.exists(ssh_pub_path):
    with open(ssh_pub_path, "r") as f:
        pub_key = f.read().strip()
    print(f"  Pub key: {pub_key[:60]}...")

    # Aggiungi a authorized_keys su Bender
    run(f"mkdir -p /home/{BENDER_USER}/.ssh && chmod 700 /home/{BENDER_USER}/.ssh")
    out, _ = run(f"grep -F '{pub_key[:50]}' /home/{BENDER_USER}/.ssh/authorized_keys 2>/dev/null || echo MISSING")
    if "MISSING" in out:
        escaped = pub_key.replace("'", "'\\''")
        run(f"echo '{escaped}' >> /home/{BENDER_USER}/.ssh/authorized_keys")
        run(f"chmod 600 /home/{BENDER_USER}/.ssh/authorized_keys")
        print("  OK  Chiave aggiunta a authorized_keys su Bender")
    else:
        print("  Chiave gia' presente in authorized_keys")

    # Verifica connessione passwordless
    print("  Verifica connessione SSH passwordless...")
    ssh2 = paramiko.SSHClient()
    ssh2.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh2.connect(BENDER_HOST, username=BENDER_USER,
                     key_filename=ssh_key_path, timeout=10)
        _, out2, _ = ssh2.exec_command("echo SSH_OK")
        res2 = out2.read().decode().strip()
        print("  OK  SSH senza password funzionante!" if "SSH_OK" in res2
              else f"  WARN: risposta inattesa: {res2}")
        ssh2.close()
    except Exception as e:
        print(f"  WARN: {e}")
else:
    print("  WARN: chiave pubblica non trovata")

# ── Step 5: Riavvio servizi e health check ───────────────────────────
print("\n" + "=" * 55)
print("STEP 5 -- Riavvio servizi")
print("=" * 55)

print("  Riavviando WorkMind...")
run("echo '195183_crea' | sudo -S systemctl restart workmind 2>&1", timeout=30)
time.sleep(7)

out, _ = run("echo '195183_crea' | sudo -S systemctl is-active workmind 2>&1")
status_wm = out.strip()
print(f"  WorkMind: {status_wm}")

if status_wm != "active":
    print("  [!] WorkMind non attivo, controllo log...")
    run("echo '195183_crea' | sudo -S journalctl -u workmind -n 15 --no-pager 2>&1")

print("  Riavviando Nginx...")
run("echo '195183_crea' | sudo -S systemctl restart nginx 2>&1", timeout=20)
time.sleep(2)

out, _ = run("echo '195183_crea' | sudo -S systemctl is-active nginx 2>&1")
status_ng = out.strip()
print(f"  Nginx: {status_ng}")

# Health check
print("\n  Health check HTTPS...")
time.sleep(3)
out, _ = run("curl -sk -o /dev/null -w '%{http_code}' https://localhost/login 2>&1")
print(f"  HTTPS https://localhost/login -> HTTP {out.strip()}")

out, _ = run("curl -s -o /dev/null -w '%{http_code}' http://localhost 2>&1")
print(f"  HTTP  http://localhost         -> HTTP {out.strip()} (atteso 301)")

# ── Riepilogo finale ─────────────────────────────────────────────────
print("\n" + "=" * 55)
print("DEPLOY COMPLETATO")
print("=" * 55)
print(f"  WorkMind:   {'OK' if status_wm=='active' else status_wm}")
print(f"  Nginx:      {'OK' if status_ng=='active' else status_ng}")
print(f"  HTTPS:      https://100.116.199.50/login")
print(f"  SSH key:    {ssh_key_path}")
print(f"  Plugins:    {REMOTE_DIR}/data/plugins_enabled.json")
print(f"  Hub CLI:    python hub/hub_manager.py status")
print("=" * 55)

ssh.close()
