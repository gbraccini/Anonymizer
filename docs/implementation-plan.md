# Anonymizer — piano 1: core, revisione e backend web

Data: 2026-11-02. Revisione: 2026-11-03, dopo una prima valutazione.
Stato: implementazione avviata il 2026-11-03. Advisor: orchestratore; scrivente:
Sol 6.1; ambiente, download, build e test: Luna. Primo blocco testuale verificato:
93 test, lint e build riusciti. Secondo blocco visuale/CLI verificato:
142 test, OCR reale, lint e build riusciti. Terzo blocco NER locale verificato:
166 test con OCR/NER reali, lint e build riusciti; valutazione sintetica separata.
Quarto blocco locale con GUI condivisa verificato: 176 test, percorso browser,
confronti pixel PNG/PDF e pacchetto con asset UI. Standalone installabile ancora da creare.
Ottimizzazione successiva: 208 test con OCR e runtime NER Torch/ONNX reali;
backend ONNX FP32 opzionale, compattazione delle maschere a pixel invariati.
Percorso PDF ibrido disponibile soltanto con opt-in nel core; non attivo nella GUI.
Checklist di prodotto ancora in corso; soglie operative da validare con le misure.

**Obiettivo:** produrre una copia oscurata di ogni immagine/PDF caricato, conservando il contenuto clinico e consentendo revisione nel browser. Il testo pseudonimizzato e la mappa sono output aggiuntivi quando utili. Radiografie, OCT e altri esami visuali devono restare immagini utilizzabili, non essere ridotti al solo OCR.

**Estensione approvata il 2026-11-03 durante l'avvio:** oscuramento visuale obbligatorio anche quando si esporta il TXT. Prima fase su immagini e PDF esportati; DICOM originali esclusi per scelta esplicita. Il core testuale già avviato resta riutilizzabile ma non soddisfa da solo il nuovo risultato richiesto.

**Architettura:** core Python indipendente dall'interfaccia; ingest → estrazione/OCR → detect → merge → proposte testuali e geometriche → revisione client → export visuale, con TXT opzionale. Nessun modello generativo riscrive testo o ricostruisce pixel clinici. L'OCR lavora su una copia di analisi; l'oscuramento usa le coordinate del documento originale.

**Stack di partenza:** Python 3.12, pypdfium2, Pillow + pi-heif, OpenCV headless, pytesseract + Tesseract italiano, rapidfuzz, FastAPI, uvicorn, python-multipart, typer; pytest, httpx, Faker e ruff per sviluppo. Prototipo frontend con Jinja2 e JavaScript; scelta definitiva dopo la prova di revisione su PC e telefono. Modello NER da confrontare presto.

**Specifica:** docs/design.md.

## Decisioni e vincoli

### Evidenze del primo blocco — 2026-11-03

Moduli testuali presenti: modello, CF, L0/L1/L2, merge, pseudonymize, mapstore,
reassoc, text_pipeline e CLI .txt. Fixture: 20 documenti testuali sintetici annotati
e contratto JSON di revisione. Luna ha verificato 93 test, Ruff pulito, build wheel,
installazione isolata con dati inclusi, esempio README e roundtrip byte per byte
LF/CRLF/CR. Inoltre 300 casi generati di merge con 21.328 candidati hanno mantenuto
copertura e provenienza. Dettagli in docs/validation.md e report locali ignorati.

Le checklist sotto restano criteri di completamento dell'intero piano: non sono
tutte soddisfatte dalla presenza dei moduli. Vocabolario solo sintetico, matching
OCR deterministico (non ancora fuzzy generale), un valore canonico per tipo e
identità, nessuna validazione su referti reali. Alla chiusura del primo blocco
OCR, API/JWT, revisione web, NER e oscuramento visuale erano ancora da implementare.

### Secondo blocco — motore visuale e CLI

Implementati ingest, geometrie, estrazione PDF nativa conservativa/OCR, maschere,
manifesto di revisione ed export PNG/PDF raster. La CLI analyze produce il manifesto;
export richiede gli stessi originali e decisioni confermate. Ogni regione proposta
deve ricevere una decisione, anche se più regioni appartengono allo stesso candidato.
Impronte di sorgente, geometria e revisione intercettano file sostituiti e modifiche
accidentali; non costituiscono autenticazione né prova di revisione umana.

Variazione tecnica emersa dal test reale Windows: l'OCR invoca Tesseract direttamente
con una lista di argomenti e TSV, evitando il difetto di quoting tessdata del wrapper
pytesseract. Timeout e temporanei con pulizia ordinaria restano previsti. Nessun
obbligo di elaborazione solo in memoria è stato introdotto. Export PDF tramite
ReportLab; verifica strutturale indipendente con pypdf.

Restano parziali Task 9 (solo orientamento, niente deskew/prospettiva), Task 10C
(nessun rilevatore automatico QR/firme, maschere manuali disponibili) e Task 11
(TXT documentale aggiuntivo rinviato alla sincronizzazione con tutte le decisioni
visuali; bench e interfaccia anagrafica CLI non completi). API/JWT, revisione web,
NER e validazione clinica non fanno parte del risultato di questo blocco.
Il primo traguardo di prodotto con revisione grafica rimane aperto.

Collaudo Luna: 142 test passati, Ruff pulito, wheel installata separatamente;
Tesseract italiano locale, PNG/PDF scansione end-to-end, rotazioni/crop PDF e
controlli indipendenti di pixel e contenuti nascosti. L'esame simulato ha anche
documentato un nome mancato dal rilevatore e corretto con maschera manuale.
Nessuna misura di recall clinico dedotta dalla suite. Dettagli in docs/validation.md.

### Terzo blocco — NER locale e misure

GLiNER multi-v2.1 è integrato come livello L3 opzionale, con artefatti locali
verificati, budget di token rispettati e audit vincolato alla revisione.
Confronto con baseline su 22 documenti di sviluppo e 22 di valutazione separata,
senza anagrafica nota. Dopo la protezione circoscritta VAS/NRS, lo sviluppo copre
32/32 identificativi senza alterare i segmenti clinici annotati.
La valutazione copre 33/33 identificativi ma oscura erroneamente "Romberg";
nessuna modifica successiva per migliorare quel risultato. Sul campione OCT il
nome prima mancato è ora rilevato, con falso positivo sulla parola "Paziente".

