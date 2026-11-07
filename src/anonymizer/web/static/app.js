/**
 * @file app.js
 * @brief Interfaccia browser per la revisione degli oscuramenti proposti.
 *
 * Gestisce il caricamento dei documenti, l'analisi tramite l'API locale, la
 * revisione pagina per pagina (clic, disegno, spostamento, zoom), l'anteprima
 * sincronizzata tra immagine e testo, la conferma finale e l'esportazione.
 * Ogni richiesta porta con sé contratto firmato e stato di revisione, così il
 * server può verificare che l'esportazione corrisponda a quanto confermato.
 */
"use strict";
/**
 * @brief Restituisce l'elemento del DOM con l'identificativo indicato.
 * @param {string} id Identificativo dell'elemento.
 * @returns {HTMLElement|null} Elemento trovato o null.
 */
const $ = id => document.getElementById(id);
/**
 * @brief Namespace XML usato per creare gli elementi SVG delle sovrapposizioni.
 */
const svgNS = "http://www.w3.org/2000/svg";
/**
 * @brief Stato principale: file selezionati, risultato dell'analisi, revisione e pagina.
 */
let files = [],
  analysis = null,
  review = {},
  page = 0;
/**
 * @brief Contatori di generazione e revisione e stato dell'ultima anteprima ricevuta.
 *
 * Servono a scartare le risposte arrivate dopo una modifica o un reset.
 */
let generation = 0,
  revision = 0,
  previewRevision = -1,
  previewPage = -1;
/**
 * @brief Indicatori delle operazioni in corso verso il server.
 */
let running = false,
  pending = false,
  analyzing = false,
  exporting = false;
/**
 * @brief Strumento attivo, gesto in corso, timer di aggiornamento e coda delle richieste.
 */
let tool = "click",
  drawing = null,
  refreshTimer = null,
  requestTail = Promise.resolve();
/**
 * @brief Pile di annullamento/ripristino e cache dei riquadri delle parole per pagina.
 */
let history = [],
  future = [],
  wordsCache = new Map();
/**
 * @brief Stato dei gesti di scorrimento usati per il cambio pagina ai bordi.
 */
let edgeGesture = null,
  edgeWheelTimer = null,
  scrollPageEntry = null,
  nativeBarGesture = null,
  lastMasterTop = 0;
/**
 * @brief Tempi delle fasi di elaborazione riportati dal server, in secondi.
 */
let stageTimings = {};
/**
 * @brief Indica se almeno un'anteprima è stata caricata per il documento corrente.
 */
let documentReady = false;
/**
 * @brief Zoom e spostamento condivisi tra i pannelli e ancore testo/immagine.
 */
let sharedZoom = 1,
  sharedPanX = 0,
  scrollAnchors = [],
  previewLines = [];
/**
 * @brief Testo della pagina mostrato, originale e oscurato, usato per copia e download.
 */
let displayedText = {
  original: "",
  redacted: ""
};
/**
 * @brief Posizione verticale in coordinate pagina e scala corrente di visualizzazione.
 */
let sharedSourceTop = 0,
  sharedScale = 1;
/**
 * @brief Errore dell'ultima anteprima, necessità di rianalisi e area da evidenziare.
 */
let previewError = null,
  previewNeedsAnalysis = false,
  focusGeometry = null;
/**
 * @brief Testi in italiano delle note di lettura, indicizzati per codice di avviso.
 */
const warningNames = {
  identity_document_visual_review: "Documento di identità: controlla e oscura anche foto, firme, codici a barre e numeri ripetuti o non letti dall’OCR.",
  identity_ocr_fallback_requires_review: "Lettura migliorata per il documento di identità: verifica i campi recuperati e le zone ancora leggibili.",
  identity_ocr_retry_inconclusive: "La lettura aggiuntiva del documento non è stata sufficiente: controlla e oscura manualmente i dati rimasti visibili.",
  residual_graphics_ocr_requires_review: "Verifica anche il testo ricavato dalla grafica residua del PDF",
  reading_order_and_table_relations_require_review: "Verifica ordine di lettura e tabelle",
  detector_coverage_limited: "La rilevazione automatica ha copertura limitata",
  preprocessing_orientation_only_no_deskew: "Orientamento corretto; inclinazione non corretta",
  manual_review_nontext_identifiers_and_clinical_detail: "Verifica dati non testuali e conservazione del contenuto clinico",
  ner_disabled: "NER disabilitato",
  identity_unconfirmed: "Identità non confermata",
  ocr_reading_order_requires_review: "Verifica testo e ordine di lettura OCR",
  candidate_geometry_incomplete: "Area non individuata completamente: aggiungi un rettangolo collegato",
  low_ocr_confidence: "OCR incerto: controlla l’immagine",
  no_readable_text_manual_review: "Nessun testo leggibile: verifica manualmente tutta la pagina"
};
/**
 * @brief Messaggi in italiano per i codici di errore restituiti dall'API.
 */
const errors = {
  total_pixel_limit: "Il documento supera le dimensioni complessive elaborabili. Dividilo in più parti oppure scegli esplicitamente una qualità PDF inferiore nelle impostazioni e ripeti l'analisi.",
  page_pixel_limit: "Una pagina supera il limite di dimensioni elaborabili. Per un PDF scegli una qualità inferiore nelle impostazioni; per un'immagine usa una copia a risoluzione inferiore.",
  page_count_limit: "Il numero di pagine supera il limite consentito. Dividi il documento o seleziona meno file e ripeti l'analisi.",
  input_byte_limit: "I documenti selezionati superano il limite complessivo di dimensione dei file. Seleziona meno file o dividi il documento.",
  input_file_limit: "Il numero di file selezionati supera il limite consentito. Seleziona meno documenti e ripeti l'analisi.",
  operation_busy: "Operazione in corso. Attendi e riprova.",
  upload_byte_limit: "Dimensione massima dei documenti superata.",
  analysis_contract_expired: "Sessione scaduta: analizza nuovamente i documenti.",
  analysis_contract_signature_invalid: "Sessione non valida o server riavviato: ripeti l’analisi.",
  original_source_hash_or_order_mismatch: "I documenti non corrispondono agli originali analizzati.",
  unconfirmed_redaction: "Conferma la verifica dell’intero documento prima di esportare.",
  unresolved_review_warning: "Controlla le note di lettura e conferma l’intero documento.",
  unresolved_candidate_geometry: "Completa le aree senza geometria con un rettangolo collegato.",
  rejection_requires_reason: "Manca il motivo di un ripristino.",
  final_review_confirmation_required: "Conferma la verifica finale prima di esportare.",
  review_changed_since_preview: "Il documento è cambiato: attendi l’anteprima e conferma nuovamente.",
  output_must_be_pdf_or_single_page_png: "Per più pagine scegli il formato PDF.",
  ner_model_load_failed: "Caricamento NER fallito. Controlla la configurazione locale.",
  ocr_unavailable_failed_or_timeout: "OCR non disponibile o non riuscito. Controlla il servizio locale.",
  unsupported_color_profile: "Profilo colore non supportato.",
  invalid_color_profile: "Il profilo colore dell’immagine non è valido.",
  invalid_or_unsupported_color_profile: "Il profilo colore dell’immagine non può essere convertito in modo affidabile.",
  unsupported_color_profile_primaries: "L’immagine usa colori non sRGB senza un profilo ICC utilizzabile. Esportala in sRGB e riprova.",
  unsupported_depth_alpha_or_color_mode: "Profondità o trasparenza non supportata.",
  local_access_only: "Servizio accessibile solo dal computer locale."
};

/**
 * @brief Mostra un messaggio nell'area di stato.
 * @param {string} text Testo da mostrare.
 */
function message(text) {
  $("message").textContent = text;
}

/**
 * @brief Crea un elemento HTML con contenuto testuale opzionale.
 * @param {string} tag Nome del tag.
 * @param {string} [text] Testo da assegnare, se presente.
 * @returns {HTMLElement} Elemento creato.
 */
function node(tag, text) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  return element;
}

/**
 * @brief Restituisce i dati del manifest per la pagina corrente.
 * @returns {Object} Voce della pagina nel manifest del contratto.
 */
function pageData() {
  return analysis.contract.manifest.pages[page];
}

/**
 * @brief Copia profonda di un valore serializzabile in JSON.
 * @param {*} value Valore da copiare.
 * @returns {*} Copia indipendente del valore.
 */
