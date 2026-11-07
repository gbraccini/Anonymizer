import pytest

from anonymizer.detect.layout import analyze_layout_fields, detect_layout_fields
from anonymizer.model import Kind, PageResult, Span, TextRegion
from anonymizer.ner_model import NerAudit
from anonymizer.text_pipeline import analyze_text, detect_page_ner


def page_parts(parts, *, chars=False, scale=1):
    text = "\U0001f600 "
    regions = []
    for value, box in parts:
        start = len(text)
        text += value + "\n"
        box = tuple(v * scale for v in box)
        if chars:
            width = (box[2] - box[0]) / len(value)
            regions.extend(
                TextRegion(
                    start + i,
                    start + i + 1,
                    (box[0] + i * width, box[1], box[0] + (i + 1) * width, box[3]),
                )
                for i in range(len(value))
                if not value[i].isspace()
            )
        else:
            regions.append(TextRegion(start, start + len(value), box))
    return PageResult("p", "s", 0, text, regions=tuple(regions))


@pytest.mark.parametrize("chars", [False, True])
@pytest.mark.parametrize("scale", [0.5, 3])
def test_spatial_names_exclude_interposed_reading_order_text(chars, scale):
    page = page_parts(
        [
            ("Paziente:", (10, 10, 70, 20)),
            ("Hb 12 g/dL", (300, 10, 380, 20)),
            ("Zo\u00eb", (80, 10, 100, 20)),
            ("D\u2019\u00c1vori", (110, 10, 160, 20)),
        ],
        chars=chars,
        scale=scale,
    )
    found = detect_layout_fields(page)
    assert [page.text[s.start : s.end] for s in found] == ["Zo\u00eb\nD\u2019\u00c1vori"]
    assert all(s.kind == Kind.PERSON and s.level == 1 and s.entity_id is None for s in found)
    assert "Hb 12 g/dL" not in "".join(page.text[s.start : s.end] for s in found)


def test_noncontiguous_original_offsets_never_include_clinical_text():
    page = page_parts(
        [
            ("Medico curante:", (10, 10, 100, 20)),
            ("Elena", (110, 10, 145, 20)),
            ("Glucosio 90", (300, 10, 390, 20)),
            ("Vitali", (150, 10, 190, 20)),
        ]
    )
    found = detect_layout_fields(page)
    assert [page.text[s.start : s.end] for s in found] == ["Elena", "Vitali"]
    assert all(s.kind == Kind.DOCTOR for s in found)


@pytest.mark.parametrize("x,y", [(10, 30), (14, 32)])
def test_below_label_with_coarse_fullname_region(x, y):
    page = page_parts(
        [("Firmato da:", (10, 10, 100, 20)), ("Lucia De Santis", (x, y, x + 100, y + 10))]
    )
    assert [page.text[s.start : s.end] for s in detect_layout_fields(page)] == ["Lucia De Santis"]


@pytest.mark.parametrize(
    "value,box",
    [
        ("Mario Vallerin", (300, 30, 400, 40)),
        ("Mario Vallerin", (10, 200, 100, 210)),
        ("IN BUONE CONDIZIONI", (80, 10, 200, 20)),
        ("CENTRO AUTORIZZATO", (80, 10, 200, 20)),
    ],
)
def test_distant_columns_and_clinical_states_not_names(value, box):
    page = page_parts([("Paziente:", (10, 10, 70, 20)), (value, box)])
    assert detect_layout_fields(page) == []


