from dataclasses import replace

import pytest

from anonymizer.detect.context import detect_contact_details, detect_doctors, detect_patient_labels
from anonymizer.model import Kind, PageResult, TextRegion
from anonymizer.text_pipeline import analyze_text


@pytest.mark.parametrize(
    "title",
    [
        "Dr",
        "DR",
        "Dr.",
        "Dr :",
        "Dr: ",
        "Dott.",
        "DOTT",
        "Dott.ssa:",
        "Dr.ssa",
        "Dottor",
        "Dottore",
        "Dottoressa",
        "dott.ssa :",
    ],
)
def test_explicit_titles_outside_vocabulary_and_unicode_offsets(title):
    text = f"😀 Firma digitale del documento {title} Mirella Astravelli 12345"
    spans = detect_doctors(text, "p")
    assert len(spans) == 1
    span = spans[0]
    assert text[span.start : span.end] == "Mirella Astravelli"
    assert (span.kind, span.level, span.origin) == (Kind.DOCTOR, 1, "context:doctor")
    assert span.validation.reason == "explicit_doctor_title" and span.entity_id is None


@pytest.mark.parametrize(
    "name",
    [
        "MIRELLA ASTRAVELLI",
        "María D’Ávori",
        "Jean-Luc D'Astravelli",
        "Zoë van Daalen",
        "MARIA TERESA DE LA TORRE",
        "Łukasz Żur",
        "André De Vallerin Monteluna",
        "Andre\u0301 Vallerin",
    ],
)
def test_compound_names_particles_and_diacritics_not_truncated(name):
    text = f"Dott.ssa: {name}; Hb 12 g/dL"
    spans = detect_doctors(text, "p")
    assert [text[span.start : span.end] for span in spans] == [name]


@pytest.mark.parametrize(
    "text",
    [
        "Dr",
        "Dott. ...",
        "Dott.ssa:",
        "DR PROTEINA C REATTIVA",
        "DR proteina C reattiva",
        "Dr Pressione Arteriosa",
        "Dr Mirella",
        "Dr Mirella Astravelli123",
        "Drog Mirella Astravelli",
        "αDr Mirella Astravelli",
        "e\u0301Dr Mirella Astravelli",
        "Medr Mirella Astravelli",
        "Dr\n\nMirella Astravelli",
        "Dr Mirella\nAstravelli",
        "Dr mirella astravelli",
        "DR 123 Mirella Astravelli",
        "Dr Uno Due Tre Quattro Cinque Sei Sette",
    ],
)
def test_ambiguous_clinical_prose_and_title_without_name_are_not_detected(text):
    assert detect_doctors(text, "p") == []


@pytest.mark.parametrize(
    "suffix",
    [
        " HA VALIDATO IL REFERTO",
        " Data 03/04/2026",
        " ha validato il referto",
        " Firma digitale",
        " Di seguito",
        "\nEMOGLOBINA 12 g/dL",
        " 03/04/2026",
    ],
)
def test_stops_before_signature_prose_and_next_clinical_line(suffix):
    text = "Dr : Mirella Astravelli" + suffix
    spans = detect_doctors(text, "p")
    assert [text[span.start : span.end] for span in spans] == ["Mirella Astravelli"]


def test_one_newline_after_title_supported_and_patient_not_attributed():
    text = "Dott.ssa:\r\n Zoë Astravelli\nGlucosio 90 mg/dL"
    analysis = analyze_text([PageResult("p", "s", 0, text)])
    context = [span for span in analysis.candidates if span.origin == "context:doctor"]
    assert len(context) == 1 and context[0].entity_id is None
    assert text[context[0].start : context[0].end] == "Zoë Astravelli"
    assert "Zoë Astravelli" not in analysis.result.pages[0].text
    assert "Glucosio 90 mg/dL" in analysis.result.pages[0].text