function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

/**
 * @brief Aggiorna i tempi delle fasi e ne mostra il riepilogo.
 * @param {Object} values Tempi per fase da unire a quelli già noti.
 */
function timing(values) {
  Object.assign(stageTimings, values);
  const names = {
    analysis_wall: "Analisi completa",
    ingest: "Lettura",
    render: "Rendering",
    ocr: "OCR",
    ner: "NER",
    text_other: "Regole testuali",
    proposals: "Proposte",
    preview: "Anteprima",
    export: "Esportazione",
    export_source_check: "Controllo originali",
    export_render: "Rendering esportazione",
    export_masks: "Applicazione oscuramenti",
    export_encode: "Creazione file"
  };
  const durations = Object.entries(names)
    .filter(([key]) => Number.isFinite(stageTimings[key]))
    .map(([key, label]) => `${label}: ${stageTimings[key].toFixed(2)} s`);
  if (stageTimings.overlap_enabled) durations.push("OCR e NER sovrapposti: i tempi delle fasi non si sommano");
  $("timings").textContent = durations.join(" · ");
}

/**
 * @brief Prepara il corpo multipart di una richiesta all'API.
 *
 * Include sempre i file; dopo l'analisi aggiunge contratto, firma e revisione.
 * @returns {FormData} Dati da inviare.
 */
function form() {
  const data = new FormData();
  for (const file of files) data.append("files", file);
  if (analysis) {
    data.append("contract", JSON.stringify(analysis.contract));
    data.append("signature", analysis.signature);
    data.append("review", JSON.stringify(review));
  }
  return data;
}

/**
 * @brief Invia una richiesta POST all'API in coda alle precedenti.
 *
 * Le richieste sono serializzate; prima dell'invio si verifica che non siano
 * state superate da modifiche successive.
 * @param {string} route Percorso sotto /api/.
 * @param {FormData} data Corpo della richiesta.
 * @param {function(): boolean} [valid] Controllo di validità eseguito prima dell'invio.
 * @returns {Promise<Response>} Risposta riuscita.
 * @throws {Error} Con proprietà code se superata o se il server risponde con errore.
 */
function request(route, data, valid = () => true) {
  const result = requestTail.catch(() => {}).then(async () => {
    if (!valid()) throw new Error("Operazione superata da una modifica successiva.");
    const response = await fetch(`/api/${route}`, {
      method: "POST",
      body: data
    });
    if (!response.ok) {
      let code = "operation_failed";
      try {
        code = (await response.json()).error;
      } catch {}
      const error = new Error(errors[code] || "Operazione non riuscita. Controlla formato, limiti e configurazione locale.");
      error.code = code;
      throw error;
    }
    return response;
  });
  requestTail = result;
  return result;
}

/**
 * @brief Indica se l'anteprima mostrata corrisponde allo stato corrente e nulla è in corso.
 * @returns {boolean} Vero se si può interagire con la pagina in modo affidabile.
 */
function canonicalReady() {
  return analysis && previewRevision === revision && previewPage === page && !pending && !running && !analyzing;
}

/**
 * @brief Aggiorna abilitazione dei comandi, passi, messaggi di aiuto e stato di attesa.
 *
 * Se c'è un'area senza geometria da evidenziare sulla pagina corrente, la porta in vista.
 */
function controls() {
  document.body.classList.toggle("review-mode", !!analysis);
  const ready = !!canonicalReady();
  $("finalStep").hidden = !documentReady;
  $("settings").hidden = $("landing").hidden;
  $("final").disabled = exporting || (!ready && !$("final").checked);
  const approved = ready && review.final_confirmation === true && $("final").checked && !exporting;
  const currentStep = analysis ? (review.final_confirmation === true ? 2 : 1) : 0;
  ["stepUpload", "stepReview", "stepExport"].forEach((id, index) => {
    $(id).classList.toggle("complete", index < currentStep);
    if (index === currentStep) $(id).setAttribute("aria-current", "step");
    else $(id).removeAttribute("aria-current");
  });
  $("reviewProgress").textContent = analysis ? `Pagina ${page + 1} di ${analysis.contract.manifest.pages.length}` : "";
  $("export").disabled = !approved;
  $("copyRedacted").disabled = !approved;
  $("copyOriginal").disabled = !ready;
  $("downloadOriginal").disabled = !ready;
  $("undo").disabled = !history.length || !analysis;
  $("redo").disabled = !future.length || !analysis;
  $("analyze").disabled = analyzing || !files.length;
  $("analyze").setAttribute("aria-busy", String(analyzing));
  $("workspace").setAttribute("aria-busy", String(!!analysis && (running || pending)));
  const working = analyzing || (!!analysis && (running || pending));
  $("message").classList.toggle("working", working);
  $("message").setAttribute("aria-busy", String(working));
  let reason;
  const geometryIssue = analysis ? incompleteGeometry() : null;
  if (!analysis) reason = "Analizza i documenti per preparare la revisione.";
  else if (exporting) reason = "Operazione in corso: attendi il completamento.";
  else if (previewError) reason = `Anteprima non aggiornata. ${previewError}`;
  else if (!ready) reason = $("final").checked ? "Conferma ricevuta. Preparazione dell'anteprima finale..." : "Preparazione anteprima: attendi prima di confermare il documento.";
  else if (geometryIssue) reason = `Completa prima l'area senza geometria nella pagina ${geometryIssue.page + 1}, poi conferma l'intero documento.`;
  else if (!$("final").checked) reason = "Quando hai terminato il controllo, conferma l'intero documento per abilitare copia ed esportazione.";
  else reason = "Documento confermato: puoi copiare il testo oscurato completo o esportare la copia.";
  $("completionHelp").textContent = reason;
  $("copyActionHelp").textContent = reason;
  $("previewRecovery").hidden = !analysis || !previewError;
  $("previewErrorMessage").textContent = previewError || "";
  $("retryPreview").hidden = previewNeedsAnalysis;
  $("retryPreview").disabled = running || analyzing || exporting;
  $("repeatAnalysis").disabled = running || analyzing || exporting;
  if (analysis) {
    $("prevPage").disabled = page === 0;
    $("nextPage").disabled = page === analysis.contract.manifest.pages.length - 1;
  }
  updatePanCursor();
  if (ready && focusGeometry && focusGeometry.page === page) {
    const issue = focusGeometry;
    focusGeometry = null;
    $("candidate").value = issue.candidate;
    $("reviewDetails").open = true;
    $("warningSummary").scrollIntoView({
      block: "nearest"
    });
    $("warningSummary").focus();
    message(`Completa l’area ${issue.candidate.slice(0, 8)} nella pagina ${issue.page + 1} con un rettangolo collegato, poi conferma l’intero documento.`);
  }
}

/**
 * @brief Segna la revisione come modificata e pianifica una nuova anteprima.
 *
 * Invalida l'anteprima e il digest precedenti, così la conferma va rinnovata.
 * @param {boolean} [confirmed] Stato di conferma finale da impostare.
 */
function invalidate(confirmed = false) {
  cancelEdgeNavigation();
  cancelGesture();
  previewError = null;
  previewNeedsAnalysis = false;
  revision++;
  review.final_confirmation = confirmed;
  delete review.preview_digest;
  $("final").checked = confirmed;
  $("textRedacted").textContent = "Aggiornamento del testo oscurato…";
  $("previewStatus").textContent = "aggiornamento in corso";
  pending = true;
  controls();
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => void refresh(), 160);
}

/**
 * @brief Fotografa lo stato di revisione di una pagina per annulla/ripristina.
 * @param {number} [index] Indice della pagina.
 * @returns {Object} Decisioni, conferme degli avvisi e maschere manuali della pagina.
 */
function snapshot(index = page) {
  const data = analysis.contract.manifest.pages[index],
    id = data.page.page_id;
  const ids = new Set(data.redactions.map(mask => mask.id));
  return {
    page: index,
    decisions: clone(Object.fromEntries(Object.entries(review.decisions).filter(([key]) => ids.has(key)))),
    acknowledgments: clone(review.acknowledgments[id] || []),
    manual_masks: clone(review.manual_masks.filter(mask => mask.page_id === id))
  };
}

/**
 * @brief Applica una modifica alla revisione salvando lo stato per l'annullamento.
 * @param {function(): void} action Modifica da eseguire su review.
 */
