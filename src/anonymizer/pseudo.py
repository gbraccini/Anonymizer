"""!
@file pseudo.py
@brief Sostituzione deterministica dei dati identificativi con token reversibili.

Applica gli intervalli fusi al testo delle pagine, assegna un token stabile per entità
e categoria e produce la mappa di trasformazione necessaria alla riassociazione.
"""

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date

from anonymizer.model import (
    Entity,
    Kind,
    MapEntry,
    MergedSpan,
    PageResult,
    PseudonymizationResult,
    PseudonymizedPage,
    Replacement,
    TransformationMap,
    Warning,
    opaque_id,
    validate_interval,
)

## Espressione regolare di un token `[[ETICHETTA]]` su una sola riga.
TOKEN_PATTERN = r"\[\[[^\[\]\r\n]+\]\]"
## Etichetta italiana usata nei token per ciascuna categoria di dato.
_LABELS = {
    Kind.PERSON: "PERSONA",
    Kind.DOCTOR: "MEDICO",
    Kind.CF: "CF",
    Kind.BIRTH_DATE: "DATA_NASCITA",
    Kind.DATE: "DATA",
    Kind.LOCATION: "LUOGO",
    Kind.FACILITY: "STRUTTURA",
    Kind.PHONE: "TELEFONO",
    Kind.EMAIL: "EMAIL",
    Kind.IBAN: "IBAN",
    Kind.HEALTH_CARD: "TESSERA",
    Kind.CASE_NUMBER: "PRATICA",
    Kind.POSTCODE: "CAP",
    Kind.ADDRESS: "INDIRIZZO",
    Kind.COMPOSITE: "DATO",
}


@dataclass(frozen=True)
class ReferenceDate:
    """!
    @brief Data di riferimento di una pagina, usata per convertire la nascita in età.
    """

    ## Data di riferimento (es. data del referto).
    value: date
    ## Se vero, la data è stata confermata e può essere usata.
    confirmed: bool = False


def _birth_date(value: str) -> date | None:
    """!
    @brief Interpreta una data di nascita in formato numerico o con mese in lettere.

    Accetta `GG mese AAAA` con mese italiano, `AAAA-MM-GG` e `GG/MM/AAAA` con separatori
    `/`, `.` o `-`.
    @param value Testo della data.
    @return Data interpretata, oppure None se il formato non è riconosciuto o la data
        non esiste.
    """
    from anonymizer.detect.regex import ITALIAN_MONTHS

    textual = re.fullmatch(r"(\d{1,2})\s+(\w+)\s+(\d{4})", value.casefold())
    if textual and textual[2] in ITALIAN_MONTHS:
        try:
            return date(int(textual[3]), ITALIAN_MONTHS.index(textual[2]) + 1, int(textual[1]))
        except ValueError:
            return None
    for pattern in (r"(\d{4})-(\d{1,2})-(\d{1,2})", r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})"):
        match = re.fullmatch(pattern, value)
        if match:
            parts = tuple(map(int, match.groups()))
            year, month, day = parts if len(match[1]) == 4 else tuple(reversed(parts))
            try:
                return date(year, month, day)
            except ValueError:
                return None
    return None


def should_mask(span: MergedSpan, mask_facilities: bool = True) -> bool:
    """!
    @brief Decide se un intervallo fuso va sostituito.

    Basta un candidato che lo richieda. Non lo richiedono le date generiche di livello
    superiore a 0 che non provengono da regole su eventi o identità, né le strutture
    di livello superiore a 1 quando il mascheramento delle strutture è disattivato.
    @param span Intervallo fuso da valutare.
    @param mask_facilities Se falso, non maschera le strutture rilevate a livello alto.
    @return Vero se almeno un candidato richiede il mascheramento.
    """
    return any(
        not (
            candidate.kind == Kind.DATE
            and candidate.level > 0
            and candidate.origin
            not in (
                "event:date",
                "event:time",
                "layout:event:date",
                "layout:event:time",
                "identity:date",
            )
        )
        and not (candidate.kind == Kind.FACILITY and not mask_facilities and candidate.level > 1)
        for candidate in span.candidates
    )