def test_label_protection_applies_to_fresh_and_cached_l3_only():
    page = page_parts([("Paziente:", (10, 10, 70, 20)), ("Elena Vitali", (80, 10, 160, 20))])
    label = page.text.index("Paziente")
    name = page.text.index("Elena")

    class Fake:
        audit = NerAudit()

        def detect(self, text, page_id):
            return [
                Span(page_id, label, label + 8, Kind.PERSON, 3, "ner:fake"),
                Span(page_id, name, name + 11, Kind.PERSON, 3, "ner:fake"),
            ]

    fake = Fake()
    assert len(detect_page_ner(page, fake)) == 2
    fresh = analyze_text([page], ner=fake)
    assert not any(s.origin == "ner:fake" and s.start == label for s in fresh.candidates)
    cached = {"p": fake.detect(page.text, "p")}
    result = analyze_text([page], ner=fake, ner_candidates=cached)
    assert not any(s.origin == "ner:fake" and s.start == label for s in result.candidates)
    assert any(s.origin == "layout:patient_name" for s in result.candidates)
    detected, protected = analyze_layout_fields(page)
    assert detected and any(a <= label < label + 8 <= b for a, b, _ in protected)


@pytest.mark.parametrize("chars", [False, True])
def test_layout_pairs_separate_fields_without_reading_order_assumptions(chars):
    page = page_parts(
        [
            ("Cognome:", (10, 10, 70, 20)),
            ("Hb 12 g/dL", (400, 10, 490, 20)),
            ("Vallerin", (80, 10, 140, 20)),
            ("Nome:", (10, 35, 50, 45)),
            ("Lucia", (60, 35, 100, 45)),
        ],
        chars=chars,
    )
    found = [s for s in detect_layout_fields(page) if s.origin == "layout:patient_field"]
    assert [page.text[s.start : s.end] for s in found] == ["Vallerin", "Lucia"]


def test_layout_coarse_cells_support_paired_fields_but_not_remote_columns():
    page = page_parts(
        [("Cognome: Vallerin", (10, 10, 140, 20)), ("Nome: Lucia", (10, 35, 110, 45))]
    )
    assert [page.text[s.start : s.end] for s in detect_layout_fields(page)] == ["Vallerin", "Lucia"]
    page = page_parts(
        [("Cognome: Vallerin", (10, 10, 140, 20)), ("Nome: Lucia", (500, 35, 600, 45))]
    )
    assert detect_layout_fields(page) == []


def test_layout_initials_detected_after_explicit_doctor_field_only():
    page = page_parts([("Refertante:", (10, 10, 90, 20)), ("M. De Santis", (100, 10, 180, 20))])
    found = detect_layout_fields(page)
    assert [page.text[s.start : s.end] for s in found] == ["M. De Santis"]
    assert found[0].kind == Kind.DOCTOR


def test_fragmented_layout_names_cannot_become_repeat_seeds():
    page = page_parts(
        [
            ("Paziente:", (10, 10, 70, 20)),
            ("Maria Teresa", (80, 10, 150, 20)),
            ("Hb 12", (400, 10, 450, 20)),
            ("Vallerin", (160, 10, 210, 20)),
        ]
    )
    found = detect_layout_fields(page)
    assert len(found) == 2
    assert all(s.validation.reason == "explicit_spatial_label_fragment" for s in found)


def test_final_pipeline_cannot_pair_remote_columns_via_linear_text():
    page = page_parts(
        [("Cognome: Vallerin", (10, 10, 140, 20)), ("Nome: Lucia", (500, 10, 600, 20))]
    )
    result = analyze_text([page])
    assert not any(s.origin.endswith("patient_field") for s in result.candidates)


def test_coarse_single_region_contains_both_explicit_fields():
    page = page_parts([("Cognome: Vallerin Nome: Lucia", (10, 10, 250, 20))])
    result = analyze_text([page])
    assert [
        page.text[s.start : s.end] for s in result.candidates if s.origin == "layout:patient_field"
    ] == ["Vallerin", "Lucia"]


def test_ambiguous_three_nearby_fields_do_not_pair_unidirectionally():
    page = page_parts(
        [
            ("Nome: Lucia", (10, 10, 100, 20)),
            ("Cognome: Vallerin", (10, 30, 140, 40)),
            ("Nome: Elena", (10, 50, 100, 60)),
        ]
    )
    result = analyze_text([page])
    assert not any(s.origin.endswith("patient_field") for s in result.candidates)
    assert not any(s.origin == "context:person_repeat" for s in result.candidates)
