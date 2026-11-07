# Installativo Windows per il test

Il pacchetto di prova si trova in
`dist/installer/Anonymizer-Setup-0.1.0.9-x64.exe`.
La procedura mostra la licenza d'uso esclusivamente personale, che va
accettata per proseguire; il testo è installato anche come `LICENSE.txt`.
Questa versione separa i pesi del modello dal setup: il file ONNX misura
1.157.129.714 byte e viene scaricato automaticamente da Hugging Face al primo
avvio, se manca. Non richiede account, token o conversioni sul PC dell'utente.
Il tokenizer e la configurazione offline (circa 16 MB) sono inclusi nel setup.
Il setup misura 406.605.849 byte (circa 407 MB), contro 831.830.831 byte
della versione 0.1.0.4: circa il 51% in meno. Rispetto alla versione iniziale
da 1.771.884.450 byte con modello incluso, la riduzione è circa il 77%.
SHA-256: `afbaa32103cd54cdf08ede5afaf93f0595b1c0e4306da2bd4369648ef2b444ca`.

La versione 0.1.0.4 estende la ricerca delle ripetizioni ai nomi completi
riconosciuti da GLiNER con confidenza almeno 0,90 e cerca anche l'ordine inverso
dei nomi di due parole senza particelle. Il confronto riguarda tutte le pagine
dello stesso documento, comprese quelle precedenti alla prima rilevazione.
Le proposte NER conservano il livello L3 e richiedono revisione. Iniziali,
componenti isolate e varianti OCR approssimative non vengono propagate.