function edit(action) {
  history.push(snapshot());
  if (history.length > 60) history.shift();
  future = [];
  action();
  invalidate();
  renderPageControls();
}
/**
 * @brief Richiede anteprime finché ci sono modifiche in sospeso.
 *
 * Le risposte superate da una nuova revisione, pagina o generazione vengono scartate.
 * @returns {Promise<void>} Completata quando non ci sono più aggiornamenti in sospeso.
 */
async function refresh() {
  if (running || !analysis) return;
  cancelGesture();
  running = true;
  message("Preparazione anteprima…");
  previewError = null;
  previewNeedsAnalysis = false;
  controls();
  const token = generation;
  try {
    while (pending && analysis && token === generation) {
      pending = false;
      const version = revision,
        index = page,
        data = form();
      data.append("page", index);
      try {
        const response = await request("preview", data, () => token === generation && version === revision);
        const result = await response.json();
        if (token !== generation || version !== revision || index !== page) continue;
        $("original").src = `data:image/png;base64,${result.original}`;
        $("redacted").src = `data:image/png;base64,${result.redacted}`;
        await Promise.all([$("original").decode(), $("redacted").decode()]);
        if (token !== generation || version !== revision || index !== page) continue;
        showGeometricText(result.text);
        for (const id of ["overlay", "redactedOverlay"]) $(id).setAttribute("viewBox", `0 0 ${result.width} ${result.height}`);
        review.preview_digest = result.preview_digest;
        previewRevision = version;
        previewPage = index;
        previewError = null;
        previewNeedsAnalysis = false;
        documentReady = true;
        timing(result.timings);
        $("previewStatus").textContent = "anteprima aggiornata";
        renderPageControls();
        message("Anteprima aggiornata. Puoi correggere le aree o confermare l’intero documento.");
      } catch (error) {
        if (token === generation && version === revision && index === page) {
          previewError = error.code ? error.message : "Impossibile caricare l’anteprima. Riprova; se l’errore persiste, ripeti l’analisi.";
          previewNeedsAnalysis = ["analysis_contract_expired", "analysis_contract_signature_invalid", "original_source_hash_or_order_mismatch"].includes(error.code);
          if (previewNeedsAnalysis) previewError += " Ripeti l’analisi per avviare una nuova revisione.";
          $("previewStatus").textContent = "anteprima non disponibile";
          message(previewError);
        }
      }
    }
  } finally {
    running = false;
    controls();
    if (pending && analysis) void refresh();
  }
}

/**
 * @brief Azzera analisi, revisione e vista, tornando alla schermata di caricamento.
 */
function reset() {
  cancelGesture();
  sharedZoom = 1;
  generation++;
  revision++;
  analysis = null;
  documentReady = false;
  previewError = null;
  previewNeedsAnalysis = false;
  focusGeometry = null;
  review = {};
  stageTimings = {};
  history = [];
  future = [];
  wordsCache.clear();
  analyzing = false;
  pending = false;
  previewRevision = previewPage = -1;
  clearTimeout(refreshTimer);
  $("workspace").hidden = true;
  $("landing").hidden = false;
  for (const id of ["original", "redacted"]) $(id).removeAttribute("src");
  for (const id of ["overlay", "redactedOverlay", "warnings", "exceptions"]) $(id).replaceChildren();
  clearSharedView();
  $("final").checked = false;
  $("timings").textContent = "";
  controls();
}

/**
 * @brief Sostituisce l'elenco dei file selezionati e ne aggiorna la lista.
 * @param {File[]} next Nuovo elenco di file.
 */
function updateFiles(next) {
  reset();
  files = next;
  $("files").value = "";
  $("fileList").replaceChildren();
  files.forEach((file, index) => {
    const row = node("li"),
      remove = node("button", "×");
    remove.className = "quiet";
    remove.setAttribute("aria-label", `Rimuovi ${file.name}`);
    remove.dataset.fileIndex = String(index);
    remove.onclick = () => updateFiles(files.filter((_, i) => i !== index));
    row.append(node("span", file.name), node("small", `${(file.size / 1000000).toFixed(2)} MB`), remove);
    $("fileList").append(row);
  });
  controls();
  message(files.length ? "Documenti pronti per l’analisi." : "");
}

/**
 * @brief Elenca le maschere della pagina corrente con le decisioni dell'utente applicate.
 * @returns {Object[]} Maschere proposte e manuali della pagina.
 */
function masksOnPage() {
  const data = pageData();
  return data.redactions.map(mask => ({
    ...mask,
    ...(review.decisions[mask.id] || {})
  })).concat(review.manual_masks.filter(mask => mask.page_id === data.page.page_id).map(mask => ({
    ...mask,
    origin: "manual"
  })));
}

/**
 * @brief Verifica se un punto è dentro un poligono o molto vicino al suo bordo.
 * @param {number[][]} polygon Vertici del poligono.
 * @param {number[]} point Coordinate [x, y].
 * @returns {boolean} Vero se il punto è interno o sul bordo.
 */
function contains(polygon, point) {
  let inside = false;
  const [x, y] = point;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [xi, yi] = polygon[i], [xj, yj] = polygon[j];
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
    const dx = xj - xi,
      dy = yj - yi;
    const fraction = Math.max(0, Math.min(1, ((x - xi) * dx + (y - yi) * dy) / (dx * dx + dy * dy || 1)));
    if (Math.hypot(x - xi - fraction * dx, y - yi - fraction * dy) < .6) return true;
  }
  return inside;
}

/**
 * @brief Ricava i riquadri delle parole della pagina corrente dalle regioni OCR.
 *
 * Le regioni di pochi caratteri vengono estese alla parola intera; il risultato è
 * memorizzato per pagina.
 * @returns {Object[]} Riquadri con il testo della parola.
 */
function wordBoxes() {
  if (wordsCache.has(page)) return wordsCache.get(page);
  const data = pageData().page,
    chars = Array.from(data.text),
    results = new Map();
  const wordChar = char => char !== undefined && /[\p{L}\p{M}\p{N}_’'-]/u.test(char);
  for (const region of data.regions) {
    if (!region.box) continue;
    let start = region.start,
      end = region.end;
    if (end - start <= 2 && wordChar(chars[start])) {
      while (start > 0 && wordChar(chars[start - 1])) start--;
      while (end < chars.length && wordChar(chars[end])) end++;
    }
    const key = `${start}:${end}:${Math.round(region.box[1])}`;
    if (results.has(key)) continue;
    const related = data.regions.filter(r => r.box && r.start < end && r.end > start && r.box[1] < region.box[3] && r.box[3] > region.box[1]);
    const box = [Math.min(...related.map(r => r.box[0])), Math.min(...related.map(r => r.box[1])), Math.max(...related.map(r => r.box[2])), Math.max(...related.map(r => r.box[3]))];
    results.set(key, {
      box,
      text: chars.slice(start, end).join("")
    });
  }
  const result = [...results.values()];
  wordsCache.set(page, result);
  return result;
}

/**
 * @brief Crea un elemento SVG con gli attributi indicati.
 * @param {string} tag Nome del tag SVG.
 * @param {Object} attributes Attributi da impostare.
 * @returns {SVGElement} Elemento creato.
 */
function svgElement(tag, attributes) {
  const element = document.createElementNS(svgNS, tag);
  for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, value);
  return element;
}

/**
 * @brief Disegna sulle due immagini le zone attivabili di parole e maschere.
 */
function renderOverlays() {
  if (!analysis) return;
  const masks = masksOnPage();
  for (const id of ["overlay", "redactedOverlay"]) {
    const svg = $(id);
    svg.replaceChildren();
    for (const word of wordBoxes()) {
      const [x0, y0, x1, y1] = word.box;
      const center = [(x0 + x1) / 2, (y0 + y1) / 2];
      if (masks.some(mask => mask.decision !== "reject" && contains(mask.polygon, center))) continue;
      const zone = svgElement("rect", {
        x: x0,
        y: y0,
        width: x1 - x0,
        height: y1 - y0,
        class: "word-zone",
        tabindex: "0",
        role: "button",
        "aria-label": `Oscura parola: ${word.text}`
      });
      zone.onkeydown = event => keyboardClick(event, center);
      svg.append(zone);
    }
    masks.forEach((mask, index) => {
      const rejected = mask.decision === "reject";
      const zone = svgElement("polygon", {
        points: mask.polygon.map(p => p.join(",")).join(" "),
        class: `mask-zone${rejected ? " rejected" : ""}`,
        tabindex: "0",
        role: "button",
        "data-mask-id": mask.id,
        "data-decision": rejected ? "reject" : "apply",
        "aria-label": `${rejected ? "Oscura nuovamente" : mask.origin === "manual" ? "Rimuovi oscurazione manuale" : "Ripristina leggibilità"}: area ${index + 1}`
      });
      const center = [mask.polygon.reduce((s, p) => s + p[0], 0) / 4, mask.polygon.reduce((s, p) => s + p[1], 0) / 4];
      zone.onkeydown = event => keyboardClick(event, center);
      svg.append(zone);
    });
  }
}

