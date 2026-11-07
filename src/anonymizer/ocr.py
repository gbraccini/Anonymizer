"""!
@file ocr.py
@brief Riconoscimento ottico del testo tramite Tesseract e conversione in risultati di pagina.

Esegue Tesseract come processo esterno con output TSV, converte le parole in testo e
regioni con coordinate in pixel e, per le pagine che sembrano documenti d'identità non
riconosciuti, tenta una seconda lettura su un'immagine pre-elaborata accettandola solo se
non riduce la copertura delle redazioni.
"""

import csv
import math
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, replace
from io import StringIO
from pathlib import Path
from time import perf_counter

from anonymizer.ingest import PageInput
from anonymizer.model import PageResult, TextRegion, Warning
from anonymizer.visual_model import DocumentError


@dataclass(frozen=True)
class OCRConfig:
    """!
    @brief Parametri di esecuzione di Tesseract, validati alla costruzione.
    """

    ## Codice lingua Tesseract (solo lettere).
    language: str = "ita"
    ## Tempo massimo complessivo in secondi per il riconoscimento di una pagina.
    timeout: float = 45
    ## Modalità di segmentazione della pagina (3, 6 o 11).
    psm: int = 3
    ## Numero di thread OpenMP per Tesseract (1-32), o None per il default.
    cpu_threads: int | None = None

    def __post_init__(self) -> None:
        """!
        @brief Valida la configurazione.
        @throws DocumentError Se lingua, timeout, modalità o numero di thread non sono validi.
        """
        if not self.language.isalpha() or not math.isfinite(self.timeout) or self.timeout <= 0:
            raise DocumentError("invalid_ocr_configuration")
        if self.psm not in (3, 6, 11):
            raise DocumentError("unsupported_ocr_layout_mode")
        if self.cpu_threads is not None and (
            type(self.cpu_threads) is not int or not 1 <= self.cpu_threads <= 32
        ):
            raise DocumentError("invalid_ocr_thread_count")


## Configurazione OCR predefinita (italiano, timeout 45 s, segmentazione automatica).
DEFAULT_OCR_CONFIG = OCRConfig()


def from_tsv(data: dict, item: PageInput) -> PageResult:
    """!
    @brief Converte l'output TSV di Tesseract in un risultato di pagina.

    Le parole della stessa riga sono separate da spazi e righe diverse da a capo. Ogni
    pagina riceve un avviso bloccante sull'ordine di lettura; parole con confidenza
    inferiore a 0,75 o l'assenza di testo leggibile aggiungono ulteriori avvisi bloccanti.
    @param data Colonne TSV come dizionario nome colonna -> lista di valori.
    @param item Pagina di input con identificatori e geometria.
    @return Risultato di pagina con origine "ocr", regioni per parola e avvisi.
    @throws DocumentError Se mancano colonne, le lunghezze non coincidono o una parola ha
        geometria o confidenza fuori dai limiti della pagina.
    """
    required = (
        "text",
        "left",
        "top",
        "width",
        "height",
        "conf",
        "block_num",
        "par_num",
        "line_num",
    )
    if any(key not in data for key in required) or len({len(data[key]) for key in required}) != 1:
        raise DocumentError("invalid_ocr_tsv")
    parts, regions = [], []
    offset, previous_line = 0, None
    warnings = [Warning("ocr_reading_order_requires_review", item.page_id, blocking=True)]
    for index, word in enumerate(data["text"]):
        if not word.strip():
            continue
        line = tuple(data[key][index] for key in ("block_num", "par_num", "line_num"))
        separator = "" if previous_line is None else " " if line == previous_line else "\n"
        parts.extend((separator, word))
        offset += len(separator)
        left, top, width, height = (
            int(data[key][index]) for key in ("left", "top", "width", "height")
        )
        confidence = float(data["conf"][index]) / 100
        if not (
            0 <= left < left + width <= item.geometry.width
            and 0 <= top < top + height <= item.geometry.height
            and math.isfinite(confidence)
            and 0 <= confidence <= 1
        ):
            raise DocumentError("invalid_ocr_word_geometry")
        regions.append(
            TextRegion(
                offset,
                offset + len(word),
                (left, top, left + width, top + height),
                confidence,
                ":".join(map(str, line)),
            )
        )
        if confidence < 0.75:
            warnings.append(Warning("low_ocr_confidence", item.page_id, blocking=True))
        offset += len(word)
        previous_line = line
    if not regions:
        warnings.append(Warning("no_readable_text_manual_review", item.page_id, blocking=True))
    return PageResult(
        item.page_id,
        item.source.source_id,
        item.source_page_index,
        "".join(parts),
        "ocr",
        tuple(regions),
        tuple(warnings),
    )


