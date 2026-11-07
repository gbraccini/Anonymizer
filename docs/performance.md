# Esecuzione adattiva

Il modello GLiNER ONNX FP32, le soglie, le regole e la risoluzione OCR restano
invariati. La configurazione automatica sceglie il lavoro concorrente in base
alle CPU accessibili al processo e alla memoria disponibile all'avvio.

## Budget

Il rilevamento considera l'affinità del processo, i core fisici quando
identificabili e i limiti cgroup disponibili su Linux. Il budget conserva un
processore logico per l'interfaccia quando possibile, non supera i core fisici
rilevati ed è limitato a 12. In caso di informazioni insufficienti viene scelto
un profilo conservativo.

L'OCR usa normalmente un thread. Il NER usa fino a quattro thread; può usarne
otto con budget di almeno nove e almeno 6 GiB di memoria libera. Il valore viene
ridotto quando il budget CPU non basta. La sovrapposizione richiede almeno tre
CPU nel budget e 4 GiB disponibili; altrimenti le fasi sono sequenziali.

Sono criteri di selezione del profilo, non una garanzia di memoria massima o di
durata. Il modello viene caricato una volta e i thread non vengono riconfigurati
durante ciascuna richiesta. La memoria libera può cambiare dopo l'avvio.

## Pipeline

Un solo produttore rende e riconosce le pagine, mantenendo PDFium sequenziale.
Un solo consumatore esegue il NER mentre il produttore prepara la pagina
successiva. La coda contiene al massimo una pagina di testo e coordinate;
le immagini vengono chiuse prima dell'accodamento. Il modello non viene
duplicato. I risultati NER sono riutilizzati nel passaggio finale, che conserva
ordine delle pagine, regole documentali e propagazione dei dati della struttura.

Ogni errore interrompe l'analisi senza restituire risultati parziali. L'OCR
mantiene il timeout del processo separato. Una chiamata NER già in esecuzione
deve terminare prima del rilascio delle risorse: la scadenza opzionale della
pipeline viene controllata fra i lavori, non interrompe forzatamente il codice
nativo. La webapp continua ad ammettere una sola operazione alla volta.

## Controllo e misure

La CLI seleziona automaticamente i thread quando `--ner-threads` viene omesso.
`--ner-threads N`, `--ocr-threads N` e `--serial` consentono confronti controllati.
Un numero di thread esplicito viene rispettato; se supera il budget combinato,
la sovrapposizione viene disabilitata. L'endpoint locale `/api/health` espone il
profilo sotto `performance`; il contratto di revisione registra i thread NER
effettivi nel consueto audit.

`analysis_wall` misura il tempo reale complessivo. `render`, `ocr` e `ner`
misurano le durate delle rispettive attività: con sovrapposizione non vanno
sommati per ricostruire il totale. L'interfaccia mostra questa distinzione.

Il passaggio a OCR persistente tramite API nativa non è attivato: richiederebbe
un processo isolato riutilizzabile, pulizia dello stato fra pagine e verifica
dell'equivalenza. Una prova locale di PNG meno compresso e ingresso tramite
stdin non ha mostrato un guadagno. Il percorso PDF ibrido rimane sperimentale:
le prove precedenti non giustificano una modifica automatica all'estrazione.

I risultati dei confronti sono registrati in [validation.md](validation.md).

Nel confronto controllato del 4 novembre 2026, eseguito nel runtime Qt con lo
stesso modello caricato una volta e thread fissi NER/OCR 8/1, quattro analisi
complete in ordine sequenziale/sovrapposta/sovrapposta/sequenziale hanno dato
medie di 103,08 s e 90,78 s. La riduzione osservata è circa il 12%; tutti i
fingerprint degli output coincidono. Il campione sostiene il mantenimento
della sovrapposizione su questa macchina, ma non dimostra un beneficio su ogni
hardware e non raggiunge il precedente riferimento utente di circa 72 s.

Il caricamento del modello (15,54 s) e il riscaldamento iniziale sono esclusi
da queste durate. Il confronto misura la pipeline nel runtime distribuito:
non include apertura della GUI, trasferimento HTTP, anteprima o esportazione.
Sotto sovrapposizione le singole fasi OCR e NER rallentano; aumentare ancora
i thread non è quindi giustificato da queste misure. Nessuna nuova modifica
al modello o al profilo distribuito viene introdotta da questo confronto.
