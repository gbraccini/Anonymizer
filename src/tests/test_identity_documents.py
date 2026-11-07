import re

import pytest

from anonymizer.detect.dictionary import Vocabulary
from anonymizer.detect.identity_documents import analyze_identity_document
from anonymizer.model import Kind, PageResult, TextRegion
from anonymizer.text_pipeline import analyze_text


def detected(text, regions=()):
    page = PageResult("p", "source", 0, text, regions=regions)
    result = analyze_identity_document(page)
    return result, [(text[s.start : s.end], s.kind, s.origin) for s in result.spans]


def test_cie_bilingual_fields_numbers_dates_and_visible_sex():
    text = (
        "CARTA D'IDENTITA' / IDENTITY CARD\n"
        "COGNOME / SURNAME: D'ARVINO\nNOME / NAME: LUCIA\n"
        "Data di nascita: 03/11/1980\nLuogo di nascita: Valleverde\n"
        "Data di rilascio: 05/11/2020\nScadenza: 05/11/2030\n"
        "CAN: 123456\nAB12345CD\nSesso: F\nStatura: 165"
    )
    result, spans = detected(text)
    assert result.document_types == ("identity_card",)
    for observed in (
        "D'ARVINO",
        "LUCIA",
        "03/11/1980",
        "Valleverde",
        "05/11/2020",
        "05/11/2030",
        "123456",
        "AB12345CD",
    ):
        assert any(value == observed for value, _, _ in spans)
    analysis = analyze_text(
        [PageResult("p", "source", 0, text)], vocabulary=Vocabulary((), (), (), ())
    )
    assert "Sesso: F" in analysis.result.pages[0].text
    assert "Statura: 165" in analysis.result.pages[0].text
    assert "05/11/2030" not in analysis.result.pages[0].text
    assert any(w.code == "identity_document_visual_review" for w in analysis.result.warnings)
    assert all(s.entity_id is None for s in result.spans)


@pytest.mark.parametrize(
    "phrase,number",
    [
        ("carta di identita n. AB1234567", "AB1234567"),
        ("carta d’identità numero AB12345CD", "AB12345CD"),
        ("passaporto n. XY1234567", "XY1234567"),
        ("passaporto numero Z9-12345", "Z9-12345"),
        ("patente di guida n. U1234567X", "U1234567X"),
    ],
)
def test_explicit_document_reference_accepts_serial_and_legacy_number(phrase, number):
    _, spans = detected("Documento presentato: " + phrase + ". Terapia invariata.")
    assert (number, Kind.CASE_NUMBER, "identity:document_number") in spans


def test_licence_numbered_fields_are_not_generic_clinical_numbering():
    fields = (
        "1. VALLERIN\n2. LUCIA\n3. 03/11/1980 VALLEVERDE\n"
        "4a. 05/11/2020\n4b. 05/11/2030\n4c. UCO ROMA\n5. X1234567Z\n"
        "8. Via delle Vele 18 Valleverde"
    )
    result, spans = detected("PATENTE DI GUIDA\n" + fields)
    assert result.document_types == ("driving_licence",)
    assert ("X1234567Z", Kind.CASE_NUMBER, "identity:document_number") in spans
    assert ("VALLEVERDE", Kind.LOCATION, "identity:location") in spans
    assert ("UCO ROMA", Kind.FACILITY, "identity:authority") in spans
    assert any(kind == Kind.ADDRESS for _, kind, _ in spans)
    assert not detected(fields)[1]


@pytest.mark.parametrize(
    "text",
    [
        "Emoglobina AB12345CD; lotto XY1234567; CAN 123456",
        "Il passaporto non è necessario.\nNome: Ferritina\nScadenza: 03/11/2026",
        "5. Glucosio 90 mg/dL\n4a. 03/11/2026\n8. Via orale",
        "Carta di identita valida: controllare la documentazione clinica.",
        "PATENTE DI GUIDA\n5. negativo\nCAN: 123456",
    ],
)
def test_no_uncontextual_serial_can_or_clinical_field_inference(text):
    _, spans = detected(text)
    assert not spans


