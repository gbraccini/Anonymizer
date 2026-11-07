"""!
@file merge.py
@brief Fusione dei candidati rilevati in intervalli non sovrapposti.

Raggruppa i candidati che si sovrappongono o che, con la stessa entità e categoria,
sono contigui o separati solo da spazio, trattino o apostrofo, preservandone la
provenienza.
"""

from collections.abc import Iterable, Mapping

from anonymizer.model import Kind, MergedSpan, Span, validate_interval


def _merged(candidates: list[Span]) -> MergedSpan:
    """!
    @brief Costruisce l'intervallo fuso che copre un gruppo di candidati.

    Categorie diverse vengono riconciliate: data e data di nascita diventano data di
    nascita, persona e medico diventano medico; ogni altra combinazione diventa
    composita con conflitto di tipo. Entità diverse producono un conflitto di entità.
    @param candidates Candidati della stessa pagina, non vuoto.
    @return Intervallo fuso con eventuali conflitti.
    """
    first = candidates[0]
    kinds = {span.kind for span in candidates}
    entities = {span.entity_id for span in candidates if span.entity_id is not None}
    conflicts = []
    if len(entities) > 1:
        conflicts.append("entity_conflict")
    if len(kinds) > 1:
        if kinds <= {Kind.DATE, Kind.BIRTH_DATE}:
            kind = Kind.BIRTH_DATE
        elif kinds <= {Kind.PERSON, Kind.DOCTOR}:
            kind = Kind.DOCTOR
        else:
            kind = Kind.COMPOSITE
            conflicts.append("type_conflict")
    else:
        kind = first.kind
    return MergedSpan(
        first.page_id,
        min(span.start for span in candidates),
        max(span.end for span in candidates),
        kind,
        tuple(candidates),
        entity_id=next(iter(entities)) if len(entities) == 1 else None,
        conflicts=tuple(conflicts),
    )


def merge(text: str | Mapping[str, str], spans: Iterable[Span]) -> list[MergedSpan]:
    """!
    @brief Fonde i candidati sovrapposti o adiacenti della stessa entità.

    I candidati sono ordinati per pagina e posizione; l'esito è deterministico.
    @param text Testo della pagina, oppure mappa da identificatore di pagina a testo
        quando i candidati appartengono a più pagine.
    @param spans Candidati da fondere.
    @return Intervalli fusi in ordine di pagina e posizione.
    @throws ValueError Se servono più pagine ma è dato un solo testo, se una pagina è
        sconosciuta o se un intervallo non è valido.
    """
    candidates = sorted(spans, key=lambda item: (item.page_id, item.start, item.end, item.id))
    if isinstance(text, str):
        if len({span.page_id for span in candidates}) > 1:
            raise ValueError("Multiple pages require a page_id to text mapping")
        pages = {span.page_id: text for span in candidates}
    else:
        pages = text
    for span in candidates:
        if span.page_id not in pages:
            raise ValueError("Unknown page ID")
        validate_interval(pages[span.page_id], span.start, span.end)
    output = []
    group: list[Span] = []
    end = 0
    for span in candidates:
        same_page = bool(group) and span.page_id == group[0].page_id
        same_entity = (
            bool(group)
            and span.entity_id is not None
            and all(item.entity_id == span.entity_id for item in group)
            and all(item.kind == span.kind for item in group)
        )
        separator = pages[span.page_id][end : span.start] if same_page else ""
        adjacent = (
            same_entity
            and same_page
            and span.start >= end
            and (span.start == end or separator in (" ", "-", "'", "’"))
        )
        if group and not (same_page and (span.start < end or adjacent)):
            output.append(_merged(group))
            group = []
        group.append(span)
        end = max(end, span.end) if len(group) > 1 else span.end
    if group:
        output.append(_merged(group))
    return output
