import hashlib
import json
import re
from pathlib import Path

import pytest

from anonymizer.detect.clinical import clinical_rules, protected_clinical_spans
from anonymizer.detect.context import detect_doctors, detect_patient_labels
from anonymizer.detect.ner import GLiNERDetector
from anonymizer.model import Kind, PageResult, TextRegion
from anonymizer.ner_model import NerAudit, NerConfig
from anonymizer.patient import KnownIdentity, KnownValue
from anonymizer.text_pipeline import analyze_text

CASES = json.loads((Path(__file__).parent / "fixtures/clinical_it_cases.json").read_text("utf-8"))


class Backend:
    model_id = "synthetic/clinical"
    revision = "test"
    artifact_sha256 = "a" * 64
    library_version = "test"
    word_limit = 128
    subword_limit = 256
    max_width = 12

    def __init__(self, target):
        self.target = target

    def split(self, text):
        return [(m.group(), m.start(), m.end()) for m in re.finditer(r"\S+", text)]

    def token_count(self, words):
        return len(words) + 5

    def predict(self, text, threshold):
        return [
            dict(start=m.start(), end=m.end(), text=m.group(), label="person", score=0.9)
            for m in re.finditer(re.escape(self.target), text)
        ]


def detector(target):
    return GLiNERDetector(NerConfig(Path("unused")), backend=Backend(target))


@pytest.mark.parametrize("case", CASES["safe"])
def test_safe_italian_patterns_suppress_only_contained_ner(case):
    text, target = case["text"], case["target"]
    assert detector(target).detect(text, "p") == []
    assert protected_clinical_spans(text)
    extended = text + " Mario Astravelli"
    assert detector(extended).detect(extended, "p")


@pytest.mark.parametrize("case", CASES["not_safe"])
def test_clinical_patterns_keep_names_and_unsupported_contexts(case):
    assert detector(case["target"]).detect(case["text"], "p")


@pytest.mark.parametrize("case", CASES["sensitive"])
def test_sensitive_labels_detect_unicode_fullnames_with_provenance(case):
    text = "\U0001f600 " + case["text"]
    function = detect_doctors if case["kind"] == "DOCTOR" else detect_patient_labels
    spans = function(text, "p")
    assert [(text[s.start : s.end], s.kind) for s in spans] == [(case["target"], case["kind"])]
    assert spans[0].entity_id is None and spans[0].level == 1
    assert spans[0].validation.reason.startswith("clinical_it_label:")


@pytest.mark.parametrize("text", CASES["not_sensitive"])
def test_sensitive_labels_do_not_capture_narrative_or_empty_fields(text):
    assert detect_doctors(text, "p") == []
    assert detect_patient_labels(text, "p") == []


@pytest.mark.parametrize("name", ["Da Silva Maria", "Da Riva Paolo", "Al Faridi Sara"])
@pytest.mark.parametrize("uppercase", [False, True])
@pytest.mark.parametrize(
    "label,kind", [("Paziente:", Kind.PERSON), ("Medico curante:", Kind.DOCTOR)]
)
def test_sensitive_labels_allow_leading_surname_particles(name, uppercase, label, kind):
    name = name.upper() if uppercase else name
    text = label + " " + name
    function = detect_doctors if kind == Kind.DOCTOR else detect_patient_labels
    spans = function(text, "p")
    assert [(text[s.start : s.end], s.kind) for s in spans] == [(name, kind)]


@pytest.mark.parametrize(
    "text",
    [
        "PAZIENTE: DA VALUTARE DOMANI",
        "Paziente: da definire",
        "PAZIENTE: DA RIPETERE DOMANI",
        "PAZIENTE: DA RIFERIRE DOMANI",
    ],
)
def test_leading_da_infinitive_is_not_a_declared_fullname(text):
    assert detect_patient_labels(text, "p") == []


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_headings_are_whole_lines_across_newline_encodings(newline):
    text = "Prima" + newline + "RISULTATI:" + newline + "Mario Astravelli"
    assert detector("RISULTATI").detect(text, "p") == []
    assert detector("Mario Astravelli").detect(text, "p")
    assert detector("RISULTATI: Mario Astravelli").detect("RISULTATI: Mario Astravelli", "p")


def test_safe_rules_never_override_explicit_known_identity_or_new_label():
    text = "Valutazione e piano"
    known = KnownIdentity((KnownValue(Kind.PERSON, text),), role="patient", confirmed=True)
    result = analyze_text([PageResult("p", "s", 0, text)], (known,), ner=detector(text))
    assert any(s.level == 0 for s in result.candidates)
    assert text not in result.result.pages[0].text
    text = "Medico curante Marco Paoli"
    result = analyze_text([PageResult("p", "s", 0, text)], ner=detector("medico curante"))
    assert any(s.kind == Kind.DOCTOR and s.level == 1 for s in result.candidates)
    assert "Marco Paoli" not in result.result.pages[0].text
    assert result.ner_audit.clinical_guard_version == "clinical_context_v6"
    assert NerAudit(clinical_guard_version="clinical_context_v4")


def test_rules_have_verified_upstream_mappings_and_explicit_local_extensions():
    data = clinical_rules()
    assert data["revision"] == "4da3cf31c9bfbfd66c66b141c45ba7a47628dd0a"
    root = Path("build/artifacts/philter-upstream")
    for rule in data["rules"]:
        assert rule["sources"] and rule["adaptation"]
        for name in rule["sources"]:
            source = data["sources"][name]
            assert len(source["sha256"]) == 64 and source["original_pattern"]
            if root.is_dir():
                path = next(root.rglob(name))
                assert hashlib.sha256(path.read_bytes()).hexdigest() == source["sha256"]
    heading = next(r for r in data["rules"] if r["id"] == "document_section_heading")
    assert heading["adaptation_type"] == "local_extension"


def test_new_sensitive_label_geometry_and_redacted_text_are_synchronized():
    pytest.importorskip("PIL")
    from anonymizer.redact import propose_redactions
    from anonymizer.visual_model import SourcePageGeometry, VisualPage
    from anonymizer.web.text import page_text

    text = "Paziente: Lucia De Santis\nEmoglobina 12,5 g/dL"
    start, end = text.index("Lucia"), text.index("\n")
    page = PageResult(
        "p",
        "s",
        0,
        text,
        regions=(
            TextRegion(0, start, (0, 0, 40, 10)),
            TextRegion(start, end, (50, 0, 150, 10)),
            TextRegion(end + 1, len(text), (0, 30, 180, 40)),
        ),
    )
    result = analyze_text([page], ner=detector("12,5 g/dL"))
    geometry = SourcePageGeometry(200, 80, 200, 80, 72)
    masks, warnings, required = propose_redactions(page, list(result.merged_spans), geometry)
    assert len(masks) == 1 and not warnings
    redacted = page_text(VisualPage(page, 0, geometry, masks, required_candidate_ids=required))
    assert "Lucia De Santis" not in redacted["redacted"]
    assert "Emoglobina 12,5 g/dL" in redacted["redacted"]
