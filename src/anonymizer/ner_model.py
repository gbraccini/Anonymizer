"""!
@file ner_model.py
@brief Configurazione e dati di audit del riconoscimento di entità (NER).

L'audit registra modello, runtime e parametri effettivamente usati, così che ogni
revisione documenti con quale configurazione sono stati prodotti i candidati.
"""

import math
from dataclasses import dataclass
from pathlib import Path

## Etichette richieste al modello NER, nell'ordine registrato nell'audit.
LABELS = ("person", "location", "healthcare facility")


class NerError(ValueError):
    """!
    @brief Errore di configurazione o di audit NER identificato da un codice simbolico.
    """

    def __init__(self, code: str):
        """!
        @brief Crea l'errore usando il codice anche come messaggio.
        @param code Codice simbolico dell'errore.
        """
        ## Codice dell'errore.
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class NerConfig:
    """!
    @brief Configurazione dell'esecuzione del modello NER.
    """

    ## Cartella del modello locale.
    model_path: Path
    ## Soglia di confidenza, strettamente compresa tra 0 e 1.
    threshold: float = 0.5
    ## Parole per finestra di analisi.
    window_words: int = 256
    ## Parole di sovrapposizione tra finestre; None per il valore predefinito.
    overlap_words: int | None = None
    ## Numero massimo di caratteri analizzabili.
    max_characters: int = 1_000_000
    ## Numero massimo di finestre.
    max_windows: int = 4096
    ## Motore di esecuzione: `torch` oppure `onnx`.
    runtime: str = "torch"
    ## Thread di calcolo, da 1 a 32.
    cpu_threads: int = 4

    def __post_init__(self) -> None:
        """!
        @brief Verifica runtime, thread, soglia e limiti delle finestre.
        @throws NerError Con un codice che identifica il parametro non valido.
        """
        if self.runtime not in ("torch", "onnx"):
            raise NerError("ner_invalid_runtime")
        if type(self.cpu_threads) is not int or not 1 <= self.cpu_threads <= 32:
            raise NerError("ner_invalid_cpu_threads")
        if (
            type(self.threshold) not in (int, float)
            or not math.isfinite(self.threshold)
            or not 0 < self.threshold < 1
        ):
            raise NerError("ner_invalid_threshold")
        for value in (self.window_words, self.max_characters, self.max_windows):
            if type(value) is not int or value <= 0:
                raise NerError("ner_invalid_window_budget")
        if self.overlap_words is not None and (
            type(self.overlap_words) is not int or self.overlap_words < 0
        ):
            raise NerError("ner_invalid_overlap")


@dataclass(frozen=True)
class NerAudit:
    """!
    @brief Registrazione di come è stato eseguito (o perché non è stato eseguito) il NER.

    Con stato `ready` tutti i dati di identificazione del modello e del budget di
    finestre devono essere presenti e coerenti.
    """

    ## `disabled` oppure `ready`.
    status: str = "disabled"
    ## Motivo dello stato.
    reason: str = "not_configured"
    ## Libreria NER usata; con stato `ready` deve essere `gliner`.
    backend: str | None = None
    ## Identificatore del modello.
    model_id: str | None = None
    ## Revisione del modello.
    revision: str | None = None
    ## Impronta SHA-256 esadecimale del registro degli artefatti.
    artifact_sha256: str | None = None
    ## Versione della libreria NER.
    library_version: str | None = None
    ## Soglia di confidenza usata.
    threshold: float | None = None
    ## Etichette richieste; con stato `ready` devono coincidere con ::LABELS.
    labels: tuple[str, ...] = ()
    ## Numero massimo di parole per input del modello.
    word_limit: int | None = None
    ## Numero massimo di token subword per input del modello.
    subword_limit: int | None = None
    ## Lunghezza massima, in parole, di un'entità.
    max_width: int | None = None
    ## Parole per finestra.
    window_words: int | None = None
    ## Parole di sovrapposizione: almeno `max_width - 1` e minori della finestra, così che nessuna
    ## entità venga spezzata tra finestre.
    overlap_words: int | None = None
    ## Versione del filtro sui contesti clinici.
    clinical_guard_version: str = "none"
    ## Motore di esecuzione: `torch` oppure `onnx`.
    runtime: str = "torch"
    ## Versione del motore, obbligatoria per ONNX pronto.
    runtime_version: str | None = None
    ## Provider di esecuzione ONNX; deve essere quello CPU.
    provider: str | None = None
    ## Precisione numerica ONNX; deve essere `fp32`.
    precision: str | None = None
    ## Thread di calcolo usati, da 1 a 32.
    cpu_threads: int | None = None

    def __post_init__(self) -> None:
        """!
        @brief Verifica la completezza e la coerenza dei dati di audit.
        @throws NerError Con un codice che identifica il primo dato mancante o non valido.
        """
        if self.runtime not in ("torch", "onnx"):
            raise NerError("ner_invalid_runtime")
        if self.cpu_threads is not None and (
            type(self.cpu_threads) is not int or not 1 <= self.cpu_threads <= 32
        ):
            raise NerError("ner_invalid_cpu_threads")
        if (
            self.status == "ready"
            and self.runtime == "onnx"
            and (
                not isinstance(self.runtime_version, str)
                or not self.runtime_version
                or self.provider != "CPUExecutionProvider"
                or self.precision != "fp32"
                or self.cpu_threads is None
            )
        ):
            raise NerError("ner_incomplete_runtime_audit")
        if self.clinical_guard_version not in (
            "none",
            "pain_scores_v1",
            "clinical_context_v2",
            "clinical_context_v3",
            "clinical_context_v4",
            "clinical_context_v5",
            "clinical_context_v6",
        ):
            raise NerError("ner_unknown_clinical_guard")
        if self.status not in ("disabled", "ready"):
            raise NerError("ner_invalid_audit_status")
        if self.status == "ready":
            if self.backend != "gliner" or self.labels != LABELS:
                raise NerError("ner_invalid_audit_labels")
            if any(
                not isinstance(value, str) or not value
                for value in (
                    self.model_id,
                    self.revision,
                    self.artifact_sha256,
                    self.library_version,
                )
            ):
                raise NerError("ner_incomplete_audit")
            if (
                type(self.threshold) not in (int, float)
                or not math.isfinite(self.threshold)
                or not 0 < self.threshold < 1
            ):
                raise NerError("ner_invalid_threshold")
            if len(self.artifact_sha256) != 64 or any(
                char not in "0123456789abcdef" for char in self.artifact_sha256
            ):
                raise NerError("ner_invalid_audit_artifact_hash")
            if (
                any(
                    type(value) is not int or value <= 0
                    for value in (
                        self.word_limit,
                        self.subword_limit,
                        self.max_width,
                        self.window_words,
                    )
                )
                or type(self.overlap_words) is not int
                or self.overlap_words < self.max_width - 1
                or self.overlap_words >= self.window_words
                or self.window_words > self.word_limit
            ):
                raise NerError("ner_invalid_audit_budget")
