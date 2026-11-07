import re

import pytest

from anonymizer.detect.event_fields import detect_event_fields
from anonymizer.detect.regex import detect_regex
from anonymizer.merge import merge
from anonymizer.model import Kind, PageResult, Span, TextRegion
from anonymizer.pseudo import should_mask
from anonymizer.text_pipeline import analyze_text


@pytest.mark.parametrize(
    "label,value",
    [
        ("Data prelievo:", "gioved\u00ec 05/11/2026 ore 08:30"),
        ("Data/Ora prelievo:", "05/11/2026 08:30"),
        ("Data referto:", "05/11/2026 Ore: 08:30"),
        ("Referto del", "05/11/2026, ore 08:30"),
        ("Data e ora:", "5 novembre 2026 ore 08:30:42"),
        ("Visita", "04/04/2020"),
        ("Ricovero del", "2026-11-05"),
        ("Data:", "05/11"),
        ("Data refertazione:", "5 novembre"),
        ("Giorno visita:", "gioved\u00ec"),
        ("Data referto:", "novembre 2026"),
        ("Ora referto:", "08:30:00"),
        ("Orario dimissione:", "8.30"),
        ("Firmato il", "05/11/2026"),
    ],
)
def test_explicit_administrative_dates_times_are_masked(label, value):
    text = "\U0001f600 " + label + " " + value
    page = PageResult("p", "s", 0, text)
    result = analyze_text([page])
    events = [s for s in result.candidates if s.origin in ("event:date", "event:time")]
    assert events and all(s.kind == Kind.DATE and s.level == 1 for s in events)
    for span in events:
        assert text[span.start : span.end] not in result.result.pages[0].text
    assert label in result.result.pages[0].text


@pytest.mark.parametrize(
    "text",
    [
        "Assumere alle 08:00 per 7 giorni",
        "500 mg ogni 8 ore",
        "Visita ogni gioved\u00ec",
        "Durata ricovero: 7 giorni",
        "Et\u00e0: 75 anni",
        "Terapia dal 05/11/2026",
        "Bibliografia: studio del 05/11/2026",
        "Autorizzazione del 05/11/2026",
        "Data normativa: 05/11/2026",
        "Data prelievo:\n\n05/11/2026",
        "Protocollo terapeutico 12 mg",
        "Referto negativo",
        "Cartella clinica",
        "Pratica completata",
        "Protocollo:\nOgni 8 ore per 7 giorni",
        "Protocollo:\n\n90",
        "Via orale 2 volte",
        "Sede anatomica: Fegato",
        "Sede prelievo: Fossa antecubitale sinistra",
        "Luogo prelievo: Fegato",
        "Ora visita: 25:99",
        "Data visita: 31/02/2026",
        "Esame: 12.5 mg/dL",
        "Referto: 12.5 mmol/L",
        "Protocollo terapeutico: 5-FU",
    ],
)
def test_clinical_schedules_narratives_and_incomplete_fields_preserved(text):
    assert detect_event_fields(text, "p") == []
    result = analyze_text([PageResult("p", "s", 0, text)])
    assert not any(s.origin.startswith("event:") for s in result.candidates)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Prot. n. AB-7", "AB-7"),
        ("N. cartella clinica: 12/34", "12/34"),
        ("Cartella clinica n. CC-2026-0042", "CC-2026-0042"),
        ("Referto n. 123", "123"),
        ("Accettazione: 7", "7"),
        ("ID paziente: A9", "A9"),
        ("Cod. paziente: 99", "99"),
        ("pratica AX-9001", "AX-9001"),
    ],
)
def test_short_contextual_identifiers_without_dose_or_common_word_matching(text, expected):
    spans = [s for s in detect_regex(text, "p") if s.kind == Kind.CASE_NUMBER]
    assert [text[s.start : s.end] for s in spans] == [expected]
    result = analyze_text([PageResult("p", "s", 0, text)])
    assert expected not in result.result.pages[0].text


def test_location_date_and_sex_policy_are_independent():
    text = "Luogo e data: Valleverde, 05/11/2026. Sesso: Femminile. Durata: 7 giorni."
    result = analyze_text([PageResult("p", "s", 0, text)])
    assert "Valleverde" not in result.result.pages[0].text
    assert "05/11/2026" not in result.result.pages[0].text
    assert "Sesso: Femminile" in result.result.pages[0].text
    assert "Durata: 7 giorni" in result.result.pages[0].text


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_single_wrapped_field_is_supported_without_geometry(newline):
    text = "Data accettazione:" + newline + "05/11/2026"
    assert any(s.origin == "event:date" for s in detect_event_fields(text, "p"))


def test_candidate_policy_does_not_turn_generic_date_into_mask_without_event_evidence():
    text = "05/11/2026"
    generic = Span("p", 0, len(text), Kind.DATE, 1, "regex:date")
    event = Span("p", 0, len(text), Kind.DATE, 1, "event:date")
    assert not should_mask(merge(text, [generic])[0])
    combined = merge(text, [generic, event])[0]
    assert combined.kind == Kind.DATE and should_mask(combined)
    assert set(combined.origins) == {"regex:date", "event:date"}


def test_event_date_is_not_also_a_case_number_and_associated_time_is_masked():
    page = PageResult("p", "s", 0, "Referto 05/11/2026, ore 08:30")
    result = analyze_text([page])
    assert not any(s.kind == Kind.CASE_NUMBER for s in result.candidates)
    assert "08:30" not in result.result.pages[0].text
    assert all(s.kind == Kind.DATE for s in result.merged_spans)


def table(parts):
    text, regions = "", []
    for value, box in parts:
        start = len(text)
        text += value + "\n"
        regions.append(TextRegion(start, start + len(value), box))
    return PageResult("p", "s", 0, text, regions=tuple(regions))


def test_layout_uses_visual_neighbors_not_interposed_reading_order():
    page = table(
        [
            ("Data prelievo:", (0, 0, 90, 10)),
            ("Glucosio 90", (400, 0, 470, 10)),
            ("05/11/2026", (100, 0, 180, 10)),
            ("Ora referto:", (0, 25, 80, 35)),
            ("08:30", (90, 25, 130, 35)),
        ]
    )
    analysis = analyze_text([page])
    origins = {s.origin for s in analysis.candidates}
    assert {"layout:event:date", "layout:event:time"} <= origins
    assert "Glucosio 90" in analysis.result.pages[0].text
    assert "05/11/2026" not in analysis.result.pages[0].text


def test_far_column_cannot_supply_identifier_via_linear_newline_fallback():
    page = table(
        [
            ("Protocollo:", (0, 0, 80, 10)),
            ("90", (400, 20, 420, 30)),
            ("Glucosio", (400, 10, 460, 20)),
        ]
    )
    assert not any(s.kind == Kind.CASE_NUMBER for s in analyze_text([page]).candidates)


def test_layout_below_field_and_coarse_cell_both_supported():
    page = table(
        [
            ("N. cartella clinica:", (0, 0, 100, 10)),
            ("AB-7", (0, 20, 40, 30)),
            ("Luogo prelievo: Valleverde", (0, 50, 180, 60)),
        ]
    )
    analysis = analyze_text([page])
    assert "AB-7" not in analysis.result.pages[0].text
    assert "Valleverde" not in analysis.result.pages[0].text
    assert not re.search(r"\[\[DATA", analysis.result.pages[0].text)