Mediana NER 0,235 s/documento, p95 2,154 s, inizializzazione 9,409 s e picco
2,68 GiB, CPU con quattro thread; OCR/export esclusi. Non sono misure di qualità
su referti reali né una prova sull'hardware 4 vCPU/8 GB. Modello scelto per il
prototipo assistito; UI, health API, carico e validazione clinica restano aperti.
Evidenze in docs/ner-evaluation.md e docs/validation.md.

### Quarto blocco approvato — prototipo locale di revisione

Implementato e collaudato il 2026-11-03 : interfaccia browser con
caricamento immagini/PDF, pagine e zoom, originale/anteprima affiancati, decisioni
sulle proposte, maschere rettangolari manuali e download PNG/PDF dopo revisione.
Raccogliere tempi delle fasi e caricare il modello una sola volta all'avvio.
Sol 6.1 implementa; Luna verifica ambiente, percorso completo e pacchetto;
l'advisor controlla contratti, comportamento e documentazione.

Il perimetro è locale ed esplicito, con ascolto loopback e controlli Host/Origin.
JWT e accesso condiviso appartengono al blocco successivo. Nessun archivio server
dei documenti fra richieste: il browser mantiene gli originali e li reinvia per
anteprima canonica ed export. Questa anteprima server estende la precedente
previsione di reinvio soltanto all'export e riusa lo stesso renderer finale.
Il contratto iniziale deve essere protetto contro modifiche client a geometrie,
avvisi e proposte obbligatorie; le sole modifiche consentite sono le decisioni
di revisione e l'aggiunta/rimozione delle maschere manuali. Qualsiasi modifica
invalida la conferma precedente. Nessun contenuto non fidato interpretato come HTML.

Criteri di chiusura del blocco: prova browser del percorso completo, controllo
indipendente PNG/PDF, rifiuto di originali sostituiti e revisione alterata,
stato NER visibile, misure OCR/NER/rendering/export e pacchetto con risorse UI.
OCR testuale modificabile, riordino/esclusione pagine, TXT documentale, identità
anagrafica, DICOM e validazione clinica restano fuori da questo primo prototipo.

Evidenze: 176 test passati con OCR/NER reali, Ruff pulito, wheel/sdist costruite
e asset UI verificati nell'installazione separata. Browser Edge, viewport desktop
e telefono, rifiuto motivato, disegno manuale, conferma invalidata dopo modifica,
download PDF. PNG e bitmap incorporate nei PDF identici alle anteprime canoniche
dei campioni, zero modifiche fuori maschera. Tempi e limiti in docs/validation.md;
report locale build/artifacts/web-verification.json. Il prototipo soddisfa il
percorso visuale locale; il traguardo condiviso completo e la standalone richiedono
ancora i rispettivi blocchi di autenticazione e confezionamento.

### Vincoli applicabili al prodotto

- **Anagrafica locale opzionale, requisito richiamato il 2026-11-03:**
  il prototipo GUI consegnato non la integra ancora. Completare il passaggio dei
  dati noti alla GUI/API e un adattatore locale di sola lettura prima di considerare
  completa la standalone. Verificare il canale effettivamente disponibile nel gestionale destinatario; non assumere equivalenza con altri servizi.
  Fonte assente e fonte guasta devono essere distinguibili, con inserimento manuale
  o modalità senza anagrafica disponibili. Un'unica GUI per tutte queste modalità.

- **GUI condivisa web/standalone, richiesta ribadita il 2026-11-03:** mantenere
  un'unica interfaccia HTML/CSS/JavaScript e gli stessi contratti del motore Python.
  La futura app desktop riutilizza questi asset in una finestra dedicata; nessuna
  seconda implementazione dei componenti di revisione, delle maschere o dei flussi.
  Il contenitore desktop gestisce avvio/arresto del servizio locale, porta/sessione,
  percorsi e risorse distribuite. Eventuali funzioni native vanno isolate in un
  adattatore minimo. OCR, NER ed export restano nel motore comune. Scegliere il
  contenitore e il packaging dopo il primo collaudo della GUI condivisa; per la
  standalone verificare anche installazione su macchina pulita, risorse OCR/modello,
  funzionamento offline e chiusura senza processi residui. L'attuale launcher locale
  non equivale ancora a un'app standalone distribuita.

- **Prototipo Windows portabile, 2026-11-03:** realizzati launcher `Anonymizer.exe`,
  runtime CPython distribuito, finestra pywebview/WebView2 e bundle OCR/NER offline.
  GUI e core restano condivisi; servizio desktop su porta dinamica separata da 8765,
  chiusura dei processi tramite segnale privato e Windows Job Object. Il pacchetto
  include cache Python precompilate e verificate tramite hash. Collaudo del motore
  nella copia fuori checkout riuscito; collaudo completo della finestra sospeso
  dopo l'interruzione esplicita di Computer Use con Esc. La prima attesa di circa
  92 secondi richiede diagnosi distinta dagli avvii successivi più rapidi: non è
  considerata spiegata o risolta dalla sola precompilazione. La pagina iniziale
  è stata compattata e la finestra configurata massimizzata su richiesta dell'utente.

- **Passaggio a Qt autorizzato, 2026-11-03:** sostituire il contenitore
  pywebview/WebView2 con PySide6 e QtWebEngine distribuiti insieme all'app.
  Eliminare il requisito di .NET e WebView2 sul PC destinatario, mantenendo
  identici GUI web, OCR, NER e contratti API. Profilo browser temporaneo,
  esportazione su scelta esplicita e chiusura dei processi restano requisiti.
  Verificare risorse Qt nella copia rilocata, clipboard e download; il cambio
  di contenitore non costituisce soluzione dei tempi di caricamento del modello.

