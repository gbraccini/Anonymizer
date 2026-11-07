import hashlib
import importlib.util
import json
import os
import re
from dataclasses import replace
from pathlib import Path

import pytest

from anonymizer.detect.ner import GLiNERDetector, verify_model_artifacts
from anonymizer.model import Kind, PageResult
from anonymizer.ner_model import NerConfig, NerError
from anonymizer.text_pipeline import analyze_text


class FakeBackend:
    model_id = "synthetic/fake"
    revision = "revision"
    artifact_sha256 = "a" * 64
    library_version = "test"
    word_limit = 8
    subword_limit = 12
    max_width = 3

    def __init__(self, targets=()):
        self.targets = targets
        self.calls = []

    def split(self, text):
        return [(m.group(), m.start(), m.end()) for m in re.finditer(r"\w+|[^\w\s]", text)]

    def token_count(self, words):
        return 4 + len(words)

    def predict(self, text, threshold):
        self.calls.append(text)
        return [
            dict(start=m.start(), end=m.end(), text=m.group(), label=label, score=0.9)
            for target, label in self.targets
            for m in re.finditer(re.escape(target), text)
        ]


def detector(backend=None, **kwargs):
    return GLiNERDetector(NerConfig(Path("unused"), **kwargs), backend=backend or FakeBackend())


def test_windows_cover_boundary_tail_and_unicode_without_duplicates():
    text = "uno due tre quattro cinque sei Zoë Évora otto nove 😀 dieci undici Łukasz Żur dodici"
    backend = FakeBackend((("Zoë Évora", "person"), ("Łukasz Żur", "person")))
    spans = detector(backend).detect(text, "page")
    assert [text[s.start : s.end] for s in spans] == ["Zoë Évora", "Łukasz Żur"]
    assert len(backend.calls) >= 3
    assert all(s.level == 3 and s.entity_id is None for s in spans)
    assert all(backend.token_count([w[0] for w in backend.split(t)]) <= 12 for t in backend.calls)


def test_overlap_duplicate_predictions_are_deduplicated():
    text = "uno due tre quattro cinque sei Ada sette otto nove"
    backend = FakeBackend((("Ada", "person"),))
    assert len(detector(backend).detect(text, "p")) == 1
    assert sum("Ada" in call for call in backend.calls) == 2


@pytest.mark.parametrize(
    "change,code",
    [
        ({"overlap_words": 1}, "overlap"),
        ({"window_words": 2}, "overlap"),
        ({"threshold": float("nan")}, "threshold"),
        ({"max_windows": 0}, "budget"),
    ],
)
def test_invalid_configuration(change, code):
    with pytest.raises(NerError, match=code):
        detector(**change)


def test_budgets_do_not_silently_truncate():
    with pytest.raises(NerError, match="character_limit"):
        detector(max_characters=2).detect("lungo", "p")
    with pytest.raises(NerError, match="window_count_limit"):
        detector(max_windows=1).detect(" ".join(["uno"] * 30), "p")
    backend = FakeBackend()
    backend.subword_limit = 4
    with pytest.raises(NerError, match="single_word"):
        detector(backend).detect("lunghissimo", "p")
    backend.subword_limit = 6
    with pytest.raises(NerError, match="preserve_overlap"):
        detector(backend).detect("uno due tre quattro", "p")


@pytest.mark.parametrize(
    "prediction,code",
    [
        (dict(start=1, end=4, text="Zoë", label="person", score=0.9), "text_mismatch"),
        (dict(start=0, end=40, text="Zoë", label="person", score=0.9), "offsets"),
        (dict(start=0, end=3, text="Zoë", label="date", score=0.9), "label_or_score"),
        (dict(start=0, end=3, text="Zoë", label="person", score=float("nan")), "label_or_score"),
    ],
)
def test_invalid_predictions_fail_closed(prediction, code):
    backend = FakeBackend()
    backend.predict = lambda text, threshold: [prediction]
    with pytest.raises(NerError, match=code):
        detector(backend).detect("Zoë 😀", "p")


def test_empty_threshold_and_backend_failure():
    backend = FakeBackend((("Ada", "person"),))
    d = detector(backend, threshold=0.95)
    assert d.detect("  \n", "p") == []
    assert d.detect("Ada", "p") == []
    backend.predict = lambda *args: (_ for _ in ()).throw(RuntimeError("private text"))
    with pytest.raises(NerError, match="^ner_inference_failed$"):
        d.detect("Ada", "p")


