from __future__ import annotations

import re
from pathlib import Path

import pytest

from anonymizer.detect.context import detect_contact_details
from anonymizer.detect.known import detect_known
from anonymizer.detect.layout import detect_layout_fields, protected_layout_spans
from anonymizer.detect.ner import GLiNERDetector
from anonymizer.model import Kind, PageResult, TextRegion
from anonymizer.ner_model import LABELS, NerAudit, NerConfig
from anonymizer.patient import KnownIdentity, KnownValue
from anonymizer.redact import propose_redactions
from anonymizer.text_pipeline import analyze_text
from anonymizer.visual_model import SourcePageGeometry, VisualPage
from anonymizer.web.text import page_text


def _matches(text, spans, kind):
    return [text[span.start : span.end] for span in spans if span.kind == kind]


def test_complete_address_components_are_found_and_clinical_content_is_preserved():
    text = (
        "Centro Analisi: Aurora Lab S.r.l.\n"
        "Via delle Rose, 18, 20100 Firenze\n"
        "Terapia: assumere per via orale; glicemia 92 mg/dL."
    )
    page = PageResult("p", "s", 0, text)
    analysis = analyze_text([page])
    assert "Via delle Rose, 18" in _matches(text, analysis.candidates, Kind.ADDRESS)
    assert "20100" in _matches(text, analysis.candidates, Kind.POSTCODE)
    assert "Firenze" in _matches(text, analysis.candidates, Kind.LOCATION)
    redacted = analysis.result.pages[0].text
    assert "assumere per via orale" in redacted
    assert "glicemia 92 mg/dL" in redacted


def test_clinical_routes_and_unassociated_city_are_not_address_candidates():
    text = "Somministrare per via orale. Dolore riferito a Firenze; controllo pressorio."
    spans = detect_contact_details(text, "p")
    assert not any(span.kind in {Kind.ADDRESS, Kind.POSTCODE, Kind.LOCATION} for span in spans)


@pytest.mark.parametrize(
    ("canonical", "observed"),
    [
        ("Luca D'Angelo", "Luca D’Angelo"),
        ("Anna-Maria Rossi", "Anna–Maria Rossi"),
        ("Jean-Luc D'Angelo", "Jean‑Luc D’Angelo"),
    ],
)
def test_known_name_unicode_apostrophe_and_dash_variants_keep_original_offsets(
    canonical, observed
):
    text = f"🙂 Paziente: {observed} — Hb 12 g/dL"
    identity = KnownIdentity((KnownValue(Kind.PERSON, canonical),), confirmed=True)
    matches = [span for span in detect_known(text, "p", (identity,)) if span.kind == Kind.PERSON]
    assert len(matches) == 1
    span = matches[0]
    assert (span.start, span.end) == (text.index(observed), text.index(observed) + len(observed))
    assert text[span.start : span.end] == observed
    assert span.entity_id == identity.id and span.level == 0


def _layout_page():
    text = (
        "Medico curante: Elodie D’Angelo\n"
        "Paziente: Rossi Demo\n"
        "Glicemia: 92 mg/dL"
    )
    fragments = (
        ("Medico curante:", (10, 10, 105, 20)),
        ("Elodie D’Angelo", (120, 10, 220, 20)),
        ("Paziente:", (10, 34, 70, 44)),
        ("Rossi Demo", (95, 34, 170, 44)),
        ("Glicemia: 92 mg/dL", (330, 34, 470, 44)),
    )
    regions = tuple(
        TextRegion(text.index(value), text.index(value) + len(value), box)
        for value, box in fragments
    )
    return PageResult("layout-p", "layout-s", 0, text, regions=regions)


