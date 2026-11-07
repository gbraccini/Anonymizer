"""!
@file visual_model.py
@brief Modello del manifesto di revisione visiva e delle relative validazioni.

Descrive sorgenti, geometria delle pagine e mascherature da applicare al raster,
e verifica la coerenza del manifesto prima e dopo la conferma della revisione.
"""

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field

from anonymizer.model import PageResult, opaque_id
from anonymizer.ner_model import NerAudit


class DocumentError(ValueError):
    """!
    @brief Errore di documento identificato da un codice simbolico stabile.
    """

    def __init__(self, code: str):
        """!
        @brief Crea l'errore usando il codice anche come messaggio.
        @param code Codice simbolico dell'errore.
        """
        ## Codice dell'errore, utilizzabile dal chiamante senza analizzare il messaggio.
        self.code = code
        super().__init__(code)


def finite(value: object) -> bool:
    """!
    @brief Indica se il valore è un `int` o `float` esatto e finito.

    Booleani e sottoclassi numeriche sono esclusi; interi troppo grandi per la
    conversione in virgola mobile sono considerati non finiti.
    @param value Valore da controllare.
    @return Vero se il valore è un numero finito accettabile.
    """
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


@dataclass(frozen=True)
class Limits:
    """!
    @brief Limiti di risorse per i documenti in ingresso.
    """

    ## Numero massimo di file per documento.
    max_files: int = 20
    ## Dimensione complessiva massima in byte.
    max_bytes: int = 50_000_000
    ## Numero massimo di pagine.
    max_pages: int = 30
    ## Pixel massimi per singola pagina.
    max_page_pixels: int = 25_000_000
    # Thirty A4 pages at 300 DPI need about 261 MP; rasters are processed per page.
    ## Pixel massimi complessivi del documento.
    max_total_pixels: int = 300_000_000

    def __post_init__(self) -> None:
        """!
        @brief Verifica che tutti i limiti siano interi positivi.
        @throws DocumentError Con codice `invalid_limits` se un limite non è valido.
        """
        if any(type(value) is not int or value <= 0 for value in asdict(self).values()):
            raise DocumentError("invalid_limits")


## Limiti applicati quando il chiamante non ne specifica altri.
DEFAULT_LIMITS = Limits()


@dataclass(frozen=True)
class SourcePageGeometry:
    """!
    @brief Geometria di una pagina sorgente e trasformazione verso le coordinate originali.

    Le coordinate sono in pixel dell'immagine originale normalizzata per orientamento,
    con origine in alto a sinistra.
    """

    ## Larghezza in pixel.
    width: int
    ## Altezza in pixel.
    height: int
    ## Larghezza fisica in punti tipografici.
    width_points: float
    ## Altezza fisica in punti tipografici.
    height_points: float
    ## Risoluzione di rasterizzazione.
    dpi: int
    ## Rotazione della pagina in gradi (0, 90, 180, 270).
    rotation: int = 0
    ## Orientamento EXIF dell'immagine (da 1 a 8).
    exif_orientation: int = 1
    ## MediaBox della pagina PDF, se applicabile.
    pdf_media_box: tuple[float, ...] | None = None
    ## CropBox della pagina PDF, se applicabile.
    pdf_crop_box: tuple[float, ...] | None = None
    ## Dimensioni del dispositivo di rendering PDF, se applicabile.
    pdf_device: tuple[int, ...] | None = None
    ## Trasformazione affine (a, b, c, d, e, f) dalle coordinate OCR a quelle originali; deve essere
    ## invertibile.
    ocr_to_original: tuple[float, ...] = (1, 0, 0, 1, 0, 0)
    ## Spazio di coordinate; è supportato un solo valore.
    coordinate_space: str = "orientation_normalized_original_pixels_upper_left"
    ## Modalità dei pixel (`RGB` o `L`).
    pixel_mode: str = "RGB"

    def __post_init__(self) -> None:
        """!
        @brief Verifica dimensioni, orientamento, spazio colore e trasformazioni.
        @throws DocumentError Con un codice che identifica il primo campo non valido.
        """
        if any(
            type(value) is not int or value <= 0 for value in (self.width, self.height, self.dpi)
        ):
            raise DocumentError("invalid_page_dimensions")
        if not all(
            finite(value) and value > 0 for value in (self.width_points, self.height_points)
        ):
            raise DocumentError("invalid_physical_dimensions")
        if self.rotation not in (0, 90, 180, 270) or self.exif_orientation not in range(1, 9):
            raise DocumentError("invalid_orientation")
        if self.coordinate_space != "orientation_normalized_original_pixels_upper_left":
            raise DocumentError("unsupported_coordinate_space")
        if self.pixel_mode not in ("RGB", "L"):
            raise DocumentError("unsupported_pixel_mode")
        if len(self.ocr_to_original) != 6 or not all(map(finite, self.ocr_to_original)):
            raise DocumentError("invalid_ocr_transform")
        a, b, c, d, _, _ = self.ocr_to_original
        if abs(a * d - b * c) < 1e-12:
            raise DocumentError("singular_ocr_transform")
        for box in (self.pdf_media_box, self.pdf_crop_box):
            if box is not None and (len(box) != 4 or not all(map(finite, box))):
                raise DocumentError("invalid_pdf_box")


