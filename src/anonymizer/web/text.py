"""!
@file text.py
@brief Viste testuali derivate dalla stessa impronta raster della copia visuale.

Un carattere è considerato oscurato solo se la sua regione cade sotto una
maschera effettivamente disegnata, così testo e immagine esportati coincidono.
"""

import math
import re
from dataclasses import replace
from itertools import groupby

from anonymizer.redact import apply_redactions
from anonymizer.visual_model import finite


def _render_text(text, states):
    """!
    @brief Ricompone il testo sostituendo i tratti oscurati o non localizzati.

    Stato 0: testo senza posizione, sostituito parola per parola con
    [TESTO NON LOCALIZZATO]; 1: visibile; 2: coperto, sostituito con [OSCURATO].
    Gli spazi restano invariati.
    @param text Testo da ricomporre.
    @param states Stato di ciascun carattere.
    @return Testo risultante.
    """
    output = []
    for state, indices in groupby(range(len(states)), key=states.__getitem__):
        run = list(indices)
        value = text[run[0] : run[-1] + 1]
        output.append(
            value
            if state == 1 or not value.strip()
            else "[OSCURATO]"
            if state == 2
            else re.sub(r"\S+", "[TESTO NON LOCALIZZATO]", value)
        )
    return "".join(output)


def page_text(page, *, include_lines=False):
    """!
    @brief Calcola testo originale e oscurato di una pagina dalle maschere rasterizzate.
    @param page Pagina del manifest di revisione.
    @param include_lines Se True aggiunge il dettaglio per riga con il riquadro che
           la delimita.
    @return Dizionario con chiavi `original`, `redacted` ed eventualmente `lines`.
    """
    from PIL import Image

    geometry = replace(page.geometry, pixel_mode="L")
    image = Image.new("L", (geometry.width, geometry.height), 255)
    try:
        masks = tuple(replace(mask, confirmed=True) for mask in page.redactions)
        footprint = apply_redactions(image, masks, geometry)
    finally:
        image.close()
    states = bytearray(len(page.page.text))
    regions = []
    try:
        for region in page.page.regions:
            if region.box is None:
                continue
            if len(region.box) != 4 or not all(map(finite, region.box)):
                continue
            x0, y0, x1, y1 = region.box
            if x0 >= x1 or y0 >= y1:
                continue
            box = (
                max(0, math.floor(x0)),
                max(0, math.floor(y0)),
                min(geometry.width, math.ceil(x1)),
                min(geometry.height, math.ceil(y1)),
            )
            if box[0] >= box[2] or box[1] >= box[3]:
                continue
            regions.append((region.start, region.end, box))
            with footprint.crop(box) as crop:
                masked = crop.getextrema()[0] == 0
            for index in range(region.start, region.end):
                states[index] = max(states[index], 2 if masked else 1)
    finally:
        footprint.close()
    text = page.page.text
    result = {"original": text, "redacted": _render_text(text, states)}
    if include_lines:
        lines = []
        offset = 0
        for value in text.splitlines(keepends=True):
            end = offset + len(value)
            boxes = [box for start, stop, box in regions if start < end and stop > offset]
            bounds = (
                [
                    min(b[0] for b in boxes),
                    min(b[1] for b in boxes),
                    max(b[2] for b in boxes),
                    max(b[3] for b in boxes),
                ]
                if boxes
                else None
            )
            if value.strip():
                lines.append(
                    dict(
                        original=value.rstrip("\r\n"),
                        redacted=_render_text(value, states[offset:end]).rstrip("\r\n"),
                        bounds=bounds,
                        unlocalized=any(
                            state == 0 and not char.isspace()
                            for char, state in zip(value, states[offset:end], strict=True)
                        ),
                    )
                )
            offset = end
        result["lines"] = lines
    return result


def document_text(manifest):
    """!
    @brief Concatena il testo oscurato di tutte le pagine con un'intestazione per pagina.
    @param manifest Manifest di revisione.
    @return Testo oscurato del documento.
    """
    return "\n\n".join(
        f"--- Pagina {index + 1} ---\n{page_text(page)['redacted']}"
        for index, page in enumerate(manifest.pages)
    )
