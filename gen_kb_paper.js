const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
  ShadingType, VerticalAlign, PageNumber, LevelFormat,
} = require("docx");
const fs = require("fs");

// ── Colors ────────────────────────────────────────────────────────────────────
const NAVY    = "1B3A6B";
const BLUE    = "2E5FA3";
const ACCENT  = "2E75B6";
const TEAL    = "1A6B5A";
const ORANGE  = "C45C0A";
const GREY    = "555555";
const LGREY   = "F2F4F7";
const MGREY   = "E8EBF0";
const WHITE   = "FFFFFF";
const CALLOUT_BLUE = "EBF3FB";
const CALLOUT_GREEN = "E8F5EF";
const CALLOUT_ORANGE = "FEF3E8";
const CALLOUT_RED = "FDECEA";

const PAGE = { width: 11906, height: 16838 };
const MARGIN = 1418;
const CONTENT_W = PAGE.width - MARGIN * 2;

// ── Typography helpers ────────────────────────────────────────────────────────
const thin = (color) => ({ style: BorderStyle.SINGLE, size: 4, color });
const none = () => ({ style: BorderStyle.NONE, size: 0, color: WHITE });

function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    children: [new TextRun({ text, font: "Calibri", size: 26, bold: true, color: NAVY })],
    spacing: { before: 400, after: 120 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: ACCENT, space: 4 } },
  });
}
function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    children: [new TextRun({ text, font: "Calibri", size: 22, bold: true, color: BLUE })],
    spacing: { before: 280, after: 80 },
  });
}
function h3(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_3,
    children: [new TextRun({ text, font: "Calibri", size: 20, bold: true, color: GREY })],
    spacing: { before: 180, after: 60 },
  });
}
function body(text) {
  return new Paragraph({
    children: [new TextRun({ text, font: "Calibri", size: 22, color: "222222" })],
    spacing: { before: 60, after: 60 },
  });
}
function bodyMixed(runs) {
  return new Paragraph({
    children: runs.map(r =>
      new TextRun({ font: "Calibri", size: 22, color: "222222", ...r })
    ),
    spacing: { before: 60, after: 60 },
  });
}
function bullet(text) {
  return new Paragraph({
    numbering: { reference: "bullets", level: 0 },
    children: [new TextRun({ text, font: "Calibri", size: 22, color: "222222" })],
    spacing: { before: 40, after: 40 },
  });
}
function bullet2(text) {
  return new Paragraph({
    numbering: { reference: "bullets2", level: 0 },
    children: [new TextRun({ text, font: "Calibri", size: 20, color: "444444" })],
    spacing: { before: 30, after: 30 },
  });
}
function spacer() {
  return new Paragraph({ children: [new TextRun({ text: "", size: 16 })], spacing: { before: 0, after: 0 } });
}
function labelLine(label, text) {
  return new Paragraph({
    children: [
      new TextRun({ text: label + " ", font: "Calibri", size: 22, bold: true, color: NAVY }),
      new TextRun({ text, font: "Calibri", size: 22, color: "222222" }),
    ],
    spacing: { before: 60, after: 60 },
  });
}
function codeLine(text) {
  return new Paragraph({
    children: [new TextRun({ text, font: "Courier New", size: 18, color: "333333" })],
    spacing: { before: 20, after: 20 },
    shading: { fill: "F5F5F5", type: ShadingType.CLEAR },
    indent: { left: 400 },
  });
}

// ── Callout box ───────────────────────────────────────────────────────────────
function callout(title, items, accentColor = ACCENT, bgColor = CALLOUT_BLUE) {
  const children = [
    new Paragraph({
      children: [new TextRun({ text: title, font: "Calibri", size: 20, bold: true, color: accentColor })],
      spacing: { before: 0, after: 80 },
    }),
    ...items.map(item =>
      typeof item === "string"
        ? new Paragraph({
            numbering: { reference: "bullets", level: 0 },
            children: [new TextRun({ text: item, font: "Calibri", size: 20, color: "222222" })],
            spacing: { before: 40, after: 40 },
          })
        : item
    ),
  ];
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [CONTENT_W],
    rows: [new TableRow({
      children: [new TableCell({
        width: { size: CONTENT_W, type: WidthType.DXA },
        borders: {
          top: none(), bottom: none(), right: none(),
          left: { style: BorderStyle.SINGLE, size: 20, color: accentColor },
        },
        shading: { fill: bgColor, type: ShadingType.CLEAR },
        margins: { top: 140, bottom: 140, left: 280, right: 160 },
        children,
      })],
    })],
  });
}