def _recognize_once(
    image, item: PageInput, config: OCRConfig, *, scale_override=None
) -> PageResult:
    """!
    @brief Esegue una singola passata di Tesseract sull'immagine.

    L'eseguibile si ricava da ANONYMIZER_TESSERACT o dal PATH e i dati linguistici
    opzionalmente da ANONYMIZER_TESSDATA. Le immagini piccole vengono raddoppiate prima
    dell'OCR e le coordinate risultanti riportate alla scala originale.
    @param image Immagine PIL della pagina.
    @param item Pagina di input con identificatori e geometria.
    @param config Configurazione OCR.
    @param scale_override Fattore di scala forzato (1 o 2) al posto di quello automatico.
    @return Risultato di pagina nelle coordinate dell'immagine originale.
    @throws DocumentError Se Tesseract non è disponibile, fallisce, supera il timeout o
        produce un TSV non valido.
    """
    deadline = perf_counter() + config.timeout
    executable = os.getenv("ANONYMIZER_TESSERACT") or shutil.which("tesseract")
    if not executable:
        raise DocumentError("ocr_unavailable_failed_or_timeout")
    tessdata = os.getenv("ANONYMIZER_TESSDATA")
    # Small screenshots have glyphs too short for reliable OCR; bound extra memory to 10 MP.
    scale = scale_override if scale_override is not None else 2 if max(image.size) <= 1600 else 1
    try:
        with tempfile.TemporaryDirectory(prefix="anonymizer-ocr-") as directory:
            input_path = Path(directory) / "page.png"
            if scale == 2:
                with image.resize((image.width * scale, image.height * scale)) as enlarged:
                    enlarged.save(input_path, "PNG", exif=b"", icc_profile=None)
            else:
                image.save(input_path, "PNG", exif=b"", icc_profile=None)
            # An argv list preserves Windows paths with spaces without wrapper re-tokenization.
            command = [
                executable,
                str(input_path),
                "stdout",
                "-l",
                config.language,
                "--psm",
                str(config.psm),
            ]
            if tessdata:
                command.extend(("--tessdata-dir", tessdata))
            command.extend(("-c", "tessedit_create_tsv=1", "-c", "tessedit_create_txt=0"))
            environment = os.environ.copy()
            if config.cpu_threads is not None:
                environment.update(
                    OMP_THREAD_LIMIT=str(config.cpu_threads),
                    OMP_NUM_THREADS=str(config.cpu_threads),
                )
            remaining = deadline - perf_counter()
            if remaining <= 0:
                raise DocumentError("ocr_unavailable_failed_or_timeout")
            completed = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=environment,
                timeout=remaining,
                check=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        reader = csv.DictReader(
            StringIO(completed.stdout.decode("utf-8")),
            delimiter="\t",
            quoting=csv.QUOTE_NONE,
        )
        if reader.fieldnames is None:
            raise DocumentError("invalid_ocr_tsv")
        data = {key: [] for key in reader.fieldnames}
        for row in reader:
            if set(row) != set(data) or any(value is None for value in row.values()):
                raise DocumentError("invalid_ocr_tsv")
            for key, value in row.items():
                data[key].append(value)
    except (subprocess.SubprocessError, OSError, UnicodeError):
        raise DocumentError("ocr_unavailable_failed_or_timeout") from None
    if scale == 1:
        return from_tsv(data, item)
    geometry = replace(
        item.geometry, width=item.geometry.width * scale, height=item.geometry.height * scale
    )
    page = from_tsv(data, replace(item, geometry=geometry))
    return replace(
        page,
        regions=tuple(replace(r, box=tuple(v / scale for v in r.box)) for r in page.regions),
    )