/**
 * @brief Simula un clic da tastiera con Invio o Spazio su una zona.
 * @param {KeyboardEvent} event Evento tastiera.
 * @param {number[]} point Punto della pagina da attivare.
 */
function keyboardClick(event, point) {
  if (event.key !== "Enter" && event.key !== " ") return;
  event.preventDefault();
  clickPoint(point);
}

/**
 * @brief Aggiorna note di lettura, aree da completare e sovrapposizioni della pagina.
 */
function renderPageControls() {
  if (!analysis) return;
  const data = pageData(),
    id = data.page.page_id;
  renderToolHint();
  $("warnings").replaceChildren();
  for (const warning of data.warnings) $("warnings").append(node("div", warningNames[warning.code] || "Verifica aggiuntiva richiesta"));
  $("warningSummary").textContent = "Note di lettura";
  $("exceptions").replaceChildren();
  const required = [...new Set(data.warnings.filter(w => w.code === "candidate_geometry_incomplete").flatMap(w => w.candidate_ids))];
  const remaining = required.filter(candidate => !review.manual_masks.some(mask => mask.page_id === id && mask.candidate_ids.includes(candidate)));
  $("geometryBadge").hidden = !remaining.length;
  $("geometryBadge").textContent = `${remaining.length} ${remaining.length === 1 ? "area da completare" : "aree da completare"}`;
  const selected = $("candidate").value;
  $("candidate").replaceChildren(new Option("Nessun candidato", ""));
  for (const candidate of required) {
    const linked = review.manual_masks.some(mask => mask.page_id === id && mask.candidate_ids.includes(candidate));
    const row = node("div", `Area senza geometria ${candidate.slice(0, 8)} · ${linked ? "collegata ✓" : "da completare"}`);
    row.className = "exception";
    const button = node("button", "Disegna area collegata");
    button.onclick = () => {
      $("candidate").value = candidate;
      setTool("draw");
      $("reviewDetails").open = false;
      message(`Completa l’area ${candidate.slice(0, 8)}: disegna sull’immagine il rettangolo da oscurare.`);
    };
    row.append(button);
    $("exceptions").append(row);
    $("candidate").add(new Option(`Area ${candidate.slice(0, 8)}`, candidate));
  }
  if (required.includes(selected)) $("candidate").value = selected;
  $("candidateLabel").hidden = !required.length;
  renderOverlays();
  controls();
}

/**
 * @brief Aggiunge una maschera manuale rettangolare, collegata al candidato scelto.
 * @param {number[]} box Rettangolo [x0, y0, x1, y1] in coordinate pagina.
 */
function addRectangle(box) {
  const g = pageData().geometry;
  const [x0, y0, x1, y1] = box;
  if (x0 < 0 || y0 < 0 || x1 > g.width || y1 > g.height || x1 - x0 < 1 || y1 - y0 < 1) {
    message("Area troppo piccola o fuori dalla pagina: riprova.");
    return;
  }
  edit(() => review.manual_masks.push({
    id: crypto.randomUUID(),
    page_id: pageData().page.page_id,
    polygon: [
      [x0, y0],
      [x1, y0],
      [x1, y1],
      [x0, y1]
    ],
    confirmed: true,
    candidate_ids: $("candidate").value ? [$("candidate").value] : []
  }));
}

/**
 * @brief Gestisce il clic su un punto della pagina.
 *
 * Su un'oscurazione la ripristina (o la riapplica se già ripristinata); su una
 * parola riconosciuta aggiunge un rettangolo che la copre.
 * @param {number[]} point Coordinate [x, y] in pixel pagina.
 */
function clickPoint(point) {
  if (!canonicalReady()) return;
  const hits = masksOnPage().filter(mask => contains(mask.polygon, point));
  const active = hits.filter(mask => mask.decision !== "reject");
  const targets = active.length ? active : hits;
  if (targets.length) {
    const ids = new Set(targets.map(mask => mask.id));
    edit(() => {
      review.manual_masks = review.manual_masks.filter(mask => !ids.has(mask.id));
      for (const mask of targets.filter(mask => mask.origin !== "manual")) {
        review.decisions[mask.id] = {
          decision: active.length ? "reject" : "apply",
          confirmed: true,
          reason: active.length ? "Ripristinata con clic sul documento" : ""
        };
      }
    });
    message(`${targets.length} ${active.length ? "aree ripristinate" : "oscurazioni applicate"} nel punto selezionato. Altre parti dello stesso dato possono restare oscurate. Puoi annullare l’intera modifica.`);
    return;
  }
  const word = wordBoxes().find(({
    box: b
  }) => b[0] <= point[0] && point[0] <= b[2] && b[1] <= point[1] && point[1] <= b[3]);
  if (!word) {
    message("Nessuna parola riconosciuta qui. Usa Disegna per oscurare un’area libera.");
    return;
  }
  const g = pageData().geometry,
    b = word.box;
  addRectangle([Math.max(0, Math.floor(b[0]) - 2), Math.max(0, Math.floor(b[1]) - 2), Math.min(g.width, Math.ceil(b[2]) + 2), Math.min(g.height, Math.ceil(b[3]) + 2)]);
}

/**
 * @brief Aggiorna le classi del cursore delle sovrapposizioni in base allo strumento.
 */
function updatePanCursor() {
  for (const id of ["overlay", "redactedOverlay"]) {
    const svg = $(id);
    svg.classList.toggle("editing", tool === "draw");
    svg.classList.toggle("pan", tool === "pan" || (tool === "click" && sharedZoom > 1));
    svg.classList.toggle("panning", drawing?.svg === svg && drawing.panned === true);
  }
}

/**
 * @brief Annulla il gesto puntatore in corso rimuovendo la bozza e la cattura.
 */
function cancelGesture() {
  const previous = drawing;
  drawing = null;
  if (previous) {
    endScrollGesture(previous.scrollGesture);
    previous.svg.querySelector(".draft")?.remove();
    if (previous.svg.hasPointerCapture(previous.pointerId)) {
      previous.svg.releasePointerCapture(previous.pointerId);
    }
  }
  updatePanCursor();
}

/**
 * @brief Mostra il suggerimento d'uso per lo strumento attivo.
 */
function renderToolHint() {
  const identityDocument = analysis && pageData().warnings.some(w => w.code === "identity_document_visual_review");
  if (identityDocument) {
    $("toolHint").textContent = tool === "draw" ? "Documento di identità: trascina un rettangolo per coprire foto, firme, codici a barre e dati rimasti leggibili." : "Documento di identità: controlla anche foto, firme e codici a barre. Usa Disegna per coprirli; verifica i numeri ripetuti.";
    return;
  }
  $("toolHint").textContent = tool === "draw" ? "Trascina per oscurare un’area libera, anche senza testo riconosciuto." : tool === "pan" ? "Scorri o trascina per spostare il documento. Le oscurazioni restano invariate." : "Clicca un’oscurazione per ripristinare la leggibilità. Clicca una parola per oscurarla. Le aree tratteggiate sono ripristinate. Con zoom attivo, trascina per scorrere.";
}

/**
 * @brief Cambia lo strumento attivo (clic, disegno, spostamento).
 * @param {string} value Nome dello strumento.
 */
function setTool(value) {
  cancelEdgeNavigation();
  cancelGesture();
  tool = value;
  for (const [id, name] of [
      ["toolClick", "click"],
      ["toolDraw", "draw"],
      ["toolPan", "pan"]
    ]) $(id).setAttribute("aria-pressed", String(value === name));
  renderToolHint();
  renderOverlays();
  controls();
}

