#!/usr/bin/env python3
"""Deploy helper for Bender - run from Windows."""
import paramiko
import sys

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('Bender', username='emanuele', password='195183_crea', timeout=10)

def run(cmd, timeout=30):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    for line in out.split('\n'):
        sys.stdout.buffer.write((line + '\n').encode('utf-8', errors='replace'))
    if err.strip():
        for line in err.split('\n')[-5:]:
            sys.stdout.buffer.write(('STDERR: ' + line + '\n').encode('utf-8', errors='replace'))

# 1. Write .env
print("=== Writing .env ===")
run("""cat > /home/emanuele/workmind/.env << 'EOF'
WORKMIND_NODE_ID=node-bender-001
WORKMIND_NODE_LABEL=Bender - Nodo Principale
WORKMIND_ENV=production
WORKMIND_REPO_URL=https://github.com/toprecensione/workmind.git
WORKMIND_BRANCH=claude/competent-elion
GITHUB_TOKEN=
LOG_LEVEL=INFO
DEEPSEEK_API_KEY=
ANTHROPIC_API_KEY=
WORKMIND_DEEPSEEK_DAILY_LIMIT=5.00
WORKMIND_CLAUDE_DAILY_LIMIT=10.00
WORKMIND_DB_PASSWORD=
WORKMIND_EMAIL_SECRET=
WORKMIND_IMAP_PASSWORD=
WORKMIND_SMB_PASSWORD=
WORKMIND_RDP_PASSWORD=
WORKMIND_ENCRYPTION_KEY=WorkMind2026BenderSecureKey!!
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
EOF
chmod 600 /home/emanuele/workmind/.env
echo ENV_OK""")

# 2. Write company.yaml
print("=== Writing company.yaml ===")
run("""cat > /home/emanuele/workmind/config/company.yaml << 'EOF'
name: "WorkMind Dev"
sector: "sviluppo"
language: "it"
timezone: "Europe/Rome"
supervisor_email: ""
report_time_daily: "22:00"
report_day_weekly: "friday"
local_watch_dirs:
  - "/home/emanuele/workmind/data"
database:
  enabled: false
email:
  enabled: false
smb:
  enabled: false
rdp:
  enabled: false
custom_entities: []
document_types:
  - "fattura"
  - "ordine"
  - "contratto"
  - "DDT"
  - "offerta"
  - "email"
  - "altro"
EOF
echo COMPANY_OK""")

# 3. Create systemd service
print("=== Creating systemd service ===")
run("""echo '195183_crea' | sudo -S bash -c 'cat > /etc/systemd/system/workmind.service << UNIT
[Unit]
Description=WorkMind Operational Assistant
After=network.target redis-server.service
Wants=redis-server.service

[Service]
Type=simple
User=emanuele
Group=emanuele
WorkingDirectory=/home/emanuele/workmind
EnvironmentFile=/home/emanuele/workmind/.env
ExecStart=/home/emanuele/workmind/venv/bin/python main.py
Restart=on-failure
RestartSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable workmind.service'
echo SYSTEMD_OK""")

# 4. Start WorkMind
print("=== Starting WorkMind ===")
run("echo '195183_crea' | sudo -S systemctl start workmind 2>&1; sleep 3; echo '195183_crea' | sudo -S systemctl status workmind 2>&1 | head -15")

ssh.close()
print("\n=== DEPLOY COMPLETE ===")
