import hashlib
import re
from pathlib import Path

import pytest

from anonymizer.detect.clinical import external_rules, protected_clinical_spans
from anonymizer.detect.ner import GLiNERDetector
from anonymizer.model import Kind, PageResult
from anonymizer.ner_model import NerAudit, NerConfig
from anonymizer.patient import KnownIdentity, KnownValue
from anonymizer.text_pipeline import analyze_text


class Backend:
    model_id = "synthetic/external-clinical"
    revision = "test"
    artifact_sha256 = "a" * 64
    library_version = "test"
    word_limit = 128
    subword_limit = 256
    max_width = 12

    def __init__(self, target, label="person"):
        self.target, self.label = target, label

    def split(self, text):
        return [(m.group(), m.start(), m.end()) for m in re.finditer(r"\S+", text)]

    def token_count(self, words):
        return len(words) + 5

    def predict(self, text, threshold):
        return [
            dict(start=m.start(), end=m.end(), text=m.group(), label=self.label, score=0.9)
            for m in re.finditer(re.escape(self.target), text)
        ]


def detector(target, label="person"):
    return GLiNERDetector(NerConfig(Path("unused")), backend=Backend(target, label))


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize(
    "label",
    ["Paziente", "NOME E COGNOME", "Medico curante", "Refertante", "Direttore sanitario"],
)
def test_explicit_labels_protect_only_the_label_and_not_following_person(newline, label):
    name = "Zoë D’Astravelli"
    text = "😀" + newline + label + ": " + name
    assert detector(label).detect(text, "p") == []
    assert detector(name).detect(text, "p")
    assert detector(label + ": " + name).detect(text, "p")


@pytest.mark.parametrize(
    "text,target",
    [
        ("Interpretazione del referto con il medico.", "referto"),
        ("LETTURA DEI RISULTATI con la paziente.", "RISULTATI"),
        ("Consultazione delle analisi disponibili.", "analisi"),
        ("valutazione dell’analisi disponibile", "analisi"),
        ("valutazione dell'analisi disponibile", "analisi"),
        ("IL medico curante di riferimento valuta gli esami.", "medico curante"),
    ],
)
def test_clinical_scope_preserves_generic_nouns_in_narrative(text, target):
    assert detector(target).detect(text, "p") == []


@pytest.mark.parametrize(
    "text,target",
    [
        ("Paziente Astravelli", "Paziente Astravelli"),
        ("Interpretazione del referto di Zoë Astravelli", "Zoë Astravelli"),
        ("Interpretazione del referto di Zoë Astravelli", "referto di Zoë Astravelli"),
        ("Laboratorio Analisi Astravelli", "Analisi Astravelli"),
        ("Refertante: Valeria Monteluna", "Valeria Monteluna"),
        ("Interpretazione del refertone", "refertone"),
    ],
)
def test_scoped_guards_never_exempt_extended_names_or_unmatched_context(text, target):
    assert detector(target).detect(text, "p")


def test_explicit_known_value_survives_even_if_ner_protects_same_text():
    text = "Paziente: Zoë Astravelli"
    identity = KnownIdentity((KnownValue(Kind.PERSON, "Paziente"),), confirmed=True)
    result = analyze_text([PageResult("p", "s", 0, text)], (identity,), ner=detector("Paziente"))
    assert any(s.level == 0 and s.entity_id == identity.id for s in result.candidates)
    assert "Paziente" not in result.result.pages[0].text
    assert "Zoë Astravelli" not in result.result.pages[0].text


def test_external_rules_record_pinned_sources_and_shipped_licenses():
    data = external_rules()
    root = Path("build/artifacts/external-rules-sources")
    data_path = Path(__file__).parents[1] / "anonymizer/data"
    for key, source in data["upstreams"].items():
        assert re.fullmatch(r"[0-9a-f]{40}", source["revision"])
        license_source = next(s for s in source["sources"] if s["path"] == "LICENSE")
        license_path = data_path / (key.upper() + "_LICENSE.txt")
        assert hashlib.sha256(license_path.read_bytes()).hexdigest() == license_source["sha256"]
        for entry in source["sources"]:
            assert source["revision"] in entry["url"]
            assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
            if entry["path"] == "NOTICE":
                notice = data_path / (key.upper() + "_NOTICE.txt")
                assert hashlib.sha256(notice.read_bytes()).hexdigest() == entry["sha256"]
            if root.is_dir():
                assert hashlib.sha256((root / key / entry["path"]).read_bytes()).hexdigest() == (
                    entry["sha256"]
                )
    assert all(r["adaptation_type"] == "local_logic_adaptation" for r in data["clinical_rules"])
    assert data["guard_version"] == detector("paziente").audit.clinical_guard_version
    assert NerAudit(clinical_guard_version="clinical_context_v5")


def test_no_protection_of_entire_section_or_identifiers():
    text = "Risultati\nInterpretazione del referto\nPaziente: Zoë Astravelli\nTel. 0123456789"
    protected = protected_clinical_spans(text)
    for target in ("Zoë Astravelli", "0123456789"):
        start = text.index(target)
        assert not any(a <= start and start + len(target) <= b for a, b, _ in protected)
    result = analyze_text([PageResult("p", "s", 0, text)], ner=detector("referto"))
    assert any(s.kind == Kind.PHONE and s.level == 1 for s in result.candidates)
    assert "0123456789" not in result.result.pages[0].text
