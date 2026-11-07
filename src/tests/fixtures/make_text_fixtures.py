import json
from dataclasses import asdict
from pathlib import Path

from anonymizer.cf import checksum
from anonymizer.model import PageResult
from anonymizer.patient import KnownIdentity
from anonymizer.text_pipeline import analyze_text

ROOT = Path(__file__).parent


def occurrences(text, value):
    cursor = 0
    while True:
        start = text.find(value, cursor)
        if start < 0:
            return
        yield start, start + len(value)
        cursor = start + len(value)


def main():
    code = "VLTLVE80C03L219" + checksum("VLTLVE80C03L219")
    templates = [
        (
            "header",
            "Clinica del Glicine\nElvio Veltrani\nCF {cf}\nNon febbre. Hb 12.5 g/dL.",
            [("Clinica del Glicine", "FACILITY"), ("Elvio Veltrani", "PERSON"), (code, "CF")],
            ["Non febbre", "Hb 12.5 g/dL"],
        ),
        (
            "table",
            "Nerina Serralvi\nEsame\tValore\tUnità\nNa\t140\tmmol/L\nK\t4.2\tmmol/L",
            [("Nerina Serralvi", "PERSON")],
            ["Na\t140\tmmol/L", "K\t4.2\tmmol/L"],
        ),
        (
            "multiple_people",
            "Elvio Veltrani; familiare Nerina Serralvi. Nessun dolore alla testa.",
            [("Elvio Veltrani", "PERSON"), ("Nerina Serralvi", "PERSON")],
            ["Nessun dolore alla testa"],
        ),
        (
            "dates",
            "Elvio Veltrani, nato il 3 marzo 1980. Visita 03/11/2026. Sesso M.",
            [
                ("Elvio Veltrani", "PERSON"),
                ("3 marzo 1980", "BIRTH_DATE"),
                ("03/11/2026", "DATE"),
            ],
            ["Sesso M"],
        ),
        (
            "contacts",
            "Tel: +39 012 3456789; elvio@example.invalid; CAP: 12345. Hb 12 g/dL.",
            [
                ("+39 012 3456789", "PHONE"),
                ("elvio@example.invalid", "EMAIL"),
                ("12345", "POSTCODE"),
            ],
            ["Hb 12 g/dL"],
        ),
        (
            "doctor",
            "Dott. Tobia Nivori\nOspedale delle Nuvole\nReferto negativo. PA 120/80 mmHg.",
            [("Tobia Nivori", "DOCTOR"), ("Ospedale delle Nuvole", "FACILITY")],
            ["Referto negativo", "PA 120/80 mmHg"],
        ),
        (
            "unicode",
            "😀 e\u0301 Zelia Veltrani\nNessuna febbre; glicemia 98 mg/dL.",
            [("Zelia Veltrani", "PERSON")],
            ["😀 e\u0301", "Nessuna febbre", "98 mg/dL"],
        ),
        (
            "location",
            "Nerina Serralvi, residente a Borgo Sereno. Non allergie note.",
            [("Nerina Serralvi", "PERSON"), ("Borgo Sereno", "LOCATION")],
            ["Non allergie note"],
        ),
        (
            "repeat_header",
            "Clinica del Glicine\nElvio Veltrani\nClinica del Glicine\nNon edema.",
            [("Clinica del Glicine", "FACILITY"), ("Elvio Veltrani", "PERSON")],
            ["Non edema"],
        ),
        (
            "poor_reading",
            "VLTLVE8OC03L219A\n[lettura incerta]\nNa 140 mmol/L; non dispnea.",
            [("VLTLVE8OC03L219A", "CF")],
            ["Na 140 mmol/L", "non dispnea"],
        ),
    ]
    documents = []
    for index, (template, text, identifiers, clinical) in enumerate(templates):
        for repetition in range(2):
            source_text = text.format(cf=code)
            page_id = f"fixture-page-{index}-{repetition}"
            annotations = [
                {"page_id": page_id, "start": start, "end": end, "kind": kind, "observed": value}
                for value, kind in identifiers
                for start, end in occurrences(source_text, value)
            ]
            documents.append(
                {
                    "document_id": f"fixture-document-{index}-{repetition}",
                    "split": "development" if index < 6 else "evaluation",
                    "template_id": template,
                    "synthetic": True,
                    "pages": [
                        {
                            "page_id": page_id,
                            "source_id": f"source-{index}-{repetition}",
                            "index": 0,
                            "text": source_text,
                            "extraction_mode": "text_fixture",
                        }
                    ],
                    "identifiers": annotations,
                    "clinical_invariants": [
                        {"page_id": page_id, "start": start, "end": end, "observed": value}
                        for value in clinical
                        for start, end in occurrences(source_text, value)
                    ],
                    "warnings": ["synthetic_text_only", "no_extraction_quality_measurement"],
                }
            )
    (ROOT / "text_corpus.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "scope": "20 synthetic text smoke samples; no recall guarantee",
                "documents": documents,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    identity = KnownIdentity(
        (),
        id="fixture-entity-patient",
        given_name="Elvio",
        surname="Veltrani",
        role="patient",
        confirmed=True,
    )
    page = PageResult(
        "fixture-page",
        "fixture-source",
        0,
        "😀 Elvio Veltrani; ELVIO VELTRANI; Hb 12 g/dL; non febbre.",
    )
    analysis = analyze_text([page], (identity,))
    first = analysis.result.replacements[0]
    contract = {
        "schema_version": 1,
        "offset_unit": "unicode_codepoint",
        "synthetic": True,
        "pages": [asdict(page)],
        "candidates": [asdict(span) for span in analysis.candidates],
        "entities": [asdict(entity) for entity in analysis.result.map.entities],
        "merged_spans": [asdict(span) for span in analysis.merged_spans],
        "result": asdict(analysis.result),
        "review_examples": [
            {
                "operation": "undo_mask",
                "replacement_id": first.id,
                "restore_observed": first.original,
                "requires_confirmation_for_level_0_1": True,
            },
            {
                "operation": "ocr_correction",
                "page_id": page.page_id,
                "start": 2,
                "end": 7,
                "observed": "Elvio",
                "corrected": "Elvio",
                "invalidates_intersecting_spans": True,
                "invalidates_export_confirmation": True,
            },
            {
                "operation": "conflicting_identity",
                "entity_ids": [identity.id, "other-entity"],
                "must_not_infer_patient": True,
                "requires_review": True,
            },
        ],
        "timings_ms": {},
    }
    (ROOT / "review_contract.json").write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