È destinato a Windows 10/11 x64. Include il runtime Python, QtWebEngine,
Tesseract con lingua italiana e licenze dei componenti.
Non richiede installazioni separate di Python, .NET o WebView2.
Il modello deriva da `urchade/gliner_multi-v2.1`, già usato dal progetto.
Il download usa l'esportazione FP32 pubblica
[`onnx-community/gliner_multi-v2.1`](https://huggingface.co/onnx-community/gliner_multi-v2.1),
revisione `6ddaeb9413b0e71ad8457da1aab378a165b24058`.
Questa esportazione sostituisce quella ONNX generata localmente: nel confronto
su 44 testi sintetici ha riconosciuto gli stessi intervalli e tipi di entità,
con differenza massima dei punteggi di 0,00000418. Il confronto diretto del
backend usa il suo limite nativo di 384 parole; i due testi più lunghi sono
stati confrontati anche attraverso il rilevatore a finestre, ottenendo le
stesse entità sull'intero testo. Queste prove sintetiche non costituiscono una
validazione clinica. Le regole applicative restano le stesse. Anche la portable
completa locale contiene questa esportazione.

Installa esclusivamente la portable Qt di `dist/Anonymizer-Qt`, avviata
tramite `Anonymizer.exe`. Non installa una webapp separata, servizi Windows
o avvii automatici. La finestra Qt usa internamente l'interfaccia condivisa
e un backend su una porta locale dinamica, attivo soltanto durante l'uso
dell'applicazione. La webapp di sviluppo sulla porta 8765 è indipendente
e non viene distribuita come applicazione aggiuntiva.

## Istruzioni per chi prova il programma

1. Copiare il file di installazione sul PC e aprirlo.
2. Seguire la procedura in italiano. L'installazione riguarda il solo utente
   corrente e non richiede privilegi amministrativi.
3. Avviare Anonymizer dal menu Start o dal collegamento sul desktop, se scelto.
4. Al primo avvio connettersi a Internet e attendere il download da Hugging Face:
   la finestra mostra percentuale, MB trasferiti, verifica e preparazione.
   Se il download si interrompe, premere **Riprova**; i byte già scaricati
   vengono riutilizzati quando il server supporta la ripresa.
5. Poi caricare un'immagine o un PDF.
   Verificare gli oscuramenti prima di esportare il risultato.

La destinazione predefinita è `%LOCALAPPDATA%\Programs\Anonymizer`.
Il modello lavora sul PC; il primo caricamento può richiedere tempo.
Il modello scaricato viene conservato in `%LOCALAPPDATA%\Anonymizer\models`,
separato dall'installazione e dai documenti. Ogni avvio ne verifica l'integrità:
se presente e valido, non viene scaricato di nuovo e non serve Internet.
La cache è associata al contenuto del modello, non al numero dell'installer:
aggiornare solo l'applicazione non provoca un nuovo download.
Il modello preparato occupa circa 1,17 GB; durante il primo download servono
circa 2,34 GB liberi per download e preparazione, oltre all'applicazione.
La disinstallazione conserva questa cache per un'eventuale reinstallazione.

Per rimuovere il programma usare **Impostazioni → App → Anonymizer**.
La disinstallazione rimuove i file installati dal pacchetto e i suoi
collegamenti; non cancella ricorsivamente cartelle contenenti altri file
né i documenti salvati dall'utente.

Questa distribuzione di test non è firmata digitalmente: Windows può
mostrare un avviso di editore sconosciuto. Non vengono disattivate le
protezioni di Windows. La verifica su un PC Windows pulito e su hardware
rappresentativo degli utenti resta parte della prova esterna.

## Contenuto e integrità

Il costruttore usa il bundle Qt e verifica gli hash di `bundle.json` prima
della compilazione. Include soltanto i file elencati nel manifest e il
manifest stesso, evitando di raccogliere file aggiunti incidentalmente
alla cartella portable. Il pacchetto contiene le stesse regole della standalone.
Il descrittore `model-download.json` fissa URL HTTPS con revisione immutabile,
dimensione e SHA-256 del file ONNX e dei quattro file di supporto. Il modello
diventa utilizzabile soltanto dopo tutte le verifiche. Sono controllati anche
i reindirizzamenti HTTPS del CDN di Hugging Face. Non si usa `main` come revisione
di download, né vengono richieste credenziali Hugging Face.
La connessione esterna serve esclusivamente a scaricare il modello prima
dell'avvio del backend: l'elaborazione dei documenti resta locale e offline.

Il file SHA-256 accanto all'installatore permette di confrontare l'integrità
della copia inviata. La compilazione e il collaudo locale sono descritti
in `validation.md`.

Per questa revisione sono passati 849 test automatici, con 2 test opzionali
saltati. È stato esportato e riaperto un PDF sintetico di tre pagine, simulando
il riconoscimento NER solo sulla prima: gli oscuramenti del nome risultano
presenti in tutte e tre le pagine, anche con nome e cognome invertiti.
Il referto reale segnalato dall'utente non è ancora stato fornito per il confronto.
Verificati nella 0.1.0.3 anche il trasferimento HTTPS reale da Hugging Face,
la verifica del file completo e il secondo accesso alla cache senza rete.
Il backend della portable ha avviato OCR e NER dal modello fuori dal bundle;
la pagina iniziale e lo stato del servizio riportano entrambi `0.1.0.3`.
La 0.1.0.4 mantiene gli stessi file del modello e la stessa cache. Nel runtime
della portable sono stati verificati la nuova regola multipagina e il numero
di versione in prima pagina; i metadati Windows dell'installer riportano `0.1.0.4`.
Verificata anche la connessione HTTPS dal runtime Python incluso nella portable,
con risposta parziale HTTP 206 da Hugging Face.

## Ricostruire l'installativo

Dalla 0.1.0.5 il costruttore esclude dal payload i file di sviluppo `.lib`,
`.pdb`, `.h`, `.hpp`, le directory include di Torch/NumPy/Qt e il pacchetto
debug dei DevTools Chromium. Mantiene DLL, moduli Python, bytecode, licenze
e risorse dell'interfaccia. La compressione usa `lzma2/normal` e modalità solid.
Il payload installato su un PC pulito occupa 1.747.252.779 byte.
Un aggiornamento sopra una versione precedente può conservare vecchi file
di sviluppo già presenti: questa riduzione su disco si riferisce a una
installazione pulita. Il peso del nuovo installer è ridotto in ogni caso.

La portable `dist/Anonymizer-Qt-compact` contiene lo stesso payload della build
0.1.0.5. Collaudati avvio del backend, pagina iniziale Qt, OCR reale, inferenza
ONNX e proposte di oscuramento su un'immagine sintetica. Passati 58 test
mirati su packaging e desktop. Il modello rimane quello della 0.1.0.4.

Su Windows, partire dal bundle Qt completo e da un compilatore Inno Setup
6.5.2 o successivo della serie 6, ottenuto dal progetto ufficiale.
Il compilatore serve soltanto sul PC di sviluppo.

```powershell
.venv\Scripts\python.exe tools\packaging\windows\build_installer.py `
  --bundle dist\Anonymizer-Qt `
  --iscc tools\local\inno-setup\installed\ISCC.exe `
  --output dist\installer `
  --model-download tools\packaging\windows\huggingface-model.json
```

`--iscc` può indicare un'altra installazione locale. Se omesso, il costruttore
cerca il compilatore nel PATH e nelle destinazioni usuali. La directory di
output deve essere esterna al bundle e non deve contenere artefatti omonimi:
la build non sovrascrive un installatore già prodotto. Il rapporto JSON
accanto all'eseguibile riporta versione del compilatore, dimensione, hash
del manifest di origine e hash dell'installatore.

Il bundle completo deve contenere il modello pubblico corrispondente al
manifest `tools/packaging/windows/huggingface-model.json`. Per prepararlo a partire
dai file di supporto del modello locale precedente:

```powershell
.venv\Scripts\python.exe tools\packaging\windows\prepare_huggingface_model.py `
  --support-model tools\local\models\gliner-onnx-verified `
  --output tools\local\models\gliner-huggingface
```

Il comando verifica i file di supporto, scarica il file ONNX fissato nel manifest
e verifica hash e grafo. Usare questa cartella come modello durante la
preparazione della portable completa. Il costruttore dell'installer rifiuta
un bundle il cui modello differisce dal descrittore. Omettere `--model-download`
per un installer completo offline. Il precedente costruttore ZIP resta
utilizzabile per distribuzioni personalizzate, ma non serve per Hugging Face.

Il contatore `tools/packaging/windows/version.json` parte dalla build 1 già
distribuita. Ogni build riuscita incrementa l'ultima cifra (`0.1.0.2`,
`0.1.0.3`, …); un errore non consuma un numero. Un lock impedisce a due
build contemporanee di usare la stessa versione. La stessa versione viene
scritta nel nome dell'installer, nei metadati Windows, nel manifest e nel
payload dell'app: è visibile nella pagina iniziale e nel titolo della finestra.

Lo script `tools/packaging/windows/installer.iss` usa un AppId stabile per gli
aggiornamenti della stessa applicazione. Prima di aggiornare, chiudere
Anonymizer: l'installatore non termina automaticamente i processi aperti.
Non sono definite cancellazioni ricorsive in fase di disinstallazione.