- Prodotto di **pseudonimizzazione assistita con revisione**, senza promessa di anonimato assoluto o autorizzazione automatica a usare qualsiasi servizio IA. Il servizio di oscuramento riceve l'originale; al servizio successivo il medico inoltra il testo approvato.
- Prima versione: identificativi diretti di paziente e terzi, luoghi e strutture riconoscibili. Informazioni contestuali residue possono consentire reidentificazione; copertura e limiti devono essere documentati.
- **Eccezione approvata il 2026-11-03:** i file temporanei su disco di pytesseract e delle librerie di upload sono accettati in questa fase. Nessun lavoro dedicato a OCR senza file, tmpfs o dimostrazione di assenza assoluta di scritture. Restano pulizia ordinaria, nessun archivio server di documenti/risultati e nessun contenuto nei log. L'hardening dei residui dopo crash è rinviato e non blocca il prototipo.
- Nessun database o cache dei documenti; testo originale e mappa restituiti al browser per la revisione. L'export visuale usa una seconda richiesta autenticata e stateless con originali e maschere approvate; nessun archivio tra richieste. Questa scelta sostituisce il precedente vincolo di non reinviare mai il documento. Riassociazione testuale sempre locale. La CLI scrive copie soltanto su richiesta, senza sovrascrivere gli originali.
- Formati iniziali PDF/JPEG/PNG/HEIC esportati, DICOM escluso. Metadati, miniature, allegati e layer nascosti non devono trasferire dati nell'output. Nessuna promessa di de-identificazione anatomica o supporto diagnostico DICOM.
- Maschere visuali applicate ai pixel, non semplici annotazioni rimovibili. PDF iniziale rigenerato da pagine raster già oscurate, senza testo originale sottostante o oggetti originali incorporati. Qualità di rasterizzazione e conservazione dei dettagli devono essere verificate; nessuna riduzione silenziosa di risoluzione per rientrare nei limiti.
- Verifica delle licenze di codice, pesi e dataset rispetto ai vincoli di progetto; esclusi PyMuPDF, OCRmyPDF e Ghostscript. Nessun ripiego automatico su dataset con obblighi incompatibili.
- Separare rilevazione e decisione di mascheratura: identificativi L0/L1 mascherati anche se formalmente invalidi ma plausibili; date degli eventi conservate. L2/L3 aggiungono copertura.
- L'unione di intervalli sovrapposti non perde caratteri sensibili; non implica che i candidati appartengano alla stessa persona.
- Nessuna deduzione del paziente dal primo CF trovato. Identità discordanti richiedono revisione; la somiglianza dei nomi non basta per fondere persone.
- Traslazione e ritraslazione delle date rinviate, assenti da CLI/API/UI iniziali. Nascita → età solo con riferimento temporale attendibile e confermato; altrimenti segnaposto, senza fallback implicito a oggi.
- Autenticazione obbligatoria nel primo ambiente condiviso. Override finto solo nei test e nello sviluppo locale esplicitamente configurato; configurazione condivisa incompleta nega accesso.
- Nessun commit o pubblicazione automatici: autorizzazione esplicita dell'utente secondo le istruzioni globali.

## Ordine di esecuzione e traguardi

I numeri 1–15 conservano il riferimento al piano originale; **non sono l'ordine cronologico**.

1. Task 0: contratto di revisione, campione iniziale, criteri di misura e verifica del contratto JWT.
2. Task 1–7: nucleo testuale. Avviare subito Task 14 con campioni annotati.
3. Task 8–11: prima estrazione completa; Task 10B: confronto NER; Task 10C: oscuramento visuale effettivo e rigenerazione dei file.
4. Task 12, 12B e 13: percorso completo autenticato con revisione ed export. Il prototipo UI può partire prima con risposte simulate.
5. Task 14–15: campione ampliato, prova con medici, regressioni, carico e decisione sul pilota.

**Primo traguardo di prodotto:** caricamento, confronto originale/anteprima oscurata, correzione delle aree sensibili, download della copia immagine/PDF e, quando utile, TXT/mappa. Il blocco testuale iniziale è una base tecnica, non questo traguardo. Dimostrare qualità visuale e costo della revisione prima di ampliare le funzionalità.

## Contratto comune di dati e revisione

- Documento e pagine hanno ID opachi; l'ordine è scelto dal medico, mai imposto dal nome file.
- PageResult: page_id, source_id, indice, testo originale estratto immutabile, modalità di estrazione, parole/blocchi con intervalli e coordinate, avvisi di qualità. Le coordinate devono essere riportabili all'originale dopo preprocessing.
- Span: ID, page_id, intervallo [start,end) nel testo originale della pagina, tipo, livello, origine, confidenza se disponibile, validazione ed eventuale entity_id. Confidenza e checksum non sono probabilità di sicurezza.
- MergedSpan: unione della copertura con riferimenti a tutti i candidati, origini, livelli e conflitti.
- Entity: ID, ruolo, varianti osservate, segnaposto e stato di conferma. Un CF valido non equivale a paziente confermato.
- Replacement: ID, intervallo originale, testo sostitutivo, intervallo nel risultato ed entità. Valore canonico e forme osservate distinti; annullare una sostituzione ripristina la specifica occorrenza originale.
- API con schema_version; offset in punti di codice Unicode. Il browser converte esplicitamente gli indici UTF-16 JavaScript. Test con accenti, caratteri combinati ed emoji; nessuna normalizzazione successiva che invalidi gli offset.
- Risposta: pagine/testo originale/coordinate, candidati, entità, sostituzioni, anteprima pseudonimizzata, mappa, avvisi e tempi. Nessun archivio server per continuare la revisione.
- Il browser conserva gli originali caricati per visualizzazione locale e successivo export stateless. Eventuali anteprime HEIC nella risposta, con dimensioni limitate e senza URL persistenti sul server.
- SourcePageGeometry: dimensioni originali, unità, crop/rotazione PDF o orientamento immagine e trasformazione tra copia OCR e originale. Una box senza spazio di riferimento non è sufficiente per oscurare.
- VisualRedaction: ID, page_id, poligono/quadrilatero in coordinate originali, origine automatica/manuale, candidati collegati, stato di conferma. Può esistere senza testo (firma, QR, identificativo illeggibile). Unire la copertura senza oscurare inutilmente il contenuto tra righe separate.
- L'output visuale contiene maschere opache definitive; le sostituzioni con segnaposto o età riguardano il TXT. Rimuovere un'identificazione testuale non implica che la corrispondente maschera immagine sia automaticamente valida: servono coordinate e verifica.
- Modifiche locali ricostruiscono testo e mappa dall'originale e dalle operazioni di revisione. Correzioni OCR esplicite, annullabili e distinte dalle mascherature; invalidano gli intervalli interessati e richiedono nuova verifica prima dell'export.
- Segnaposto delimitati e stabili, es. [[PAZIENTE]], [[PERSONA_1]], [[CF_1]]. Gestire collisioni con testo già presente. Riassociazione solo di token esatti, non ricorsiva.

