"""!
@file redact.py
@brief Propone e applica le maschere visive di redazione sulle pagine raster.

Trasforma gli intervalli di testo da mascherare in rettangoli in pixel a partire dalle
regioni OCR/testo della pagina e disegna le redazioni confermate sull'immagine, sia per
le anteprime sia per l'esportazione finale.
"""

import math
from dataclasses import replace
from statistics import median

from anonymizer.model import MergedSpan, PageResult
from anonymizer.pseudo import should_mask
from anonymizer.visual_model import (
    DocumentError,
    ReviewWarning,
    SourcePageGeometry,
    VisualRedaction,
)


def propose_redactions(
    page: PageResult,
    spans: list[MergedSpan],
    geometry: SourcePageGeometry,
) -> tuple[tuple[VisualRedaction, ...], tuple[ReviewWarning, ...], tuple[str, ...]]:
    """!
    @brief Genera le redazioni automatiche per gli intervalli da mascherare di una pagina.

    Ogni regione che interseca un intervallo produce un rettangolo allargato di 2 pixel;
    le zone MRZ validate vengono coperte da un unico blocco perché l'OCR può perdere i
    glifi ai bordi. Se i caratteri non spaziati dell'intervallo non sono tutti coperti da
    regioni con geometria, viene emesso un avviso per la revisione.
    @param page Risultato testuale della pagina con regioni e bounding box.
    @param spans Intervalli fusi del documento; vengono considerati solo quelli della pagina
        per cui should_mask è vero.
    @param geometry Geometria della pagina sorgente usata per limitare e validare le maschere.
    @return Tupla (maschere proposte, avvisi di revisione, id degli intervalli da mascherare).
    """
    masks, warnings, required = [], [], []
    for span in spans:
        if span.page_id != page.page_id or not should_mask(span):
            continue
        required.append(span.id)
        covered = set()
        span_masks = []
        for region in page.regions:
            if region.start >= span.end or region.end <= span.start or region.box is None:
                continue
            covered.update(range(max(region.start, span.start), min(region.end, span.end)))
            x0, y0, x1, y1 = region.box
            box = (
                max(0, math.floor(x0) - 2),
                max(0, math.floor(y0) - 2),
                min(geometry.width, math.ceil(x1) + 2),
                min(geometry.height, math.ceil(y1) + 2),
            )
            left, top, right, bottom = box
            mask = VisualRedaction(
                page.page_id,
                ((left, top), (right, top), (right, bottom), (left, bottom)),
                "automatic",
                (span.id,),
            )
            mask.validate(geometry)
            span_masks.append(mask)
        for candidate in span.candidates:
            if candidate.origin != "identity:mrz":
                continue
            regions = [
                r
                for r in page.regions
                if r.box and r.start < candidate.end and candidate.start < r.end
            ]
            lines = page.text[candidate.start : candidate.end].splitlines()
            columns = max((sum(not c.isspace() for c in line) for line in lines), default=0)
            if not regions or not columns:
                continue
            left = min(r.box[0] for r in regions)
            right = max(r.box[2] for r in regions)
            top = min(r.box[1] for r in regions)
            bottom = max(r.box[3] for r in regions)
            height = median(r.box[3] - r.box[1] for r in regions)
            # OCR can omit edge glyphs; a validated MRZ is a single monospaced zone.
            horizontal = max(2, math.ceil(min(2 * (right - left) / columns, 2 * height)))
            vertical = max(2, math.ceil(height / 4))
            box = (
                max(0, math.floor(left) - horizontal),
                max(0, math.floor(top) - vertical),
                min(geometry.width, math.ceil(right) + horizontal),
                min(geometry.height, math.ceil(bottom) + vertical),
            )
            left, top, right, bottom = box
            block = VisualRedaction(
                page.page_id,
                ((left, top), (right, top), (right, bottom), (left, bottom)),
                "automatic",
                (span.id,),
            )
            block.validate(geometry)
            if span.start == candidate.start and span.end == candidate.end:
                span_masks = [block]
                break
            span_masks.append(block)
        masks.extend(_compact_span_rectangles(span_masks))
        nonspace = {
            index for index in range(span.start, span.end) if not page.text[index].isspace()
        }
        if not nonspace <= covered:
            warnings.append(
                ReviewWarning("candidate_geometry_incomplete", candidate_ids=(span.id,))
            )
    return tuple(masks), tuple(warnings), tuple(required)


