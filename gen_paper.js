const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
  ShadingType, VerticalAlign, PageNumber, LevelFormat, TableOfContents,
} = require("docx");
const fs = require("fs");

// ── Colors ────────────────────────────────────────────────────────────────────
const NAVY   = "1B3A6B";
const BLUE   = "2E5FA3";
const LBLUE  = "D6E4F7";
const GREY   = "555555";
const LGREY  = "F2F4F7";
const WHITE  = "FFFFFF";
const ACCENT = "2E75B6";
const CALLOUT_BG = "EBF3FB";

// ── Page: A4, 2.5cm margins ───────────────────────────────────────────────────
// A4: 11906 x 16838 DXA. 2.5cm = ~1418 DXA
const PAGE = { width: 11906, height: 16838 };
const MARGIN = 1418;
const CONTENT_W = PAGE.width - MARGIN * 2; // 9070 DXA

// ── Helpers ───────────────────────────────────────────────────────────────────
const sp = (before, after) => ({ spacing: { before, after } });
const thin = (color) => ({ style: BorderStyle.SINGLE, size: 4, color });
const none = () => ({ style: BorderStyle.NONE, size: 0, color: WHITE });

function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    children: [new TextRun({ text, font: "Calibri", size: 26, bold: true, color: NAVY })],
    spacing: { before: 360, after: 120 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: ACCENT, space: 4 } },
  });
}

function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    children: [new TextRun({ text, font: "Calibri", size: 22, bold: true, color: BLUE })],
    spacing: { before: 240, after: 80 },
  });
}

function h3(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_3,
    children: [new TextRun({ text, font: "Calibri", size: 20, bold: true, color: GREY })],
    spacing: { before: 180, after: 60 },
  });
}

function body(text, opts = {}) {
  return new Paragraph({
    children: [new TextRun({ text, font: "Calibri", size: 22, color: "222222", ...opts })],
    spacing: { before: 60, after: 60 },
  });
}

function bullet(text, bold_part = null) {
  const children = [];
  if (bold_part) {
    const idx = text.indexOf(bold_part);
    if (idx >= 0) {
      if (idx > 0) children.push(new TextRun({ text: text.slice(0, idx), font: "Calibri", size: 22, color: "222222" }));
      children.push(new TextRun({ text: bold_part, font: "Calibri", size: 22, bold: true, color: "222222" }));
      const rest = text.slice(idx + bold_part.length);
      if (rest) children.push(new TextRun({ text: rest, font: "Calibri", size: 22, color: "222222" }));
    } else {
      children.push(new TextRun({ text, font: "Calibri", size: 22, color: "222222" }));
    }
  } else {
    children.push(new TextRun({ text, font: "Calibri", size: 22, color: "222222" }));
  }
  return new Paragraph({
    numbering: { reference: "bullets", level: 0 },
    children,
    spacing: { before: 40, after: 40 },
  });
}

function bold_body(label, text) {
  return new Paragraph({
    children: [
      new TextRun({ text: label + " ", font: "Calibri", size: 22, bold: true, color: NAVY }),
      new TextRun({ text, font: "Calibri", size: 22, color: "222222" }),
    ],
    spacing: { before: 60, after: 60 },
  });
}

function spacer(lines = 1) {
  return new Paragraph({
    children: [new TextRun({ text: "", size: lines === 1 ? 16 : 22 })],
    spacing: { before: 0, after: 0 },
  });
}

// ── Cell helpers ──────────────────────────────────────────────────────────────
const cellBorder = {
  top: thin("CCCCCC"), bottom: thin("CCCCCC"),
  left: thin("CCCCCC"), right: thin("CCCCCC"),
};
const noBorder = { top: none(), bottom: none(), left: none(), right: none() };

function headerCell(text, width) {
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    borders: cellBorder,
    shading: { fill: NAVY, type: ShadingType.CLEAR },
    margins: { top: 80, bottom: 80, left: 140, right: 140 },
    verticalAlign: VerticalAlign.CENTER,
    children: [new Paragraph({
      children: [new TextRun({ text, font: "Calibri", size: 20, bold: true, color: WHITE })],
      alignment: AlignmentType.LEFT,
      spacing: { before: 0, after: 0 },
    })],
  });
}