def mrz_td1():
    return [
        "I<ITAAB12345CD0" + "<" * 15,
        "8001030F3001050FRA" + "<" * 11 + "9",
        "DORVINO<<LUCIA".ljust(30, "<"),
    ]


def mrz_td3(prefix="P<ITA"):
    return [
        (prefix + "DORVINO<<LUCIA").ljust(44, "<"),
        "XY12345670ITA8001030F3001050" + "<" * 14 + "09",
    ]


@pytest.mark.parametrize("lines", [mrz_td1(), mrz_td3(), mrz_td3("PPITA")])
@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_whole_mrz_masked_with_invalid_check_digits_and_ocr_spaces(lines, newline):
    assert all(len(line) == len(lines[0]) for line in lines)
    raw = newline.join(
        " ".join(line[index : index + 5] for index in range(0, len(line), 5)) for line in lines
    )
    text = "😀\n" + raw + "\nSesso: F"
    result, spans = detected(text)
    assert result.recognized
    assert (raw, Kind.CASE_NUMBER, "identity:mrz") in spans
    analysis = analyze_text(
        [PageResult("p", "source", 0, text)], vocabulary=Vocabulary((), (), (), ())
    )
    assert raw not in analysis.result.pages[0].text
    assert "Sesso: F" in analysis.result.pages[0].text


def test_incomplete_or_separated_mrz_does_not_mask_clinical_prose():
    lines = mrz_td1()
    assert not detected("\n".join(lines[:2]))[1]
    assert not detected("\n\n".join(lines))[1]
    assert not detected("\n".join([lines[0], "Risultato nella norma", lines[2]]))[1]


def token_regions(text, positions):
    tokens = list(re.finditer(r"\S+", text))
    return tuple(
        TextRegion(m.start(), m.end(), box) for m, box in zip(tokens, positions, strict=True)
    )


def test_geometry_rejects_remote_value_and_preserves_interposed_reading_order():
    text = "CIE\nCOGNOME\nGlucosio\nVALLERIN\nNOME\nLUCIA"
    boxes = [
        (0, 0, 30, 10),
        (0, 20, 70, 30),
        (400, 20, 470, 30),
        (80, 20, 150, 30),
        (0, 40, 45, 50),
        (55, 40, 105, 50),
    ]
    _, spans = detected(text, token_regions(text, boxes))
    assert ("VALLERIN", Kind.PERSON, "identity:name") in spans
    assert ("LUCIA", Kind.PERSON, "identity:name") in spans
    assert not any("Glucosio" in value for value, _, _ in spans)
    remote = list(boxes)
    remote[3] = (800, 20, 870, 30)
    _, remote_spans = detected(text, token_regions(text, remote))
    assert not any(value == "VALLERIN" for value, _, _ in remote_spans)


def test_label_below_value_unicode_and_coarse_region_offsets():
    text = "CIE\nCOGNOME\nD’ÀRVINO\nNOME: ÉLODIE\nSesso: F"
    regions = tuple(
        TextRegion(m.start(), m.end(), (0, i * 15, 170, i * 15 + 10))
        for i, m in enumerate(re.finditer(r"[^\n]+", text))
    )
    _, spans = detected(text, regions)
    assert ("D’ÀRVINO", Kind.PERSON, "identity:name") in spans
    assert ("ÉLODIE", Kind.PERSON, "identity:name") in spans


def test_distant_document_heading_does_not_activate_clinical_fields():
    text = "CIE\nNome: Ferritina"
    regions = (TextRegion(0, 3, (0, 0, 30, 10)), TextRegion(4, len(text), (600, 900, 780, 910)))
    assert not detected(text, regions)[1]