### Revisione con mouse e testo documentale — 2026-11-03

Estensione successiva: prima pagina più moderna, originale e copia
affiancati, modifica direttamente sulle pagine al posto della lista di controlli.
Si mantiene una sola GUI HTML/CSS/JavaScript per browser e futura standalone.

- Caricamento con trascinamento, elenco file rimovibile, impostazioni secondarie
  raccolte in un pannello; nessuna nuova dipendenza grafica.
- Clic sulle parole per oscurare e sulle maschere per rendere leggibile la zona.
  Rettangoli liberi anche senza OCR, strumenti di spostamento/zoom, Annulla e
  Ripristina. Le interazioni agiscono su entrambe le anteprime.
- Verifica esplicita per pagina e conferma finale. Ogni modifica invalida la
  verifica della pagina e l'export. Gli avvisi restano consultabili; i candidati
  senza geometria richiedono una maschera manuale collegata.
- Testo estratto originale e oscurato per pagina. Il testo oscurato deriva dalla
  stessa impronta raster dell'export: regioni toccate sostituite con `[OSCURATO]`,
  testo senza coordinate con `[TESTO NON LOCALIZZATO]`. Niente riscrittura OCR.
- Copia del testo oscurato completo dopo verifica finale e download ZIP con PDF
  oscurato più TXT. Il TXT non sostituisce l'output visuale e non include ancora
  token riassociabili o mappa. CLI documentale e riassociazione restano da estendere.

Collaudo completato: 220 test passati senza skip con OCR/Torch/ONNX reali, lint e
build puliti. In Edge: upload/drop/rimozione file, layout desktop/mobile, clic da
entrambi i pannelli, Annulla/Ripristina tra pagine, testo sincronizzato e ZIP
riaperto con PDF raster e TXT. Disegno su immagine senza testo a zoom 200% con
scroll, rimozione e invalidazione finale verificati. Restano da provare nel browser
gesti touch, clipboard e collegamento dei candidati senza geometria; i vincoli
backend restano coperti. Evidenze e limiti in docs/validation.md. Questo blocco non
chiude validazione clinica, integrazione dell'anagrafica o confezionamento standalone.

## Task 0: criteri e contratto

**File previsti:** docs/validation.md, src/tests/fixtures/, src/anonymizer/model.py (con Task 2).

- [ ] Campione sintetico iniziale: PDF nativo, scansione, foto inclinata, pagina mista, tabella, intestazione ripetuta, più persone e testo poco leggibile.
- [ ] Annotare identificativi per occorrenza/pagina/posizione; separatamente numeri, unità, negazioni e relazioni riga/colonna.
- [ ] Esempi JSON del contratto, inclusi conflitti, correzione OCR e annullamento di mascheratura.
- [x] Definire classi coperte, casi non supportati e avvisi bloccanti. Criteri iniziali in docs/validation.md; copertura effettiva da verificare nel codice. Un avviso non equivale a lettura completa.
- [ ] Verificare contratto JWT del servizio di identità: issuer, audience, firma, scadenza e accesso. Non inventare endpoint o registrare segreti. Dettagli mancanti bloccano l'ambiente condiviso, non il prototipo locale.

## Task 1: scaffold e codice fiscale

**File:** pyproject.toml, src/anonymizer/__init__.py, src/anonymizer/cf.py, src/tests/test_cf.py, .gitignore, README.md.

**Interfacce:** is_valid_cf, decode_cf, cf_variants; decodifica con dati certi e ambiguità esplicite. L'anno nel CF non risolve da solo il secolo.

- [ ] Creare pacchetto, dipendenze, CLI e strumenti di verifica.
- [ ] Test per checksum, omocodia, date impossibili, varianti OCR e secolo ambiguo. Verificare i CF sintetici delle fixture.
- [ ] Implementare validazione/decodifica separatamente dalla mascheratura; non inventare date complete dai dati ambigui.
- [ ] Eseguire test del modulo e controlli statici pertinenti.

## Task 2: intervalli e regex L1

**File:** src/anonymizer/model.py, src/anonymizer/detect/__init__.py, src/anonymizer/detect/regex.py, src/tests/test_detect_regex.py.

**Interfaccia:** detect_regex(text, page_id) → list[Span]. Tipi: CF, tessera, data, nascita, telefono, email, CAP, IBAN, codice pratica, persona, medico, luogo, struttura.

- [ ] Test per tipo, contesti negativi clinici e offset; distinguere date evento/nascita.
- [ ] CF plausibile con checksum errato resta sensibile. Test anche senza anagrafica e con errori OCR contestualizzati; sostituire il precedente test che imponeva di ignorarlo.
- [ ] Contesto per telefoni/CAP/codici, evitando di mascherare misure cliniche indiscriminatamente. Conservare esito validazione e motivazione.
- [ ] Implementare, verificare e documentare classi ancora non coperte, comprese targhe se rinviate.

## Task 3: dizionari e contesto L2

**File:** src/anonymizer/data/, src/anonymizer/data/LICENSES.md, src/anonymizer/detect/dictionary.py, src/tests/test_detect_dictionary.py.

