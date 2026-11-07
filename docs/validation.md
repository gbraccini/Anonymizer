# Anonymizer — criteri di verifica

Avvio implementazione: 2026-11-03. Questo documento distingue i criteri da
verificare dalle evidenze effettivamente ottenute; non certifica il prodotto.

## Responsabilità del primo blocco

- Advisor: architettura, revisione degli invarianti, documentazione e stato del piano.
- Sol 6.1: implementazione e test del codice.
- Luna: ambiente isolato, download, esecuzione test, lint e build del pacchetto.

Il primo blocco comprende contratto, core testuale e CLI di servizio. Il secondo
aggiunge ingest, OCR, geometrie, revisione tramite manifesto e copie visuali.
Il terzo blocco integra e misura NER locale; interfaccia browser e autenticazione
seguono nei blocchi successivi.
Una prova del core non dimostra ancora la sicurezza dell'intero percorso documentale.

Requisito esteso durante l'avvio: copia oscurata dell'immagine/PDF sempre richiesta,
TXT aggiuntivo quando utile. DICOM escluso dalla prima fase. I criteri visuali
comprendono coordinate/trasformazioni corrette, maschere manuali, pixel fuori area
preservati, qualità PDF verificata e assenza di dati nei metadati/layer/allegati
della copia generata. Testo occultato da annotazioni rimovibili non soddisfa il
requisito. Queste verifiche appartengono al secondo blocco, distinto dal core testuale.

## Invarianti e casi obbligatori del core

| Area | Caso | Risultato richiesto |
| --- | --- | --- |
| CF | Struttura plausibile e checksum errato | Candidato sensibile; niente inferenze anagrafiche certe |
| CF | Anno a due cifre e omocodia | Validazione separata dalla decodifica; secolo non inventato |
| Identità | Paziente non confermato o CF di terzo | Mascheratura senza assegnazione automatica del ruolo paziente |
| Identità | Nomi simili o parziali di persone diverse | Nessuna fusione sulla sola distanza di edit |
| Intervalli | Sovrapposizioni parziali e transitive | Tutta la copertura originale preservata, con provenienza |
| Intervalli | Pagine differenti | Nessuna fusione tra pagine |
| Testo | Cifre, unità e negazioni fuori dalle maschere | Caratteri invariati |
| Date | Evento clinico | Data conservata |
| Date | Nascita senza riferimento confermato | Segnaposto, nessuna età calcolata a oggi |
| Date | Referto storico con riferimento confermato | Età rispetto al riferimento del documento |
| Mappa | Nome e CF della stessa persona | Segnaposto e valori di riassociazione distinti |
| Mappa | Forme diverse della stessa entità confermata | Valore canonico distinto dalle occorrenze osservate |
| Annullamento | Ripristino di una sostituzione | Forma originale di quella occorrenza |
| Riassociazione | Token sconosciuto, prefissi simili, valore contenente un token | Token esatti, sconosciuti segnalati, nessuna sostituzione ricorsiva |
| Collisioni | Segnaposto già contenuto nel documento | Nessuna confusione tra testo originario e token generato |
| Unicode | Accenti, caratteri combinati ed emoji | Offset coerenti in punti di codice; conversione UTF-16 esplicita nel futuro client |
| Errori | Intervalli o schema mappa non validi | Errore controllato; nessun risultato apparentemente completo |

La copertura dei dizionari iniziali deve essere dichiarata. Un piccolo vocabolario
di prova non equivale a un elenco completo di nomi o strutture italiane.

## Campione e metriche

Il corpus iniziale usa dati sintetici. Annotare ogni occorrenza per pagina e
intervallo, indicando identità, tipo e testo osservato. Annotare separatamente i
passaggi clinici da preservare. Tenere separati documenti/template di sviluppo e
di valutazione; nessun dato reale va aggiunto al repository.

Tre livelli di misura:

1. Estrazione: omissioni, errori testuali e relazioni riga/colonna.
2. Rilevazione: copertura totale/parziale e precisione sul testo effettivamente
   estratto, con denominatori per tipo.
3. Output: identificativi ancora visibili, documenti con almeno una fuga e
   contenuti clinici alterati, prima e dopo revisione.

La semplice assenza della stringa originaria non misura il successo: una variante
OCR non mascherata resta un errore. Identificativi persi nell'estrazione non sono
successi del rilevatore. Gli obiettivi 0,99/0,95 restano da misurare; test unitari
verdi non dimostrano il raggiungimento di tali soglie.

## Avvisi e revisione

- Identità incerta: mascherare conservativamente senza attribuire il ruolo paziente;
  conferma prima di assegnare segnaposto o valori canonici riferiti al paziente.
- Intervalli in conflitto: conservare copertura e provenienza, mostrando il conflitto.
- Lettura incompleta, pagina fallita o correzione OCR: invalidare la conferma;
  richiedere verifica/correzione oppure esclusione esplicita con output parziale.
- Rimozione di mascheratura L0/L1: conferma esplicita; ogni modifica invalida la
  precedente approvazione dell'output.
- NER assente: stato visibile e copertura limitata dichiarata.

La prova con medici dovrà stabilire soglie accettabili per tempi mediano/p95,
correzioni e residui. Il rilascio pilota richiede un campione separato e la
risoluzione dei difetti critici, oltre alle prove automatiche.

## Autenticazione: evidenze iniziali e prerequisiti

L'ambiente condiviso userà token JWT emessi da un servizio di identità esterno.
Prima di attivarlo restano da confermare algoritmo, materiale di verifica tramite
configurazione protetta, issuer/audience applicabili e claim minimi di
autorizzazione. Non trasferire al browser claim estranei alle necessità di
Anonymizer.

Questi prerequisiti non bloccano il core locale. Il futuro profilo condiviso deve
negare accesso se la configurazione di autenticazione non è completa.

## Temporanei

Per scelta di progetto, i temporanei delle librerie sono ammessi. Verificare
pulizia ordinaria e chiusura delle risorse su errori gestiti; non introdurre un
criterio di assenza assoluta di scritture o un obbligo di tmpfs.

## Evidenze di esecuzione del primo blocco

Verifica finale di Luna del 2026-11-03, dopo le correzioni richieste dall'advisor:

- Python 3.12.13 scaricato in tools/local/python; .venv isolata, nessuna installazione
  di sistema per il progetto.
- 93 test pytest passati; Ruff senza errori su anonymizer e tests.
- Wheel costruita e reinstallata in ambiente separato; vocabolario incluso nel
  pacchetto e CLI avviabile.
- Esempio README con dati noti confermati verificato; paziente mascherato e testo
  clinico dell'esempio preservato.
- Roundtrip CLI/serializzazione/riassociazione verificato byte per byte anche con
  newline LF, CRLF e CR.
- Prove generate di merge: 300 casi, 21.328 candidati, copertura e provenienza
  preservate. Le prove non rappresentano una misura di recall clinico.
- Fixture: src/tests/fixtures/text_corpus.json (20 documenti sintetici testuali) e
  src/tests/fixtures/review_contract.json. Non sostituiscono il campione PDF/foto/OCT
  simulato previsto per la fase visuale.

Report riproducibili locali: build/artifacts/verification.json e verification.txt.
Alla chiusura del primo blocco Tesseract non era disponibile; Docker era presente
ma non avviato. Quel collaudo non comprendeva OCR, NER, immagini/PDF, auth live o usabilità.

Limiti implementativi espliciti: dizionario sintetico, varianti OCR deterministiche
in L0 senza fuzzy generale, IBAN italiano contiguo, targhe escluse. Una sola forma
canonica distinta per tipo di dato e identità; più valori distinti dello stesso
tipo sono rifiutati per evitare riassociazioni errate. Nessuna garanzia di copertura
dei documenti reali.

## Secondo blocco: percorso visuale

Contratto implementato: impronta SHA-256 degli originali, geometria canonica per
pagina, coordinate in pixel dopo orientamento, proposte e maschere manuali,
decisione per ogni regione proposta e impronta dell'intera revisione. Modificare
testo, maschere o avvisi invalida la conferma precedente. Il digest non è una
firma di sicurezza e non dimostra l'effettiva revisione umana: il futuro backend
dovrà mantenere controlli di autenticazione, validazione e limiti indipendenti.

PNG generato da pixel nuovi, senza metadati originari. PDF creato con ReportLab
da immagini oscurate e compressione senza perdita; nessun oggetto originale
viene copiato. Il riferimento per la fedeltà è la decodifica orientata
dell'immagine oppure il rendering PDF al DPI scelto, non i byte compressi della
sorgente. La rasterizzazione PDF perde testo selezionabile e vettori.
Il confronto esatto PDF riguarda l'immagine incorporata, estratta con pypdf;
un rendering successivo del nuovo PDF può ricampionarla e modificare i pixel
visualizzati. Sul campione OCT simulato questo comportamento è stato osservato:
non si estende la garanzia sui pixel incorporati agli screenshot del lettore.

Politica iniziale restrittiva: RGB/L opachi a 8 bit e singolo fotogramma;
trasparenza, 16 bit/HDR e profili colore non supportati sono rifiutati.
Orientamento EXIF supportato; deskew e prospettiva ancora assenti. DICOM e moduli
PDF XFA esclusi. I quadrilateri manuali hanno un bordo conservativo di rasterizzazione:
la futura anteprima dovrà usare lo stesso renderer dell'export.

Tesseract 5.5.3 è stato predisposto localmente tramite conda-forge, con lingua ita,
in tools/local/tesseract-conda. Il binario non richiede modifiche al PATH di
sistema. Un primo tentativo con installer Windows aveva ignorato la destinazione
locale ed era finito in Program Files: è stato subito disinstallato con il suo
uninstaller, verificando rimozione della directory e della voce di disinstallazione.
Le prove successive usano soltanto l'ambiente locale. Versioni e checksum dei
download restano nei report locali; nessun dato clinico reale è stato usato.

La prova reale ha rilevato un difetto del quoting Windows nel percorso tessdata
passato tramite pytesseract. L'adattatore OCR usa perciò Tesseract direttamente
con argomenti separati, ambiente dedicato e timeout, mantenendo parole/coordinate
TSV. I temporanei ordinari restano ammessi e sono puliti a fine operazione.

Limiti di prodotto alla chiusura del secondo blocco: interfaccia grafica, TXT documentale coerente
con tutte le modifiche alle maschere, autenticazione web, NER, rilevamento
automatico di firme/QR, corpus clinico separato e prove con medici. Le fixture
sintetiche verificano invarianti e regressioni, non recall o idoneità diagnostica.

Osservazione della QA visuale sul campione di esame oculare simulato: email e
telefono vengono mascherati automaticamente, ma il nome sintetico "Beta Alfa"
rimane visibile perché non coperto dai rilevatori attuali. È un errore di
rilevazione registrato, non un successo dedotto dall'assenza di altre stringhe.
Il percorso assistito richiede aggiunta manuale della maschera sul nome prima
di considerare revisionato questo campione. Il caso non viene sostituito con
un nome già presente nel vocabolario per migliorare artificialmente il risultato.

### Collaudo finale del secondo blocco — 2026-11-03

- 142 test pytest passati in 23,95 s, con Tesseract italiano reale configurato.
- Ruff senza errori; wheel costruita e installata senza dipendenze in ambiente
  separato, import isolato da site-packages, vocabolario incluso e CLI avviabile.
- OCR italiano reale, percorso tessdata con spazi, token con virgolette e pulizia
  temporanei su timeout verificati. Immagine e PDF scansione elaborati end-to-end.
- PDF nativo ruotato a 0/90/180/270 gradi e ritagliato: geometrie e bitmap
  oscurate confrontate con il riferimento usando l'estrazione indipendente pypdf.
- Testo estraibile, allegati e dati originari nei metadati assenti dai PDF nuovi;
  AcroForm visibile nel rendering, testo invisibile inviato al percorso OCR,
  XFA rifiutato. Errore su pagina successiva elimina l'output parziale.
- PNG 16 bit, RGB16 e trasparenza tRNS rifiutati; HEIC RGB 8 bit singolo
  fotogramma verificato rispetto alla decodifica di riferimento.
- Esame oculare simulato: variante automatica e variante corretta manualmente
  conservate separatamente; zero pixel modificati fuori dalle maschere nei PNG.
  Anche le bitmap incorporate nei PDF, estratte con pypdf, hanno zero pixel
  modificati fuori maschera rispetto al rendering originale. Nel rendering
  successivo del PDF revisionato il lettore modifica 31.446 pixel rispetto alla
  bitmap incorporata (delta medio per canale 0,493; massimo 211 su scala 0–255):
  la differenza viene registrata separatamente, senza attribuirla all'oscuramento.
  L'advisor ha ispezionato l'output revisionato, con nome/email/telefono coperti
  e grafico simulato conservato.

Esempi locali: build/artifacts/synthetic-oct.png,
synthetic-oct-reviewed.png e synthetic-oct-reviewed.pdf. Gli output denominati
redacted sono la prova automatica con il nome mancato e non rappresentano
risultati completamente revisionati. Nessun esame reale o metrica di recall
clinico è incluso in questo collaudo.

Rapporto di questa fase: build/artifacts/visual-verification.json, con risultati
e SHA-256 degli artefatti. Il rapporto del primo blocco resta separato.

## Terzo blocco: NER locale — 2026-11-03

GLiNER multi-v2.1 integrato come livello L3 opzionale, con caricamento locale,
verifica degli artefatti, finestre sovrapposte e audit nel manifesto di revisione.
Assenza esplicita e guasti non producono fallback silenziosi. La protezione
pain_scores_v1 esclude soltanto proposte L3 contenute in punteggi VAS/NRS validi.

Luna ha verificato 166 test passati, zero skip, con OCR e NER reali; Ruff pulito,
wheel ricostruita e installata senza dipendenze in un ambiente isolato, con CLI,
modulo NER, dati ed extra presenti. Setup del modello riprodotto separatamente
e caricamento offline verificato con cache vuota.

Valutazione sintetica separata, eseguita una sola volta dopo lo sviluppo:
22 documenti, 33/33 identificativi interamente coperti, 502/502 caratteri.
Rimane il falso positivo clinico "Romberg": sette caratteri oscurati erroneamente
in uno dei due documenti puramente clinici. Nessuna taratura successiva su questo
insieme. Mediana 0,235 s/documento, p95 2,154 s, inizializzazione 9,409 s e
picco circa 2,68 GiB su CPU con quattro thread. OCR ed export esclusi dai tempi;
hardware obiettivo 4 vCPU/8 GB e documenti reali non ancora validati.

Sul campione OCT sintetico il nome "Beta Alfa" ora viene mascherato automaticamente,
insieme a email e telefono. Rimane una proposta errata sulla parola "Paziente".
Zero pixel cambiati fuori dalle maschere; curve simulate preservate. La revisione
resta necessaria e la suite non certifica la copertura su esami reali.

Dettagli, limiti e riproducibilità: [valutazione NER](ner-evaluation.md).
Report locale: build/artifacts/ner-verification.json. Output visuale corrente:
build/artifacts/synthetic-oct-ner-pain-redacted.png.

## Quarto blocco: GUI condivisa e servizio locale — 2026-11-03

Interfaccia HTML/CSS/JavaScript locale con confronto originale/anteprima, pagine,
zoom, proposte confermabili o rifiutabili con motivo, rettangoli manuali e avvisi.
La GUI è destinata anche alla futura standalone: il contenitore desktop riuserà
gli stessi asset e il motore Python, senza duplicare il flusso di revisione.
Il launcher attuale resta un servizio loopback da aprire nel browser, non un
installer desktop. Autenticazione condivisa e packaging desktop sono successivi.

Il contratto iniziale è firmato con una chiave effimera del processo; il browser
lo restituisce senza reinterpretarne la serializzazione firmata. Il server
ricostruisce la revisione da quel contratto e da modifiche ammesse, verifica gli
originali e confronta il digest con l'anteprima precedente prima di esportare.
La firma protegge l'integrità del contratto, non prova che una persona abbia
verificato correttamente il contenuto. La revisione scade dopo un'ora o al riavvio.

Il primo collaudo browser ha rilevato una differenza di serializzazione numerica
Python/JavaScript che invalidava la firma. Correzione: payload JSON opaco firmato
sui byte originari, con manifesto separato confrontato con il payload verificato;
regressione dedicata e ripetizione del percorso browser.

Anteprime server ottenute dallo stesso renderer canonico dell'export, poi ridotte
a un lato massimo di 1800 pixel. L'export usa la risoluzione originale normalizzata
o il rendering PDF al DPI scelto. Il browser reinvia gli originali per anteprima
ed export; nessun archivio documentale tra richieste. Sono ammessi temporanei
ordinari. Il launcher impone loopback, un worker, controlli peer/Host/Origin,
risposte no-store e una sola elaborazione mutante alla volta. Il limite del corpo
HTTP è verificato anche senza Content-Length prima del parsing multipart.