function dataCell(text, width, shade = false, isBold = false) {
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    borders: cellBorder,
    shading: { fill: shade ? LGREY : WHITE, type: ShadingType.CLEAR },
    margins: { top: 80, bottom: 80, left: 140, right: 140 },
    verticalAlign: VerticalAlign.CENTER,
    children: [new Paragraph({
      children: [new TextRun({ text, font: "Calibri", size: 20, bold: isBold, color: "222222" })],
      spacing: { before: 0, after: 0 },
    })],
  });
}

function calloutBox(label, items) {
  // Simulate callout with a 1-column table, left border accent
  const children = [
    new Paragraph({
      children: [new TextRun({ text: label, font: "Calibri", size: 20, bold: true, color: ACCENT })],
      spacing: { before: 0, after: 60 },
    }),
    ...items.map((item, i) =>
      new Paragraph({
        numbering: { reference: "numbers", level: 0 },
        children: [new TextRun({ text: item, font: "Calibri", size: 20, color: "222222" })],
        spacing: { before: 40, after: 40 },
      })
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
          left: { style: BorderStyle.SINGLE, size: 18, color: ACCENT },
        },
        shading: { fill: CALLOUT_BG, type: ShadingType.CLEAR },
        margins: { top: 120, bottom: 120, left: 240, right: 160 },
        children,
      })],
    })],
  });
}

// ── Table builders ────────────────────────────────────────────────────────────
function ruoliTable() {
  const cols = [2000, 7070];
  const rows_data = [
    ["Admin", "Accesso completo: prodotti, vendite, utenti, configurazione AI, statistiche"],
    ["Supervisor", "Prodotti, vendite, carichi magazzino, statistiche"],
    ["Operatore", "Registrazione vendite, consultazione stock, assistente AI"],
  ];
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: cols,
    rows: [
      new TableRow({ children: [headerCell("Ruolo", cols[0]), headerCell("Permessi", cols[1])] }),
      ...rows_data.map((r, i) => new TableRow({
        children: [dataCell(r[0], cols[0], i % 2 === 0, true), dataCell(r[1], cols[1], i % 2 === 0)],
      })),
    ],
  });
}

function stackTable() {
  const cols = [2600, 2800, 3670];
  const rows_data = [
    ["Frontend", "SvelteKit", "SPA, mobile-first"],
    ["Backend", "FastAPI / Python", "API REST async"],
    ["Database", "PostgreSQL", "Transazionale, ACID"],
    ["Cache", "Redis", "Sessioni, performance"],
    ["AI", "Claude (Anthropic)", "Function calling"],
    ["Accesso", "Tailscale HTTPS", "VPN cifrata, SSL auto"],
    ["Server", "Debian Linux", "systemd, auto-restart"],
    ["Export", "CSV/Excel", "UTF-8 BOM, separatore ;"],
  ];
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: cols,
    rows: [
      new TableRow({ children: ["Componente","Tecnologia","Note"].map((t,i) => headerCell(t, cols[i])) }),
      ...rows_data.map((r, i) => new TableRow({
        children: r.map((cell, j) => dataCell(cell, cols[j], i % 2 === 0, j === 0)),
      })),
    ],
  });
}

// ── Cover page ────────────────────────────────────────────────────────────────
function coverPage() {
  return [
    spacer(8),
    new Paragraph({
      children: [new TextRun({ text: "WorkMind", font: "Calibri", size: 64, bold: true, color: NAVY })],
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 0 },
    }),
    new Paragraph({
      children: [new TextRun({ text: "MEDIC", font: "Calibri", size: 64, bold: true, color: ACCENT })],
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 120 },
    }),
    new Paragraph({
      border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: ACCENT, space: 4 } },
      children: [],
      spacing: { before: 0, after: 240 },
    }),
    new Paragraph({
      children: [new TextRun({ text: "Piattaforma di Gestione Intelligente", font: "Calibri", size: 30, color: GREY })],
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 80 },
    }),
    new Paragraph({
      children: [new TextRun({ text: "per Cliniche di Medicina Estetica", font: "Calibri", size: 30, color: GREY })],
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 480 },
    }),
    spacer(4),
    new Paragraph({
      children: [new TextRun({ text: "Documento Tecnico — Versione 1.0", font: "Calibri", size: 22, color: GREY })],
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 80 },
    }),
    new Paragraph({
      children: [new TextRun({ text: "Aprile 2026", font: "Calibri", size: 22, color: GREY })],
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 0 },
    }),
    new Paragraph({ children: [new TextRun("")], pageBreakBefore: true }),
  ];
}