def test_doctor_candidate_produces_geometric_masks_and_synchronized_text():
    pytest.importorskip("PIL")
    from anonymizer.redact import propose_redactions
    from anonymizer.visual_model import SourcePageGeometry, VisualPage
    from anonymizer.web.text import page_text

    text = "Dr : Mirella Astravelli Hb 12 g/dL"
    name = "Mirella Astravelli"
    start = text.index(name)
    regions = (
        TextRegion(0, start, (1, 1, 25, 10)),
        TextRegion(start, start + len(name), (30, 1, 90, 10)),
        TextRegion(start + len(name), len(text), (100, 1, 190, 10)),
    )
    page = PageResult("p", "s", 0, text, regions=regions)
    analysis = analyze_text([page])
    geometry = SourcePageGeometry(200, 80, 200, 80, 72)
    masks, warnings, required = propose_redactions(page, list(analysis.merged_spans), geometry)
    assert len(masks) == 1 and not warnings and len(required) == 1
    view = VisualPage(page, 0, geometry, masks)
    assert page_text(view)["redacted"] == "Dr : [OSCURATO] Hb 12 g/dL"
    restored = replace(view, redactions=(replace(masks[0], decision="reject", reason="Review"),))
    assert page_text(restored)["redacted"] == text


@pytest.mark.parametrize(
    "label",
    ["Cognome e nome", "NOME E COGNOME:", "Cognome/nome:", "Nome - Cognome =", "Nome Cognome"],
)
@pytest.mark.parametrize("name", ["Rossi Demo", "Zoë D’Ávori", "MARIA TERESA DE LA TORRE"])
def test_compound_patient_labels_stop_before_following_columns(label, name):
    text = f"😀 {label} {name} Data 23-05-2026 UM 02-01-2026"
    spans = detect_patient_labels(text, "p")
    assert [text[span.start : span.end] for span in spans] == [name]
    span = spans[0]
    assert (span.kind, span.level, span.origin) == (Kind.PERSON, 1, "context:patient_name")
    assert span.validation.reason == "explicit_patient_name_label"
    assert span.entity_id is None


@pytest.mark.parametrize(
    "suffix",
    [" Metodica ELISA", " Sesso F", " Codice fiscale", " UM 02-01-2026", "\nGlucosio 90"],
)
def test_patient_label_one_newline_and_non_dictionary_name(suffix):
    text = "Cognome e nome:\r\n Élodie van Astravelli" + suffix
    spans = detect_patient_labels(text, "p")
    assert [text[span.start : span.end] for span in spans] == ["Élodie van Astravelli"]


@pytest.mark.parametrize(
    "text",
    [
        "Cognome e nome Data Metodica",
        "Nome e cognome\n\nZoë Astravelli",
        "Cognome e nome\nMetodica Esame",
        "Nome e cognome: ...",
        "Cognome e nome NON NOTO",
        "Nome e cognome Campo Obbligatorio",
        "Il nome della terapia è diverso dal cognome del medico",
        "Nome: Pressione Arteriosa",
        "Nome e cognome deve essere compilato",
        "Cognome e nome Glucosio Creatinina",
        "Cognome e nome Astravelli123 Demo",
        "Cognome e nome Uno Due Tre Quattro Cinque Sei Sette",
        "αNome e cognome Zoë Astravelli",
        "Nome e cognome Astravelli\nZoë",
    ],
)
def test_patient_labels_do_not_detect_empty_headers_or_generic_clinical_names(text):
    assert detect_patient_labels(text, "p") == []


