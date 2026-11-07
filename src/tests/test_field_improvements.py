from __future__ import annotations

import json
from pathlib import Path

import pytest

from anonymizer.detect.context import detect_doctors, detect_patient_labels
from anonymizer.detect.layout import detect_layout_fields
from anonymizer.detect.repeated import detect_person_repetitions
from anonymizer.model import Kind, PageResult, TextRegion
from anonymizer.redact import propose_redactions
from anonymizer.text_pipeline import analyze_text
from anonymizer.visual_model import SourcePageGeometry, VisualPage
from anonymizer.web.text import page_text

FIXTURE_PATH = Path(__file__).with_name("fixtures") / "field_improvements.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _pages(case):
    pages = []
    for index, record in enumerate(case["pages"]):
        text = record["text"]
        regions = []
        cursor = 0
        for item in record.get("regions", []):
            fragment = item["text"]
            start = text.index(fragment, cursor)
            end = start + len(fragment)
            cursor = end
            regions.append(TextRegion(start, end, tuple(item["box"])))
        pages.append(
            PageResult(
                f"{case['id']}-p{index}",
                record.get("source_id", case["source_id"]),
                index,
                text,
                extraction_mode="pdf_native" if regions else "text",
                regions=tuple(regions),
            )
        )
    return pages


def _case(case_id):
    return next(case for case in FIXTURE["cases"] if case["id"] == case_id)


def _assert_expected(record, page, spans):
    for expected in record.get("expected_values", []):
        assert any(
            span.page_id == page.page_id
            and
            span.kind == Kind(expected["kind"])
            and page.text[span.start : span.end] == expected["text"]
            for span in spans
        ), (record, expected)
    for forbidden in record.get("forbidden_values", []):
        assert not any(
            span.page_id == page.page_id
            and
            span.kind == Kind(forbidden["kind"])
            and page.text[span.start : span.end] == forbidden["text"]
            and span.origin.startswith(forbidden["origin_prefix"])
            for span in spans
        ), (record, forbidden)


@pytest.mark.parametrize(
    "case_id",
    ["paired_fields_same_row", "paired_fields_reversed_order"],
)
def test_explicit_cognome_nome_pairs_use_geometry_without_masking_results(case_id):
    case = _case(case_id)
    page = _pages(case)[0]
    fields = detect_layout_fields(page)
    _assert_expected(case["pages"][0], page, fields)
    analysis = analyze_text([page])
    for value in case["pages"][0]["preserve"]:
        assert value in analysis.result.pages[0].text

    geometry = SourcePageGeometry(700, 100, 700, 100, 72)
    masks, warnings, required = propose_redactions(page, list(analysis.merged_spans), geometry)
    assert not warnings and required
    redacted = page_text(VisualPage(page, 0, geometry, masks))["redacted"]
    for expected in case["pages"][0]["expected_values"]:
        assert expected["text"] not in redacted
    for value in case["pages"][0]["preserve"]:
        assert value in redacted


def test_initials_after_medical_title_are_detected_with_clinical_text_preserved():
    case = _case("medical_signature_initial")
    page = _pages(case)[0]
    spans = detect_doctors(page.text, page.page_id)
    _assert_expected(case["pages"][0], page, spans)
    analysis = analyze_text([page])
    assert "Hb 12 g/dL" in analysis.result.pages[0].text


def test_person_repetition_is_full_name_seeded_and_limited_to_one_source():
    same_source = _pages(_case("full_name_repeat_same_source"))
    other_case = _pages(_case("repeat_not_cross_source"))
    pages = [*same_source, *other_case]
    seeds = []
    for page in pages:
        seeds.extend(span for span in detect_layout_fields(page) if span.kind == Kind.PERSON)
        # Text-only explicit compound fields are recognized without a model.
        seeds.extend(detect_patient_labels(page.text, page.page_id))
    repeated = detect_person_repetitions(pages, seeds)
    for page, record in zip(
        pages,
        [*_case_records("full_name_repeat_same_source"), *_case_records("repeat_not_cross_source")],
        strict=True,
    ):
        _assert_expected(record, page, [*seeds, *repeated])


def test_initials_and_single_surnames_do_not_seed_cross_page_repetitions():
    pages = _pages(_case("initials_do_not_seed_full_name_repetition"))
    initial = [span for span in detect_doctors(pages[0].text, pages[0].page_id)]
    initial += detect_doctors(pages[1].text, pages[1].page_id)
    repeated = detect_person_repetitions(pages, initial)
    _assert_expected(
        _case("initials_do_not_seed_full_name_repetition")["pages"][0], pages[0], initial
    )
    _assert_expected(
        _case("initials_do_not_seed_full_name_repetition")["pages"][1], pages[1], repeated
    )

    single_surname = PageResult("surname", "source", 0, "Vortani")
    assert detect_person_repetitions([single_surname], []) == []


def test_distant_field_labels_and_clinical_analytes_are_not_person_values():
    case = _case("clinical_labels_are_not_names")
    page = _pages(case)[0]
    fields = detect_layout_fields(page)
    _assert_expected(case["pages"][0], page, fields)
    assert not any(
        span.kind == Kind.PERSON and page.text[span.start : span.end] in {"Albumina", "Creatinina"}
        for span in fields
    )
    analysis = analyze_text([page])
    assert "Albumina 4.2 g/dL" in analysis.result.pages[0].text


def test_similar_names_are_neither_fused_nor_propagated_as_one_name():
    case = _case("similar_fullnames_not_fused")
    page = _pages(case)[0]
    analysis = analyze_text([page])
    _assert_expected(case["pages"][0], page, analysis.candidates)
    assert not any(
        "Selene Vortani\nSelene Vortanì" in page.text[span.start : span.end]
        for span in analysis.candidates
    )
    assert "Glucosio 88 mg/dL" in analysis.result.pages[0].text


def test_given_name_alone_does_not_seed_repetition():
    pages = [
        PageResult("given-only-0", "given-only-source", 0, "Nome: Maria Teresa"),
        PageResult("given-only-1", "given-only-source", 1, "Maria Teresa\nPotassio 4.1 mmol/L"),
    ]
    seeds = [
        *detect_patient_labels(pages[0].text, pages[0].page_id),
        *detect_layout_fields(pages[0]),
    ]
    repeated = detect_person_repetitions(pages, seeds)
    assert not any(span.origin == "context:person_repeat" for span in repeated)
    assert "Potassio 4.1 mmol/L" in analyze_text(pages).result.pages[1].text


def _case_records(case_id):
    return _case(case_id)["pages"]
