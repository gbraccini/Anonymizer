from datetime import date

import pytest

from anonymizer.detect.known import detect_known
from anonymizer.model import Kind
from anonymizer.patient import KnownIdentity, KnownValue


def test_explicit_identity_matches_ocr_reverse_names_birth_and_contact():
    identity = KnownIdentity(
        (KnownValue(Kind.EMAIL, "elvio@example.invalid"),),
        given_name="Elvio",
        surname="Rossi",
        birth_date=date(1980, 3, 3),
        role="patient",
        confirmed=True,
    )
    text = "R0ssl Elvio; Rossi; 3 marzo 1980; elvio@example.invalid"
    found = detect_known(text, "p", (identity,))
    assert any(text[span.start : span.end] == "R0ssl Elvio" for span in found)
    assert any(text[span.start : span.end] == "Rossi" for span in found)
    assert any(span.kind == Kind.BIRTH_DATE for span in found)
    assert any(span.kind == Kind.EMAIL for span in found)
    assert all(span.entity_id == identity.id and span.level == 0 for span in found)


def test_similar_names_are_not_arbitrarily_fused():
    a = KnownIdentity((KnownValue(Kind.PERSON, "Elvio Veltrani"),), confirmed=True)
    b = KnownIdentity((KnownValue(Kind.PERSON, "Elvio Veltrano"),), confirmed=False)
    text = "Elvio Veltrani e Elvio Veltrano e Elvio Veltranu"
    found = detect_known(text, "p", (a, b))
    assert len(found) == 2
    assert [span.entity_id for span in found] == [a.id, b.id]
    assert found[1].validation.status == "proposed"


def test_short_clinical_tokens_do_not_gain_fuzzy_matches():
    identity = KnownIdentity((KnownValue(Kind.PERSON, "Li"),))
    assert detect_known("L1; litio", "p", (identity,)) == []


@pytest.mark.parametrize("value", ["3/3/1980", "3-3-1980", "3.3.1980", "1980-03-03"])
def test_known_birth_date_without_label_in_supported_numeric_formats(value):
    identity = KnownIdentity((), birth_date=date(1980, 3, 3))
    found = detect_known(value, "p", (identity,))
    assert len(found) == 1 and found[0].kind == Kind.BIRTH_DATE


def test_competing_explicit_identities_remain_separate_candidates():
    identities = tuple(KnownIdentity((KnownValue(Kind.CF, "VLTLVE80C03L219A"),)) for _ in range(2))
    found = detect_known("VLTLVE80C03L219A", "p", identities)
    assert len(found) == 2 and found[0].entity_id != found[1].entity_id


@pytest.mark.parametrize(
    "kind,values",
    [
        (Kind.PHONE, ("0123456789", "0987654321")),
        (Kind.EMAIL, ("elvio@example.invalid", "nerina@example.invalid")),
        (Kind.CF, ("VLTLVE80C03L219A", "SRRNRN90A41L219B")),
    ],
)
def test_distinct_values_of_same_kind_require_separate_data_identity(kind, values):
    with pytest.raises(ValueError, match="one canonical value"):
        KnownIdentity(tuple(KnownValue(kind, value) for value in values))


@pytest.mark.parametrize(
    "declared,observed",
    [
        ("Zo\u00eb D'\u00c1vori", "Zoe\u0308 D\u2019\u00c1vori"),
        ("Anne-Marie Vallerin", "Anne\u2013Marie  Vallerin"),
        ("Via D'\u00c1vori 12", "Via D\u2019\u00c1vori\n12"),
    ],
)
def test_unicode_context_matching_preserves_original_offsets(declared, observed):
    kind = Kind.ADDRESS if declared.startswith("Via") else Kind.PERSON
    identity = KnownIdentity((KnownValue(kind, declared),), confirmed=True)
    text = "\U0001f600 " + observed + "; clinica invariata"
    spans = detect_known(text, "p", (identity,))
    assert len(spans) == 1
    assert text[spans[0].start : spans[0].end] == observed
    assert spans[0].entity_id == identity.id and spans[0].level == 0
    assert spans[0].validation.reason == "normalized_known_value"
    assert detect_known("Zoe Davari; Anne Maria Vallerin", "p", (identity,)) == []


def test_no_declared_identity_does_not_normalize_page(monkeypatch):
    import anonymizer.detect.known as module

    monkeypatch.setattr(
        module, "normalized_context", lambda _: pytest.fail("unnecessary normalization")
    )
    assert detect_known("clinical text", "p", ()) == []