// ── Tables ────────────────────────────────────────────────────────────────────
const cellBorder = {
  top: thin("CCCCCC"), bottom: thin("CCCCCC"),
  left: thin("CCCCCC"), right: thin("CCCCCC"),
};
function hcell(text, w) {
  return new TableCell({
    width: { size: w, type: WidthType.DXA },
    borders: cellBorder,
    shading: { fill: NAVY, type: ShadingType.CLEAR },
    margins: { top: 80, bottom: 80, left: 140, right: 140 },
    verticalAlign: VerticalAlign.CENTER,
    children: [new Paragraph({
      children: [new TextRun({ text, font: "Calibri", size: 20, bold: true, color: WHITE })],
      spacing: { before: 0, after: 0 },
    })],
  });
}
function dcell(text, w, shade = false, bold = false, color = null) {
  return new TableCell({
    width: { size: w, type: WidthType.DXA },
    borders: cellBorder,
    shading: { fill: shade ? LGREY : WHITE, type: ShadingType.CLEAR },
    margins: { top: 80, bottom: 80, left: 140, right: 140 },
    verticalAlign: VerticalAlign.CENTER,
    children: [new Paragraph({
      children: [new TextRun({ text, font: "Calibri", size: 20, bold, color: color || "222222" })],
      spacing: { before: 0, after: 0 },
    })],
  });
}

function formatsTable() {
  const cols = [1600, 2800, 2400, 2270];
  const rows = [
    ["PDF", "pdfplumber + PyPDF2", "Testo + tabelle estratte", "Manuali, schede tecniche, contratti"],
    ["DOCX", "python-docx", "Testo + tabelle + metadati", "Procedure, specifiche, offerte"],
    ["XLSX / XLS", "openpyxl + xlrd", "Tutti i fogli + tabelle", "Listini, capitolati, dati"],
    ["CSV / TXT", "stdlib + chardet", "Testo con encoding auto", "Export gestionali, log"],
    ["EML / MSG", "email stdlib + extract_msg", "Corpo + allegati testo", "Email archiviate Outlook"],
    ["DXF / DWG", "ezdxf + dwg2dxf", "Testi, layer, blocchi", "Tavole AutoCAD, planimetrie"],
  ];
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: cols,
    rows: [
      new TableRow({ children: ["Formato","Libreria","Cosa estrae","Casi d'uso"].map((t,i) => hcell(t, cols[i])) }),
      ...rows.map((r, i) => new TableRow({
        children: r.map((c, j) => dcell(c, cols[j], i % 2 === 0, j === 0)),
      })),
    ],
  });
}

function v1v2Table() {
  const cols = [2800, 3100, 3170];
  const rows = [
    ["Storage KB", "JSON flat file su disco", "PostgreSQL (tabelle documents + document_chunks)"],
    ["Vector Search", "ChromaDB su disco (cosine)", "pgvector su PostgreSQL — stesso DB, zero infrastrutture extra"],
    ["Embeddings", "HuggingFace all-MiniLM (locale, CPU)", "OpenAI / DeepSeek / locale — configurabile per org"],
    ["SMB Watcher", "watchdog su mount CIFS (callback non connessa)", "FastAPI background task async + webhook on-change"],
    ["Document Parser", "Sincrono, cache Redis SHA256", "Async + cache PostgreSQL SHA256"],
    ["Memoria conversazionale", "Mem0 + Qdrant su disco", "Mem0 su PostgreSQL (memories table gia presente)"],
    ["Multi-tenancy", "Singolo tenant (company.yaml)", "Multi-org: ogni org ha la propria KB isolata"],
    ["Configurazione SMB", "YAML fisso su server", "Admin panel web: add/remove share per org"],
    ["Integrazione canali", "Hardcoded in main.py", "Connectors attivabili da admin panel"],
    ["Accesso KB da AI", "Inject in system prompt (keyword + RAG)", "Inject in system prompt — stesso pattern, piu robusto"],
  ];
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: cols,
    rows: [
      new TableRow({ children: ["Componente","v1 (attuale)","v2 (proposto)"].map((t,i) => hcell(t, cols[i])) }),
      ...rows.map((r, i) => new TableRow({
        children: r.map((c, j) => dcell(c, cols[j], i % 2 === 0, j === 0)),
      })),
    ],
  });
}

