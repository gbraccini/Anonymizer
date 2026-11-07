# Anonymizer — pseudonimizzazione assistita dei referti per analisi IA

Nome prodotto: **Anonymizer**, pacchetto Python anonymizer.
Data: 2026-11-02. Revisione: 2026-11-03.
Stato: implementazione del core testuale avviata. Requisito aggiornato: copia immagine/PDF oscurata obbligatoria, TXT aggiuntivo. Prima fase
su immagini e PDF esportati; DICOM escluso per scelta esplicita. Soglie operative
e scelte soggette a misura restano da validare.

## Intento e confine di fiducia

Il medico carica PDF o immagini di referti/esami in una webapp ospitata dal fornitore del servizio e ottiene una copia oscurata del documento originale, dopo revisione.
Radiografie, OCT e altri esami visuali devono conservare il contenuto dell'immagine.
Quando utile, sono disponibili anche TXT pseudonimizzato e mappa separata per
riassociare una risposta nel browser. Il TXT non sostituisce la copia oscurata.

Il fornitore del servizio riceve il documento originale per elaborarlo. Il servizio IA successivo
riceve le copie oscurate e/o il testo approvati dal medico. La mappa viene generata
sul server e restituita al browser, senza archiviarla sul server.

La funzione offerta è **pseudonimizzazione assistita con revisione**, senza promessa
di anonimato assoluto. La prima versione copre identificativi diretti di paziente
e terzi, luoghi e strutture riconoscibili dai rilevatori. Informazioni residue
possono rendere riconoscibile una persona; trasformare il testo non autorizza
automaticamente l'uso di qualsiasi servizio IA destinatario.

Il contesto resta quello di PC poco potenti, medici non tecnici e uso frequente
del telefono per fotografare documenti. La webapp elimina installazione locale
e dipendenza dalla potenza del PC. Il core indipendente dall'interfaccia permette
una versione desktop con gli stessi asset GUI HTML/CSS/JavaScript della webapp.
La standalone è un requisito del progetto; il confezionamento resta da implementare.

Valutazione del 2026-11-03: 46 secondi di analisi sono inaccettabili,
e il PC di sviluppo è più potente dei PC destinatari. Le prestazioni restano
un requisito aperto: aumentare i thread su quel PC non è una soluzione di prodotto.
La webapp ospitata esegue OCR/NER sul server; la standalone con elaborazione locale
deve superare una verifica distinta su un PC rappresentativo, mantenendo la stessa
GUI. Il profilo server 4 vCPU/8 GB non definisce automaticamente il minimo desktop,
e limitare i thread sulla CPU di sviluppo non simula una CPU meno potente.
Nessuno spostamento automatico dei documenti dalla standalone a un servizio remoto.

## Decisione sui file temporanei — 2026-11-03

Il progetto accetta per questa fase i file temporanei su disco di pytesseract
e delle librerie di upload. Non è richiesto un percorso senza scritture, un OCR
alternativo o tmpfs; questo punto non deve bloccare lo sviluppo.

Restano pulizia ordinaria delle librerie e chiusura delle risorse dopo elaborazione
ed errori gestiti, nessun archivio applicativo di documenti/risultati e nessun dato
sensibile nei log. L'hardening dei residui dopo crash è rinviato; la prima versione
non promette assenza assoluta di scritture o cancellazione forense.

## Obiettivi

1. PDF nativi/scansionati e JPG/PNG/HEIC caricati da PC o telefono. Ordine delle
   pagine scelto dal medico e preservato, senza riordinamento per nome file.
2. Estrazione del testo e OCR italiano con preprocessing delle foto.
3. Rilevazione a livelli, candidati spiegabili e identità distinte.
4. Maschere definitive sui dati sensibili dell'immagine/PDF e pseudonimi stabili
   nel TXT aggiuntivo; nessuna riscrittura generativa di testo o pixel clinici.
5. Revisione dell'originale e dell'anteprima oscurata, con zoom e aree modificabili
   anche senza testo OCR; vista testuale aggiuntiva. Uso su PC e telefono.
6. Copia immagine/PDF obbligatoria; testo copiabile/scaricabile e mappa separata
   quando utili. Riassociazione testuale locale della risposta.
7. Obiettivo iniziale di 15 s per 3 pagine, NER incluso, da verificare con profilo
   hardware, qualità input e concorrenza dichiarati.