@pytest.mark.parametrize(
    "text,number",
    [
        ("CIE: CA12345AA", "CA12345AA"),
        ("Patente: U1234567X", "U1234567X"),
        ("Numero carta di identità: CA 12345 AA", "CA 12345 AA"),
        ("Passaporto numero XY 1234567", "XY 1234567"),
        ("Numero patente U1234567X", "U1234567X"),
        ("Numero carta di identità AB1234567", "AB1234567"),
    ],
)
def test_delimited_document_numbers_and_ocr_spaces(text, number):
    assert (number, Kind.CASE_NUMBER, "identity:document_number") in detected(text)[1]


def test_heading_serial_bilingual_dates_and_legacy_passport_fields():
    text = (
        "CARTA D´IDENTITA` / IDENTITY CARD CA12345AA\n"
        "LUOGO E DATA DI NASCITA / PLACE AND DATE OF BIRTH: VALLEVERDE 03/11/1980\n"
        "EMISSIONE / ISSUING: 05/11/2020\nSCADENZA / EXPIRY: 05/11/2030"
    )
    result, spans = detected(text)
    assert result.recognized
    for expected in ("CA12345AA", "VALLEVERDE", "03/11/1980", "05/11/2020", "05/11/2030"):
        assert any(value == expected for value, _, _ in spans)
    assert not any(
        "ISSUING" in value or "EXPIRY" in value or "PLACE" in value for value, _, _ in spans
    )
    passport = "PASSAPORTO\nDATE OF BIRTH: 01 GEN/JAN 1988\nN. passaporto: Z9-12345"
    spans = detected(passport)[1]
    assert ("01 GEN/JAN 1988", Kind.BIRTH_DATE, "identity:birth_date") in spans
    assert ("Z9-12345", Kind.CASE_NUMBER, "identity:document_number") in spans
    assert not any(
        value == "31 FEB/FEB 1988"
        for value, _, _ in detected("PASSAPORTO\nDATE OF BIRTH: 31 FEB/FEB 1988")[1]
    )


def test_mrz_alone_anchors_cie_reverse_fields_and_serial_repeats_same_source_only():
    lines = mrz_td1()
    text = "RESIDENZA: Via delle Vele 12\n" + "\n".join(lines)
    result, spans = detected(text)
    assert result.recognized
    assert ("Via delle Vele 12", Kind.ADDRESS, "identity:address") in spans
    pages = [
        PageResult("p1", "a", 0, "PASSAPORTO\nXY1234567"),
        PageResult("p2", "a", 1, "Numero ripetuto XY 1234567. Dose 5 mg."),
        PageResult("p3", "b", 2, "Lotto XY1234567. Dose 5 mg."),
    ]
    analysis = analyze_text(pages, vocabulary=Vocabulary((), (), (), ()))
    assert "XY 1234567" not in analysis.result.pages[1].text
    assert analysis.result.pages[2].text == pages[2].text
    assert "Dose 5 mg." in analysis.result.pages[1].text


def test_serial_seed_from_mrz_and_short_legacy_code_not_propagated():
    pages = [
        PageResult("p1", "a", 0, "\n".join(mrz_td3())),
        PageResult("p2", "a", 1, "XY1234567"),
        PageResult("p3", "a", 2, "Passaporto numero Z123"),
        PageResult("p4", "a", 3, "Lotto Z123"),
    ]
    analysis = analyze_text(pages, vocabulary=Vocabulary((), (), (), ()))
    assert "XY1234567" not in analysis.result.pages[1].text
    assert analysis.result.pages[3].text == "Lotto Z123"


def test_mrz_structural_positions_without_double_filler_and_ocr_digit_errors():
    lines = mrz_td1()
    lines[1] = lines[1].replace("0", "O")
    lines[2] = "DORVINO".ljust(30, "<").replace("<<", "<A")
    assert detected("\n".join(lines))[0].recognized
    lines[1] = lines[1][:7] + "Q" + lines[1][8:]
    assert not any(origin == "identity:mrz" for _, _, origin in detected("\n".join(lines))[1])