function phaseTable() {
  const cols = [1200, 2600, 3200, 2070];
  const rows = [
    ["Fase 1", "Document Parser async", "Port parser v1, cache PostgreSQL SHA256, supporto PDF/DOCX/XLSX/DXF", "~2 gg"],
    ["Fase 2", "Vector Store su pgvector", "Tabelle document_chunks con embedding, API search semantica", "~3 gg"],
    ["Fase 3", "KB Admin UI", "Pagina admin: upload manuale file, insegna fatti, cerca in KB", "~2 gg"],
    ["Fase 4", "SMB Connector", "Mount CIFS + watcher async + auto-ingest on change", "~3 gg"],
    ["Fase 5", "RAG in chat AI", "Inject contesto KB in medic_chat e tutti i canali", "~1 gg"],
    ["Fase 6", "Canali esterni", "WhatsApp + Email + Telegram con KB context", "~2 gg"],
  ];
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: cols,
    rows: [
      new TableRow({ children: ["Fase","Modulo","Descrizione","Stima"].map((t,i) => hcell(t, cols[i])) }),
      ...rows.map((r, i) => new TableRow({
        children: r.map((c, j) => dcell(c, cols[j], i % 2 === 0, j === 0)),
      })),
    ],
  });
}

// ── Cover ─────────────────────────────────────────────────────────────────────
function coverPage() {
  return [
    spacer(), spacer(), spacer(), spacer(), spacer(), spacer(),
    new Paragraph({
      children: [new TextRun({ text: "WorkMind", font: "Calibri", size: 64, bold: true, color: NAVY })],
      alignment: AlignmentType.CENTER, spacing: { before: 0, after: 0 },
    }),
    new Paragraph({
      children: [new TextRun({ text: "MEDIC", font: "Calibri", size: 64, bold: true, color: ACCENT })],
      alignment: AlignmentType.CENTER, spacing: { before: 0, after: 120 },
    }),
    new Paragraph({
      border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: ACCENT, space: 4 } },
      children: [], spacing: { before: 0, after: 240 },
    }),
    new Paragraph({
      children: [new TextRun({ text: "Knowledge Base & Document Intelligence", font: "Calibri", size: 30, bold: true, color: TEAL })],
      alignment: AlignmentType.CENTER, spacing: { before: 0, after: 80 },
    }),
    new Paragraph({
      children: [new TextRun({ text: "Apprendimento dai File Aziendali — Design Study", font: "Calibri", size: 24, color: GREY })],
      alignment: AlignmentType.CENTER, spacing: { before: 0, after: 480 },
    }),
    spacer(), spacer(), spacer(),
    new Paragraph({
      children: [new TextRun({ text: "Studio Tecnico per Evoluzione v1 → v2 — Aprile 2026", font: "Calibri", size: 20, color: GREY })],
      alignment: AlignmentType.CENTER, spacing: { before: 0, after: 80 },
    }),
    new Paragraph({
      children: [new TextRun({ text: "Documento non implementato — analisi e progettazione", font: "Calibri", size: 20, color: ORANGE, italics: true })],
      alignment: AlignmentType.CENTER, spacing: { before: 0, after: 0 },
    }),
    new Paragraph({ children: [new TextRun("")], pageBreakBefore: true }),
  ];
}

