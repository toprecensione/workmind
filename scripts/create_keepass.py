#!/usr/bin/env python3
"""
WorkMind — Creazione database KeePass
Genera workmind_credentials.kdbx con tutte le credenziali del progetto,
organizzate per cartelle. Compatibile con KeePass 2.x (v4 format).

Eseguire da Windows: python scripts/create_keepass.py
Dipendenza: pip install pykeepass
"""
import sys
import os
from pathlib import Path

# ── Dipendenza ────────────────────────────────────────────────────────
try:
    from pykeepass import PyKeePass, create_database
    from pykeepass.group import Group
except ImportError:
    print("Installo pykeepass...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pykeepass"])
    from pykeepass import PyKeePass, create_database

# ── Percorso output ───────────────────────────────────────────────────
SCRIPT_DIR  = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
OUTPUT_PATH = PROJECT_DIR / "workmind_credentials.kdbx"
MASTER_PW   = "WorkMind2026!"   # Stessa pw admin — da cambiare dopo!

# ── Crea database ─────────────────────────────────────────────────────
print(f"[*] Creazione database: {OUTPUT_PATH}")
kp = create_database(str(OUTPUT_PATH), password=MASTER_PW)

def folder(name, parent=None):
    """Crea o recupera un gruppo."""
    parent = parent or kp.root_group
    grp = kp.find_groups(name=name, first=True)
    if grp is None:
        grp = kp.add_group(parent, name)
    return grp

def entry(group, title, username, password, url="", notes=""):
    """Aggiunge una voce al gruppo specificato."""
    kp.add_entry(group, title, username, password, url=url, notes=notes)

# ══════════════════════════════════════════════════════════════════════
# STRUTTURA CARTELLE
# ══════════════════════════════════════════════════════════════════════

# ── Servers ───────────────────────────────────────────────────────────
g_servers = folder("Servers")

entry(
    g_servers,
    title    = "Bender — SSH (LAN)",
    username = "emanuele",
    password = "195183_crea",
    url      = "ssh://192.168.0.141:22",
    notes    = "PC Ubuntu locale\nTailscale IP: 100.116.199.50\nOS: Ubuntu 22.04"
)
entry(
    g_servers,
    title    = "Bender — SSH (Tailscale)",
    username = "emanuele",
    password = "195183_crea",
    url      = "ssh://100.116.199.50:22",
    notes    = "Accesso remoto via Tailscale VPN\nAccount Tailscale: toprecensione@gmail.com"
)
entry(
    g_servers,
    title    = "Bender — sudo",
    username = "emanuele",
    password = "195183_crea",
    url      = "",
    notes    = "Password sudo = password utente"
)
entry(
    g_servers,
    title    = "Bender — WorkMind UI (HTTPS)",
    username = "toprecensione@gmail.com",
    password = "WorkMind2026!",
    url      = "https://100.116.199.50/login",
    notes    = "Interfaccia web WorkMind\nCertificato SSL self-signed (730 giorni)\nPorta interna Flask: 7860"
)

# ── WorkMind Application ──────────────────────────────────────────────
g_app = folder("WorkMind App")

entry(
    g_app,
    title    = "WorkMind — Admin",
    username = "toprecensione@gmail.com",
    password = "WorkMind2026!",
    url      = "https://100.116.199.50/login",
    notes    = "Ruolo: admin\nCreato automaticamente al primo avvio\nCambia password dopo il primo accesso!"
)
entry(
    g_app,
    title    = "WorkMind — Flask Secret Key",
    username = "WORKMIND_SECRET_KEY",
    password = "** da .env su Bender **",
    url      = "",
    notes    = f"Variabile d'ambiente in: /home/emanuele/workmind/.env\n"
               f"Generare con: python -c \"import secrets; print(secrets.token_hex(32))\""
)

# ── Email / SMTP ──────────────────────────────────────────────────────
g_email = folder("Email & SMTP")

entry(
    g_email,
    title    = "SMTP Aruba — smtp@faberweb.it",
    username = "smtp@faberweb.it",
    password = "sm2013tp",
    url      = "smtpa.aruba.it",
    notes    = "Host: smtpa.aruba.it\nPorta: 465 (SSL)\nProtocollo: SMTP_SSL\n"
               "Usato per: reset password, inviti utenti"
)
entry(
    g_email,
    title    = "Gmail — toprecensione@gmail.com",
    username = "toprecensione@gmail.com",
    password = "** vedi Google Account **",
    url      = "https://mail.google.com",
    notes    = "Account principale amministratore\nUsato anche per Tailscale e GitHub"
)