@pytest.mark.parametrize("prefix", ["C<ITA", "I<ITA", "A<ITA", "CAITA"])
def test_td1_document_code_variants(prefix):
    lines = mrz_td1()
    lines[0] = prefix + lines[0][5:]
    assert any(origin == "identity:mrz" for _, _, origin in detected("\n".join(lines))[1])


def test_damaged_td1_requires_structure_and_geometric_alignment_without_invented_serial():
    from dataclasses import replace

    lines = mrz_td1()
    lines = [lines[0] + "<<<<<<", lines[1] + "<<", lines[2]]
    text = "\n".join(lines)
    regions, offset = [], 0
    for i, line in enumerate(lines):
        regions.append(TextRegion(offset, offset + len(line), (10, i * 15, 400, i * 15 + 12)))
        offset += len(line) + 1
    spans = detected(text, regions)[1]
    assert (text, Kind.CASE_NUMBER, "identity:mrz") in spans
    assert not any(origin == "identity:document_number" for _, _, origin in spans)
    regions[-1] = replace(regions[-1], box=(600, 80, 990, 92))
    assert not detected(text, regions)[0].recognized
    bad = text.replace("ITA", "AAA", 1)
    assert not detected(bad)[0].recognized
    assert detected("CODICE FISCALE\nRESIDENZA\nESTREMI ATTO DI NASCITA\n" + bad)[0].recognized
    clinical = "Esame A < 30\nGlucosio 90 F 12\nValore << risultato"
    assert not detected(clinical)[0].recognized


def test_damaged_td1_lost_prefix_requires_reverse_fields_and_keeps_ocr_offsets():
    from dataclasses import replace

    lines = ["<ZZZZZ1Z2Z3ZZ4ZZZZZZZZZZZZZZZ<Z<Z<", mrz_td1()[1], mrz_td1()[2].lower()]
    prefix = "CODICE FISCALE\nRESIDENZA\nPADRE E MADRE\n"
    text = prefix + "\n".join(lines)
    regions, offset = [], len(prefix)
    for line, box in zip(
        lines, [(10, 100, 400, 131), (10, 125, 400, 182), (10, 204, 400, 233)], strict=True
    ):
        regions.append(TextRegion(offset, offset + len(line), box))
        offset += len(line) + 1
    spans = detected(text, regions)[1]
    assert ("\n".join(lines), Kind.CASE_NUMBER, "identity:mrz") in spans
    assert not any(origin == "identity:document_number" for _, _, origin in spans)
    assert not detected("\n".join(lines))[0].recognized
    regions[-1] = replace(regions[-1], box=(600, 204, 990, 233))
    assert not detected(text, regions)[0].recognized


@pytest.mark.parametrize(
    "prefix", ["COPIA ", "COPIA DELLA ", "FAC-SIMILE - ", "FACSIMILE DI PROVA - ", "DOCUMENTO: "]
)
def test_explicit_copy_heading_prefixes_without_narrative_activation(prefix):
    text = prefix + "CARTA DI IDENTITA\nCOGNOME: VALLERIN"
    assert detected(text)[0].recognized
    assert not detected("Il paziente ha smarrito la patente\nNOME: Ferritina")[0].recognized


def test_licence_heading_does_not_turn_numbered_medical_list_into_identity_fields():
    text = (
        "PATENTE DI GUIDA\nEsami richiesti\n1. Emocromo\n"
        "2. Elettrocardiogramma\n3. Visita medica\n5. 92 mg/dL"
    )
    assert not detected(text)[1]
    assert detected("PATENTE DI GUIDA\n5. U1234567X")[1] == [
        ("U1234567X", Kind.CASE_NUMBER, "identity:document_number")
    ]
    genuine = (
        "PATENTE DI GUIDA\n1. VALLERIN\n2. LUCIA\n3. 03/11/1980 VALLEVERDE\n"
        "5. U1234567X\nTerapia: 2 compresse ogni 8 ore per 7 giorni"
    )
    assert not any("ore" in value or "giorni" in value for value, _, _ in detected(genuine)[1])


