"""!
@file ner.py
@brief Rilevatore NER di livello 3 basato su un modello GLiNER locale.

Verifica l'integrità degli artefatti del modello prima di caricarlo, esegue l'inferenza su
finestre di parole compatibili con il budget di token e scarta le predizioni che cadono in
contesti clinici protetti. I risultati sono candidati che richiedono revisione.
"""

import hashlib
import json
import math
import re
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path
from threading import Lock
from typing import Protocol

from anonymizer.detect.clinical import protected_clinical_spans
from anonymizer.model import Kind, Span, Validation
from anonymizer.ner_model import LABELS, NerAudit, NerConfig, NerError

## Corrispondenza tra le etichette del modello e i tipi di entità.
_KINDS = dict(zip(LABELS, (Kind.PERSON, Kind.LOCATION, Kind.FACILITY), strict=True))
## Versione delle protezioni cliniche, registrata nell'audit NER.
CLINICAL_GUARD_VERSION = "clinical_context_v6"
## Punteggi di dolore VAS/NRS su 10, che non devono diventare entità.
_PAIN_SCORE = re.compile(
    r"\b(?:VAS|NRS)\s*[:=]?\s*(?:10(?:[.,]0+)?|[0-9](?:[.,][0-9]+)?)"
    r"\s*/\s*10\b(?![.,][0-9]|\s*/|\s*-[0-9])",
    re.IGNORECASE,
)
## Spaziatura tra parole che ammette al più un a capo.
_CONTEXT_GAP = r"(?:[ \t]+|[ \t]*(?:\r\n|\r|\n)[ \t]*)"
## "placenta" come organo, preceduta da una preposizione articolata.
_ANATOMICAL_PLACENTA = re.compile(
    r"\b(?i:nella|della|dalla|alla)" + _CONTEXT_GAP + r"(?P<organ>placenta)(?![\w\u0300-\u036f])"
)
## Termini che confermano il contesto ostetrico di "placenta".
_PLACENTA_CONTEXT = re.compile(
    r"\b(?:gravidanza|gestazione|ormone|ormoni|prodotto|prodotta|produce|produzione|"
    r"secreto|secrezione|fetale|feto|placentare)\b",
    re.IGNORECASE,
)
## Sostantivi di ruolo generico: medico (curante), specialista, paziente.
_ROLE_NOUN = r"(?:medico(?:" + _CONTEXT_GAP + r"curante)?|specialista|paziente)"
## Congiunzioni tra ruoli generici: "/", "o", "o al/allo/alla".
_ROLE_LINK = (
    r"(?:[ \t]*/[ \t]*|"
    + _CONTEXT_GAP
    + r"o"
    + _CONTEXT_GAP
    + r"(?:(?i:al|allo|alla)"
    + _CONTEXT_GAP
    + r")?)"
)
## Ruoli generici preceduti da articolo, preposizione o possessivo, non nomi propri.
_GENERIC_ROLE = re.compile(
    r"\b(?i:del|dal|al|il|un|uno|lo|dello|allo|la|una|della|dalla|alla|le|i|gli|"
    r"dei|degli|ai|agli|col|proprio|propria|suo|sua)"
    + _CONTEXT_GAP
    + r"(?P<role>"
    + _ROLE_NOUN
    + r"(?:"
    + _ROLE_LINK
    + _ROLE_NOUN
    + r"){0,2}"
    + r"(?:"
    + _CONTEXT_GAP
    + r"di"
    + _CONTEXT_GAP
    + r"riferimento)?)(?![\w\u0300-\u036f])"
)