# ── Telegram ─────────────────────────────────────────────────────────
g_telegram = folder("Telegram")

entry(
    g_telegram,
    title    = "Telegram Bot Token",
    username = "WorkMindBot",
    password = "8349603082:AAH_-ks3h8xLPCu41T1-BXJGZU2w8Pde0_k",
    url      = "https://t.me/WorkMindBot",
    notes    = "Bot token da @BotFather\nUsato da: interface/telegram_bot.py\n"
               "Variabile env: TELEGRAM_BOT_TOKEN"
)

# ── WhatsApp ─────────────────────────────────────────────────────────
g_whatsapp = folder("WhatsApp Business")

entry(
    g_whatsapp,
    title    = "WhatsApp Business — API Token",
    username = "META_WHATSAPP_TOKEN",
    password = "** inserire token Meta Business Manager **",
    url      = "https://developers.facebook.com/apps/",
    notes    = "Da configurare nel .env su Bender:\n"
               "META_WHATSAPP_TOKEN=<token>\n"
               "META_PHONE_NUMBER_ID=<phone_id>\n"
               "META_WEBHOOK_SECRET=<segreto_verifica>"
)
entry(
    g_whatsapp,
    title    = "WhatsApp Business — Phone Number ID",
    username = "META_PHONE_NUMBER_ID",
    password = "** inserire Phone Number ID **",
    url      = "https://developers.facebook.com/apps/",
    notes    = "Trovare in Meta Business Manager > WhatsApp > Configurazione"
)
entry(
    g_whatsapp,
    title    = "WhatsApp Business — Webhook Secret",
    username = "META_WEBHOOK_SECRET",
    password = "** scegliere stringa segreta casuale **",
    url      = "",
    notes    = "Stringa usata per verificare le chiamate webhook Meta\n"
               "URL webhook: https://100.116.199.50/webhook/whatsapp"
)

# ── GitHub ────────────────────────────────────────────────────────────
g_github = folder("GitHub")

entry(
    g_github,
    title    = "GitHub — toprecensione",
    username = "toprecensione",
    password = "** token dal credential manager Windows **",
    url      = "https://github.com/toprecensione/workmind",
    notes    = "Account GitHub del progetto\nToken recuperabile con:\n"
               "  git credential fill < nul  (poi inserire host=github.com)\n"
               "Repository privato: toprecensione/workmind"
)
entry(
    g_github,
    title    = "GitHub — Remote URL con token",
    username = "x-access-token",
    password = "** token GitHub **",
    url      = "https://github.com/toprecensione/workmind.git",
    notes    = "Formato URL con token:\n"
               "https://x-access-token:<TOKEN>@github.com/toprecensione/workmind.git\n"
               "Usato per git push/pull su Bender senza interazione"
)

# ── Tailscale ─────────────────────────────────────────────────────────
g_tailscale = folder("Tailscale VPN")

entry(
    g_tailscale,
    title    = "Tailscale — Account",
    username = "toprecensione@gmail.com",
    password = "** vedi Google Account **",
    url      = "https://login.tailscale.com",
    notes    = "Account Tailscale (login con Google)\nRete: toprecensione@gmail.com's network"
)
entry(
    g_tailscale,
    title    = "Tailscale — Bender",
    username = "workmind-bender",
    password = "",
    url      = "https://login.tailscale.com/admin/machines",
    notes    = "Hostname Tailscale: workmind-bender\nIP Tailscale: 100.116.199.50\nIP LAN: 192.168.0.141"
)
entry(
    g_tailscale,
    title    = "Tailscale — Windows Dev (ema)",
    username = "ema",
    password = "",
    url      = "https://login.tailscale.com/admin/machines",
    notes    = "Hostname Tailscale: ema (o analogo)\nIP Tailscale: 100.119.210.88\nMacchina Hub per hub_manager.py"
)

# ── SSH Keys ─────────────────────────────────────────────────────────
g_sshkeys = folder("SSH Keys")

entry(
    g_sshkeys,
    title    = "SSH Key Hub→Bender (Ed25519)",
    username = "emanuele",
    password = "",
    url      = "",
    notes    = "Chiave privata: %USERPROFILE%\\.ssh\\workmind_hub\n"
               "Chiave pubblica: %USERPROFILE%\\.ssh\\workmind_hub.pub\n"
               "Installata in: /home/emanuele/.ssh/authorized_keys (Bender)\n"
               "Usata da: hub/hub_manager.py per connessione passwordless"
)