def _identity_retry_needed(page):
    """!
    @brief Stabilisce se la pagina sembra un documento d'identità letto male dall'OCR.

    Si ritenta solo se il documento non è già stato riconosciuto e il testo contiene
    indizi tipici: intestazioni ministeriali, righe MRZ plausibili, etichette anagrafiche
    con indizi di documento, oppure indizi di atti di nascita o certificati anagrafici.
    @param page Risultato OCR della prima passata.
    @return Vero se conviene una seconda lettura.
    """
    import re

    from anonymizer.detect.identity_documents import analyze_identity_document

    if len(page.regions) > 2000:
        return False
    text = page.text.casefold()
    if analyze_identity_document(page).recognized:
        return False
    if "repubblica" in text and "ministero" in text:
        return True
    lines = page.text.splitlines()
    for index, line in enumerate(lines[:-1]):
        compact = re.sub(r"[ \t]", "", line).replace("«", "<<")
        if (
            26 <= len(compact) <= 45
            and re.match(r"[ACI]<[A-Z<]{3}", compact)
            and compact.count("<") >= 6
        ):
            second = re.sub(r"[ \t]", "", lines[index + 1]).replace("«", "<<")
            if re.match(r"[0-9OILZSB]{6,8}[MFX<][0-9OILZSB]{6,8}[A-Z<]{3}", second):
                return True
    labels = (r"\bcognome\b|\bsurname\b", r"\bnome\b|\bgiven names?\b", r"nascita|birth")
    document_hint = (
        (
            ("cittadinanza" in text or "nationality" in text)
            and any(word in text for word in ("scadenza", "expiry", "statura", "height"))
        )
        or "firma del titolare" in text
        or "holder's signature" in text
    )
    return (
        document_hint
        and all(re.search(label, text) for label in labels)
        or (
            "padre" in text
            and "madre" in text
            and (
                bool(re.search(r"\batto[ \t]+(?:di[ \t]+)?nascita\b", text))
                or (
                    bool(re.search(r"codice[ \t]+fiscale|tax[ \t]+code", text))
                    and bool(re.search(r"residenza|residence", text))
                )
            )
        )
    )


def _dark_text_image(image):
    """!
    @brief Produce un'immagine binaria che conserva solo il testo scuro acromatico.

    Una soglia sul massimo dei canali RGB elimina gli sfondi di sicurezza colorati dei
    documenti d'identità.
    @param image Immagine PIL della pagina.
    @return Immagine in scala di grigi con valori 0 o 255.
    """
    from PIL import ImageChops

    rgb = image.convert("RGB")
    channels = rgb.split()
    try:
        with ImageChops.lighter(channels[0], channels[1]) as red_green:
            with ImageChops.lighter(red_green, channels[2]) as maximum:
                # Keep achromatic dark lettering while removing colored security backgrounds.
                return maximum.point([0 if value < 145 else 255 for value in range(256)])
    finally:
        for channel in channels:
            channel.close()
        rgb.close()