// ── Main document ─────────────────────────────────────────────────────────────
const doc = new Document({
  numbering: {
    config: [
      {
        reference: "bullets",
        levels: [{
          level: 0, format: LevelFormat.BULLET, text: "\u2022",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 560, hanging: 280 } } },
        }],
      },
      {
        reference: "numbers",
        levels: [{
          level: 0, format: LevelFormat.DECIMAL, text: "%1.",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 560, hanging: 280 } } },
        }],
      },
    ],
  },
  styles: {
    default: {
      document: { run: { font: "Calibri", size: 22, color: "222222" } },
    },
    paragraphStyles: [
      {
        id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: "Calibri", size: 26, bold: true, color: NAVY },
        paragraph: { spacing: { before: 360, after: 120 }, outlineLevel: 0 },
      },
      {
        id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: "Calibri", size: 22, bold: true, color: BLUE },
        paragraph: { spacing: { before: 240, after: 80 }, outlineLevel: 1 },
      },
      {
        id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: "Calibri", size: 20, bold: true, color: GREY },
        paragraph: { spacing: { before: 180, after: 60 }, outlineLevel: 2 },
      },
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
      default: new Header({
        children: [new Paragraph({
          children: [new TextRun({ text: "WorkMind MEDIC \u2014 Documento Tecnico", font: "Calibri", size: 18, color: "999999" })],
          alignment: AlignmentType.RIGHT,
          border: { bottom: thin("DDDDDD") },
          spacing: { before: 0, after: 80 },
        })],
      }),
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          children: [
            new TextRun({ children: [PageNumber.CURRENT], font: "Calibri", size: 18, color: "999999" }),
          ],
          alignment: AlignmentType.CENTER,
          border: { top: thin("DDDDDD") },
          spacing: { before: 80, after: 0 },
        })],
      }),
    },
    children: [
      // ── Cover ──
      ...coverPage(),

      // ── 1. Panoramica ──
      h1("1. Panoramica del Sistema"),
      body("WorkMind MEDIC è una piattaforma web progettata per semplificare e digitalizzare la gestione operativa quotidiana di cliniche di medicina estetica. Il sistema integra gestione del magazzino, tracciamento delle vendite, analisi statistica e un assistente AI avanzato in un'unica interfaccia accessibile da qualsiasi dispositivo."),
      spacer(),
      h3("Obiettivi principali"),
      bullet("Eliminare fogli Excel e registri cartacei"),
      bullet("Avere visibilità in tempo reale su stock, vendite e scadenze"),
      bullet("Permettere al personale di registrare operazioni tramite linguaggio naturale (AI)"),
      bullet("Fornire statistiche chiare per decisioni di business"),
      spacer(),

      // ── 2. Architettura ──
      h1("2. Architettura Tecnica"),
      h2("2.1 Stack Tecnologico"),
      h3("Frontend (Interfaccia Utente)"),
      bullet("Framework: SvelteKit — applicazione web moderna, reattiva e veloce"),
      bullet("Design: responsive, ottimizzato per desktop, tablet e smartphone"),
      bullet("Accesso: browser web standard, nessuna installazione richiesta"),
      bullet("Offline-ready: l'interfaccia rimane reattiva anche con connessione lenta"),
      spacer(),
      h3("Backend (Server Applicativo)"),
      bullet("Framework: FastAPI (Python) — API RESTful ad alte prestazioni"),
      bullet("Database: PostgreSQL — database relazionale robusto e affidabile"),
      bullet("Cache: Redis — per sessioni e performance"),
      bullet("Autenticazione: JWT (JSON Web Token) con refresh automatico"),
      spacer(),
      h3("Infrastruttura"),
      bullet('Server: macchina dedicata "Bender" (Debian Linux)'),
      bullet("Accesso sicuro: Tailscale VPN — tunnel cifrato, nessuna porta esposta a internet"),
      bullet("URL: https://workmind-bender.tail898ef4.ts.net"),
      bullet("Certificato SSL: automatico via Tailscale"),
      bullet("Disponibilità: servizi gestiti da systemd con restart automatico in caso di crash"),
      spacer(),
      h2("2.2 Sicurezza"),
      bullet("Tutto il traffico è cifrato HTTPS end-to-end"),
      bullet("La piattaforma NON è accessibile da internet pubblico — solo tramite VPN Tailscale"),
      bullet("Autenticazione a ruoli: admin, supervisor, operatore"),
      bullet("Token JWT con scadenza automatica e refresh silenzioso"),
      bullet("Ogni operazione è tracciata con timestamp e operatore"),
      spacer(),

      // ── 3. Funzionalità ──
      h1("3. Funzionalità Principali"),
      h2("3.1 Dashboard — Vista d'insieme"),
      body("La dashboard mostra in tempo reale:"),
      bullet("Totale vendite del mese corrente (€)"),
      bullet("Numero di prodotti sotto la soglia minima di stock"),
      bullet("Prodotti in scadenza nei prossimi 30 giorni"),
      bullet("Grafico vendite per prodotto e per operatore"),
      spacer(),
      h2("3.2 Gestione Prodotti e Magazzino"),
      body("Ogni prodotto ha una scheda con:"),
      bullet("Nome, descrizione, unità di misura"),
      bullet("Stock attuale e soglia minima (alert automatico)"),
      bullet("Prezzo di vendita"),
      bullet("Lista lotti con numero lotto e data di scadenza"),
      spacer(),
      bold_body("Carico magazzino:", "si registrano i lotti in ingresso con numero lotto, quantità e scadenza. Lo stock viene aggiornato automaticamente."),
      bold_body("Alert scadenze:", "il sistema segnala automaticamente i prodotti in scadenza nei 30 giorni successivi."),
      spacer(),
      h2("3.3 Registro Vendite"),
      bullet("Registrazione vendite con prodotto, quantità, prezzo e operatore"),
      bullet("Selezione lotto specifica o automatica (FIFO — prima scade, prima esce)"),
      bullet("Storno vendita con ripristino automatico dello stock"),
      bullet("Storico completo con filtri per data, prodotto e operatore"),
      spacer(),
      h2("3.4 Registro Attività"),
      body("Log unificato di tutte le operazioni:"),
      bullet("Vendite (con prezzo unitario e totale)"),
      bullet("Carichi magazzino (con numero lotto e scadenza)"),
      bullet("Modifiche prodotti (aggiunte, modifiche, eliminazioni)"),
      bullet("Storni"),
      spacer(),
      bold_body("Filtri disponibili:", "tipo di evento, intervallo di date."),
      bold_body("Export:", "scarica il registro in formato Excel/CSV con un click."),
      spacer(),
      h2("3.5 Statistiche"),
      bullet("Vendite totali e per prodotto (grafico a barre)"),
      bullet("Performance per operatore (chi ha venduto quanto)"),
      bullet("Andamento mensile"),
      bullet("Prodotti più venduti"),
      spacer(),
      h2("3.6 Assistente AI — La Funzionalità Chiave"),
      body("L'assistente AI è integrato direttamente con il database in tempo reale. Non è un chatbot generico: conosce il vostro magazzino, le vostre vendite, i vostri prodotti."),
      spacer(),
      h3("Cosa può fare — Consultazioni (risposta immediata)"),
      bullet('"Quante siringhe di Juvederm abbiamo?" → risposta precisa con stock attuale'),
      bullet('"Chi ha venduto di piu questo mese?" → classifica operatori'),
      bullet('"Ci sono prodotti in scadenza?" → lista con date'),
      bullet('"Qual e il totale vendite di questa settimana?" → calcolo automatico'),
      spacer(),
      h3("Cosa può fare — Operazioni dirette (con conferma)"),
      bullet('"Registra una vendita di Botox 1 siringa a 120€" → chiede conferma → salva nel DB, aggiorna stock'),
      bullet('"Carica 5 siringhe di Azalou, lotto LOT-2026-001, scadenza 30/06/2027" → chiede conferma → aggiorna magazzino'),
      spacer(),
      calloutBox("Flusso di sicurezza per operazioni con AI", [
        "Operatore chiede all'AI di eseguire un'azione",
        "L'AI mostra un riepilogo dettagliato (prodotto, quantita, prezzo, data)",
        "Operatore conferma con \"si\" o \"conferma\"",
        "L'AI esegue l'operazione nel database",
        "Viene mostrato il risultato con lo stock aggiornato",
      ]),
      spacer(),
      bold_body("Tecnologia AI:", "Claude (Anthropic) con function calling — il modello AI ha accesso diretto agli strumenti del sistema (registra vendita, carica stock) e li usa solo previa conferma esplicita."),
      bold_body("Persistenza conversazione:", "la chat e memorizzata nel browser — si puo riprendere la conversazione anche dopo aver cambiato pagina o riavviato il browser. Si azzera solo cliccando \"Nuova chat\"."),
      spacer(),

      // ── 4. Utenti ──
      h1("4. Gestione Utenti e Permessi"),
      body("Il sistema supporta tre livelli di accesso:"),
      spacer(),
      ruoliTable(),
      spacer(),
      body("I permessi dell'AI sono configurabili per ruolo: ad esempio, solo admin e supervisor possono fare carichi magazzino tramite AI, mentre tutti possono fare vendite."),
      spacer(),

      // ── 5. Accesso ──
      h1("5. Accesso e Compatibilità"),
      bold_body("URL:", "https://workmind-bender.tail898ef4.ts.net"),
      bold_body("Dispositivi:", "PC, Mac, tablet, smartphone (iOS e Android)"),
      bold_body("Browser:", "Chrome, Firefox, Safari, Edge — nessuna installazione"),
      bold_body("Requisito:", "connessione VPN Tailscale attiva (app gratuita, installazione una tantum)"),
      bold_body("Connessione minima:", "1 Mbps e sufficiente"),
      spacer(),

      // ── 6. Affidabilità ──
      h1("6. Affidabilità e Continuità Operativa"),
      bold_body("Uptime:", "servizi gestiti da systemd con restart automatico"),
      bold_body("Avvio automatico:", "tutti i servizi partono automaticamente al riavvio del server"),
      bold_body("Database:", "PostgreSQL con backup configurabile"),
      bold_body("Log:", "ogni operazione e registrata con timestamp — nessuna perdita di dati"),
      spacer(),

      // ── 7. Espandibilità ──
      h1("7. Espandibilità"),
      body("Il sistema e progettato per crescere:"),
      bullet("Aggiunta di nuovi tipi di operazioni AI (es. generazione report, notifiche)"),
      bullet("Integrazione con sistemi di fatturazione"),
      bullet("Notifiche WhatsApp/Email per alert stock"),
      bullet("Multi-sede (piu cliniche sulla stessa piattaforma)"),
      bullet("App mobile nativa (il backend e gia API-first)"),
      spacer(),

      // ── 8. Riepilogo ──
      h1("8. Riepilogo Tecnico"),
      spacer(),
      stackTable(),
      spacer(2),
      new Paragraph({
        children: [new TextRun({ text: "Documento riservato — uso interno", font: "Calibri", size: 18, color: "999999", italics: true })],
        alignment: AlignmentType.CENTER,
        spacing: { before: 480, after: 0 },
      }),
    ],
  }],
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync("C:/Users/emanuele/Claude/workmind-v2/WorkMind_MEDIC_TechnicalPaper.docx", buf);
  console.log("OK — file saved");
}).catch(err => {
  console.error("ERROR:", err.message);
  process.exit(1);
});
