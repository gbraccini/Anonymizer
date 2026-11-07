"""!
@file layout.py
@brief Associazione spaziale limitata tra etichette e valori sugli intervalli originali.

Ricostruisce le righe visive dalle regioni OCR con coordinate e cerca il valore accanto o
sotto a etichette esplicite (campi evento, nome/cognome, paziente, medico, luogo). Produce
rilevamenti di livello 1 e gli intervalli delle etichette da proteggere dal NER.
"""

import re
from dataclasses import dataclass
from functools import cache

from anonymizer.detect.clinical import clinical_rules
from anonymizer.detect.context import (
    _DIRECTOR_LABEL,
    _LOCATION_LABEL,
    _PATIENT_LABEL,
    _SEPARATE_LABEL,
    _TITLE,
    detect_separate_patient_fields,
    field_name_end,
    labeled_name_end,
    location_value_end,
)
from anonymizer.detect.event_fields import EVENT_FIELDS, detect_event_fields, parse_event_value
from anonymizer.model import Kind, PageResult, Span, Validation
from anonymizer.visual_model import finite


@dataclass(frozen=True)
class _Unit:
    """!
    @brief Sequenza contigua di token che condividono lo stesso riquadro.
    """

    ## Offset iniziale nel testo della pagina.
    start: int
    ## Offset finale, escluso.
    end: int
    ## Riquadro (x0, y0, x1, y1).
    box: tuple


@cache
def _labels():
    """!
    @brief Restituisce le etichette che introducono un valore sensibile.

    Unisce le regole cliniche con azione "sensitive" alle etichette di paziente, medico,
    direttore e luogo. Il risultato è in cache.
    @return Tuple (tipo, regex dell'etichetta).
    """
    return tuple(
        (Kind(rule["kind"]), re.compile(rule["pattern"]))
        for rule in clinical_rules()["rules"]
        if rule["action"] == "sensitive"
    ) + (
        (Kind.PERSON, _PATIENT_LABEL),
        (Kind.DOCTOR, _TITLE),
        (Kind.DOCTOR, _DIRECTOR_LABEL),
        (Kind.LOCATION, _LOCATION_LABEL),
    )


def _units(page):
    """!
    @brief Associa ai token del testo il riquadro delle regioni che li coprono.

    Ignora le regioni con riquadro assente, non finito o degenere. Token consecutivi con lo stesso
    riquadro, separati solo da spazi, vengono fusi in un'unica unità.
    @param page Pagina con testo e regioni.
    @return Unità in ordine di testo.
    """
    if not page.regions:
        return []
    regions = sorted(
        (
            r
            for r in page.regions
            if r.box is not None
            and len(r.box) == 4
            and all(map(finite, r.box))
            and r.box[0] < r.box[2]
            and r.box[1] < r.box[3]
        ),
        key=lambda r: (r.start, r.end),
    )
    active, cursor, units = [], 0, []
    for token in re.finditer(r"\S+", page.text):
        while cursor < len(regions) and regions[cursor].start < token.end():
            active.append(regions[cursor])
            cursor += 1
        active = [r for r in active if r.end > token.start()]
        boxes = [r.box for r in active if r.start < token.end()]
        if not boxes:
            continue
        box = (
            min(b[0] for b in boxes),
            min(b[1] for b in boxes),
            max(b[2] for b in boxes),
            max(b[3] for b in boxes),
        )
        if units and units[-1].box == box and not page.text[units[-1].end : token.start()].strip():
            units[-1] = _Unit(units[-1].start, token.end(), box)
        else:
            units.append(_Unit(token.start(), token.end(), box))
    return units


def _rows(units):
    """!
    @brief Raggruppa le unità in righe visive.

    Un'unità entra nella riga corrente se si sovrappone verticalmente alla prima unità della riga
    per almeno metà dell'altezza minore.
    @param units Unità da raggruppare.
    @return Righe dall'alto verso il basso, con unità ordinate da sinistra.
    """
    rows = []
    for unit in sorted(units, key=lambda u: (u.box[1], u.box[0])):
        if rows:
            anchor = rows[-1][0].box
            overlap = min(anchor[3], unit.box[3]) - max(anchor[1], unit.box[1])
            if overlap >= 0.5 * min(anchor[3] - anchor[1], unit.box[3] - unit.box[1]):
                rows[-1].append(unit)
                continue
        rows.append([unit])
    return [sorted(row, key=lambda u: u.box[0]) for row in rows]


def _joined(page, units):
    """!
    @brief Concatena il testo delle unità separandolo con spazi.
    @param page Pagina di origine.
    @param units Unità da concatenare.
    @return Coppia (testo, offset): ogni carattere è mappato al codepoint originale, None per gli
            spazi inseriti.
    """
    text, offsets = [], []
    for unit in units:
        if text:
            text.append(" ")
            offsets.append(None)
        value = page.text[unit.start : unit.end]
        text.extend(value)
        offsets.extend(range(unit.start, unit.end))
    return "".join(text), offsets


