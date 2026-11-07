import pytest

from anonymizer.cf import checksum
from anonymizer.detect.regex import detect_regex
from anonymizer.model import Kind


def values(text, kind):
    return [text[span.start : span.end] for span in detect_regex(text, "p") if span.kind == kind]


def test_invalid_cf_is_sensitive_without_known_identity():
    prefix = "VLTLVE80C03L219"
    invalid = prefix + ("A" if checksum(prefix) != "A" else "B")
    spans = detect_regex(f"Originale {invalid}.", "p")
    assert len(spans) == 1
    assert spans[0].kind == Kind.CF
    assert spans[0].validation.status == "invalid"


def test_cf_with_ocr_errors_and_spaced_letters():
    code = "VLTLVE80C03L219" + checksum("VLTLVE80C03L219")
    ocr = code[:7] + "O" + code[8:]
    text = f"{ocr}\n{' '.join(code)}"
    assert values(text, Kind.CF) == [ocr, " ".join(code)]


@pytest.mark.parametrize("value", ["03/03/1980", "3 marzo 1980", "1980-03-03", "03.03.1980"])
def test_birth_context_and_date_event(value):
    text = f"Data di nascita: {value}; visita {value}."
    assert values(text, Kind.BIRTH_DATE) == [value]
    assert values(text, Kind.DATE) == [value]


@pytest.mark.parametrize(
    "context",
    [
        "nata a Valleverde il ",
        "nato a Valleverde il ",
        "nato/a a Valleverde il ",
        "NATA A VALLEVERDE IL ",
        "nata a San Martino delle Valli di Valleverde il ",
        "nata a Sant'Elvio (VV) il ",
        "nata a Città dell’Olmo, il ",
        "nata\na Valleverde\nil\n",
        "nata a San Martino\ndelle Valli il ",
        "nato/a il ",
        "nata il ",
        "nato ",
        "d.n.: ",
    ],
)
@pytest.mark.parametrize("date", ["03/03/1980", "3 marzo 1980", "1980-03-03"])
def test_birth_date_after_birthplace(context, date):
    text = f"Paziente {context}{date}; controllo 04/11/2026."
    assert values(text, Kind.BIRTH_DATE) == [date]
    assert values(text, Kind.DATE) == ["04/11/2026"]


@pytest.mark.parametrize(
    "context",
    [
        "aggiornato il ",
        "aggiornata il ",
        "prenotato il ",
        "nata a Valleverde; visita il ",
        "nata a Valleverde. Controllo il ",
        "nata a Valleverde, ricoverata il ",
        "nata a Valleverde ricoverata il ",
        "nata a Valleverde e dimessa il ",
        "nata a Valleverde\ncontrollo il ",
        "nata a Valleverde\n\nil ",
        "nata a Valleverde il 03/03/1980, controllo il ",
        "nata a Valleverde il 03/03/1980 il ",
    ],
)
def test_event_date_not_mistaken_for_birth_date(context):
    text = f"{context}04/11/2026"
    assert values(text, Kind.DATE) == ["04/11/2026"]
    assert "04/11/2026" not in values(text, Kind.BIRTH_DATE)


@pytest.mark.parametrize("label", ["nata", "nato", "nato/a", "mata", "mato"])
@pytest.mark.parametrize("preposition", ["il", "i", "I", "l"])
def test_birth_date_with_ocr_errors_only_in_complete_birthplace_field(label, preposition):
    text = f"{label} a Valleverde {preposition} 03/03/1980; controllo 04/11/2026"
    assert values(text, Kind.BIRTH_DATE) == ["03/03/1980"]
    assert values(text, Kind.DATE) == ["04/11/2026"]


@pytest.mark.parametrize(
    "context",
    [
        "mata il ",
        "mato i ",
        "stimata a Valleverde il ",
        "formato a Valleverde il ",
        "mata a Valleverde controllo i ",
        "mata a Valleverde; i ",
        "mata a Valleverde i 03/03/1980 controllo i ",
        "mata a MIN, ricoverata il ",
        "mata a MIN controllo il ",
        "nata a Valleverde ",
        "nata a Valleverde\n\n\n\nil ",
        "aggiornato il" + " " * 185,
    ],
)
def test_ocr_birth_context_does_not_capture_unrelated_dates(context):
    text = f"{context}04/11/2026"
    assert values(text, Kind.DATE) == ["04/11/2026"]


def test_ocr_birth_date_after_unreadable_masked_birthplace():
    text = "mata a MIN i 03/03/1980"
    assert values(text, Kind.BIRTH_DATE) == ["03/03/1980"]


def test_identifiers_with_context_and_unicode_offsets():
    text = (
        "😀 e\u0301 Tel: +39 012 3456789; CAP: 12345; pratica: AX-9001; "
        "tessera sanitaria: 12345678901234567890; elvio@example.invalid; "
        "IT60X0542811101000000123456"
    )
    expected = {
        Kind.PHONE: "+39 012 3456789",
        Kind.POSTCODE: "12345",
        Kind.CASE_NUMBER: "AX-9001",
        Kind.HEALTH_CARD: "12345678901234567890",
        Kind.EMAIL: "elvio@example.invalid",
        Kind.IBAN: "IT60X0542811101000000123456",
    }
    for kind, value in expected.items():
        assert values(text, kind) == [value]
    assert next(
        span for span in detect_regex(text, "p") if span.kind == Kind.PHONE
    ).start == text.index("+39")


@pytest.mark.parametrize(
    "text",
    [
        "Referto negativo. Cartella clinica. Pratica completata.",
        "PA 120/80 mmHg; glicemia 12345 mg/dL; PCR 12.5; 3391234567 cellule.",
        "Non dolore alla testa; forte grasso viscerale. Dose 25 mg.",
    ],
)
def test_clinical_text_not_identifiers(text):
    assert detect_regex(text, "p") == []