// ── Document ──────────────────────────────────────────────────────────────────
const doc = new Document({
  numbering: {
    config: [
      { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "\u2022", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 560, hanging: 280 } } } }] },
      { reference: "bullets2", levels: [{ level: 0, format: LevelFormat.BULLET, text: "\u25E6", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 900, hanging: 280 } } } }] },
      { reference: "numbers", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 560, hanging: 280 } } } }] },
    ],
  },
  styles: {
    default: { document: { run: { font: "Calibri", size: 22, color: "222222" } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: "Calibri", size: 26, bold: true, color: NAVY },
        paragraph: { spacing: { before: 400, after: 120 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: "Calibri", size: 22, bold: true, color: BLUE },
        paragraph: { spacing: { before: 280, after: 80 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: "Calibri", size: 20, bold: true, color: GREY },
        paragraph: { spacing: { before: 180, after: 60 }, outlineLevel: 2 } },
    ],
  },
  sections: [{
    properties: {
      page: {
        size: { width: PAGE.width, height: PAGE.height },
        margin: { top: MARGIN, right: MARGIN, bottom: MARGIN, left: MARGIN },
      },
    },
    headers: {
      default: new Header({ children: [new Paragraph({
        children: [new TextRun({ text: "WorkMind MEDIC \u2014 Knowledge Base & Document Intelligence", font: "Calibri", size: 18, color: "999999" })],
        alignment: AlignmentType.RIGHT,
        border: { bottom: thin("DDDDDD") },
        spacing: { before: 0, after: 80 },
      })] }),
    },
    footers: {
      default: new Footer({ children: [new Paragraph({
        children: [new TextRun({ children: [PageNumber.CURRENT], font: "Calibri", size: 18, color: "999999" })],
        alignment: AlignmentType.CENTER,
        border: { top: thin("DDDDDD") },
        spacing: { before: 80, after: 0 },
      })] }),
    },
    children: [

      // ── Cover ──
      ...coverPage(),

      // ════════════════════════════════════════════════════
      h1("1. Che cos'è il Document Intelligence"),
      body("WorkMind nasce come assistente operativo che risponde a domande aziendali. Ma le domande più utili richiedono conoscenza: procedure interne, listini, schede tecniche, planimetrie, email storiche. Invece di dover istruire il sistema manualmente, l'obiettivo è che WorkMind impari autonomamente dai file già presenti in azienda."),
      spacer(),
      body("Il modulo Document Intelligence fa esattamente questo: monitora cartelle di rete condivise (SMB/CIFS), legge i file supportati, li scompone, li indicizza in una base di conoscenza vettoriale, e li rende disponibili a tutti i canali di interazione — chat web, WhatsApp, email, Telegram."),
      spacer(),
      callout("Risultato concreto per il cliente", [
        "\"Qual e il listino prezzi aggiornato del prodotto X?\" → risposta dal file Excel in rete",
        "\"Dammi le istruzioni di montaggio del componente Y\" → estratto dal PDF tecnico",
        "\"C'e una planimetria della sala trattamenti?\" → riferimento al file DWG/DXF",
        "\"Cosa dice il contratto con il fornitore Z?\" → estratto dal DOCX in archivio",
      ], TEAL, CALLOUT_GREEN),
      spacer(),

      // ════════════════════════════════════════════════════
      h1("2. Come funzionava in WorkMind v1"),
      body("WorkMind 1.0 aveva questo sistema parzialmente implementato. E utile capirlo per progettare la versione 2.0 in modo piu solido."),
      spacer(),

      h2("2.1 Tre livelli di memoria (v1)"),
      body("Il sistema v1 usava tre layer sovrapposti, ciascuno con un diverso trade-off tra velocita, precisione e dipendenze:"),
      spacer(),

      callout("Layer 1 — KnowledgeBase (sempre attiva, zero dipendenze)", [
        "Storage: file JSON su disco (data/knowledge_base.json)",
        "Ricerca: overlap di parole chiave (scoring 0-1, soglia 0.3)",
        "Contenuto: fatti insegnati via /teach, correzioni, processi, glossario",
        "Limite: ricerca lessicale, nessuna comprensione semantica",
      ], BLUE, CALLOUT_BLUE),
      spacer(),

      callout("Layer 2 — VectorStore RAG (ricerca semantica, ChromaDB)", [
        "Storage: ChromaDB persistente su disco (cosine similarity)",
        "Chunking: 500 caratteri con 50 di overlap, su confini di frase",
        "Ricerca: embedding vettoriale — trova concetti simili anche con parole diverse",
        "Indicizza: tutti i file in DATA_DIR + fatti KB + documenti caricati manualmente",
        "Limite: dipende da ChromaDB installato, non multi-tenant",
      ], ACCENT, CALLOUT_BLUE),
      spacer(),

      callout("Layer 3 — Mem0 (memoria conversazionale per utente)", [
        "Storage: Qdrant su disco + HuggingFace embeddings locali (all-MiniLM-L6-v2)",
        "Funzione: ricorda il contesto di ogni conversazione per ogni utente",
        "Estrazione fatti automatica: DeepSeek API analizza le conversazioni",
        "Sincronizzazione: i fatti KB vengono copiati in Mem0 via sync_from_kb()",
        "Limite: pesante in memoria, difficile da scalare, dipendenze multiple",
      ], TEAL, CALLOUT_GREEN),
      spacer(),

      h2("2.2 Il parser documentale (v1)"),
      body("Il DocumentParser v1 e un componente universale che gestisce tutti i formati con fallback automatici e cache Redis (SHA256, TTL 30 giorni):"),
      spacer(),
      formatsTable(),
      spacer(),

      h2("2.3 Il watcher SMB (v1)"),
      body("L'SmbWatcher monitorava i mount point CIFS/SMB su Linux usando la libreria watchdog (inotify) con fallback polling ogni 30 secondi. Alla rilevazione di un file creato o modificato, scattava un evento FileEvent con path, tipo e timestamp."),
      spacer(),
      callout("Limite critico trovato in v1", [
        "Il watcher era avviato con on_file_changed=None — nessun callback connesso",
        "I file venivano rilevati ma NON inviati al parser ne al vector store",
        "La pipeline SMB → Parser → VectorStore era progettata ma mai collegata",
        "In v2 questo e il primo gap da sanare",
      ], ORANGE, CALLOUT_ORANGE),
      spacer(),

      h2("2.4 Come la KB veniva usata nei canali (v1)"),
      body("Tutti i canali (web, WhatsApp, Telegram) seguivano lo stesso pattern a tre step:"),
      spacer(),
      callout("Flusso di risposta con KB in v1", [
        "Parola chiave rilevata (contatto, prezzo, procedura...) → cerca in KnowledgeBase JSON → se trovato, risponde senza chiamare AI (zero costo)",
        "Se non trovato → costruisce contesto: KB prompt + RAG ChromaDB + Mem0 memory",
        "Passa tutto come system prompt all'AI con istruzioni anti-allucinazione",
      ], NAVY, CALLOUT_BLUE),
      spacer(),

      // ════════════════════════════════════════════════════
      h1("3. Design proposto per WorkMind v2"),
      body("WorkMind v2 ha un'architettura molto piu solida rispetto a v1: async FastAPI, PostgreSQL multi-tenant, admin panel, connectors configurabili. Il database PostgreSQL gia contiene le tabelle documents, document_chunks e memories — mai utilizzate in v2 ma gia pronte."),
      spacer(),
      body("Il design proposto sfrutta questa infrastruttura esistente invece di aggiungere dipendenze esterne (ChromaDB, Qdrant su disco)."),
      spacer(),

      h2("3.1 Confronto v1 vs v2 proposto"),
      spacer(),
      v1v2Table(),
      spacer(),

      h2("3.2 Architettura v2 — I quattro componenti"),
      spacer(),

      h3("A) Document Parser Async"),
      body("Port diretto del parser v1 con due miglioramenti:"),
      bullet("Asincrono (asyncio + run_in_executor per operazioni bloccanti)"),
      bullet("Cache su PostgreSQL invece di Redis: tabella documents con colonne sha256, parsed_at, text_content"),
      bullet("Risultato: se un file e gia stato parsato e non cambiato (SHA256 identico), skip immediato"),
      spacer(),

      h3("B) Vector Store su pgvector"),
      body("Invece di ChromaDB su disco, si usa l'estensione pgvector per PostgreSQL — gia popolare, supportata da tutti i provider cloud, zero infrastrutture aggiuntive."),
      spacer(),
      callout("Struttura tabella document_chunks (gia presente in DB)", [
        "id, org_id — identificazione e isolamento multi-tenant",
        "document_id — FK verso documents",
        "chunk_index — posizione nel documento originale",
        "content — testo del chunk (500 caratteri)",
        "embedding — vettore float[] con pgvector (dimensione configurabile: 384 o 1536)",
        "meta_json — source_path, filename, page, sheet, layer (per DXF)",
      ], BLUE, CALLOUT_BLUE),
      spacer(),
      body("La ricerca semantica diventa una semplice query SQL:"),
      codeLine("SELECT content, meta_json, 1 - (embedding <=> query_vec) AS score"),
      codeLine("FROM document_chunks WHERE org_id = $1"),
      codeLine("ORDER BY embedding <=> query_vec LIMIT 5;"),
      spacer(),

      h3("C) SMB Connector — Admin Panel"),
      body("In v2, la configurazione degli share SMB avviene dall'admin panel web, non da un file YAML su server. Ogni organizzazione configura i propri share in modo indipendente."),
      spacer(),
      callout("Dati configurabili per share SMB", [
        "Host/IP del server NAS o file server Windows",
        "Nome dello share (es. \\\\SERVER\\DocumentiTecnici)",
        "Credenziali (utente/password SMB, cifrate in DB)",
        "Estensioni da indicizzare (default: pdf, docx, xlsx, dxf, dwg, eml)",
        "Percorsi da escludere (es. /Archivio_Vecchio, /Temp)",
        "Intervallo di re-scan completo (es. ogni 24h)",
      ], TEAL, CALLOUT_GREEN),
      spacer(),

      h3("D) Background Task Watcher"),
      body("In v2, il watcher diventa un FastAPI background task asincrono che parte con l'applicazione:"),
      spacer(),
      bullet("Al boot: scan completo di tutti gli share configurati e attivi"),
      bullet("In esecuzione: polling ogni N secondi (configurabile, default 60s)"),
      bullet("On change: file nuovo o modificato → parser → chunking → embedding → upsert in document_chunks"),
      bullet("Deduplication: SHA256 del file confrontato con il valore in DB — se identico, skip"),
      bullet("Errori non bloccanti: un file non leggibile viene loggato e saltato, il resto continua"),
      spacer(),

      h2("3.3 Integrazione con la chat AI (RAG in v2)"),
      body("Il flusso di risposta in v2 con KB attiva diventa:"),
      spacer(),
      callout("Flusso RAG in medic_chat v2", [
        "Riceve messaggio utente",
        "Calcola embedding del messaggio (stessa API usata per indicizzare)",
        "Query pgvector: TOP 5 chunk piu simili per quell'org_id",
        "Se score >= 0.35: aggiunge blocco '=== DOCUMENTI AZIENDALI ===' al system prompt",
        "Passa tutto a Claude con istruzione: 'usa solo i dati forniti, cita la fonte'",
        "Risposta include riferimento al file sorgente (es. 'da Listino_2026.xlsx, foglio Prezzi')",
      ], NAVY, CALLOUT_BLUE),
      spacer(),

      h2("3.4 KB e canali esterni"),
      body("In v2, la stessa KB viene iniettata in tutti i canali che WorkMind supportera:"),
      spacer(),
      bullet("Chat web (gia presente) — RAG context nel system prompt"),
      bullet("WhatsApp Business — risposta automatica con KB context + conferma operazioni"),
      bullet("Email — risposta automatica a email in entrata con conoscenza aziendale"),
      bullet("Telegram — bot con accesso KB per notifiche e query"),
      spacer(),
      body("Il vantaggio chiave: la KB e condivisa tra tutti i canali. Un documento caricato dallo share SMB e immediatamente disponibile su WhatsApp, email e chat senza nessuna configurazione aggiuntiva."),
      spacer(),

      // ════════════════════════════════════════════════════
      h1("4. Capacita di apprendimento — Cosa impara WorkMind"),
      spacer(),

      h2("4.1 Dalle cartelle di rete (automatico)"),
      bullet("Documenti tecnici e manuali (PDF) — procedure operative, schede prodotto"),
      bullet("Fogli di calcolo (Excel) — listini prezzi, capitolati, dati di produzione"),
      bullet("Documenti Word — contratti, specifiche, comunicazioni formali"),
      bullet("File CAD (DXF/DWG) — planimetrie, schemi tecnici, layout"),
      bullet("Email archiviate (EML/MSG) — storico comunicazioni con fornitori/clienti"),
      spacer(),

      h2("4.2 Insegnamento diretto (manuale)"),
      bullet("Chat /teach: 'Il nostro fornitore di siringhe e X, telefono Y' → fatto salvato"),
      bullet("Correzioni: se l'AI sbaglia, si corregge e il sistema impara"),
      bullet("Processi: sequenze di step per procedure standard aziendali"),
      bullet("Glossario: termini tecnici specifici del settore o dell'azienda"),
      spacer(),

      h2("4.3 Dalle conversazioni (automatico, opt-in)"),
      bullet("Ogni conversazione puo arricchire la memoria per quell'utente"),
      bullet("Preferenze, abitudini, contesti ricorrenti vengono ricordati"),
      bullet("Dati sensibili esclusi (configurabile per ruolo)"),
      spacer(),

      // ════════════════════════════════════════════════════
      h1("5. Piano di implementazione proposto"),
      body("L'implementazione e suddivisa in 6 fasi indipendenti e progressive. Ogni fase porta valore autonomamente — non e necessario completarle tutte per avere benefici."),
      spacer(),
      phaseTable(),
      spacer(),
      callout("Nota importante", [
        "Questo documento e uno studio di design — nessuna delle funzionalita descritte e ancora implementata in v2",
        "Le fasi 1-3 (parser, vector store, admin UI) sono le piu critiche e le meno dipendenti da infrastruttura esterna",
        "La fase 4 (SMB) richiede accesso di rete al file server aziendale e credenziali SMB",
        "Le fasi 5-6 (canali esterni) dipendono dalla configurazione delle relative API (WhatsApp Business, SMTP, Telegram)",
      ], ORANGE, CALLOUT_ORANGE),
      spacer(),

      // ════════════════════════════════════════════════════
      h1("6. Requisiti Tecnici per l'Implementazione"),
      spacer(),
      h2("6.1 Lato server (Bender)"),
      bullet("PostgreSQL con estensione pgvector installata (apt install postgresql-16-pgvector)"),
      bullet("Mount CIFS configurati: il server Bender deve poter montare gli share SMB del client"),
      bullet("Librerie Python aggiuntive: pdfplumber, python-docx, openpyxl, ezdxf, extract_msg, chardet"),
      bullet("Embedding API: OpenAI text-embedding-3-small (1536 dim) o DeepSeek o modello locale"),
      spacer(),
      h2("6.2 Lato rete cliente"),
      bullet("File server Windows o NAS raggiungibile da Bender via Tailscale o VPN dedicata"),
      bullet("Utente SMB dedicato in sola lettura per WorkMind (no write access necessario)"),
      bullet("Whitelist IP o regola firewall per permettere la connessione da Bender"),
      spacer(),
      h2("6.3 Volumi attesi e performance"),
      bullet("1.000 documenti da 10 pagine ciascuno = ~20.000 chunk = ~20.000 embedding"),
      bullet("Indicizzazione iniziale: ~2-3 ore su CPU (o ~20 minuti con API OpenAI)"),
      bullet("Query RAG: <100ms (pgvector con index HNSW su 20.000 vettori)"),
      bullet("Re-scan incrementale (solo file modificati): <1 minuto tipicamente"),
      spacer(),

      // ════════════════════════════════════════════════════
      h1("7. Riepilogo"),
      body("WorkMind v1 ha dimostrato che la direzione e quella giusta: un assistente AI che conosce i documenti aziendali e radicalmente piu utile di un chatbot generico. L'architettura v1 pero aveva limiti strutturali — storage su disco non multi-tenant, pipeline SMB mai completamente collegata, dipendenze esterne fragili."),
      spacer(),
      body("WorkMind v2 ha gia le fondamenta giuste: database PostgreSQL con tabelle documents e document_chunks, architettura multi-tenant, admin panel configurabile. Il Document Intelligence e la prossima evoluzione naturale."),
      spacer(),
      callout("Valore per il cliente finale", [
        "Zero cambiamento operativo: i file restano dove sono, nelle cartelle di sempre",
        "Apprendimento continuo: ogni nuovo documento in rete e disponibile in chat entro 60 secondi",
        "Nessun doppio lavoro: niente copia-incolla di informazioni nel sistema",
        "Multi-canale: la stessa conoscenza su chat, WhatsApp, email, Telegram",
        "Tracciabile: ogni risposta AI cita il documento sorgente con nome file e posizione",
      ], TEAL, CALLOUT_GREEN),
      spacer(),

      new Paragraph({
        children: [new TextRun({ text: "Studio tecnico riservato — WorkMind v2 Design Document", font: "Calibri", size: 18, color: "999999", italics: true })],
        alignment: AlignmentType.CENTER,
        spacing: { before: 480, after: 0 },
      }),
    ],
  }],
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync("C:/Users/emanuele/Claude/workmind-v2/WorkMind_KB_DesignStudy.docx", buf);
  console.log("OK — saved WorkMind_KB_DesignStudy.docx");
}).catch(err => {
  console.error("ERROR:", err.message);
  process.exit(1);
});