def test_layout_fields_use_nearby_geometry_and_preserve_adjacent_result():
    page = _layout_page()
    fields = detect_layout_fields(page)
    assert (Kind.DOCTOR, "Elodie D’Angelo") in {
        (span.kind, page.text[span.start : span.end]) for span in fields
    }
    assert (Kind.PERSON, "Rossi Demo") in {
        (span.kind, page.text[span.start : span.end]) for span in fields
    }
    assert all(span.entity_id is None and span.level in (1, 2) for span in fields)
    analysis = analyze_text([page])
    assert "Glicemia: 92 mg/dL" in analysis.result.pages[0].text


def _spatial_label_page(*, char_boxes: bool):
    text = "Paziente:\nRossi\nGlicemia 92 mg/dL\nDemo"
    fragments = (
        ("Paziente:", (10, 10, 90, 20)),
        ("Rossi", (130, 10, 170, 20)),
        ("Glicemia 92 mg/dL", (10, 35, 155, 45)),
        ("Demo", (180, 10, 220, 20)),
    )
    regions = []
    for value, box in fragments:
        start = text.index(value)
        if char_boxes:
            width = (box[2] - box[0]) / len(value)
            regions.extend(
                TextRegion(
                    start + index,
                    start + index + 1,
                    (box[0] + index * width, box[1], box[0] + (index + 1) * width, box[3]),
                )
                for index in range(len(value))
                if not value[index].isspace()
            )
        else:
            regions.append(TextRegion(start, start + len(value), box))
    return PageResult(
        "spatial-p",
        "spatial-s",
        0,
        text,
        extraction_mode="pdf_native" if char_boxes else "ocr",
        regions=tuple(regions),
    )


@pytest.mark.parametrize("char_boxes", [False, True], ids=["ocr-word-boxes", "pdf-char-boxes"])
def test_split_name_regions_do_not_mask_interposed_clinical_result(char_boxes):
    page = _spatial_label_page(char_boxes=char_boxes)
    fields = detect_layout_fields(page)
    field_texts = {page.text[span.start : span.end] for span in fields}
    assert {"Rossi", "Demo"} <= field_texts
    assert not any("Glicemia" in value for value in field_texts)

    analysis = analyze_text([page])
    geometry = SourcePageGeometry(500, 100, 500, 100, 72)
    masks, warnings, _ = propose_redactions(page, list(analysis.merged_spans), geometry)
    assert not warnings
    view = VisualPage(page, 0, geometry, masks)
    redacted = page_text(view)["redacted"]
    assert "Glicemia 92 mg/dL" in redacted
    assert "Rossi" not in redacted and "Demo" not in redacted


class _TinyBackend:
    model_id = "synthetic/external-rules"
    revision = "synthetic"
    artifact_sha256 = "a" * 64
    library_version = "test"
    word_limit = 32
    subword_limit = 64
    max_width = 4

    def split(self, text):
        return [
            (match.group(), match.start(), match.end())
            for match in re.finditer(r"\w+|[^\w\s]", text)
        ]

    def token_count(self, words):
        return len(words) + 4

    def predict(self, text, threshold):
        return [
            {
                "start": match.start(),
                "end": match.end(),
                "text": match.group(),
                "label": "person",
                "score": 0.95,
            }
            for match in re.finditer(r"Medico curante", text, re.IGNORECASE)
        ]


def test_l3_protected_layout_label_does_not_discard_known_l0_candidate():
    page = _layout_page()
    label = "Medico curante"
    expected_label_span = (page.text.index(label), page.text.index(label) + len(label))
    protected_label_end = expected_label_span[1] + 1  # the exact source label includes ':'
    protected = protected_layout_spans(page)
    assert any(
        start <= expected_label_span[0] and end >= protected_label_end and kind == Kind.PERSON
        for start, end, kind in protected
    )

    identity = KnownIdentity((KnownValue(Kind.PERSON, label),), confirmed=True)
    detector = GLiNERDetector(NerConfig(Path("unused")), backend=_TinyBackend())
    baseline = analyze_text([page], identities=(identity,))
    analysis = analyze_text([page], identities=(identity,), ner=detector)
    baseline_candidates = {
        (span.start, span.end, span.kind, span.level, span.origin)
        for span in baseline.candidates
    }
    assert baseline_candidates <= {
        (span.start, span.end, span.kind, span.level, span.origin) for span in analysis.candidates
    }
    same_interval = [
        span
        for span in analysis.candidates
        if (span.start, span.end) == expected_label_span and span.kind == Kind.PERSON
    ]
    assert any(span.level == 0 and span.origin.startswith("known:") for span in same_interval)
    assert not any(span.level == 3 for span in same_interval)


