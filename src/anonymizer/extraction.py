"""!
@file extraction.py
@brief Renderizza le pagine PDF per l'analisi ed estrae il testo nativo quando è affidabile.

Il testo nativo con le relative coordinate viene usato solo per pagine composte da
oggetti testo semplici (o, in modalità ibrida, da testo e tracciati neri opachi), così
che le posizioni coincidano con quanto visibile nel raster; negli altri casi si ricorre
all'OCR sull'immagine renderizzata.
"""

import math
from contextlib import closing
from ctypes import byref, c_int, c_size_t, c_uint
from dataclasses import dataclass

from anonymizer.ingest import PageInput
from anonymizer.model import PageResult, TextRegion
from anonymizer.visual_model import DocumentError


@dataclass
class PdfAnalysisRender:
    """!
    @brief Risultato del rendering di una pagina PDF destinato all'analisi.

    È iterabile come coppia (image, native) per consentire l'unpacking a due valori.
    """

    ## Immagine RGB della pagina (residua senza testo se residual è vero).
    image: object
    ## Testo nativo estratto con le regioni, oppure None se non affidabile.
    native: PageResult | None
    ## Vero se l'immagine contiene solo i tracciati residui dopo la rimozione del testo.
    residual: bool = False

    def __iter__(self):
        """!
        @brief Restituisce in sequenza l'immagine e il testo nativo.
        @return Iteratore su (image, native).
        """
        yield self.image
        yield self.native


def _render_image(page, item):
    """!
    @brief Renderizza una pagina PDF già aperta alla risoluzione della geometria.
    @param page Pagina pypdfium2 aperta.
    @param item Pagina di input con la geometria attesa.
    @return Immagine RGB della pagina.
    @throws DocumentError Se le dimensioni renderizzate non coincidono con la geometria.
    """
    with closing(page.render(scale=item.geometry.dpi / 72, draw_annots=True)) as bitmap:
        image = bitmap.to_pil().convert("RGB")
    if image.size != (item.geometry.width, item.geometry.height):
        image.close()
        raise DocumentError("render_geometry_mismatch")
    return image


def _black_opaque_path(obj, raw):
    """!
    @brief Verifica che un tracciato PDF sia disegnato solo in nero pieno opaco.
    @param obj Oggetto tracciato della pagina.
    @param raw Modulo pypdfium2.raw con le funzioni PDFium.
    @return Vero se riempimento e contorno attivi sono neri con alpha 255.
    """
    fill, stroke = c_int(), c_int()
    if not raw.FPDFPath_GetDrawMode(obj, byref(fill), byref(stroke)):
        return False
    if fill.value not in (0, 1, 2) or stroke.value not in (0, 1):
        return False
    for active, getter in (
        (fill.value != 0, raw.FPDFPageObj_GetFillColor),
        (stroke.value != 0, raw.FPDFPageObj_GetStrokeColor),
    ):
        if not active:
            continue
        red, green, blue, alpha = c_uint(), c_uint(), c_uint(), c_uint()
        if not getter(obj, byref(red), byref(green), byref(blue), byref(alpha)):
            return False
        if (red.value, green.value, blue.value, alpha.value) != (0, 0, 0, 255):
            return False
    return True


def _hybrid_safe(page, objects, raw):
    """!
    @brief Stabilisce se la pagina può essere analizzata in modalità ibrida.

    Richiede assenza di trasparenze, oggetti di primo livello con limiti finiti, tracciati
    neri opachi e testi con un programma di font ispezionabile.
    @param page Pagina pypdfium2 aperta.
    @param objects Oggetti di primo livello della pagina.
    @param raw Modulo pypdfium2.raw con le funzioni PDFium.
    @return Vero se la rimozione del testo lascia un raster residuo affidabile.
    """
    if raw.FPDFPage_HasTransparency(page):
        return False
    for obj in objects:
        if obj.level != 0 or not all(math.isfinite(value) for value in obj.get_bounds()):
            return False
        if obj.type == raw.FPDF_PAGEOBJ_PATH:
            if not _black_opaque_path(obj, raw):
                return False
        elif obj.type == raw.FPDF_PAGEOBJ_TEXT:
            font = raw.FPDFTextObj_GetFont(obj)
            size = c_size_t()
            # Type3 glyph programs have no ordinary font program to inspect.
            if (
                not font
                or not raw.FPDFFont_GetFontData(font, None, 0, byref(size))
                or not size.value
            ):
                return False
        else:
            return False
    return True