8. Nessuna archiviazione server dei documenti; temporanei secondo la decisione sopra.
9. Misurare fedeltà clinica, dati identificativi residui e lavoro di revisione,
   oltre a velocità e copertura dei rilevatori.
10. Usare l'anagrafica locale del gestionale quando disponibile, con selezione/conferma
    del paziente e inserimento manuale o uso senza anagrafica in sua assenza.
    Il connettore alimenta il livello dei dati noti dello stesso motore e la stessa
    GUI condivisa; non sostituisce la rilevazione di terzi tramite regole e NER.

## Anagrafica locale opzionale — requisito riallineato il 2026-11-03

È previsto il collegamento all'anagrafica di un gestionale clinico locale, se presente.
La precedente esclusione dall'integrazione locale è superata per questa funzione.
Il prototipo attuale dispone di KnownIdentity e rilevatore L0 nel core, ma la GUI
non riceve ancora anagrafica e non esiste un connettore operativo.

Recuperare i soli dati necessari del paziente scelto (nome, cognome, codice fiscale,
nascita e altri identificativi disponibili pertinenti), mostrando provenienza e
conferma dell'identità. Distinguere fonte disponibile, assente ed errore; nessuna
selezione implicita del paziente dal primo CF del referto. Un cambio paziente o
dei dati anagrafici richiede nuova analisi e invalida la revisione precedente.

L'adattatore locale deve essere di sola lettura e separato dalla GUI. Nella versione
web ospitata, l'accesso a un database sul PC richiede un componente locale oppure
un'integrazione esplicita con il gestionale: il browser non accede direttamente
al database. Verificare l'interfaccia realmente disponibile nel gestionale destinatario; codice di altri client non dimostra da solo un'API utilizzabile dal gestionale installato. Non inventare endpoint o configurazioni di connessione.
Anagrafiche centrali e autenticazione JWT sono integrazioni distinte.

## Non obiettivi e sviluppi successivi

- Invio automatico al servizio IA, app mobile nativa e DICOM originali.
- De-identificazione anatomica automatica o interpretazione clinica degli esami.
  Il prodotto tratta identificativi, annotazioni e metadati nei formati esportati.
- Integrazioni estese nell'interfaccia del gestionale e anagrafiche centrali restano sviluppi successivi. Il collegamento opzionale all'anagrafica
  locale e la standalone con GUI condivisa sono invece requisiti espliciti.
- Anonimato assoluto. Accordi e valutazione del trattamento/del servizio destinatario
  restano distinti dal prodotto tecnico.
- Traslazione e ritraslazione delle date: rinviate, assenti dalla prima CLI/API/UI.
- Cifratura della mappa scaricata e hardening dei temporanei: fasi successive.

## Condizioni da evitare

- Identificativi residui non rilevati né intercettati in revisione.
- Alterazioni cliniche silenziose: anche OCR, linearizzazione delle tabelle e
  falsi positivi possono cambiare numeri, unità, negazioni e associazioni.
- Pagine perse o fallite presentate come documento completo.
- Fusione di paziente, familiari e altre persone sulla sola somiglianza dei nomi.
- Documenti o mappe archiviati sul server o nei log/cache applicativi.
- Mappa di riassociazione inclusa nel testo da inviare all'IA.
- Rettangoli soltanto sovrapposti, con dati recuperabili sotto le annotazioni;
  metadati, miniature, allegati o layer originali copiati nell'output.
- Modifiche al dettaglio clinico dovute a preprocessing OCR applicato anche
  all'immagine finale, conversioni non dichiarate o riduzione silenziosa della qualità.
- Revisione tanto onerosa da essere ignorata o svolta superficialmente.

## Vincoli e stack iniziale

- Linux in container Docker, su una VPS.
  Profilo proposto da confermare: 4 vCPU, 8 GB RAM, senza GPU.
- Browser: ultime due versioni di Chrome, Edge, Safari iOS e Chrome Android.
- JWT emessi da un servizio di identità esterno: contratto effettivo
  da verificare. Autenticazione obbligatoria dal primo ambiente condiviso, TLS e
  rifiuto dell'accesso se la configurazione condivisa è incompleta. Override finto
  soltanto per test e sviluppo locale esplicito.
- Python 3.12; core in src/anonymizer/, FastAPI in src/anonymizer/web/, CLI di servizio.
- Tesseract via pytesseract, italiano fast come partenza, OpenCV per foto;
  pypdfium2 per PDF, Pillow/pi-heif per immagini.
