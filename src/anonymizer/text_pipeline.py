"""!
@file text_pipeline.py
@brief Analisi testuale delle pagine: rilevamento, fusione e pseudonimizzazione.

Esegue tutti i rilevatori (contesto, documenti d'identità, layout, regex, dizionario,
identità note, NER) sul testo estratto, fonde i candidati e produce il risultato
pseudonimizzato con i relativi avvisi.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from time import perf_counter

from anonymizer.detect.context import (
    detect_contact_details,
    detect_doctors,
    detect_facility_repetitions,
    detect_patient_labels,
)
from anonymizer.detect.dictionary import Vocabulary, detect_dictionary
from anonymizer.detect.event_fields import detect_event_fields
from anonymizer.detect.identity_documents import (
    analyze_identity_document,
    detect_document_number_repetitions,
)
from anonymizer.detect.known import detect_known
from anonymizer.detect.layout import analyze_layout_fields
from anonymizer.detect.ner import NerDetector
from anonymizer.detect.regex import detect_regex
from anonymizer.detect.repeated import detect_person_repetitions
from anonymizer.merge import merge
from anonymizer.model import MergedSpan, PageResult, PseudonymizationResult, Span, Warning
from anonymizer.ner_model import NerAudit
from anonymizer.patient import KnownIdentity
from anonymizer.pseudo import ReferenceDate, pseudonymize
from anonymizer.visual_model import finite


@dataclass(frozen=True)
class TextAnalysis:
    """!
    @brief Esito completo dell'analisi testuale di un documento.
    """

    ## Pagine analizzate.
    pages: tuple[PageResult, ...]
    ## Tutti i candidati prodotti dai rilevatori, prima della fusione.
    candidates: tuple[Span, ...]
    ## Intervalli fusi con la relativa provenienza.
    merged_spans: tuple[MergedSpan, ...]
    ## Risultato della pseudonimizzazione, avvisi inclusi.
    result: PseudonymizationResult
    ## Informazioni di audit sull'uso del modello NER.
    ner_audit: NerAudit = field(default_factory=NerAudit)


def ner_sections(page: PageResult) -> list[tuple[int, int]]:
    """!
    @brief Suddivide la pagina in sezioni per il NER.

    Mantiene insieme le righe vicine ma non unisce sezioni distanti della pagina: si taglia
    dove lo spazio verticale tra regioni supera sei volte l'altezza della riga e il testo
    intermedio è vuoto.
    @param page Pagina con testo e regioni.
    @return Lista di intervalli (inizio, fine) che coprono il testo della pagina.
    """
    cuts = [0]
    previous = None
    for region in sorted(page.regions, key=lambda item: (item.start, item.end)):
        box = region.box
        if box is None or len(box) != 4 or not all(map(finite, box)):
            continue
        x0, y0, x1, y1 = box
        if x0 >= x1 or y0 >= y1:
            continue
        if previous is not None and region.start >= previous.end:
            old = previous.box
            gap = max(y0 - old[3], old[1] - y1, 0)
            height = max(y1 - y0, old[3] - old[1])
            if gap > 6 * height and not page.text[previous.end : region.start].strip():
                if region.start > cuts[-1]:
                    cuts.append(region.start)
        previous = region
    if len(page.text) > cuts[-1]:
        cuts.append(len(page.text))
    return list(zip(cuts, cuts[1:], strict=False))


def detect_page_ner(page: PageResult, ner: NerDetector) -> list[Span]:
    """!
    @brief Esegue il NER sezione per sezione riportando gli offset sul testo della pagina.
    @param page Pagina da analizzare.
    @param ner Rilevatore NER.
    @return Intervalli rilevati con posizioni relative all'intero testo della pagina.
    """
    return [
        replace(span, start=span.start + start, end=span.end + start)
        for start, end in ner_sections(page)
        for span in ner.detect(page.text[start:end], page.page_id)
    ]


def _layout_protected(span, protected):
    """!
    @brief Indica se un intervallo NER ricade in una zona protetta dall'analisi del layout.
    @param span Intervallo candidato.
    @param protected Terne (inizio, fine, tipo) protette dal layout.
    @return Vero se l'intervallo è di livello 3 ed è contenuto in una zona dello stesso tipo.
    """
    return span.level == 3 and any(
        kind == span.kind and start <= span.start < span.end <= end
        for start, end, kind in protected
    )


def analyze_text(
    pages: Sequence[PageResult],
    identities: tuple[KnownIdentity, ...] = (),
    *,
    vocabulary: Vocabulary | None = None,
    reference_dates: dict[str, ReferenceDate] | None = None,
    mask_facilities: bool = True,
    ner: NerDetector | None = None,
    ner_disabled_reason: str = "not_configured",
    timings: dict[str, float] | None = None,
    ner_candidates: dict[str, list[Span]] | None = None,
) -> TextAnalysis:
    """!
    @brief Rileva i dati identificativi nelle pagine e produce il risultato pseudonimizzato.

    Quando la pagina ha regioni con geometria, alcuni rilevatori basati solo sul testo
    (identificatori di evento, campi paziente da contesto) vengono esclusi a favore
    dell'analisi posizionale. I candidati NER interni a zone protette dal layout vengono
    scartati. Gli avvisi per documenti
    d'identità riconosciuti e per NER disattivato vengono aggiunti al risultato.
    @param pages Pagine con testo estratto.
    @param identities Identità note da cercare nel testo.
    @param vocabulary Vocabolario per il rilevamento a dizionario.
    @param reference_dates Date di riferimento per la pseudonimizzazione delle date.
    @param mask_facilities Se vero, maschera anche le strutture sanitarie.
    @param ner Rilevatore NER, o None se disattivato.
    @param ner_disabled_reason Motivo registrato nell'audit quando il NER è assente.
    @param timings Dizionario opzionale in cui accumulare il tempo speso nel NER.
    @param ner_candidates Candidati NER già calcolati per pagina, usati al posto del NER.
    @return Analisi con pagine, candidati, intervalli fusi, risultato e audit NER.
    @throws ValueError Se i candidati NER precalcolati non corrispondono alle pagine o
        contengono intervalli non validi.
    """
    if ner_candidates is not None:
        if ner is None or set(ner_candidates) != {page.page_id for page in pages}:
            raise ValueError("invalid_precomputed_ner_pages")
        for page in pages:
            if any(
                span.page_id != page.page_id
                or span.level != 3
                or not 0 <= span.start < span.end <= len(page.text)
                for span in ner_candidates[page.page_id]
            ):
                raise ValueError("invalid_precomputed_ner_span")
    contact = {page.page_id: detect_contact_details(page.text, page.page_id) for page in pages}
    candidates = detect_facility_repetitions(
        pages, [span for spans in contact.values() for span in spans]
    )
    identity_warnings = []
    for page in pages:
        identity_document = analyze_identity_document(page)
        candidates.extend(identity_document.spans)
        if identity_document.recognized:
            identity_warnings.append(Warning("identity_document_visual_review", page.page_id))
        layout, protected = analyze_layout_fields(page)
        candidates.extend(layout)
        has_geometry = any(region.box for region in page.regions)
        candidates.extend(
            span
            for span in detect_regex(page.text, page.page_id)
            if not has_geometry or span.origin != "event:identifier"
        )
        if not has_geometry:
            candidates.extend(detect_event_fields(page.text, page.page_id, identifiers=False))
        candidates.extend(detect_doctors(page.text, page.page_id))
        candidates.extend(
            span
            for span in detect_patient_labels(page.text, page.page_id)
            if span.origin != "context:patient_field" or not any(r.box for r in page.regions)
        )
        candidates.extend(contact[page.page_id])
        candidates.extend(detect_dictionary(page.text, page.page_id, vocabulary))
        candidates.extend(detect_known(page.text, page.page_id, identities))
        if ner is not None:
            if ner_candidates is not None:
                candidates.extend(
                    s for s in ner_candidates[page.page_id] if not _layout_protected(s, protected)
                )
            else:
                started = perf_counter()
                candidates.extend(
                    s for s in detect_page_ner(page, ner) if not _layout_protected(s, protected)
                )
                if timings is not None:
                    timings["ner"] = timings.get("ner", 0) + perf_counter() - started
    candidates.extend(detect_document_number_repetitions(pages, tuple(candidates)))
    candidates.extend(detect_person_repetitions(pages, tuple(candidates)))
    merged = merge({page.page_id: page.text for page in pages}, candidates)
    result = pseudonymize(
        pages,
        merged,
        [identity.to_entity() for identity in identities],
        reference_dates=reference_dates,
        mask_facilities=mask_facilities,
    )
    audit = ner.audit if ner is not None else NerAudit(reason=ner_disabled_reason)
    result = replace(result, warnings=(*result.warnings, *identity_warnings))
    if ner is None:
        result = replace(result, warnings=(*result.warnings, Warning("ner_disabled")))
    return TextAnalysis(tuple(pages), tuple(candidates), tuple(merged), result, audit)