def _compact_span_rectangles(masks):
    """!
    @brief Unisce i rettangoli automatici adiacenti sulla stessa riga di pixel.

    La fusione avviene solo quando l'unione è esatta: stesse coordinate verticali intere,
    intervalli orizzontali che si toccano o sovrappongono e attributi identici.
    @param masks Redazioni di un singolo intervallo.
    @return Lista di redazioni compattate, ordinata per posizione.
    """
    ordered = sorted(
        masks,
        key=lambda mask: (
            mask.polygon[0][1],
            mask.polygon[2][1],
            mask.polygon[0][0],
        ),
    )
    compacted = []
    for mask in ordered:
        if compacted:
            previous = compacted[-1]
            left, top = previous.polygon[0]
            right, bottom = previous.polygon[2]
            next_left, next_top = mask.polygon[0]
            next_right, next_bottom = mask.polygon[2]
            if (
                previous.origin == mask.origin == "automatic"
                and previous.confirmed == mask.confirmed
                and previous.decision == mask.decision
                and previous.reason == mask.reason
                and all(
                    type(value) is int
                    for value in (
                        left,
                        top,
                        right,
                        bottom,
                        next_left,
                        next_top,
                        next_right,
                        next_bottom,
                    )
                )
                and previous.candidate_ids == mask.candidate_ids
                and previous.page_id == mask.page_id
                and top == next_top
                and bottom == next_bottom
                and next_left <= right
            ):
                # Same integer pixel rows and touching intervals make this an exact union.
                right = max(right, next_right)
                compacted[-1] = replace(
                    previous,
                    polygon=(
                        (left, top),
                        (right, top),
                        (right, bottom),
                        (left, bottom),
                    ),
                )
                continue
        compacted.append(mask)
    return compacted


def apply_redactions(image, redactions: tuple[VisualRedaction, ...], geometry: SourcePageGeometry):
    """!
    @brief Disegna l'impronta canonica delle redazioni per anteprime ed esportazioni finali.

    I rettangoli coprono i bordi in pixel arrotondati verso l'esterno. I quadrilateri
    arrotondano i vertici ai pixel e includono un tratto di bordo di tre pixel per
    proteggere i pixel ai margini. Le redazioni con decisione diversa da "apply" non
    vengono disegnate.
    @param image Immagine della pagina renderizzata, con dimensioni e modo della geometria.
    @param redactions Redazioni da applicare; devono essere tutte confermate.
    @param geometry Geometria attesa della pagina sorgente.
    @return Nuova immagine con le aree redatte riempite di nero.
    @throws DocumentError Se l'immagine non corrisponde alla geometria, una redazione non è
        valida o una redazione non è confermata.
    """
    from PIL import Image, ImageDraw

    if image.size != (geometry.width, geometry.height) or image.mode != geometry.pixel_mode:
        raise DocumentError("redaction_image_geometry_mismatch")
    output = Image.frombytes(image.mode, image.size, image.tobytes())
    draw = ImageDraw.Draw(output)
    for mask in redactions:
        mask.validate(geometry)
        if not mask.confirmed:
            output.close()
            raise DocumentError("unconfirmed_redaction")
        if mask.decision == "apply":
            # Integer outward rounding protects partially covered edge pixels.
            if (
                len({point[0] for point in mask.polygon}) == 2
                and len({point[1] for point in mask.polygon}) == 2
            ):
                left = math.floor(min(point[0] for point in mask.polygon))
                top = math.floor(min(point[1] for point in mask.polygon))
                right = math.ceil(max(point[0] for point in mask.polygon))
                bottom = math.ceil(max(point[1] for point in mask.polygon))
                draw.rectangle((left, top, right - 1, bottom - 1), fill=0)
            else:
                points = [(round(x), round(y)) for x, y in mask.polygon]
                draw.polygon(points, fill=0)
                draw.line(points + points[:1], fill=0, width=3)
    return output