@dataclass(frozen=True)
class SourceRecord:
    """!
    @brief File sorgente che compone il documento.
    """

    ## Identificatore non vuoto della sorgente.
    source_id: str
    ## Impronta SHA-256 esadecimale del file.
    sha256: str
    ## Formato del file (PDF, JPEG, PNG o HEIF).
    format: str
    ## Posizione del file nell'ordine di caricamento.
    input_index: int
    ## Numero di pagine del file, positivo.
    page_count: int

    def __post_init__(self) -> None:
        """!
        @brief Verifica identificatore, posizione e numero di pagine.
        @throws DocumentError Se uno dei campi non è valido.
        """
        if not isinstance(self.source_id, str) or not self.source_id:
            raise DocumentError("invalid_source_id")
        if type(self.input_index) is not int or self.input_index < 0:
            raise DocumentError("invalid_source_order")
        if type(self.page_count) is not int or self.page_count <= 0:
            raise DocumentError("invalid_source_page_count")


@dataclass(frozen=True)
class VisualRedaction:
    """!
    @brief Mascheratura di una zona della pagina, definita da un quadrilatero convesso.
    """

    ## Pagina a cui si applica.
    page_id: str
    ## Quattro vertici in pixel della pagina, in ordine di percorrenza.
    polygon: tuple[tuple[float, float], ...]
    ## Provenienza: `manual` oppure `automatic`.
    origin: str = "manual"
    ## Candidati testuali coperti dalla mascheratura.
    candidate_ids: tuple[str, ...] = ()
    ## Se vero, confermata in revisione.
    confirmed: bool = False
    ## `apply` per applicarla, `reject` per scartarla con motivazione.
    decision: str = "apply"
    ## Motivazione, obbligatoria in caso di rifiuto.
    reason: str = ""
    ## Identificatore opaco della mascheratura.
    id: str = field(default_factory=opaque_id)
    ## Regola di rasterizzazione del poligono; è supportato un solo valore.
    raster_policy: str = "rectangle_outward_quad_rounded_edge3_v1"

    def validate(self, geometry: SourcePageGeometry) -> None:
        """!
        @brief Verifica la mascheratura rispetto alla geometria della pagina.

        Il quadrilatero deve stare dentro la pagina ed essere strettamente convesso,
        quindi con area non nulla.
        @param geometry Geometria della pagina di destinazione.
        @throws DocumentError Se forma, decisione, coordinate o convessità non sono valide.
        """
        if self.raster_policy != "rectangle_outward_quad_rounded_edge3_v1":
            raise DocumentError("unsupported_mask_raster_policy")
        if len(self.polygon) != 4 or self.origin not in ("manual", "automatic"):
            raise DocumentError("invalid_redaction_shape")
        if self.decision not in ("apply", "reject") or type(self.confirmed) is not bool:
            raise DocumentError("invalid_redaction_decision")
        if self.decision == "reject" and not self.reason.strip():
            raise DocumentError("rejection_requires_reason")
        for point in self.polygon:
            if len(point) != 2 or not all(map(finite, point)):
                raise DocumentError("invalid_redaction_coordinate")
            if not (0 <= point[0] <= geometry.width and 0 <= point[1] <= geometry.height):
                raise DocumentError("redaction_out_of_bounds")
        crosses = []
        for index in range(4):
            a, b, c = (self.polygon[(index + offset) % 4] for offset in range(3))
            crosses.append((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]))
        if not (all(value > 0 for value in crosses) or all(value < 0 for value in crosses)):
            raise DocumentError("redaction_must_be_convex_nonempty")