def test_patient_label_masks_text_and_export_are_synchronized(tmp_path):
    from io import BytesIO

    Image = pytest.importorskip("PIL.Image")
    from anonymizer.export import export_document
    from anonymizer.ingest import InputFile, inspect_inputs
    from anonymizer.manifest import confirm_review
    from anonymizer.redact import apply_redactions, propose_redactions
    from anonymizer.visual_model import ReviewManifest, VisualPage
    from anonymizer.web.text import page_text

    image = Image.new("RGB", (260, 80), "white")
    buffer = BytesIO()
    image.save(buffer, "PNG")
    source = InputFile(buffer.getvalue(), ".png")
    records, page_inputs = inspect_inputs((source,))
    original = page_inputs[0]
    text = "Cognome e nome Zoë Astravelli Metodica ELISA"
    name = "Zoë Astravelli"
    start, end = text.index(name), text.index(name) + len(name)
    regions = (
        TextRegion(0, start, (1, 1, 70, 10)),
        TextRegion(start, end, (80, 1, 150, 10)),
        TextRegion(end, len(text), (170, 1, 250, 10)),
    )
    page = PageResult(original.page_id, source.source_id, 0, text, regions=regions)
    analysis = analyze_text([page])
    assert any(span.origin == "context:patient_name" for span in analysis.candidates)
    assert name not in analysis.result.pages[0].text
    assert "Metodica ELISA" in analysis.result.pages[0].text
    masks, warnings, required = propose_redactions(
        page, list(analysis.merged_spans), original.geometry
    )
    assert masks and not warnings
    visual = VisualPage(page, 0, original.geometry, masks, required_candidate_ids=required)
    assert page_text(visual)["redacted"] == "Cognome e nome [OSCURATO] Metodica ELISA"
    manifest = confirm_review(ReviewManifest(records, (visual,), page_order=(page.page_id,)))
    output = tmp_path / "masked.png"
    export_document((source,), manifest, output)
    expected = apply_redactions(image, manifest.pages[0].redactions, original.geometry)
    with Image.open(output) as actual:
        assert actual.tobytes() == expected.tobytes()
        assert actual.getpixel((100, 5)) == (0, 0, 0)
        assert actual.getpixel((200, 5)) == (255, 255, 255)
    assert buffer.getvalue() == source.data
    expected.close()
    image.close()


@pytest.mark.parametrize(
    "value",
    [
        "Diagnostica Vallerin s.r.l.",
        "LABORATORIO ANALISI ASTRAVELLI SRL",
        "Centro Analisi Zoë D’Ávori S.p.A.",
        "Clinica Monteluna s.r.l.",
    ],
)
def test_facility_requires_real_name_and_legal_or_contact_context(value):
    text = "😀 " + value + " - Via Fermi, 63/F 42123 Valleverde"
    spans = detect_contact_details(text, "p")
    assert [(text[s.start : s.end], s.kind) for s in spans] == [
        (value, Kind.FACILITY),
        ("Via Fermi, 63/F", Kind.ADDRESS),
        ("42123", Kind.POSTCODE),
        ("Valleverde", Kind.LOCATION),
    ]
    assert all(s.level == 1 and s.entity_id is None for s in spans)


@pytest.mark.parametrize(
    "text,target",
    [
        ("Struttura: Clinica Astravelli", "Clinica Astravelli"),
        ("Laboratorio Analisi Vallerin Tel. 0123456789", "Laboratorio Analisi Vallerin"),
        ("Clinica:Monteluna fax 0123456789", "Clinica:Monteluna"),
    ],
)
def test_explicit_facility_label_or_contact(text, target):
    assert [text[s.start : s.end] for s in detect_contact_details(text, "p")] == [target]


@pytest.mark.parametrize(
    "text",
    [
        "Centro Analisi Dei Risultati",
        "Diagnostica Differenziale",
        "Clinica e diagnosi",
        "Laboratorio analisi",
        "Clinica Monteluna",
        "Via Orale 12 mg",
        "via di somministrazione 20 mg",
        "via respiratoria",
        "Via Respiratoria 12 mg",
        "Via Roma",
        "Via Roma 42123 Valleverde",
        "Via\nAstravelli 12",
        "Laboratorio\nAstravelli s.r.l.",
    ],
)
def test_contact_rules_do_not_mask_clinical_prose_or_incomplete_headers(text):
    assert detect_contact_details(text, "p") == []


@pytest.mark.parametrize(
    "address",
    [
        "Via Fermi, 63/F",
        "Viale D’Ávori 12",
        "Piazza della Torre 2 bis",
        "Corso Évora n. 17A",
        "V.le Monteluna 9/ B",
    ],
)
def test_numbered_addresses_preserve_unicode_offsets_and_stop_before_postcode(address):
    text = "😀 " + address + " 12345 Valleverde Tel. 0123456789"
    spans = detect_contact_details(text, "p")
    assert [(text[s.start : s.end], s.kind) for s in spans] == [
        (address, Kind.ADDRESS),
        ("12345", Kind.POSTCODE),
        ("Valleverde", Kind.LOCATION),
    ]