Limiti operativi: il gate è per processo; il profilo distribuito/multiworker non
è supportato. Il timeout OCR esistente è per pagina, senza arresto forzato globale
del lavoro CPU. La riduzione dell'anteprima richiede controllo dei dettagli
nell'output. Correzione del testo OCR, TXT documentale, anagrafica, riordino ed
esclusione pagine non fanno parte del prototipo attuale. Prove in viewport mobile
non equivalgono a validazione d'usabilità con medici o su un dispositivo fisico.

### Collaudo finale della GUI locale

- 176 test pytest passati con OCR italiano e NER reali; Ruff pulito e controllo
  sintattico JavaScript superato. Sdist e wheel costruite; installazione della
  wheel in ambiente separato verifica gli asset index.html, app.js e style.css.
- Browser Edge: caricamento OCT sintetico, rifiuto motivato di una proposta,
  disegno manuale, gestione degli avvisi, invalidazione della conferma dopo una
  modifica e download PDF. Zero errori JavaScript; screenshot 1440×1000 e 390×844
  ispezionati. Il campione manuale verifica il comando, non una revisione clinica.
- Percorso HTTP con PNG, PDF nativo e PDF scansione di due pagine, a 300 DPI.
  Sorgente sostituita e digest obsoleto rifiutati. Test dedicati coprono contratto
  alterato, area fuori pagina, conferma mancante, scadenza, richiesta concorrente,
  salute del servizio durante analisi e limite HTTP senza Content-Length.
- PNG finale e bitmap incorporate nei PDF, estratte con pypdf, identici alle
  anteprime canoniche sui campioni senza riduzione: zero pixel differenti.
  Il confronto originale/anteprima non rileva modifiche fuori dalle maschere.
  PDF finali con due pagine e zero testo estraibile; metadati originari assenti.
- Il successivo rendering PDFium può ricampionare i pixel incorporati: sui quattro
  fogli il delta medio di luminanza è circa 0,28–0,65 su 255, massimo 134–205.
  Questa differenza del lettore è distinta dalla bitmap esportata; non si promette
  identità dei pixel in tutti i visualizzatori PDF.

Misure locali su Intel Core Ultra 7 155H (16 core/22 processori logici), 31,3 GiB
di RAM, quattro thread NER CPU. Ogni pagina di questi campioni misura 1800×1000
pixel: non sono pagine A4 a 300 DPI. Tempi wall HTTP di una singola esecuzione
con modello già caricato, non mediana/p95 né prova di carico:

| Campione sintetico | Analisi | Anteprime, totale | Export |
| --- | ---: | ---: | ---: |
| PNG, una pagina | 0,55 s | 0,07 s | 0,06 s |
| PDF nativo, due pagine | 0,79 s | 0,33 s | 0,76 s |
| PDF scansione, due pagine | 2,00 s | 0,32 s | 0,34 s |

Analisi include trasporto HTTP locale, ingest, rendering/estrazione, eventuale
OCR, NER e proposte. Export include verifica delle sorgenti, rendering, maschere
e codifica; le anteprime sono richieste separate e la revisione umana è esclusa.
Avvio misurato del launcher reale: 11,523 s fino a disponibilità, di cui 10,552 s
nel ciclo di inizializzazione app. Working set campionato circa 2,14 GB decimali,
picco 2,89 GB (circa 1,99 e 2,70 GiB). Sono misure locali; hardware obiettivo
4 vCPU/8 GB, PDF A4 lunghi e concorrenza distribuita restano da validare.

Report consolidato: build/artifacts/web-verification.json. Dettagli:
build/artifacts/web-api-e2e/web-api-e2e.json,
build/artifacts/web-ui-e2e/web-ui-e2e.json e build/artifacts/web-startup-final.json.
Gli avvii riportati appartengono a istanze successive durante il collaudo e non
vanno interpretati come misure della stessa istanza. Nessun documento reale è
stato usato e il campione NER di valutazione non è stato modificato né ritoccato.

## Verifica prestazioni su PDF locale autorizzato — 2026-11-03

È stato misurato un PDF locale di quattro pagine
A4, 19.853 byte, a 300 DPI (2480×3509 pixel/pagina). Il documento resta fuori dal
repository: nessun testo, identificativo, manifesto o immagine viene salvato nei
report o inviato a servizi esterni. I confronti dei risultati si svolgono in RAM;
i report conservano soltanto tempi, conteggi e risultati delle verifiche.
Questa autorizzazione riguarda la prova tecnica richiesta, non un corpus clinico
di addestramento o una validazione generale del prodotto.

Baseline del servizio con quattro thread NER e modello già caricato: 46,55 s di
analisi HTTP, di cui 17,08 s OCR, 28,43 s NER, 0,68 s rendering. Prima anteprima
1,35 s. Un passaggio browser distinto richiede 50,56 s fino alla risposta analisi
e 52,26 s fino all'anteprima; la differenza fra passaggi non è overhead del DOM.
Risultato: quattro pagine, 6.443 caratteri, 1.015 regioni OCR, 155 proposte.

Profilazione separata: nove inferenze NER impiegano 24,23 s, contro 0,315 s per
73 conteggi di token. I quattro thread sono effettivi anche nel worker; il collo
di bottiglia è l'inferenza, non un errore di configurazione fra thread principale
e worker. Una finestra rappresentativa richiede 10,28/4,77/2,31 s con 1/2/4 thread,
con stessi intervalli e classi rilevati. Su una pagina OCR, il limite OpenMP a uno
produce lo stesso risultato ma 4,62 s contro 4,84 s: il guadagno marginale non
giustifica una modifica generale sulla sola prova.

Report numerici locali: build/artifacts/pdf-performance-before.json,
build/artifacts/pdf-ner-profile.json e build/artifacts/pdf-thread-profile.json.
Queste misure su pagine A4 spiegano perché i piccoli campioni sintetici del blocco
precedente non consentivano di stimare i tempi di questo documento.

### Configurazione CPU verificata sul PC corrente

Confronto successivo nello stesso processo, con un solo modello e testo OCR
estratto una volta e riutilizzato in RAM: analisi testuale 14,739 s con quattro
thread contro 8,515 s con otto; inferenze 14,444 contro 8,324 s. Circa 42% in meno
per questa fase. Il tempo a quattro thread è diverso dalla prima misura HTTP:
sono esecuzioni distinte e non si attribuisce tutta la differenza alla modifica.

Identici nel confronto: testo/regioni, intervalli e tipi dei candidati e delle
unioni, 55 span NER, 75 intervalli uniti, geometrie, codici degli avvisi e 155
poligoni di oscuramento con le loro associazioni. Differenza massima di confidenza
NER circa 1,79e-7, senza cambiamenti dei candidati alla soglia invariata.
Nessuna modifica a DPI, modello, pesi, etichette o politica di oscuramento.

Decisione: usare --ner-threads 8 nel servizio locale di questo PC, tramite
l'opzione esistente. Nessuna modifica al codice applicativo o al default di quattro
thread per il profilo generale. Non introdotti batching, quantizzazione o OCR
parallelo; il piccolo guadagno OpenMP osservato non è stato applicato.
Report numerico: build/artifacts/pdf-threads4-vs8.json. Il primo harness di
profilazione è terminato senza mantenere la baseline in memoria; non è usato
come prova di equivalenza. La prova citata qui ha eseguito entrambi i passaggi
nello stesso processo prima di rilasciare i dati.

Servizio locale riavviato con otto thread, configurazione verificata nella riga di
comando e health OCR/NER pronto. Un passaggio HTTP successivo sullo stesso PDF
a 300 DPI: analisi 11,985 s (OCR 5,093 s, NER 6,579 s), prima anteprima 0,622 s.
Stessi conteggi della baseline: quattro pagine, 6.443 caratteri, 1.015 regioni,
155 proposte e 32 avvisi. Il calo OCR da 17,08 a 5,09 s, senza modificarne il
codice o i parametri, evidenzia variabilità del carico/ambiente: il miglioramento
wall 46,55→11,98 s non è interamente attribuibile al cambio dei thread NER.
Il beneficio controllato resta circa 42% sulla fase NER. Nessuna garanzia sul
tempo di ogni futura esecuzione o sulla completezza clinica delle proposte.

Report finale numerico: build/artifacts/pdf-performance-after.json. Codice
applicativo invariato, pertanto la suite da 176 test non è stata ripetuta;
la verifica di questa modifica di configurazione è il confronto in RAM e la
nuova richiesta HTTP completa. L'originale non è stato modificato e nessuna copia
del referto o del suo risultato è stata conservata negli artefatti.

### Prestazioni sui PC destinatari: requisito ancora aperto

46 secondi non sono un tempo accettabile, considerata la
potenza inferiore dei PC degli utenti. Il tuning a otto thread e la successiva
misura locale di circa 12 secondi non validano la standalone. Quattro thread
sulla CPU di sviluppo non equivalgono a una CPU meno potente. Servono prove
separate per server e desktop su hardware rappresentativo, con mediana/p95,
memoria, avvio a freddo e qualità invariata; Task 15 è anticipato nel piano.

Inventario aggiuntivo del PDF autorizzato, svolto senza OCR/NER e senza salvare
testo, metadati o copie: tutte le quattro pagine contengono testo nativo;
zero immagini, form XObject, annotazioni o widget. Conteggi per pagina:

| Pagina | Oggetti testo | Path vettoriali | Caratteri PDFium |
| --- | ---: | ---: | ---: |
| 1 | 145 | 6 | 1.927 |
| 2 | 108 | 6 | 1.714 |
| 3 | 111 | 314 | 1.461 |
| 4 | 85 | 6 | 1.500 |

Il ramo nativo attuale ammette solo oggetti di testo visibile; questi path causano
OCR a pagina intera. È una possibilità concreta di riduzione del lavoro, non
ancora un'ottimizzazione implementata. Ignorare tutti i path sarebbe scorretto:
testo vettoriale e codici possono essere composti da linee/rettangoli. Il percorso
proposto deve conservare un controllo del contenuto grafico residuo e il fallback
OCR. I 6.602 caratteri nativi contro 6.443 OCR non misurano da soli la copertura:
spazi, ordine ed errori di estrazione richiedono verifica distinta.

Nessuna modifica al motore in questo riallineamento, nessun nuovo benchmark di
inferenza e nessuna ripetizione della suite da 176 test. Il servizio locale resta
configurato a otto thread; il README torna a mostrare il default di quattro senza
presentarlo come configurazione già validata per PC poco potenti.

### Prove di riduzione del lavoro — 2026-11-03

Implementato un percorso PDF ibrido conservativo: estrazione nativa del testo e
OCR di tutti i tracciati rimasti dopo rimozione degli oggetti testo dalla sola
copia PDFium in memoria. Non vengono cancellati rettangoli di pixel attorno alle
lettere, né classificati come innocui linee, griglie o codici. Il percorso richiede
testo visibile con font ispezionabile e path neri opachi, senza trasparenza,
immagini, form o annotazioni. I casi incerti usano OCR completo. Un errore OCR
non restituisce un'analisi parziale. L'export continua a usare l'originale.
Il percorso richiede l'opzione esplicita del core `pdf_hybrid=True`; il default
rimane `False`, anche nella GUI e nella CLI. La riduzione OCR da sola e il cambio
dei candidati non giustificano l'attivazione automatica nel prodotto.

Sul PDF autorizzato tre pagine superano i controlli, una resta in OCR completo.
Confronto nello stesso processo, 300 DPI, NER escluso: estrazione 6,608 contro
3,248 s; OCR 6,278 contro 2,795 s. Questa è una riduzione della fase di estrazione,
non una misura del tempo completo. Nel successivo confronto con lo stesso modello
FP32 a quattro thread, il totale è 18,003 contro 17,614 s, con NER 9,509 contro
13,640 s: il risparmio OCR non dimostra ancora un vantaggio complessivo affidabile.

Il testo nativo differisce dall'OCR: 6.571 contro 6.443 caratteri, 4.429 contro
1.015 regioni. Il confronto in RAM dei valori dei candidati normalizzati e del
tipo trova 72 corrispondenze, 14 candidati baseline assenti e 19 aggiunti; 12 valori
assenti fra i candidati restano presenti nel testo ibrido. Non è un confronto
contro annotazioni cliniche e non dimostra quale risultato sia corretto.
Report locali numerici: build/artifacts/pdf-hybrid-benchmark.json e
build/artifacts/pdf-hybrid-ner-final.json; nessun testo o manifesto conservato.

Le proposte native per carattere sono compattate solo per lo stesso candidato e
le stesse righe di pixel, con intervalli orizzontali che si toccano o sovrappongono.
Non vengono colmati spazi vuoti e non vengono uniti candidati diversi. L'unione
deve produrre esattamente gli stessi pixel oscurati, riducendo le conferme GUI.

