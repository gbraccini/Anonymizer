import pytest

from anonymizer.detect.repeated import detect_person_repetitions
from anonymizer.model import Kind, PageResult, Span, Validation
from anonymizer.text_pipeline import analyze_text


def test_exact_fullname_propagates_only_within_source_and_original_offsets():
    first = PageResult("a", "source", 0, "Paziente: Zo\u00eb D'\u00c1vori")
    observed = "Zoe\u0308 D\u2019\u00c1vori"
    second = PageResult(
        "b", "source", 1, "\U0001f600 " + observed + "; D'\u00c1vori; Zo\u00eb D'Avori"
    )
    other = PageResult("c", "other", 0, observed)
    result = analyze_text([first, second, other])
    repeated = [s for s in result.candidates if s.origin == "context:person_repeat"]
    assert [second.text[s.start : s.end] for s in repeated if s.page_id == "b"] == [observed]
    assert not any(s.page_id == "c" for s in repeated)
    assert all(s.entity_id is None for s in repeated)
    assert observed not in result.result.pages[1].text
    assert result.result.pages[2].text == observed


@pytest.mark.parametrize(
    "origin,reason,value",
    [
        ("ner:gliner", "", "Mario Vallerin"),
        ("dictionary:person", "", "Mario Vallerin"),
        ("context:patient_field", "", "Maria Teresa"),
        ("layout:patient_field", "", "Maria Teresa"),
        ("layout:patient_name", "explicit_spatial_label_fragment", "Mario Vallerin"),
        ("context:doctor", "", "M. Vallerin"),
        ("context:patient_name", "", "De Santis"),
    ],
)
def test_untrusted_initials_components_and_layout_fragments_never_seed(origin, reason, value):
    page = PageResult("p", "s", 0, value + "; " + value)
    seed = Span(
        "p", 0, len(value), Kind.PERSON, 1, origin, validation=Validation("unchecked", reason)
    )
    assert detect_person_repetitions([page], [seed]) == []


def test_repeat_whitespace_bounds_and_conflicting_kind_are_conservative():
    name = "Elena Vitali"
    page = PageResult(
        "p", "s", 0, name + "; Elena\r\n Vitali; Elena\n\nVitali; Vitali Elena; E1ena Vitali"
    )
    seeds = [
        Span(
            "p",
            0,
            len(name),
            kind,
            1,
            origin,
            validation=Validation("unchecked", "explicit_spatial_label"),
        )
        for kind, origin in [(Kind.DOCTOR, "context:doctor"), (Kind.PERSON, "context:patient_name")]
    ]
    found = detect_person_repetitions([page], seeds)
    assert [page.text[s.start : s.end] for s in found] == [name, "Elena\r\n Vitali", "Vitali Elena"]
    assert all(s.kind == Kind.PERSON for s in found)


def test_separate_given_name_value_is_not_propagated_as_fullname():
    pages = [
        PageResult("a", "s", 0, "Nome: Maria Teresa Cognome: Vallerin"),
        PageResult("b", "s", 1, "Maria Teresa; Vallerin"),
    ]
    result = analyze_text(pages)
    assert not any(s.origin == "context:person_repeat" for s in result.candidates)


def test_unicode_dash_names_repeat_without_ocr_or_spelling_changes():
    first = PageResult("a", "s", 0, "Paziente: Anne\u2013Marie D\u2019\u00c1vori")
    second = PageResult("b", "s", 1, "Anne-Marie D'\u00c1vori; Anne Marie D'\u00c1vori")
    result = analyze_text([first, second])
    assert [
        second.text[s.start : s.end]
        for s in result.candidates
        if s.page_id == "b" and s.origin == "context:person_repeat"
    ] == ["Anne-Marie D'\u00c1vori"]


def test_invalid_unknown_seed_metadata_is_ignored():
    page = PageResult("p", "s", 0, "Mario Vallerin")
    seeds = [
        Span("p", 0, 14, Kind.PERSON, 1, "context:patient_name"),
        Span(
            "missing",
            0,
            14,
            Kind.PERSON,
            1,
            "context:patient_name",
            validation=Validation("unchecked", "explicit_patient_name_label"),
        ),
        Span(
            "p",
            0,
            99,
            Kind.PERSON,
            1,
            "context:patient_name",
            validation=Validation("unchecked", "explicit_patient_name_label"),
        ),
    ]
    assert detect_person_repetitions([page], seeds) == []