def test_contact_candidates_mask_geometric_regions_and_keep_clinical_text():
    pytest.importorskip("PIL")
    from anonymizer.redact import propose_redactions
    from anonymizer.visual_model import SourcePageGeometry, VisualPage
    from anonymizer.web.text import page_text

    facility = "Diagnostica Astravelli s.r.l."
    address = "Via Monteluna, 63/F"
    text = facility + " - " + address + "\nHb 12 g/dL"
    start = text.index(address)
    end = start + len(address)
    regions = (
        TextRegion(0, len(facility), (1, 1, 95, 10)),
        TextRegion(start, end, (105, 1, 195, 10)),
        TextRegion(end + 1, len(text), (1, 30, 95, 40)),
    )
    page = PageResult("p", "s", 0, text, regions=regions)
    analysis = analyze_text([page])
    assert {s.origin for s in analysis.candidates} >= {"context:facility", "context:address"}
    geometry = SourcePageGeometry(200, 80, 200, 80, 72)
    masks, warnings, required = propose_redactions(page, list(analysis.merged_spans), geometry)
    assert len(masks) == 2 and not warnings and len(required) == 2
    result = page_text(VisualPage(page, 0, geometry, masks))["redacted"]
    assert facility not in result and address not in result
    assert "Hb 12 g/dL" in result


def test_street_civic_stops_before_city_without_postcode():
    text = "via Emilia 12 Reggio Emilia"
    spans = detect_contact_details(text, "p")
    assert [(text[span.start : span.end], span.kind) for span in spans] == [
        ("via Emilia 12", Kind.ADDRESS)
    ]


@pytest.mark.parametrize("suffix", ["s.r.l.", "s.r.I.", "s.r.1.", "S.R.L."])
def test_bounded_facility_ocr_legal_suffix_and_contact_website(suffix):
    facility = "Diagnostica Vallerin " + suffix
    text = (
        facility + " - Via Fermi, 63/F 42123 Valleverde\nTel. 0123456789 Fax 0123456790\n"
        "www.vallerin-example.it info@vallerin-example.it"
    )
    spans = detect_contact_details(text, "p")
    values = [(text[s.start : s.end], s.origin) for s in spans]
    assert (facility, "context:facility") in values
    assert ("Via Fermi, 63/F", "context:address") in values
    assert ("www.vallerin-example.it", "context:facility_web") in values


@pytest.mark.parametrize(
    "text",
    [
        "Bibliografia scientifica https://example.org/study",
        "Diagnostica Differenziale Tel. 0123456789 www.example.org",
        "Diagnostica Vallerin s.r.l.\n\nBibliografia https://example.org/study",
        "Diagnostica Vallerin s.r.l. www.example.org",
    ],
)
def test_scientific_urls_without_facility_contact_evidence_are_preserved(text):
    assert not any(s.origin == "context:facility_web" for s in detect_contact_details(text, "p"))


@pytest.mark.parametrize(
    "heading", ["CENTRO AUTORIZZATO", "LABORATORIO ACCREDITATO", "CLINICA AUTORIZZATA"]
)
def test_placeholder_patient_label_does_not_capture_facility_heading(heading):
    assert detect_patient_labels("Nome Cognome\n" + heading, "p") == []
    text = "Cognome e nome Rossi Demo Data 23-05-2026 UM 02-01-2026"
    assert [text[s.start : s.end] for s in detect_patient_labels(text, "p")] == ["Rossi Demo"]


@pytest.mark.parametrize("text", ["Valore 12345 cellule", "Via Fermi 12 123456", "Via Fermi 12345"])
def test_postcodes_require_numbered_street_and_exact_five_digits(text):
    assert not any(s.kind == Kind.POSTCODE for s in detect_contact_details(text, "p"))


