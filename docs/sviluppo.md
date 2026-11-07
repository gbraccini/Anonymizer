# Anonymizer — guida per sviluppatori

Stato del prototipo, struttura del repository, ambiente di sviluppo, build Windows
e uso da riga di comando. La presentazione del prodotto è nel [README](../README.md).

## Stato del prototipo

Il core comprende dati noti del paziente e di terzi, regex, vocabolario sintetico
di sviluppo, fusione degli intervalli, pseudonimizzazione e mappa versionata.
Il percorso documentale aggiunge analisi di immagini/PDF, OCR, NER locale opzionale,
proposte geometriche e produzione di copie realmente oscurate. La CLI serve a collaudare il motore;
l'output richiede revisione e non costituisce una garanzia di anonimato.

È disponibile un prototipo browser di revisione esclusivamente locale.
L'autenticazione per l'accesso condiviso non è ancora integrata.
La GUI HTML/CSS/JavaScript è condivisa con il prototipo desktop Windows portabile:
la finestra dedicata riutilizza gli stessi asset e lo stesso motore Python.
La cartella portable include eseguibile, Python, OCR e modello NER ONNX.
Il collaudo completo dell'interfaccia desktop e la verifica su Windows pulito
restano da completare. È disponibile anche un installativo per il test,
non firmato digitalmente; le istruzioni sono in
[windows-installer.md](windows-installer.md).
È richiesto anche il collegamento opzionale all'anagrafica locale di un gestionale clinico, quando
disponibile. Il core gestisce già dati noti, ma connettore e pannello anagrafico
nella GUI non sono ancora implementati. Prima del prossimo blocco di integrazione,
la priorità è ridurre il costo OCR/NER e validare i tempi su hardware rappresentativo
dei PC degli utenti; le prestazioni della standalone non sono ancora accettate.
Il vocabolario incluso non copre nomi e strutture italiani in generale.
I tempi delle fasi sono esposti nel prototipo; recall clinico ed efficacia della
revisione su documenti reali restano da misurare.

## Ambiente di sviluppo

### Struttura del repository

```text
Anonymizer/
  src/
    anonymizer/       applicazione, motore e interfaccia condivisa
    tests/            test e fixture sintetiche
  docs/               specifica, piano e documentazione
  dist/               portable e installer pronti da distribuire
  build/              build intermedie, cache e risultati delle verifiche
  tools/
    packaging/        script per portable e installer Windows
    experiments/      valutazione e preparazione del modello
    deploy/           riferimento della precedente prova Docker
    local/            strumenti e modelli scaricati, esclusi da Git
    test-data/        campioni di prova locali, esclusi da Git
```

In radice restano README, configurazione del progetto, `.git` e `.venv`.
`dist`, `build`, `tools/local` e `tools/test-data` sono ignorati da Git: in un
checkout nuovo i percorsi citati sotto esistono solo dopo aver rifatto le build.
I sorgenti installabili sono esclusivamente in `src/anonymizer`; test e
strumenti non entrano nel pacchetto distribuito. I comandi seguenti si
eseguono dalla radice del repository. Dopo lo spostamento di un checkout
già installato, aggiornare l'installazione editable con
`uv pip install --python .venv/Scripts/python.exe --no-deps -e .`.
La documentazione è raccolta direttamente in `docs`, senza livelli aggiuntivi.

### Installativo Windows per i tester

Il nuovo file di test è `dist/installer/Anonymizer-Setup-0.1.0.7-x64.exe`.
La procedura in italiano mostra la licenza d'uso esclusivamente personale,
che va accettata, e installa la variante Qt per il solo utente corrente,
senza richiedere privilegi amministrativi. Comprende Python e OCR italiano;
al primo avvio scarica il modello ONNX pubblico da Hugging Face (circa 1,16 GB),
mostrando avanzamento e possibilità di riprovare. Se il modello è presente e
integro, lo riusa senza connessione. Propone collegamenti nel menu Start e sul
desktop e registra la disinstallazione nelle App di Windows. La versione compare
nella pagina iniziale e aumenta a ogni installer generato.
Vedere [istruzioni e requisiti](windows-installer.md).

### Eseguibile Windows portabile

La variante alleggerita 0.1.0.7 è in `dist/Anonymizer-Qt-compact`:
avviare `Anonymizer.exe` e mantenere tutta la cartella. Come l'installer,
scarica il modello da Hugging Face se non è già presente nella cache verificata.
Occupa circa 1,75 GB prima del download del modello. La portable completa
precedente, con modello incluso, rimane nella cartella indicata sotto.