def _intervals(page, offsets):
    """!
    @brief Converte offset di caratteri in intervalli del testo originale.

    Fonde offset consecutivi o separati solo da spazi nel testo originale.
    @param page Pagina di origine.
    @param offsets Offset originali, con None per i separatori inseriti.
    @return Lista di (inizio, fine).
    """
    result = []
    for offset in (o for o in offsets if o is not None):
        if result and (
            offset == result[-1][1]
            or offset > result[-1][1]
            and not page.text[result[-1][1] : offset].strip()
        ):
            result[-1] = (result[-1][0], offset + 1)
        else:
            result.append((offset, offset + 1))
    return result


def _value_units(row, start, height):
    """!
    @brief Seleziona le unità di un valore a partire da una posizione della riga.

    Si ferma a uno stacco orizzontale maggiore di due altezze o dopo 8 unità.
    @param row Riga di unità.
    @param start Indice della prima unità del valore.
    @param height Altezza di riferimento dell'etichetta.
    @return Unità del valore.
    """
    values = []
    for unit in row[start:]:
        if values and unit.box[0] - values[-1].box[2] > 2 * height:
            break
        values.append(unit)
        if len(values) >= 8:
            break
    return values


def _nearby_values(rows, row_index, stop, label_units, height):
    """!
    @brief Trova il valore di un'etichetta: a destra sulla stessa riga oppure nella riga sotto.

    Il valore a destra deve iniziare entro quattro altezze dall'etichetta. Quello sotto deve
    distare al più due altezze e avere una sola unità allineata a sinistra con l'etichetta.
    @param rows Righe della pagina.
    @param row_index Indice della riga dell'etichetta.
    @param stop Indice successivo all'ultima unità dell'etichetta.
    @param label_units Unità dell'etichetta.
    @param height Altezza di riferimento dell'etichetta.
    @return Unità del valore, vuota se non c'è un candidato.
    """
    row = rows[row_index]
    if stop < len(row) and 0 <= row[stop].box[0] - label_units[-1].box[2] <= 4 * height:
        return _value_units(row, stop, height)
    if row_index + 1 < len(rows):
        below = rows[row_index + 1]
        gap = below[0].box[1] - max(u.box[3] for u in label_units)
        aligned = [
            i for i, u in enumerate(below) if abs(u.box[0] - label_units[0].box[0]) <= 1.5 * height
        ]
        if 0 <= gap <= 2 * height and len(aligned) == 1:
            return _value_units(below, aligned[0], height)
    return []


def _paired_layout_fields(page, records):
    """!
    @brief Marca come persona i valori di campi nome/cognome separati che formano una coppia.

    Due campi con etichette diverse sono vicini se stanno sulla stessa riga entro 18 altezze o
    su righe diverse entro 3 altezze in entrambe le direzioni. Si accettano solo coppie reciproche
    e univoche, per non associare campi di persone diverse.
    @param page Pagina di origine.
    @param records Tuple (etichetta normalizzata, riquadro, intervalli del valore).
    @return Span di livello 1.
    """
    spans = []
    neighbors = []
    for index, (label, box, _) in enumerate(records):
        height = box[3] - box[1]
        possible = []
        for other_index in range(max(0, index - 4), min(len(records), index + 5)):
            other, other_box, _ = records[other_index]
            scale = max(height, other_box[3] - other_box[1])
            same_row = abs(box[1] - other_box[1]) <= 0.5 * scale
            near = (
                same_row
                and abs(box[0] - other_box[0]) <= 18 * scale
                or not same_row
                and abs(box[0] - other_box[0]) <= 3 * scale
                and abs(box[1] - other_box[1]) <= 3 * scale
            )
            if other != label and near:
                possible.append(other_index)
        neighbors.append(possible)
    for index, (_, _, intervals) in enumerate(records):
        possible = neighbors[index]
        if len(possible) != 1 or neighbors[possible[0]] != [index]:
            continue
        for start, end in intervals:
            spans.append(
                Span(
                    page.page_id,
                    start,
                    end,
                    Kind.PERSON,
                    1,
                    "layout:patient_field",
                    validation=Validation("unchecked", "paired_spatial_name_surname_fields"),
                )
            )
    return spans