@dataclass(frozen=True)
class ReviewWarning:
    """!
    @brief Avviso di revisione associato a una pagina.
    """

    ## Codice simbolico dell'avviso.
    code: str
    ## Se vero, deve essere riconosciuto prima di confermare la revisione.
    blocking: bool = True
    ## Se vero, l'avviso è stato preso in carico.
    acknowledged: bool = False
    ## Candidati a cui l'avviso si riferisce.
    candidate_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """!
        @brief Verifica che i flag siano booleani.
        @throws DocumentError Con codice `invalid_warning_decision` se non lo sono.
        """
        if type(self.blocking) is not bool or type(self.acknowledged) is not bool:
            raise DocumentError("invalid_warning_decision")


@dataclass(frozen=True)
class VisualPage:
    """!
    @brief Pagina del manifesto con testo, geometria e decisioni di mascheratura.
    """

    ## Testo estratto della pagina.
    page: PageResult
    ## Indice della pagina all'interno del file sorgente.
    source_page_index: int
    ## Geometria della pagina sorgente.
    geometry: SourcePageGeometry
    ## Mascherature proposte o confermate.
    redactions: tuple[VisualRedaction, ...] = ()
    ## Avvisi di revisione.
    warnings: tuple[ReviewWarning, ...] = ()
    ## Candidati che devono essere coperti da una mascheratura.
    required_candidate_ids: tuple[str, ...] = ()
    ## Mascherature che devono comparire nella revisione.
    required_redaction_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReviewManifest:
    """!
    @brief Manifesto di revisione di un documento visivo.
    """

    ## File sorgente del documento.
    sources: tuple[SourceRecord, ...]
    ## Pagine nell'ordine di uscita.
    pages: tuple[VisualPage, ...]
    ## Identificatore opaco del documento.
    document_id: str = field(default_factory=opaque_id)
    ## Versione dello schema; è supportata solo la 1.
    schema_version: int = 1
    ## Impronta del manifesto al momento della conferma, se confermato.
    reviewed_digest: str | None = None
    ## Regola di produzione dell'output; è supportato un solo valore.
    policy: str = "opaque_raster_rgb8_l8_no_original_metadata_v1"
    ## Identificatori delle pagine nell'ordine atteso.
    page_order: tuple[str, ...] = ()
    ## Dati di audit del riconoscimento di entità.
    ner_audit: NerAudit = field(default_factory=NerAudit)