/**
 * @brief Converte la posizione del puntatore in coordinate pagina.
 * @param {PointerEvent} event Evento puntatore.
 * @param {SVGElement} svg Sovrapposizione di riferimento.
 * @returns {number[]} Coordinate [x, y] in pixel pagina.
 */
function pointerPoint(event, svg) {
  const rect = svg.getBoundingClientRect(),
    g = pageData().geometry;
  return [(event.clientX - rect.left) / rect.width * g.width, (event.clientY - rect.top) / rect.height * g.height];
}

/**
 * @brief Converte una posizione tra spazio logico di scorrimento e spazio pagina.
 *
 * Interpola linearmente tra le ancore che allineano le righe di testo all'immagine.
 * @param {number} value Posizione da convertire.
 * @param {string} from Chiave di partenza ("logical" o "source").
 * @param {string} to Chiave di arrivo.
 * @returns {number} Posizione convertita.
 */
function mapScroll(value, from, to) {
  if (!scrollAnchors.length) return 0;
  for (let i = 1; i < scrollAnchors.length; i++) {
    const a = scrollAnchors[i - 1],
      b = scrollAnchors[i];
    if (value <= b[from] && b[from] > a[from]) {
      const fraction = Math.max(0, Math.min(1, (value - a[from]) / (b[from] - a[from])));
      return a[to] + fraction * (b[to] - a[to]);
    }
  }
  return scrollAnchors.at(-1)[to];
}

/**
 * @brief Impedisce al gesto di scorrimento corrente di cambiare pagina.
 */
function cancelScrollIntent() {
  if (edgeGesture) edgeGesture.spent = true;
  nativeBarGesture = null;
}

/**
 * @brief Annulla ogni cambio pagina pendente dovuto allo scorrimento.
 */
function cancelEdgeNavigation() {
  cancelScrollIntent();
  scrollPageEntry = null;
}

/**
 * @brief Avvia o riprende un gesto di scorrimento legato alla revisione corrente.
 * @param {string} kind Tipo di gesto (rotella, tasto, barra, tocco, trascinamento).
 * @param {boolean} [fresh] Forza un nuovo gesto.
 * @returns {Object|null} Gesto attivo, o null se la vista non è pronta.
 */
function beginScrollGesture(kind, fresh = false) {
  if (fresh || !edgeGesture || edgeGesture.kind !== kind || edgeGesture.ended) {
    if (!canonicalReady()) return null;
    edgeGesture = {kind, page, token: generation, version: revision, spent: false, ended: false};
  }
  if (kind === "wheel") {
    clearTimeout(edgeWheelTimer);
    const gesture = edgeGesture;
    edgeWheelTimer = setTimeout(() => endScrollGesture(gesture), 350);
  }
  return edgeGesture;
}

/**
 * @brief Segna un gesto di scorrimento come concluso.
 * @param {Object|null} gesture Gesto da chiudere.
 */
function endScrollGesture(gesture) {
  if (gesture) gesture.ended = true;
}

/**
 * @brief Imposta lo scorrimento principale e sincronizza i pannelli.
 * @param {number} value Posizione logica di scorrimento.
 */
function setMasterScroll(value) {
  const master = $("masterScroll");
  master.scrollTop = value;
  // Scroll events are asynchronous, including those from script; record the applied position now.
  lastMasterTop = master.scrollTop;
  syncSharedScroll();
}

/**
 * @brief Passa alla pagina adiacente se il gesto ha raggiunto il bordo.
 *
 * Ogni gesto può cambiare pagina una sola volta.
 * @param {number} direction Verso dello scorrimento.
 * @param {Object} gesture Gesto in corso.
 * @returns {boolean} Vero se la pagina è stata cambiata.
 */
function maybeTurnPage(direction, gesture) {
  if (!gesture || gesture.spent || gesture.ended || !canonicalReady() ||
      gesture.page !== page || gesture.token !== generation || gesture.version !== revision) return false;
  const master = $("masterScroll"),
    maximum = Math.max(0, master.scrollHeight - master.clientHeight);
  const atEdge = direction > 0 ? master.scrollTop >= maximum - 1 : direction < 0 && master.scrollTop <= 1;
  if (!atEdge) return false;
  const next = page + Math.sign(direction);
  if (next < 0 || next >= analysis.contract.manifest.pages.length) return false;
  gesture.spent = true;
  switchPage(next, direction > 0 ? "top" : "bottom");
  return true;
}

/**
 * @brief Applica uno scorrimento richiesto dall'utente e valuta il cambio pagina.
 * @param {number} value Posizione logica di destinazione.
 * @param {number} direction Verso dello scorrimento.
 * @param {Object} gesture Gesto in corso.
 * @returns {boolean} Vero se la pagina è stata cambiata.
 */
function scrollByUser(value, direction, gesture) {
  if (!gesture || !canonicalReady() || gesture.page !== page ||
      gesture.token !== generation || gesture.version !== revision) return false;
  setMasterScroll(value);
  return maybeTurnPage(direction, gesture);
}

/**
 * @brief Gestisce i tasti di scorrimento (frecce, pagina su/giù, inizio, fine).
 * @param {KeyboardEvent} event Evento tastiera.
 */
function scrollKey(event) {
  const master = $("masterScroll");
  const amount = {ArrowDown: 40, ArrowUp: -40, PageDown: 250, PageUp: -250}[event.key];
  if (!amount && event.key !== "Home" && event.key !== "End") return;
  event.preventDefault();
  const direction = amount ? Math.sign(amount) : event.key === "Home" ? -1 : 1;
  const target = amount ? master.scrollTop + amount : direction < 0 ? 0 : master.scrollHeight;
  scrollByUser(target, direction, beginScrollGesture(`key:${event.key}`, !event.repeat));
}

/**
 * @brief Svuota testo, ancore e scorrimento della vista condivisa.
 */
function clearSharedView() {
  cancelEdgeNavigation();
  previewLines = [];
  displayedText = {
    original: "",
    redacted: ""
  };
  scrollAnchors = [];
  sharedSourceTop = sharedPanX = 0;
  setMasterScroll(0);
  $("scrollExtent").style.height = "0px";
  $("horizontalPan").hidden = true;
  $("horizontalPan").scrollLeft = 0;
  for (const id of ["textOriginal", "textRedacted"]) $(id).replaceChildren();
}

/**
 * @brief Mostra il testo della pagina come righe ordinate per posizione verticale.
 *
 * Le righe senza coordinate sono marcate come non verificabili.
 * @param {Object} text Testo originale, oscurato e righe con i relativi limiti.
 */
function showGeometricText(text) {
  displayedText = {
    original: text.original,
    redacted: text.redacted
  };
  previewLines = text.lines || [{
    original: "Riavvia l'applicazione per l'allineamento geometrico.\n" + text.original,
    redacted: "Riavvia l'applicazione per l'allineamento geometrico.\n" + text.redacted,
    bounds: null,
    unlocalized: true
  }];
  previewLines = previewLines.map((line, order) => ({
    ...line,
    order
  })).sort((a, b) =>
    (a.bounds?.[1] ?? Infinity) - (b.bounds?.[1] ?? Infinity) || a.order - b.order);
  for (const [id, kind] of [
      ["textOriginal", "original"],
      ["textRedacted", "redacted"]
    ]) {
    const content = node("div");
    content.className = "text-lines";
    previewLines.forEach((line, index) => {
      const row = node("div", line[kind]);
      row.className = "text-line";
      row.dataset.line = String(index);
      if (line.unlocalized) {
        row.classList.add("unlocalized-line");
        row.title = "Contiene testo senza coordinate: posizione non verificabile.";
      }
      content.append(row);
    });
    $(id).replaceChildren(content);
  }
  requestAnimationFrame(() => layoutSharedView(sharedSourceTop));
}

/**
 * @brief Calcola scala, dimensioni e ancore che allineano testo e immagini.
 * @param {number} [sourceTop] Posizione verticale in coordinate pagina da mantenere.
 */
