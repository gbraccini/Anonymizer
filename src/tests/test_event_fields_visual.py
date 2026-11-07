from __future__ import annotations

from dataclasses import replace

from PIL import Image, ImageDraw

from anonymizer.model import Kind, PageResult, TextRegion
from anonymizer.redact import apply_redactions, propose_redactions
from anonymizer.text_pipeline import analyze_text
from anonymizer.visual_model import ReviewManifest, SourcePageGeometry, VisualPage
from anonymizer.web.text import document_text, page_text

LINES = (
    "Luogo prelievo: Valleverde",
    "Data prelievo: giovedì 05/11/2026 ore 08:30",
    "Prot. n. AB-7",
    "Cartella clinica: CC-2026-0042",
    "Sesso: Femminile",
    "Terapia: 500 mg ogni 8 ore per 7 giorni",
    "Sede anatomica: ginocchio sinistro",
)
PAGE_ID = "synthetic-event-fields"
PAGE_TEXT = "\n".join(LINES)
GEOMETRY = SourcePageGeometry(1200, 180, 1200, 180, 72)


def _page_with_character_regions() -> PageResult:
    regions = []
    offset = 0
    for row, line in enumerate(LINES):
        for column, character in enumerate(line):
            if not character.isspace():
                x = column * 12
                y = row * 24
                regions.append(
                    TextRegion(offset + column, offset + column + 1, (x, y, x + 11, y + 20))
                )
        offset += len(line) + 1
    return PageResult(
        PAGE_ID,
        "synthetic-event-source",
        0,
        PAGE_TEXT,
        extraction_mode="ocr",
        regions=tuple(regions),
    )


def _candidate_values(page, analysis, kind):
    return {
        page.text[span.start : span.end]
        for span in analysis.candidates
        if span.page_id == page.page_id and span.kind == kind
    }


def _spans(page, analysis, origin):
    accepted_origins = {origin, f"layout:{origin}"}
    return [
        span
        for span in analysis.candidates
        if span.page_id == page.page_id and span.origin in accepted_origins
    ]


def _regions_for_interval(page, start, end):
    return [region for region in page.regions if region.start < end and region.end > start]


def test_event_fields_are_redacted_in_visual_and_clipboard_text_but_clinical_content_remains():
    page = _page_with_character_regions()
    analysis = analyze_text([page], ner_disabled_reason="synthetic_test")

    assert any(
        page.text[span.start : span.end] == "Valleverde"
        for span in _spans(page, analysis, "event:location")
    )
    assert any(
        page.text[span.start : span.end] == "giovedì 05/11/2026"
        for span in _spans(page, analysis, "event:date")
    )
    assert any(
        page.text[span.start : span.end] == "08:30" for span in _spans(page, analysis, "event:time")
    )
    identifiers = _spans(page, analysis, "event:identifier")
    assert {page.text[span.start : span.end] for span in identifiers} >= {"AB-7", "CC-2026-0042"}

    masks, warnings, required = propose_redactions(page, list(analysis.merged_spans), GEOMETRY)
    assert not warnings
    assert required
    visual_page = VisualPage(page, 0, GEOMETRY, masks)
    copied_text = page_text(visual_page)["redacted"]
    clipboard_text = document_text(ReviewManifest((), (visual_page,)))

    for value in ("Valleverde", "giovedì", "05/11/2026", "08:30", "AB-7", "CC-2026-0042"):
        assert value not in copied_text
        assert value not in clipboard_text
    for value in (
        "Sesso: Femminile",
        "500 mg ogni 8 ore per 7 giorni",
        "Sede anatomica: ginocchio sinistro",
    ):
        assert value in copied_text
        assert value in clipboard_text

    source = Image.new("RGB", (GEOMETRY.width, GEOMETRY.height), "white")
    try:
        draw = ImageDraw.Draw(source)
        for region in page.regions:
            x0, y0, x1, y1 = region.box
            draw.rectangle((x0, y0, x1 - 1, y1 - 1), fill=(64, 64, 64))
        redacted = apply_redactions(
            source, tuple(replace(mask, confirmed=True) for mask in masks), GEOMETRY
        )
        try:
            assert redacted.size == source.size
            for required_id in required:
                span = next(item for item in analysis.merged_spans if item.id == required_id)
                assert any(mask.candidate_ids == (required_id,) for mask in masks)
                assert span.kind in {Kind.LOCATION, Kind.DATE, Kind.CASE_NUMBER}
                for region in _regions_for_interval(page, span.start, span.end):
                    x0, y0, x1, y1 = map(int, region.box)
                    with redacted.crop((x0, y0, x1, y1)) as crop:
                        assert crop.getextrema() == ((0, 0),) * 3
            preserved_values = (
                "Femminile",
                "500 mg",
                "8 ore",
                "7 giorni",
                "ginocchio sinistro",
            )
            for value in preserved_values:
                line_index = next(i for i, line in enumerate(LINES) if value in line)
                line = LINES[line_index]
                start = line.index(value)
                offset = start + sum(len(part) + 1 for part in LINES[:line_index])
                char_regions = _regions_for_interval(page, offset, offset + len(value))
                assert char_regions
                for region in char_regions:
                    x0, y0, x1, y1 = map(int, region.box)
                    with redacted.crop((x0, y0, x1, y1)) as crop:
                        assert crop.getextrema() == ((64, 64),) * 3
        finally:
            redacted.close()
    finally:
        source.close()


def test_clinical_frequency_after_protocol_heading_is_not_an_identifier():
    text = "Protocollo:\nOgni 8 ore per 7 giorni; somministrare 500 mg"
    value_start = text.index("Ogni")
    page = PageResult(
        "clinical-after-protocol",
        "clinical-source",
        0,
        text,
        extraction_mode="ocr",
        regions=(
            TextRegion(0, len("Protocollo:"), (10, 10, 160, 30)),
            TextRegion(value_start, len(text), (760, 10, 1180, 30)),
        ),
    )
    analysis = analyze_text([page], ner_disabled_reason="synthetic_test")

    assert not any(
        page.text[span.start : span.end] in {"8 ore", "7 giorni", "500 mg"}
        and span.kind == Kind.CASE_NUMBER
        for span in analysis.candidates
    )
    assert "Ogni 8 ore per 7 giorni; somministrare 500 mg" in analysis.result.pages[0].text