def _accept_identity_retry(primary, secondary, geometry=None):
    """!
    @brief Decide se accettare la seconda lettura al posto della prima.

    La seconda lettura deve riconoscere un documento d'identità. Con la geometria, le
    maschere proposte sulla seconda devono coprire tutti i pixel coperti da quelle della
    prima, senza avvisi; senza geometria, ogni testo da mascherare della prima deve
    comparire nella seconda (ignorando maiuscole e spazi).
    @param primary Risultato della prima passata OCR.
    @param secondary Risultato candidato della seconda passata.
    @param geometry Geometria della pagina, opzionale, per il confronto in pixel.
    @return Vero se la seconda lettura non riduce la copertura delle redazioni.
    """
    from anonymizer.detect.identity_documents import analyze_identity_document
    from anonymizer.pseudo import should_mask
    from anonymizer.text_pipeline import analyze_text

    identity = analyze_identity_document(secondary)
    if not identity.recognized or not identity.spans:
        return False
    analysis = analyze_text([primary], ner_disabled_reason="ocr_retry_coverage_check")
    if geometry is not None:
        from PIL import Image, ImageOps

        from anonymizer.redact import apply_redactions, propose_redactions

        proposed, warnings, _ = propose_redactions(primary, list(analysis.merged_spans), geometry)
        if warnings:
            return False
        if not proposed:
            return True
        final = analyze_text([secondary], ner_disabled_reason="ocr_retry_coverage_check")
        masks, final_warnings, _ = propose_redactions(secondary, list(final.merged_spans), geometry)
        if final_warnings:
            return False
        monochrome = replace(geometry, pixel_mode="L")
        with Image.new("L", (geometry.width, geometry.height), 255) as white:
            primary_mask = apply_redactions(
                white, tuple(replace(m, confirmed=True) for m in proposed), monochrome
            )
        try:
            remaining = ImageOps.invert(primary_mask)
        finally:
            primary_mask.close()
        try:
            coverage = apply_redactions(
                remaining, tuple(replace(m, confirmed=True) for m in masks), monochrome
            )
        finally:
            remaining.close()
        try:
            return coverage.getbbox() is None
        finally:
            coverage.close()

    def comparable(value):
        """!
        @brief Normalizza un testo eliminando spazi e differenze di maiuscole.
        @param value Testo da normalizzare.
        @return Testo normalizzato per il confronto.
        """
        return "".join(value.casefold().split())

    observed = comparable(secondary.text)
    return all(
        comparable(primary.text[span.start : span.end]) in observed
        for span in analysis.merged_spans
        if should_mask(span)
    )


def _retain_primary_geometry(primary, candidate):
    """!
    @brief Estende i box del candidato per includere l'area dei campi sensibili della prima lettura.

    Per ogni intervallo da mascherare della prima lettura, cerca un intervallo dello stesso
    tipo nel candidato con box sovrapposto e centro vicino, e allarga la regione più
    sovrapposta all'unione dei due box se l'ingrandimento resta contenuto.
    @param primary Risultato della prima passata OCR.
    @param candidate Risultato fuso della seconda passata.
    @return Candidato con le regioni eventualmente allargate.
    """
    from anonymizer.pseudo import should_mask
    from anonymizer.text_pipeline import analyze_text

    before = analyze_text([primary], ner_disabled_reason="ocr_retry_coverage_check")
    after = analyze_text([candidate], ner_disabled_reason="ocr_retry_coverage_check")
    regions = list(candidate.regions)

    def box_for(page, span):
        """!
        @brief Calcola il box che racchiude le regioni della pagina sovrapposte all'intervallo.
        @param page Risultato di pagina.
        @param span Intervallo di testo.
        @return Box (x0, y0, x1, y1), oppure None se nessuna regione ha geometria.
        """
        boxes = [r.box for r in page.regions if r.box and r.start < span.end and span.start < r.end]
        if boxes:
            return (
                min(b[0] for b in boxes),
                min(b[1] for b in boxes),
                max(b[2] for b in boxes),
                max(b[3] for b in boxes),
            )

    def intersection(a, b):
        """!
        @brief Area di intersezione tra due box.
        @param a Primo box (x0, y0, x1, y1).
        @param b Secondo box (x0, y0, x1, y1).
        @return Area sovrapposta, zero se disgiunti.
        """
        return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))

    def area(box):
        """!
        @brief Area di un box.
        @param box Box (x0, y0, x1, y1).
        @return Area del box.
        """
        return (box[2] - box[0]) * (box[3] - box[1])

    for original in before.merged_spans:
        if not should_mask(original) or not (old := box_for(primary, original)):
            continue
        for current in after.merged_spans:
            if current.kind != original.kind or not should_mask(current):
                continue
            new = box_for(candidate, current)
            if not new or intersection(old, new) < 0.65 * min(area(old), area(new)):
                continue
            if any(
                abs((old[i] + old[i + 2]) - (new[i] + new[i + 2]))
                > max(old[i + 2] - old[i], new[i + 2] - new[i])
                for i in (0, 1)
            ):
                continue
            indices = [
                i
                for i, r in enumerate(regions)
                if r.box
                and r.start < current.end
                and current.start < r.end
                and intersection(old, r.box)
            ]
            if not indices:
                continue
            index = max(indices, key=lambda i: intersection(old, regions[i].box))
            region = regions[index]
            union = (
                min(old[0], region.box[0]),
                min(old[1], region.box[1]),
                max(old[2], region.box[2]),
                max(old[3], region.box[3]),
            )
            if area(union) <= 4 * area(region.box):
                # Preserve first-read uncertainty only on an overlapping sensitive field.
                regions[index] = replace(region, box=union)
                break
    return replace(candidate, regions=tuple(regions))