- [ ] Reperire nomi, cognomi, comuni/codici catastali e strutture con fonti/licenze verificate. Se mancano fonti adatte, usare un sottoinsieme dichiarato e misurarne i limiti.
- [ ] Testare titoli, nome+cognome, nascita/residenza, strutture e cognomi ambigui (Forte, Grasso, Testa), anche in frasi cliniche.
- [ ] Implementare contesto e provenienza; non estendere indiscriminatamente una struttura fino a fine riga assorbendo testo clinico.
- [ ] Misurare identificativi mancati e testo clinico mascherato erroneamente.

## Task 4: dati noti e identità L0

**File:** src/anonymizer/patient.py, src/anonymizer/detect/known.py, src/tests/test_detect_known.py.

- [ ] Distinguere dati dichiarati dal medico e proposti dal documento, con conferma e origine.
- [ ] Testare nomi, varianti OCR, CF, nascita in più formati, contatti e familiari. Fuzzy su token abbastanza lunghi, soglie misurate e contesti negativi.
- [ ] Casi con CF di paziente/familiare, CF discordanti, nomi simili e dati dichiarati incompatibili.
- [ ] Mascherare anche con identità incerta; PAZIENTE/CF_PAZIENTE solo con associazione confermata. Altrimenti entità separate e avviso.
- [ ] Non fondere persone soltanto sulla distanza di edit; testare separazione delle identità.

## Task 4B: collegamento anagrafica e GUI condivisa — prossimo blocco

- [ ] Ricognizione del contratto effettivamente disponibile per anagrafica locale del gestionale: ricerca/selezione oppure paziente corrente, disponibilità e permessi.
  Confrontare gli adattatori esistenti senza assumere endpoint o aprire database
  sulla base di credenziali dedotte. Distinto da login JWT e anagrafiche centrali.
- [ ] Definire un adattatore di sola lettura che restituisca dati minimi e provenienza
  nel contratto KnownIdentity comune, senza esportare l'intera anagrafica.
- [ ] Aggiungere alla stessa GUI selezione/conferma paziente e dati noti manuali;
  passare l'identità al motore documentale L0, mantenendo regole/NER per i terzi.
- [ ] Invalidare analisi e conferme quando cambiano paziente o dati noti; mantenere
  separati identificativi trovati nel referto e identità confermata del paziente.
- [ ] Verificare con fonte simulata: disponibile/assente/errore, pazienti omonimi,
  dati discordanti, cambio paziente e nessuna modifica alla sorgente. Collaudare
  poi il collegamento reale nell'ambiente autorizzato, senza dati nei log/report.

## Task 5: fusione senza perdita di copertura

**File:** src/anonymizer/merge.py, src/tests/test_merge.py.
**Interfaccia:** merge(text, spans) → list[MergedSpan], per pagina, ordinata senza sovrapposizioni.

- [ ] Test per contenimento, sovrapposizioni parziali/catene: [0,10) e [8,16) coprono [0,16).
- [ ] L'output contiene tutta la copertura sensibile dell'input e conserva origini/candidati.
- [ ] Unire token adiacenti solo con stessa entità e separatore compatibile; non persone o pagine diverse.
- [ ] Conflitti di tipo/identità: copertura conservativa, candidato composto e avviso; mantenere conferma L0/L1.

## Task 6: pseudonimizzazione e mappa

**File:** src/anonymizer/pseudo.py, src/tests/test_pseudo.py.
**Interfaccia:** pseudonymize produce anteprima, sostituzioni con offset originali/risultanti e mappa versionata. Opzioni: strutture e riferimenti temporali confermati per documento; nessuna traslazione.

- [ ] Test per stabilità delle entità confermate, intestazioni, CF di terzi, persone simili distinte e collisioni dei segnaposto.
- [ ] Conservare date evento e sesso. Nascita → età al riferimento confermato; altrimenti [[DATA_NASCITA_n]] e avviso. Nei dossier storici non applicare indiscriminatamente un unico riferimento.
- [ ] Tutti i caratteri fuori dagli intervalli trasformati restano invariati rispetto al testo estratto, inclusi numeri/unità/negazioni.
- [ ] Conservare forma originale per occorrenza e valore canonico separati.
- [ ] Mappa esclusa dall'export testuale. Non riassociare genericamente espressioni di età a date di nascita.

## Task 7: serializzazione e riassociazione

**File:** src/anonymizer/mapstore.py, src/anonymizer/reassoc.py, src/tests/test_mapstore.py, src/tests/test_reassoc.py.

- [ ] Schema versione 1 con ID documento/sessione, entità e valori necessari. Validazione di struttura/versione.
- [ ] Test round trip, token sconosciuti, PERSONA_1 vs PERSONA_10, collisioni e sostituzione non ricorsiva.
- [ ] Solo token esatti; nessuna ritraslazione date. Segnalare token sconosciuti/modificati senza indovinarne il significato.
- [ ] Fixture comuni Python/JavaScript; riassociazione web solo nel browser.

## Task 8: ingest e scelta dell'estrazione

**File:** src/anonymizer/ingest.py, src/tests/test_ingest.py, src/tests/fixtures/make_fixtures.py.
**Interfacce:** InputFile e pagine con ID/metadati; iterazione per pagina senza rasterizzare tutto in anticipo.

- [ ] Validare estensione/contenuto PDF/JPEG/PNG/HEIC e preservare ordine scelto dal medico.
- [ ] Fixture: PDF nativo, scansione, sola intestazione testuale con corpo immagine, layer incompleto, pagina mista.
- [ ] Eliminare soglia dei 50 caratteri: valutare copertura/layout/qualità. Nei dubbi OCR o avviso; evitare duplicazioni layer/OCR.
- [ ] Test: PDF realmente nativo salta OCR; PDF misto conserva contenuto e identificativi raster.
- [ ] Limiti pagine/dimensioni prima della rasterizzazione, budget cumulativo pixel e coordinate collegabili all'originale.

## Task 9: pre-elaborazione foto

**File:** src/anonymizer/preprocess.py, src/tests/test_preprocess.py.