def _clinical_protected(text):
    """!
    @brief Calcola gli intervalli in cui le predizioni NER vanno scartate.

    Comprende punteggi di dolore, "placenta" in contesto ostetrico, ruoli generici su al più
    due righe e gli intervalli clinici protetti condivisi.
    @param text Testo della pagina.
    @return Tuple (inizio, fine, tipo); tipo None protegge da qualsiasi tipo di entità.
    """
    protected = [(match.start(), match.end(), None) for match in _PAIN_SCORE.finditer(text)]
    for match in _ANATOMICAL_PLACENTA.finditer(text):
        # The anatomical use needs clinical evidence in the same nearby sentence.
        begin = max(0, match.start() - 220)
        for separator in (".", "!", "?", "\n", "\r"):
            begin = max(begin, text.rfind(separator, begin, match.start()) + 1)
        if _PLACENTA_CONTEXT.search(text, begin, match.start()):
            protected.append((*match.span("organ"), Kind.LOCATION))
    for match in _GENERIC_ROLE.finditer(text):
        if len(re.findall(r"\r\n|\r|\n", match.group())) <= 1:
            protected.append((*match.span("role"), Kind.PERSON))
    return [*protected, *protected_clinical_spans(text)]


class NerDetector(Protocol):
    """!
    @brief Interfaccia di un rilevatore NER usato dalla pipeline.
    """

    ## Metadati di audit del modello e della configurazione.
    audit: NerAudit

    def detect(self, text: str, page_id: str) -> list[Span]:
        """!
        @brief Rileva entità nominate nel testo di una pagina.
        @param text Testo della pagina.
        @param page_id Identificativo della pagina.
        @return Span candidati.
        """
        ...


class NerBackend(Protocol):
    """!
    @brief Interfaccia del motore di inferenza usato da GLiNERDetector.
    """

    ## Identificativo del modello.
    model_id: str
    ## Revisione del modello.
    revision: str
    ## SHA-256 del registro degli artefatti.
    artifact_sha256: str
    ## Versione della libreria di inferenza.
    library_version: str
    ## Numero massimo di parole per input.
    word_limit: int
    ## Numero massimo di token subword per input.
    subword_limit: int
    ## Ampiezza massima di un'entità in parole.
    max_width: int

    def split(self, text: str) -> list[tuple[str, int, int]]:
        """!
        @brief Suddivide il testo in parole con i relativi offset.
        @param text Testo da suddividere.
        @return Tuple (parola, inizio, fine).
        """
        ...

    def token_count(self, words: Sequence[str]) -> int:
        """!
        @brief Conta i token subword dell'input costruito per le parole date.
        @param words Parole della finestra.
        @return Numero di token.
        """
        ...

    def predict(self, text: str, threshold: float) -> list[dict]:
        """!
        @brief Predice le entità nel testo.
        @param text Testo della finestra.
        @param threshold Confidenza minima.
        @return Dizionari con chiavi start, end, label, score e text.
        """
        ...


def _sha256(path: Path) -> str:
    """!
    @brief Calcola lo SHA-256 di un file leggendolo a blocchi da 1 MiB.
    @param path File da leggere.
    @return Digest esadecimale.
    """
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def verify_onnx_graph(path: Path) -> None:
    """!
    @brief Rifiuta i tensori esterni prima che un runtime possa seguirne i riferimenti a file.

    Il grafo viene caricato senza dati esterni e visitato ricorsivamente.
    @param path Percorso del file ONNX.
    @throws NerError ner_onnx_external_data_unsupported se un tensore usa dati esterni,
            ner_invalid_onnx_graph se il grafo non è leggibile.
    """
    try:
        import onnx

        model = onnx.load(str(path), load_external_data=False)

        def inspect(message):
            """!
            @brief Visita un messaggio protobuf cercando tensori con dati esterni.
            @param message Messaggio da ispezionare.
            @throws NerError Se trova un tensore con dati esterni.
            """
            if isinstance(message, onnx.TensorProto):
                if message.external_data or message.data_location == onnx.TensorProto.EXTERNAL:
                    raise NerError("ner_onnx_external_data_unsupported")
                # Do not materialize large raw_data bytes via ListFields.
                return
            for field, value in message.ListFields():
                if field.message_type is not None:
                    if field.is_repeated:
                        for item in value:
                            inspect(item)
                    else:
                        inspect(value)

        inspect(model)
    except NerError:
        raise
    except Exception:
        raise NerError("ner_invalid_onnx_graph") from None