def test_splitter_must_cover_every_original_nonspace_codepoint():
    backend = FakeBackend()
    backend.split = lambda text: [("Ada", 0, 3)]
    with pytest.raises(NerError, match="splitter_coverage"):
        detector(backend).detect("Ada 😀", "p")


def test_duplicate_keeps_highest_score_and_different_labels_remain_distinct():
    backend = FakeBackend()
    backend.predict = lambda text, threshold: [
        dict(start=0, end=3, text="Ada", label=label, score=score)
        for label, score in (("person", 0.6), ("person", 0.9), ("location", 0.8))
    ]
    spans = detector(backend).detect("Ada", "p")
    assert len(spans) == 2
    assert next(s.confidence for s in spans if s.kind == Kind.PERSON) == 0.9


def test_explicit_broken_model_cli_fails_before_output(tmp_path, capsys):
    from anonymizer.cli import main

    source = tmp_path / "input.txt"
    output, mapping = tmp_path / "output.txt", tmp_path / "map.json"
    source.write_text("Synthetic clinical text")
    assert (
        main(
            [
                "anon",
                str(source),
                "--output",
                str(output),
                "--map",
                str(mapping),
                "--ner-model",
                str(tmp_path / "absent"),
            ]
        )
        == 1
    )
    assert not output.exists() and not mapping.exists()
    error = capsys.readouterr().err
    assert "ner_invalid_local_model" in error
    assert str(tmp_path) not in error


def test_pipeline_additive_coverage_and_no_patient_attribution():
    page = PageResult("p", "s", 0, "Email test@example.invalid; Zoë Évora, evento 03/04/2025.")
    baseline = analyze_text([page])
    enhanced = analyze_text([page], ner=detector(FakeBackend((("Zoë Évora", "person"),))))
    old = {(s.start, s.end, s.kind, s.level, s.origin) for s in baseline.candidates}
    assert old <= {(s.start, s.end, s.kind, s.level, s.origin) for s in enhanced.candidates}
    assert enhanced.ner_audit.status == "ready"
    assert any(w.code == "ner_disabled" for w in baseline.result.warnings)
    assert all(s.entity_id is None for s in enhanced.candidates if s.level == 3)
    assert any(s.kind == Kind.DATE for s in enhanced.candidates)


def test_artifact_ledger_hash_and_tamper(tmp_path):
    names = ("gliner_config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json")
    files = {}
    for name in names:
        (tmp_path / name).write_bytes(b"synthetic")
        files[name] = hashlib.sha256(b"synthetic").hexdigest()
    ledger = dict(model_id="synthetic/fake", revision="abc", files=files)
    (tmp_path / "anonymizer_model.json").write_text(json.dumps(ledger))
    assert verify_model_artifacts(tmp_path)[0] == ledger
    (tmp_path / "model.safetensors").write_bytes(b"changed")
    with pytest.raises(NerError, match="hash_mismatch"):
        verify_model_artifacts(tmp_path)


def test_manifest_legacy_requires_new_confirmation_and_audit_changes_digest():
    from test_visual_model import sample

    from anonymizer.manifest import confirm_review, dumps, loads
    from anonymizer.visual_model import review_digest

    approved = confirm_review(sample())
    raw = json.loads(dumps(approved))
    del raw["ner_audit"]
    migrated = loads(json.dumps(raw))
    assert migrated.reviewed_digest is None
    assert migrated.ner_audit.reason == "legacy_manifest_not_recorded"
    confirm_review(migrated)
    with_ner = replace(approved, ner_audit=detector().audit)
    assert review_digest(with_ner) != review_digest(approved)


def test_native_pdf_ner_candidates_become_visual_masks():
    pytest.importorskip("PIL")
    pytest.importorskip("pypdfium2")
    pytest.importorskip("reportlab")
    from test_visual_export import pdf_input

    from anonymizer.pipeline import analyze_documents

    name = "Elvio Veltrani"
    analysis = analyze_documents(
        (pdf_input(name),),
        dpi=72,
        ner=detector(FakeBackend(((name, "person"),))),
    )
    spans = [s for s in analysis.text_analysis.candidates if s.level == 3]
    assert len(spans) == 1
    page = analysis.manifest.pages[0]
    merged = next(s for s in analysis.text_analysis.merged_spans if spans[0] in s.candidates)
    assert any(merged.id in mask.candidate_ids for mask in page.redactions)
    assert analysis.manifest.ner_audit.status == "ready"
    assert all(point[0] >= 0 and point[1] >= 0 for m in page.redactions for point in m.polygon)