def test_consecutive_licence_date_fields_on_one_line_and_french_accents():
    text = "PATENTE DI GUIDA\n4a. 05/11/2020 4b. 05/11/2030 5. U1234567X"
    spans = detected(text)[1]
    for value in ("05/11/2020", "05/11/2030", "U1234567X"):
        assert any(observed == value for observed, _, _ in spans)
    passport = "PASSAPORTO\nDATA DI RILASCIO / DATE OF ISSUE / DATE DE DÉLIVRANCE: 05/11/2020"
    assert ("05/11/2020", Kind.DATE, "identity:date") in detected(passport)[1]


def test_document_title_segment_requires_correlated_identity_field_cluster():
    heading = "FAC SIMILE CARTA DI IDENTITÀ CARD ANNOTAZIONE PUBBLICA"
    fields = "\nCOGNOME: VALLERIN\nNOME: LUCIA\nDATA DI NASCITA: 03/11/1980"
    result, spans = detected(heading + fields + "\nCOMUNE DI / MUNICIPALITY: VALLEVERDE")
    assert result.recognized
    assert ("VALLEVERDE", Kind.FACILITY, "identity:authority") in spans
    assert ("LUCIA", Kind.PERSON, "identity:name") in spans
    assert not detected(heading + "\nNOME: Ferritina")[0].recognized
    assert not detected("Il paziente ha smarrito la carta di identità\nVisita: 03/11/2026")[
        0
    ].recognized


@pytest.mark.parametrize("geometry", [False, True])
def test_cie_parent_names_and_birth_registration_do_not_mask_labels(geometry):
    lines = [
        "CARTA DI IDENTITA ELETTRONICA",
        "COGNOME E NOME DEL PADRE E DELLA MADRE O DI CHI NE FA LE VECI / "
        "FATHER AND MOTHER’S-TUTOR’S NAME",
        "VALLERIN LUCIA",
        "ESTREMI ATTO DI NASCITA: 00000.0.A00",
    ]
    text = "\n".join(lines)
    regions, start = [], 0
    for index, line in enumerate(lines):
        regions.append(TextRegion(start, start + len(line), (0, index * 15, 900, index * 15 + 12)))
        start += len(line) + 1
    spans = detected(text, regions if geometry else ())[1]
    assert ("VALLERIN LUCIA", Kind.PERSON, "identity:name") in spans
    assert ("00000.0.A00", Kind.CASE_NUMBER, "identity:registration") in spans
    assert not any("PADRE" in value or "FATHER" in value for value, _, _ in spans)


@pytest.mark.parametrize("heading", ["CIE", "CARTA DI IDENTITA ELETTRONICA"])
def test_unlabelled_can_requires_electronic_identity_card(heading):
    text = heading + " / IDENTITY CAF CA12345AA\n123456\n92 mg/dL"
    assert ("123456", Kind.CASE_NUMBER, "identity:can") in detected(text)[1]
    for title in ("PASSAPORTO", "PATENTE DI GUIDA", "CARTA DI IDENTITA"):
        assert not any(origin == "identity:can" for _, _, origin in detected(title + "\n123456")[1])
    clinical = heading + "\nGlicemia 123456 mg/dL"
    regions = []
    for match in re.finditer(r"\S+", clinical):
        y = 0 if match.start() < len(heading) else 20
        regions.append(
            TextRegion(match.start(), match.end(), (match.start(), y, match.end(), y + 10))
        )
    assert not any(origin == "identity:can" for _, _, origin in detected(clinical, regions)[1])