- [ ] Orientamento, deskew, prospettiva e contrasto con fallback se il foglio non è rilevabile.
- [ ] Restituire trasformazioni geometriche per riportare coordinate all'originale.
- [ ] Test inclinazione, ombre, tagli, assenza quadrilatero; evitare perdita di intestazioni, cifre e segni.
- [ ] Confrontare qualità testuale prima/dopo, oltre alle proprietà geometriche/binarie.

## Task 10: OCR e fedeltà

**File:** src/anonymizer/ocr.py, src/tests/test_ocr.py, src/tests/test_extraction_quality.py.

- [ ] Tesseract TSV con parole, intervalli, coordinate, righe/blocchi, confidenza e timeout. Configurazione ANONYMIZER_TESSERACT e ANONYMIZER_TESSDATA; adattatore subprocess al posto di pytesseract per il quoting Windows verificato nel secondo blocco.
- [ ] Temporanei ordinari ammessi; pulizia delle librerie e chiusura risorse su errore gestito. Nessun test di assenza assoluta di scritture.
- [ ] Test pagina vuota, errori, testo poco leggibile e tabelle; preservare valore/unità/riga e segnalare ricostruzioni incerte.
- [ ] Evidenziare passaggi sospetti; confidenza OCR non è prova di correttezza. Nessuna correzione generativa.
- [ ] OCR reale su campione ridotto, simulato per regressioni dei livelli successivi.

## Task 10B: valutazione anticipata NER

**File:** tools/experiments/ner/, src/anonymizer/detect/ner.py, src/tests/test_ner.py, docs/ner-evaluation.md.

- [x] Verificare licenza/fattibilità CPU del primo candidato GLiNER; una sola istanza per adattatore. Altri candidati e ciclo di vita server ancora da valutare.
- [x] Confrontare L0/L1/L2 con e senza L3 sul medesimo campione sintetico e su insieme separato non usato per tarare.
- [x] Misurare persone/luoghi/strutture, falsi positivi clinici, RAM, cold start e latenza a caldo, anche senza anagrafica nota.
- [x] Adattatore con stessi Span e riferimenti verificati al testo originale; nessun modello generativo introdotto.
- [ ] Scelta e limiti registrati prima del pilota. NER assente/guasto visibile in health e avvisi, senza fallback silenzioso.

Scelta e limiti registrati; stato assente/guasto e avvisi implementati nella CLI
e nel manifesto. La voce resta aperta per health web e valutazione prima del pilota.

## Task 10C: oscuramento visuale e generazione delle copie

**File previsti:** src/anonymizer/visual_model.py, src/anonymizer/redact.py, src/anonymizer/export.py, src/tests/test_redact.py, src/tests/test_visual_export.py.

- [ ] Implementare SourcePageGeometry e VisualRedaction; collegare intervalli a tutte le regioni necessarie, comprese occorrenze ripetute e testi su più righe. Coordinate non disponibili o ambigue → avviso bloccante e maschera manuale, non esportazione come documento già protetto.
- [ ] Rilevare/proporre anche aree sensibili non riducibili al solo testo: QR/barcode, firme e annotazioni. Prevedere aggiunta manuale; dichiarare i limiti dei rilevatori automatici. Non mascherare automaticamente anatomia o misure cliniche come se fossero identificativi.
- [ ] Immagini: decodificare l'originale, applicare solo le maschere approvate e risalvare una copia PNG senza metadati originari. Conservare risoluzione e pixel fuori maschera; gestire esplicitamente orientamento, colore e profondità supportati, senza conversioni o perdita di frame silenziose. Preprocessing OCR non applicato all'output clinico.
- [ ] PDF: renderizzare tutte le pagine a qualità verificata, oscurarle e creare un PDF nuovo composto esclusivamente dalle immagini già oscurate. Preservare ordine, dimensioni pagina e orientamento. Non copiare oggetti originali, testo nascosto, allegati, annotazioni o miniature. Nessuna semplice sovrapposizione di rettangoli sul PDF originale.
- [ ] Se qualità/risorse non consentono una copia verificabile, bloccare e spiegare il limite; non abbassare silenziosamente DPI. La rigenerazione raster perde ricerca testuale/elementi vettoriali: documentare questo compromesso e verificarne l'accettabilità per gli esami esportati.
- [ ] Test su immagini e PDF sintetici con intestazioni, scritte dentro l'immagine, metadati identificativi, layer testuale, pagine ruotate e grafici/esami simulati. Fuori dalle maschere confrontare pixel con l'immagine decodificata o il rendering di riferimento del PDF.
- [ ] Riaprire gli output con un lettore indipendente e controllare testo estraibile, oggetti/metadati e immagini incorporate. Il testo nascosto non deve riemergere da selezione/copia o rimozione di annotazioni. Una ricerca delle sole stringhe nei byte compressi non basta.
- [ ] Testare originali immutati, maschere fuori pagina rifiutate, output multipagina completo e applicazione delle modifiche manuali. DICOM rifiutato esplicitamente nella prima fase.

## Task 11: pipeline e CLI

**File:** src/anonymizer/pipeline.py, src/anonymizer/cli.py, src/tests/test_pipeline.py, src/tests/test_cli.py.

- [ ] Comporre stadi rispettando budget/ordine; rilasciare risorse appena possibile. Risultato conforme al contratto comune.
- [ ] CLI anon/reassoc/bench con anagrafica, riferimento temporale esplicito e directory output; nessun --shift-dates.
- [ ] Estendere la CLI testuale di sviluppo con comandi documentali espliciti: copia oscurata obbligatoria, TXT opzionale e mappa separata. Non presentare il comando solo testo come implementazione del flusso immagini/PDF.
- [ ] Test PDF nativo, pagina vuota/fallita, conflitti, qualità insufficiente e multipagina. Pagina persa non equivale a documento completo.
- [ ] Verificare separazione .anon.txt/.map.json: la mappa contiene intenzionalmente dati originali, il testo non contiene la mappa.
- [ ] Log con conteggi, tempi e codici controllati; niente testo, nomi file o eccezioni grezze con dati sensibili.

## Task 12: API, autenticazione e risorse

**File:** src/anonymizer/web/app.py, src/anonymizer/web/schemas.py, src/anonymizer/web/auth.py, src/tests/test_api.py.