@pytest.mark.skipif(not os.getenv("ANONYMIZER_TEST_NER_MODEL"), reason="local model opt-in")
def test_real_backend_prompt_budget_unicode_and_long_tail():
    d = GLiNERDetector(NerConfig(Path(os.environ["ANONYMIZER_TEST_NER_MODEL"])))
    backend_id = id(d.backend)
    assert d.backend.token_count(["Giulia", "Rossi"]) > 2
    text = "😀 " + "Controllo clinico stabile. " * 150
    text += "Giulia Rossi visita Ospedale San Marco di Milano."
    spans = d.detect(text, "p")
    assert any(text[s.start : s.end] == "Giulia Rossi" for s in spans)
    assert any(s.kind == Kind.FACILITY for s in spans)
    assert id(d.backend) == backend_id
    assert d.detect("", "p") == []


@pytest.fixture(scope="module")
def evaluator_module():
    path = Path(__file__).parents[2] / "tools/experiments/ner/evaluate.py"
    spec = importlib.util.spec_from_file_location("anonymizer_ner_evaluator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_corpus_split_integrity_and_matching_metrics(evaluator_module):
    matched_count = evaluator_module.matched_count

    corpus_path = Path(__file__).parents[2] / "tools/experiments/ner/corpus.json"
    corpus = json.loads(corpus_path.read_text("utf-8"))
    people = {}
    for split in ("development", "evaluation"):
        docs = [doc for doc in corpus["docs"] if doc["split"] == split]
        assert len(docs) >= 22
        assert sum(not doc["entities"] for doc in docs) >= 2
        people[split] = set()
        for doc in docs:
            for entity in doc["entities"]:
                assert 0 <= entity["start"] < entity["end"] <= len(doc["text"])
                if entity["kind"] == "PERSON":
                    people[split].add(doc["text"][entity["start"] : entity["end"]])
    assert not people["development"] & people["evaluation"]
    assert matched_count([(0, 5), (5, 10)], [(0, 10)], True) == 1
    assert matched_count([(0, 5)], [(0, 10)], False) == 0
    assert matched_count([(0, 5), (5, 10)], [(0, 10), (1, 4)], True) == 2


def test_evaluator_separates_entity_type_from_mask_coverage(evaluator_module):
    evaluate = evaluator_module.evaluate

    text = "Centro delle Vele a Valleverde"
    document = dict(
        id="synthetic",
        text=text,
        entities=[dict(start=20, end=len(text), kind="LOCATION")],
        clinical_segments=[dict(start=0, end=6)],
    )
    report = evaluate([document], detector(FakeBackend(((text, "healthcare facility"),))))
    assert report["entity_metrics"]["LOCATION"]["partial_recall"] == 0
    assert report["output_mask_coverage"]["fully_covered_entities"] == 1
    assert report["output_mask_coverage"]["falsely_masked_clinical_characters"] == 6


def test_pain_score_guard_only_formally_valid_measurements():
    fixture_path = Path(__file__).parent / "fixtures/ner_pain_scores.json"
    fixture = json.loads(fixture_path.read_text("utf-8"))
    for text in fixture["protected"]:
        backend = FakeBackend(((text, "location"),))
        backend.word_limit = 50
        backend.subword_limit = 100
        d = detector(backend)
        assert d.detect(text, "p") == [], text
        assert d.audit.clinical_guard_version == "clinical_context_v6"
        from anonymizer.ner_model import NerAudit

        assert NerAudit(clinical_guard_version=fixture["guard_version"])
    for text in fixture["not_protected"]:
        backend = FakeBackend(((text, "healthcare facility"),))
        backend.word_limit = 50
        backend.subword_limit = 100
        assert len(detector(backend).detect(text, "p")) == 1, text


def test_pain_guard_containment_and_known_identity_precedence():
    from anonymizer.patient import KnownIdentity, KnownValue

    text = "VAS 7/10 Ada Marni"
    backend = FakeBackend(
        (("VAS 7/10", "location"), ("7/10", "location"), ("Ada Marni", "person"), (text, "person"))
    )
    backend.word_limit = 50
    backend.subword_limit = 100
    d = detector(backend)
    spans = d.detect(text, "p")
    assert {text[s.start : s.end] for s in spans} == {"Ada Marni", text}
    known = KnownIdentity((KnownValue(Kind.PERSON, "VAS 7/10"),), role="patient", confirmed=True)
    page = PageResult("p", "synthetic", 0, text)
    baseline = analyze_text([page], (known,))
    enhanced = analyze_text([page], (known,), ner=d)
    baseline_candidates = {(s.start, s.end, s.kind, s.level, s.origin) for s in baseline.candidates}
    assert baseline_candidates <= {
        (s.start, s.end, s.kind, s.level, s.origin) for s in enhanced.candidates
    }
    assert any(s.level == 0 and s.entity_id == known.id for s in enhanced.candidates)


def clinical_detector(targets):
    backend = FakeBackend(targets)
    backend.word_limit = 256
    backend.subword_limit = 1024
    return detector(backend)


@pytest.mark.parametrize(
    "text,target,label",
    [
        (
            "L'ormone aumenta durante la gravidanza nella placenta.Interviene poi.",
            "placenta",
            "location",
        ),
        ("Viene prodotto anche nella placenta, oltre che nei tessuti.", "placenta", "location"),
        ("Seguire il suggerimento del medico curante.", "medico curante", "person"),
        ("Serve il parere di uno specialista in grado di valutare.", "specialista", "person"),
        ("Valori inquadrati dal medico nella situazione clinica.", "medico", "person"),
        ("Resta a disposizione del medico curante, che valuterà.", "medico curante", "person"),
    ],
)
def test_clinical_context_guard_removes_only_contained_expected_kind(text, target, label):
    d = clinical_detector(((target, label),))
    assert d.detect(text, "p") == []
    assert d.audit.clinical_guard_version == "clinical_context_v6"


@pytest.mark.parametrize(
    "text,target,label",
    [
        ("Mario Placenta", "Mario Placenta", "person"),
        ("Dott. Placenta", "Placenta", "person"),
        ("Cognome e nome: Mario Placenta", "Mario Placenta", "person"),
        ("Nome e cognome: Mario Medico", "Mario Medico", "person"),
        ("Cognome e nome: Medico Curante", "Medico Curante", "person"),
        ("Paziente: placenta", "placenta", "location"),
        ("Si trova nella placenta.", "placenta", "location"),
        ("Gravidanza conclusa. Si trova nella placenta.", "placenta", "location"),
        ("In gravidanza nella placenta.", "placenta", "person"),
        ("In gravidanza nella placenta.", "placenta", "healthcare facility"),
        ("Il parere del Medico Curante", "Medico Curante", "person"),
        ("medico curante", "medico curante", "person"),
        ("Parere del medico curante Mario Placenta", "medico curante Mario Placenta", "person"),
        ("L'ormone è prodotto nella placenta di Valleverde.", "placenta di Valleverde", "location"),
    ],
)
def test_clinical_guard_preserves_names_unknown_contexts_and_extended_entities(text, target, label):
    spans = clinical_detector(((target, label),)).detect(text, "p")
    assert [text[span.start : span.end] for span in spans] == [target]


def test_clinical_guard_preserves_known_identity_and_previous_audit_versions():
    from anonymizer.ner_model import NerAudit
    from anonymizer.patient import KnownIdentity, KnownValue

    text = "Il parere del medico curante."
    known = KnownIdentity(
        (KnownValue(Kind.PERSON, "medico curante"),), role="patient", confirmed=True
    )
    page = PageResult("p", "s", 0, text)
    baseline = analyze_text([page], (known,))
    enhanced = analyze_text(
        [page], (known,), ner=clinical_detector((("medico curante", "person"),))
    )
    assert {(s.start, s.end, s.level, s.origin) for s in baseline.candidates} <= {
        (s.start, s.end, s.level, s.origin) for s in enhanced.candidates
    }
    assert "medico curante" not in enhanced.result.pages[0].text
    assert NerAudit().clinical_guard_version == "none"
    assert (
        NerAudit(clinical_guard_version="pain_scores_v1").clinical_guard_version == "pain_scores_v1"
    )


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize("inside_role", [False, True])
def test_clinical_roles_accept_only_one_ocr_line_wrap(newline, inside_role):
    role = "medico" + (newline if inside_role else " ") + "curante"
    text = "A disposizione del" + (" " if inside_role else newline) + role + ", che valuterà."
    assert clinical_detector(((role, "person"),)).detect(text, "p") == []
    separated = "A disposizione del" + newline + newline + role
    assert clinical_detector(((role, "person"),)).detect(separated, "p")
    two_wraps = "A disposizione del" + newline + "medico" + newline + "curante"
    assert clinical_detector((("medico" + newline + "curante", "person"),)).detect(two_wraps, "p")


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_anatomical_preposition_wrap_preserves_context_requirement(newline):
    text = "L'ormone è prodotto nella" + newline + "placenta, oltre che nei tessuti."
    assert clinical_detector((("placenta", "location"),)).detect(text, "p") == []
    separated = "L'ormone è prodotto nella" + newline + newline + "placenta."
    assert clinical_detector((("placenta", "location"),)).detect(separated, "p")


@pytest.mark.parametrize(
    "prefix,role",
    [
        ("nel quale il ", "paziente"),
        ("per il ", "paziente"),
        ("del ", "medico curante/specialista di riferimento"),
        ("del\n", "medico/specialista"),
        ("al ", "medico o allo specialista"),
        ("col proprio ", "medico/specialista"),
    ],
)
def test_generic_patient_and_coordinated_clinical_roles(prefix, role):
    text = "Il referto è destinato " + prefix + role + " che valuterà i risultati."
    d = clinical_detector(((role, "person"),))
    assert d.detect(text, "p") == []


@pytest.mark.parametrize(
    "text,target",
    [
        ("Paziente: Mario Paziente", "Mario Paziente"),
        ("Cognome e nome: Medico Curante", "Medico Curante"),
        ("Il parere del medico Mario Medico", "medico Mario Medico"),
        (
            "Il parere del medico curante/specialista Mario Placenta",
            "medico curante/specialista Mario Placenta",
        ),
        ("paziente", "paziente"),
        ("Medico Curante", "Medico Curante"),
    ],
)
def test_coordinated_role_guard_keeps_names_extended_spans_and_unknown_context(text, target):
    assert [
        text[s.start : s.end] for s in clinical_detector(((target, "person"),)).detect(text, "p")
    ] == [target]


def test_previous_clinical_context_audit_is_accepted():
    from anonymizer.ner_model import NerAudit

    assert (
        NerAudit(clinical_guard_version="clinical_context_v2").clinical_guard_version
        == "clinical_context_v2"
    )


@pytest.mark.parametrize("scale", [0.5, 1, 3])
def test_layout_sections_split_distant_blocks_preserving_unicode_offsets(scale):
    from anonymizer.model import TextRegion
    from anonymizer.text_pipeline import ner_sections

    parts = ["\U0001f600 Clinica Vallerin", "RISULTATI", "Clinica Monteluna"]
    text = "\n".join(parts)
    starts = [0, len(parts[0]) + 1, len(parts[0]) + len(parts[1]) + 2]
    regions = tuple(
        TextRegion(start, start + len(part), (0, y * scale, 100 * scale, (y + 10) * scale))
        for start, part, y in zip(starts, parts, [0, 500, 1000], strict=True)
    )
    page = PageResult("p", "s", 0, text, regions=regions)
    sections = ner_sections(page)
    assert len(sections) == 3
    assert "".join(text[a:b] for a, b in sections) == text
    backend = FakeBackend(
        (
            ("Clinica Vallerin", "healthcare facility"),
            ("Clinica Monteluna", "healthcare facility"),
            (text, "healthcare facility"),
        )
    )
    backend.word_limit = 100
    backend.subword_limit = 200
    result = analyze_text([page], ner=detector(backend))
    spans = [s for s in result.candidates if s.level == 3]
    assert [text[s.start : s.end] for s in spans] == ["Clinica Vallerin", "Clinica Monteluna"]
    assert all("RISULTATI" not in text[s.start : s.end] for s in spans)
    assert len(backend.calls) == 3


def test_layout_sections_preserve_nearby_multiline_names_and_unknown_text():
    from anonymizer.model import TextRegion
    from anonymizer.text_pipeline import ner_sections

    text = "Clinica\nVallerin"
    page = PageResult(
        "p",
        "s",
        0,
        text,
        regions=(
            TextRegion(0, 7, (0, 0, 100, 10)),
            TextRegion(8, len(text), (0, 18, 100, 28)),
        ),
    )
    assert ner_sections(page) == [(0, len(text))]
    backend = FakeBackend(((text, "healthcare facility"),))
    result = analyze_text([page], ner=detector(backend))
    assert [(s.start, s.end) for s in result.candidates if s.level == 3] == [(0, len(text))]
    text = "Clinica unlocalized Vallerin"
    page = PageResult(
        "p",
        "s",
        0,
        text,
        regions=(
            TextRegion(0, 7, (0, 0, 100, 10)),
            TextRegion(text.index("Vallerin"), len(text), (0, 500, 100, 510)),
        ),
    )
    assert ner_sections(page) == [(0, len(text))]
    assert ner_sections(PageResult("p", "s", 0, text)) == [(0, len(text))]