# ── AI Services ──────────────────────────────────────────────────────
g_ai = folder("AI Services")

entry(
    g_ai,
    title    = "Anthropic API (Claude)",
    username = "ANTHROPIC_API_KEY",
    password = "** da inserire nel .env **",
    url      = "https://console.anthropic.com",
    notes    = "Variabile env: ANTHROPIC_API_KEY\nUsata da: ai_client/client.py"
)
entry(
    g_ai,
    title    = "OpenAI API (se usata)",
    username = "OPENAI_API_KEY",
    password = "** da inserire nel .env se necessario **",
    url      = "https://platform.openai.com",
    notes    = "Opzionale — solo se si usa GPT come fallback\nVariabile env: OPENAI_API_KEY"
)
entry(
    g_ai,
    title    = "Mem0 — Storage locale",
    username = "MEM0_LOCAL",
    password = "** nessuna credenziale (locale) **",
    url      = "",
    notes    = "Mem0 gira in locale su Bender\nDati in: /home/emanuele/workmind/data/\n"
               "Nessuna API key necessaria per uso locale"
)

# ── Redis ─────────────────────────────────────────────────────────────
g_redis = folder("Database & Cache")

entry(
    g_redis,
    title    = "Redis — Bender (locale)",
    username = "redis",
    password = "",
    url      = "redis://127.0.0.1:6379",
    notes    = "Nessuna password impostata (accesso solo da localhost)\n"
               "Usato da: storage/redis_store.py\n"
               "Porta: 6379"
)

# ── Client Futuri ─────────────────────────────────────────────────────
g_clients = folder("Client WorkMind")

entry(
    g_clients,
    title    = "Client 2 — [Da configurare]",
    username = "",
    password = "",
    url      = "",
    notes    = "Inserire quando verrà configurato il secondo client:\n"
               "- Tailscale IP\n- SSH user/password\n- WorkMind dir\n- Nome azienda"
)
entry(
    g_clients,
    title    = "Client 3 — [Da configurare]",
    username = "",
    password = "",
    url      = "",
    notes    = "Placeholder per client futuro"
)
entry(
    g_clients,
    title    = "Client 4 — [Da configurare]",
    username = "",
    password = "",
    url      = "",
    notes    = "Placeholder per client futuro"
)
entry(
    g_clients,
    title    = "Client 5 — [Da configurare]",
    username = "",
    password = "",
    url      = "",
    notes    = "Placeholder per client futuro"
)

# ── Salva ─────────────────────────────────────────────────────────────
kp.save()
print(f"\n[+] Database KeePass creato con successo!")
print(f"    File:          {OUTPUT_PATH}")
print(f"    Master PW:     {MASTER_PW}")
print(f"    Voci totali:   {len(kp.entries)}")
print(f"\n[!] IMPORTANTE: Cambia la master password dopo il primo accesso!")
print(f"    Apri con KeePass 2.x o KeePassXC\n")

# Stampa link locale per aprire direttamente
abs_path = str(OUTPUT_PATH.resolve()).replace("\\", "/")
print(f"    Link locale:   file:///{abs_path}")

# Prova ad aprire con KeePass/KeePassXC (Windows)
import subprocess, shutil
for app in ["KeePass", "KeePassXC"]:
    path = shutil.which(app)
    if path:
        print(f"\n[*] Apertura con {app}...")
        subprocess.Popen([path, str(OUTPUT_PATH)])
        break
else:
    # Prova percorsi comuni di KeePass su Windows
    common_paths = [
        r"C:\Program Files\KeePass Password Safe 2\KeePass.exe",
        r"C:\Program Files (x86)\KeePass Password Safe 2\KeePass.exe",
        r"C:\Program Files\KeePassXC\KeePassXC.exe",
        r"C:\Users\emanuele\AppData\Local\KeePassXC\KeePassXC.exe",
    ]
    opened = False
    for p in common_paths:
        if os.path.exists(p):
            print(f"\n[*] Apertura con KeePass: {p}")
            subprocess.Popen([p, str(OUTPUT_PATH)])
            opened = True
            break
    if not opened:
        print("\n[*] KeePass non trovato automaticamente.")
        print(f"    Apri manualmente: {OUTPUT_PATH}")