- [ ] POST /api/anonymize restituisce contratto completo di revisione; form anagrafico/opzioni senza traslazione. GET /api/health con stato sintetico OCR/NER.
- [ ] POST /api/export riceve nuovamente originali e maschere approvate, verifica identità delle pagine/impronte e limiti, genera copie oscurate e le restituisce senza conservarle. Originali scelti nel browser collegati alla stessa revisione; manifesto malformato, geometria incoerente o avvisi bloccanti non gestiti → errore controllato. Nessuna garanzia di completezza basata sul solo flag client di conferma.
- [ ] JWT verificato nel primo ambiente condiviso; test token assente/scaduto e firma/issuer/audience errati. Override locale/test esplicito e disabilitato nel profilo condiviso.
- [ ] CF malformato nel form → 422; plausibile con checksum errato → avviso/conferma senza inferenza anagrafica. CF sospetti nel documento mascherabili.
- [ ] 20 file/50 MB durante ricezione; 413 su limiti e 415 su formato, senza nomi file negli errori.
- [ ] Limiti configurabili anche su pagine/pixel/concorrenza/timeout. Proposta iniziale: 30 pagine, 25 megapixel/pagina, 150 megapixel cumulativi, 2 elaborazioni simultanee, 120 s/richiesta; ritarare al Task 15. Nessuna coda illimitata.
- [ ] Budget di concorrenza sull'intero servizio, non per singolo processo web. Sovraccarico esplicito; timeout/cancellazione fermano anche worker/OCR.
- [ ] Test limiti prima delle operazioni costose, carico, timeout, auth e cleanup dopo successo/errore. Il controllo della sola directory corrente non è prova di assenza di scritture e non è un criterio.
- [ ] Risposte sensibili non memorizzabili in cache. Revisione locale; seconda richiesta stateless solo per export visuale. Stessi controlli auth/risorse/cleanup su entrambi gli endpoint, senza persistenza tra richieste.

## Task 12B: revisione browser ed export

**File:** src/anonymizer/web/templates/, src/anonymizer/web/static/, src/tests/browser/.

- [ ] Prototipo anticipato: originale e anteprima oscurata, con zoom e maschere editabili; testo come vista aggiuntiva. Verificare usability su PC e telefono, anche quando il documento è prevalentemente visuale.
- [ ] Collegare selezione/avvisi alle coordinate originali; distinguere mascherature, incertezza OCR, conflitti e pagine mancanti.
- [ ] Aggiungere/rimuovere mascherature, confermare identità, riordinare pagine e correggere OCR con annullamento. Modifiche invalidano conferma precedente.
- [ ] Rimozione L0/L1 con conferma esplicita. Ricostruire offset/sostituzioni/mappa; test Unicode e occorrenze ripetute.
- [ ] Gestire avvisi bloccanti prima dell'export: correzione/conferma del passaggio oppure esclusione esplicita della pagina con indicazione di output parziale.
- [ ] Export della copia immagine/PDF dopo revisione, TXT e mappa aggiuntivi quando utili. Maschere manuali geometriche anche senza candidato OCR. Anteprima coerente con il renderer finale; visualizzare testo non fidato senza interpretazione HTML.
- [ ] Riassociazione con fixture Task 7, senza inviare mappa/risposta IA al server; nessuna conservazione automatica oltre la sessione di lavoro.
- [ ] Prova con medici: tempo, correzioni, errori residui e usabilità PC/telefono. Scelta frontend definitiva dopo la prova.

## Task 13: container

**File:** tools/deploy/Dockerfile, tools/deploy/compose.trial.yaml, .dockerignore, src/tests/test_docker.py.

- [ ] Linux Python 3.12, Tesseract italiano, utente non root, risorse/auth esplicite. Nessun volume per archiviare documenti/risultati.
- [ ] Temporanei ammessi; nessun obbligo di tmpfs/filesystem senza scritture.
- [ ] Profili locale/condiviso distinti; test con credenziali sintetiche e rifiuto richieste anonime.
- [ ] Verificare health, campione, timeout e chiusura risorse nel container; nessun deploy esterno implicito.

## Task 14: corpus e validazione a tre livelli

**File:** src/tests/corpus/generate.py, src/tests/test_recall.py, src/tests/test_extraction_quality.py, docs/validation.md.

- [ ] Avviare al Task 0: 20 documenti sintetici sono smoke test, non prova delle prestazioni. Ampliare layout, foto, PDF misti, tabelle, persone multiple, nomi stranieri e assenza anagrafica.
- [ ] Separare sviluppo/taratura e valutazione per documento/template. Eventuali documenti reali solo con uso autorizzato, fuori da repository e report.
- [ ] **Estrazione:** confrontare testo/layout con annotazioni; errori/omissioni e fedeltà di numeri, unità, negazioni, relazioni tabellari.
- [ ] **Rilevazione:** annotazioni per occorrenza nel testo effettivamente estratto, incluse varianti OCR. Copertura parziale/totale per intervallo e tipo, precisione e falsi positivi clinici.
- [ ] **Output:** identificativi residui anche alterati dall'OCR, documenti con almeno una fuga e contenuto clinico rimosso erroneamente; prima e dopo revisione umana.
- [ ] **Output visuale:** copertura delle aree sensibili, residui nei pixel/metadati/layer, fedeltà fuori maschera e leggibilità dei dettagli clinici. Valutare immagini e PDF riaperti dopo export, non soltanto l'anteprima o il TXT.
- [ ] Regressione: Rossi → R0ssi non mascherato è fallimento, anche se Rossi è assente. Identificativo perso nell'estrazione è errore di estrazione, non successo del rilevatore.
- [ ] 0,99 su testo pulito e 0,95 su foto restano obiettivi iniziali L0/L1, non garanzie. Riportare denominatori, numerosità per classe e incertezza; non generalizzare dalle sole fixture.
- [ ] Tempo revisione mediano/p95, correzioni/documento ed errori residui; concordare soglie con medici dopo prima prova.
- [ ] Difetti diventano regressioni. Pilota solo con criteri concordati superati sul campione separato e senza errori critici irrisolti; la media di recall da sola non basta.