def test_can_isolated_in_its_column_and_ocr_serial_digit_confusion():
    lines = ["CARTA DI IDENTITA ELETTRONICA", "CAOOOOOAA", "Annotazione esterna 123456"]
    text = "\n".join(lines)
    start = text.index("Annotazione")
    number = text.index("123456")
    regions = (
        TextRegion(0, len(lines[0]), (100, 0, 400, 15)),
        TextRegion(len(lines[0]) + 1, start - 1, (100, 20, 210, 35)),
        TextRegion(start, number - 1, (0, 50, 120, 65)),
        TextRegion(number, number + 6, (400, 50, 470, 65)),
    )
    spans = detected(text, regions)[1]
    assert ("CAOOOOOAA", Kind.CASE_NUMBER, "identity:document_number") in spans
    assert ("123456", Kind.CASE_NUMBER, "identity:can") in spans


def test_remote_annotation_on_same_row_does_not_hide_nearby_card_label():
    text = "CARTA DI IDENTITA\nAnnotazione esterna COGNOME: VALLERIN"
    surname = text.index("COGNOME")
    value = text.index("VALLERIN")
    regions = (
        TextRegion(0, 16, (700, 0, 960, 15)),
        TextRegion(17, surname - 1, (0, 40, 140, 55)),
        TextRegion(surname, value - 1, (800, 40, 900, 55)),
        TextRegion(value, len(text), (910, 40, 1000, 55)),
    )
    assert ("VALLERIN", Kind.PERSON, "identity:name") in detected(text, regions)[1]


def test_vertical_caption_and_damaged_translation_do_not_join_field_value_rows():
    entries = [
        ("CARTA DI IDENTITA", (200, 0, 430, 15)),
        ("VERTICALE", (10, 20, 18, 110)),
        ("COGNOME", (200, 30, 280, 43)),
        ("/", (285, 30, 290, 43)),
        ("SURNAME", (295, 30, 370, 43)),
        ("VALLERIN", (200, 49, 280, 64)),
        ("NOME", (200, 75, 245, 88)),
        ("/", (250, 75, 255, 88)),
        ("NAHE", (260, 75, 305, 88)),
        ("LUCIA", (200, 94, 250, 109)),
    ]
    text, regions = "", []
    for value, box in entries:
        start = len(text)
        text += value + "\n"
        regions.append(TextRegion(start, start + len(value), box))
    spans = detected(text, tuple(regions))[1]
    assert ("VALLERIN", Kind.PERSON, "identity:name") in spans
    assert ("LUCIA", Kind.PERSON, "identity:name") in spans
    assert not any(value == "NAHE" for value, _, _ in spans)


@pytest.mark.parametrize("province", ["(VA)", "{VA}", "[VA]"])
def test_birth_place_long_municipality_with_province_and_date_preserves_other_fields(province):
    text = (
        "CARTA DI IDENTITA\nLUOGO E DATA DI NASCITA: "
        f"BORGO SULLA SPONDA DEL LAGO VERDE {province} 30.12.1964 SESSO: F STATURA: 180"
    )
    spans = detected(text)[1]
    assert (
        f"BORGO SULLA SPONDA DEL LAGO VERDE {province}",
        Kind.LOCATION,
        "identity:location",
    ) in spans
    assert ("30.12.1964", Kind.BIRTH_DATE, "identity:birth_date") in spans
    assert not any("SESSO" in value or "STATURA" in value for value, _, _ in spans)