function layoutSharedView(sourceTop = sharedSourceTop) {
  if (!analysis || !$("original").getAttribute("src")) return;
  cancelScrollIntent();
  const g = pageData().geometry;
  const headings = Array.from($("comparison").querySelectorAll(".document-panel > h2, .inline-text-panel > h2"));
  headings.forEach(heading => heading.style.height = "auto");
  const headingHeight = Math.max(...headings.map(heading => heading.offsetHeight));
  headings.forEach(heading => heading.style.height = `${headingHeight}px`);
  const views = Array.from(document.querySelectorAll(".document-panel .viewport"));
  const width = Math.min(...views.map(view => view.clientWidth));
  if (!width) return;
  sharedScale = width / g.width * sharedZoom;
  const horizontal = $("horizontalPan"),
    container = $("comparison").getBoundingClientRect();
  const left = views[0].getBoundingClientRect(),
    right = views[1].getBoundingClientRect();
  horizontal.hidden = sharedZoom <= 1;
  horizontal.style.left = `${left.left - container.left}px`;
  horizontal.style.top = `${left.bottom - container.top}px`;
  horizontal.style.width = `${right.right - left.left}px`;
  $("horizontalExtent").style.width = `${horizontal.clientWidth + Math.max(0, g.width * sharedScale - views[0].clientWidth)}px`;
  for (const id of ["originalFrame", "redactedFrame"]) {
    $(id).style.width = `${g.width * sharedScale}px`;
    $(id).style.height = `${g.height * sharedScale}px`;
  }
  scrollAnchors = [{
    logical: 0,
    source: 0
  }];
  let bottom = 0;
  const originals = $("textOriginal").querySelectorAll(".text-line");
  const redacted = $("textRedacted").querySelectorAll(".text-line");
  if (originals.length !== previewLines.length || redacted.length !== previewLines.length) return;
  const hasGeometry = previewLines.some(line => line.bounds);
  previewLines.forEach((line, index) => {
    const source = line.bounds?.[1] ?? (hasGeometry ? g.height : 0);
    const top = Math.max(source * sharedScale, bottom);
    const height = Math.max(originals[index].offsetHeight, redacted[index].offsetHeight, 20);
    originals[index].style.top = redacted[index].style.top = `${top}px`;
    line.logical = top;
    scrollAnchors.push({
      logical: top,
      source
    });
    bottom = top + height + 8;
  });
  const visible = Math.min($("textOriginal").clientHeight, $("textRedacted").clientHeight,
    ...views.map(view => view.clientHeight));
  const total = Math.max(g.height * sharedScale, bottom) + Math.max(0, $("masterScroll").clientHeight - visible);
  scrollAnchors.push({
    logical: total,
    source: g.height
  });
  $("scrollExtent").style.height = `${total}px`;
  let target = mapScroll(sourceTop, "source", "logical");
  if (scrollPageEntry && scrollPageEntry.page === page && scrollPageEntry.token === generation &&
      scrollPageEntry.version === revision && previewPage === page && previewRevision === revision) {
    target = scrollPageEntry.edge === "bottom" ? $("masterScroll").scrollHeight : 0;
    scrollPageEntry = null;
  }
  setMasterScroll(target);
  $("zoom").textContent = `${Math.round(sharedZoom * 100)}%`;
  syncSharedScroll();
}

/**
 * @brief Allinea immagini, testo e barra orizzontale alla posizione di scorrimento.
 */
function syncSharedScroll() {
  if (!analysis || !scrollAnchors.length) return;
  const g = pageData().geometry,
    top = $("masterScroll").scrollTop;
  sharedSourceTop = mapScroll(top, "logical", "source");
  const view = $("originalFrame").parentElement;
  sharedPanX = Math.max(0, Math.min(sharedPanX, g.width - view.clientWidth / sharedScale));
  if (Math.abs($("horizontalPan").scrollLeft - sharedPanX * sharedScale) > .5) {
    $("horizontalPan").scrollLeft = sharedPanX * sharedScale;
  }
  for (const id of ["originalFrame", "redactedFrame"]) {
    $(id).style.transform = `translate(${-sharedPanX * sharedScale}px, ${-sharedSourceTop * sharedScale}px)`;
  }
  for (const id of ["textOriginal", "textRedacted"]) {
    const content = $(id).querySelector(".text-lines");
    if (content) content.style.transform = `translateY(${-top}px)`;
  }
  $("masterScroll").dataset.sourceY = String(sharedSourceTop);
}

/**
 * @brief Cambia lo zoom condiviso mantenendo fermo il punto sotto il puntatore.
 * @param {number} value Nuovo fattore di zoom, limitato tra 1 e 5.
 * @param {WheelEvent|null} [event] Evento che fornisce il punto di riferimento.
 */
function changeZoom(value, event = null) {
  if (!analysis) return;
  cancelEdgeNavigation();
  cancelGesture();
  const viewport = (event?.target.closest(".document-panel") || $("originalFrame").closest(".document-panel")).querySelector(".viewport");
  const rect = viewport.getBoundingClientRect();
  const overDocument = event?.target.closest(".document-panel");
  const y = overDocument ? Math.max(0, Math.min(viewport.clientHeight, event.clientY - rect.top)) : viewport.clientHeight / 2;
  const x = overDocument ? Math.max(0, Math.min(viewport.clientWidth, event.clientX - rect.left)) : viewport.clientWidth / 2;
  const sourceY = sharedSourceTop + y / sharedScale;
  const sourceX = sharedPanX + x / sharedScale;
  sharedZoom = Math.max(1, Math.min(5, value));
  updatePanCursor();
  layoutSharedView();
  sharedPanX = sourceX - x / sharedScale;
  setMasterScroll(mapScroll(Math.max(0, sourceY - y / sharedScale), "source", "logical"));
  syncSharedScroll();
}

/**
 * @brief Sincronizza i pannelli e registra il verso dello scorrimento da barra nativa.
 */
$("masterScroll").onscroll = () => {
  const top = $("masterScroll").scrollTop;
  if (nativeBarGesture && top !== lastMasterTop) {
    nativeBarGesture.direction = Math.sign(top - lastMasterTop);
    nativeBarGesture.moved = true;
  }
  lastMasterTop = top;
  syncSharedScroll();
};
/**
 * @brief Avvia un gesto di scorrimento con la barra nativa.
 */
$("masterScroll").onpointerdown = event => {
  if (event.button !== 0 || !canonicalReady()) return;
  nativeBarGesture = {pointerId: event.pointerId, direction: 0, moved: false,
    gesture: beginScrollGesture(`bar:${event.pointerId}`, true)};
};
/**
 * @brief Conclude il gesto sulla barra nativa e valuta il cambio pagina.
 * @param {PointerEvent} event Evento di rilascio o annullamento del puntatore.
 */
function finishNativeScroll(event) {
  const state = nativeBarGesture;
  if (!state || state.pointerId !== event.pointerId) return;
  if (event.type === "pointercancel") {
    nativeBarGesture = null;
    endScrollGesture(state.gesture);
    return;
  }
  requestAnimationFrame(() => {
    if (nativeBarGesture !== state) return;
    const top = $("masterScroll").scrollTop;
    if (top !== lastMasterTop) {
      state.direction = Math.sign(top - lastMasterTop);
      state.moved = true;
      lastMasterTop = top;
    }
    nativeBarGesture = null;
    if (state.moved) maybeTurnPage(state.direction, state.gesture);
    endScrollGesture(state.gesture);
  });
}
document.addEventListener("pointerup", finishNativeScroll, true);
document.addEventListener("pointercancel", finishNativeScroll, true);
$("masterScroll").onkeydown = scrollKey;
document.addEventListener("keyup", event => {
  if (edgeGesture?.kind === `key:${event.key}`) endScrollGesture(edgeGesture);
});
/**
 * @brief Applica lo spostamento orizzontale dalla barra dedicata.
 */
$("horizontalPan").onscroll = () => {
  const value = $("horizontalPan").scrollLeft / sharedScale;
  if (Math.abs(value - sharedPanX) * sharedScale <= .5) return;
  sharedPanX = value;
  syncSharedScroll();
};
/**
 * @brief Gestisce la rotella: zoom con Ctrl, altrimenti scorrimento e spostamento.
 */
$("comparison").addEventListener("wheel", event => {
  if (!analysis) return;
  event.preventDefault();
  if (event.ctrlKey) changeZoom(sharedZoom * Math.exp(-event.deltaY * .002), event);
  else {
    const unit = event.deltaMode === 1 ? 20 : event.deltaMode === 2 ? $("masterScroll").clientHeight : 1;
    if (event.shiftKey || event.target.closest("#horizontalPan")) {
      sharedPanX += event.deltaY * unit / sharedScale;
    } else if (event.deltaY && scrollByUser($("masterScroll").scrollTop + event.deltaY * unit,
        Math.sign(event.deltaY), beginScrollGesture("wheel"))) return;
    sharedPanX += event.deltaX * unit / sharedScale;
    syncSharedScroll();
  }
}, {
  passive: false
});
/**
 * @brief Collega lo scorrimento tattile e da tastiera ai pannelli di testo.
 */