- Jinja2 e JavaScript per prototipo responsivo; frontend definitivo dopo la prova
  della revisione. La complessità di questa schermata guida la decisione.
- NER: partire dalla valutazione di GLiNER su CPU/ONNX. Alternative di estrazione,
  come NuExtract o piccoli modelli locali, solo se misurate sullo stesso campione
  e capaci di restituire riferimenti verificabili senza inventare contenuto.
- Licenze di codice, modelli e dataset da verificare separatamente rispetto ai
  vincoli di distribuzione. PyMuPDF, OCRmyPDF e Ghostscript esclusi secondo la
  scelta di progetto; nessun fallback automatico a fonti incompatibili.

## Pipeline

1. **Ingest progressivo.** Validazione formato/contenuto, limiti di pagine e pixel
   prima delle operazioni costose, ordine preservato. Non rasterizzare tutto in anticipo.
2. **Scelta estrazione.** PDF con testo completo e attendibile → estrazione diretta.
   PDF misti o layer incompleti → OCR/valutazione aggiuntiva senza duplicazioni.
   La sola presenza di 50 caratteri non dimostra la copertura della pagina.
3. **Preprocessing e OCR.** Orientamento, prospettiva, contrasto e deskew con fallback.
   Conservare trasformazioni per riportare coordinate all'originale; testo, parole,
   righe/blocchi e intervalli. Segnalare incertezze e verificare relazioni tabellari.
   Confidenza OCR elevata non è prova di fedeltà.
4. **Rilevazione.**
   - L0: dati dichiarati dal medico separati dai dati proposti dal documento.
     Matching esatto/fuzzy con soglie misurate; contesti negativi clinici.
     Non attribuire al paziente il primo CF trovato. Validazione, decodifica e
     conferma dell'identità sono distinte; esplicitare ambiguità come il secolo.
   - L1: CF, tessera sanitaria, date, telefoni, email, CAP, codici pratica e IBAN.
     Targhe da coprire o dichiarare escluse dal primo rilascio. Un CF plausibile
     con checksum errato resta sensibile anche senza anagrafica nota.
   - L2: dizionari e contesto per persone, luoghi e strutture, con gestione dei
     cognomi ambigui e delle possibili interferenze con il testo clinico.
   - L3: modello NER valutato presto. Scelta e uso predefinito decisi prima del
     pilota; indisponibilità visibile in health e avvisi, senza fallback silenzioso.
5. **Fusione.** Unione completa della copertura sovrapposta, conservando candidati,
   livelli, origini e conflitti. Non scegliere soltanto l'intervallo più lungo.
   Unire token adiacenti solo con evidenza della stessa entità. Copertura sensibile
   e risoluzione dell'identità sono due problemi distinti.
6. **Pseudonimizzazione.** Identificativi L0/L1 mascherati, L2/L3 aggiungono copertura.
   Le date degli eventi restano visibili: rilevazione non significa sempre mascheratura.
   Segnaposto delimitati come [[PAZIENTE]], [[PERSONA_1]], [[MEDICO_1]], [[LUOGO_1]],
   [[STRUTTURA_1]], [[CF_PAZIENTE]], con gestione delle collisioni.
   Ruolo paziente solo con associazione confermata; altrimenti entità distinte.
   Nascita → età soltanto al riferimento temporale attendibile e confermato del
   documento; altrimenti [[DATA_NASCITA_n]]. Nessun fallback implicito a oggi.
   Nei dossier storici rispettare riferimenti diversi. Sesso conservato; strutture
   mascherate per default, configurabile. Testo fuori dalle trasformazioni invariato.
7. **Proposta visuale e revisione locale.** Collegare ogni candidato a regioni
   geometriche dell'originale, conservando dimensioni, orientamento e trasformazioni
   della copia OCR. Originale e anteprima oscurata con testo aggiuntivo.
   Mascherature, problemi OCR, conflitti e pagine mancanti distinti.
   Aggiunta/rimozione mascherature, conferma identità, riordino pagine e correzioni
   OCR esplicite/annullabili. Rimozione L0/L1 con conferma esplicita. Correzioni OCR
   invalidano gli intervalli interessati e impongono nuova verifica; ogni modifica
   invalida la precedente conferma dell'output.
   Avvisi bloccanti risolti con correzione/conferma o esclusione esplicita della
   pagina, indicando un output parziale. Nessuna omissione silenziosa.
   Aree manuali anche senza OCR, per firme, QR/barcode o scritte illeggibili.
   Coordinate mancanti/incoerenti richiedono correzione prima dell'export visuale.
