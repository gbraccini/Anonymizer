"""!
@file review.py
@brief Contratti di analisi firmati e applicazione delle modifiche di revisione.

Il manifest prodotto dall'analisi torna al client firmato con HMAC, così le
richieste successive lo riutilizzano senza che il server debba conservarlo.
"""

import hashlib
import hmac
import json
import time
from dataclasses import asdict, replace

from anonymizer.manifest import loads
from anonymizer.visual_model import (
    DocumentError,
    ReviewManifest,
    VisualRedaction,
    review_digest,
    validate_manifest,
)


def canonical(value):
    """!
    @brief Serializza un valore in JSON canonico, con chiavi ordinate e senza spazi.
    @param value Valore serializzabile in JSON.
    @return Byte UTF-8 della rappresentazione canonica.
    """
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


class ReviewSigner:
    """!
    @brief Firma e verifica con HMAC-SHA256 i contratti di analisi a scadenza.
    """

    def __init__(self, key: bytes, lifetime: int = 3600):
        """!
        @brief Crea il firmatario.
        @param key Chiave segreta HMAC.
        @param lifetime Validità del contratto in secondi.
        """
        self.key, self.lifetime = key, lifetime

    def issue(self, manifest: ReviewManifest):
        """!
        @brief Emette un contratto firmato per il manifest.
        @param manifest Manifest di revisione prodotto dall'analisi.
        @return Coppia (contratto con payload canonico, firma esadecimale).
        """
        contract = dict(manifest=asdict(manifest), expires=int(time.time()) + self.lifetime)
        payload = canonical(contract)
        return dict(**contract, payload=payload.decode()), hmac.new(
            self.key, payload, hashlib.sha256
        ).hexdigest()

    def verify(self, contract, signature):
        """!
        @brief Verifica firma, coerenza e scadenza di un contratto.
        @param contract Contratto ricevuto dal client.
        @param signature Firma esadecimale ricevuta dal client.
        @return Manifest ricostruito dal payload firmato.
        @throws DocumentError Se la firma non è valida o il contratto è scaduto.
        """
        if not isinstance(contract, dict) or set(contract) != {"manifest", "expires", "payload"}:
            raise DocumentError("analysis_contract_signature_invalid")
        if not isinstance(contract["payload"], str):
            raise DocumentError("analysis_contract_signature_invalid")
        expected = hmac.new(self.key, contract["payload"].encode(), hashlib.sha256).hexdigest()
        if not isinstance(signature, str) or not hmac.compare_digest(expected, signature):
            raise DocumentError("analysis_contract_signature_invalid")
        trusted = json.loads(contract["payload"])
        if trusted != {key: value for key, value in contract.items() if key != "payload"}:
            raise DocumentError("analysis_contract_signature_invalid")
        if type(trusted.get("expires")) is not int or trusted["expires"] < time.time():
            raise DocumentError("analysis_contract_expired")
        return loads(json.dumps(trusted["manifest"]))


def apply_review(base: ReviewManifest, edits: dict, *, final: bool = False):
    """!
    @brief Applica al manifest firmato le modifiche di revisione inviate dal client.

    Valida le decisioni sulle maschere, la presa visione degli avvisi e le maschere
    manuali (solo rettangolari). Per l'esportazione finale richiede la conferma
    esplicita e che il digest coincida con quello dell'ultima anteprima.
    @param base Manifest di partenza già verificato.
    @param edits Modifiche di revisione.
    @param final True per l'esportazione definitiva.
    @return Manifest revisionato e validato.
    @throws DocumentError Se le modifiche non sono valide o la revisione finale non
            è confermata.
    """
    if not isinstance(edits, dict) or not edits.keys() <= {
        "decisions",
        "acknowledgments",
        "manual_masks",
        "final_confirmation",
        "preview_digest",
    }:
        raise DocumentError("invalid_review_edits")
    decisions = edits.get("decisions", {})
    acknowledgments = edits.get("acknowledgments", {})
    manuals = edits.get("manual_masks", [])
    if not isinstance(decisions, dict) or not isinstance(acknowledgments, dict):
        raise DocumentError("invalid_review_edits")
    if not isinstance(manuals, list) or len(manuals) > 1000:
        raise DocumentError("manual_mask_limit")
    existing = {mask.id for page in base.pages for mask in page.redactions}
    page_ids = {page.page.page_id for page in base.pages}
    if not decisions.keys() <= existing or not acknowledgments.keys() <= page_ids:
        raise DocumentError("unknown_review_identity")
    additions = {}
    for item in manuals:
        if not isinstance(item, dict) or set(item) != {
            "id",
            "page_id",
            "polygon",
            "confirmed",
            "candidate_ids",
        }:
            raise DocumentError("invalid_manual_mask")
        if item["id"] in existing or item["page_id"] not in page_ids:
            raise DocumentError("unknown_or_duplicate_manual_identity")
        if not isinstance(item["id"], str) or not 1 <= len(item["id"]) <= 100:
            raise DocumentError("invalid_manual_mask_id")
        existing.add(item["id"])
        mask = VisualRedaction(
            item["page_id"],
            tuple(tuple(point) for point in item["polygon"]),
            "manual",
            tuple(item["candidate_ids"]),
            id=item["id"],
            confirmed=item["confirmed"],
        )
        if len({p[0] for p in mask.polygon}) != 2 or len({p[1] for p in mask.polygon}) != 2:
            raise DocumentError("manual_rectangles_only")
        additions.setdefault(item["page_id"], []).append(mask)
    pages = []
    for page in base.pages:
        masks = []
        for mask in page.redactions:
            decision = decisions.get(mask.id, {})
            if not isinstance(decision, dict) or not decision.keys() <= {
                "decision",
                "reason",
                "confirmed",
            }:
                raise DocumentError("invalid_mask_decision")
            masks.append(replace(mask, **decision))
        ack = acknowledgments.get(page.page.page_id, [])
        if not isinstance(ack, list) or any(
            type(index) is not int or not 0 <= index < len(page.warnings) for index in ack
        ):
            raise DocumentError("invalid_warning_acknowledgment")
        pages.append(
            replace(
                page,
                redactions=tuple(masks + additions.get(page.page.page_id, [])),
                warnings=tuple(
                    replace(w, acknowledged=i in ack) for i, w in enumerate(page.warnings)
                ),
            )
        )
    manifest = replace(base, pages=tuple(pages), reviewed_digest=None)
    validate_manifest(manifest)
    if final:
        if edits.get("final_confirmation") is not True:
            raise DocumentError("final_review_confirmation_required")
        if edits.get("preview_digest") != review_digest(manifest):
            raise DocumentError("review_changed_since_preview")
        manifest = replace(manifest, reviewed_digest=review_digest(manifest))
        validate_manifest(manifest, reviewed=True)
    return manifest