Nel checkout preparato, avviare `dist/Anonymizer-Qt/Anonymizer.exe`. Mantenere
l'intera cartella `Anonymizer-Qt`: l'eseguibile usa le cartelle adiacenti
`runtime`, `ocr`, `models` e `_internal`. Per spostare l'app, copiare tutta la
cartella. Non occorre installare separatamente Python, Tesseract o il modello.
La finestra usa PySide6 e QtWebEngine inclusi nel pacchetto: non richiede
installazioni separate di .NET o Microsoft Edge WebView2. La precedente build
`dist/Anonymizer` usa ancora WebView2 e non va confusa con la variante Qt.

L'app apre una finestra dedicata massimizzata, mostra un indicatore durante il
caricamento e avvia il proprio servizio su una porta loopback dinamica. La
webapp di sviluppo su `http://127.0.0.1:8765` resta indipendente. Il modello
lavora offline con thread scelti in base a CPU e memoria disponibili; alla chiusura vengono arrestati il
servizio desktop e i suoi processi figli. Non vengono archiviati documenti o
risultati; i file temporanei della sessione seguono la normale pulizia locale.

OCR e NER lavorano su pagine diverse contemporaneamente quando il budget hardware
lo consente, usando un solo modello e una coda limitata. Sui PC con poche risorse
restano sequenziali. Criteri, opzioni e significato dei tempi sono descritti in
[performance.md](performance.md).

La build usa [build_portable.py](../tools/packaging/windows/build_portable.py) su Windows
con CPython 3.12, extra `web,visual,ocr,ner-onnx,desktop,desktop-build` e Torch CPU.
Parametri richiesti: `--python-root`, `--ocr-root`, `--tessdata`, `--model`,
`--ocr-licenses`, `--model-licenses`, `--qt-licenses` e `--output` (directory nuova). Gli input
sono runtime Python standalone, OCR italiano e bundle ONNX già verificati.
`bundle.json` elenca versioni, provenienza del modello e hash dei file.
I componenti Qt rimangono librerie separate nel runtime; i testi e gli avvisi
raccolti per Qt sono sotto `licenses/qt`, oltre alle licenze delle wheel.
Il marchio condiviso è `src/anonymizer/web/static/anonymizer.svg`: documento bianco
con barre di oscuramento su fondo petrolio. Per rigenerare PNG e ICO dalle forme
vettoriali eseguire `.venv\Scripts\python.exe tools\packaging\windows\build_icons.py`
prima della build. L'ICO multirisoluzione viene incorporata nell'eseguibile;
pagina iniziale, favicon, finestra Qt e caricamento usano lo stesso marchio.
La build precompila le librerie con cache validate tramite hash, mantenendo i
sorgenti; l'avvio `-I -B` usa quelle cache senza crearne di nuove nel pacchetto.

### Prova Debian abbandonata

Il 3 novembre 2026 la prova su un server Debian di sviluppo è stata giudicata troppo lenta e disinstallata dal server, compreso il modello. Si prosegue con
l'elaborazione locale su `http://127.0.0.1:8765`. La porta 8766 e il tunnel della
prova non sono più da utilizzare. Risultati e cronaca sono conservati nella
[validazione](validation.md); i file Docker nel repository restano come
riferimento dell'esperimento, non come distribuzione attiva.

### Sviluppo locale