@pytest.mark.parametrize("char_boxes", [False, True], ids=["ocr-word-boxes", "pdf-char-boxes"])
def test_column_order_keeps_patient_and_refertante_distinct_and_glucose_visible(char_boxes):
    text = "Paziente:\nGlicemia 92 mg/dL\nRossi Demo\nRefertante:\nSara Bianchi"
    fragments = (
        ("Paziente:", (10, 10, 90, 20)),
        ("Glicemia 92 mg/dL", (10, 35, 155, 45)),
        ("Rossi Demo", (130, 10, 205, 20)),
        ("Refertante:", (400, 10, 475, 20)),
        ("Sara Bianchi", (500, 10, 585, 20)),
    )
    regions = []
    for value, box in fragments:
        start = text.index(value)
        if char_boxes:
            width = (box[2] - box[0]) / len(value)
            regions.extend(
                TextRegion(
                    start + index,
                    start + index + 1,
                    (box[0] + index * width, box[1], box[0] + (index + 1) * width, box[3]),
                )
                for index, char in enumerate(value)
                if not char.isspace()
            )
        else:
            regions.append(TextRegion(start, start + len(value), box))
    page = PageResult(
        "columns-p",
        "columns-s",
        0,
        text,
        extraction_mode="pdf_native" if char_boxes else "ocr",
        regions=tuple(regions),
    )
    fields = detect_layout_fields(page)
    detected = {(span.kind, page.text[span.start : span.end]) for span in fields}
    assert (Kind.PERSON, "Rossi Demo") in detected
    assert (Kind.DOCTOR, "Sara Bianchi") in detected
    assert (Kind.PERSON, "Sara Bianchi") not in detected
    analysis = analyze_text([page])
    assert "Glicemia 92 mg/dL" in analysis.result.pages[0].text


def test_empty_patient_column_does_not_capture_name_from_distant_refertante_column():
    text = "Paziente:\nRefertante:\nSara Bianchi"
    fragments = (
        ("Paziente:", (10, 10, 90, 20)),
        ("Refertante:", (400, 10, 475, 20)),
        ("Sara Bianchi", (500, 10, 585, 20)),
    )
    regions = tuple(
        TextRegion(text.index(value), text.index(value) + len(value), box)
        for value, box in fragments
    )
    page = PageResult("empty-p", "empty-s", 0, text, regions=regions)
    fields = detect_layout_fields(page)
    assert (Kind.DOCTOR, "Sara Bianchi") in {
        (span.kind, text[span.start : span.end]) for span in fields
    }
    assert (Kind.PERSON, "Sara Bianchi") not in {
        (span.kind, text[span.start : span.end]) for span in fields
    }


def test_prior_clinical_guard_audit_v5_remains_readable():
    audit = NerAudit(
        status="ready",
        reason="configured_local_model",
        backend="gliner",
        model_id="synthetic/model",
        revision="synthetic-revision",
        artifact_sha256="a" * 64,
        library_version="synthetic-version",
        threshold=0.5,
        labels=LABELS,
        word_limit=512,
        subword_limit=512,
        max_width=12,
        window_words=256,
        overlap_words=11,
        clinical_guard_version="clinical_context_v5",
        runtime="onnx",
        runtime_version="synthetic-runtime",
        provider="CPUExecutionProvider",
        precision="fp32",
        cpu_threads=4,
    )
    assert audit.clinical_guard_version == "clinical_context_v5"
