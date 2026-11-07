from datetime import date

import pytest

from anonymizer.merge import merge
from anonymizer.model import Entity, Kind, PageResult, Span
from anonymizer.patient import KnownIdentity, KnownValue
from anonymizer.pseudo import ReferenceDate, pseudonymize, undo_replacement
from anonymizer.reassoc import reassociate
from anonymizer.text_pipeline import analyze_text


def page(text, page_id="p"):
    return PageResult(page_id, "source", 0, text)


def test_confirmed_patient_cf_and_name_get_distinct_stable_tokens():
    person = KnownIdentity(
        (KnownValue(Kind.PERSON, "Elvio Veltrani"), KnownValue(Kind.CF, "VLTLVE80C03L219A")),
        role="patient",
        confirmed=True,
    )
    text = "Elvio Veltrani; VLTLVE80C03L219A\nELVIO VELTRANI\nNon dolore: Hb 12 g/dL"
    result = analyze_text([page(text)], (person,)).result
    assert result.pages[0].text == (
        "[[PAZIENTE]]; [[CF_PAZIENTE]]\n[[PAZIENTE]]\nNon dolore: Hb 12 g/dL"
    )
    entries = {entry.token: entry for entry in result.map.entries}
    assert entries["[[CF_PAZIENTE]]"].canonical_value == "VLTLVE80C03L219A"
    assert entries["[[PAZIENTE]]"].canonical_value == "Elvio Veltrani"
    assert entries["[[PAZIENTE]]"].observed_values == ("Elvio Veltrani", "ELVIO VELTRANI")
    operation = result.replacements[2]
    assert undo_replacement(result.pages[0].text, operation).endswith(
        "ELVIO VELTRANI\nNon dolore: Hb 12 g/dL"
    )


def test_unconfirmed_identity_and_third_party_cf_are_not_patient():
    person = KnownIdentity((KnownValue(Kind.PERSON, "Elvio Veltrani"),), role="patient")
    result = analyze_text([page("Elvio Veltrani; VLTLVE80C03L219A")], (person,)).result
    assert "PAZIENTE" not in result.pages[0].text
    assert "VLTLVE" not in result.pages[0].text
    assert any(warning.code == "identity_unconfirmed" for warning in result.warnings)


def test_unknown_identical_names_do_not_establish_same_person():
    result = analyze_text([page("Elvio Veltrani; Elvio Veltrani")]).result
    assert result.pages[0].text == "[[PERSONA_1]]; [[PERSONA_2]]"


def test_collision_avoidance_looks_at_all_pages():
    identity = KnownIdentity(
        (KnownValue(Kind.PERSON, "Elvio Veltrani"),), role="patient", confirmed=True
    )
    result = analyze_text(
        [
            page("Elvio Veltrani", "a"),
            page("[[PAZIENTE]] [[PAZIENTE_1]] [[PERSONA_1]]", "b"),
        ],
        (identity,),
    ).result
    assert result.pages[0].text == "[[PAZIENTE_2]]"
    assert result.pages[1].text == "[[PAZIENTE]] [[PAZIENTE_1]] [[PERSONA_1]]"


def test_identifying_events_and_l0_dates_masked_with_sex_preserved():
    identity = KnownIdentity((KnownValue(Kind.BIRTH_DATE, "03/03/1980"),))
    text = "Visita 04/04/2020. Nata il 03/03/1980. Sesso F, non febbre."
    result = analyze_text([page(text)], (identity,)).result
    assert "04/04/2020" not in result.pages[0].text
    assert "03/03/1980" not in result.pages[0].text
    assert "Sesso F, non febbre." in result.pages[0].text
    assert any(
        warning.code == "birth_date_without_confirmed_reference" for warning in result.warnings
    )
    l0_event = Span("p", 7, 17, Kind.DATE, 0, "known:test")
    assert pseudonymize(
        [page("Visita 04/04/2020")], merge("Visita 04/04/2020", [l0_event])
    ).replacements


