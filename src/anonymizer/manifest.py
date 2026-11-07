"""!
@file manifest.py
@brief Serializzazione JSON e conferma del manifesto di revisione visiva.

Ricostruisce le strutture immutabili dal JSON, aggiorna i manifesti privi di audit NER
richiedendone una nuova revisione e sigilla la revisione confermata con un'impronta.
"""

import json
from dataclasses import asdict, replace

from anonymizer.model import PageResult, TextRegion, Warning
from anonymizer.ner_model import NerAudit
from anonymizer.visual_model import (
    DocumentError,
    ReviewManifest,
    ReviewWarning,
    SourcePageGeometry,
    SourceRecord,
    VisualPage,
    VisualRedaction,
    review_digest,
    validate_manifest,
)


def dumps(manifest: ReviewManifest) -> str:
    """!
    @brief Valida e serializza il manifesto in JSON indentato.
    @param manifest Manifesto da serializzare.
    @return Testo JSON del manifesto.
    @throws DocumentError Se il manifesto non è coerente.
    """
    validate_manifest(manifest)
    return json.dumps(asdict(manifest), ensure_ascii=False, allow_nan=False, indent=2)


def loads(raw: str) -> ReviewManifest:
    """!
    @brief Carica e valida un manifesto di revisione da JSON.

    Un manifesto senza audit NER viene trattato come precedente al suo arrivo: l'impronta
    di revisione è azzerata e ogni pagina riceve un avviso bloccante, così che la
    revisione debba essere ripetuta.
    @param raw Testo JSON prodotto da dumps().
    @return Manifesto ricostruito e validato.
    @throws DocumentError Con codice `invalid_review_manifest` per qualsiasi errore di
        formato o di coerenza.
    """
    try:
        root = json.loads(raw)
        sources = tuple(SourceRecord(**source) for source in root.pop("sources"))
        pages = []
        for item in root.pop("pages"):
            data = item.pop("page")
            regions = tuple(
                TextRegion(
                    **{**region, "box": tuple(region["box"]) if region["box"] is not None else None}
                )
                for region in data.pop("regions")
            )
            warnings = tuple(
                Warning(**{**warning, "span_ids": tuple(warning["span_ids"])})
                for warning in data.pop("warnings")
            )
            page = PageResult(**data, regions=regions, warnings=warnings)
            geometry = item.pop("geometry")
            for key in ("pdf_media_box", "pdf_crop_box", "pdf_device", "ocr_to_original"):
                if geometry.get(key) is not None:
                    geometry[key] = tuple(geometry[key])
            masks = tuple(
                VisualRedaction(
                    **{
                        **mask,
                        "polygon": tuple(tuple(point) for point in mask["polygon"]),
                        "candidate_ids": tuple(mask["candidate_ids"]),
                    }
                )
                for mask in item.pop("redactions")
            )
            review_warnings = tuple(
                ReviewWarning(
                    **{
                        **warning,
                        "candidate_ids": tuple(warning["candidate_ids"]),
                    }
                )
                for warning in item.pop("warnings")
            )
            pages.append(
                VisualPage(
                    page,
                    item.pop("source_page_index"),
                    SourcePageGeometry(**geometry),
                    masks,
                    review_warnings,
                    tuple(item.pop("required_candidate_ids")),
                    tuple(item.pop("required_redaction_ids")),
                    **item,
                )
            )
        root["page_order"] = tuple(root["page_order"])
        audit = root.pop("ner_audit", None)
        if audit is None:
            root["reviewed_digest"] = None
            root["ner_audit"] = NerAudit(reason="legacy_manifest_not_recorded")
            pages = [
                replace(
                    page,
                    warnings=(*page.warnings, ReviewWarning("legacy_ner_audit_requires_review")),
                )
                for page in pages
            ]
        else:
            audit["labels"] = tuple(audit["labels"])
            root["ner_audit"] = NerAudit(**audit)
        manifest = ReviewManifest(sources, tuple(pages), **root)
        validate_manifest(manifest)
        return manifest
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, OverflowError):
        raise DocumentError("invalid_review_manifest") from None


def confirm_review(manifest: ReviewManifest) -> ReviewManifest:
    """!
    @brief Conferma la revisione accettando tutte le mascherature e gli avvisi.

    Registra l'impronta del contenuto confermato e verifica il risultato con i
    controlli della revisione completa.
    @param manifest Manifesto da confermare.
    @return Nuovo manifesto confermato con impronta di revisione.
    @throws DocumentError Se il manifesto confermato non supera la validazione.
    """
    pages = tuple(
        replace(
            item,
            redactions=tuple(replace(mask, confirmed=True) for mask in item.redactions),
            warnings=tuple(replace(warning, acknowledged=True) for warning in item.warnings),
        )
        for item in manifest.pages
    )
    reviewed = replace(manifest, pages=pages, reviewed_digest=None)
    reviewed = replace(reviewed, reviewed_digest=review_digest(reviewed))
    validate_manifest(reviewed, reviewed=True)
    return reviewed