for (const id of ["textOriginal", "textRedacted"]) {
  let touch = null;
  $(id).addEventListener("touchstart", event => {
    touch = {
      y: event.touches[0].clientY,
      top: $("masterScroll").scrollTop,
      gesture: beginScrollGesture("touch", true)
    };
  }, {
    passive: true
  });
  $(id).addEventListener("touchmove", event => {
    if (!touch) return;
    event.preventDefault();
    const target = touch.top + touch.y - event.touches[0].clientY;
    scrollByUser(target, Math.sign(target - $("masterScroll").scrollTop), touch.gesture);
  }, {
    passive: false
  });
  $(id).addEventListener("touchend", () => {
    endScrollGesture(touch?.gesture);
    touch = null;
  });
  $(id).addEventListener("touchcancel", () => {
    endScrollGesture(touch?.gesture);
    touch = null;
  });
  $(id).onkeydown = scrollKey;
}
/**
 * @brief Ricalcola la vista condivisa quando cambia la dimensione del confronto.
 */
new ResizeObserver(() => layoutSharedView()).observe($("comparison"));
/**
 * @brief Collega i gesti puntatore alle due sovrapposizioni SVG.
 */
for (const id of ["overlay", "redactedOverlay"]) {
  const svg = $(id);
  /**
   * @brief Inizia un gesto memorizzando lo stato da cui è partito.
   */
  svg.onpointerdown = event => {
    if (!canonicalReady() || event.button !== 0 || drawing) return;
    drawing = {
      svg,
      pointerId: event.pointerId,
      version: revision,
      tool,
      panned: false,
      point: pointerPoint(event, svg),
      x: event.clientX,
      y: event.clientY,
      lastY: event.clientY,
      page,
      token: generation,
      scrollX: sharedPanX,
      sourceTop: sharedSourceTop,
      scrollGesture: beginScrollGesture(`pan:${event.pointerId}`, true)
    };
    svg.setPointerCapture(event.pointerId);
  };
  /**
   * @brief Sposta la vista o aggiorna il rettangolo in bozza durante il trascinamento.
   *
   * Il gesto viene annullato se nel frattempo cambiano pagina, revisione o strumento.
   */
  svg.onpointermove = event => {
    if (!drawing || drawing.svg !== svg || drawing.pointerId !== event.pointerId) return;
    if (!canonicalReady() || drawing.page !== page || drawing.token !== generation || drawing.version !== revision || drawing.tool !== tool) {
      cancelGesture();
      return;
    }
    const distance = Math.hypot(event.clientX - drawing.x, event.clientY - drawing.y);
    const canPan = tool === "pan" || (tool === "click" && (sharedZoom > 1 || event.pointerType === "touch"));
    if (canPan && (drawing.panned || tool === "pan" || distance >= 5)) {
      drawing.panned = true;
      updatePanCursor();
      sharedPanX = drawing.scrollX + (drawing.x - event.clientX) / sharedScale;
      const direction = Math.sign(drawing.lastY - event.clientY);
      drawing.lastY = event.clientY;
      if (direction) {
        const target = mapScroll(Math.max(0, drawing.sourceTop + (drawing.y - event.clientY) / sharedScale), "source", "logical");
        scrollByUser(target, direction, drawing.scrollGesture);
      }
      syncSharedScroll();
    }
    if (tool !== "draw") return;
    const end = pointerPoint(event, svg),
      start = drawing.point;
    svg.querySelector(".draft")?.remove();
    svg.append(svgElement("rect", {
      x: Math.min(start[0], end[0]),
      y: Math.min(start[1], end[1]),
      width: Math.abs(start[0] - end[0]),
      height: Math.abs(start[1] - end[1]),
      class: "draft"
    }));
  };
  /**
   * @brief Annulla il gesto se riguarda questa sovrapposizione e questo puntatore.
   * @param {PointerEvent} event Evento puntatore.
   */
  const cancelPointer = event => {
    if (drawing?.svg === svg && drawing.pointerId === event.pointerId) cancelGesture();
  };
  svg.onpointercancel = cancelPointer;
  svg.onlostpointercapture = cancelPointer;
  /**
   * @brief Conclude il gesto come clic o come rettangolo disegnato.
   */
  svg.onpointerup = event => {
    if (!drawing || drawing.svg !== svg || drawing.pointerId !== event.pointerId) return;
    const start = drawing,
      end = pointerPoint(event, svg);
    cancelGesture();
    if (!canonicalReady() || start.page !== page || start.token !== generation || start.version !== revision || start.tool !== tool || tool === "pan" || start.panned) return;
    const distance = Math.hypot(event.clientX - start.x, event.clientY - start.y);
    if (tool === "click") {
      if (distance < 5) clickPoint(end);
      return;
    }
    if (distance < 5) {
      message("Trascina per almeno 5 pixel per disegnare un’area.");
      return;
    }
    addRectangle([Math.min(start.point[0], end[0]), Math.min(start.point[1], end[1]), Math.max(start.point[0], end[0]), Math.max(start.point[1], end[1])]);
  };
}

/**
 * @brief Passa a un'altra pagina e ne richiede l'anteprima.
 * @param {number} index Indice della pagina.
 * @param {string|null} [edge] Bordo da mostrare all'arrivo ("top" o "bottom").
 */
function switchPage(index, edge = null) {
  if (!analysis || index < 0 || index >= analysis.contract.manifest.pages.length) return;
  cancelEdgeNavigation();
  cancelGesture();
  previewError = null;
  previewNeedsAnalysis = false;
  page = index;
  $("page").value = String(page);
  previewPage = -1;
  $("original").removeAttribute("src");
  $("redacted").removeAttribute("src");
  clearSharedView();
  if (edge) scrollPageEntry = {page, token: generation, version: revision, edge};
  pending = true;
  renderPageControls();
  void refresh();
}

/**
 * @brief Ripristina uno stato salvato spostando quello corrente nella pila opposta.
 * @param {Object[]} from Pila da cui prelevare lo stato.
 * @param {Object[]} to Pila in cui salvare lo stato corrente.
 */
function restore(from, to) {
  if (!from.length || !analysis) return;
  cancelGesture();
  const state = from.pop();
  const changesPage = state.page !== page;
  to.push(snapshot(state.page));
  const data = analysis.contract.manifest.pages[state.page],
    id = data.page.page_id;
  for (const mask of data.redactions) delete review.decisions[mask.id];
  Object.assign(review.decisions, state.decisions);
  review.acknowledgments[id] = state.acknowledgments;
  review.manual_masks = review.manual_masks.filter(mask => mask.page_id !== id).concat(state.manual_masks);
  page = state.page;
  if (changesPage) {
    for (const id of ["original", "redacted"]) $(id).removeAttribute("src");
    clearSharedView();
  }
  $("page").value = String(page);
  previewPage = -1;
  invalidate();
  renderPageControls();
}
/**
 * @brief Comandi di annullamento, ripristino, nuova anteprima e rianalisi.
 */
$("undo").onclick = () => restore(history, future);
$("redo").onclick = () => restore(future, history);
$("retryPreview").onclick = () => {
  if (!analysis || running) return;
  pending = true;
  void refresh();
};
$("repeatAnalysis").onclick = () => $("analyze").click();
/**
 * @brief Pulsanti di selezione dello strumento.
 */
$("toolClick").onclick = () => setTool("click");
$("toolDraw").onclick = () => setTool("draw");
$("toolPan").onclick = () => setTool("pan");
/**
 * @brief Apre le note di lettura e porta il fuoco sulla prima area da completare.
 */
$("geometryBadge").onclick = () => {
  $("reviewDetails").open = true;
  $("warningSummary").scrollIntoView({
    block: "nearest"
  });
  $("exceptions").querySelector("button")?.focus();
};
/**
 * @brief Chiude il pannello delle note di lettura con Esc.
 */
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && $("reviewDetails").open) {
    $("reviewDetails").open = false;
    $("warningSummary").focus();
  }
});
/**
 * @brief Navigazione tra le pagine e comandi di zoom.
 */
