# Regole di terze parti

## Presidio

Il progetto riutilizza una selezione dei pattern pubblicati da
[Presidio](https://github.com/data-privacy-stack/presidio), alla revisione
`05b60e1a6805f3b2c0ad6cbe7526ccd226647971`.
Non installa il motore Presidio, spaCy o un secondo modello NER.

I sorgenti consultati e conservati localmente in
`build/artifacts/presidio-upstream/` sono:

- [EmailRecognizer](https://github.com/data-privacy-stack/presidio/blob/05b60e1a6805f3b2c0ad6cbe7526ccd226647971/presidio-analyzer/presidio_analyzer/predefined_recognizers/generic/email_recognizer.py).
- [IbanRecognizer](https://github.com/data-privacy-stack/presidio/blob/05b60e1a6805f3b2c0ad6cbe7526ccd226647971/presidio-analyzer/presidio_analyzer/predefined_recognizers/generic/iban_recognizer.py).
- [Formati IBAN per paese](https://github.com/data-privacy-stack/presidio/blob/05b60e1a6805f3b2c0ad6cbe7526ccd226647971/presidio-analyzer/presidio_analyzer/predefined_recognizers/generic/iban_patterns.py).
- [UrlRecognizer](https://github.com/data-privacy-stack/presidio/blob/05b60e1a6805f3b2c0ad6cbe7526ccd226647971/presidio-analyzer/presidio_analyzer/predefined_recognizers/generic/url_recognizer.py).

La licenza MIT di Presidio è distribuita integralmente in
`src/anonymizer/data/PRESIDIO_LICENSE.txt`. Il pattern URL è a sua volta derivato
da CommonRegex; la relativa licenza MIT, copyright Madison May, è distribuita
in `src/anonymizer/data/COMMONREGEX_LICENSE.txt`.
La [copia della licenza CommonRegex](https://github.com/madisonmay/CommonRegex/blob/2425abdb79c8992b8b655c27e1fb195cc54457ab/LICENSE)
è riferita alla revisione `2425abdb79c8992b8b655c27e1fb195cc54457ab`.

## Ambito del riuso

Le regole strutturate sono adattate al testo italiano estratto da PDF e OCR.
Il file `src/anonymizer/data/presidio_rules.json` contiene i pattern effettivamente
caricati da `src/anonymizer/detect/structured.py`, i formati IBAN per paese,
gli URL dei sorgenti e i rispettivi hash SHA-256. Il caricamento avviene una
volta per processo e non richiede accesso alla rete.

Gli adattamenti rispetto ai riconoscitori originali sono espliciti:

- Email: candidati di lunghezza limitata attorno a `@`, verifica dell'intero
  indirizzo e dei limiti sintattici. Non si usa `tldextract` e non si verifica
  l'esistenza del dominio o della casella; domini sintetici possono essere
  oscurati. Si conservano indirizzi Unicode e punycode.
- IBAN: normalizzazione di spazi orizzontali, tab e trattini, verifica del
  formato del paese e del checksum MOD97. Nessuna unione tra righe. Un IBAN
  italiano plausibile o un IBAN con etichetta esplicita resta da oscurare
  anche con checksum errato, per non rendere leggibili identificatori che
  potrebbero contenere errori OCR; la validazione riporta l'errore.
- URL: candidati con prefisso `www.` o HTTP(S), confini del dominio e
  conservazione di porta, percorso, query e frammento. La lista statica di
  suffissi non limita gli URL espliciti sintatticamente plausibili, grazie
  a un controllo locale aggiuntivo; nessuna interrogazione DNS.

Gli URL sono cercati nei blocchi di contatto di strutture già riconosciute:
un collegamento bibliografico non diventa automaticamente un dato da oscurare.
Le regole locali per codice fiscale e telefoni italiani restano indipendenti.

pyDeid e i2b2 restano riferimenti metodologici della ricerca documentata in
`validation.md`. Le regole grammaticali italiane precedenti, la separazione
geometrica dei blocchi e la propagazione delle denominazioni complete sono
implementazioni del progetto.

## Philter: adattamento italiano

Una selezione delle regole inglesi di
[Philter UCSF](https://github.com/BCHSI/philter-ucsf/tree/4da3cf31c9bfbfd66c66b141c45ba7a47628dd0a)
è adattata in `src/anonymizer/data/clinical_it_rules.json`, caricato a runtime
da `src/anonymizer/detect/clinical.py`. La revisione di riferimento è
`4da3cf31c9bfbfd66c66b141c45ba7a47628dd0a`. Ogni regola indica il pattern
italiano, la fonte inglese e le modifiche applicate. Non viene eseguito il
motore Philter e non sono installati modelli o dizionari inglesi.
La selezione attiva comprende 11 regole adattate da 13 pattern originali e
una estensione locale per le intestazioni documentali italiane.

Sono conservati in `build/artifacts/philter-upstream/` il file di
configurazione, la licenza e 18 file di pattern selezionati per la revisione.
Il manifest registra URL, SHA-256, dimensione e Git blob SHA-1: tutti i
20 file sono stati verificati rispetto alla revisione fissata. La presenza
nel materiale di studio non implica l'attivazione di ogni pattern scaricato.
La licenza BSD-3-Clause è inclusa integralmente nel package e nei bundle
in `src/anonymizer/data/PHILTER_LICENSE.txt`.

| Famiglia inglese | Adattamento italiano e limiti |
| --- | --- |
| `measurement_safe`, `units_safe` | Quantità numeriche con unità, virgola decimale e notazione clinica; nessuna esenzione per una parola isolata. |
| `bp_safe` | Etichette PA e pressione arteriosa con coppia di valori; esclusione di continuazioni simili a date. |
| `pain_safe` | Dolore espresso come punteggio su 10; contesto e limiti espliciti. |
| `attending_safe` | Ruolo medico nel contesto narrativo, senza includere il nome che segue. |
| `assessment_&_plan_safe`, `assessment_safe`, `chief_safe` | Intestazioni cliniche italiane riconosciute soltanto come righe complete. |
| `attending`, `ordering_md` | Etichette del medico e del refertante seguite da un nome plausibile. |
| `confirmed_by_name` | Firme e validazioni: riconoscimento del nome dopo la relativa etichetta. |
| `patient_provider`, `name_indicator` | Campi paziente con separatore esplicito; esclusione di segnaposto e descrizioni grammaticali dello stato clinico. |

Le espressioni italiane sono riscritte con confini Unicode e limiti adatti
all'OCR. Non sono una traduzione automatica dei pattern originali, che
contengono convenzioni di nomi, abbreviazioni e formati americani. Le
estensioni locali delle intestazioni documentali italiane sono indicate
separatamente dalle traduzioni delle intestazioni cliniche inglesi.

Le regole di conservazione filtrano solo predizioni NER di livello 3
interamente comprese nell'intervallo riconosciuto. Non annullano identità
note, identificatori, indirizzi o altri rilevamenti dei livelli 0–2. Un
nome o un'intera predizione che oltrepassa l'intervallo clinico non viene
scartato. Le etichette sensibili producono candidati limitati al nome;
non attribuiscono automaticamente l'identità del paziente al nominativo.

Non vengono trasferite le soglie americane sull'età, le regole specifiche
UCSF o liste estese di parole sempre esenti. Il riuso di queste regole non
costituisce una certificazione di copertura di ogni documento clinico.

## EDS-Pseudo, OpenMed, EDS-PDF e medspaCy

L'integrazione del 4 novembre 2026 riusa risorse selezionate e criteri dei
quattro progetti, senza installarne i motori. GLiNER, l'OCR, il modello e
la gestione adattiva dei thread restano invariati. Il file
`src/anonymizer/data/external_rules.json` contiene risorse effettivamente caricate,
pattern originali di confronto, revisioni, URL, dimensioni e SHA-256.
I sorgenti di studio sono in `build/artifacts/external-rules-sources/`;
non sono necessari a runtime e non contengono documenti degli utenti.

| Fonte fissata | Riuso e adattamento |
| --- | --- |
| [EDS-Pseudo](https://github.com/aphp/eds-pseudo/tree/b8bfde4a0e6ca31ac5ea85483757294d48f19d03), BSD-3-Clause | Criteri di combinazione dei componenti degli indirizzi da `addresses/addresses.py` e normalizzazione dei dati già noti da `structured.py`. Implementazione locale con offset originali; nessuna importazione dei matcher spaCy o delle convenzioni francesi. |
| [OpenMed](https://github.com/maziyarpanahi/openmed/blob/29ffa70050cc7729a0051be419a1b090699a5ed1/openmed/core/pii_i18n.py), Apache-2.0 | Prefissi stradali e parole contestuali italiane estratti da `_ITALIAN_PII_PATTERNS`. La regex originale dell'indirizzo e quella del CAP sono conservate per tracciabilità, ma non eseguite: le sostituisce un parser limitato per componenti. |
| [EDS-PDF](https://github.com/aphp/edspdf/blob/7177a29534181686d035c85fa667784e7d930482/edspdf/structures.py), BSD-3-Clause | Riferimento per elaborare blocchi tramite coordinate. L'associazione etichetta-valore è codice locale sulle `TextRegion` già prodotte dall'estrazione; non usa classificatori o modelli EDS-PDF. |
| [medspaCy](https://github.com/medspacy/medspacy/blob/b7bb7d82f2e8fbadc9ab26d6b4c37578f8883c2c/medspacy/postprocess/postprocessor.py), MIT | Riferimento metodologico per il postprocessing delle entità. Le condizioni italiane sono nuove regole locali con intervallo limitato. Il file italiano `resources/it/context_rules.json` della revisione è vuoto: non viene presentato come un pacchetto di regole italiane recuperato. |

Gli adattamenti comprendono:

- Indirizzi: strada e civico, seguiti da CAP e città/provincia con separatori
  limitati; nessuna classificazione automatica di una città isolata o di un
  numero clinico come indirizzo. I componenti conservano intervalli distinti.
- Contatti di struttura: le righe adiacenti possono fornire evidenza di
  indirizzo/telefono, senza attraversare paragrafi vuoti. Il nome della
  struttura richiede comunque una denominazione plausibile. Una estensione
  locale riconosce anche denominazioni di 1–4 parole con forma legale a inizio
  riga, soltanto in presenza di quei recapiti; non usa liste di marchi né
  propaga automaticamente un marchio isolato di una sola parola.
- Identità note: normalizzazione di Unicode e varianti di apostrofi e
  trattini, conservando la corrispondenza con gli offset del documento.
  Non viene introdotto un confronto fonetico o una distanza arbitraria tra nomi.
- Campi visuali: etichetta e valore vicini a destra o sotto, con limiti
  geometrici e rispetto delle colonne. I candidati mantengono gli offset
  originali; testo clinico interposto nell'ordine di estrazione non viene
  incluso solo per unire due parole del nome.
- Contesto clinico: etichette esplicite come `Paziente:` o `Medico curante:`
  e sostantivi in espressioni come `interpretazione del referto` proteggono
  soltanto il testo generico identificato, non il nome seguente né una sezione
  intera. Sono aggiunte locali ispirate al postprocessing, non traduzioni
  di regole medspaCy inesistenti.

Le nuove protezioni appartengono a `clinical_context_v6`. Continuano a
filtrare solo candidati NER L3 interamente contenuti, mai L0-L2 o identità
note; le versioni precedenti degli audit restano leggibili. Nessuna lista
estesa di parole è dichiarata sempre innocua.

Le licenze complete sono distribuite in `src/anonymizer/data/EDS_PSEUDO_LICENSE.txt`,
`OPENMED_LICENSE.txt`, `EDSPDF_LICENSE.txt` e `MEDSPACY_LICENSE.txt`.
È incluso anche `OPENMED_NOTICE.txt`, il NOTICE originale di OpenMed: i
componenti elencati in quel documento descrivono il progetto upstream e
non implicano che siano installati in Anonymizer. Le modifiche rispetto
alle fonti sono descritte qui e nel JSON delle regole.

Non sono adottati il validatore OpenMed del codice fiscale basato sul solo
formato, nuovi modelli NER/LLM, soglie americane sulle età o corpus con
licenza non definita. La correttezza e il costo delle nuove condizioni
sono verificati separatamente dalla valutazione del modello.

### Estensione locale: campi separati e ripetizioni

Il successivo affinamento aggiunge codice locale, senza ulteriori risorse
upstream o dipendenze. Le etichette separate `Nome:` e `Cognome:` devono
formare una coppia vicina: il testo usa separatori e distanze limitati; se
sono presenti coordinate, la pipeline richiede l'associazione geometrica.
Un valore composto del solo campo Nome non viene trattato come nome completo.

Le iniziali con punto sono ammesse dopo titoli o etichette mediche esplicite,
insieme ad almeno una componente estesa. Una sequenza di sole iniziali non
basta. Le etichette `Direttore sanitario:` e `Direttrice sanitaria:` richiedono
il separatore esplicito. Queste condizioni non identificano automaticamente
la persona nell'anagrafica.

I nomi completi riconosciuti da regole contestuali o geometriche consentite
possono essere ritrovati nelle altre pagine dello stesso documento tramite
confronto esatto normalizzato Unicode, mantenendo gli offset originali.
Partecipano anche i nomi completi riconosciuti da GLiNER con confidenza almeno
0,90; le ripetizioni conservano livello L3 e natura di proposta da revisionare.
Per i nomi di due parole, senza particelle, si cerca anche l'ordine invertito.
Non alimentano questo passaggio dizionario, componenti dei campi separati,
iniziali o frammenti geometrici. Non si cercano cognomi isolati né varianti
OCR approssimative; non c'è propagazione transitiva tra rilevamenti. I risultati
clinici protetti non vengono oscurati dalla propagazione NER. Le protezioni
NER restano v6.

### Campi di evento e identificativi amministrativi

La decisione del 5 novembre 2026 mantiene visibile il sesso anagrafico e
introduce l'oscuramento contestuale di date, giorni e orari che identificano
visite, prelievi, accettazioni, referti e altri eventi documentati. Sostituisce
la precedente conservazione indiscriminata delle date degli eventi.
Le date senza contesto identificativo non vengono automaticamente oscurate;
durate, frequenze e indicazioni di terapia devono restare leggibili.

Le nuove regole sono codice locale, senza dipendenze o codice upstream
aggiuntivi. Si basano su etichette e valori vicini, con associazione geometrica
per i campi disposti in tabella. Comprendono identificativi di protocollo,
cartella, referto e accettazione, oltre a luoghi amministrativi espliciti.
Non cercano numeri isolati o termini geografici mediante regex indiscriminate.
La politica di mascheratura è condivisa fra testo e documenti visuali;
resta necessaria la revisione delle proposte, soprattutto con OCR incompleto.

### Documenti di riconoscimento italiani — fonti consultate il 5 novembre 2026

Le regole locali per documenti di identità derivano dalla struttura dei campi
pubblicata dalle autorità, senza importare codice o immagini da altri prodotti.
L'obiettivo è individuare dati da oscurare, non certificare l'autenticità o la
validità del documento. Anche un documento scaduto contiene identificativi.

| Documento | Evidenza ufficiale e conseguenza per il rilevamento |
| --- | --- |
| Carta d'identità cartacea | La [risposta del Ministero dell'Interno pubblicata dal Senato](https://www.senato.it/show-doc?id=611986&leg=16&tipodoc=Sindispr) descrive la numerazione con due lettere e sette cifre e la sua estensione ai modelli bilingui. Il [modello PRADO ITA-BO-03001](https://www.consilium.europa.eu/prado/it/ITA-BO-03001/index.html) documenta la disposizione del documento cartaceo. |
| Carta d'identità elettronica | Il [Ministero dell'Interno](https://www.cartaidentita.interno.gov.it/cose-la-carta/caratteristiche-del-documento/) descrive il seriale con due lettere, cinque cifre e due lettere, il CAN, la MRZ e il codice fiscale anche come codice a barre. La frase sul formato è la base della regola: gli esempi tipografici nella pagina non sono un validatore. |
| Patente | Il [Portale dell'Automobilista](https://www.ilportaledellautomobilista.it/web/portale-automobilista/la-patente-di-guida) associa 1 al cognome, 2 al nome, 3 alla nascita, 4a/4b al rilascio/scadenza, 4c all'autorità e 5 al numero. Il [catalogo PRADO](https://www.consilium.europa.eu/prado/it/prado-documents/ita/f/o/docs-per-type.html) documenta più generazioni: un solo formato rigido del numero non garantisce la copertura delle versioni storiche. |
| Passaporto | Il [decreto sul passaporto ordinario, articolo 1](https://www.gazzettaufficiale.it/atto/serie_generale/caricaArticoloDefault/originario?atto.codiceRedazionale=10A05685&atto.dataPubblicazioneGazzetta=2010-05-19&atto.tipoProvvedimento=DECRETO) descrive il seriale di due lettere e sette cifre, le ripetizioni e perforazioni, i campi della pagina anagrafica e le righe OCR. Il [modello PRADO ITA-AO-02005](https://www.consilium.europa.eu/prado/it/ITA-AO-02005/index.html) documenta la versione introdotta nel 2023. |

Le specifiche [ICAO 9303 parte 4](https://www.icao.int/sites/default/files/publications/DocSeries/9303_p4_cons_en.pdf)
e [parte 5](https://www.icao.int/sites/default/files/publications/DocSeries/9303_p5_cons_en.pdf)
descrivono rispettivamente la MRZ TD3, due righe da 44 caratteri, e TD1,
tre righe da 30 caratteri. La parte 5, sezione 3.2.3, definisce il CAN come
sei cifre senza cifra di controllo. La MRZ ripete dati personali e numero:
quando riconosciuta deve essere oscurata interamente. Un checksum errato
non è una ragione per lasciare in chiaro dati plausibili letti dall'OCR.

Queste strutture non giustificano una regex universale su tutti i codici
alfanumerici dei referti. Numeri, campi numerati e valori senza etichetta
richiedono contesto documentale; i campi devono restare associati alle loro
etichette anche in presenza di più colonne. Il sesso resta visibile nella
parte in chiaro, secondo la scelta del progetto; non viene estratto dalla
MRZ per conservarne un frammento leggibile.

Foto, firme manoscritte, immagini secondarie del volto, codici a barre/QR
e numerazioni perforate non sono coperti dal solo rilevamento testuale.
La scansione non contiene il chip NFC: non sono previsti lettura del chip
o accessi a banche dati. Il controllo visuale deve coprire le zone residue
con lo strumento Disegna; non si dichiara anonimizzazione completa sulla
sola base delle regex o di un esito positivo sui campioni sintetici.

L'implementazione in `src/anonymizer/detect/identity_documents.py` usa
etichette italiane, inglesi e traduzioni francesi dei passaporti, campi
numerati coerenti della patente e coordinate OCR quando disponibili.
Comprende nascita, rilascio/scadenza, residenza, autorità, genitori/tutori
ed estremi dell'atto di nascita quando associati alle rispettive etichette.
Il CAN senza etichetta richiede una riga isolata e prova di CIE elettronica.
I campi numerati non si attivano su un semplice elenco clinico; un numero
interno a una posologia non può fungere da etichetta della patente.

Le MRZ italiane riconosciute hanno prefisso TD1 `A`, `C` o `I`, oppure TD3
`P`, seguito dal codice emittente `ITA`; la nazionalità del titolare può
essere diversa. La struttura viene verificata senza richiedere checksum
valido, tollerando spazi e alcune confusioni OCR nelle posizioni numeriche.
Seriali alfanumerici sufficientemente lunghi, riconosciuti nei campi o
nella MRZ, vengono cercati anche sulle altre pagine dello stesso file.
La propagazione non attraversa `source_id` diversi e non usa confronti fuzzy.

I seriali riutilizzano `Kind.CASE_NUMBER` con provenienza `identity:*`;
le date documentali sono mascherate mediante la politica condivisa tra
testo e raster. Non cambia lo schema, il modello NER o il parallelismo.
Le pagine riconosciute mostrano un promemoria visuale specifico senza
aggiungere un'altra sezione di controlli alla schermata di verifica.

La successiva correzione sui facsimili ufficiali distingue l'importazione
dall'OCR: i PNG sRGB dichiarati validamente vengono accettati senza cambiare
i pixel. Una seconda lettura OCR mirata può migliorare il contrasto del
testo scuro e ingrandire una copia temporanea entro un limite di pixel;
queste trasformazioni non vengono applicate all'immagine esportata.
Il tentativo richiede indizi documentali e condivide il timeout della prima
lettura. I soli campi nome/cognome/nascita di un referto non lo attivano.

Il riconoscimento tollera un titolo contaminato da annotazioni soltanto
con indizi indipendenti, e alcune confusioni OCR nelle posizioni numeriche
dei seriali CIE. La MRZ danneggiata richiede struttura su tre righe e
coerenza geometrica, non semplicemente una sequenza alfanumerica.
Gli identificativi ambigui non diventano seriali ricostruiti da propagare.
Il risultato alternativo deve conservare la copertura delle maschere
già proposte dalla prima lettura; un tentativo inconcludente conserva
la prima lettura e segnala la necessità di revisione.