def test_age_requires_confirmed_reference_for_each_page_and_is_not_reassociated():
    text = "Nata il 3 marzo 1980. Visita 02/03/2020."
    pages = [page(text, "a"), page(text, "b"), page(text, "c")]
    result = analyze_text(
        pages,
        reference_dates={
            "a": ReferenceDate(date(2020, 3, 2), confirmed=True),
            "b": ReferenceDate(date(2026, 3, 4), confirmed=False),
        },
    ).result
    assert "39 anni" in result.pages[0].text
    assert "DATA_NASCITA" in result.pages[1].text
    assert "DATA_NASCITA" in result.pages[2].text
    assert reassociate("39 anni", result.map).text == "39 anni"
    assert not result.replacements[0].reversible_token


def test_future_or_ambiguous_birth_dates_stay_tokenized():
    for text in ("Nato il 03/03/80", "Nato il 03/03/2080", "Nato il 31/02/1980"):
        result = analyze_text(
            [page(text)],
            reference_dates={
                "p": ReferenceDate(date(2020, 1, 1), confirmed=True),
            },
        ).result
        assert "DATA_NASCITA" in result.pages[0].text


def test_unicode_and_clinical_text_outside_replacements_are_identical():
    text = "😀 e\u0301 Elvio Veltrani: Hb 12.5 g/dL\nNO febbre\tNa 140 mmol/L."
    result = analyze_text([page(text)]).result
    operation = result.replacements[0]
    assert operation.start == text.index("Elvio")
    assert operation.result_start == text.index("Elvio")
    assert (
        result.pages[0].text
        == text[: operation.start] + operation.replacement + text[operation.end :]
    )
    assert undo_replacement(result.pages[0].text, operation) == text


def test_facility_option_cannot_override_l0():
    text = "Clinica del Glicine"
    assert analyze_text([page(text)], mask_facilities=False).result.pages[0].text == text
    identity = KnownIdentity((KnownValue(Kind.FACILITY, text),))
    assert (
        analyze_text([page(text)], (identity,), mask_facilities=False).result.pages[0].text != text
    )


def test_conflicting_identity_never_promoted_to_patient():
    identities = tuple(
        KnownIdentity(
            (KnownValue(Kind.PERSON, "Elvio Veltrani"),),
            role="patient",
            confirmed=True,
        )
        for _ in range(2)
    )
    result = analyze_text([page("Elvio Veltrani")], identities).result
    assert "PAZIENTE" not in result.pages[0].text
    assert any(
        warning.code == "entity_conflict" and warning.blocking for warning in result.warnings
    )


def test_preserved_overlap_still_rejected():
    text = "03/03/2020"
    spans = merge(text, [Span("p", 0, 10, Kind.DATE, 1, "test")])
    spans += merge(text, [Span("p", 2, 8, Kind.PERSON, 1, "test")])
    with pytest.raises(ValueError):
        pseudonymize([page(text)], spans)


def test_stale_undo_rejected():
    result = analyze_text([page("Elvio Veltrani")]).result
    with pytest.raises(ValueError):
        undo_replacement("modified", result.replacements[0])


def test_explicit_name_fields_provide_clean_canonical_for_ocr_and_surname_only():
    identity = KnownIdentity(
        (), given_name="Elvio", surname="Rossi", confirmed=True, role="patient"
    )
    result = analyze_text([page("R0ssl Elvio; Rossi")], (identity,)).result
    assert result.pages[0].text == "[[PAZIENTE]]; [[PAZIENTE]]"
    assert reassociate(result.pages[0].text, result.map).text == "Elvio Rossi; Elvio Rossi"
    assert result.replacements[0].original == "R0ssl Elvio"
    surname_only = KnownIdentity((), surname="Forte")
    assert analyze_text([page("Forte")], (surname_only,)).result.replacements


def test_patient_entities_are_not_required_for_nonpersonal_identifiers():
    result = analyze_text([page("Tel: 0123456789; CAP: 12345")]).result
    assert not any(warning.code == "identity_unconfirmed" for warning in result.warnings)


def test_invalid_entities_and_duplicate_pages_are_rejected():
    with pytest.raises(ValueError):
        pseudonymize([page("x"), page("x")], [])
    with pytest.raises(ValueError):
        pseudonymize([page("x")], [], [Entity("a"), Entity("a")])
