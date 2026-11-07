"""!
@file export.py
@brief Esporta il documento revisionato applicando le redazioni ai sorgenti originali.

Verifica che i file forniti corrispondano esattamente a quelli registrati nel manifesto
revisionato (hash, ordine e geometria), poi ri-renderizza ogni pagina, applica le maschere
e scrive un PDF o un singolo PNG senza metadati della sorgente.
"""

from io import BytesIO
from pathlib import Path
from time import perf_counter

from anonymizer.ingest import InputFile, inspect_inputs, render_page
from anonymizer.redact import apply_redactions
from anonymizer.visual_model import (
    DEFAULT_LIMITS,
    DocumentError,
    Limits,
    ReviewManifest,
    validate_manifest,
)


def bind_sources(
    inputs: tuple[InputFile, ...],
    manifest: ReviewManifest,
    limits: Limits,
):
    """!
    @brief Associa i file di input alle sorgenti del manifesto e ne verifica l'identità.
    @param inputs File originali nell'ordine in cui erano stati caricati.
    @param manifest Manifesto revisionato con sorgenti, pagine e geometrie attese.
    @param limits Limiti di dimensione e risorse per l'ispezione.
    @return Dizionario (source_id, indice pagina sorgente) -> pagina ispezionata.
    @throws DocumentError Se numero, hash, ordine, DPI o geometria non coincidono.
    """
    by_index = sorted(manifest.sources, key=lambda source: source.input_index)
    if len(inputs) != len(by_index):
        raise DocumentError("source_count_mismatch")
    linked = tuple(
        InputFile(item.data, item.extension, source.source_id)
        for item, source in zip(inputs, by_index, strict=True)
    )
    dpis = {item.geometry.dpi for item in manifest.pages}
    if len(dpis) != 1:
        raise DocumentError("inconsistent_render_dpi")
    records, page_inputs = inspect_inputs(linked, limits, next(iter(dpis)))
    if records != manifest.sources:
        raise DocumentError("original_source_hash_or_order_mismatch")
    original_pages = {(item.source.source_id, item.source_page_index): item for item in page_inputs}
    for item in manifest.pages:
        original = original_pages[(item.page.source_id, item.source_page_index)]
        if item.geometry != original.geometry:
            raise DocumentError("original_geometry_mismatch")
    return original_pages


def export_document(
    inputs: tuple[InputFile, ...],
    manifest: ReviewManifest,
    output: Path,
    *,
    limits: Limits = DEFAULT_LIMITS,
    timings: dict[str, float] | None = None,
) -> tuple[Path, ...]:
    """!
    @brief Scrive il documento anonimizzato a partire dai sorgenti e dal manifesto revisionato.

    Il file di output viene creato in modo esclusivo e rimosso in caso di qualsiasi errore,
    così non restano esportazioni parziali.
    @param inputs File originali da ri-renderizzare.
    @param manifest Manifesto revisionato con le redazioni da applicare.
    @param output Percorso del file da creare (.pdf, oppure .png per una sola pagina).
    @param limits Limiti di dimensione e risorse.
    @param timings Dizionario opzionale in cui accumulare i tempi delle fasi di export.
    @return Tupla con il percorso del file creato.
    @throws DocumentError Se il manifesto non è valido, i sorgenti non coincidono, l'output
        esiste già o l'estensione non è supportata.
    """
    started = perf_counter()
    validate_manifest(manifest, reviewed=True)
    original_pages = bind_sources(inputs, manifest, limits)
    if timings is not None:
        timings["export_source_check"] = perf_counter() - started
        timings.update(export_render=0.0, export_masks=0.0, export_encode=0.0)
    if output.exists():
        raise DocumentError("output_already_exists")
    pdf = output.suffix.lower() == ".pdf"
    if not pdf and (len(manifest.pages) != 1 or output.suffix.lower() != ".png"):
        raise DocumentError("output_must_be_pdf_or_single_page_png")
    created = False
    try:
        with output.open("xb") as stream:
            created = True
            canvas = None
            if pdf:
                from reportlab.pdfgen.canvas import Canvas

                canvas = Canvas(stream, pageCompression=1, invariant=1)
                canvas.setTitle("")
                canvas.setAuthor("")
                canvas.setSubject("")
                canvas.setCreator("Anonymizer")
            for item in manifest.pages:
                original = original_pages[(item.page.source_id, item.source_page_index)]
                phase = perf_counter()
                image = render_page(original)
                if timings is not None:
                    timings["export_render"] += perf_counter() - phase
                try:
                    phase = perf_counter()
                    redacted = apply_redactions(image, item.redactions, item.geometry)
                    if timings is not None:
                        timings["export_masks"] += perf_counter() - phase
                    try:
                        phase = perf_counter()
                        if pdf:
                            from reportlab.lib.utils import ImageReader

                            buffer = BytesIO()
                            redacted.save(buffer, "PNG", exif=b"", icc_profile=None)
                            buffer.seek(0)
                            size = (item.geometry.width_points, item.geometry.height_points)
                            canvas.setPageSize(size)
                            canvas.drawImage(
                                ImageReader(buffer), 0, 0, width=size[0], height=size[1]
                            )
                            canvas.showPage()
                        else:
                            redacted.save(stream, "PNG", exif=b"", icc_profile=None)
                        if timings is not None:
                            timings["export_encode"] += perf_counter() - phase
                    finally:
                        redacted.close()
                finally:
                    image.close()
            if canvas:
                phase = perf_counter()
                canvas.save()
                if timings is not None:
                    timings["export_encode"] += perf_counter() - phase
    except BaseException:
        if created:
            output.unlink(missing_ok=True)
        raise
    return (output,)