Richiede Python 3.12 o successivo. Esempio Windows con uv:

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -e ".[dev]" build
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check src tools/packaging tools/experiments tools/deploy
.\.venv\Scripts\python.exe -m build --wheel
```

Il codice è documentato in italiano in formato Doxygen. Con Doxygen installato,
`doxygen Doxyfile` genera l'HTML in `build/doxygen/html/index.html`.

Il core testuale non richiede librerie OCR o modelli. Per il percorso documentale
installare anche gli extra visual e ocr e predisporre Tesseract con lingua italiana:

```powershell
uv pip install --python .venv\Scripts\python.exe -e ".[dev,visual,ocr]"
$env:ANONYMIZER_TESSERACT = "C:\percorso\tesseract.exe"
$env:ANONYMIZER_TESSDATA = "C:\percorso\tessdata"
```

I percorsi sono esempi da sostituire. L'extra web abilita il prototipo browser locale.
Ambiente locale, tool scaricati e report non vanno aggiunti al repository.

Nell'ambiente locale preparato per questo checkout, Tesseract 5.5.3 con lingua
italiana è disponibile in tools/local/tesseract-conda. Per usarlo nella
sola sessione PowerShell corrente:

```powershell
$env:ANONYMIZER_TESSERACT = (Resolve-Path tools\local\tesseract-conda\Library\bin\tesseract.exe).Path
$env:ANONYMIZER_TESSDATA = (Resolve-Path tools\local\tesseract-conda\share\tessdata).Path
```

Questa cartella è locale e ignorata da Git; un nuovo checkout richiede di
predisporre nuovamente Tesseract. Non serve modificare il PATH di sistema.

## Revisione nel browser locale

Installare anche l'extra web e configurare Tesseract come sopra. Con il modello
locale già preparato, avviare dalla root del repository:

```powershell
uv pip install --python .venv\Scripts\python.exe -e ".[dev,visual,ocr,ner,web]"
.\.venv\Scripts\python.exe -m anonymizer.cli serve --local-only --ner-model tools\local\models\gliner_multi-v2.1
```

Aprire http://127.0.0.1:8765 quando il servizio è pronto. Il modello viene caricato
una sola volta all'avvio. Il default è Torch con un numero di thread CPU automatico:
non equivale a un collaudo su un PC poco potente. È disponibile anche il runtime
ONNX CPU in precisione FP32, con gli stessi pesi, etichette e soglia, scelto
esplicitamente tramite `--ner-runtime onnx`. Gli artefatti locali sono verificati
prima del caricamento e il runtime viene registrato nel contratto di revisione.
Per escludere il NER
esplicitamente sostituire --ner-model e il percorso con --no-ner; lo stato ridotto
resta visibile; omettere anche --ner-runtime in quel caso.
Porta e thread sono configurabili con --port, --ner-threads e --ocr-threads.
L'opzione --serial disabilita la sovrapposizione per confronti controllati.
Per fermare un avvio in terminale usare Ctrl+C.

Preparazione ONNX offline, una sola volta a partire dal modello Torch già
verificato; la directory output deve essere nuova:

```powershell
uv pip install --python .venv\Scripts\python.exe -e ".[ner-onnx,web,visual,ocr]"
.\.venv\Scripts\python.exe tools\experiments\ner\prepare_onnx.py --source tools\local\models\gliner_multi-v2.1 --output tools\local\models\gliner-onnx-verified --cpu-threads 4
.\.venv\Scripts\python.exe -m anonymizer.cli serve --local-only --ner-model tools\local\models\gliner-onnx-verified --ner-runtime onnx
```

In questo checkout il bundle ONNX è già preparato: usare direttamente l'ultimo
comando. La conversione non è quantizzazione; la variante INT8 provata ha perso
identificativi ed è stata scartata. L'implementazione GLiNER continua a usare
componenti Torch anche con ONNX. Misure e limiti in [validation](validation.md).

Sul PDF locale di quattro pagine, il confronto con lo stesso OCR e quattro
thread ha ridotto NER più regole da 8,47 a 7,25 s, con stessi candidati e maschere.
Una richiesta HTTP successiva ha impiegato 18,45 s più 1,15 s per l'anteprima.
Sono misure locali su CPU di sviluppo: il requisito di velocità sui PC degli
utenti resta aperto, senza attribuire a ONNX il calo rispetto ai 46 s iniziali.

Il core offre inoltre `analyze_documents(..., pdf_hybrid=True)` per sperimentare
testo PDF nativo più OCR della grafica residua. Rimane disabilitato nella GUI/CLI:
ha ridotto il solo OCR, ma ha anche cambiato i candidati NER e non ha ancora
dimostrato un beneficio completo. Le maschere adiacenti dello stesso candidato
vengono compattate soltanto quando l'unione conserva esattamente i pixel oscurati.

1. Trascinare immagini/PDF nella prima pagina oppure selezionarli dal computer;
   rimuovere eventuali file prima dell'analisi. La qualità PDF predefinita è 300 DPI.
2. Confrontare originale e anteprima affiancati. Cliccare una parola per oscurarla,
   una maschera per ripristinare la leggibilità, un'area automatica tratteggiata
   per oscurarla nuovamente. Trascinare per coprire una zona libera, anche senza
   testo riconosciuto. Annulla e Ripristina consentono di correggere le modifiche.
3. Consultare "Note di lettura" nella barra e sfogliare liberamente il documento
   con Precedente/Successiva o il selettore sotto le anteprime. Le aree senza
   geometria richiedono un rettangolo manuale collegato al candidato indicato.
4. Confermare l'intero documento con una sola spunta, senza conferme separate
   delle pagine. Dopo l'aggiornamento dell'anteprima, copiare il testo oscurato
   completo o scaricare PDF raster, PNG per una sola pagina
   oppure un archivio ZIP con PDF e testo oscurato.
   Qualsiasi modifica richiede una nuova conferma; il server rifiuta revisioni
   diverse dall'anteprima confermata e originali sostituiti.

Durante l'analisi un indicatore di attività descrive l'elaborazione in corso;
non mostra percentuali stimate. Alla risposta del servizio, il messaggio passa
alla preparazione dell'anteprima.

La conferma unica è disponibile nella revisione: non occorre aprire ogni pagina
per abilitarla. La spunta approva le decisioni e le note dell'intero documento;
copia ed esportazione attendono l'anteprima aggiornata della stessa revisione.
Una modifica, Annulla o Ripristina annulla la conferma dell'intero documento;
sfogliare le pagine la conserva. Le geometrie mancanti sono controllate su tutte
le pagine e guidano alla prima area da completare. Un errore dell'anteprima offre
un'azione per riprovare o ripetere l'analisi quando la sessione non è più valida.
Impostazioni e stato dei servizi restano nella schermata iniziale.

Su desktop (almeno 1101 × 650 pixel CSS) la revisione usa l'altezza della finestra:
navigazione, conferma e passaggio finale restano visibili; anteprime e testi
scorrono nei propri riquadri. Su finestre più piccole resta disponibile lo
scorrimento della pagina per non tagliare i controlli.

Le anteprime hanno lato massimo di 1800 pixel; l'oscuramento viene applicato prima
della riduzione, con lo stesso renderer dell'export. La copia finale mantiene i
pixel alla risoluzione selezionata. Una visualizzazione ridotta non sostituisce
la verifica dei dettagli dell'output. "Nuovo documento" rimuove i documenti dalla
sessione dell'interfaccia; nessun salvataggio automatico nel browser è previsto.

Gli originali restano nel browser e vengono reinviati per anteprima ed export.
Il server conserva dati solo durante le richieste, con temporanei ordinari puliti
al termine; download espliciti restano nella cartella scelta dall'utente.
La revisione scade dopo un'ora o al riavvio del server: occorre ripetere l'analisi.

Il launcher ascolta solo su loopback, con una sola elaborazione alla volta e
rifiuto esplicito delle richieste concorrenti. Host, origine, dimensioni e
contratto di analisi sono controllati. Questo profilo non offre login o accesso
multiutente e non va pubblicato attraverso un proxy. Il timeout OCR è per pagina;
non è ancora disponibile un arresto forzato dell'intera elaborazione.
Il testo originale e quello oscurato sono visibili ai lati dei rispettivi
documenti, senza un pannello separato in fondo alla pagina. Su schermi piccoli
il testo si dispone sotto il documento corrispondente. Le note generali su OCR
e verifica clinica sono raccolte nella barra; il numero di note non indica il
numero di dati sensibili o di errori rilevati. Eventuali aree senza geometria
da completare restano segnalate e accessibili.
Il testo oscurato segue le maschere effettive, comprese quelle manuali e i ripristini:
qualsiasi regione testuale toccata viene omessa conservativamente. Le parti senza
coordinate diventano `[TESTO NON LOCALIZZATO]`. Il testo può perdere l'ordine delle
tabelle e non viene corretto o riscritto. Dopo la revisione finale si può copiare
il testo oscurato completo o scaricarlo insieme al PDF. Il download del testo
originale è distinto ed esplicito. Questo TXT usa `[OSCURATO]`, non i token
riassociabili della CLI testuale. Correzione OCR e riordino/esclusione pagine
restano fuori da questo prototipo. Gli asset della GUI restano condivisi con la
futura applicazione standalone.

## NER locale con GLiNER

Il riconoscimento combina regole, dizionario e NER. Una regola dedicata segnala
anche nomi non presenti nel dizionario preceduti da titoli espliciti come `Dr :`
o `Dott.ssa`, senza un'altra inferenza del modello. Non copre ogni forma di firma
e non sostituisce la verifica delle pagine.

Il modello aggiunge persone, luoghi e strutture sanitarie ai candidati delle
regole esistenti; le proposte diventano maschere sul documento. Non attribuisce
automaticamente il ruolo di paziente e non riscrive il contenuto clinico.
Può omettere identificativi o proporre maschere errate: controllare sempre
l'originale. Fonti, licenze, configurazione e misure sono in
[Valutazione NER](ner-evaluation.md).

Questo checkout ha già il modello verificato in tools/local/models/gliner_multi-v2.1.
Per predisporre un ambiente nuovo, installare prima la versione CPU di PyTorch
testata, poi l'extra NER:

```powershell
uv pip install --python .venv\Scripts\python.exe torch==2.7.1 --index-url https://download.pytorch.org/whl/cpu
uv pip install --python .venv\Scripts\python.exe -e ".[dev,visual,ocr,ner]"
.\.venv\Scripts\python.exe tools\experiments\ner\prepare_model.py --cache tools\local\hf-cache --output tools\local\models\gliner_multi-v2.1
```

L'indice CPU è quello indicato nelle [istruzioni ufficiali PyTorch](https://pytorch.org/get-started/previous-versions/#v271).
Il setup scarica esplicitamente circa 1,16 GB di pesi e i componenti del tokenizer,
verifica la revisione e l'impronta previste e crea il registro anonymizer_model.json.
La directory di output deve essere nuova. Pesi e cache restano esclusi da Git.
Le normali analisi usano esclusivamente il pacchetto locale: componenti mancanti
o modificati producono un errore, senza download automatico o fallback silenzioso.

Per abilitare il NER, passare --ner-model al comando analyze oppure anon.
--ner-threshold controlla la soglia, inizialmente 0.5. Senza modello, o con
--no-ner, il motore continua con L0/L1/L2 ma restituisce stato disabled e avviso
ner_disabled. L'export usa soltanto le maschere revisionate e non ricarica il modello.
Il manifesto registra modello, revisione, impronta e parametri NER; quelli creati
prima di questa estensione richiedono una nuova conferma della revisione.

Per includere nelle prove anche modello e OCR reali, configurare i percorsi
Tesseract sopra e impostare:

```powershell
$env:ANONYMIZER_TEST_NER_MODEL = (Resolve-Path tools\local\models\gliner_multi-v2.1).Path
.\.venv\Scripts\python.exe -m pytest
```

Le prove reali opzionali sono saltate quando gli strumenti non sono configurati.

## Prova con immagini e PDF esportati

Analizzare un originale e conservare il manifesto JSON localmente:

```powershell
.\.venv\Scripts\anonymizer.exe analyze esame.pdf --manifest esame.review.json --ner-model tools\local\models\gliner_multi-v2.1
```

Il manifesto contiene testo originale estratto, coordinate, proposte e avvisi:
è materiale sensibile di revisione, non un documento anonimizzato da condividere.
In questa CLI di sviluppo la revisione avviene sul JSON confrontandolo con
l'originale. Ogni pagina contiene redactions, espresse come quattro vertici in
pixel, origine in alto a sinistra dopo normalizzazione dell'orientamento.
Si possono modificare le aree e aggiungere maschere manuali anche per QR o firme.
Per rifiutare una proposta conservarla con decision="reject" e reason non vuoto;
non cancellarla. Le proposte prive di geometria richiedono una maschera manuale
collegata al candidato segnalato. Tutte le pagine devono rimanere presenti.

Solo dopo avere controllato maschere, avvisi e contenuto clinico, esportare:

```powershell
.\.venv\Scripts\anonymizer.exe export esame.pdf --manifest esame.review.json --output esame.oscurato.pdf --confirm-review
```

La conferma esplicita approva le decisioni correnti e gli avvisi. È un comando
di sviluppo, non una prova automatica dell'avvenuta revisione umana. Senza conferma
o un manifesto già approvato tramite API Python, l'export è bloccato. L'impronta
di revisione rileva modifiche successive; non è una firma né un controllo di
autorizzazione per il futuro servizio web. Gli originali sono ricontrollati tramite
SHA-256 e geometria prima dell'export.

Per una singola immagine usare lo stesso flusso e output .png. Più input, indicati
nello stesso ordine in entrambi i comandi, producono un PDF multipagina. Nessun file
esistente viene sovrascritto. Il PDF generato contiene soltanto le immagini già
oscurate: perde ricerca testuale e contenuti vettoriali. Il rendering predefinito
è a 300 DPI, modificabile in analisi con --dpi; non viene ridotto automaticamente.

Supporto iniziale: immagini JPEG/PNG/HEIC opache a 8 bit RGB o scala di grigi,
singolo fotogramma, entro la politica colore prevista. Alpha, HDR/16 bit,
profili colore non supportati e immagini multiple sono rifiutati esplicitamente.
I PDF misti o con elementi interattivi usano OCR; il testo nativo viene usato solo
nei casi conservativamente riconosciuti. L'output non riutilizza metadati, layer,
allegati o annotazioni originali. Fuori dalle maschere il riferimento è l'immagine
decodificata e orientata, oppure il rendering PDF alla risoluzione selezionata.
Per il PDF il confronto esatto riguarda la bitmap incorporata nella nuova pagina;
un lettore può ricampionarla quando la visualizza, quindi non si promettono
screenshot identici pixel per pixel. Leggibilità e dettaglio degli esami reali
richiedono ancora validazione.

Limiti predefiniti: 20 file, 50 MB totali, 30 pagine, 25 megapixel per pagina e
150 megapixel cumulativi. Le immagini non subiscono deskew o correzione prospettica
in questa fase. QR, firme e identificativi non testuali richiedono controllo e
maschere manuali. DICOM esclusi. La qualità su esami reali resta da validare.
Il TXT aggiuntivo del percorso documentale è disponibile nella GUI, sincronizzato
con le decisioni visuali. I comandi testuali sottostanti restano strumenti separati
del core; la CLI documentale non include ancora il TXT aggiuntivo.

## Prova con testo sintetico

Usare un file .txt UTF-8 e percorsi di uscita distinti, non già esistenti:

```powershell
.\.venv\Scripts\anonymizer.exe anon esempio.txt --output esempio.anon.txt --map esempio.map.json
.\.venv\Scripts\anonymizer.exe reassoc risposta.txt --map esempio.map.json --output risposta.riassociata.txt
```

Il primo comando produce testo e mappa separati e indica che è necessaria una
revisione. Il secondo riassocia solo segnaposto esatti e segnala il numero di token
sconosciuti. La mappa contiene intenzionalmente dati originali: rimane separata dal
testo da inoltrare al servizio IA. Questi file vengono scritti sul dispositivo che
esegue la CLI, su richiesta esplicita.

Per fornire dati noti e riferimenti temporali usare per ora l'API Python:

```python
from anonymizer.model import PageResult
from anonymizer.patient import KnownIdentity
from anonymizer.text_pipeline import analyze_text