def analyze_layout_fields(page: PageResult):
    """!
    @brief Analizza la geometria una sola volta; restituisce rilevamenti e protezioni NER esatte
           limitate alle etichette.

    Applica a ogni unità i rilevatori testuali di campi evento e paziente, poi prova come
    etichetta ogni sequenza fino a 7 unità della stessa riga e cerca il valore vicino per campi
    evento, campi nome/cognome separati ed etichette sensibili.
    @param page Pagina con testo e regioni.
    @return Coppia (span ordinati, intervalli (inizio, fine, tipo) delle etichette da escludere
            dal NER).
    """
    rows = _rows(_units(page))
    spans, protected, seen, fields = [], [], set(), []
    for row in rows:
        for unit in row:
            for span in detect_event_fields(page.text[unit.start : unit.end], page.page_id):
                spans.append(
                    Span(
                        page.page_id,
                        span.start + unit.start,
                        span.end + unit.start,
                        span.kind,
                        1,
                        "layout:" + span.origin,
                        validation=span.validation,
                    )
                )
            for span in detect_separate_patient_fields(
                page.text[unit.start : unit.end], page.page_id
            ):
                spans.append(
                    Span(
                        page.page_id,
                        span.start + unit.start,
                        span.end + unit.start,
                        Kind.PERSON,
                        1,
                        "layout:patient_field",
                        validation=span.validation,
                    )
                )
    for row_index, row in enumerate(rows):
        for index in range(len(row)):
            for stop in range(index + 1, min(index + 7, len(row)) + 1):
                label_units = row[index:stop]
                height = max(u.box[3] - u.box[1] for u in label_units)
                if any(
                    b.box[0] - a.box[2] > 2 * height
                    for a, b in zip(label_units, label_units[1:], strict=False)
                ):
                    break
                label, label_offsets = _joined(page, label_units)
                for event_field in EVENT_FIELDS:
                    if not event_field.pattern.fullmatch(label):
                        continue
                    values = _nearby_values(rows, row_index, stop, label_units, height)
                    value, offsets = _joined(page, values)
                    if event_field.mode == "identifier" and any(
                        other.mode == "datetime"
                        and other.pattern.fullmatch(label)
                        and parse_event_value(value, 0, other.mode)
                        for other in EVENT_FIELDS
                    ):
                        continue
                    for start, end, kind, origin in parse_event_value(value, 0, event_field.mode):
                        for a, b in _intervals(page, offsets[start:end]):
                            key = (a, b, kind)
                            if key not in seen:
                                seen.add(key)
                                spans.append(
                                    Span(
                                        page.page_id,
                                        a,
                                        b,
                                        kind,
                                        1,
                                        "layout:" + origin,
                                        validation=Validation(
                                            "unchecked", "spatial_administrative_field"
                                        ),
                                    )
                                )
                field = _SEPARATE_LABEL.fullmatch(label)
                if field:
                    values = _nearby_values(rows, row_index, stop, label_units, height)
                    value, offsets = _joined(page, values)
                    end = field_name_end(value, 0)
                    if end is not None:
                        fields.append(
                            (
                                field.group("label").casefold(),
                                label_units[0].box,
                                _intervals(page, offsets[:end]),
                            )
                        )
                if len(label_units) == 1:
                    inline = _SEPARATE_LABEL.match(label)
                    if inline and not field:
                        end = field_name_end(label, inline.end())
                        if end is not None and not label[end:].strip():
                            fields.append(
                                (
                                    inline.group("label").casefold(),
                                    label_units[0].box,
                                    _intervals(page, label_offsets[inline.end() : end]),
                                )
                            )
                kinds = {kind for kind, pattern in _labels() if pattern.fullmatch(label)}
                if not kinds:
                    continue
                for a, b in _intervals(page, label_offsets):
                    protected.extend(
                        (a, b, kind) for kind in (Kind.PERSON, Kind.LOCATION, Kind.FACILITY)
                    )
                values = _nearby_values(rows, row_index, stop, label_units, height)
                value, offsets = _joined(page, values)
                for kind in kinds:
                    end = (
                        location_value_end(value, 0)
                        if kind == Kind.LOCATION
                        else labeled_name_end(value, 0, kind)
                    )
                    if end is None:
                        continue
                    intervals = _intervals(page, offsets[:end])
                    for a, b in intervals:
                        key = (a, b, kind)
                        if key in seen:
                            continue
                        seen.add(key)
                        spans.append(
                            Span(
                                page.page_id,
                                a,
                                b,
                                kind,
                                1,
                                "layout:personal_location"
                                if kind == Kind.LOCATION
                                else "layout:doctor_name"
                                if kind == Kind.DOCTOR
                                else "layout:patient_name",
                                validation=Validation(
                                    "unchecked",
                                    "explicit_spatial_label"
                                    if len(intervals) == 1
                                    else "explicit_spatial_label_fragment",
                                ),
                            )
                        )
    unique_fields = list(
        {
            (label, box, tuple(intervals)): (label, box, intervals)
            for label, box, intervals in fields
        }.values()
    )
    spans.extend(_paired_layout_fields(page, unique_fields))
    return sorted(spans, key=lambda s: (s.start, s.end, s.kind)), sorted(set(protected))


def detect_layout_fields(page: PageResult) -> list[Span]:
    """!
    @brief Restituisce i rilevamenti spaziali della pagina.
    @param page Pagina con testo e regioni.
    @return Span ordinati.
    """
    return analyze_layout_fields(page)[0]


def protected_layout_spans(page: PageResult) -> list[tuple[int, int, Kind]]:
    """!
    @brief Restituisce gli intervalli delle etichette spaziali da proteggere dal NER.
    @param page Pagina con testo e regioni.
    @return Tuple (inizio, fine, tipo) ordinate.
    """
    return analyze_layout_fields(page)[1]