@pytest.mark.parametrize("precomputed", [False, True])
def test_model_name_on_later_page_masks_all_repetitions_and_preserves_other_sources(precomputed):
    from dataclasses import replace

    from anonymizer.model import TextRegion
    from anonymizer.ner_model import NerAudit
    from anonymizer.redact import apply_redactions, propose_redactions
    from anonymizer.visual_model import SourcePageGeometry

    Image = pytest.importorskip("PIL.Image")
    values = ["VALLERIN ZOE", "Zoe Vallerin", "Zoe\nVallerin"]
    pages = [
        PageResult(
            str(index),
            "report",
            index,
            value + "\nGlucosio 90 mg/dL",
            regions=(TextRegion(0, len(value), (10, 10, 180, 30)),),
        )
        for index, value in enumerate(values)
    ]
    pages.append(PageResult("other", "another-report", 0, "Zoe Vallerin"))

    class Ner:
        audit = NerAudit(reason="synthetic")

        def detect(self, text, page_id):
            if page_id != "1":
                return []
            return [Span(page_id, 0, len(values[1]), Kind.PERSON, 3, "ner:gliner", confidence=0.97)]

    ner = Ner()
    cached = {page.page_id: ner.detect(page.text, page.page_id) for page in pages}
    result = analyze_text(pages, ner=ner, ner_candidates=cached if precomputed else None)
    for page, output in zip(pages[:3], result.result.pages[:3], strict=True):
        assert values[page.index] not in output.text
        assert "Glucosio 90 mg/dL" in output.text
        geometry = SourcePageGeometry(200, 100, 200, 100, 72)
        masks, _, required = propose_redactions(page, result.merged_spans, geometry)
        assert masks and required
        with Image.new("RGB", (200, 100), "white") as image:
            with apply_redactions(
                image, tuple(replace(mask, confirmed=True) for mask in masks), geometry
            ) as redacted:
                assert redacted.getpixel((80, 20)) == (0, 0, 0)
                assert redacted.getpixel((80, 60)) == (255, 255, 255)
    assert result.result.pages[3].text == "Zoe Vallerin"
    repeated = [s for s in result.candidates if s.origin == "ner:person_repeat"]
    assert {s.page_id for s in repeated} == {"0", "2"}
    assert all(s.level == 3 and s.confidence == 0.97 for s in repeated)


@pytest.mark.parametrize(
    "value,prefix,confidence",
    [
        ("Zoe Vallerin", "", 0.89),
        ("Vallerin", "", 0.99),
        ("Z. Vallerin", "", 0.99),
        ("Maria Teresa", "Nome: ", 0.99),
        ("De Santis", "Cognome: ", 0.99),
        ("PROTEINA REATTIVA", "", 0.99),
    ],
)
def test_model_repetition_requires_strong_complete_name_evidence(value, prefix, confidence):
    first = PageResult("first", "s", 0, prefix + value)
    second = PageResult("second", "s", 1, value)
    seed = Span(
        "first", len(prefix), len(first.text), Kind.PERSON, 3, "ner:gliner", confidence=confidence
    )
    assert detect_person_repetitions([first, second], [seed]) == []


def test_three_page_pdf_export_masks_name_when_model_only_finds_first_page(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    from test_visual_export import pdf_input

    from anonymizer.export import export_document
    from anonymizer.manifest import confirm_review
    from anonymizer.ner_model import NerAudit
    from anonymizer.pipeline import analyze_documents

    name = "Zoe Vallerin"
    source = pdf_input(name, "VALLERIN ZOE", name)

    class Ner:
        audit = NerAudit(reason="synthetic")
        calls = 0

        def detect(self, text, page_id):
            self.calls += 1
            if self.calls != 1:
                return []
            start = text.index(name)
            return [
                Span(
                    page_id, start, start + len(name), Kind.PERSON, 3, "ner:gliner", confidence=0.97
                )
            ]

    analysis = analyze_documents((source,), dpi=72, ner=Ner())
    assert len(analysis.manifest.pages) == 3
    output = tmp_path / "redacted.pdf"
    export_document((source,), confirm_review(analysis.manifest), output)
    reader = pypdf.PdfReader(output)
    assert len(reader.pages) == 3
    for expected, exported in zip(analysis.manifest.pages, reader.pages, strict=True):
        assert expected.redactions
        assert exported.extract_text() == ""
        image = list(exported.images)[0].image
        for mask in expected.redactions:
            left, top = mask.polygon[0]
            right, bottom = mask.polygon[2]
            with image.crop((left, top, right, bottom)) as region:
                assert region.getextrema() == ((0, 0), (0, 0), (0, 0))