page = PageResult(
    page_id="synthetic-page-1",
    source_id="synthetic-document-1",
    index=0,
    text="Paziente Elvio Veltrani. Non presenta febbre. Valore 12 mg.",
)
patient = KnownIdentity(
    values=(),
    role="patient",
    confirmed=True,
    given_name="Elvio",
    surname="Veltrani",
)
analysis = analyze_text([page], (patient,))
print(analysis.result.pages[0].text)
```

I dati dell'esempio sono sintetici. Confermare un'identità è una scelta esplicita
del chiamante, non una conseguenza della presenza di un CF nel testo.

## Contratto e limiti

- Intervalli per pagina in punti di codice Unicode, sul testo originale immutabile.
- Copertura sovrapposta unita conservando i candidati e i conflitti.
- Valori canonici distinti dalle forme osservate per occorrenza; l'annullamento usa
  la specifica forma originale.
- Il checksum non decide da solo se mascherare un CF plausibile; il secolo di
  nascita non viene inventato.
- Le date degli eventi restano visibili. Un'età richiede un riferimento temporale
  confermato; altrimenti la nascita viene sostituita con un segnaposto.
- Nessuna fusione automatica di persone basata soltanto sulla distanza di edit.
- Le varianti OCR L0 sono limitate alle confusioni deterministiche previste;
  il matcher generale a distanza di edit resta da implementare/misurare.
- Una sola forma canonica distinta per tipo di dato nella stessa identità: due
  telefoni/email distinti richiedono un'estensione del modello; oggi sono rifiutati
  per evitare riassociazione al valore sbagliato. IBAN iniziale italiano contiguo,
  targhe non coperte.
- La CLI testuale non sostituisce la futura revisione sull'immagine originale.

I [criteri di verifica](validation.md) riportano invarianti, prove e limiti.
Per la successiva fase OCR, i temporanei delle librerie sono ammessi per scelta di progetto: il progetto non promette per ora assenza assoluta di scritture.
