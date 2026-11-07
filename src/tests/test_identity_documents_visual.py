from __future__ import annotations

from dataclasses import replace

import pytest
from PIL import Image, ImageDraw

from anonymizer.detect.identity_documents import analyze_identity_document
from anonymizer.model import PageResult, TextRegion
from anonymizer.redact import apply_redactions, propose_redactions
from anonymizer.text_pipeline import analyze_text
from anonymizer.visual_model import ReviewManifest, SourcePageGeometry, VisualPage
from anonymizer.web.text import document_text, page_text

GEOMETRY = SourcePageGeometry(1400, 480, 1400, 480, 72)


def _td3():
    first = "P<ITAROSSI<<ALFA<MARIA".ljust(44, "<")
    second = (
        "CA1234567" "0" "ITA" "900101" "0" "F" "300101" "0" "<<<<<<<<<<<<<<" "0" "0"
    )
    assert len(first) == len(second) == 44
    return first, second


def _td1():
    first = "C<ITACA12345AA0" + "<" * 15
    second = "9001010F3001010ITA" + "<" * 11 + "0"
    third = "ROSSI<<ALFA<MARIA".ljust(30, "<")
    assert len(first) == len(second) == len(third) == 30
    return first, second, third


DOCUMENTS = (
    pytest.param(
        (
            "PATENTE DI GUIDA / DRIVING LICENCE",
            "1. ROSSI",
            "2. ALFA",
            "3. 01.01.1990 ROMA (RM)",
            "5. U1234567X",
            "Sesso: F",
            "Esame: glicemia 92 mg/dL; terapia ogni 8 ore per 7 giorni",
        ),
        ("ROSSI", "ALFA", "01.01.1990", "ROMA", "U1234567X"),
        ("Sesso: F", "92 mg/dL", "ogni 8 ore per 7 giorni"),
        id="driving-licence",
    ),
    pytest.param(
        (
            "CARTA D'IDENTITÀ ELETTRONICA / IDENTITY CARD",
            "Cognome / Surname: Rossi",
            "Nome / Given names: Alfa Maria",
            "Numero documento / Document no.: CA12345AA",
            "CAN: 654321",
            "Data di nascita / Date of birth: 01/01/1990",
            "Sesso / Sex: F",
            "Esame: emoglobina 12 g/dL; dose 5 mg",
            *_td1(),
        ),
        ("Rossi", "Alfa Maria", "CA12345AA", "654321", "01/01/1990", *_td1()),
        ("Sesso / Sex: F", "12 g/dL", "5 mg"),
        id="bilingual-cie-with-td1",
    ),
    pytest.param(
        (
            "PASSAPORTO / PASSPORT",
            "COGNOME / SURNAME / NOM: Rossi",
            "NOME / GIVEN NAMES / PRÉNOMS: Alfa Maria",
            "DATA DI NASCITA / DATE OF BIRTH / DATE DE NAISSANCE: 01/01/1990",
            "AUTORITÀ / ISSUING AUTHORITY / AUTORITE: QUESTURA DI ESEMPIO",
            "Sesso / Sex: F",
            "Clinical note: pressione 120/80 mmHg; 2 compresse al giorno",
            *_td3(),
        ),
        ("Rossi", "Alfa Maria", "01/01/1990", "QUESTURA DI ESEMPIO", *_td3()),
        ("Sesso / Sex: F", "120/80 mmHg", "2 compresse al giorno"),
        id="passport-with-td3",
    ),
)


def _page(lines: tuple[str, ...], page_id: str) -> PageResult:
    text = "\n".join(lines)
    regions = []
    offset = 0
    for row, line in enumerate(lines):
        column = 0
        for token in line.split():
            token_start = line.index(token, column)
            start = offset + token_start
            end = start + len(token)
            left = token_start * 12 + 8
            top = row * 27 + 5
            right = left + max(12, len(token) * 12)
            regions.append(TextRegion(start, end, (left, top, right, top + 17)))
            column = token_start + len(token)
        offset += len(line) + 1
    return PageResult(
        page_id,
        f"{page_id}-source",
        0,
        text,
        extraction_mode="ocr",
        regions=tuple(regions),
    )


def _regions_for_value(page: PageResult, value: str):
    start = page.text.index(value)
    end = start + len(value)
    return [region for region in page.regions if region.start < end and region.end > start]


def test_document_type_mentioned_in_prose_does_not_activate_identity_field_rules():
    page = _page(
        ("Conservare la patente nel cassetto.", "Codice interno: ZX1234", "Sesso: F"),
        "identity-mentioned-in-prose",
    )
    analysis = analyze_text([page], ner_disabled_reason="synthetic_test")

    assert not any(span.origin.startswith("identity:") for span in analysis.candidates)
    assert not any(
        warning.code == "identity_document_visual_review"
        for warning in analysis.result.warnings
    )


def test_numbered_medical_exam_list_is_not_interpreted_as_driving_licence_fields():
    page = _page(
        (
            "PATENTE DI GUIDA",
            "1. Emocromo",
            "2. Elettrocardiogramma",
            "3. Visita medica",
            "Esame: glicemia 92 mg/dL",
        ),
        "identity-title-with-medical-list",
    )
    detected = analyze_identity_document(page)
    false_field_values = {"Emocromo", "Elettrocardiogramma", "Visita medica"}

    assert not any(
        page.text[span.start : span.end] in false_field_values
        for span in detected.spans
    )


@pytest.mark.parametrize("lines, identifiers, preserved", DOCUMENTS)
def test_identity_document_fields_are_masked_in_pixels_and_clipboard_text(
    lines, identifiers, preserved
):
    page = _page(lines, f"identity-{lines[0][:8].lower()}")
    analysis = analyze_text([page], ner_disabled_reason="synthetic_test")
    masks, warnings, required = propose_redactions(
        page, list(analysis.merged_spans), GEOMETRY
    )
    assert not warnings
    assert required

    candidate_texts = {
        page.text[span.start : span.end]
        for span in analysis.candidates
        if span.page_id == page.page_id
    }
    assert all(any(value in candidate for candidate in candidate_texts) for value in identifiers)

    visual_page = VisualPage(page, 0, GEOMETRY, masks)
    copied_text = page_text(visual_page)["redacted"]
    exported_text = document_text(ReviewManifest((), (visual_page,)))
    for value in identifiers:
        assert value not in copied_text
        assert value not in exported_text
    for value in preserved:
        assert value in copied_text
        assert value in exported_text

    source = Image.new("RGB", (GEOMETRY.width, GEOMETRY.height), "white")
    try:
        draw = ImageDraw.Draw(source)
        for region in page.regions:
            x0, y0, x1, y1 = map(int, region.box)
            draw.rectangle((x0, y0, x1 - 1, y1 - 1), fill=(64, 64, 64))
        redacted = apply_redactions(
            source,
            tuple(replace(mask, confirmed=True) for mask in masks),
            GEOMETRY,
        )
        try:
            for value in identifiers:
                regions = _regions_for_value(page, value)
                assert regions
                for region in regions:
                    x0, y0, x1, y1 = map(int, region.box)
                    with redacted.crop((x0, y0, x1, y1)) as crop:
                        assert crop.getextrema() == ((0, 0),) * 3, value
            for value in preserved:
                regions = _regions_for_value(page, value)
                assert regions
                for region in regions:
                    x0, y0, x1, y1 = map(int, region.box)
                    with redacted.crop((x0, y0, x1, y1)) as crop:
                        assert crop.getextrema() == ((64, 64),) * 3, value
        finally:
            redacted.close()
    finally:
        source.close()
