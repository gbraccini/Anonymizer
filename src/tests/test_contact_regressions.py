import pytest

from anonymizer.detect.context import detect_contact_details
from anonymizer.detect.layout import detect_layout_fields
from anonymizer.detect.regex import detect_regex
from anonymizer.model import Kind, PageResult, TextRegion
from anonymizer.text_pipeline import analyze_text


@pytest.mark.parametrize(
    "number",
    [
        "3209990001",
        "055 9990600",
        "05599942",
        "0531/999342",
        "+39 02 999322",
        "0039 320 123 4567",
        "320-123-4567",
        "320.123.4567",
        "(055) 9990600",
        "+39\u00a0320\u202f123\u202f4567",
        "320\u2011123\u20114567",
    ],
)
@pytest.mark.parametrize("label", ["", "Tel.Abitazione: ", "Tel.Cellulare: ", "MMG/PLS: "])
def test_phone_formats_without_relying_on_label(number, label):
    text = "😀 " + label + number + "; fine"
    found = [s for s in detect_regex(text, "p") if s.kind == Kind.PHONE]
    assert [text[s.start : s.end] for s in found] == [number]


@pytest.mark.parametrize(
    "text",
    [
        "03/03/1980",
        "2026-11-04",
        "PA 120/80 mmHg",
        "3391234567 cellule",
        "Hb 12.5 g/dL; glicemia 95 mg/dL",
        "ABC3201234567XYZ",
        "3201234567890123456",
        "Rapporto 0.1234567",
        "Rapporto 0.3201234567; indice 3.14159265",
        "a3201234567@example.org",
        "CAP 05536",
        "01.02.2020 03.04.2021",
    ],
)
def test_phones_do_not_capture_dates_clinical_values_or_identifier_fragments(text):
    assert not any(s.kind == Kind.PHONE for s in detect_regex(text, "p"))


def test_adjacent_phone_numbers_are_separate():
    text = "3201234567 055 9990600; +39 02 999322 / 3207654321"
    found = [s for s in detect_regex(text, "p") if s.kind == Kind.PHONE]
    assert [text[s.start : s.end] for s in found] == [
        "3201234567",
        "055 9990600",
        "+39 02 999322",
        "3207654321",
    ]


@pytest.mark.parametrize(
    "label",
    [
        "Luogo di nascita:",
        "Comune di nascita:",
        "Nato a",
        "Nata a",
        "Residente a",
        "Residenza:",
        "Comune di residenza:",
        "Domicilio:",
    ],
)
@pytest.mark.parametrize("city", ["Valleverde", "San Vallerin (PV)", "castel fiorito"])
def test_explicit_personal_locations(label, city):
    text = f"{label} {city}; Tel. 3201234567"
    found = [s for s in detect_contact_details(text, "p") if s.kind == Kind.LOCATION]
    assert [text[s.start : s.end] for s in found] == [city]


@pytest.mark.parametrize(
    "text",
    [
        "Nato a termine",
        "Nata a 38 settimane",
        "Residenza sanitaria assistenziale",
        "Domicilio: non disponibile",
        "Pressione Arteriosa (PA)",
        "Nato a\n\nGlucosio 90 mg/dL",
        "Terapia per via orale",
    ],
)
def test_location_rules_preserve_clinical_phrases(text):
    assert not any(s.kind == Kind.LOCATION for s in detect_contact_details(text, "p"))


@pytest.mark.parametrize("city", ["Valleverde (PV)", "Valleverde(PV)"])
def test_province_suffix_with_unreadable_label(city):
    text = "[etichetta illeggibile]: " + city
    found = detect_contact_details(text, "p")
    assert [text[s.start : s.end] for s in found] == [city]


def test_spatial_location_with_interposed_clinical_column():
    text = "Luogo di nascita:\nHb 12 g/dL\nValleverde\n(PV)"
    values = [
        ("Luogo di nascita:", (10, 10, 100, 20)),
        ("Hb 12 g/dL", (300, 10, 390, 20)),
        ("Valleverde", (110, 10, 170, 20)),
        ("(PV)", (175, 10, 200, 20)),
    ]
    regions = tuple(TextRegion(text.index(v), text.index(v) + len(v), box) for v, box in values)
    page = PageResult("p", "s", 0, text, regions=regions)
    found = detect_layout_fields(page)
    assert [text[s.start : s.end] for s in found] == ["Valleverde\n(PV)"]


def test_residence_address_and_city_without_postcode():
    text = "Residenza: Via Monteluna 12, Valleverde; Tel. 3201234567"
    spans = detect_contact_details(text, "p")
    assert [(text[s.start : s.end], s.kind) for s in spans] == [
        ("Via Monteluna 12", Kind.ADDRESS),
        ("Valleverde", Kind.LOCATION),
    ]


@pytest.mark.parametrize(
    "email", ["nome@example.org", "nome.cognome @ example.org", "nome+tag\u00a0@\u00a0example.org"]
)
def test_email_ocr_spacing_and_original_offsets(email):
    text = "😀 Email: " + email + "; fine"
    found = [s for s in detect_regex(text, "p") if s.kind == Kind.EMAIL]
    assert [text[s.start : s.end] for s in found] == [email]


def test_contacts_are_replaced_in_pipeline_without_ner():
    values = ["3201234567", "055 9990600", "nome @ example.org", "Valleverde (PV)"]
    text = f"Tel.Abitazione: {values[0]}\nMMG/PLS: {values[1]}\nEmail: {values[2]}\n"
    text += f"Luogo di nascita: {values[3]}\nHb 12 g/dL"
    result = analyze_text([PageResult("p", "s", 0, text)])
    output = result.result.pages[0].text
    assert all(value not in output for value in values)
    assert "Hb 12 g/dL" in output