def render_pdf_for_analysis(item: PageInput, *, hybrid: bool = False) -> PdfAnalysisRender:
    """!
    @brief Renderizza l'input per l'OCR ed estrae il testo nativo quando possibile.

    Il testo nativo viene estratto solo per pagine senza form o annotazioni. Con la
    modalità ibrida attiva e una pagina idonea, gli oggetti testo vengono rimossi e
    l'immagine restituita contiene solo i tracciati residui, insieme al testo nativo.
    Errori di PDFium durante l'estrazione fanno ripiegare sul solo raster.
    @param item Pagina PDF da renderizzare.
    @param hybrid Abilita la modalità ibrida testo nativo più tracciati residui.
    @return Immagine, eventuale testo nativo e indicatore di raster residuo.
    @throws DocumentError Se le dimensioni renderizzate non coincidono con la geometria.
    """
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw

    with pdfium.PdfDocument(item.source.data) as document:
        document.init_forms()
        with closing(document[item.source_page_index]) as page:
            with closing(page.render(scale=item.geometry.dpi / 72, draw_annots=True)) as bitmap:
                image = bitmap.to_pil().convert("RGB")
                if image.size != (item.geometry.width, item.geometry.height):
                    image.close()
                    raise DocumentError("render_geometry_mismatch")
                native = None
                has_interactive = (
                    raw.FPDF_GetFormType(document) != 0 or raw.FPDFPage_GetAnnotCount(page) != 0
                )
                objects = list(page.get_objects(max_depth=1))
                text_only = bool(objects) and all(
                    obj.type == raw.FPDF_PAGEOBJ_TEXT
                    and raw.FPDFTextObj_GetTextRenderMode(obj) in (0, 1, 2)
                    for obj in objects
                )
                has_paths = any(obj.type == raw.FPDF_PAGEOBJ_PATH for obj in objects)
                supported = bool(objects) and all(
                    obj.type == raw.FPDF_PAGEOBJ_PATH
                    or (
                        obj.type == raw.FPDF_PAGEOBJ_TEXT
                        and raw.FPDFTextObj_GetTextRenderMode(obj) in (0, 1, 2)
                    )
                    for obj in objects
                )
                residual = False
                try:
                    can_hybrid = (
                        hybrid and has_paths and supported and _hybrid_safe(page, objects, raw)
                    )
                    if (text_only or can_hybrid) and not has_interactive:
                        with closing(page.get_textpage()) as textpage:
                            native = _native_text(textpage, bitmap.get_posconv(page), item, raw)
                    if native is not None and can_hybrid:
                        # Textpage handles must be closed before detaching any text object.
                        for obj in objects:
                            if obj.type == raw.FPDF_PAGEOBJ_TEXT:
                                page.remove_obj(obj)
                                obj.close()
                        residual_image = _render_image(page, item)
                        image.close()
                        image = residual_image
                        residual = True
                except (RuntimeError, ValueError, OverflowError):
                    native, residual = None, False
    return PdfAnalysisRender(image, native, residual)


def _native_text(textpage, converter, item: PageInput, raw) -> PageResult | None:
    """!
    @brief Estrae il testo nativo con un box in pixel per ogni carattere visibile.

    I caratteri non spaziati con box vuoto dopo il ritaglio alla pagina vengono scartati.
    @param textpage Text page pypdfium2 della pagina.
    @param converter Convertitore da coordinate PDF a coordinate bitmap.
    @param item Pagina di input con identificatori e geometria.
    @param raw Modulo pypdfium2.raw con le funzioni PDFium.
    @return Risultato di pagina con origine "native_pdf", oppure None se il testo è vuoto,
        troppo lungo, contiene codici Unicode non validi o box non finiti.
    """
    count = textpage.count_chars()
    if count <= 0 or count > 1_000_000:
        return None
    parts, regions = [], []
    offset = 0
    for index in range(count):
        code = raw.FPDFText_GetUnicode(textpage, index)
        if code <= 0 or code > 0x10FFFF or 0xD800 <= code <= 0xDFFF:
            return None
        char = chr(code)
        if char.isspace():
            parts.append(char)
            offset += 1
            continue
        box = textpage.get_charbox(index, loose=True)
        if not all(math.isfinite(value) for value in box):
            return None
        left, bottom, right, top = box
        points = [
            converter.to_bitmap(x, y)
            for x, y in ((left, bottom), (left, top), (right, bottom), (right, top))
        ]
        x0, x1 = min(point[0] for point in points), max(point[0] for point in points)
        y0, y1 = min(point[1] for point in points), max(point[1] for point in points)
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(item.geometry.width, x1), min(item.geometry.height, y1)
        if x1 <= x0 or y1 <= y0:
            continue
        regions.append(TextRegion(offset, offset + 1, (x0, y0, x1, y1)))
        parts.append(char)
        offset += 1
    if not regions:
        return None
    return PageResult(
        item.page_id,
        item.source.source_id,
        item.source_page_index,
        "".join(parts),
        "native_pdf",
        tuple(regions),
    )
