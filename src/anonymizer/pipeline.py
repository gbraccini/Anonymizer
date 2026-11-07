"""!
@file pipeline.py
@brief Pipeline completa di analisi documentale: ingest, estrazione, NER, proposte di redazione.

Ispeziona gli input, estrae il testo di ogni pagina (testo nativo PDF e/o OCR), esegue
l'analisi testuale e costruisce il manifesto di revisione con le maschere proposte e gli
avvisi. Il NER può essere sovrapposto all'estrazione su un thread dedicato.
"""

import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from queue import Empty, Full, Queue
from threading import Event
from time import perf_counter

from anonymizer.detect.ner import NerDetector
from anonymizer.extraction import render_pdf_for_analysis
from anonymizer.ingest import InputFile, inspect_inputs, render_page
from anonymizer.model import Warning
from anonymizer.ocr import DEFAULT_OCR_CONFIG, OCRConfig, recognize
from anonymizer.patient import KnownIdentity
from anonymizer.performance import ExecutionProfile, configure_ner_worker
from anonymizer.redact import propose_redactions
from anonymizer.text_pipeline import TextAnalysis, analyze_text, detect_page_ner
from anonymizer.visual_model import (
    DEFAULT_LIMITS,
    DocumentError,
    Limits,
    ReviewManifest,
    ReviewWarning,
    VisualPage,
    validate_manifest,
)


@dataclass(frozen=True)
class DocumentAnalysis:
    """!
    @brief Esito dell'analisi di un insieme di documenti.
    """

    ## Manifesto di revisione con sorgenti, pagine, maschere proposte e avvisi.
    manifest: ReviewManifest
    ## Analisi testuale completa da cui derivano le proposte.
    text_analysis: TextAnalysis
    ## Durate delle fasi in secondi, per diagnostica delle prestazioni.
    timings: dict[str, float] = field(default_factory=dict)