8. **Export visuale.** Copie con maschere opache applicate ai pixel. Per immagini,
   copia PNG senza metadati originari, conservando risoluzione e pixel fuori
   maschera; la copia preprocessata per OCR non diventa l'immagine clinica finale.
   Profondità, colore e frame supportati devono essere espliciti, senza conversioni
   distruttive o omissioni silenziose. Per PDF, nuova costruzione da pagine raster
   già oscurate: nessun testo originale, allegato, annotazione, miniatura o oggetto
   nascosto copiato. Preservare ordine, dimensioni e orientamento delle pagine.
   Questa prima soluzione perde ricerca testuale/elementi vettoriali: qualità dei
   dettagli e rasterizzazione vanno verificate, senza abbassare DPI silenziosamente.
   Gli originali non vengono sovrascritti; il download non deve contenere i dati
   sotto rettangoli rimovibili.
9. **Testo aggiuntivo e riassociazione.** TXT e mappa separati quando utili.
   La mappa scaricata contiene dati reali e resta sul dispositivo; non è inclusa
   nell'output IA. Riassociazione nel browser di token esatti, non ricorsiva;
   token sconosciuti/modificati segnalati, senza indovinarli. Nessuna ritraslazione
   date né conversione generica di età in date di nascita.

### Interazione diretta nel prototipo locale — 2026-11-03

La revisione si concentra sulle pagine affiancate: clic su una parola per
oscurarla, clic su una maschera per ripristinare la leggibilità, trascinamento
per una zona libera. Annulla/Ripristina rendono reversibili le modifiche della
sessione. Le maschere automatiche rifiutate restano riconoscibili e riattivabili.
Le decisioni non richiedono una lista permanente di checkbox: si conferma la
pagina dopo averla controllata, poi l'intero documento prima dell'export.
Avvisi e problemi di geometria hanno un pannello dedicato; l'interazione non
elimina i vincoli di revisione o la verifica firmata degli originali.

La vista testuale affianca originale e testo oscurato. Quest'ultimo segue i pixel
coperti dalle maschere correnti, comprese quelle manuali e le sovrapposizioni;
le regioni testuali interessate vengono sostituite integralmente e le porzioni
senza coordinate non vengono esposte nel testo oscurato. Il prototipo usa
`[OSCURATO]` e `[TESTO NON LOCALIZZATO]`, non ancora la pseudonimizzazione
riassociabile prevista nel progetto complessivo. Il testo completo oscurato è
copiabile dopo la revisione finale e scaricabile insieme alla copia PDF in ZIP.
Il testo originale ha azioni distinte ed esplicite. Tutte le viste usano gli
stessi asset destinati alla standalone; nessuna seconda GUI nativa.

## Contratto API e revisione

- POST /api/anonymize: multipart con file, anagrafica e opzioni. Risposta JSON
  versionata: testo originale immutabile per pagina, coordinate, candidati con
  provenienza/validazione, entità e conferme, sostituzioni con intervalli originali
  e risultanti, geometria delle pagine/trasformazioni, proposte di maschera visuale,
  anteprima pseudonimizzata, mappa, avvisi e tempi.
- ID opachi di documento/pagina/entità/occorrenza. Valore canonico e forma osservata
  separati: annullare una mascheratura ripristina la specifica occorrenza originale.
- Offset in punti di codice Unicode con conversione esplicita agli indici UTF-16
  JavaScript; test di accenti, caratteri combinati ed emoji.
- Originali caricati conservati dal browser per la visualizzazione locale.
  Eventuali anteprime HEIC nella stessa risposta, con limiti di dimensione e senza
  URL persistenti sul server.
- Il client ricostruisce testo/mappa e modifica le aree di mascheratura localmente.
- POST /api/export: seconda richiesta autenticata e stateless con originali e
  maschere approvate, valida collegamento alle pagine, geometria e risorse, genera
  le copie oscurate e le restituisce. Nessun archivio tra richieste. Sostituisce il
  precedente vincolo di non reinviare mai il documento, per consentire export
  visuale uniforme dopo la revisione. Il solo flag di conferma client non prova
  completezza della mascheratura. Riassociazione sempre locale, senza inviare
  mappa o risposta IA al server.