def test_birth_field_below_translation_ignores_remote_caption_and_reads_split_province():
    lines = [
        "CARTA DI IDENTITA",
        "LUOGO E DATA DI NASCITA",
        "PLACE AND DATE OF BIRTH",
        "BORGO SULLA SPONDA DEL LAGO VERDE { VA } 30.12.1964 SESSO F",
    ]
    text = "\n".join(lines)
    regions = []
    for index, line in enumerate(lines):
        start = sum(len(value) + 1 for value in lines[:index])
        x = 200
        for match in re.finditer(r"\S+", line):
            width = len(match.group()) * 6
            regions.append(
                TextRegion(
                    start + match.start(),
                    start + match.end(),
                    (x, index * 20, x + width, index * 20 + 14),
                )
            )
            x += width + 4
    caption_start = len(text) + 1
    text += "\nANNOTAZIONE"
    regions.append(TextRegion(caption_start, len(text), (0, 35, 100, 75)))
    spans = detected(text, regions)[1]
    assert ("BORGO SULLA SPONDA DEL LAGO VERDE { VA }", Kind.LOCATION, "identity:location") in spans
    assert ("30.12.1964", Kind.BIRTH_DATE, "identity:birth_date") in spans
    assert not any("SESSO" in value for value, _, _ in spans)


@pytest.mark.parametrize("geometry", [False, True])
def test_trilingual_passport_labels_preserve_original_offsets(geometry):
    lines = [
        "PASSAPORTO",
        "COGNOME / SURNAME / NOM",
        "VALLERIN",
        "NOME / GIVEN NAMES / PRÉNOMS",
        "LUCIA",
        "DATA DI NASCITA / DATE OF BIRTH / DATE DE NAISSANCE",
        "01 GEN/JAN 1988",
        "AUTORITA / AUTHORITY / AUTORITÉ",
        "QUESTURA DI ROMA",
    ]
    text = "\n".join(lines)
    regions = []
    start = 0
    for index, line in enumerate(lines):
        regions.append(TextRegion(start, start + len(line), (0, index * 15, 450, index * 15 + 12)))
        start += len(line) + 1
    spans = detected(text, tuple(regions) if geometry else ())[1]
    for value in ("VALLERIN", "LUCIA", "01 GEN/JAN 1988", "QUESTURA DI ROMA"):
        assert any(observed == value for observed, _, _ in spans)
    assert not any("NOM" in value or "AUTORITE" in value for value, _, _ in spans)


def test_reverse_identity_bilingual_parent_tax_code_and_damaged_date_fields():
    text = (
        "CARTA DI IDENTITA\nFATHER AND MOTHER'S-TUTOR'S NAME\nVALLERIN LUCIA\n"
        "FISCAL CODE\n.DVRLCU80A01H501\nESTREMI ATTO DI NASCITA\n00000.0.A00\n"
        "INDIRIZZO DI RESIDENZA / RESIDENCE\nVIA DEL BORGO, 12\n"
        "EMISSIONE: 31.02.2020\n"
    )
    spans = detected(text)[1]
    for value, kind, origin in (
        ("VALLERIN LUCIA", Kind.PERSON, "identity:name"),
        ("DVRLCU80A01H501", Kind.CF, "identity:tax_code"),
        ("00000.0.A00", Kind.CASE_NUMBER, "identity:registration"),
        ("VIA DEL BORGO, 12", Kind.ADDRESS, "identity:address"),
        ("31.02.2020", Kind.DATE, "identity:date"),
    ):
        assert (value, kind, origin) in spans
    assert not detected(text.replace("CARTA DI IDENTITA\n", ""))[0].recognized


def test_supplemental_primary_regions_do_not_interleave_secondary_identity_labels():
    entries = [
        ("CARTA DI IDENTITA", (100, 0, 330, 15), None),
        ("COGNOME", (100, 30, 180, 44), None),
        ("VALLERIN", (100, 50, 180, 64), None),
        ("NOME", (100, 80, 145, 94), None),
        ("LUCIA", (100, 100, 150, 114), None),
        ("LETTURA", (185, 30, 260, 44), "primary:1"),
    ]
    text, regions = "", []
    for value, box, block in entries:
        start = len(text)
        text += value + "\n"
        regions.append(TextRegion(start, start + len(value), box, block_id=block))
    spans = detected(text, regions)[1]
    assert ("VALLERIN", Kind.PERSON, "identity:name") in spans
    assert ("LUCIA", Kind.PERSON, "identity:name") in spans
