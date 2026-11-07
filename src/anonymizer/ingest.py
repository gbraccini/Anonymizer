"""!
@file ingest.py
@brief Ispeziona i file di input e renderizza le pagine sorgente come immagini.

Valida formato, dimensioni e metadati di PDF e immagini (JPEG, PNG, HEIC/HEIF), ne
calcola la geometria di rendering entro i limiti configurati e produce i raster delle
singole pagine usati da estrazione, anteprima ed esportazione.
"""

import hashlib
import math
from contextlib import closing
from dataclasses import dataclass, field
from io import BytesIO

from anonymizer.color import normalize_color, normalized_color_mode
from anonymizer.model import opaque_id
from anonymizer.visual_model import (
    DEFAULT_LIMITS,
    DocumentError,
    Limits,
    SourcePageGeometry,
    SourceRecord,
)


@dataclass(frozen=True)
class InputFile:
    """!
    @brief File sorgente caricato in memoria.
    """

    ## Contenuto binario del file.
    data: bytes
    ## Estensione dichiarata, punto incluso (es. ".pdf"), verificata rispetto al contenuto.
    extension: str
    ## Identificatore opaco della sorgente.
    source_id: str = field(default_factory=opaque_id)


@dataclass(frozen=True)
class PageInput:
    """!
    @brief Singola pagina di un file sorgente pronta per il rendering.
    """

    ## File sorgente a cui appartiene la pagina.
    source: InputFile
    ## Indice della pagina nel file sorgente (0 per le immagini).
    source_page_index: int
    ## Geometria di rendering calcolata in ispezione.
    geometry: SourcePageGeometry
    ## Identificatore opaco della pagina.
    page_id: str = field(default_factory=opaque_id)


def open_image(source: InputFile):
    """!
    @brief Apre un'immagine sorgente con Pillow, registrando il decoder HEIF se serve.
    @param source File immagine da aprire.
    @return Immagine PIL aperta in modo lazy sul contenuto in memoria.
    @throws DocumentError Se l'immagine non è decodificabile o supera i limiti di Pillow.
    """
    from PIL import Image

    if source.extension.lower() in (".heic", ".heif"):
        from pi_heif import register_heif_opener

        register_heif_opener(thumbnails=False)
    try:
        return Image.open(BytesIO(source.data))
    except (Image.DecompressionBombError, OSError, ValueError, SyntaxError, RuntimeError):
        raise DocumentError("invalid_or_oversized_image") from None


def image_geometry(source: InputFile, dpi: int) -> tuple[str, SourcePageGeometry]:
    """!
    @brief Valida un'immagine sorgente e ne calcola la geometria orientata.

    Accetta solo immagini a frame singolo, 8 bit, in scala di grigi o RGB, senza
    trasparenza né immagini ausiliarie; l'orientamento EXIF scambia larghezza e altezza
    quando ruota di 90 gradi.
    @param source File immagine da ispezionare.
    @param dpi Risoluzione usata per convertire i pixel in punti.
    @return Tupla (nome del formato Pillow, geometria della pagina).
    @throws DocumentError Se contenuto ed estensione non coincidono o l'immagine usa
        caratteristiche non supportate.
    """
    expected = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".heic": "HEIF", ".heif": "HEIF"}
    with open_image(source) as image:
        if image.format != expected[source.extension.lower()]:
            raise DocumentError("extension_content_mismatch")
        if getattr(image, "n_frames", 1) != 1:
            raise DocumentError("unsupported_multiple_frames")
        if image.format == "PNG" and (len(source.data) < 25 or source.data[24] != 8):
            raise DocumentError("unsupported_depth_alpha_or_color_mode")
        if "transparency" in image.info:
            raise DocumentError("unsupported_depth_alpha_or_color_mode")
        if image.mode not in ("L", "RGB") or image.info.get("bit_depth", 8) != 8:
            raise DocumentError("unsupported_depth_alpha_or_color_mode")
        pixel_mode = normalized_color_mode(image)
        if image.info.get("depth_images") or image.info.get("aux"):
            raise DocumentError("unsupported_auxiliary_images")
        nclx = image.info.get("nclx_profile")
        if nclx and (
            nclx.get("color_primaries") != 1 or nclx.get("transfer_characteristics") != 13
        ):
            raise DocumentError("unsupported_heif_color_profile")
        orientation = image.info.get("original_orientation") or image.getexif().get(274, 1)
        width, height = image.size
        # The HEIF decoder has already applied container orientation and reset EXIF.
        if image.format != "HEIF" and orientation in (5, 6, 7, 8):
            width, height = height, width
        return image.format, SourcePageGeometry(
            width,
            height,
            width * 72 / dpi,
            height * 72 / dpi,
            dpi,
            exif_orientation=orientation,
            pixel_mode=pixel_mode,
        )