- GET /api/health: stato sintetico OCR/NER.
- Limiti iniziali: 20 file, 50 MB complessivi durante ricezione e 120 s/richiesta.
  Il piano propone limiti aggiuntivi configurabili di pagine, pixel e concorrenza
  da validare con RAM e carico. Nessuna coda illimitata; timeout/cancellazione devono
  fermare anche worker e OCR.

## Gestione dei dati

- Nessun database documentale, archivio risultati o coda persistente; temporanei
  delle librerie secondo la decisione approvata.
- Rilascio risorse e cleanup dopo successo/errori gestiti.
- Log con identificativo utente ove necessario, conteggi, tempi e codici di errore
  controllati; mai testo, nomi file, campi paziente o eccezioni grezze contenenti dati.
- Risposte sensibili non memorizzabili in cache; niente conservazione automatica
  nel browser oltre la sessione di lavoro. Download espliciti restano sul dispositivo.
- Limiti e rate limit per utente da misurare; budget di elaborazione sull'intero
  servizio, non moltiplicato accidentalmente per il numero di processi web.

## Qualità e criteri di rilascio

Il corpus parte subito con annotazioni per occorrenza, pagina e posizione:
sintetici realistici, foto, PDF misti, tabelle, intestazioni ripetute e più persone.
Venti documenti iniziali sono smoke test, non prova delle prestazioni.
Sviluppo/taratura separati dalla valutazione; eventuali documenti reali soltanto
con disponibilità e uso autorizzati, fuori da repository e report.

Misurare separatamente:

1. **Estrazione:** errori/omissioni, numeri, unità, negazioni e relazioni tabellari.
2. **Rilevazione:** copertura parziale/totale e precisione per tipo sul testo
   effettivamente estratto, comprese varianti OCR e falsi positivi clinici.
3. **Output:** identificativi residui anche alterati dall'OCR, quota di documenti
   con almeno una fuga e contenuto clinico perso; prima e dopo revisione umana.
4. **File visuale esportato:** copertura delle aree, residui nei pixel/metadati/layer,
   qualità dei dettagli fuori maschera. Riaprire con un lettore indipendente ed
   esaminare testo/oggetti/immagini incorporati; il solo controllo dell'anteprima
   o la ricerca di stringhe nei byte compressi non dimostrano la rimozione.

Rossi letto come R0ssi e non mascherato è un errore, anche se Rossi è assente
dall'output. Un identificativo omesso dall'OCR è un errore di estrazione, non un
successo del rilevatore.

0,99 su testo pulito e 0,95 su foto restano obiettivi iniziali L0/L1, non garanzie.
Dichiarare denominatori, numerosità per classe e incertezza.
Misurare tempo di revisione mediano/p95, correzioni e errori residui con medici;
concordare soglie dopo la prima prova.

Test automatici con OCR reale su campione ridotto e simulato per regressioni,
API/auth, revisione browser, Unicode, identità multiple, riassociazione e risorse.
Ogni difetto diventa regressione. Pilota subordinato a criteri concordati superati
sul campione separato e assenza di difetti critici irrisolti, non alla sola media
del recall.

Prestazioni: latenza mediana/p95 per analisi ed export separatamente, RAM, cold start
e concorrenza. Rivedere il budget iniziale con il nuovo output visuale obbligatorio.
Ridurre DPI o cambiare preprocessing richiede ripetere anche misure di fedeltà e
copertura; velocità da sola non giustifica il cambiamento.

## Fasi

1. Contratto di revisione, campione annotato, core testuale e prototipo UI anche
   con dati simulati; verifica delle informazioni necessarie al JWT.
2. Prima estrazione completa PDF/foto e confronto anticipato del NER.
3. Oscuramento visuale e percorso autenticato: upload, confronto originale/anteprima,
   correzioni, export immagine/PDF, TXT aggiuntivo e riassociazione locale;
   container per prove riproducibili.
4. Campione ampliato, prova con medici, misure di qualità/carico e decisione sul pilota.
5. Funzionalità rinviate e hardening secondo i risultati: traslazione date,
   eventuale cifratura mappa, gestione più rigorosa dei temporanei.

Dettagli operativi, task e checklist sono nel
[piano di implementazione](implementation-plan.md).