def verify_model_artifacts(directory: Path, runtime: str = "torch") -> tuple[dict, str]:
    """!
    @brief Verifica il registro anonymizer_model.json e gli hash degli artefatti locali.

    Controlla runtime e precisione dichiarati, la presenza di configurazione, pesi e tokenizer,
    che ogni file stia direttamente nella directory e che il suo SHA-256 corrisponda. Per ONNX
    verifica anche il grafo.
    @param directory Directory del modello.
    @param runtime "torch" oppure "onnx".
    @return Coppia (registro, SHA-256 del registro serializzato in forma canonica).
    @throws NerError Con un codice specifico per ogni verifica fallita, oppure
            ner_invalid_local_model per errori di lettura o di formato.
    """
    try:
        if runtime not in ("torch", "onnx"):
            raise NerError("ner_invalid_runtime")
        directory = directory.resolve(strict=True)
        ledger = json.loads((directory / "anonymizer_model.json").read_text("utf-8"))
        if not isinstance(ledger["model_id"], str) or not ledger["model_id"]:
            raise NerError("ner_invalid_artifact_ledger")
        if not isinstance(ledger["revision"], str) or not ledger["revision"]:
            raise NerError("ner_invalid_artifact_ledger")
        files = ledger["files"]
        weight = "model.onnx" if runtime == "onnx" else "model.safetensors"
        if ledger.get("runtime", "torch") != runtime or (
            runtime == "onnx" and ledger.get("precision") != "fp32"
        ):
            raise NerError("ner_artifact_runtime_mismatch")
        if (
            not isinstance(files, dict)
            or not {"gliner_config.json", weight, "tokenizer_config.json"} <= files.keys()
        ):
            raise NerError("ner_incomplete_local_artifacts")
        if not any(
            name in files for name in ("tokenizer.json", "spm.model", "sentencepiece.bpe.model")
        ):
            raise NerError("ner_missing_local_tokenizer")
        for name, expected in files.items():
            path = directory / name
            if (
                not isinstance(name, str)
                or path.resolve().parent != directory
                or len(expected) != 64
            ):
                raise NerError("ner_invalid_artifact_ledger")
            if _sha256(path) != expected:
                raise NerError("ner_artifact_hash_mismatch")
        if runtime == "onnx":
            verify_onnx_graph(directory / weight)
        raw = json.dumps(ledger, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return ledger, hashlib.sha256(raw.encode()).hexdigest()
    except NerError:
        raise
    except (OSError, ValueError, TypeError, KeyError):
        raise NerError("ner_invalid_local_model") from None


class LocalGLiNERBackend:
    """!
    @brief Backend GLiNER che carica su CPU solo artefatti locali verificati.
    """

    def __init__(self, config: NerConfig):
        """!
        @brief Verifica gli artefatti, carica il modello (torch o ONNX) e ne ricava i limiti.
        @param config Configurazione NER.
        @throws NerError Se gli artefatti non sono validi, l'architettura non è supportata o il
                caricamento fallisce.
        """
        ledger, digest = verify_model_artifacts(config.model_path, config.runtime)
        try:
            from gliner import GLiNER

            options = {}
            self.runtime_version = self.provider = None
            self.precision = "fp32"
            if config.runtime == "onnx":
                import onnxruntime as ort

                session = ort.SessionOptions()
                session.intra_op_num_threads = config.cpu_threads
                session.inter_op_num_threads = 1
                session.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
                session.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                options = {
                    "runtime": "onnxruntime",
                    "runtime_model_file": "model.onnx",
                    "runtime_options": {
                        "session_options": session,
                        "providers": ["CPUExecutionProvider"],
                    },
                }
                self.runtime_version = version("onnxruntime")
                self.provider = "CPUExecutionProvider"
            else:
                import torch

                torch.set_num_threads(config.cpu_threads)
                self.runtime_version = version("torch")
            self.model = GLiNER.from_pretrained(
                str(config.model_path.resolve()),
                local_files_only=True,
                token=False,
                load_tokenizer=True,
                map_location="cpu",
                **options,
            )
            if config.runtime == "torch":
                self.model.eval()
            self.processor = self.model.data_processor
            self.tokenizer = self.processor.transformer_tokenizer
            self.word_limit = self.model.config.max_len
            self.max_width = self.model.config.max_width
            encoder_config = self.model.config.encoder_config
            encoder_limit = getattr(encoder_config, "max_position_embeddings", None)
            limits = [
                value
                for value in (self.tokenizer.model_max_length, encoder_limit)
                if type(value) is int and 0 < value < 1_000_000
            ]
            if not limits or getattr(self.model.config, "labels_encoder", None):
                raise NerError("ner_unsupported_model_architecture")
            self.subword_limit = min(limits)
            self.model_id, self.revision = ledger["model_id"], ledger["revision"]
            self.artifact_sha256, self.library_version = digest, version("gliner")
        except NerError:
            raise
        except Exception:
            raise NerError("ner_model_load_failed") from None

    def split(self, text: str) -> list[tuple[str, int, int]]:
        """!
        @brief Suddivide il testo con lo splitter di parole del modello.
        @param text Testo da suddividere.
        @return Tuple (parola, inizio, fine).
        """
        return list(self.processor.words_splitter(text))

    def token_count(self, words: Sequence[str]) -> int:
        """!
        @brief Conta i token subword dell'input che il modello costruisce, etichette comprese.
        @param words Parole della finestra.
        @return Numero di token.
        """
        prepared, _ = self.processor.prepare_inputs([list(words)], list(LABELS))
        encoded = self.tokenizer(
            prepared,
            is_split_into_words=True,
            truncation=False,
            padding=False,
            return_attention_mask=False,
        )
        return len(encoded["input_ids"][0])

    def predict(self, text: str, threshold: float) -> list[dict]:
        """!
        @brief Predice le entità con le etichette configurate, ammettendo entità annidate.
        @param text Testo della finestra.
        @param threshold Confidenza minima.
        @return Dizionari con chiavi start, end, label, score e text.
        """
        return self.model.predict_entities(text, list(LABELS), threshold=threshold, flat_ner=False)


class GLiNERDetector:
    """!
    @brief Rilevatore NER che applica GLiNER su finestre di parole sovrapposte.

    L'accesso al modello è serializzato da un lock.
    """

    def __init__(self, config: NerConfig, *, backend: NerBackend | None = None):
        """!
        @brief Valida i limiti del backend e della finestra e prepara l'audit.
        @param config Configurazione NER.
        @param backend Backend alternativo; se None si usa LocalGLiNERBackend.
        @throws NerError Se i limiti del modello non sono validi o la sovrapposizione non è
                compatibile con la finestra.
        """
        self.config = config
        self.backend = backend if backend is not None else LocalGLiNERBackend(config)
        self._lock = Lock()
        word_limit, width = self.backend.word_limit, self.backend.max_width
        if any(
            type(value) is not int or value <= 0
            for value in (word_limit, width, self.backend.subword_limit)
        ):
            raise NerError("ner_invalid_model_limits")
        overlap = width - 1 if config.overlap_words is None else config.overlap_words
        window = min(config.window_words, word_limit)
        if overlap < width - 1 or overlap >= window:
            raise NerError("ner_overlap_incompatible_with_window")
        self.audit = NerAudit(
            "ready",
            "configured_local_model",
            "gliner",
            self.backend.model_id,
            self.backend.revision,
            self.backend.artifact_sha256,
            self.backend.library_version,
            config.threshold,
            LABELS,
            word_limit,
            self.backend.subword_limit,
            width,
            window,
            overlap,
            clinical_guard_version=CLINICAL_GUARD_VERSION,
            runtime=config.runtime,
            runtime_version=getattr(self.backend, "runtime_version", None),
            provider=getattr(self.backend, "provider", None),
            precision=getattr(self.backend, "precision", None),
            cpu_threads=config.cpu_threads,
        )

    def detect(self, text: str, page_id: str) -> list[Span]:
        """!
        @brief Rileva entità nel testo di una pagina.
        @param text Testo della pagina.
        @param page_id Identificativo della pagina.
        @return Span di livello 3 da revisionare, ordinati per posizione; vuoto se il testo è vuoto.
        @throws NerError Se il testo supera il limite di caratteri o l'inferenza fallisce.
        """
        if len(text) > self.config.max_characters:
            raise NerError("ner_input_character_limit")
        if not text.strip():
            return []
        try:
            with self._lock:
                return self._detect(text, page_id)
        except NerError:
            raise
        except Exception:
            raise NerError("ner_inference_failed") from None

    def _detect(self, text: str, page_id: str) -> list[Span]:
        """!
        @brief Esegue l'inferenza a finestre e filtra le predizioni.

        Verifica che lo splitter copra il testo con offset coerenti, sceglie con ricerca binaria la
        finestra più lunga entro il budget di subword e controlla offset, testo, etichetta e
        punteggio di ogni predizione. Scarta le predizioni contenute in intervalli protetti e, per
        ogni intervallo, conserva quella con punteggio più alto.
        @param text Testo della pagina.
        @param page_id Identificativo della pagina.
        @return Span ordinati per inizio, fine e tipo.
        @throws NerError Se splitter, conteggio dei token o predizioni sono incoerenti, o se si
                supera il numero massimo di finestre.
        """
        protected = _clinical_protected(text)
        words = self.backend.split(text)
        previous = 0
        for word, start, end in words:
            if (
                type(start) is not int
                or type(end) is not int
                or not previous <= start < end <= len(text)
            ):
                raise NerError("ner_invalid_splitter_offsets")
            if text[start:end] != word or text[previous:start].strip():
                raise NerError("ner_invalid_splitter_coverage")
            previous = end
        if not words or text[previous:].strip():
            raise NerError("ner_invalid_splitter_coverage")
        output = {}
        first, windows = 0, 0
        while first < len(words):
            windows += 1
            if windows > self.config.max_windows:
                raise NerError("ner_window_count_limit")
            upper = min(len(words), first + self.audit.window_words)
            low, high = first + 1, upper
            best = first
            while low <= high:
                middle = (low + high) // 2
                cost = self.backend.token_count([word[0] for word in words[first:middle]])
                if type(cost) is not int or cost <= 0:
                    raise NerError("ner_invalid_token_count")
                if cost <= self.audit.subword_limit:
                    best, low = middle, middle + 1
                else:
                    high = middle - 1
            if best == first:
                raise NerError("ner_single_word_exceeds_token_budget")
            start, end = words[first][1], words[best - 1][2]
            window = text[start:end]
            # Re-splitting must agree with the actual inference API at a new boundary.
            actual = self.backend.split(window)
            if [word[0] for word in actual] != [word[0] for word in words[first:best]]:
                raise NerError("ner_window_splitter_drift")
            for entity in self.backend.predict(window, self.config.threshold):
                left, right, label, score = (
                    entity[key] for key in ("start", "end", "label", "score")
                )
                if (
                    type(left) is not int
                    or type(right) is not int
                    or not 0 <= left < right <= len(window)
                ):
                    raise NerError("ner_invalid_prediction_offsets")
                if (
                    window[left:right] != entity["text"]
                    or text[start + left : start + right] != entity["text"]
                ):
                    raise NerError("ner_prediction_text_mismatch")
                if (
                    label not in _KINDS
                    or type(score) not in (int, float)
                    or not math.isfinite(score)
                    or not 0 <= score <= 1
                ):
                    raise NerError("ner_invalid_prediction_label_or_score")
                if score < self.config.threshold:
                    continue
                key = (start + left, start + right, _KINDS[label])
                # Only contained L3 guesses are rejected; other detector levels remain independent.
                if any(
                    begin <= key[0] and key[1] <= finish and (kind is None or kind == key[2])
                    for begin, finish, kind in protected
                ):
                    continue
                candidate = Span(
                    page_id,
                    key[0],
                    key[1],
                    key[2],
                    3,
                    "ner:gliner",
                    confidence=score,
                    validation=Validation("unchecked", "model_prediction_requires_review"),
                )
                if key not in output or output[key].confidence < score:
                    output[key] = candidate
            if best == len(words):
                break
            if best - first <= self.audit.overlap_words:
                raise NerError("ner_window_cannot_preserve_overlap")
            first = best - self.audit.overlap_words
        return sorted(output.values(), key=lambda span: (span.start, span.end, span.kind))
