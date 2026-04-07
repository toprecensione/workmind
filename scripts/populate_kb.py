#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkMind — Popolamento Knowledge Base
Aggiunge i fatti aziendali fondamentali alla KB su Bender
per eliminare le allucinazioni su contatti/dati ufficiali.

Eseguire: python scripts/populate_kb.py
Modifica i valori AZIENDA_* prima di eseguire.
"""
import sys, os, json, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import paramiko
from datetime import datetime, timezone

BENDER_HOST = "100.116.199.50"
BENDER_USER = "emanuele"
BENDER_KEY  = os.path.expanduser("~/.ssh/workmind_hub")
REMOTE_DIR  = "/home/emanuele/workmind"

# ══════════════════════════════════════════════════════════════════════
# PERSONALIZZA QUESTI DATI con quelli reali dell'azienda
# ══════════════════════════════════════════════════════════════════════

AZIENDA_FATTI = [
    # -- Identita' aziendale --
    "WorkMind e' un sistema di gestione operativa AI sviluppato internamente.",
    "WorkMind NON ha un sito web pubblico. Non esiste workmind.dev.",
    "WorkMind NON ha un'email support@workmind.dev.",
    "Il progetto WorkMind e' gestito da Emanuele per uso aziendale privato.",

    # -- FaberWeb (la tua azienda, modifica se necessario) --
    # "Il nome dell'azienda e' FaberWeb.",
    # "Il sito web e': https://faberweb.it",
    # "L'email di contatto e': info@faberweb.it",
    # "Il numero di telefono e': +39 [INSERIRE]",
    # "L'indirizzo e': [INSERIRE VIA, CITTA', CAP]",
    # "La P.IVA e': [INSERIRE]",
    # "L'email PEC e': [INSERIRE]@pec.it",
    # "Il responsabile e': Emanuele",
    # "Gli orari di apertura sono: [INSERIRE]",
    # "Il settore di attivita' e': [INSERIRE]",

    # -- WorkMind tecnico --
    "WorkMind gira su Ubuntu (PC Bender) all'indirizzo IP locale 192.168.0.141.",
    "L'interfaccia web di WorkMind e' accessibile su https://100.116.199.50/login.",
    "L'account amministratore di WorkMind e' toprecensione@gmail.com.",
    "Il bot Telegram di WorkMind si chiama WorkMindBot.",
    "Per aggiungere informazioni alla knowledge base usa il comando /teach.",

    # -- Istruzioni per gli utenti --
    "Per informazioni di contatto aziendali, chiedere sempre all'amministratore.",
    "Non condividere dati sensibili di clienti via chat.",
]

AZIENDA_GLOSSARIO = {
    "KB": "Knowledge Base — il database di fatti aziendali di WorkMind",
    "WorkMind": "Sistema AI operativo interno per gestione aziendale",
    "Bender": "Il server Ubuntu su cui gira WorkMind",
    "Haiku": "Modello Claude economico usato per risposte affidabili",
    "Sonnet": "Modello Claude avanzato usato per analisi complesse",
    "DeepSeek": "Modello AI economico usato per classificazioni interne",
    "HallucinationGuard": "Sistema di validazione che blocca risposte inventate",
}

AZIENDA_PROCESSI = [
    {
        "name": "Aggiunta contatti aziendali",
        "description": "Come aggiungere dati di contatto reali alla KB per evitare allucinazioni",
        "steps": [
            "Aprire la chat WorkMind o Telegram",
            "Usare il comando: /teach <dato reale>",
            "Esempio: /teach Email: info@miazienda.it",
            "Esempio: /teach Telefono: +39 02 1234567",
            "Verificare con /kb list",
        ]
    },
    {
        "name": "Risposta a domande sui contatti",
        "description": "WorkMind risponde con dati KB senza chiamare l'AI",
        "steps": [
            "L'utente chiede un contatto (email, telefono, sito)",
            "WorkMind cerca in KB con lookup_fact()",
            "Se trovato: risposta diretta dalla KB (zero costo AI)",
            "Se non trovato: risponde 'Non ho questa info, usa /teach'",
            "MAI inventare dati di contatto",
        ]
    },
]

# ══════════════════════════════════════════════════════════════════════

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def build_kb_patch():
    """Costruisce il JSON da appendere alla KB esistente."""
    facts = [{"text": t, "taught_at": now_iso(), "taught_by": "populate_kb.py"}
             for t in AZIENDA_FATTI]
    return {
        "new_facts": facts,
        "new_glossary": AZIENDA_GLOSSARIO,
        "new_processes": AZIENDA_PROCESSI,
    }

def main():
    print("[*] Connessione a Bender...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(BENDER_HOST, username=BENDER_USER,
                key_filename=BENDER_KEY, timeout=10)
    print("[+] Connesso\n")

    def run(cmd, timeout=30):
        _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        return out, err

    # Leggi KB attuale
    kb_path = f"{REMOTE_DIR}/data/knowledge_base.json"
    out, _ = run(f"cat {kb_path} 2>/dev/null || echo '{{}}'")
    try:
        kb = json.loads(out)
    except Exception:
        kb = {}

    # Struttura base
    kb.setdefault("facts", [])
    kb.setdefault("corrections", [])
    kb.setdefault("processes", [])
    kb.setdefault("glossary", {})

    # Aggiungi senza duplicati
    patch = build_kb_patch()
    existing_texts = {f["text"].lower() for f in kb["facts"]}

    added_facts = 0
    for fact in patch["new_facts"]:
        if fact["text"].lower() not in existing_texts:
            kb["facts"].append(fact)
            existing_texts.add(fact["text"].lower())
            added_facts += 1

    added_glossary = 0
    for term, defn in patch["new_glossary"].items():
        if term.lower() not in kb["glossary"]:
            kb["glossary"][term.lower()] = defn
            added_glossary += 1

    added_processes = 0
    existing_proc_names = {p["name"].lower() for p in kb["processes"]}
    for proc in patch["new_processes"]:
        if proc["name"].lower() not in existing_proc_names:
            kb["processes"].append({**proc, "taught_at": now_iso(), "taught_by": "populate_kb.py"})
            added_processes += 1

    # Scrivi KB aggiornata su Bender
    kb_json = json.dumps(kb, indent=2, ensure_ascii=False)
    # Usa python per scrivere file con caratteri UTF-8
    python_cmd = (
        f"python3 -c \""
        f"import json; "
        f"data = json.loads(open('{kb_path}').read() if __import__('os').path.exists('{kb_path}') else '{{}}'); "
        f"print(len(data.get('facts', [])))\""
    )
    # Scrivi tramite sftp
    sftp = ssh.open_sftp()
    # Crea directory se mancante
    try: sftp.stat(f"{REMOTE_DIR}/data")
    except FileNotFoundError: sftp.mkdir(f"{REMOTE_DIR}/data")

    import io
    kb_bytes = kb_json.encode("utf-8")
    with sftp.open(kb_path, "w") as f:
        f.write(kb_bytes)
    sftp.close()

    print(f"[+] Knowledge Base aggiornata:")
    print(f"    Fatti aggiunti:    {added_facts}")
    print(f"    Glossario:         {added_glossary} termini")
    print(f"    Processi:          {added_processes}")
    print(f"    Totale fatti KB:   {len(kb['facts'])}")
    print(f"    Totale glossario:  {len(kb['glossary'])}")

    # Riavvia WorkMind per ricaricare KB
    print("\n[*] Riavvio WorkMind...")
    run("echo '195183_crea' | sudo -S systemctl restart workmind 2>&1", timeout=20)
    time.sleep(5)
    out, _ = run("echo '195183_crea' | sudo -S systemctl is-active workmind 2>&1")
    print(f"    WorkMind: {out.strip()}")

    ssh.close()
    print("\n[+] KB popolata. WorkMind non inventera' piu' dati di contatto.")
    print("\nProssimi passi:")
    print("  1. Apri la chat o Telegram e usa /teach per aggiungere dati reali:")
    print("     /teach Il sito e': https://tuaazienda.it")
    print("     /teach Email: info@tuaazienda.it")
    print("     /teach Telefono: +39 02 XXXXXXX")
    print("  2. Verifica con /kb list")
    print("  3. Testa: chiedi 'qual e' la vostra email?'")

if __name__ == "__main__":
    main()