def test_complete_facility_name_propagates_across_pages_without_bare_aliases():
    from anonymizer.detect.context import detect_facility_repetitions
    from anonymizer.model import Span

    first = PageResult("p0", "s", 0, "Diagnostica Stra\u00dfevelli s.r.l.")
    second = PageResult(
        "p1",
        "s",
        1,
        "\U0001f600 DIAGNOSTICA  STRASSEVELLI\n"
        "Diagnostica Monteluna; Stra\u00dfevelli; Diagnostica differenziale",
    )
    seeds = detect_contact_details(first.text, first.page_id)
    repeated = detect_facility_repetitions([first, second], seeds)
    assert [second.text[s.start : s.end] for s in repeated if s.page_id == "p1"] == [
        "DIAGNOSTICA  STRASSEVELLI"
    ]
    assert all(s.entity_id is None and s.level == 1 for s in repeated)
    analysis = analyze_text([first, second])
    assert "DIAGNOSTICA  STRASSEVELLI" not in analysis.result.pages[1].text
    assert "Diagnostica Monteluna; Stra\u00dfevelli; Diagnostica differenziale" in (
        analysis.result.pages[1].text
    )
    unchecked = Span("p0", 0, len(first.text), Kind.FACILITY, 3, "ner:gliner")
    assert detect_facility_repetitions([first, second], [unchecked]) == []


def test_facility_repetitions_allow_one_wrapped_line_not_paragraphs():
    from anonymizer.detect.context import detect_facility_repetitions

    first = PageResult("p0", "s", 0, "Centro Analisi Vallerin s.r.l.")
    second = PageResult(
        "p1",
        "s",
        1,
        "Centro Analisi\r\n Vallerin; Centro Analisi\n\nVallerin; Centro Analisi Vallerino",
    )
    spans = detect_facility_repetitions([first, second], detect_contact_details(first.text, "p0"))
    assert [second.text[s.start : s.end] for s in spans if s.page_id == "p1"] == [
        "Centro Analisi\r\n Vallerin"
    ]


@pytest.mark.parametrize("separator", [", ", " - ", "\n", "\r\n"])
def test_complete_address_with_city_province_and_bounded_separators(separator):
    text = "Via Monteluna, 12/A" + separator + "12345, San Vallerin (PV) Tel. 0123456789"
    spans = detect_contact_details(text, "p")
    assert [(text[s.start : s.end], s.kind) for s in spans] == [
        ("Via Monteluna, 12/A", Kind.ADDRESS),
        ("12345", Kind.POSTCODE),
        ("San Vallerin (PV)", Kind.LOCATION),
    ]


@pytest.mark.parametrize(
    "tail",
    [
        "Referto Analisi Risultati",
        "Pressione Arteriosa 120/80",
        "Interpretazione dei Risultati",
        "Valleverde123",
        "\nValleverde",
    ],
)
def test_postcode_does_not_turn_clinical_headings_or_paragraphs_into_city(tail):
    text = "Via Roma 12 12345\n" + tail
    assert not any(s.kind == Kind.LOCATION for s in detect_contact_details(text, "p"))


def test_reused_italian_street_vocabulary_and_lowercase_label_evidence():
    text = "Indirizzo: lungomare dei salici 12 12345 Valleverde"
    spans = detect_contact_details(text, "p")
    assert [(text[s.start : s.end], s.kind) for s in spans] == [
        ("lungomare dei salici 12", Kind.ADDRESS),
        ("12345", Kind.POSTCODE),
        ("Valleverde", Kind.LOCATION),
    ]
    assert detect_contact_details("lungomare dei salici 12", "p") == []


def test_adjacent_contact_evidence_never_crosses_blank_block():
    text = "Clinica Vallerin\nVia Roma 12 12345 Valleverde"
    assert any(s.kind == Kind.FACILITY for s in detect_contact_details(text, "p"))
    text = text.replace("\n", "\n\n")
    assert not any(s.kind == Kind.FACILITY for s in detect_contact_details(text, "p"))


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_adjacent_contact_evidence_handles_all_newlines(newline):
    text = "Clinica Vallerin" + newline + "Via Roma 12 12345 Valleverde"
    assert any(s.kind == Kind.FACILITY for s in detect_contact_details(text, "p"))
    text = text.replace(newline, newline * 2)
    assert not any(s.kind == Kind.FACILITY for s in detect_contact_details(text, "p"))