def pdf_geometry(page, dpi: int) -> SourcePageGeometry:
    """!
    @brief Calcola la geometria di rendering di una pagina PDF.
    @param page Pagina pypdfium2 aperta.
    @param dpi Risoluzione di rendering.
    @return Geometria con dimensioni in pixel e punti, rotazione e box PDF.
    @throws DocumentError Se le dimensioni della pagina non sono finite e positive.
    """
    width_pt, height_pt = page.get_size()
    if not all(math.isfinite(value) and value > 0 for value in (width_pt, height_pt)):
        raise DocumentError("invalid_pdf_page_dimensions")
    # Match PdfPage.render's operation order: ceil can expose float rounding at integer edges.
    scale = dpi / 72
    width, height = math.ceil(width_pt * scale), math.ceil(height_pt * scale)
    return SourcePageGeometry(
        width,
        height,
        width_pt,
        height_pt,
        dpi,
        rotation=page.get_rotation(),
        pdf_media_box=tuple(page.get_mediabox()),
        pdf_crop_box=tuple(page.get_cropbox()),
        pdf_device=(0, 0, width, height, 0),
    )


def inspect_inputs(
    inputs: tuple[InputFile, ...],
    limits: Limits = DEFAULT_LIMITS,
    dpi: int = 300,
) -> tuple[tuple[SourceRecord, ...], tuple[PageInput, ...]]:
    """!
    @brief Ispeziona tutti i file di input applicando limiti di file, byte, pagine e pixel.

    Non decodifica i raster: legge solo struttura e metadati per costruire i record delle
    sorgenti (con hash SHA-256) e l'elenco delle pagine da renderizzare.
    @param inputs File da ispezionare, nell'ordine di caricamento.
    @param limits Limiti di risorse da rispettare.
    @param dpi Risoluzione di rendering, tra 72 e 1200.
    @return Tupla (record delle sorgenti, pagine da renderizzare).
    @throws DocumentError Se un limite è superato, un id sorgente è duplicato, il formato
        non è supportato o un file non è valido.
    """
    if type(dpi) is not int or not 72 <= dpi <= 1200:
        raise DocumentError("invalid_render_dpi")
    if not inputs or len(inputs) > limits.max_files:
        raise DocumentError("input_file_limit")
    if sum(len(source.data) for source in inputs) > limits.max_bytes:
        raise DocumentError("input_byte_limit")
    if len({source.source_id for source in inputs}) != len(inputs):
        raise DocumentError("duplicate_source_id")
    records, pages = [], []
    pixels = 0

    def add_page(source: InputFile, index: int, geometry: SourcePageGeometry) -> None:
        """!
        @brief Registra una pagina aggiornando i contatori di pixel e pagine.
        @param source File sorgente della pagina.
        @param index Indice della pagina nel file.
        @param geometry Geometria calcolata della pagina.
        @throws DocumentError Se si superano i limiti di pixel per pagina, totali o di pagine.
        """
        nonlocal pixels
        area = geometry.width * geometry.height
        if area > limits.max_page_pixels:
            raise DocumentError("page_pixel_limit")
        pixels += area
        if pixels > limits.max_total_pixels:
            raise DocumentError("total_pixel_limit")
        if len(pages) >= limits.max_pages:
            raise DocumentError("page_count_limit")
        pages.append(PageInput(source, index, geometry))

    for input_index, source in enumerate(inputs):
        extension = source.extension.lower()
        if extension == ".pdf":
            import pypdfium2 as pdfium
            import pypdfium2.raw as raw

            if not source.data.startswith(b"%PDF-"):
                raise DocumentError("extension_content_mismatch")
            with pdfium.PdfDocument(source.data) as document:
                if raw.FPDF_GetFormType(document) not in (
                    raw.FORMTYPE_NONE,
                    raw.FORMTYPE_ACRO_FORM,
                ):
                    raise DocumentError("unsupported_xfa_form_document")
                count = len(document)
                if count + len(pages) > limits.max_pages or count <= 0:
                    raise DocumentError("page_count_limit")
                for index in range(count):
                    with closing(document[index]) as page:
                        add_page(source, index, pdf_geometry(page, dpi))
            format_name = "PDF"
        elif extension in (".jpg", ".jpeg", ".png", ".heic", ".heif"):
            format_name, geometry = image_geometry(source, dpi)
            add_page(source, 0, geometry)
            count = 1
        else:
            raise DocumentError("unsupported_format_dicom_excluded")
        records.append(
            SourceRecord(
                source.source_id,
                hashlib.sha256(source.data).hexdigest(),
                format_name,
                input_index,
                count,
            )
        )
    return tuple(records), tuple(pages)


def render_page(item: PageInput):
    """!
    @brief Renderizza una pagina sorgente come immagine raster.

    I PDF vengono resi in RGB con form e annotazioni; le immagini vengono orientate
    secondo EXIF e normalizzate in sRGB.
    @param item Pagina da renderizzare.
    @return Immagine PIL con le dimensioni previste dalla geometria.
    @throws DocumentError Se le dimensioni renderizzate non coincidono con la geometria.
    """
    if item.source.extension.lower() == ".pdf":
        import pypdfium2 as pdfium

        with pdfium.PdfDocument(item.source.data) as document:
            document.init_forms()
            with closing(document[item.source_page_index]) as page:
                with closing(page.render(scale=item.geometry.dpi / 72, draw_annots=True)) as bitmap:
                    image = bitmap.to_pil().convert("RGB")
    else:
        from PIL import ImageOps

        with open_image(item.source) as original:
            with ImageOps.exif_transpose(original) as oriented:
                image = normalize_color(oriented)
    if image.size != (item.geometry.width, item.geometry.height):
        image.close()
        raise DocumentError("render_geometry_mismatch")
    return image