**Esperimento INT8 scartato:** quantizzazione dinamica CPU del modello GLiNER
attuale, soltanto sui 22 documenti sintetici di sviluppo, stesso processo e
quattro thread. FP32: 10,814 s e 32/32 identificativi interamente coperti; INT8:
7,798 s ma zero predizioni e 0/32 identificativi coperti. Nessuna adozione nel
motore o nel servizio, nessun modello quantizzato salvato e nessun uso del corpus
di valutazione o del PDF privato. Report build/artifacts/ner-int8-development.json.
La documentazione [GLiNER sulla quantizzazione](https://github.com/urchade/gliner/blob/main/docs/usage.md)
segnala il rischio di perdita di accuratezza sui modelli DeBERTa non addestrati
per quantizzazione; il risultato qui riguarda specificamente questa configurazione.

### Backend ONNX FP32 e regressioni

Implementato backend opzionale ONNX CPU, senza quantizzazione e senza modificare
il modello, le etichette o la soglia. Bundle derivato offline verificato in
`tools/local/models/gliner-onnx-verified`: grafo di 1.157.113.249 byte, configurazione e
tokenizer, ledger con hash/provenienza. Hash verificati prima di aprire il grafo;
riferimenti a tensori esterni rifiutati prima del runtime. Opzioni CPU e audit
sono condivisi fra CLI e app. Torch rimane il default della configurazione.

Collaudo del codice finale: **208 test passati, zero skip**, con Tesseract, NER
Torch e NER ONNX reali. Ruff pulito; wheel e sdist costruite, asset statici e dati
del pacchetto verificati. Le nuove regressioni coprono identificativi vettoriali
con OCR reale, sovrapposizione di testo e tracciati, fallback per compositing non
supportato, errori senza risultati parziali, crop/rotazione, export dei pixel
originali, compattazione con impronta identica, integrità del bundle ONNX e audit.

Sviluppo sintetico: stessi 33 candidati per offset/tipo e stessi caratteri
mascherati in 22/22 documenti; 32/32 identificativi annotati coperti. Valutazione
separata immutata: stessi 34 candidati, stessi caratteri mascherati in 22/22
documenti, 33/33 identificativi coperti; persiste in entrambi il falso positivo
clinico di sette caratteri. Dettagli, tempi e limiti in docs/ner-evaluation.md.
Questo collauda la sostituzione del runtime, non costituisce validazione clinica.

Confronto finale sul PDF locale autorizzato: OCR completo a 300 DPI eseguito una
sola volta (5,881 s più 0,239 s rendering), stessi quattro PageResult mantenuti in
RAM per Torch e ONNX, entrambi con quattro thread. Analisi testuale NER più regole:
**8,466 contro 7,247 s**, circa 14,4% in meno. Caricamento dei due adattatori:
9,098 contro 11,435 s. Non si tratta di due richieste HTTP complete e non si
sommano caricamento e inferenza come latenza ordinaria del servizio già pronto.

Confronto canonico: 86/86 candidati identici per offset, tipo, livello e origine;
delta massimo di confidenza 1,36e-5, stessi 75 intervalli uniti, stessi avvisi,
155 maschere e impronte di oscuramento identiche sulle quattro pagine. Nessun
identificativo o dato clinico copiato nei report: solo conteggi, tempi e risultati
di confronto. Report `build/artifacts/pdf-torch-vs-onnx-benchmark.json`.
Il beneficio sul file reale è più contenuto di quello misurato sullo sviluppo:
non viene presentato come dimezzamento generale o soluzione già validata per
PC poco potenti. I 46 secondi iniziali appartenevano a un'altra esecuzione con
diverse condizioni di carico e non sono la baseline causale di questa modifica.

Servizio locale aggiornato al bundle verificato ONNX, quattro thread, estrazione
ibrida disabilitata. Una sola richiesta HTTP finale: **18,448 s** per analisi
(OCR 6,931 s, NER 11,088 s, rendering 0,261 s), **1,152 s** per anteprima;
entrambe HTTP 200. Stessi quattro fogli a 2480×3509 pixel, 6.443 caratteri,
1.015 regioni, 155 proposte e 32 avvisi. Originale e anteprima restano in RAM
nel controllo client; nessuna copia del referto o delle immagini nei report.

Processo server fresco, senza conversione del modello: avvio 17,199 s,
working set 1.947.947.008 byte (1,95 GB / 1,81 GiB), picco 2.567.430.144 byte
(2,57 GB / 2,39 GiB). Unico listener loopback sulla porta 8765, runtime e thread
verificati nella riga di comando e nell'audit dell'analisi. Report numerico
`build/artifacts/web-onnx-final-e2e.json`. Il riavvio invalida le revisioni aperte.

Il tempo HTTP finale non dimostra un ulteriore miglioramento rispetto al precedente
passaggio a otto thread e non è mediana/p95. Il risultato controllato resta il
14,4% sulla fase testuale a parità di quattro thread e OCR. **Prestazioni su PC
modesti e budget di prodotto ancora da validare**; non è stato provato un PC
destinatario né un ambiente effettivo 4 vCPU/8 GB. Non considerare chiuso Task 15.

## Revisione diretta sulle pagine e testo estratto — 2026-11-03

La GUI condivisa è stata aggiornata con caricamento tramite trascinamento, file
rimovibili, correzioni con clic sulle due anteprime, rettangoli liberi, spostamento,
zoom e Annulla/Ripristina. La cronologia salva la singola pagina: annullare una
modifica non deve cancellare decisioni o verifiche effettuate su altre pagine.
La verifica resta esplicita per pagina e per documento; le eccezioni geometriche
non sono superate dalla semplificazione dei controlli. Le immagini devono essere
decodificate prima di abilitare la verifica della pagina.

Il testo oscurato usa l'impronta raster dello stesso renderer dell'export, inclusi
quadrilateri, sovrapposizioni, rifiuti e maschere manuali. Una regione testuale
anche parzialmente coperta viene omessa integralmente. Le parti senza coordinate
utilizzabili diventano `[TESTO NON LOCALIZZATO]`; non vengono pubblicate come testo
leggibile. Originale e oscurato sono inseriti nei controlli come testo, senza
interpretazione HTML. Il TXT documentale non è ancora riassociabile.

Il download ZIP contiene esattamente `documento-oscurato.pdf` e
`testo-oscurato.txt`; l'endpoint di copia del testo completo e l'export visuale
richiedono lo stesso contratto firmato, conferme, digest corrente e originali
verificati. I test includono modifica manuale successiva all'anteprima, geometria
alterata, originale sostituito, Unicode, regioni fuori pagina/degenerate e un
quadrilatero la cui impronta differisce dal rettangolo di delimitazione.

La verifica UI usa solo fixture sintetiche, senza il referto privato impiegato
nel precedente confronto di prestazioni. Landing e revisione controllate
visivamente a 1440×1000 e 390×844 in Edge. Caricamento, rimozione e drop passati;
nessun overflow orizzontale o errore JavaScript nel controllo iniziale. Evidenze
locali `build/artifacts/ui-mouse-*.png` e `ui-mouse-upload-report.json`.

Percorso PDF sintetico di due pagine a 72 DPI completato in Edge: clic su maschera
da entrambe le viste, clic su parola, Annulla/Ripristina, verifica delle pagine e
annullamento su una pagina senza perdere la verifica dell'altra. Il testo cambia
con la maschera manuale. ZIP scaricato e riaperto: due voci attese, PDF di due
pagine senza testo estraibile, TXT coerente con le decisioni. Sedici risposte API
HTTP 200, nessun errore JavaScript. Report `ui-mouse-pdf-e2e-report.json`.
Un primo timeout dell'harness è stato ricondotto a `wait_for_function`/eval
incompatibile con la CSP: risolto nei controlli browser senza indebolire la CSP.

Ulteriore prova su immagine sintetica senza testo leggibile: disegno reale con
mouse a zoom 200% e viewport spostato, maschera presente nell'anteprima canonica,
rimozione con clic e invalidazione della verifica finale/export. Sei risposte
HTTP 200 e nessun errore JavaScript. Report `ui-mouse-drag-report.json`.
Non verificati in questa sessione browser: gesti touch di spostamento, clipboard
del sistema e collegamento manuale di candidati con geometria incompleta. Il
layout mobile è stato controllato; i vincoli geometrici e l'endpoint del testo
finale restano coperti dai test backend. Non è una validazione su dispositivi
fisici né una verifica clinica delle rilevazioni automatiche.

Collaudo finale: **220 test passati, zero skip**, con Tesseract, Torch e ONNX reali
(40,38 s). Ruff e controllo sintattico JavaScript puliti; wheel e sdist costruite,
tre asset GUI verificati in entrambi gli archivi. Report
`build/artifacts/ui-mouse-build-report.json`. Servizio locale riavviato dopo
l'ultima modifica del backend, NER ONNX con quattro thread e OCR pronti; nessuna
modifica ai limiti, ai modelli o all'estrazione PDF predefinita.

### Testi accanto ai documenti e note compatte

In una revisione successiva, i due documenti restano adiacenti al
centro e i rispettivi testi sono visibili ai lati esterni. Sotto 1100 px ogni
testo si dispone sotto il proprio documento. Rimossi i due riquadri inferiori
dedicati a testo e avvisi; le azioni di copia/download restano accanto ai testi.

La barra contiene "Note di lettura", senza contare i promemoria generali come
errori del documento. Solo le geometrie ancora da collegare producono il badge
"aree da completare". Il pannello conserva le note, la selezione dei candidati e
il disegno collegato; si apre anche quando la verifica incontra una geometria
incompleta. Conferme, riconoscimento degli avvisi e controlli server invariati.
Modificati soltanto HTML/CSS/JavaScript: nessun riavvio del servizio richiesto.

Verifica mirata completata in Edge su PDF sintetico: disposizione dei quattro
pannelli a 1440 e 1920 px, testi sotto i rispettivi documenti a 390 px, nessun
overflow. Note aperte entro il viewport mobile e chiusura con Escape. Clic,
ripristino e testo aggiornato, verifica di due pagine ed export PDF riusciti;
nessun errore JavaScript. Il ramo delle geometrie mancanti è stato verificato con
risposte UI simulate: badge, focus sull'azione, rettangolo collegato e scomparsa
del badge; questa prova non costituisce un export reale con contratto simulato.
Controllo sintattico JavaScript pulito; wheel/sdist aggiornate con i tre asset.
Report locali `ui-inline-report.json`, `ui-inline-geometry-mock.json` e
`ui-inline-build-report.json`. La suite completa precedente non è stata ripetuta
per questa modifica esclusivamente grafica.

### Conferme esplicite e navigazione a piè di pagina

La segnalazione di copia e casella finale disabilitate è stata chiarita come problema di comprensibilità del percorso. Il pulsante si chiama
ora "Conferma questa pagina". I comandi finali mostrano il requisito ancora
mancante, i numeri delle pagine da confermare e un'azione per raggiungerle. Le
pagine confermate sono marcate nel selettore. La navigazione è stata spostata
sotto documenti e testi, centrata, con Precedente/Successiva in evidenza e la
conferma nella stessa zona. Le condizioni di approvazione non sono cambiate.

Un errore dell'anteprima resta visibile e permette di riprovare; contratto scaduto
o non valido richiede una nuova analisi. Le risposte obsolete di altre pagine
non aggiornano lo stato dell'errore e un'anteprima valida lo cancella.

QA mirata su PDF sintetico di due pagine: navigazione desktop/mobile senza
overflow, focus sulla pagina mancante, blocco fino a tutte le conferme e
abilitazione finale dopo l'anteprima aggiornata. Simulato un errore HTTP 500 della
preview, seguito da retry riuscito. Copia effettiva negli appunti Edge verificata:
testo identico alla risposta text-export normalizzando LF/CRLF di Windows,
identificativi sintetici oscurati assenti. Una verifica sincronizzata separata
conferma le due spunte U+2713 e lo stato finale abilitato: due campionamenti iniziali
dell'harness erano imprecisi. Nessun errore JavaScript; sintassi JS e build
wheel/sdist con asset aggiornati verificate. Nessun riavvio o nuova suite completa.
Report locali `ui-confirm-after-report.json`, `ui-confirm-final-check.json` e
`ui-confirm-build-report.json`.

### Passaggio finale mostrato dopo la revisione completa

Per scelta di progetto, conferma finale, formato, esportazione e copia del
testo completo restano nascosti durante la revisione. Compaiono nel riquadro
"Conferma e condividi" dopo la conferma dell'ultima pagina ancora mancante e
l'aggiornamento dell'anteprima. Confermare soltanto l'ultima pagina numerica non
basta. L'apertura porta una sola volta il focus sul titolo; cambiare pagina senza
modifiche conserva il passaggio disponibile senza rifocalizzarlo. Una modifica
o un annullamento richiude il riquadro e azzera la conferma finale. Le impostazioni
sono visibili soltanto nella schermata iniziale. Nessuna conferma o esportazione
automatica e nessun cambiamento ai controlli server.

QA mirata con PDF sintetico di due pagine: revisione in ordine inverso, passaggio
nascosto fino al completamento, apertura con focus, navigazione senza rifocus,
modifica/Annulla e successiva riconferma verificati. Screenshot desktop/mobile
controllati. Il browser sposta normalmente il focus sul BODY quando Precedente
diventa disabilitato sulla prima pagina; il titolo finale non lo sottrae.
Evidenze in `build/artifacts/ui-final-step-report.json` e screenshot associati.
Nessun overflow a 390 px o errore JavaScript; dieci risposte API HTTP 200.
Controllo sintattico JS e build wheel/sdist con tutti e tre gli asset superati
(`ui-final-step-build-report.json`), senza riavvio né ripetizione della suite core.

### Revisione entro l'altezza del desktop

La GUI condivisa usa una disposizione vincolata all'altezza della finestra su
desktop da 1101 × 650 pixel CSS. Ridotti intestazione, spazi e istruzioni ripetute;
i quattro pannelli occupano lo spazio residuo con scorrimento interno. Navigazione,
conferma e passaggio finale restano nel flusso e non sono tagliati tramite
`overflow: hidden` sul body. Finestre più piccole conservano lo scorrimento normale.

Collaudo Edge su PDF sintetico di due pagine, prima e dopo il passaggio finale:
1920 × 1080, 1440 × 900, 1366 × 768 e 1280 × 720 senza overflow verticale del
documento né orizzontale. Verificati posizione dei controlli, quattro colonne,
note, zoom 200% con scorrimento interno e clic che aggiorna il testo oscurato.
Errore preview simulato HTTP 500, retry HTTP 200; nessun errore JavaScript.
A 390 px verificata l'assenza di overflow orizzontale, non l'adattamento verticale.
Screenshot 1280 × 720 finale e 1440 × 900 revisione ispezionati dall'orchestratore.
Report `build/artifacts/ui-viewport-report.json`; controllo sintattico JS superato.

### Nome del firmatario letto dall'OCR ma non segnalato

Segnalazione sulla quarta pagina del documento locale: a 200 e
300 DPI l'OCR leggeva correttamente il nome, ma non risultavano candidati dal
dizionario o dal NER. Aggiunto un rilevatore deterministico di contesto per nomi
preceduti da titoli medici espliciti, anche con due punti dopo il titolo. Non
modificati modello, soglia NER, DPI predefiniti o numero di inferenze.

La regola genera candidati DOCTOR, livello 1, origine `context:doctor`; gestisce
maiuscole, iniziali maiuscole, diacritici, apostrofi e particelle nei nomi composti.
Richiede almeno due parti nominali, limita la lunghezza e si arresta a indicatori
clinici e di prosa. Non è un riconoscitore universale di firme: nomi minuscoli,
nomi divisi su più righe e contesti non supportati possono ancora sfuggire.

Verifica locale sulla pagina segnalata a 200 e 300 DPI: candidato sul nome intero,
tutti i pixel delle regioni OCR del nome neri dopo l'applicazione delle maschere,
nome assente nel testo oscurato e nessun avviso di geometria incompleta. Report
`build/artifacts/signatory-local-report.json` con soli esiti, senza testo, nomi
o immagini del referto. I test di regressione usano esclusivamente dati sintetici.

Collaudo: 62 test mirati su contesto, dizionario e testo web, più 68 test su regex,
merge, pseudonimizzazione, export visuale e API web, tutti passati. Ruff, controllo
formattazione e sintassi JavaScript puliti. Wheel e sdist includono il nuovo modulo
e i tre asset GUI (`context-package-report.json`). Non ripetuta la suite dei
modelli NER, che non sono cambiati.

Servizio locale riavviato con OCR e NER ONNX pronti. Nuova analisi reale a 300 DPI
tramite il servizio e anteprima della pagina 4 entrambe HTTP 200: tutte le regioni
del nome coperte dalle maschere, nome assente dal testo dell'anteprima. Soli esiti
nel report `signatory-live-report.json`. Le revisioni precedenti al riavvio
richiedono una nuova analisi; nessuna conferma finale o esportazione automatica.

### Conferma unica del documento e attività durante l'analisi

Con una nuova scelta di progetto, la GUI sostituisce la verifica pagina per
pagina con una sola conferma esplicita dell'intero documento. Questa decisione
supera il precedente requisito di confermare tutte le pagine separatamente.
La navigazione rimane libera; aprire tutte le pagine non è un prerequisito per
confermare. La conferma comprende decisioni e note di tutte le pagine, conservando
rifiuti motivati e maschere manuali. Un cambiamento o Annulla/Ripristina annulla
la conferma globale; la sola navigazione la conserva.

Il contratto server rimane invariato: tutte le decisioni devono essere confermate,
le note riconosciute e le geometrie mancanti completate. La GUI raccoglie queste
conferme con un unico gesto e richiede un'anteprima aggiornata prima di abilitare
copia o export. Nessuna conferma finale viene dedotta dalla sola analisi.

L'attività durante l'analisi usa un indicatore indeterminato e una descrizione
dell'operazione. Non essendoci un endpoint con avanzamento per fase, non vengono
mostrate percentuali né tappe simulate con un timer. La preparazione dell'anteprima
è indicata soltanto dopo la risposta di analisi.

Collaudo reale in Edge con PDF sintetico di due pagine a 72 DPI: conferma dalla
prima pagina senza aprire la seconda, copia del testo completo negli appunti e
ZIP con PDF di due pagine e TXT identico al testo copiato. Il PDF esportato non
contiene testo estraibile; il ripristino intenzionale di una maschera automatica
e una nuova maschera manuale restano rispettati. Navigazione senza revoca,
modifica con revoca, Annulla senza ripristino della conferma e deselezione durante
l'aggiornamento dell'anteprima verificati. Nessun errore JavaScript.
Report `build/artifacts/ui-document-report.json`; screenshot di revisione e
conferma a 1280 × 720 controllati dall'orchestratore.

La prova ha rilevato un messaggio di errore analisi fuori vista su finestre basse:
la GUI lo porta ora in vista dopo la scomparsa del loader, soltanto se appartiene
alla richiesta corrente. Errori di richieste superate da un reset non modificano
messaggio o posizione di scorrimento. Modificati solo gli asset condivisi della
GUI: nessun riavvio del servizio richiesto.

Prova UI con risposta sintetica modificata: una geometria incompleta nella seconda
pagina impedisce la conferma dalla prima, apre la pagina interessata e le Note di
lettura, mantenendo copia/export disabilitati. Anteprime simulate per questa sola
prova; non è una verifica di export con contratto modificato. Confermata l'assenza
di overflow del documento a 1280 × 720 e di overflow orizzontale mobile a 390 px,
senza errori JavaScript. Loader e conferma unica ispezionati anche visivamente.

Retest dell'errore superato: loader e messaggio risultano interamente visibili,
con tolleranza di 1 pixel CSS per l'arrotondamento dello scorrimento del browser.
Controllo sintattico JavaScript e build wheel/sdist superati, asset GUI e rilevatore
di contesto presenti in entrambi i pacchetti. Report consolidato
`build/artifacts/ui-document-final-report.json`. Non ripetuta la suite core,
poiché il backend non è stato modificato.

### Prova installata su Debian e assenza di persistenza dei documenti

Il 3 novembre 2026 installata una distribuzione Docker di prova su un server Debian
di sviluppo: Intel Celeron N3000, due core senza AVX,
circa 7,6 GiB RAM. Container limitato a 1,5 CPU e 4 GiB RAM, un thread NER,
Tesseract italiano e GLiNER ONNX FP32 su CPU. Bundle del modello trasferito con
verifica SHA256 di tutti i cinque file; modello montato in sola lettura.
Import e operazioni CPU PyTorch/ONNX Runtime verificati. OCR e NER risultano
entrambi `ready`; nessun ripiego con NER disattivato.

Il servizio ascolta solo su `127.0.0.1:18765` del server. Accesso di prova dal PC
attraverso tunnel SSH su `http://127.0.0.1:8766`; il servizio locale sulla porta
8765 è distinto. Nessuna modifica agli altri container. La GUI condivisa mostra
il luogo effettivo dell'elaborazione e il titolo grande «Anonymizer realizzato
da Gianluca Braccini», verificato visivamente nello screenshot della landing.

Misure HTTP tramite tunnel, con la sola fixture sintetica di due pagine e 2.000
byte, contenente circa 180 caratteri OCR complessivi. Nessun referto reale
trasferito. Non sono misure rappresentative di documenti clinici lunghi o scansioni
complesse, né un test di carico multiutente.

| Operazione | 72 DPI | 300 DPI |
| --- | ---: | ---: |
| Analisi completa | 6,336 s | 8,982 s |
| OCR | 0,906 s | 3,201 s |
| NER | 5,046 s | 5,207 s |
| Anteprime delle due pagine, totale | 0,394 s | 3,777 s |
| Esportazione ZIP con PDF e TXT | 0,492 s | 4,177 s |

Caricamento all'avvio del servizio: 70,86 s nella prima istanza funzionante,
67,61 s dopo l'aggiornamento. Il modello resta caricato tra le richieste.
Picco memoria cgroup della prova finale: 3.169.755.136 byte, circa 2,95 GiB;
nessun OOM o riavvio. Non è un limite superiore per documenti più grandi.

Collaudo API a entrambe le risoluzioni: analisi, anteprima di tutte le pagine,
conferme, testo ed esportazione riusciti. PDF esportati di due pagine senza
testo estraibile; TXT nello ZIP identico a quello dell'endpoint testo. A 300 DPI
sette maschere e sette marcatori nel testo, con i tre nomi sintetici verificati
assenti dal testo oscurato. Collaudo Edge a 72 DPI: conferma unica dalla prima
pagina senza visitare la seconda, export abilitato e ZIP scaricato sul PC;
nessun errore JavaScript.

La prova ha individuato un errore preesistente a 300 DPI: per una pagina Letter
612 × 792 pt, `ceil(points * dpi / 72)` calcolava 2550 × 3300, mentre PDFium,
che moltiplica per la scala già calcolata, produce 2550 × 3301. Allineato l'ordine
delle operazioni in `pdf_geometry`; conservate guardie di coerenza e limiti pixel.
Nove nuovi test verificano pixel, crop, rotazione, mismatch reale e budget;
65 regressioni esistenti su modello visuale, export e API web superate. Ruff
pulito sui file modificati. Rebuild Docker incrementale e `pip check` riusciti;
prova a 300 DPI completata sulla versione corretta effettivamente installata.

Come richiesto, rimangono installati app e modello, ma non documenti o risultati:
filesystem container in sola lettura, `/tmp` verificato come tmpfs da 512 MiB,
`TMPDIR=/tmp`, nessun volume per upload o output, logging Docker disabilitato,
core dump disabilitati e `memory.swap.max=0`. Dopo esportazione riuscita e dopo
richiesta sintetica non valida, nessuna voce temporanea `anonymizer-*` residua.
Input sintetici inviati via HTTP; report e download salvati solo sul PC. Questa
verifica riguarda la persistenza dei file, non l'azzeramento immediato dei buffer
RAM. Artefatti locali: `build/artifacts/debian-trial-e2e-72dpi.json`,
`debian-trial-e2e-300dpi.json`, `debian-trial-ui-72dpi.json` e
`debian-trial-landing.png`; riepilogo di runtime, risorse e pulizia in
`build/artifacts/debian-trial-report.json`. Stato finale Docker `healthy`, zero
PDF e ZIP nella directory di distribuzione e log temporanei di build rimossi.

### Disinstallazione della prova Debian e ritorno in locale

Giudicate insufficienti le prestazioni,
la prova remota è stata abbandonata il 3 novembre 2026. Rimossi il container
Compose della prova, l'immagine app, i 22 record di cache BuildKit attribuiti
all'esperimento (circa 3,059 GB) e la directory
della prova, compreso il modello (circa 1,17 GB).
La rimozione della cache è avvenuta per ID, senza una pulizia globale Docker.
Verificata indipendentemente l'assenza del container e della directory remota.

Chiuso il tunnel SSH locale sulla porta 8766. Il servizio locale sulla porta
8765 è stato riavviato con gli aggiornamenti, Tesseract italiano e il modello
ONNX verificato, quattro thread NER. Health: `execution_location=this_computer`,
OCR e NER `ready`. La stessa fixture sintetica di due pagine a 300 DPI è stata
analizzata tramite HTTP con esito 200 in 0,99 s; non è un benchmark clinico.
App, modello e lavoro del repository locale restano disponibili. Le precedenti
misure Debian documentano un esperimento concluso, non un servizio attivo.

Verifica conclusiva: i dieci container e le dieci immagini estranei alla prova
sono invariati rispetto all'inventario precedente alla rimozione. Nessun
listener su 18765, cache BuildKit residua zero e nessun log della prova sul
server. Report locale `build/artifacts/debian-trial-removal.json`.

### Prototipo Windows con eseguibile e GUI condivisa

Creato `dist/Anonymizer/Anonymizer.exe`: cartella portabile Windows x64, circa
3,20 GB, con 69 dipendenze runtime e 34.411 file nell'inventario SHA256, oltre
all'inventario stesso. Il piccolo launcher PyInstaller 6.22.3 avvia CPython
3.12.13 distribuito nella cartella; pywebview 6.2.1/EdgeChromium mostra gli stessi
asset della webapp. Sono inclusi OCR italiano, modello GLiNER ONNX FP32 verificato,
metadati e licenze. Non si congelano Torch/Transformers dentro un singolo EXE da
estrarre a ogni avvio. Non sono inclusi percorsi editable o dipendenze dalla venv
del checkout. WebView2 e un runtime .NET compatibile restano prerequisiti esterni;
la prova su una macchina Windows pulita non è stata eseguita.

Il backend usa un socket loopback riservato dal sistema e passato a Uvicorn,
indipendente dal servizio locale su 8765. La GUI attende OCR e NER pronti; mostra
un indicatore indeterminato durante l'avvio e messaggi di errore in italiano.
Chiusura tramite segnale privato, attesa limitata e arresto del solo processo
posseduto; il Job Object Windows elimina i figli residui del launcher. Nessun
endpoint pubblico di shutdown. Undici test passati coprono risorse, isolamento,
porta, avvio/chiusura, Job Object reale, copia dei pacchetti e cache precompilate;
Ruff pulito sui moduli aggiunti e sui test.

Su richiesta dell'utente la finestra si apre massimizzata. Il CSS condiviso
compatta la landing nelle viewport desktop da 1101 × 650: mantiene titolo,
credito, controlli e footer; non nasconde l'overflow del body. Finestre piccole
e zoom/accessibilità conservano lo scorrimento normale. La verifica visiva della
versione finale resta da completare: Computer Use è stato fermato con Esc e
non è stato riattivato. Anche copia negli appunti e download nella finestra
nativa non sono stati collaudati fino al completamento. Nel primo tentativo UI
è stato selezionato per errore un file recente non sintetico; la finestra è
stata chiusa prima dei risultati, senza lettura di contenuti né salvataggio di
output o screenshot. Verificati arresto dei processi, rimozione della sessione
temporanea e permanenza del servizio 8765.

Collaudo successivo esclusivamente API, senza finestra, dalla copia completa
fuori dal checkout e con spazi nel percorso: `sys.path` senza repo/venv, runtime
offline e cache isolata. Fixture sintetica di due pagine, 2.000 byte, 300 DPI:
analisi HTTP 200 in 1,258 s (OCR 0,838, NER 0,213), sette maschere e undici note;
anteprima HTTP 200 in 0,595 s; testo in 0,053 s; ZIP in 2,663 s, con membro PDF
riconosciuto dall'intestazione e TXT identico all'endpoint testo, sette marcatori
di oscuramento e due marcatori di pagina. Non è una misura di recall clinico né
un collaudo del download nativo. Arresto pulito, sessione rimossa e porta dinamica
chiusa. Report `build/artifacts/desktop-backend-e2e.json`.

### Diagnosi dell'attesa iniziale di 92 secondi

Nel primo avvio desktop `health.startup_seconds` ha misurato 92,359 s. È il tempo
del lifespan del backend, distinto da copia del pacchetto, apertura della finestra
e analisi di un documento. Non era attiva una traccia per fase di quell'avvio:
la causa specifica dell'episodio non è stata identificata e non va attribuita
senza evidenza ad antivirus, disco, rete o scheduling.

Un profilo successivo senza bytecode precompilato ha misurato 26,101 s nel
percorso di caricamento, di cui 18,186 s per importare GLiNER, 2,605 s per
verificare il modello e 5,096 s per caricarlo. Il builder ora precompila 11.642
moduli, circa 222 MB, con cache checked-hash e nomi sorgente relativi. I sorgenti
restano inclusi; `-I -B` legge le cache senza scriverne di nuove, e una modifica
del sorgente invalida la cache. Nessun controllo del modello è stato rimosso.
Confronto singolo della sola importazione, nella stessa copia rilocata e con
cache del filesystem già usata: 8,596 s senza bytecode e 4,840 s con bytecode.
Questi valori non sono p95 e non spiegano da soli la prima attesa di 92 s.

Avvii completi successivi del backend senza finestra hanno richiesto circa
31 e 19 s; il secondo ha dichiarato 17,206 s di lifespan, circa 18,16 s di CPU
del processo e 3,73 GB di letture logiche cumulative. Le letture del processo
possono essere servite dalla cache: non sono una misura di I/O fisico del disco.

Il wrapper QA `desktop-lifespan-profile.py` ha poi misurato il vero lifespan,
compreso il caricamento nel worker AnyIO, senza server, GUI o documenti:

| Fase | Tempo wall |
| --- | ---: |
| Verifica artefatti, incluso parsing ONNX | 3,164 s |
| Importazione GLiNER | 7,231 s |
| Caricamento modello ONNX | 5,794 s |
| Restante inizializzazione backend | 0,003 s |
| Attesa iniziale del worker | 0,047 s |
| Verifica OCR | 0,043 s |
| Lifespan completo | 16,284 s |

CPU del lifespan: 16,125 s, di cui 10,641 user e 5,484 kernel. Il parsing ONNX,
1,261 s, è già incluso nella verifica artefatti e non va sommato nuovamente.
OCR e NER pronti. Le fasi spiegano quasi tutto questo run; non è emersa una
coda significativa. I 92 s non sono stati riprodotti: resta aperta l'attribuzione
dell'episodio iniziale, e non è dimostrata una garanzia di avvio rapido al primo
uso su altri PC.

Il monitor esterno del wrapper si è bloccato sulla pipe stdout dopo che il
report era già stato scritto: il JSON superava la capacità della pipe non
letta dal parent in attesa. Terminato soltanto il figlio diagnostico già inattivo;
nessun secondo caricamento. La traccia delle fasi è integra, ma i campioni I/O
esterni non sono stati salvati. Questo errore dell'harness non è la causa dei
92 s del prodotto, che usa stdout/stderr su DEVNULL. Artefatti locali:
`desktop-motor-profile.json`, `desktop-import-ab.json` e
`desktop-lifespan-profile.json`, sotto `build/artifacts/`.

### Migrazione della finestra desktop a Qt (2026-11-03)

Per scelta di progetto, il contenitore pywebview/WebView2 viene sostituito
da PySide6 6.12.0 e QtWebEngine. La GUI HTML/CSS/JavaScript e il servizio Python
restano condivisi con la webapp; il servizio desktop usa la propria porta
loopback dinamica. Il nuovo pacchetto è distinto, `dist/Anonymizer-Qt`, e include
le dipendenze Qt. Il builder esclude pywebview, pythonnet e clr-loader e non
richiede .NET o WebView2 come prerequisiti.

Il contenitore usa un profilo Qt anonimo off-the-record, cache in memoria e
nessuna persistenza di cookie o permessi. Le richieste sono limitate all'origine
locale della sessione e alle risorse inline necessarie. Popup, navigazione
remota e lettura programmatica degli appunti sono disabilitati. La scrittura
sanificata negli appunti serve ai pulsanti Copia della GUI. Le esportazioni
richiedono un percorso scelto dall'utente e passano da un temporaneo di sessione;
non sovrascrivono file preesistenti. La chiusura annulla i download in corso e
arresta il servizio; il launcher mantiene la gestione dei figli con Job Object.

Le wheel Qt installate dichiarano alternative LGPL/GPL nei metadati ma allegano
solo il testo commerciale nelle rispettive directory di licenza. La raccolta
aggiuntiva sotto `licenses/qt` conserva documenti ufficiali e provenienza, senza
costituire una certificazione di completezza per la distribuzione finale.
Il cambio di contenitore non modifica il costo OCR/NER né spiega l'episodio
iniziale di avvio da 92 secondi.

Verifica dei sorgenti congelati: 44 test passati in 4,81 s per desktop,
Qt offscreen, API web ed esportazione testuale; Ruff pulito. I test Qt usano
il motore WebEngine reale senza disabilitare la sandbox e comprendono download
Blob, copia con gesto utente simulato, rifiuto della lettura degli appunti,
interruzione dei download, protezione da sovrascrittura e chiusura durante
l'avvio con risposta tardiva. La clipboard verificata è quella del backend
offscreen: il test non controlla la clipboard Windows dell'utente. Nessuna
automazione della GUI utente è stata ripresa dopo il precedente Esc.

Verifica diretta con `dist/Anonymizer-Qt/runtime/python.exe -I -B`: Qt 6.12.0,
Chromium 140.0.7339.225, nessun import disponibile per `webview`, `pythonnet` o
`clr_loader`, nessun percorso del checkout nel `sys.path`. Il manifest elenca
68 dipendenze e nessun prerequisito .NET/WebView2. Le DLL Visual C++ delle wheel
Qt sono presenti nel pacchetto. La cartella, prima di eventuali avvisi aggiuntivi,
contiene 38.160 file per 3.873.481.127 byte; non è stato prodotto un installer.

Smoke del pacchetto copiato fuori checkout in una cartella temporanea
dell'utente, con percorso contenente
spazi, Python incluso, `-I -B`, PATH ridotto a Windows e Job Object del launcher:
uscita 0, profilo off-the-record, nessun flag di disattivazione sandbox,
caricamento della landing riuscito. Il backend era uno stub della sola health,
con asset reali del bundle: nessun documento e nessun caricamento OCR/NER.
A 1440×900 e 1366×768 il DOM riporta scrollHeight uguale all'altezza del viewport,
con titolo, pulsante Analizza e badge entro i limiti. Alla chiusura: zero nuovi
QtWebEngineProcess residui, zero file nella sessione e directory rimossa.
Report: `build/artifacts/qt-portable-offscreen.json`.

Le PNG prodotte da `grab()` nel backend offscreen sono uniformi: non costituiscono
verifica visiva del contenuto Chromium. Restano da completare il collaudo della
finestra Windows reale, delle finestre native di apertura/salvataggio e della
clipboard di sistema, oltre alla prova su un PC Windows pulito. Il test DOM
non sostituisce questi controlli.

Il tentativo separato di estrarre `chrome://credits` ha restituito
`ERR_INVALID_URL`: la pagina diagnostica è conservata fuori dalla directory
licenze, come `build/artifacts/qt-credits-unavailable.html`. Non è un elenco
di crediti Chromium. I sette file aggiuntivi sotto `licenses/qt` sono quattro
testi LGPL/GPL ufficiali Qt/PySide 6.12, due pagine ufficiali di riferimento
e il registro di provenienza. La completezza degli avvisi dei componenti
terzi rimane da verificare prima della distribuzione finale.
Sorgente Qt e bytecode checked-hash sono stati sincronizzati nella build e
nella copia QA e verificati contro entrambi i manifest.

### Marchio e icona dell'app (2026-11-03)

Creato il marchio vettoriale originale `src/anonymizer/web/static/anonymizer.svg`:
documento bianco con angolo menta e due barre di oscuramento su tile petrolio.
Il nome e il credito a Gianluca Braccini restano testo HTML. Il simbolo compare
nell'header, accanto al titolo iniziale, nella favicon e nel caricamento Qt.
Lo stesso disegno genera PNG trasparenti 256/512 e ICO con nove dimensioni
(16, 20, 24, 32, 40, 48, 64, 128, 256) tramite `tools/packaging/windows/build_icons.py`.
Qt riceve l'icona di applicazione/finestra; il processo host Windows imposta
`GianlucaBraccini.Anonymizer` come AppUserModelID prima di QApplication.

Ricostruito solo il launcher con `--icon`, aggiornati asset, sorgenti desktop,
bytecode checked-hash e manifest nella build Qt e nella copia QA. Nessuna
ricostruzione o modifica del modello OCR/NER. Verifica PE: nove RT_ICON e un
RT_GROUP_ICON; QIcon del runtime incluso produce pixmap valide a 16/32/48/256.
Anteprima PNG ispezionata visivamente. Asset SVG/PNG/ICO serviti con HTTP 200
dalla webapp locale; DOM offscreen a 1440×900 e 1366×768 senza overflow verticale,
con immagini header/hero caricate e titolo visibile. Le catture Qt offscreen
non sono usate come prova visiva. I 44 test desktop/Qt/web pertinenti passano
e Ruff è pulito; non sono stati aggiunti test per le sole forme del logo.
Report: `build/artifacts/branding-verification.json`.

### Raccolta di referti pubblici per QA locale (2026-11-03)

Preparata `tools/test-data/referti-online/`, esclusa da Git e dal pacchetto desktop:
tre PDF (ECG HTN di 1 pagina, InTestinal 360 di 26 pagine, profilo ormonale
Natrix pubblicato da Farmacia Dova di 8 pagine), due PNG dimostrativi ClaraMed
e un JPEG OCT Spectralis pubblicato in Clinical Insights in Eyecare.
Le immagini sono download originali, non rasterizzazioni dei PDF. L'asset OCT
ha URL con suffisso PNG ma contenuto JPEG, conservato come JPG senza ricodifica.

Il catalogo locale `README.md` descrive copertura e prove suggerite;
`manifest.json` registra URL, formato, byte, SHA-256, pagine/dimensioni,
motivazione della selezione e condizioni di riuso note. Verificati apertura
e formato dei file; ispezionate anteprime dei PDF e le tre immagini.
ClaraMed dichiara dati fittizi; ECG e Spire sono facsimili, il profilo ormonale
è collegato come esempio e l'OCT ha campi anagrafici vuoti. Un'altra figura
OCT è stata esclusa dopo controllo visivo degli identificativi residui.

Questa attività prepara i dati: non misura prestazioni o accuratezza
dell'anonimizzatore. Non è stato eseguito un ciclo completo analisi/revisione/
esportazione con questi campioni. ECG e OCT già deidentificati servono
soprattutto per importazione e falsi positivi; i PNG consentono di verificare
anche il nome del medico nella firma a fondo pagina. Mancano una verità di
riferimento annotata e casi con fotografie degradate, radiografie o DICOM.

### Nome paziente dopo etichetta esplicita (2026-11-03)

Corretto il caso ClaraMed `Cognome e nome Rossi Demo Data ...`: la pipeline
aggiunge un candidato PERSON dopo etichette composte come `Cognome e nome`
e `Nome e cognome`, con varianti delimitate, nomi Unicode e particelle.
La regola non dipende da NER o dal dizionario e si arresta alle etichette
delle colonne successive. Non attribuisce automaticamente un'identità.

118 test mirati passati e Ruff pulito. OCR reale sulle PNG amber e blue,
con NER disabilitato per isolare la regola: nome oscurato nel TXT e nei
box del raster esportato. Su amber i tre box adiacenti di data/unità
restano pixel-identici; zero pixel modificati fuori dalle maschere.
Il confronto pre-fix è un replay controllato con il solo nuovo detector
disabilitato in memoria, perché la correzione era già presente al primo run.
Report valido: `build/artifacts/patient-label-before.json`, raster
`patient-label-before-simulated.png`; post-fix `patient-label-after.json/png`
e controllo aggiuntivo `patient-label-blue.json/png`. Il file intermedio
`patient-label-before.png` non rappresenta il comportamento precedente.

Questo controllo verifica il caso segnalato e la sincronizzazione testo/raster,
non costituisce una misura generale di copertura del riconoscimento nomi.

### Confronto sincronizzato e zoom (2026-11-03)

La GUI condivisa web/Qt usa un solo controllo verticale per immagini originali,
oscurate e testi laterali. L'anteprima aggiunge righe con coordinate e versioni
originale/oscurata derivate dallo stesso footprint raster usato dal testo
completo. Quest'ultimo mantiene il contratto precedente per copia ed export.
Le righe senza coordinate sono indicate esplicitamente; nessun valore non
localizzato viene esposto nella versione oscurata.

La sincronizzazione usa una mappa monotona tra righe leggibili e coordinate
del documento, con spazio aggiuntivo quando il testo richiede più altezza.
Lo zoom condiviso (100–500% rispetto alla larghezza adattata) offre pulsanti
meno/più, Adatta larghezza e Ctrl+rotella; il punto osservato viene mantenuto
entro i limiti di scorrimento. Pan e trasformazioni sono comuni alle immagini.
La corsa considera anche il pannello testo più corto per rendere raggiungibili
le ultime righe; cambio pagina e nuova analisi azzerano la posizione.

Regressioni Python verificate per maschere sovrapposte, Unicode, geometria
assente, poligoni e ripristini: le righe dell'anteprima mantengono le stesse
decisioni di oscuramento del testo completo. La suite integrata rilevamento,
web, testo, esportazione e compattazione ha passato 140 test prima degli ultimi
tre test specifici sulle righe; la suite web/testo aggiornata passa 27 test.
Probe QtWebEngine offscreen sul portable rilocato `Anonymizer Qt QA` con
fixture e API sintetiche a 1366×768 e 1440×900: una scrollbar verticale
effettiva, nessuno scroll del body, frame allineati, righe dense e sparse
collegate alle coordinate, ultima riga e fondo immagine raggiungibili.
Verificati wheel da immagini/testi, Home/End, zoom con errore di ancoraggio
inferiore a un pixel sorgente, pan condiviso, click/ripristino, rettangolo
manuale, cambio pagina e reset; zero errori JavaScript. Report:
`build/artifacts/comparison-geometry-qa.json`. La verifica usa geometrie DOM
e input Qt; le catture offscreen uniformi non sono prova visiva del rendering.

Sincronizzati in `dist/Anonymizer-Qt` e nella copia QA corretta i quattro
moduli Python (`detect/context`, `text_pipeline`, `web/text`, `web/app`),
bytecode checked-hash, i tre asset HTML/CSS/JS e gli hash in `bundle.json`.
Il servizio locale già aperto non è stato riavviato e le analisi esistenti
non sono state modificate: per usare il codice aggiornato occorre riaprire
l'applicazione ed eseguire una nuova analisi.

### Falsi positivi nel referto ormonale e scorrimento orizzontale (2026-11-03)

Riprodotti sulle pagine 3–4 del campione ormonale, con OCR a 300 DPI e GLiNER
ONNX locale, quattro thread e soglia 0,5, due candidati LOCATION su `placenta`
e quattro PERSON su ruoli generici (`medico curante`, `medico`, `specialista`).
Nessun altro rilevatore concorreva a quelle proposte. Nel primo caso il box OCR
comprende anche `Interviene`, quindi oscurare il candidato parziale oscurava
l'intera parola OCR. Baseline: `build/artifacts/clinical-fp-baseline.json`.

Introdotta `clinical_context_v2`: mantiene la protezione dei punteggi VAS/NRS
ed esclude soltanto ipotesi NER del tipo atteso, interamente comprese in termini
minuscoli con contesto clinico/grammaticale esplicito. Non è una lista globale
di parole da lasciare in chiaro. Candidati estesi, nomi propri e rilevatori
indipendenti L0–L2 restano invariati; gli audit `none` e `pain_scores_v1` restano
leggibili. Supportato un solo a capo nel trigger, compreso `del\nmedico curante`.

Il primo replay ONNX sulle stesse OCR ha rimosso cinque dei sei falsi positivi
e mantenuto l'oscuramento del nome paziente. Il sesto, dovuto all'a capo OCR,
ha motivato la correzione aggiuntiva: verificati tutti i sei intervalli della
baseline contro la guardia finale. 65 test NER/ONNX passati (due smoke del
modello non configurati nella suite saltati); altri 111 test su contratti,
web, testo e nomi contestuali passati. Nessuna modifica a modello o soglia.

La GUI aggiunge una barra orizzontale comune sotto le due immagini centrali,
visibile quando lo zoom produce overflow. Condivide lo spostamento con pan,
rotella orizzontale e Shift+rotella; Adatta/reset ripristinano l'origine.
Le colonne di testo non vengono traslate orizzontalmente.

Verifica finale: il replay delle sei predizioni ONNX salvate, applicando la
guardia corrente e la generazione delle maschere, lascia zero candidati e zero
maschere riferite a questi falsi positivi. Non è una nuova inferenza del modello:
tipo e limiti del controllo sono in
`build/artifacts/clinical-fp-cached-replay.json`.
La prova QtWebEngine usa gli asset della copia QA e verifica scorrimento nativo
verso entrambi gli estremi, allineamento delle immagini, testo fermo e Adatta/reset;
nessuna chiamata manuale al gestore scroll. Esito positivo e zero errori JavaScript
in `build/artifacts/comparison-geometry-qa.json`.
Sincronizzati i due moduli NER, bytecode checked-hash, tre asset statici e manifest
nel bundle `dist/Anonymizer-Qt` e nella copia `Anonymizer Qt QA`.

### Referto intestinale e allineamento iniziale (2026-11-03)

Il campione pubblico `referto-intestinal-360-facsimile.pdf` contiene 26 pagine A4:
a 300 DPI richiede 226.287.048 pixel complessivi. Il preflight falliva alla
pagina 18 con `total_pixel_limit`, prima di OCR e NER, per il precedente limite
di 150 milioni di pixel. Baseline: `build/artifacts/intestinal-preflight.json`.
Il limite predefinito passa a 300 milioni, sufficiente per le 30 pagine A4
consentite a 300 DPI (circa 261 milioni). Restano invariati i limiti di pagine,
file, byte e pixel per singola pagina; la risoluzione scelta non viene ridotta.
Le immagini sono elaborate e chiuse pagina per pagina. I limiti personalizzati
continuano a essere rispettati. Errori di dimensione, pagine e numero di file
hanno ora messaggi specifici nella GUI.

Lo stato nella pagina iniziale ha la stessa larghezza massima di 730 px del
riquadro di caricamento, con testo lungo a capo; lo stile della revisione resta
invariato. Passati 51 test su geometria, esportazione e API web, comprese quattro
regressioni su 30/31 pagine, limite cumulativo e limiti personalizzati.

Prova reale completa, OCR italiano e GLiNER ONNX locale con quattro thread:
26 pagine analizzate a 300 DPI in 75,16 s (OCR 37,19 s; NER 35,69 s), oltre
a 10,39 s di caricamento iniziale del modello. Anteprime di pagina 1 e 26
riuscite; esportazione di tutte le 26 pagine riuscita in 14,44 s, PDF di
23.661.570 byte. Picco working set campionato del processo circa 2,56 GB,
esclusi eventuali processi OCR figli. Per esercitare l'esportatore il solo
manifest della prova è stato confermato automaticamente: questo non certifica
la correttezza clinica di ogni oscuramento. Nessuna modifica a revisioni utente.
Il risultato esportato temporaneo è stato rimosso; rimane il report numerico
`build/artifacts/intestinal-full-smoke.json`. La prova conferma la rimozione
del blocco, non una riduzione dei tempi di elaborazione.

Unificati i due avvisi di analisi in corso in un solo `#message` con indicatore
animato: il duplicato provocava scorrimento verticale durante il lavoro.
Probe QtWebEngine sui file del bundle QA aggiornato: stato di analisi a
1366×768 e messaggio reale `total_pixel_limit` di 174 caratteri a 1366×768
e 1440×900. Stato allineato a 730 px; errore disposto su due righe, misurate
con `Range.getClientRects`, senza overflow orizzontale né scroll del documento;
zero errori JavaScript. Report: `build/artifacts/comparison-landing-status.json`.
Sincronizzati modulo dei limiti, bytecode checked-hash, HTML/CSS/JS e manifest
in `dist/Anonymizer-Qt` e nella copia `Anonymizer Qt QA`; hash verificati contro
i sorgenti e i rispettivi manifest. Per applicare le modifiche serve riaprire
l'app e ripetere l'analisi; nessun processo utente è stato riavviato.

### Riferimenti per regole generali di de-identificazione (2026-11-03)

Ricerca richiesta dall'utente durante la correzione dei falsi positivi nel
referto intestinale. Sono distinti lo schema delle categorie da oscurare,
i riconoscitori riutilizzabili e la validazione sul dominio italiano:

- [i2b2/UTHealth 2014](https://pmc.ncbi.nlm.nih.gov/articles/PMC4978170/):
  linee guida e annotazioni distinguono nomi di pazienti e medici, strutture,
  luoghi, contatti e identificatori. Sono un riferimento per definire e valutare
  la policy, non un insieme di regex direttamente eseguibili. Le varianti di
  policy dei dataset non vanno scambiate per obblighi normativi italiani.
- [Presidio, riconoscitori supportati](https://presidio.dataprivacystack.org/supported_entities/):
  identificatori italiani come codice fiscale e partita IVA, oltre a contatti
  e altri formati, con combinazioni di pattern, contesto e checksum. La
  documentazione ufficiale, consultata anche tramite Context7, distingue il
  supporto dei formati italiani dalla configurazione del modello linguistico
  per nomi e località. Valutare riuso mirato dei riconoscitori, senza presumere
  che l'installazione risolva automaticamente le ambiguità dei referti italiani.
- [UCSF Philter](https://github.com/BCHSI/philter-ucsf) e
  [configurazione pubblicata](https://github.com/BCHSI/philter-ucsf/blob/master/configs/philter_delta.json):
  regole positive e negative, contesto e vocabolari per il testo clinico.
  La configurazione contiene anche pattern inglesi e specifici UCSF; non è
  trasferibile integralmente ai nostri referti. Il metodo di preservazione del
  contenuto clinico è utile come confronto, senza blacklist create sul campione.
- [pyDeid](https://github.com/GEMINI-Medicine/pyDeid): altra implementazione
  Python con regex, dizionari e possibilità di integrare nomi noti e NER.
- [Studio CLiC-it 2025 sul testo clinico italiano](https://aclanthology.org/2025.clicit-1.70/):
  riferimento per la valutazione sul dominio, con 80 note italiane annotate;
  non prova di copertura generale dei PDF e delle immagini del prodotto.

Il [resoconto i2b2 2014](https://pmc.ncbi.nlm.nih.gov/articles/PMC4989908/)
descrive anche sistemi a due passaggi che riutilizzano le entità riconosciute
nei documenti per trovare ripetizioni: il criterio di propagare una denominazione
completa dal contesto esplicito ha quindi precedenti metodologici. Nessun nome
di struttura o indirizzo del campione deve entrare nelle regole applicative.
Non sono state installate nuove dipendenze sulla base della sola ricerca.

### Contesto clinico e blocchi del referto intestinale (2026-11-03)

La guardia `clinical_context_v4` riconosce costruzioni grammaticali di ruolo
come «del medico curante/specialista di riferimento», «al medico o allo
specialista» e «il paziente». Scarta soltanto predizioni PERSON del NER
interamente comprese in questi ruoli generici; non esclude globalmente le
parole e non sopprime identità note o riconoscimenti deterministici.

I blocchi OCR separati da ampi spazi verticali vengono analizzati separatamente
dal NER, conservando gli offset nel testo originale. Questo evita di fondere
logo, titolo centrale e piè di pagina in un'unica struttura. Le righe vicine,
anche con nomi su due righe, restano insieme. Il criterio usa proporzioni delle
coordinate, non nomi, numeri di pagina o misure specifiche del campione.

Il riconoscimento dei contatti combina denominazioni mediche, forma societaria,
etichette e recapiti; gli indirizzi richiedono una tipologia di strada e un
numero civico. Le denominazioni complete trovate in contesti espliciti vengono
cercate anche nelle altre pagine, senza propagare singole parole ambigue.
Sono gestite le varianti OCR della forma societaria. Nessuna denominazione
del campione è inserita nelle regole.

Verifica iniziale: 207 test passati e 2 opzionali saltati sui rilevatori; altri
60 test passati su contratti, API web, testo, esportazione e compattazione delle
maschere. Il replay delle predizioni già raccolte sul campione pubblico di
26 pagine elimina i cinque falsi positivi di ruolo riprodotti e copre tutte
le 43 occorrenze della denominazione completa, oltre a struttura e indirizzo
nei 26 piè di pagina. Report: `intestinal-detection-postfix.json` e
`intestinal-detection-current-replay.json` in `build/artifacts/`.
CAP e città risultano coperti anche nell'ultima pagina: lì sono due
sostituzioni distinte, perciò il contatore che richiedeva una sola
sostituzione per l'intera frase riportava 25/26. La copertura dei riquadri
della frase e delle città è 26/26.

Una nuova inferenza GLiNER è stata eseguita soltanto sulla pagina 9, usando
l'OCR già disponibile: tre sezioni da 229, 10 e 154 caratteri; 0,257 s di NER,
oltre a 11,39 s di caricamento del modello. «RISULTATI» resta nel testo e non
interseca maschere; logo e denominazione nel piè di pagina sono oscurati sia
nel testo sia nei relativi riquadri. Questo dato non è un benchmark completo
né una nuova inferenza sulle altre 25 pagine. Le vecchie predizioni che
attraversavano i nuovi confini sono escluse dal replay e non dimostrano da
sole il risultato di una nuova analisi di quelle pagine.

Gli oscuramenti delle parole «referto» e «analisi» segnalati dall'utente non
sono stati riprodotti direttamente nel baseline di questo campione. Non è
stata aggiunta una lista globale di parole da lasciare sempre leggibili.

### Integrazione delle regole pubbliche (2026-11-03)

Integrati in `detect/structured.py` i pattern email, IBAN e URL provenienti
da Presidio, revisione `05b60e1a6805f3b2c0ad6cbe7526ccd226647971`.
Il JSON di provenienza è letto dai riconoscitori a runtime. Verificati gli
hash dei quattro sorgenti e, tramite lettura AST senza eseguire i sorgenti
scaricati, la corrispondenza esatta dei tre pattern e dei 76 formati nazionali
IBAN. Gli adattamenti locali sono documentati in `third-party-rules.md`.

Non sono aggiunti servizi, modelli o dipendenze Python. Le licenze MIT di
Presidio e CommonRegex sono incluse nei dati del package; sia `pyproject.toml`
sia il costruttore del bundle Windows includono i file `.txt`.
I test mirati riportano 179 passaggi; dopo la rifinitura dei confini URL,
rieseguiti i 44 test dei nuovi moduli con esito positivo. Ruff pulito.
I controlli comprendono Unicode, punycode, simboli nel nome email, limiti dei
candidati, checksum IBAN e relativa policy prudenziale, separazione tra righe,
URL con suffissi lunghi, porta/query/frammento, punteggiatura finale e
collegamenti bibliografici esterni ai blocchi contatto.

Misura dei soli riconoscitori deterministici sul testo OCR già estratto dal
campione pubblico: 26 pagine, 59.694 caratteri, cinque passaggi dopo un
riscaldamento; mediana 0,046 s, 225 candidati. Nessuna esecuzione OCR o NER.
La misura riguarda regole e contesto nel loro insieme, non il costo
incrementale rispetto alla versione precedente né il tempo totale dell'app.
Report numerico: `build/artifacts/presidio-cached-text-timing.json`.

Passati inoltre 50 test di integrazione su contratti, fusione dei candidati,
esportazione visuale e testo web (9,43 s). Sincronizzati moduli, risorse e
licenze nel bundle `dist/Anonymizer-Qt` e nella copia `Anonymizer Qt QA`.
Verifica indipendente sui 15 file interessati per ciascuna copia: hash dei
sorgenti uguale alla copia e al manifest, bytecode CPython 3.12 checked-hash
con flag e hash del sorgente corretti. Nessun riavvio di processi utente.
Smoke in processi isolati avviati con entrambi i runtime distribuiti:
caricamento del JSON e riconoscimento di email, IBAN e URL nel contesto
struttura riusciti. Provata anche `build_portable.copy_app`: i sei file
nuovi/modificati di sorgente e dati, incluse le due licenze, sono copiati.
Report: `build/artifacts/presidio-bundle-sync.json`.

### Adattamento italiano delle regole cliniche Philter (2026-11-04)

La guardia NER passa a `clinical_context_v5`; le versioni precedenti restano
accettate nella lettura dei dati di audit. Il modulo `detect/clinical.py`
carica 12 regole dal JSON del package: 11 adattamenti di regole Philter e una
estensione locale per intestazioni documentali italiane. Sono verificati
hash e testo originale dei 13 pattern sorgente referenziati. La selezione,
gli adattamenti e la licenza BSD sono descritti in `third-party-rules.md`.

Le nuove etichette comprendono medico curante/di riferimento/refertante,
firma e validazione, oltre ai campi paziente con separatore esplicito. Il
parser riusa i confini Unicode, le particelle e i limiti dei nomi esistenti;
non cattura segnaposto, campi vuoti o istruzioni di stato. La revisione ha
incluso cognomi con particelle iniziali Da/Al nell'ordine cognome-nome,
anche in maiuscolo, distinguendoli da «DA VALUTARE DOMANI».

Le regole safe operano soltanto sulle predizioni NER completamente contenute
nel contesto clinico riconosciuto. Le intestazioni richiedono l'intera riga
e sono verificate con terminatori LF, CRLF e CR. Nomi aggiunti alla stessa
riga, predizioni che attraversano intestazione e nome, identità note e
rilevamenti deterministici non sono esentati.

Verifica mirata iniziale: 235 test passati e un test opzionale saltato;
dopo gli ultimi casi sulle particelle iniziali, 58/58 test delle nuove
regole passati e Ruff pulito. Un controllo indipendente aggiunge 28 casi
sintetici, tutti passati anche dopo la rifinitura finale: 16 scenari con
vocabolario vuoto per esercitare le regole senza riconoscimento fortuito
dei nomi, 11 decisioni NER simulate e una verifica di precedenza
dell'identità nota. Questi test simulati non misurano l'accuratezza del
modello reale. Report: `build/artifacts/philter-advisor-results.json`.

Ulteriori test di integrazione: 63 passati, uno opzionale saltato. Prova
fresca del modello GLiNER ONNX, quattro thread e una sola istanza, su quattro
brevi pagine sintetiche: medico con nome, firma, misure/pressione/dolore,
intestazione con struttura e indirizzo. Nomi e recapiti attesi sono rimossi
nel testo e coperti dalle maschere; misure e intestazione restano leggibili.
Nessun avviso geometrico. Le coordinate delle parole sono sintetiche: non
è una nuova prova OCR. Tempo di caricamento 15,10 s, analisi dei quattro
testi 0,251 s; non rappresenta un benchmark di documenti completi.
Report: `build/artifacts/philter-synthetic-ner.json`.

Replay delle 26 pagine pubbliche usando il testo OCR e le predizioni NER
precedentemente memorizzate: restano leggibili i cinque ruoli clinici già
verificati e rimane completa la copertura selezionata di strutture, vie,
città e contatti nel testo e nei riquadri. È confermata la distinzione delle
due sostituzioni CAP/città nella pagina finale, già descritta sopra.
Le predizioni storiche che attraversano i nuovi confini delle sezioni non
costituiscono evidenza di una nuova inferenza su quelle sezioni. Il replay
non sostituisce una valutazione del modello su tutti i referti reali.
Report: `build/artifacts/philter-cached-replay.json`.

Sullo stesso testo di 59.694 caratteri, il passaggio deterministico senza
OCR e senza NER richiede una mediana di 0,081 s su cinque misure dopo un
riscaldamento. Il dato riguarda l'insieme delle regole e della pipeline di
testo, non il tempo complessivo dell'app né il solo filtro delle predizioni
NER, che in questa misura è disabilitato.

Bundle Qt e copia QA aggiornati con quattro moduli, quattro bytecode
checked-hash e due risorse (JSON e licenza). Verifica indipendente sui dieci
file di ogni copia: sorgente, copia e manifest coincidono; flag del bytecode
e hash del sorgente sono corretti. Smoke isolati avviati con ciascun runtime
distribuito confermano il caricamento delle 12 regole, gli oscuramenti di
nomi e contatti e la conservazione dei contenuti clinici controllati.
Nessun processo utente è stato riavviato. Report:
`build/artifacts/philter-bundle-sync.json`.

### Esecuzione adattiva e confronto prestazioni — 2026-11-04

Richiesta: ottimizzare senza cambiare modello, bilanciando thread e concorrenza
in base all'hardware. La pipeline ora può sovrapporre OCR e NER su pagine diverse
con un solo modello, un solo produttore PDFium/OCR e una coda di una pagina di
testo/coordinate. Le immagini sono chiuse prima dell'accodamento. La fusione
finale conserva le regole documentali e riutilizza le predizioni già calcolate.
I dettagli operativi sono in [performance.md](performance.md).

Il riferimento precedente è congelato in
`build/artifacts/performance-baseline-src`, con manifest SHA-256
`6a691daf53a7e819543c3fadac65d5fc70a35805af2e199a62592a2fe8987363`.
Le prove usano lo stesso referto pubblico Intestinal, 26 pagine, 300 DPI,
226.287.048 pixel e lo stesso modello ONNX FP32. Macchina di sviluppo:
Intel Core Ultra 7 155H, 16 core fisici/22 logici, circa 32 GiB di RAM.

| Esecuzione | Thread NER/OCR | Analisi | OCR | NER |
| --- | --- | ---: | ---: | ---: |
| Misura storica, precedente alle ultime regole | 4/4, sequenziale | 75,16 s | 37,19 s | 35,69 s |
| Snapshot attuale, prima misura | 4/4, sequenziale | 204,90 s | 95,51 s | 102,62 s |
| Snapshot identico, seconda misura | 4/4, sequenziale | 116,36 s | 49,06 s | 64,32 s |
| Prima configurazione sovrapposta | 8/1 | 102,48 s | 90,43 s | 59,63 s |
| Ripetizione con limiti nativi allineati alla desktop | 8/1 | 102,33 s | 90,61 s | 59,97 s |

Questi tempi escludono il caricamento del modello e l'anteprima. Le fasi
sovrapposte non si sommano. La variazione 204,90→116,36 s dello stesso snapshot
impedisce di attribuire causalmente al codice un miglioramento stabile del 50%.
Una prova precedente aveva misurato circa 72 s: 102 s non
soddisfano quel riferimento. L'origine della variabilità non è ancora isolata;
un controllo locale rileva alimentazione presente, piano Prestazioni elevate e
nessuna seconda inferenza avviata dagli agenti durante i benchmark.

Le due configurazioni 8/1 conservano gli stessi fingerprint canonici di testo,
8.536 regioni OCR, candidati con confidenza, fusione, geometria, maschere e avvisi.
Conteggi: 521 candidati, 400 intervalli fusi, 776 maschere, 187 avvisi. Gli ID
casuali sono esclusi dal confronto. Picco di memoria osservato per il processo
di analisi circa 2,55 GB; non è un limite massimo garantito.

Prova OCR isolata sulla medesima bitmap della pagina 3, ordine 1/2/4/4/2/1:
medie 2,330/2,253/2,254 s. Tutte le 349 regioni e il testo coincidono. Quattro
thread non danno vantaggio misurabile rispetto a due su questa pagina; la sola
limitazione a un thread non spiega il raddoppio OCR osservato sotto concorrenza.

Report numerici, senza testo clinico nei nuovi risultati:
`build/artifacts/performance-baseline.json`,
`build/artifacts/performance-baseline-structure.json`,
`build/artifacts/performance-auto.json`,
`build/artifacts/performance-auto2.json`,
`build/artifacts/performance-ocr-thread-sweep.json`.

Verifiche funzionali: suite completa con 555 test superati e 5 opzionali saltati;
Ruff e sintassi JavaScript validi. I nuovi casi coprono budget CPU/RAM, affinità
e quota cgroup, fallback conservativo, override espliciti, ordine delle pagine,
assenza di doppia inferenza, regole documentali, pressione sulla coda, chiusura
delle immagini, errori del produttore/consumatore e rifiuto di richieste
concorrenti mentre il NER è attivo.

Confronto aggiuntivo sulle pagine 3, 4, 12 e 26 dello stesso documento, scelte
prima delle prove e ricomposte soltanto in memoria:

| NER/OCR sovrapposti | Tempo totale | OCR | NER |
| --- | ---: | ---: | ---: |
| 8/1 | 21,82 s | 14,80 s | 12,37 s |
| 8/2 | 24,09 s | 17,21 s | 12,87 s |
| 4/2 | 22,08 s | 12,78 s | 15,48 s |

Un modello a otto thread è riutilizzato per le prime due prove; la terza usa
un processo separato a quattro thread, senza due modelli contemporaneamente.
Tutti i fingerprint coincidono. Il campione non sostiene l'aumento automatico
dei thread OCR: resta il profilo conservativo 8/1 su questa macchina. Non è
una ricerca esaustiva del miglior bilanciamento per ogni hardware.

Una prova diagnostica separata imposta HighQoS soltanto nel processo benchmark
Windows, mantenendo 8/1: 19,15 s sullo stesso sottoinsieme, con output identico.
La richiesta di impostazione riesce ma la verifica tramite lettura API fallisce;
la singola misura non isola l'effetto rispetto alla variabilità già osservata.
**Nessuna impostazione QoS, priorità o piano energetico viene aggiunta al prodotto.**
Report: `build/artifacts/performance-profile-8x.json`,
`build/artifacts/performance-profile-4x2.json`,
`build/artifacts/performance-qos-8x1.json`.

Conclusione prestazionale: implementazione adattiva verificata, ma il riferimento
utente di circa 72 s non è stato migliorato nelle prove complete di oggi. Non
viene dichiarata risolta la lentezza né un'accelerazione stabile del 50%.

Bundle Qt e copia QA aggiornati con sette moduli, sette cache checked-hash e
JavaScript condiviso. La verifica indipendente conferma, su entrambe le copie,
hash sorgente/copia/manifest, flag 3 dei bytecode, hash del sorgente e percorsi
di compilazione relativi. I due runtime isolati importano tutti i moduli dal
rispettivo pacchetto; nessuna dipendenza dal checkout.

Smoke finale indipendente tramite il vero launcher backend Python della desktop
(`Backend.start`, runtime QA `pythonw.exe -I -B -m anonymizer.desktop`): servizio
pronto in 16,32 s, lifespan 15,19 s, OCR/NER pronti, profilo 12/8/1 con overlap,
audit coerente con i thread configurati. Una PNG sintetica produce HTTP 200,
una pagina e due maschere in 0,241 s. È una verifica d'integrazione, non una
misura di velocità sui referti. Il processo di prova viene arrestato normalmente
e la directory temporanea eliminata; nessun riavvio di processi utente.

Un precedente harness QA avviava direttamente il server e aveva misurato circa
71 s all'avvio: non usa lo stesso percorso di startup della desktop e non è
un confronto controllato con i 16,32 s. Nessuna promessa di avvio sempre rapido.
Report definitivi: `build/artifacts/performance-bundle-sync.json` e
`build/artifacts/performance-qa-final.json`.

## Confronto controllato nel runtime Qt — 2026-11-04

Esecuzione isolata con `python.exe -I -B` della copia `Anonymizer Qt QA`.
Il runner verifica che l'interprete e tutti i moduli applicativi provengano
dal bundle; non aggiunge il checkout al percorso degli import. Documento
Intestinal completo, 26 pagine, 300 DPI, SHA-256
`f57c4053cffb8b8b07b144e812a59e78e7743c76a7672279e725f4a3d6fe2a82`.
GLiNER ONNX FP32 invariato, soglia 0,5, modello caricato una sola volta,
profilo fissato a budget 12, NER 8, OCR 1, coda 1. Fra le prove cambia soltanto
il flag di sovrapposizione; nessuna modifica a priorità o piano energetico.
L'harness è stato prima verificato con quattro pagine sintetiche, rendering
reale e OCR/NER simulati, senza caricare un secondo modello in concorrenza.

| Ordine | Modalità | Analisi totale | Rendering | OCR | NER |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 | Sequenziale | 106,853 s | 6,267 s | 57,970 s | 42,024 s |
| 2 | Sovrapposta | 94,906 s | 7,333 s | 81,675 s | 50,880 s |
| 3 | Sovrapposta | 86,662 s | 4,664 s | 76,805 s | 47,742 s |
| 4 | Sequenziale | 99,301 s | 4,336 s | 55,947 s | 38,617 s |

Media (e mediana con due osservazioni): sequenziale 103,077 s,
sovrapposta 90,784 s; riduzione di 12,293 s, circa 11,93%.
Entrambe le prove sovrapposte sono più rapide delle due sequenziali, ma
quattro misure su una sola macchina non stimano una garanzia generale.
Il caricamento modello di 15,539 s e il warmup di 0,252 s sono esclusi;
GUI, HTTP, anteprima ed esportazione non sono misurati. Il riferimento
storico utente di circa 72 s resta non raggiunto e la differenza non è
spiegata dal solo avvio. Le singole attività rallentano quando si
sovrappongono: media OCR 56,959 → 79,240 s, NER 40,321 → 49,311 s.
È un'indicazione di interferenza fra attività concorrenti, senza identificare
da sola la risorsa responsabile. Non si aumenta il numero di thread.

Tutte le 12 impronte canoniche coincidono nelle quattro prove: testo,
regioni, candidati e fusioni con/senza confidenza, geometria, maschere,
avvisi, collegamenti candidati/maschere, blocchi e testo oscurato.
Gli ID casuali sono normalizzati. Conteggi invariati: 8.536 regioni,
521 candidati, 400 fusioni, 776 maschere, 187 avvisi. Questa equivalenza
verifica l'assenza di differenze introdotte dalla modalità di esecuzione;
non certifica che ogni dato sensibile del documento sia stato riconosciuto.
I nuovi report conservano metriche e hash, senza testo o contenuto clinico.

Monitor Windows con pausa di 10 s fra campioni, oltre al tempo delle query
CIM. Per un errore del wrapper nell'aggancio al PID, il monitor parte dopo
circa 77 s della prima prova: copertura 3/9/8/9 campioni rispettivamente.
Il benchmark non viene riavviato. Nei campioni CPU totale 6–66%, con singoli
core anche saturi; memoria disponibile 6.750–7.751 MiB; disco inattivo
77–100% e coda riportata 0. Paging in ingresso 0–66 pagine/s. Questi dati
non mostrano saturazione sostenuta di disco o esaurimento RAM, ma non
escludono picchi fra campioni. Picco working set del runner 2.553.360.384
byte (circa 2,38 GiB), esclusi i processi figli OCR. Frequenze e contatore
ProcessorPerformance sono salvati grezzi: non misurano la temperatura
e non consentono di diagnosticare throttling termico.

La CPU cumulativa del processo monitor all'ultimo campione è 4,078 s su
circa 313 s di osservazione; non include il lavoro del servizio WMI. Il primo
campionamento impiega 5,503 s di tempo reale, l'ultimo 0,952 s: attesa delle
query e consumo CPU sono misure distinte. Runner e monitor risultano conclusi.

Conclusione: mantenere la sovrapposizione già distribuita; beneficio osservato
circa 12%, problema dei 72 s ancora aperto. Nessun sorgente applicativo o
bundle modificato in questa verifica. Artefatti:
`build/artifacts/paired-runtime-benchmark.py`,
`build/artifacts/paired-runtime-benchmark.json`,
`build/artifacts/paired-runtime-monitor.ps1`,
`build/artifacts/paired-runtime-resources.jsonl`.

## Trascinamento e navigazione verticale — 2026-11-04

Nella modalità Clic, con zoom superiore al 100%, un trascinamento di almeno
5 pixel sposta entrambe le immagini tramite lo scorrimento condiviso.
Il testo segue la stessa mappatura geometrica verticale. Il gesto resta
un trascinamento anche tornando al punto iniziale: al rilascio non modifica
le maschere. Un clic breve conserva oscuramento/ripristino, Disegna conserva
il rettangolo manuale e Sposta funziona anche al 100%. Cattura del puntatore,
annullamento, cambio pagina/strumento/zoom e aggiornamenti della revisione
puliscono lo stato del gesto e il cursore. Il pan esclusivamente orizzontale
non attiva la navigazione verticale.

Lo scorrimento verticale volontario verso un estremo può cambiare pagina:
successiva in cima, precedente in fondo dopo caricamento e impaginazione
dell'anteprima. Lo zoom resta invariato. La navigazione ammette al massimo
una pagina per gesto; il burst della rotella termina dopo 350 ms senza eventi.
Prima e ultima pagina restano nei limiti. Gli spostamenti programmatici di
layout, zoom e revisione aggiornano la posizione di riferimento senza
attivare cambi pagina. Le decisioni sugli oscuramenti restano invariate.

Verifica finale: 19 controlli frontend superati con tre pagine sintetiche e
API simulate, più trascinamento reale del cursore della barra nativa che
apre la pagina successiva in cima. Controllati clic breve, rettangolo manuale,
pan sincronizzato, ritorno nello stesso gesto senza modifica delle maschere,
Sposta al 100%, cambio pagina durante il gesto, limiti, apertura precedente
in fondo, conservazione zoom, assenza di salti multipli nei burst in entrambe
le direzioni e assenza di navigazione da pan esclusivamente orizzontale.
Zero errori JavaScript; `node --check` superato. A 1280×720 la pagina occupa
720 pixel senza scorrimento verticale esterno né overflow orizzontale.

Il collaudo usa Edge headless con il solo argomento predefinito
`--hide-scrollbars` rimosso: le prime prove con barre nascoste non potevano
verificare il trascinamento nativo. Non è stata necessaria alcuna modifica
applicativa per aggirare il comportamento del browser. Le prime attese del
mock sono state corrette per attendere il completamento dell'anteprima dopo
il debounce, invece di verificare la risposta prima della sua richiesta.
Nessun OCR/NER avviato e nessun documento utente utilizzato in questo test.
Report: `build/artifacts/drag-pan-qa.json`; harness:
`build/artifacts/drag-pan-qa.py`; screenshot:
`build/artifacts/drag-pan-workspace-1280x720.png`.

Aggiornati soltanto `app.js`, `style.css` e `index.html` nel bundle
`dist/Anonymizer-Qt`, con verifica indipendente SHA-256 sorgente/copia/manifest.
Launcher, runtime Python, modello e configurazione OCR/NER invariati.
Per caricare l'interfaccia aggiornata è necessario riaprire l'applicazione.

## Regole esterne e campi geometrici — 2026-11-04

Integrate risorse italiane selezionate da OpenMed e adattamenti della logica
di EDS-Pseudo, EDS-PDF e medspaCy. Fonti fissate, licenze, NOTICE e limiti del
riuso sono descritti in `third-party-rules.md` e nel manifest distribuito
`src/anonymizer/data/external_rules.json`. Nessun nuovo motore, modello, dizionario
remoto o dipendenza runtime. Il modello GLiNER ONNX FP32 e la configurazione
adattiva dei thread non cambiano.

Le prove verificano indirizzi completi con CAP/città/provincia, contatti di
strutture nelle righe adiacenti e denominazioni con forma legale senza
prefisso clinico. Il passaggio URL esistente copre entrambi i tipi di
struttura con la medesima condizione di contatto. Le varianti Unicode dei
dati noti conservano gli offset originali. Le protezioni v6 interessano
soltanto NER L3 contenuti in etichette o intervalli clinici delimitati;
i candidati L0-L2 e gli audit precedenti restano validi.

La verifica indipendente comprende 13 casi con ordine di lettura diverso
dall'ordine visuale, due colonne paziente/refertante, nomi divisi fra regioni,
campi vuoti e parole cliniche interposte. Sia i box per parola OCR sia quelli
per carattere PDF producono maschere coerenti tramite `propose_redactions`
e testo oscurato coerente tramite `page_text`, senza mascherare il risultato
clinico interposto. Si tratta di geometrie sintetiche: questi test non
misurano il tasso di errore dell'OCR o del modello sui referti reali.

Suite completa: **637 passati, 5 saltati** prima dell'ultimo refactor del
passaggio URL condiviso. Dopo quel refactor: **232 test pertinenti passati**
(regole esterne, contesto, identità note, geometria, riconoscitori strutturati
e regex), oltre alla verifica mirata dello scrivente. Ruff globale pulito.
Nessun documento utente è stato usato nelle nuove prove.

Microbenchmark CPU con OCR/NER disabilitati, stesso ambiente locale:

| Campione sintetico | Mediana prima | Mediana dopo | Differenza |
| --- | ---: | ---: | ---: |
| 26 pagine senza box | 0,0577 s | 0,0825 s | +0,0248 s |
| 26 pagine, 2.862 box per carattere per pagina | 0,165 s | 0,731 s | +0,566 s |

Il confronto senza box usa 7 ripetizioni prima e 5 dopo; quello geometrico
usa lo snapshot precedente del package, verificato tramite hash dei moduli.
Le cinque misure geometriche dopo la modifica vanno da 0,516 a 0,749 secondi.
I conteggi dopo sono stabili: 1.040 candidati/910 intervalli uniti senza box
e 2.340/1.638 con box. L'aumento dei candidati è atteso dalle nuove regole,
non è una misura di precisione o richiamo. Il costo assoluto aggiuntivo sul
campione geometrico è inferiore a un secondo; non è una nuova misurazione
del tempo completo di OCR/NER né una garanzia su altri hardware.

Artefatti locali riproducibili:
`build/artifacts/external-rules-baseline.json`,
`external-rules-baseline-charbox.json`, `external-rules-postbench.json`
e i rispettivi harness Python nella stessa directory. I report contengono
timing, conteggi e hash, senza documenti o dati identificativi reali.

Aggiornato selettivamente `dist/Anonymizer-Qt`: 7 moduli Python, 7 file di
regole/licenze e 21 voci del manifest, includendo i bytecode con checked hash.
Verificati SHA-256 sorgente/copia/manifest e caricamento isolato con il Python
del bundle (`-I -B`): import dal package distribuito, risorse presenti,
rilevamento dei campi sintetici e conservazione del valore clinico. Il
modello NER non è stato caricato nello smoke test. Report finale:
`build/artifacts/external-rules-verification.json`; dettagli distribuzione:
`external-rules-sync.json`. Launcher, GUI, runtime e modello non sono stati
modificati da questo aggiornamento; la copia QA temporanea non è stata
sincronizzata e l'app dell'utente non è stata riavviata. Per usare le nuove
regole occorre riaprire l'app e rianalizzare il documento.

## Campi separati, firme con iniziali e ripetizioni — 2026-11-04

Aggiunta l'associazione delle coppie esplicite `Nome:` / `Cognome:`, anche
quando ciascun valore contiene una sola parola. Con coordinate disponibili
la pipeline usa la vicinanza geometrica, richiedendo un'associazione reciproca
univoca: campi in colonne lontane o tre campi concorrenti non vengono uniti.
Senza coordinate il parser richiede distanza e separatori limitati, senza
attraversare paragrafi vuoti. Le componenti restano distinte e prive di
un'identità assegnata automaticamente.

Le firme con iniziali puntate sono riconosciute soltanto dopo titoli o
etichette mediche esplicite e richiedono una componente estesa. La revisione
ha conservato i filtri grammaticali e amministrativi già applicati alle
etichette: `Refertante: Codice Fiscale` non deve diventare un nome. Nessuna
sequenza di sole iniziali abilita il riconoscimento.

Il nuovo passaggio di ripetizione usa esclusivamente nomi completi di origini
e motivazioni contestuali/geometriche consentite, nello stesso `source_id`.
Confronta le forme normalizzate Unicode mantenendo gli offset originali,
senza inversioni, similarità approssimativa o attraversamento di paragrafi.
Esclude predizioni NER, dizionari, componenti separate, iniziali e frammenti
di nomi estratti da regioni non contigue. Un rilevamento ripetuto non alimenta
ulteriori propagazioni e non assegna un'identità anagrafica.

Modello, configurazione dei thread e protezioni NER v6 restano invariati.
Il collaudo di queste regole usa documenti e geometrie sintetici; non misura
la precisione dell'OCR o del modello sui referti reali.

Microbenchmark dopo il freeze finale: 26 pagine sintetiche di 2.862 caratteri,
con 2.800 regioni per carattere per pagina, OCR e NER disabilitati. Su cinque
ripetizioni per versione, la mediana passa da **0,416 s a 0,634 s**
(**+0,217 s**, circa +52%). Le misure vanno rispettivamente da 0,412 a 0,546 s
e da 0,551 a 0,812 s. L'aumento relativo è misurabile, ma riguarda soltanto
questo passaggio CPU; non misura il tempo completo dell'applicazione.
I candidati passano da 2.340 a 2.808, mentre gli intervalli uniti restano
1.638: i conteggi non sono una misura di accuratezza. Lo snapshot precedente
e i moduli caricati sono verificati tramite percorso e SHA-256 nei report
`build/artifacts/field-improvements-before.json` e
`build/artifacts/field-improvements-after.json`; l'harness è
`field-improvements-benchmark.py` nella stessa directory.

Verifica post-freeze: **693 test passati, 5 saltati**, Ruff globale pulito.
Gli otto test indipendenti in `src/tests/test_field_improvements.py` coprono
coppie di campi nei due ordini, maschere geometriche e testo oscurato,
iniziali mediche, ripetizioni nello stesso documento, esclusione fra
documenti diversi, cognomi e iniziali isolati, parole cliniche e nomi simili
con accento differente. La fixture è sintetica e non viene usata come
dizionario o configurazione del prodotto.

Confronto sul testo della fixture, senza coordinate né OCR/NER: i dieci
intervalli identificativi attesi vengono riconosciuti esattamente **3/10
prima e 10/10 dopo**. Tutti i **13/13 valori clinici annotati** restano
leggibili in entrambe le versioni; gli oscuramenti coprono **0/209 caratteri
clinici annotati**. Questi denominatori descrivono soltanto il piccolo
campione mirato, non un tasso generale di precisione o richiamo. La verifica
delle coordinate e delle maschere appartiene ai test indipendenti sopra.
Report: `build/artifacts/field-improvements-fixture-before.json` e
`field-improvements-fixture-after.json`; harness:
`field-improvements-fixture-metrics.py` nella stessa directory.

Aggiornati nel bundle `dist/Anonymizer-Qt` i quattro moduli di contesto,
layout, ripetizioni e pipeline, con i rispettivi bytecode checked hash e
otto voci del manifest. SHA-256 sorgente/copia/manifest verificati nel
report `build/artifacts/field-improvements-sync.json`. Lo smoke test
isolato con il runtime distribuito (`-I -B`) verifica import dal bundle,
ripetizione del nome nella seconda pagina dello stesso documento, campi
separati geometrici e conservazione del testo clinico. Il modello NER non
è stato caricato. L'app dell'utente non è stata riavviata e la copia QA
temporanea non è stata aggiornata. Per usare le modifiche occorre chiudere
e riaprire l'app, poi rianalizzare il documento.

## Installativo della portable Qt — 2026-11-04

Introdotti `tools/packaging/windows/installer.iss` e `build_installer.py` per
distribuire esclusivamente `dist/Anonymizer-Qt` come installativo Windows
10/11 x64 per il singolo utente. Il programma installato resta la portable,
avviata tramite `Anonymizer.exe`; non si installano una webapp separata,
servizi Windows o avvii automatici. Il backend locale temporaneo interno
alla finestra Qt mantiene il ciclo di vita già previsto dalla portable.

La procedura è in italiano, propone i collegamenti Start/desktop e registra
la disinstallazione. Non richiede privilegi amministrativi o download di
runtime/modello. L'avvio al termine è facoltativo e disabilitato durante
l'installazione silenziosa. L'installatore non termina automaticamente
processi aperti e non definisce cancellazioni ricorsive alla disinstallazione.

Il costruttore verifica SHA-256 e percorsi di ogni voce di `bundle.json`,
richiede le risorse essenziali di applicazione, Qt, OCR e modello, genera
un elenco esplicito di file e include il manifest stesso. File aggiuntivi
nella cartella portable, come documenti o sessioni, non entrano nel pacchetto.
L'output comprende eseguibile, hash SHA-256 e rapporto JSON di provenienza.
Non è una firma digitale del produttore.

I **25 test del costruttore** coprono percorsi non validi, collisioni di
nomi, hash non corrispondenti, risorse mancanti, esclusione dei file extra,
versione del compilatore e integrità del rapporto. Ruff pulito. La versione
di Inno Setup viene interrogata tramite `Ver` del preprocessore ISPP e
controllata nuovamente con `EncodeVer` nello script: i metadati PE del
compilatore ufficiale 6.7.3 riportano 0.0.0.0 e non sono utilizzabili per
questa verifica. Il probe non produce un installatore.

Compilato con Inno Setup **6.7.3**, compressione ZIP livello 1 e senza
disk spanning: un solo `Anonymizer-Setup-0.1.0-test.1-x64.exe` di
**1.771.884.450 byte** (circa 1,77 GB), da **38.187 file / 3.873.773.969 byte**
del bundle completo. SHA-256 dell'installatore:
`f5b7bacae5237a6a4445cad0973f686caaf9ce7652723cdd4563fc440517ff43`.
Il manifest sorgente ha SHA-256
`a3f00db6bc95faf5686fd3b408d723162845beef70af07dc9eca2af58460ac6b`.
Hash e rapporto sono anche nei file `.exe.sha256` e `.exe.json` accanto
all'installatore. Authenticode dell'artefatto restituisce `NotSigned`;
non si dichiara una firma digitale o una certificazione della distribuzione.

Installazione silenziosa per utente nel percorso QA isolato: uscita 0,
senza riavvio e senza creare collegamenti sul desktop/menu Start dell'utente.
Verificati tutti i **38.186 file del payload** contro il manifest sorgente
(3.867.905.153 byte; il file aggiuntivo è `bundle.json`). Il launcher
installato ha lo stesso SHA-256 di quello portable. Le sole voci di avvio
dello script installer puntano ad `Anonymizer.exe`.

Smoke sul runtime installato con `-I -B`: `Resources.validate()` superato,
backend reale avviato e health con `mode=local_only`, OCR e NER `ready`,
`execution_location=this_computer`. Tempo di avvio del solo backend nella prova locale:
13,701 s; non è una misura del primo avvio su PC pulito o della GUI completa.
Chiusura backend con uscita 0, porta rilasciata e sessione temporanea rimossa.
La GUI dell'utente e la webapp di sviluppo non sono state riavviate.

Prima della disinstallazione è stata verificata la corrispondenza della
voce HKCU `InstallLocation` con il solo percorso QA. Disinstallazione con
uscita 0 e rimozione della voce registrata: un file sentinella aggiunto
dopo l'installazione e non appartenente al pacchetto è rimasto intatto.
Rimossi poi soltanto la sentinella e la directory QA vuota. Non rimane
un'installazione di prova. Le scorciatoie sono state disabilitate nella QA
per non interferire con quelle dell'utente; i loro target e la voce `[Run]`
sono stati verificati nello script. Non è stata avviata una seconda GUI
massimizzata per il collaudo. Report completo:
`build/artifacts/installer-verification.json`.

### Download pubblico del solo installatore

Su richiesta dell'utente, pubblicato il file statico tramite Tailscale Funnel
su un server di sviluppo, con un collegamento non più documentato.
Non sono stati installati Anonymizer o un server applicativo su Debian.
File Browser sulla porta 8080 resta indipendente; Funnel serve direttamente
il singolo file da una cartella dedicata.

Copia SSH completata e SHA-256 remoto completo uguale all'artefatto locale.
Il confronto delle configurazioni prima/dopo ammette esclusivamente la
nuova porta HTTPS 10000, il relativo handler per quel file e l'abilitazione
Funnel: le configurazioni preesistenti 443, 8384 e 8443 sono identiche.

Verifica pubblica con risoluzione DNS Google e connessione forzata all'IP
globale `185.40.234.55`, mantenendo la verifica TLS del nome host e senza
proxy: HEAD 200, dimensione 1.771.884.450 byte, supporto Range. I primi e
gli ultimi 65.536 byte, scaricati con risposta 206, corrispondono al file
locale; la radice della nuova porta restituisce 404. Non è stato riscaricato
integralmente l'EXE tramite Funnel. Report:
`build/artifacts/funnel-verification.json`, configurazioni prima/dopo e
header HTTP nella stessa directory.

### Campi amministrativi e sesso — 5 novembre 2026

La politica ora conserva il sesso e oscura date e orari collegati a eventi
identificativi, oltre a protocolli/cartelle e luoghi amministrativi espliciti.
Il parser contestuale è condiviso dalla rilevazione testuale e geometrica;
la decisione finale `should_mask` vale anche per le proposte visuali.
Non cambia il modello NER né la configurazione del parallelismo.

Le regressioni sintetiche coprono date complete/parziali, giorni della
settimana, secondi, etichette abbreviate e identificativi corti, offset Unicode,
valori sotto l'etichetta e ordine di lettura diverso dall'ordine visivo.
Verificano inoltre la conservazione di sesso, dosi, durate, cadenze terapeutiche,
sedi anatomiche, riferimenti normativi e bibliografici senza etichetta evento.
Una colonna distante non fornisce il valore di un campo vuoto.

Il test visuale percorre analisi, proposte di mascheratura, applicazione ai
pixel e testo per la clipboard: controlla sia il nero sui valori identificativi
sia i pixel e il testo dei contenuti clinici conservati. Usa coordinate
sintetiche, senza una nuova misura della qualità OCR o NER su referti reali.
Il contratto del corpus `dates` riclassifica le due annotazioni della data
di visita come identificative; il sesso resta un'invariante da preservare.

La suite completa ha prodotto 911 successi, 5 skip e un solo errore dovuto
alla precedente aspettativa di conservazione della data di visita nel corpus.
Dopo l'aggiornamento delle due annotazioni e del loro generatore, i test del
contratto sono passati: complessivamente 912 test verificati, 5 opzionali
saltati. Ruff pulito. Non è stato modificato il codice per adattarlo alla
vecchia aspettativa.

Sincronizzati i cinque moduli modificati nelle portable `dist/Anonymizer-Qt`
e `dist/Anonymizer-Qt-compact`, con bytecode CPython 3.12 checked-hash e
aggiornamento dei rispettivi manifest. Verificate le copie contro i sorgenti
e gli hash dei dieci file per bundle. Rapporto:
`build/artifacts/event-fields-visual-sync.json`.
Smoke isolato `-I -B` superato in entrambi i runtime: import dalla rispettiva
portable, nuovi campi oscurati e contenuti clinici preservati. Il collaudo
specifico di questa modifica non aggiunge un roundtrip di esportazione PDF/PNG;
verifica il raster redatto e il testo derivato dalle stesse maschere.
Le versioni dei bundle e gli installer esistenti non sono stati ricostruiti;
il download pubblico continua a distribuire l'artefatto precedente.

### Organizzazione del repository — 5 novembre 2026

Le sole directory visibili in radice sono `src`, `docs`, `dist`, `build` e
`tools`. Restano in radice README, pyproject, configurazioni Git/Docker e le
directory tecniche nascoste `.git` e `.venv`. Applicazione e test sono in
`src/anonymizer` e `src/tests`; packaging, esperimenti e precedente prova
Docker sono in `tools`. Specifica e piano sono direttamente in `docs`.
I report locali sono in `build/artifacts`; gli strumenti OCR, i compilatori,
Python e i modelli scaricati sono in `tools/local`, escluso da Git.

Aggiornati discovery setuptools, import editable, raccolta test, cache,
script portable, riferimenti Docker, documentazione e Git ignore. Il layout
interno dei pacchetti installati rimane `anonymizer/`, senza prefisso `src`.
Verificata la presenza di tutti i 133 file tracciati prima dello spostamento:
124 hanno un nuovo percorso. Le modifiche funzionali non ancora committate
del lavoro precedente sono state preservate.

Suite completa dopo le correzioni dei percorsi: **912 passati, 5 saltati**;
Ruff pulito su sorgenti, test e script mantenuti. Costruita la wheel in
`build/qa/anonymizer-0.1.0-py3-none-any.whl`: 197.271 byte, 66 membri, asset
e regole presenti, nessun test o strumento incluso. Smoke riusciti per CLI,
helper icone e copia del pacchetto da `src` verso una destinazione isolata.

Ripristinati offline l'ambiente principale e sei ambienti ausiliari dopo lo
spostamento di Python, conservando le dipendenze. Per tre entrypoint trasferiti
sono state rigenerate le console tramite reinstallazione di wheel ricostruite
dai medesimi file locali: verificati payload identico e comando `--help`.
Il browser headless della vecchia QA è stato chiuso e il suo profilo raccolto
in `build/browser-review`; il browser principale non è stato coinvolto.
Il server di sviluppo già attivo non è stato terminato: va riavviato per
caricare i nuovi percorsi. Le portable e gli installer esistenti sono invariati.

Aggiornati anche 68 harness locali di verifica; tutti i 77 script top-level
in `build/artifacts` superano il parsing Python/PowerShell, senza eseguire
analisi, sincronizzazioni o deploy. I report storici JSON/log e gli snapshot
sono conservati con il loro contenuto originale. Evidenze di rilocazione
in `build/relocation/`; nessuna pubblicazione o commit eseguiti.

### Documenti di riconoscimento italiani — 5 novembre 2026

Integrato il rilevamento contestuale per carta d'identità cartacea, CIE,
patente e passaporto. Fonti ufficiali e limiti sono descritti in
`docs/third-party-rules.md`. I test specifici comprendono 52 casi unitari
e 5 casi visuali: etichette multilingui, campi numerati coerenti della
patente, seriali, CAN, MRZ TD1/TD3, ripetizioni nello stesso file e
conservazione di sesso, valori clinici, elenchi e posologie.

La verifica visuale controlla sia le maschere nere sui pixel sia il testo
per la clipboard. Il promemoria specifico nella UI è stato verificato
con smoke JavaScript, compreso il ripristino del suggerimento normale
cambiando pagina; `node --check` superato.

Prova Tesseract su immagine sintetica: 47 regioni OCR, 6 candidati identity,
5 maschere identity unite. Nome, cognome, seriale, CAN e data di nascita
sono oscurati nel testo e sui pixel; sesso e contenuti clinici restano
visibili, senza warning geometrici. Anche il titolo con prefisso facsimile
e traduzione troncata dall'OCR passa dopo la correzione: 51 regioni e
6 candidati identity. Il report conserva separatamente il precedente
fallimento e il risultato sul codice aggiornato:
`build/artifacts/identity-documents-ocr-smoke.json`. Modello NER non caricato
in queste prove: misurano le nuove regole, non la qualità del modello.

Scaricati due facsimili CIE ufficiali in
`tools/test-data/identity-documents`, escluso da Git. Entrambi i PNG
originali sono rifiutati dalla policy esistente sui profili colore.
Una conversione RGB soltanto in memoria, senza metadata e senza salvare
derivati, ha permesso una diagnosi OCR separata: 68 e 76 regioni, ma
nessun documento riconosciuto dalle nuove regole. L'OCR non restituisce
le parole chiave del titolo né i prefissi MRZ cercati; non si attribuisce
con certezza la causa alle filigrane o alle annotazioni del facsimile.
Questa prova non valida l'accettazione dei PNG originali e non dimostra
copertura positiva sui documenti ufficiali. Evidenze numeriche, senza
trascrizioni OCR, in `build/artifacts/identity-documents-official-ocr.json`.

Foto, firme, ritratti secondari, codici a barre e numeri perforati richiedono
controllo visuale e maschere manuali con Disegna. Anche i dati testuali
non letti dall'OCR possono restare visibili. I test sintetici non
costituiscono una misura di richiamo su tutte le generazioni di documenti.

Suite completa sul codice definitivo: **969 passati, 5 saltati in 26,08 s**;
Ruff pulito su `src`. La durata è quella dei test, non un benchmark
dell'analisi OCR/NER di un documento reale.

Sincronizzate le portable `dist/Anonymizer-Qt` e
`dist/Anonymizer-Qt-compact`: i tre moduli Python modificati e `app.js`,
con bytecode checked-hash CPython 3.12 e manifest aggiornati. Gli smoke
isolati `-I -B` verificano gli import dai rispettivi bundle, CIE e
passaporto multilingue, conservazione di sesso/clinica ed elenco numerato
degli esami. Report `build/artifacts/identity-documents-bundle-sync.json`.
Launcher, numeri di versione, installer e download pubblico invariati;
nessun commit o pubblicazione eseguiti.

### Correzione importazione colore dei documenti — 5 novembre 2026

I PNG CIE ufficiali contengono il marker sRGB con intent 0 e gamma 0,45455,
non un profilo ICC malformato. La vecchia policy rifiutava indiscriminatamente
la presenza di gamma. La nuova normalizzazione accetta il marker sRGB anche
quando vale zero, senza riapplicare la gamma: entrambi gli originali sono
accettati, con dimensioni e pixel identici dopo il rendering.

I profili ICC supportati vengono validati e convertiti in sRGB mediante
LittleCMS; una gamma standalone viene trasformata esplicitamente nella
curva sRGB. Profili invalidi o primarie non supportate restano errori
espliciti. Preview ed esportazione usano lo stesso rendering normalizzato;
il preprocessing OCR non deve modificare l'immagine esportata. I controlli
di budget precedono il caricamento del raster. I test includono pixel
esportati, metadata rimossi, originali invariati e campioni numerici della
curva sRGB. Riferimento API: [Pillow ImageCms](https://pillow.readthedocs.io/en/stable/reference/ImageCms.html).

### Recupero OCR e maschere dei documenti — 5 novembre 2026

La verifica successiva supera il fallimento descritto sopra: i due PNG
originali CIE ufficiali e un PDF di due pagine che li incorpora attraversano
la pipeline completa. Sono rilevati nove campi sul fronte e cinque gruppi
sul retro, comprendenti genitori, codice fiscale, residenza, atto di nascita
e MRZ. La verifica visiva delle quattro immagini esportate conferma la
copertura dei campi e dei caratteri iniziali della MRZ omessi dall'OCR.
Report: `build/artifacts/identity-documents-current-ocr-e2e.json`;
anteprime in `build/qa/identity-documents/`.

Il recupero usa al massimo una seconda lettura, attivata da indizi documentali,
entro il timeout originale e con gli stessi limiti di thread. Conserva la
copertura delle maschere della prima lettura mediante un controllo geometrico
sui pixel; in caso di risultato inconcludente mantiene quella lettura e
richiede revisione. Il modello NER non cambia. La prova sui facsimili usa
Tesseract italiano con un thread e senza caricare NER: non rappresenta un
benchmark dell'app completa con NER.

Le regole usano etichette, struttura e geometria, senza nomi, numeri o
coordinate specifici del facsimile. La MRZ riceve una maschera unica con
margini proporzionati ai caratteri per coprire anche prefissi non trascritti.
Foto, firme, ritratti secondari e codici a barre restano da oscurare con
Disegna. Questi risultati non misurano la copertura su tutte le generazioni
di carte, patenti e passaporti; resta necessaria la verifica visuale.

Suite finale: **1000 passati, 5 saltati in 37,93 s**; Ruff su `src` e
`node --check` su `app.js` superati. Le due portable Qt e Qt-compact sono
sincronizzate con cinque moduli Python e `app.js`, cinque bytecode checked-hash
e manifest coerenti. Gli smoke isolati verificano import dal proprio bundle,
CIE/MRZ positive, narrativa e MRZ malformata negative, conservazione di sesso
e dati clinici, normalizzazione sRGB con intent zero e disponibilità LittleCMS.
Report: `build/artifacts/identity-documents-recovery-bundle-sync.json`.
Riavviare l'app per caricare i nuovi moduli. Launcher, versioni, installer e
download pubblico invariati; nessun commit o deploy eseguito.

### Data di nascita dopo il luogo e ambiguità OCR — 5 novembre 2026

Corretta la classificazione delle date nella costruzione `nata/nato/nato/a a
<luogo> il <data>`, prima trattate come date generiche e quindi conservate.
Il contesto ammette nomi composti, provincia, apostrofi e a capo OCR limitati;
il recupero `mata/mato` e `i/l` si applica solo alla costruzione completa.
Confini di parola, righe vuote, limiti di distanza e interruzioni cliniche
impediscono di estendere il contesto alle date di visita o controllo successive.

Riprodotto il difetto sull'ultima immagine locale nei Download: prima della
correzione la data era classificata DATE e riceveva zero maschere; dopo la
correzione diventa BIRTH_DATE, scompare dal testo pseudonimizzato e copiabile,
e tutti i pixel della regione OCR della data risultano neri nel rendering.
Verifica ripetuta sul runtime isolato della portable Qt-compact con OCR italiano,
senza NER. Nessun contenuto personale del campione è incluso nelle fixture o
in questa documentazione; i test usano esclusivamente dati sintetici.

Suite completa: **1088 passati, 5 saltati in 26,47 s**; Ruff su `src` pulito.
Le regressioni verificano classificazione, falsi positivi, date cliniche
successive, testo copiabile e pixel delle maschere. Il campo è limitato a
192 caratteri, otto parole del luogo e tre a capo senza righe vuote.

Sincronizzate `dist/Anonymizer-Qt` e `dist/Anonymizer-Qt-compact` con il solo
modulo `detect/regex.py`, bytecode checked-hash CPython 3.12 e hash dei manifest.
Smoke isolati `-I -B` superati su entrambe: tre costruzioni positive e sei
negative, oscuramento testo/pixel e conservazione della data clinica.
Report numerico: `build/artifacts/birth-date-bundle-sync.json`.
Riavviare l'app e rianalizzare il documento per applicare la correzione.
Installer, versioni e download pubblico invariati; nessun commit o deploy.

### Data di nascita dopo "Nato a:" e cambio di licenza — 7 novembre 2026

Nella costruzione `Nato a: <luogo> il <data>`, comune nei moduli, i due punti
dopo "a" impedivano di riconoscere il contesto: il luogo veniva oscurato, la
data di nascita no. Emerso sul referto sintetico preparato per le schermate
del README. La regola ora accetta `:` o `=` dopo "a", con o senza spazi;
aggiunti due casi alle regressioni della data di nascita.

HEIC: `pillow-heif` sostituito da `pi-heif` negli extra distribuiti. I binari
di `pillow-heif` includono l'encoder x265 (GPLv2), incompatibile con la
licenza d'uso personale; l'app legge soltanto i file HEIC, quindi basta la
variante in sola lettura con libheif e libde265 (LGPLv3). `pillow-heif`
resta solo tra le dipendenze di sviluppo, per generare il file del test.

Build 0.1.0.8: licenza in `LICENSE.txt` nel bundle, pagina di licenza
obbligatoria nell'installer, avviso di uso esclusivamente personale nella
pagina iniziale. Verificati assenza di x265, apertura HEIC, OCR e NER reali
con il runtime isolato delle portable.