def _merge_identity_retry(primary, secondary):
    """!
    @brief Fonde la seconda lettura con le parole della prima che essa non copre.

    Le regioni della prima lettura che non si sovrappongono ad alcun box della seconda
    vengono accodate al testo, con block_id prefissato da "primary:", e si aggiunge un
    avviso bloccante di revisione.
    @param primary Risultato della prima passata OCR.
    @param secondary Risultato della seconda passata.
    @return Risultato fuso con origine "ocr+identity_fallback".
    """
    from bisect import bisect_left

    text = secondary.text
    regions = list(secondary.regions)
    boxes = sorted((region.box for region in secondary.regions if region.box), key=lambda b: b[1])
    tops = [box[1] for box in boxes]
    max_height = max((box[3] - box[1] for box in boxes), default=0)
    for region in primary.regions:
        if not region.box:
            continue
        x0, y0, x1, y1 = region.box
        nearby = boxes[bisect_left(tops, y0 - max_height) : bisect_left(tops, y1)]
        if any(x0 < box[2] and box[0] < x1 and y0 < box[3] for box in nearby):
            continue
        value = primary.text[region.start : region.end]
        start = len(text) + 1
        text += "\n" + value
        regions.append(
            replace(
                region,
                start=start,
                end=start + len(value),
                block_id="primary:" + (region.block_id or ""),
            )
        )
    return replace(
        secondary,
        text=text,
        regions=tuple(regions),
        extraction_mode="ocr+identity_fallback",
        warnings=(
            *primary.warnings,
            *secondary.warnings,
            Warning("identity_ocr_fallback_requires_review", primary.page_id, blocking=True),
        ),
    )


def recognize(image, item: PageInput, config: OCRConfig = DEFAULT_OCR_CONFIG) -> PageResult:
    """!
    @brief Riconosce il testo di una pagina, con recupero mirato per i documenti d'identità.

    Se la prima lettura suggerisce un documento d'identità non riconosciuto, ne esegue una
    seconda sul solo testo scuro entro il tempo residuo. Se il recupero fallisce o non è
    accettato, restituisce la prima lettura con un avviso bloccante.
    @param image Immagine PIL della pagina.
    @param item Pagina di input con identificatori e geometria.
    @param config Configurazione OCR.
    @return Risultato di pagina della lettura scelta.
    @throws DocumentError Se la prima passata OCR fallisce.
    """
    started = perf_counter()
    primary = _recognize_once(image, item, config)
    if not _identity_retry_needed(primary):
        return primary
    try:
        with _dark_text_image(image) as prepared:
            remaining = config.timeout - (perf_counter() - started)
            if remaining <= 0:
                raise DocumentError("ocr_unavailable_failed_or_timeout")
            scale = 2 if image.width * image.height * 4 <= 10_000_000 else 1
            secondary = _recognize_once(
                prepared, item, replace(config, timeout=remaining, psm=3), scale_override=scale
            )
        candidate = _merge_identity_retry(primary, secondary)
        candidate = _retain_primary_geometry(primary, candidate)
        if _accept_identity_retry(primary, candidate, item.geometry):
            return candidate
    except DocumentError:
        # An optional recovery attempt must not discard a successful primary OCR result.
        pass
    return replace(
        primary,
        warnings=(
            *primary.warnings,
            Warning("identity_ocr_retry_inconclusive", primary.page_id, blocking=True),
        ),
    )