def analyze_documents(
    inputs: tuple[InputFile, ...],
    *,
    limits: Limits = DEFAULT_LIMITS,
    dpi: int = 300,
    ocr_config: OCRConfig = DEFAULT_OCR_CONFIG,
    identities: tuple[KnownIdentity, ...] = (),
    ner: NerDetector | None = None,
    ner_disabled_reason: str = "not_configured",
    pdf_hybrid: bool = False,
    execution_profile: ExecutionProfile | None = None,
    deadline_seconds: float | None = None,
) -> DocumentAnalysis:
    """!
    @brief Analizza i documenti in input e produce il manifesto di revisione.

    Con un profilo di esecuzione che abilita la sovrapposizione e un NER configurato, le
    pagine estratte passano tramite una coda di capacità uno a un thread NER, così OCR e
    NER procedono in parallelo; altrimenti il NER viene eseguito pagina per pagina. Ogni
    pagina riceve gli avvisi di revisione standard oltre a quelli specifici.
    @param inputs File da analizzare.
    @param limits Limiti di risorse per l'ispezione.
    @param dpi Risoluzione di rendering.
    @param ocr_config Configurazione OCR; i thread vengono sovrascritti dal profilo.
    @param identities Identità note da cercare.
    @param ner Rilevatore NER, o None per disattivarlo.
    @param ner_disabled_reason Motivo registrato quando il NER è assente.
    @param pdf_hybrid Abilita l'estrazione ibrida testo nativo più OCR dei tracciati residui.
    @param execution_profile Profilo di thread e sovrapposizione, opzionale.
    @param deadline_seconds Tempo massimo di analisi in secondi, opzionale.
    @return Manifesto validato, analisi testuale e tempi delle fasi.
    @throws DocumentError Se le opzioni non sono valide, il profilo non coincide con i thread
        del NER, la scadenza viene superata o il worker NER si arresta.
    """
    if type(pdf_hybrid) is not bool:
        raise DocumentError("invalid_pdf_hybrid_option")
    if deadline_seconds is not None and (
        deadline_seconds <= 0 or not math.isfinite(deadline_seconds)
    ):
        raise DocumentError("invalid_analysis_deadline")
    wall_started = perf_counter()
    if execution_profile is not None:
        actual_threads = getattr(getattr(ner, "config", None), "cpu_threads", None)
        if actual_threads is not None and actual_threads != execution_profile.ner_threads:
            raise DocumentError("execution_profile_ner_threads_mismatch")
        ocr_config = replace(ocr_config, cpu_threads=execution_profile.ocr_threads)
    timings = dict.fromkeys(("ingest", "render", "ocr", "ner", "text_other", "proposals"), 0.0)
    started = perf_counter()
    sources, page_inputs = inspect_inputs(inputs, limits, dpi)
    timings["ingest"] = perf_counter() - started

    def extract(item):
        """!
        @brief Estrae il testo di una pagina da testo nativo PDF, OCR o entrambi.

        In modalità residua il testo OCR dei tracciati viene accodato a quello nativo con
        offset traslati e un avviso bloccante che richiede revisione.
        @param item Pagina da estrarre.
        @return Risultato testuale della pagina.
        """
        started = perf_counter()
        residual = False
        if item.source.extension.lower() == ".pdf":
            rendered = render_pdf_for_analysis(item, hybrid=pdf_hybrid)
            image, native, residual = rendered.image, rendered.native, rendered.residual
        else:
            image, native = render_page(item), None
        timings["render"] += perf_counter() - started
        try:
            started = perf_counter()
            extracted = native
            if native is None or residual:
                ocr_page = recognize(image, item, ocr_config)
                timings["ocr"] += perf_counter() - started
                if native is None:
                    extracted = ocr_page
                else:
                    offset = len(native.text) + 1
                    extracted = replace(
                        native,
                        text=native.text + "\n" + ocr_page.text,
                        regions=(
                            *native.regions,
                            *(
                                replace(
                                    region, start=region.start + offset, end=region.end + offset
                                )
                                for region in ocr_page.regions
                            ),
                        ),
                        extraction_mode="native_pdf+residual_ocr",
                        warnings=(
                            *native.warnings,
                            *(
                                warning
                                for warning in ocr_page.warnings
                                if warning.code != "no_readable_text_manual_review"
                            ),
                            Warning(
                                "residual_graphics_ocr_requires_review", item.page_id, blocking=True
                            ),
                        ),
                    )
            return extracted
        finally:
            image.close()

    pages, cached_ner = [], {}

    def checkpoint():
        """!
        @brief Interrompe l'analisi se la scadenza configurata è stata superata.
        @throws DocumentError Con codice analysis_deadline_exceeded.
        """
        if deadline_seconds is not None and perf_counter() - wall_started >= deadline_seconds:
            raise DocumentError("analysis_deadline_exceeded")

    def infer(page):
        """!
        @brief Esegue il NER su una pagina e ne memorizza i candidati.
        @param page Pagina estratta.
        """
        checkpoint()
        started = perf_counter()
        cached_ner[page.page_id] = detect_page_ner(page, ner)
        timings["ner"] += perf_counter() - started
        checkpoint()

    overlap = ner is not None and execution_profile is not None and execution_profile.overlap
    timings["overlap_enabled"] = float(overlap)
    if overlap:
        queue, stop, sentinel = Queue(maxsize=1), Event(), object()

        def consume():
            """!
            @brief Ciclo del worker NER: consuma le pagine dalla coda fino al sentinella.

            Qualsiasi eccezione imposta l'evento di stop prima di propagarsi.
            """
            try:
                configure_ner_worker(ner)
                while not stop.is_set():
                    checkpoint()
                    try:
                        page = queue.get(timeout=0.05)
                    except Empty:
                        continue
                    if page is sentinel:
                        return
                    infer(page)
            except BaseException:
                stop.set()
                raise

        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="anonymizer-ner")
        future = executor.submit(consume)

        def enqueue(page):
            """!
            @brief Accoda una pagina per il worker NER controllando scadenza e stato del worker.
            @param page Pagina o sentinella da accodare.
            @throws DocumentError Se il worker si è arrestato o la scadenza è superata.
            """
            while True:
                checkpoint()
                if future.done():
                    future.result()
                    raise DocumentError("analysis_worker_stopped")
                try:
                    queue.put(page, timeout=0.05)
                    return
                except Full:
                    continue

        try:
            for item in page_inputs:
                checkpoint()
                if future.done():
                    future.result()
                page = extract(item)
                pages.append(page)
                enqueue(page)
            enqueue(sentinel)
            future.result()
        finally:
            stop.set()
            # Running model calls cannot be forcibly cancelled; finish before releasing resources.
            executor.shutdown(wait=True, cancel_futures=True)
    else:
        if ner is not None:
            configure_ner_worker(ner)
        for item in page_inputs:
            checkpoint()
            page = extract(item)
            pages.append(page)
            if ner is not None:
                infer(page)
    checkpoint()
    started = perf_counter()
    analysis = analyze_text(
        pages,
        identities,
        ner=ner,
        ner_disabled_reason=ner_disabled_reason,
        ner_candidates=cached_ner if ner is not None else None,
    )
    timings["text_other"] = perf_counter() - started
    started = perf_counter()
    visual_pages = []
    for item, page in zip(page_inputs, pages, strict=True):
        masks, warnings, required = propose_redactions(
            page, list(analysis.merged_spans), item.geometry
        )
        review_warnings = tuple(
            dict.fromkeys(
                (
                    *warnings,
                    *(ReviewWarning(warning.code, warning.blocking) for warning in page.warnings),
                    ReviewWarning("reading_order_and_table_relations_require_review"),
                    ReviewWarning("detector_coverage_limited"),
                    ReviewWarning("preprocessing_orientation_only_no_deskew", blocking=False),
                    *(
                        ReviewWarning(warning.code, warning.blocking)
                        for warning in analysis.result.warnings
                        if warning.page_id in (None, page.page_id)
                    ),
                    ReviewWarning("manual_review_nontext_identifiers_and_clinical_detail"),
                )
            )
        )
        visual_pages.append(
            VisualPage(
                page,
                item.source_page_index,
                item.geometry,
                masks,
                review_warnings,
                required,
                tuple(mask.id for mask in masks),
            )
        )
    manifest = ReviewManifest(
        sources,
        tuple(visual_pages),
        page_order=tuple(page.page_id for page in pages),
        ner_audit=analysis.ner_audit,
    )
    validate_manifest(manifest)
    timings["proposals"] = perf_counter() - started
    checkpoint()
    timings["analysis_wall"] = perf_counter() - wall_started
    return DocumentAnalysis(manifest, analysis, timings)