@pytest.mark.parametrize("brand", ["VallerinLab", "Astravelli Servizi"])
def test_bare_legal_facility_needs_adjacent_contact_evidence(brand):
    text = brand + " s.r.l.\nVia Roma 12 12345 Valleverde\nTel. 0123456789"
    found = [s for s in detect_contact_details(text, "p") if s.kind == Kind.FACILITY]
    assert [(text[s.start : s.end], s.origin) for s in found] == [
        (brand + " s.r.l.", "context:facility")
    ]


@pytest.mark.parametrize(
    "text",
    [
        "VallerinLab s.r.l.",
        "VallerinLab s.r.l.\n\nVia Roma 12 12345 Valleverde",
        "Analisi Risultati srl\nTel. 0123456789",
        "Terapia Farmaco srl\nTel. 0123456789",
        "Il paziente assume VallerinLab s.r.l.\nTel. 0123456789",
        "VallerinLab s.r.l. migliora il risultato\nTel. 0123456789",
    ],
)
def test_bare_legal_facility_rejects_prose_headings_and_separate_blocks(text):
    assert not any(s.kind == Kind.FACILITY for s in detect_contact_details(text, "p"))


def test_bare_legal_facility_reuses_contact_url_rule_without_bibliography():
    text = (
        "VallerinLab s.r.l.\nTel. 0123456789\nwww.vallerin-example.it\n\n"
        "Bibliografia https://example.org/scientific-study"
    )
    spans = detect_contact_details(text, "p")
    assert [text[s.start : s.end] for s in spans if s.origin == "context:facility_web"] == [
        "www.vallerin-example.it"
    ]
    assert not any(s.start <= text.index("https://example.org") < s.end for s in spans)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Cognome: Vallerin Nome: Lucia", ["Vallerin", "Lucia"]),
        ("Nome: Maria Teresa; Cognome: De Santis", ["Maria Teresa", "De Santis"]),
        ("Cognome: D\u2019\u00c1vori\r\nNome: Zo\u00eb", ["D\u2019\u00c1vori", "Zo\u00eb"]),
    ],
)
def test_separate_name_fields_require_explicit_nearby_pair(text, expected):
    text = "\U0001f600 " + text
    found = [s for s in detect_patient_labels(text, "p") if s.origin == "context:patient_field"]
    assert [text[s.start : s.end] for s in found] == expected
    assert all(s.entity_id is None and s.level == 1 for s in found)


@pytest.mark.parametrize(
    "text",
    [
        "Nome: Ferritina",
        "Cognome: Vallerin",
        "Nome: Lucia\n\nCognome: Vallerin",
        "Nome: Lucia\nHb 12 g/dL\nCognome: Vallerin",
        "Nome: Lucia Nome: Elena",
        "Cognome: IN BUONE CONDIZIONI Nome: Lucia",
    ],
)
def test_separate_fields_never_capture_isolated_values_or_clinical_blocks(text):
    assert not any(s.origin == "context:patient_field" for s in detect_patient_labels(text, "p"))


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Dott. M. Vallerin", "M. Vallerin"),
        ("Refertante: L. De Santis", "L. De Santis"),
        ("Firmato digitalmente da:\nM. L. Astravelli", "M. L. Astravelli"),
        ("Direttrice sanitaria: Z. D\u2019\u00c1vori", "Z. D\u2019\u00c1vori"),
    ],
)
def test_initials_only_with_explicit_medical_signature_context(text, expected):
    found = detect_doctors(text, "p")
    assert [text[s.start : s.end] for s in found] == [expected]


@pytest.mark.parametrize(
    "text",
    [
        "M. Vallerin",
        "Dr. P. C. R.",
        "Dott. M. 120",
        "Direttore sanitario M. Vallerin",
        "Dott. P. PROTEINA REATTIVA",
    ],
)
def test_initials_do_not_enable_bare_names_acronyms_or_clinical_phrases(text):
    assert detect_doctors(text, "p") == []


@pytest.mark.parametrize("label", ["Medico curante:", "Refertante:", "Firmato da:"])
@pytest.mark.parametrize("value", ["Centro Autorizzato", "Codice Fiscale", "M. Centro Autorizzato"])
def test_doctor_labels_preserve_administrative_stops_with_and_without_initials(label, value):
    assert detect_doctors(label + " " + value, "p") == []