def pseudonymize(
    pages: Sequence[PageResult],
    spans: Sequence[MergedSpan],
    entities: Sequence[Entity] = (),
    *,
    document_id: str | None = None,
    session_id: str | None = None,
    mask_facilities: bool = True,
    reference_dates: Mapping[str, ReferenceDate] | None = None,
) -> PseudonymizationResult:
    """!
    @brief Sostituisce gli intervalli fusi con token e costruisce la mappa di trasformazione.

    Ogni coppia (entità, categoria) riceve un solo token; senza entità il token è legato
    all'intervallo. Per il paziente confermato si preferiscono `[[PAZIENTE]]` e
    `[[CF_PAZIENTE]]`. I token già presenti nel testo non vengono riassegnati. Una data
    di nascita con data di riferimento confermata diventa un'età in anni, non
    reversibile.
    @param pages Pagine con il testo originale.
    @param spans Intervalli fusi, non sovrapposti all'interno di ogni pagina.
    @param entities Entità note a cui gli intervalli possono riferirsi.
    @param document_id Identificatore del documento; generato se assente.
    @param session_id Identificatore della sessione; generato se assente.
    @param mask_facilities Se falso, lascia in chiaro le strutture rilevate a livello alto.
    @param reference_dates Data di riferimento per pagina, usata per calcolare l'età.
    @return Pagine pseudonimizzate, sostituzioni, mappa e avvisi per la revisione.
    @throws ValueError Se ci sono identificatori duplicati o sconosciuti, intervalli non
        validi o sovrapposti, oppure intervalli privi di candidati.
    """
    page_by_id = {page.page_id: page for page in pages}
    entity_by_id = {entity.id: entity for entity in entities}
    if len(page_by_id) != len(pages) or len(entity_by_id) != len(entities):
        raise ValueError("Duplicate page or entity ID")
    by_page: dict[str, list[MergedSpan]] = defaultdict(list)
    for span in spans:
        if span.page_id not in page_by_id:
            raise ValueError("Unknown page ID")
        validate_interval(page_by_id[span.page_id].text, span.start, span.end)
        by_page[span.page_id].append(span)
    for page_spans in by_page.values():
        previous_end = 0
        for span in sorted(page_spans, key=lambda item: (item.start, item.end)):
            if span.start < previous_end:
                raise ValueError("Merged spans must not overlap")
            previous_end = span.end
    occupied = {match.group() for page in pages for match in re.finditer(TOKEN_PATTERN, page.text)}
    allocated: dict[tuple[str, Kind], str] = {}
    counters: dict[str, int] = defaultdict(int)
    replacements = []
    warnings = []
    output = []
    token_data: dict[str, dict] = {}
    observed: dict[str, list[str]] = defaultdict(list)
    placeholders: dict[str, list[str]] = defaultdict(list)

    def allocate(span: MergedSpan, entity: Entity | None) -> str:
        """!
        @brief Restituisce il token dell'intervallo, assegnandone uno nuovo se necessario.

        I token numerati per etichetta saltano quelli già presenti nel testo.
        @param span Intervallo da sostituire.
        @param entity Entità collegata all'intervallo, se presente.
        @return Token assegnato.
        """
        key = (span.entity_id or span.id, span.kind)
        if key in allocated:
            return allocated[key]
        patient = entity is not None and entity.confirmed and entity.role == "patient"
        label = _LABELS[span.kind]
        preferred = None
        if patient and span.kind in (Kind.PERSON, Kind.CF):
            preferred = "PAZIENTE" if span.kind == Kind.PERSON else "CF_PAZIENTE"
        if preferred and f"[[{preferred}]]" not in occupied:
            token = f"[[{preferred}]]"
        else:
            label = preferred or label
            while True:
                counters[label] += 1
                token = f"[[{label}_{counters[label]}]]"
                if token not in occupied:
                    break
        allocated[key] = token
        occupied.add(token)
        return token

    for page in pages:
        pieces = []
        cursor = 0
        result_cursor = 0
        for span in sorted(by_page[page.page_id], key=lambda item: (item.start, item.end)):
            if span.start < cursor:
                raise ValueError("Merged spans must not overlap")
            if not span.candidates:
                raise ValueError("Merged spans require detection provenance")
            if not should_mask(span, mask_facilities):
                continue
            original = page.text[span.start : span.end]
            entity = entity_by_id.get(span.entity_id)
            if span.entity_id is not None and entity is None:
                raise ValueError("Unknown entity ID")
            for conflict in span.conflicts:
                warnings.append(Warning(conflict, page.page_id, (span.id,), blocking=True))
            if span.kind in (Kind.PERSON, Kind.DOCTOR, Kind.CF, Kind.BIRTH_DATE) and (
                entity is None or not entity.confirmed
            ):
                warnings.append(Warning("identity_unconfirmed", page.page_id, (span.id,)))
            reversible = True
            substitution = None
            reference = (reference_dates or {}).get(page.page_id)
            if span.kind == Kind.BIRTH_DATE and reference and reference.confirmed:
                born = _birth_date(original)
                if born is not None and born <= reference.value:
                    age = (
                        reference.value.year
                        - born.year
                        - ((reference.value.month, reference.value.day) < (born.month, born.day))
                    )
                    substitution = f"{age} anni"
                    reversible = False
            if substitution is None:
                substitution = allocate(span, entity)
                if span.kind == Kind.BIRTH_DATE:
                    warnings.append(
                        Warning("birth_date_without_confirmed_reference", page.page_id, (span.id,))
                    )
            prefix = page.text[cursor : span.start]
            pieces.extend((prefix, substitution))
            result_cursor += len(prefix)
            operation = Replacement(
                opaque_id(),
                page.page_id,
                span.start,
                span.end,
                original,
                substitution,
                result_cursor,
                result_cursor + len(substitution),
                span.entity_id,
                span.id,
                reversible,
            )
            replacements.append(operation)
            if span.entity_id:
                observed[span.entity_id].append(original)
                if reversible:
                    placeholders[span.entity_id].append(substitution)
            if reversible:
                canonical = (
                    dict(entity.canonical_values).get(span.kind, original) if entity else original
                )
                if substitution not in token_data:
                    token_data[substitution] = {
                        "canonical": canonical,
                        "entity_id": span.entity_id,
                        "ids": [],
                        "values": [],
                    }
                token_data[substitution]["ids"].append(operation.id)
                token_data[substitution]["values"].append(original)
            cursor = span.end
            result_cursor += len(substitution)
        pieces.append(page.text[cursor:])
        output.append(PseudonymizedPage(page.page_id, "".join(pieces)))
    updated_entities = tuple(
        replace(
            entity,
            observed_variants=tuple(
                dict.fromkeys((*entity.observed_variants, *observed[entity.id]))
            ),
            placeholders=tuple(dict.fromkeys((*entity.placeholders, *placeholders[entity.id]))),
        )
        for entity in entities
    )
    entries = tuple(
        MapEntry(
            token,
            data["canonical"],
            data["entity_id"],
            tuple(data["ids"]),
            tuple(data["values"]),
        )
        for token, data in token_data.items()
    )
    mapping = TransformationMap(
        document_id or opaque_id(),
        session_id or opaque_id(),
        updated_entities,
        entries,
        tuple(replacements),
    )
    return PseudonymizationResult(tuple(output), tuple(replacements), mapping, tuple(warnings))


def undo_replacement(result_text: str, operation: Replacement) -> str:
    """!
    @brief Annulla una singola sostituzione nel testo risultante.
    @param result_text Testo pseudonimizzato che contiene la sostituzione.
    @param operation Sostituzione da annullare.
    @return Testo con il valore originale ripristinato in quella posizione.
    @throws ValueError Se gli offset non corrispondono più al testo, ad esempio dopo
        altre modifiche.
    """
    if result_text[operation.result_start : operation.result_end] != operation.replacement:
        raise ValueError("Replacement offsets are stale; rebuild from the original page")
    return (
        result_text[: operation.result_start]
        + operation.original
        + result_text[operation.result_end :]
    )