## Task 15: prestazioni, decisione pilota e README

**Priorità anticipata il 2026-11-03:** affrontare il costo del motore prima del
successivo blocco anagrafica/confezionamento. Sono considerati inaccettabili
46 secondi sul PC di sviluppo, più potente dei PC degli utenti. Il risultato
successivo di circa 12 secondi con otto thread non chiude questo requisito:
il confronto controllato dimostra un beneficio NER locale, mentre il totale varia
anche per il carico del sistema. Il modello GLiNER multi-v2.1 resta una scelta
di prototipo, non una scelta definitiva per la standalone.

Ordine degli interventi e criteri di decisione:

1. Individuare perché i PDF esportati con testo nativo ricorrono all'OCR.
   Estendere il percorso nativo solo se non perde identificativi in immagini,
   forme, annotazioni o testo vettoriale. Casi non verificabili mantengono OCR.
   Il PDF locale esaminato ha testo nativo su tutte e quattro le pagine e nessuna
   immagine: il fallback attuale è causato dai path vettoriali. Valutare estrazione
   nativa affiancata da controllo/OCR del contenuto grafico residuo, con geometrie
   ricondotte alla pagina originale. Non classificare automaticamente linee e
   rettangoli come decorazioni: possono comporre identificativi o codici.
   Prototipo implementato dietro `analyze_documents(pdf_hybrid=True)` (default
   disabilitato): native più OCR di tutti i path neri opachi, fallback completo
   per grafica non supportata. Sul PDF autorizzato dimezza circa l'estrazione,
   ma cambia i candidati e non dimostra ancora un vantaggio completo con NER.
   Compattazione di maschere con identica copertura pixel attiva nel core.
2. Confrontare un backend NER ottimizzato/quantizzato e un modello più compatto
   con la baseline, prima sul corpus di sviluppo. Misurare tempo, memoria,
   identificativi mancati e falsi positivi clinici; una modifica del modello
   richiede valutazione separata, senza ritoccare il precedente campione riservato.
   Prima prova INT8 dinamica scartata: sullo sviluppo 32/32 identificativi coperti
   con FP32 contro 0/32 con INT8. Non modificati modello o precisione del servizio.
   Implementato backend opzionale ONNX FP32 dello stesso modello: preparazione
   offline riproducibile, artefatti verificati, provider/thread CPU espliciti e
   audit del runtime. Sullo sviluppo stessi 33 candidati e stessi caratteri
   mascherati in 22/22 documenti; analisi testuale 12,35 contro 6,12 s in una prova
   controllata a quattro thread. Il default della CLI resta Torch. Valutazione
   separata, tempo completo e hardware destinatario restano criteri distinti.
   Verifica finale runtime: equivalenza anche su evaluation immutato e PDF
   autorizzato. Su quest'ultimo, stesso OCR e quattro thread, fase testuale
   8,47→7,25 s (−14,4%), identici 86 candidati e 155 maschere. Servizio locale
   attivato con ONNX4; richiesta HTTP separata 18,45 s più 1,15 s anteprima.
   Nessuna accettazione implicita del budget sui PC meno potenti: Task 15 aperto.
   NER rimane nel percorso completo: disabilitarlo o usare soltanto l'anagrafica
   non soddisfa il requisito di velocità con copertura di paziente e terzi.
3. Solo dopo, valutare parallelismo limitato e analisi progressiva per pagina.
   Mostrare prima una pagina migliora l'attesa percepita ma non sostituisce il
   budget per completare l'analisi; nessun export prima delle verifiche complete.
4. Validare separatamente server e standalone: hardware identificato, tre pagine
   A4 realistiche native/scansionate, modello caldo e avvio a freddo, mediana/p95,
   RAM e carico. Il numero di thread non è una simulazione di hardware modesto.
   L'obiettivo iniziale resta 15 s/3 pagine, da confermare per i due profili;
   il confezionamento desktop non costituisce accettazione delle prestazioni.

Non ridurre risoluzione dell'export o copertura dei rilevatori per migliorare i
tempi. Web e standalone riusano GUI e core; un eventuale servizio remoto per la
standalone è una decisione esplicita, non un fallback introdotto automaticamente.

**File:** README.md, docs/validation.md, docs/ner-evaluation.md.

- [ ] Profilo proposto da confermare 4 vCPU/8 GB senza GPU; misurare 3 pagine, foto/PDF misti con NER scelto. Latenza totale mediana/p95 e per stadio, RAM picco, cold start e concorrenza.
- [ ] Obiettivo iniziale 15 s/3 pagine, dichiarando input e carico; misure locali non sostituiscono quelle di riferimento.
- [ ] Separare tempo di analisi, revisione umana ed export visuale; rivedere il budget totale con il nuovo output obbligatorio. Nessuna promessa che il budget OCR iniziale copra già rendering ed export.
- [ ] Riduzione DPI/cambio preprocessing richiede ripetere anche fedeltà/copertura sullo stesso campione. Velocità da sola non giustifica il cambiamento.
- [ ] Ritarare limiti risorse e rivedere i requisiti non raggiunti prima del pilota.
- [ ] Documentare avvio, API/CLI, auth, formati, incertezza, limiti e risultati misurati, compreso uso temporaneo del disco accettato.
- [ ] Piano successivo: traslazione date, eventuale cifratura mappa, hardening temporanei e miglioramenti emersi. Revisione, auth e valutazione NER sono già in questo piano.

## Riferimenti della revisione

- [FastAPI: upload](https://fastapi.tiangolo.com/tutorial/request-files/) e [pytesseract: implementazione](https://github.com/madmaze/pytesseract/blob/master/pytesseract/pytesseract.py): temporanei ammessi per scelta di progetto.
- [Commissione europea: dati personali e pseudonimizzazione](https://commission.europa.eu/law/law-topic/data-protection/information-business-and-organisations/application-gdpr_en): riferimento per descrivere lo scopo; non sostituisce la valutazione del trattamento e del destinatario.
