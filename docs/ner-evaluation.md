# Valutazione NER locale

Data: 2026-11-03. Stato: integrazione e confronto sintetico completati; nessuna validazione clinica.

## Scopo e confronto

Il NER aggiunge candidati di livello L3 a L0/L1/L2, senza sostituire i rilevatori
esistenti o attribuire automaticamente l'identità del paziente. Le entità sono
intervalli del testo originale: passano attraverso merge e associazione alle
regioni OCR/PDF per proporre maschere sull'immagine. Il modello non riscrive
testo clinico e non ricostruisce pixel.

Confronto previsto: baseline L0/L1/L2 contro baseline più NER, sullo stesso corpus
sintetico annotato. Development ed evaluation hanno template e persone distinti;
le scelte di soglia ed etichette devono essere fissate prima dell'evaluation.
Il campione già visto "Beta Alfa" è una dimostrazione di sviluppo, non held-out.
La valutazione su testo estratto non misura le omissioni dell'OCR.

## Candidato e fonti

Primo candidato: `urchade/gliner_multi-v2.1`, revisione
`443d26d654e0324125a96bebd8e796c14ff2efe6`. È una scelta da valutare, non un
confronto già concluso tra tutti i modelli disponibili.

| Componente | Dichiarazione della fonte | Fonte |
| --- | --- | --- |
| Pesi GLiNER multi v2.1 | Multilingue, Apache-2.0 | [Model card](https://huggingface.co/urchade/gliner_multi-v2.1) |
| Codice GLiNER | Apache-2.0 | [Licenza](https://github.com/urchade/GLiNER/blob/main/LICENSE) |
| Backbone mDeBERTa-v3-base | MIT | [Model card Microsoft](https://huggingface.co/microsoft/mdeberta-v3-base) |

La dicitura multilingue non sostituisce la misura sull'italiano. Le versioni
GLiNER v0/v1 con licenza non commerciale non sono il candidato selezionato.
Il download usa safetensors, evitando la copia alternativa pickle dei pesi.
Preparazione e download sono operazioni esplicite di setup; l'analisi ordinaria
deve funzionare da directory locale senza scaricare componenti mancanti.

## Criteri tecnici

- Caricamento una volta per istanza, esecuzione locale su CPU e dipendenze NER
  opzionali per chi usa soltanto il core.
- NER disabilitato riconoscibile nei risultati. Modello esplicitamente richiesto
  ma inutilizzabile: errore controllato, senza continuare silenziosamente.
- Offset in punti di codice Unicode verificati contro il testo originale.
- Documenti lunghi divisi in finestre sovrapposte, rispettando sia i token dello
  splitter sia il limite effettivo di tokenizzazione del modello, comprese le
  etichette. Nessuna troncatura silenziosa; deduplicazione delle sovrapposizioni.
- Metadati di modello/configurazione inclusi nel manifesto di revisione.
- Nessuna classe generica "date" che oscuri le date degli eventi clinici.

La [documentazione GLiNER](https://github.com/urchade/GLiNER/blob/main/docs/usage.md)
specifica che max_len conta token dello splitter, non caratteri o subword, e che
gli input eccessivi possono essere troncati senza un indicatore nel risultato.
Questo comportamento richiede un controllo nell'adattatore Anonymizer.

Per il checkpoint provato: max_len 384 token dello splitter, limite 512 subword
comprendendo il prompt, max_width 12 token per entità. L'adattatore usa finestre
di massimo 256 token, ulteriormente ridotte se necessario per il limite subword,
e sovrapposizione di 11 token. L'assenza di troncatura dell'input non elimina il
limite del modello sulla lunghezza delle singole entità.

## Ambiente verificato

Python 3.12.13, GLiNER 0.2.30, PyTorch 2.7.1+cpu, Transformers 5.22.1,
huggingface-hub 2.4.0, SentencePiece 0.2.2 e protobuf 7.36.2. Protobuf è necessario
per la preparazione del tokenizer in questo ambiente.

Pesi safetensors: 1.155.830.112 byte, SHA-256
`2100142f31627531497850659dcb3821c99d5e71c08a8e01a98e4b11ef32a199`.
Backbone risolto alla revisione `a0484667b22365f84929a935b5e50a51f71f159d`.
Il pacchetto locale completo è in tools/local/models/gliner_multi-v2.1, escluso da Git.
Caricamento riuscito con local_files_only, modalità offline Hugging Face/Transformers
e cache separata inizialmente vuota. Lo smoke dell'adattatore Anonymizer verifica
anche conteggio del prompt, offset e produzione di Span PERSON/FACILITY.

Prima misura esplorativa su un testo breve sintetico, quattro thread CPU:
import complessivi 5,486 s, caricamento locale 4,766 s, prima inferenza 0,299 s,
mediana di cinque inferenze successive 0,271 s. RSS dopo inferenza circa 1.673 MiB;
picco Windows Working Set 2.743 MiB, includendo PyTorch. Sono tempi di uno smoke,
non prestazioni del percorso OCR/documento completo. La macchina locale ha circa
31,3 GB di RAM: il profilo di destinazione 4 vCPU/8 GB resta da validare.

## Misure da registrare

Rilevazione: precisione e richiamo con corrispondenza esatta e parziale, per tipo
e con denominatori espliciti. Output: copertura completa degli identificativi
annotati e mascherature che intersecano passaggi clinici da conservare. Prestazioni:
avvio/import, caricamento, inferenza a caldo e memoria del processo, con hardware
e numero di thread dichiarati. Le metriche sulle fixture sintetiche non
dimostrano efficacia su referti reali né raggiungimento delle soglie del pilota.

## Sviluppo e protezione dei punteggi clinici

Il corpus contiene 22 documenti di sviluppo e 22 di valutazione, inclusi due
negativi puramente clinici per gruppo. È un corpus di difficoltà deliberata:
persone e strutture sono inventate, prevalentemente fuori dal piccolo vocabolario
L2. Il confronto non rappresenta la distribuzione dei referti reali e non misura
la copertura generale di CF, email e telefoni, già verificati separatamente.

La prima prova development a soglia 0.5 ha coperto tutti i 32 identificativi
annotati, ma ha oscurato gli otto caratteri di "VAS 7/10", classificati L3 come
LOCATION. Si tratta di un falso positivo su un dato clinico; il risultato iniziale
è conservato in build/artifacts/ner-development-final.json.

Prima di eseguire evaluation è stata introdotta la protezione pain_scores_v1:
elimina soltanto le predizioni L3 interamente contenute in un punteggio strutturato
VAS/NRS da 0 a 10 su 10. Tiene conto di spazi, maiuscole e decimali, escludendo
date, denominatori differenti e valori non validi. Non elimina candidati che
si estendono fuori dalla misura e non modifica L0/L1/L2. I test verificano che
un'identità nota esplicitamente continui ad avere precedenza. La versione della
protezione è registrata nell'audit; gli audit precedenti restano identificabili
come privi della protezione.

Il corpus e i suoi intervalli annotati non sono stati modificati per questa
correzione. Le regressioni aggiuntive sono in src/tests/fixtures/ner_pain_scores.json.
Soglia 0.5, etichette person/location/healthcare facility e protezione pain_scores_v1
sono state congelate prima della valutazione separata. Nessuna
garanzia generale sulla conservazione del contenuto clinico deriva da questa
protezione circoscritta.

La dimostrazione OCR+NER sull'immagine OCT simulata recupera automaticamente il
nome "Beta Alfa" precedentemente mancato e mantiene i pixel esterni alle maschere.
Resta un falso positivo visibile sulla parola generica "Paziente": il campione
dimostra anche perché controllare le proposte sul documento originale.

## Risultati della valutazione separata

Una sola esecuzione di evaluation con la configurazione congelata. SHA-256 del
corpus: `f031d2ac393eca3f772dab65e8027722e708960d794618e232da70d5e3b5772f`.
Nessuna modifica di soglia, etichette o regole in base ai risultati evaluation.

| Entità | Annotate | Predette | Corrispondenze esatte | Richiamo esatto | Precisione esatta |
| --- | ---: | ---: | ---: | ---: | ---: |
| Persone | 22 | 23 | 22 | 100% | 95,7% |
| Luoghi | 5 | 5 | 4 | 80% | 80% |
| Strutture sanitarie | 6 | 6 | 5 | 83,3% | 83,3% |

Il matching parziale è una sovrapposizione dello stesso tipo con assegnazione
uno-a-uno: non equivale a protezione completa. Le sue corrispondenze sono 22/22,
5/5 e 6/6 rispettivamente. DOCTOR viene ricondotto a PERSON soltanto nelle
metriche di confronto, per non penalizzare artificialmente la baseline.

| Copertura degli intervalli testuali annotati | Baseline | Baseline + NER |
| --- | ---: | ---: |
| Identificativi interamente mascherati | 0/33 | 33/33 |
| Caratteri identificativi mascherati | 0/502 | 502/502 |
| Documenti con almeno un identificativo residuo | 20/22 | 0/22 |
| Segmenti clinici alterati | 0/22 | 1/22 |
| Caratteri clinici mascherati erroneamente | 0/790 | 7/790 |

Lo zero della baseline riflette la costruzione del corpus con nomi/luoghi/strutture
esterni al vocabolario sintetico, senza anagrafica nota. Non rappresenta un richiamo
nullo del progetto su tutte le categorie di dati personali. La copertura è
calcolata sugli intervalli testuali dopo merge; la verifica dei pixel è una prova
separata del percorso visuale. Numerosità ridotta, testi scritti e omogeneità del
dominio impediscono di generalizzare questi valori ai documenti reali.

Errore residuo: nel documento evaluation-00, uno dei due negativi puramente
clinici, "Romberg" viene classificato PERSON (confidenza circa 0,871) e coperto
per sette caratteri, pur indicando una prova clinica. Il risultato resta nel
rapporto; non è stato corretto sul campione di valutazione. Occorre rifiutare
manualmente questa maschera durante la revisione. La confidenza del modello
non è una probabilità di correttezza clinica.

Sul development, dopo la protezione dei punteggi, la copertura resta 32/32
identificativi e le false mascherature dei segmenti clinici scendono da 8 a 0
caratteri. Tale miglioramento è di sviluppo e resta separato dall'evaluation.

Prestazioni evaluation: mediana 0,235 s/documento, p95 2,154 s, totale circa
12,77 s di analisi testuale sui 22 documenti, inclusi due testi lunghi.
Inizializzazione dell'adattatore 9,409 s, comprendente import tardivi, verifica
degli artefatti e caricamento; picco processo circa 2.741,5 MiB. Questi tempi
non comprendono OCR, rendering, revisione umana ed export.

## Riproducibilità e decisione

Collaudo finale: 166 test passati senza skip con OCR e NER reali, Ruff pulito,
wheel ricostruita e verificata in un ambiente isolato. Sul campione OCT sintetico
nome, email e telefono vengono mascherati, con zero pixel cambiati fuori dalle
maschere; rimane il falso positivo della parola generica "Paziente".

Lo script tools/experiments/ner/prepare_model.py è stato eseguito dalla cache esistente
verso una nuova directory e il risultato verificato offline con cache vuota.
Il test Windows ha richiesto di risolvere i link della cache Hugging Face prima
di creare il collegamento temporaneo ai pesi; è presente fallback a copia.

Per riprodurre le misure, da checkout installato e con modello preparato:

```powershell
.\.venv\Scripts\python.exe tools\experiments\ner\evaluate.py --split development --model tools\local\models\gliner_multi-v2.1 --threads 4 --threshold 0.5 --output build\artifacts\nuovo-development.json
.\.venv\Scripts\python.exe tools\experiments\ner\evaluate.py --split evaluation --model tools\local\models\gliner_multi-v2.1 --threads 4 --threshold 0.5 --output build\artifacts\nuovo-evaluation.json
```

I file output devono essere nuovi. Report della sessione:
build/artifacts/ner-development-final.json (prima della protezione),
ner-development-afterguard.json, ner-evaluation-final.json e ner-verification.json.

Decisione: GLiNER è integrato come livello opzionale del prototipo assistito,
con limiti e stato espliciti. Non è approvato un flusso senza revisione o un
pilota clinico. Restano da valutare corpus reali autorizzati e separati, errori
su eponimi/altre misure, confronto con altri modelli e carico sull'hardware di
destinazione. L'interfaccia grafica deve rendere semplice rifiutare una maschera
errata e aggiungerne una mancante. Health web e caricamento nel ciclo di vita del
server appartengono al successivo blocco API.

## Backend CPU ONNX FP32 — 2026-11-03

Il successivo prototipo web dispone di health e caricamento del modello una sola
volta nel ciclo di vita dell'app. Aggiunto ora un backend opzionale ONNX per lo
stesso modello, con `NerConfig(runtime="onnx", cpu_threads=4)` oppure CLI
`--ner-runtime onnx --ner-threads 4`. Il default rimane Torch; non cambia il
protocollo dei candidati né vengono ridotti finestre, etichette o soglia.

`tools/experiments/ner/prepare_onnx.py` deriva offline un bundle FP32 da un bundle Torch
verificato. Registra provenienza, digest sorgente, versioni di conversione e hash
di grafo/config/tokenizer. Il caricatore verifica gli hash e rifiuta riferimenti
a tensori esterni prima di avviare ONNX Runtime. Provider CPU esplicito, quattro
thread intra-op, uno inter-op, esecuzione sequenziale; nessun fallback silenzioso
a un altro runtime. Runtime, versione, precisione e thread entrano nell'audit.

Confronto iniziale sui soli 22 documenti di sviluppo: FP32 Torch 12,152 s contro
ONNX 7,100 s, stesse metriche per classe e 32/32 identificativi annotati coperti,
zero caratteri clinici annotati oscurati. Verifica successiva degli intervalli:
33/33 candidati con offset e tipo identici in tutti i 22 documenti, stessi insiemi
di caratteri mascherati e delta massimo di confidenza 9,54e-7. In questa seconda
esecuzione il totale è 12,352 contro 6,115 s. Sono misure sul PC di sviluppo a
quattro thread, non un collaudo dell'hardware desktop di destinazione.

Working set nel processo sequenziale dopo inferenza: circa 1,93 GB con Torch e
2,29 GB con ONNX (GB decimali); non sono picchi indipendenti. Il picco di 5,43 GB
del processo che ha anche esportato il modello non rappresenta il requisito RAM
dell'app già installata. Il grafo FP32 occupa 1.157.113.249 byte; ONNX non elimina
attualmente la dipendenza GLiNER da componenti Torch.

Versioni provate: GLiNER 0.2.30, Torch 2.7.1+cpu, ONNX 1.23.2, ONNX Runtime
1.31.1, ONNX Script 0.7.2. Report locali numerici:
`build/artifacts/ner-onnx-development.json` e `ner-onnx-exact-development.json`.
La quantizzazione dinamica INT8 è stata scartata sullo sviluppo: 0/32
identificativi coperti, contro 32/32 con FP32. Nessuna modifica al corpus di
valutazione o ritocco del modello a partire da questa prova.

Verifica successiva sul campione evaluation immutato, una sola esecuzione con
ciascun runtime effettivamente configurato: stessi 34 candidati (23 PERSON,
6 FACILITY, 5 LOCATION), offset e tipi identici in 22/22 documenti, stesso insieme
di caratteri mascherati. Delta massimo di confidenza 3,93e-6. Entrambi coprono
33/33 identificativi e conservano il falso positivo clinico noto: un segmento,
sette caratteri. Nessuna taratura in risposta al risultato. In questa prova
l'inferenza richiede 15,813 s con Torch e 12,195 s con ONNX; caricamento 11,590 e
10,198 s. Il beneficio varia con testi e condizioni di esecuzione: non viene
generalizzato il dimezzamento osservato sullo sviluppo. Report locale
`build/artifacts/ner-onnx-heldout-evaluation.json`.