def review_digest(manifest: ReviewManifest) -> str:
    """!
    @brief Calcola l'impronta del contenuto del manifesto.

    Usa una serializzazione JSON canonica che esclude `reviewed_digest`, così che
    l'impronta possa essere memorizzata nel manifesto stesso.
    @param manifest Manifesto da cui calcolare l'impronta.
    @return Impronta SHA-256 esadecimale.
    """
    data = asdict(manifest)
    data.pop("reviewed_digest")
    raw = json.dumps(
        data, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_manifest(manifest: ReviewManifest, *, reviewed: bool = False) -> None:
    """!
    @brief Verifica la coerenza strutturale del manifesto ed eventualmente la revisione.

    Controlla versione e regola, sorgenti, identità e copertura delle pagine e delle
    mascherature. Con `reviewed` richiede inoltre che ogni mascheratura sia confermata,
    che ogni candidato richiesto sia coperto, che gli avvisi bloccanti siano
    riconosciuti e che l'impronta registrata corrisponda al contenuto attuale.
    @param manifest Manifesto da verificare.
    @param reviewed Se vero, applica anche i controlli della revisione confermata.
    @throws DocumentError Con un codice che identifica la prima incoerenza trovata.
    """
    if (
        type(manifest.schema_version) is not int
        or manifest.schema_version != 1
        or manifest.policy != "opaque_raster_rgb8_l8_no_original_metadata_v1"
    ):
        raise DocumentError("unsupported_manifest_version_or_policy")
    sources = {source.source_id: source for source in manifest.sources}
    if not sources or len(sources) != len(manifest.sources):
        raise DocumentError("duplicate_or_missing_source")
    if sorted(source.input_index for source in manifest.sources) != list(range(len(sources))):
        raise DocumentError("invalid_source_order")
    if sum(source.page_count for source in manifest.sources) != len(manifest.pages):
        raise DocumentError("missing_document_page")
    page_ids, source_pages, redaction_ids = set(), set(), set()
    if tuple(item.page.page_id for item in manifest.pages) != manifest.page_order:
        raise DocumentError("page_order_mismatch")
    for source in manifest.sources:
        if len(source.sha256) != 64 or any(
            char not in "0123456789abcdef" for char in source.sha256
        ):
            raise DocumentError("invalid_source_hash")
        if source.format not in ("PDF", "JPEG", "PNG", "HEIF") or source.page_count <= 0:
            raise DocumentError("invalid_source_format_or_pages")
    for item in manifest.pages:
        page = item.page
        source = sources.get(page.source_id)
        key = (page.source_id, item.source_page_index)
        if page.page_id in page_ids or key in source_pages or source is None:
            raise DocumentError("invalid_page_identity")
        if not 0 <= item.source_page_index < source.page_count:
            raise DocumentError("invalid_source_page_index")
        page_ids.add(page.page_id)
        source_pages.add(key)
        linked = set()
        for mask in item.redactions:
            mask.validate(item.geometry)
            if mask.page_id != page.page_id or mask.id in redaction_ids:
                raise DocumentError("invalid_redaction_identity")
            if not set(mask.candidate_ids) <= set(item.required_candidate_ids):
                raise DocumentError("unknown_redaction_candidate")
            redaction_ids.add(mask.id)
            linked.update(mask.candidate_ids)
            if reviewed and not mask.confirmed:
                raise DocumentError("unconfirmed_redaction")
        if reviewed and not set(item.required_candidate_ids) <= linked:
            raise DocumentError("unresolved_candidate_geometry")
        if reviewed and not set(item.required_redaction_ids) <= {
            mask.id for mask in item.redactions
        }:
            raise DocumentError("missing_redaction_decision")
        if reviewed:
            manual_candidates = {
                candidate
                for mask in item.redactions
                if mask.origin == "manual" and mask.decision == "apply"
                for candidate in mask.candidate_ids
            }
            for warning in item.warnings:
                if (
                    warning.code == "candidate_geometry_incomplete"
                    and not set(warning.candidate_ids) <= manual_candidates
                ):
                    raise DocumentError("unresolved_candidate_geometry")
        if reviewed and any(
            warning.blocking and not warning.acknowledged for warning in item.warnings
        ):
            raise DocumentError("unresolved_review_warning")
    expected = {
        (source.source_id, index)
        for source in manifest.sources
        for index in range(source.page_count)
    }
    if source_pages != expected:
        raise DocumentError("missing_document_page")
    if reviewed and manifest.reviewed_digest != review_digest(manifest):
        raise DocumentError("review_snapshot_changed")