$("page").onchange = () => switchPage(Number($("page").value));
$("prevPage").onclick = () => switchPage(page - 1);
$("nextPage").onclick = () => switchPage(page + 1);
$("zoomIn").onclick = () => changeZoom(sharedZoom * 1.25);
$("zoomOut").onclick = () => changeZoom(sharedZoom / 1.25);
$("zoomFit").onclick = () => changeZoom(1);
/**
 * @brief Aggiunta di file da selettore, tastiera e trascinamento.
 */
$("files").onchange = () => updateFiles(files.concat(Array.from($("files").files)));
$("dropzone").onkeydown = event => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    $("files").click();
  }
};
$("dropzone").ondragover = event => {
  event.preventDefault();
  $("dropzone").classList.add("dragover");
};
$("dropzone").ondragleave = () => $("dropzone").classList.remove("dragover");
$("dropzone").ondrop = event => {
  event.preventDefault();
  $("dropzone").classList.remove("dragover");
  updateFiles(files.concat(Array.from(event.dataTransfer.files)));
};
/**
 * @brief Svuota la sessione.
 */
$("clear").onclick = () => {
  updateFiles([]);
  message("Sessione svuotata.");
};
/**
 * @brief Il cambio di qualità PDF invalida l'analisi corrente.
 */
$("dpi").onchange = () => {
  reset();
  message("Qualità modificata: ripeti l’analisi.");
};
/**
 * @brief Avvia l'analisi dei documenti e prepara una nuova revisione.
 */
$("analyze").onclick = async () => {
  if (!files.length || analyzing) return;
  reset();
  analyzing = true;
  controls();
  const token = generation,
    data = form();
  let failed = false;
  data.append("dpi", $("dpi").value);
  message("Analisi documento: lettura OCR e ricerca dei dati personali.");
  $("message").scrollIntoView({
    block: "nearest"
  });
  try {
    const result = await (await request("analyze", data, () => token === generation)).json();
    if (token !== generation) return;
    analysis = result;
    review = {
      decisions: {},
      acknowledgments: {},
      manual_masks: [],
      final_confirmation: false
    };
    page = 0;
    $("page").replaceChildren();
    result.contract.manifest.pages.forEach((_, index) => $("page").add(new Option(`Pagina ${index + 1}`, index)));
    $("format").querySelector('[value="png"]').disabled = result.contract.manifest.pages.length !== 1;
    $("landing").hidden = true;
    $("workspace").hidden = false;
    timing(result.timings);
    analyzing = false;
    renderPageControls();
    pending = true;
    await refresh();
  } catch (error) {
    if (token === generation) {
      failed = true;
      message(error.code ? error.message : "Analisi non riuscita. Controlla il servizio locale e riprova.");
    }
  } finally {
    if (token === generation) analyzing = false;
    controls();
    if (failed && token === generation) $("message").scrollIntoView({
      block: "nearest"
    });
  }
};

/**
 * @brief Cerca la prima area senza geometria non coperta da una maschera collegata.
 * @returns {Object|null} Pagina e candidato da completare, o null.
 */
function incompleteGeometry() {
  for (const [index, item] of analysis.contract.manifest.pages.entries()) {
    for (const warning of item.warnings.filter(w => w.code === "candidate_geometry_incomplete")) {
      for (const candidate of warning.candidate_ids) {
        if (!review.manual_masks.some(mask => mask.page_id === item.page.page_id && mask.candidate_ids.includes(candidate))) return {
          page: index,
          candidate
        };
      }
    }
  }
  return null;
}

/**
 * @brief Gestisce la conferma finale dell'intero documento.
 *
 * Se mancano aree da completare porta l'utente alla pagina interessata; altrimenti
 * conferma decisioni, maschere e note di lettura e richiede una nuova anteprima.
 */
$("final").onchange = () => {
  if (!$("final").checked) {
    review.final_confirmation = false;
    controls();
    return;
  }
  if (!canonicalReady()) {
    $("final").checked = false;
    review.final_confirmation = false;
    controls();
    return;
  }
  const issue = incompleteGeometry();
  if (issue) {
    $("final").checked = false;
    review.final_confirmation = false;
    focusGeometry = issue;
    message(`Completa prima l'area senza geometria nella pagina ${issue.page + 1}. Disegna un rettangolo collegato prima di confermare il documento.`);
    if (page === issue.page) controls();
    else switchPage(issue.page);
    return;
  }
  for (const item of analysis.contract.manifest.pages) {
    for (const mask of item.redactions) {
      review.decisions[mask.id] = {
        decision: "apply",
        reason: "",
        ...review.decisions[mask.id],
        confirmed: true
      };
    }
    review.acknowledgments[item.page.page_id] = item.warnings.map((_, index) => index);
  }
  for (const mask of review.manual_masks) mask.confirmed = true;
  invalidate(true);
};

/**
 * @brief Avvia il download di un Blob con il nome indicato.
 * @param {Blob} blob Contenuto da scaricare.
 * @param {string} filename Nome del file proposto.
 */
function download(blob, filename) {
  const url = URL.createObjectURL(blob),
    link = node("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
/**
 * @brief Esporta la copia oscurata nel formato scelto.
 */
$("export").onclick = async () => {
  if ($("export").disabled) return;
  exporting = true;
  controls();
  const token = generation,
    version = revision,
    format = $("format").value,
    data = form();
  data.append("format", format === "zip" ? "pdf" : format);
  data.append("include_text", String(format === "zip"));
  message("Esportazione in corso…");
  try {
    const response = await request("export", data, () => token === generation && version === revision);
    const blob = await response.blob();
    if (token !== generation || version !== revision) return;
    download(blob, `documento-oscurato.${format}`);
    timing({
      ...JSON.parse(response.headers.get("X-Phase-Timings") || "{}"),
      export: Number(response.headers.get("X-Export-Seconds"))
    });
    message("Copia oscurata esportata. Gli originali non sono stati modificati.");
  } catch (error) {
    if (token === generation) message(error.message);
  } finally {
    exporting = false;
    controls();
  }
};
/**
 * @brief Copia negli appunti il testo originale della pagina, non oscurato.
 */
$("copyOriginal").onclick = async () => {
  try {
    await navigator.clipboard.writeText(displayedText.original);
    message("Testo ORIGINALE della pagina copiato: contiene dati non oscurati.");
  } catch {
    message("Copia non disponibile: seleziona il testo originale nel pannello.");
  }
};
/**
 * @brief Scarica il testo originale della pagina, non oscurato.
 */
$("downloadOriginal").onclick = () => {
  download(new Blob([displayedText.original], {
    type: "text/plain;charset=utf-8"
  }), `testo-ORIGINALE-pagina-${page + 1}.txt`);
  message("Scaricato il testo ORIGINALE della pagina, con dati non oscurati.");
};
/**
 * @brief Copia negli appunti il testo oscurato completo prodotto dal server.
 */
$("copyRedacted").onclick = async () => {
  if ($("copyRedacted").disabled) return;
  const token = generation,
    version = revision,
    data = form();
  exporting = true;
  controls();
  try {
    const text = await (await request("text-export", data, () => token === generation && version === revision)).text();
    if (token !== generation || version !== revision) return;
    await navigator.clipboard.writeText(text);
    message("Testo oscurato completo copiato. Esporta anche la copia visiva per verificare il documento condiviso.");
  } catch (error) {
    if (token === generation) message(error.message);
  } finally {
    exporting = false;
    controls();
  }
};
/**
 * @brief Legge lo stato del servizio locale e mostra dove avviene l'elaborazione.
 */
fetch("/api/health").then(response => response.json()).then(health => {
  const location = health.execution_location === "this_computer" ? "questo computer" : health.execution_location;
  const executionLabel = location ? `Elaborazione su ${location}` : "Elaborazione documenti";
  $("executionBadge").textContent = executionLabel;
  $("executionEyebrow").textContent = location ? `I documenti vengono elaborati su ${location}` : "Revisione dei documenti";
  $("executionFooter").textContent = executionLabel;
  $("health").textContent = `${executionLabel} · NER: ${{ disabled: "disabilitato", ready: "pronto", failed: "errore" }[health.ner]} · OCR: ${{ unavailable: "non disponibile", ready: "italiano disponibile", failed: "errore" }[health.ocr]} · Avvio: ${health.startup_seconds.toFixed(2)} s`;
}).catch(() => message("Servizio locale non disponibile."));
controls();
