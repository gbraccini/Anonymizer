"""!
@file identity_documents.py
@brief Documenti d'identità italiani: campi espliciti e zone a lettura ottica (MRZ)
complete.

Riconosce carta d'identità (anche elettronica), passaporto e patente da intestazioni,
menzioni con numero e MRZ, ed emette i valori dei campi personali solo in prossimità
di un documento riconosciuto.
"""

import re
from dataclasses import dataclass, replace
from datetime import date

from anonymizer.detect.context import field_name_end, location_value_end
from anonymizer.detect.event_fields import parse_event_value
from anonymizer.model import Kind, PageResult, Span, Validation

## Alternative regex che nominano un tipo di documento d'identità, in italiano o inglese.
_DOCUMENT = (
    r"carta\s+d['’´`]?\s*identit[àa]['’´`]?(?:\s+elettronica)?|"
    r"carta\s+di\s+identit[àa]['’´`]?(?:\s+elettronica)?|CIE|"
    r"passaporto|passport|patente(?:\s+di\s+guida)?|driving\s+licen[cs]e"
)
## Intestazione di documento con prefissi facoltativi (copia, fac-simile, Repubblica).
_HEADING = re.compile(
    r"(?i)\s*(?:(?:copia(?:\s+(?:della|del))?|fac-?simile(?:\s+di\s+prova)?)"
    r"[ :/-]+|documento[ \t]*:[ \t]*)?"
    rf"(?:repubblica\s+italiana[ /-]*)?(?P<document>{_DOCUMENT})"
    r"(?:[ /-]+(?:identity card|passport|driving licen[cs]e))?\s*"
)
## Menzione di un documento seguita dal suo numero, catturato nel gruppo number.
_MENTION = re.compile(
    rf"(?<!\w)(?:(?P<prefix>numero|num\.?|n\.)[ \t]+)?(?:{_DOCUMENT})"
    r"[ \t]{0,10}(?(prefix)[:=]?[ \t]*|"
    r"(?:(?:numero|num\.?|n[.°º]?)[ \t]*[:=]?[ \t]*|[:=][ \t]*))"
    r"(?P<number>(?:[A-Z]{2}[ \t]{0,3}\d{5}[ \t]{0,3}[A-Z]{2}|"
    r"[A-Z]{2}[ \t]{0,3}\d{7}|[A-Z0-9][A-Z0-9/-]{3,19}))(?![\w/-])",
    re.IGNORECASE,
)
## Numero seriale tipico di CIE o passaporto, tollerante a O, I, L lette come cifre.
_SERIAL = re.compile(
    r"(?<!\w)(?:[A-Z]{2}[ \t]{0,3}[0-9OIL]{5}[ \t]{0,3}[A-Z]{2}|"
    r"[A-Z]{2}[ \t]{0,3}\d{7})(?!\w)"
)
## Numero di documento alfanumerico generico.
_NUMBER = re.compile(r"[A-Z0-9][A-Z0-9/-]{3,19}(?![\w/-])", re.IGNORECASE)
## Etichette di campo, anche numerate come sulla patente, con traduzioni facoltative.
_LABEL = re.compile(
    r"(?<!\w)(?P<label>"
    r"cognome\s+e\s+nome\s+del\s+padre\s+e\s+della\s+madre"
    r"(?:\s+o\s+di\s+chi\s+ne\s+fa\s+le\s+veci)?|"
    r"father\s+and\s+mother['’]s[- ]tutor['’]s\s+name|"
    r"codice\s+fiscale|tax\s+code|fiscal\s+code|"
    r"estremi\s+(?:dell['’])?atto\s+di\s+nascita|"
    r"(?:luogo\s+e\s+data|data\s+e\s+luogo)\s+di\s+nascita|"
    r"(?:date\s+and\s+place|place\s+and\s+date)\s+of\s+birth|"
    r"data\s+di\s+nascita|date\s+of\s+birth|luogo\s+di\s+nascita|place\s+of\s+birth|"
    r"data\s+(?:di\s+)?(?:rilascio|emissione|scadenza)|date\s+of\s+(?:issue|expiry)|"
    r"issue\s+date|expiry\s+date|issuing\s+authority|authority|scadenza|expiry|"
    r"rilascio|emissione|issuing|nascita|"
    r"cognome(?:\s*/\s*surname)?|surname|nome(?:\s*/\s*(?:given\s+)?names?)?|"
    r"given\s+names?|name|indirizzo\s+di\s+residenza|residenza|residence|indirizzo|address|"
    r"autorit[àa](?:\s+di\s+rilascio)?|issuing\s+authority|rilasciat[oa]\s+da|"
    r"comune\s+di(?:\s+(?:rilascio|emissione))?|municipality|"
    r"(?:numero|n\.)\s+(?:del\s+)?(?:documento|passaporto|patente)|"
    r"document\s+(?:no\.?|number)|CAN|"
    r"(?:[1-578]|4[abc])\.?(?=[ \t]|$))"
    r"(?!\w)(?:[ \t]*/[ \t]*(?:place and date of birth|date and place of birth|"
    r"date of birth|place of birth|date of issue|date of expiry|issuing authority|"
    r"date de naissance|date de d[eé]livrance|date d'expiration|"
    r"father and mother['’]s[- ]tutor['’]s name|"
    r"given names?|surname|names?|pr[eé]noms?|nom|municipality|authority|residence|"
    r"autorit[eé]|issuing|expiry)"
    r"(?!\w)){0,3}[ \t]*(?:[:=][ \t]*)?",
    re.IGNORECASE,
)
## Inizio di un'etichetta successiva, che delimita il valore del campo corrente.
_NEXT_FIELD = re.compile(
    r"(?i)(?<!\w)(?:sesso|sex|statura|height|cittadinanza|nationality|"
    r"cognome|surname|nome|name|residenza|residence|CAN|data|date|luogo|"
    r"scadenza|expiry|rilascio|firma|signature|autorit[àa])\b"
)
## Singola riga non vuota.
_LINE = re.compile(r"[^\r\n]+")
## Caratteri ammessi in una riga MRZ, spazi OCR compresi.
_MRZ_CHARS = re.compile(r"[A-Z0-9< \t]+")
## Traduzione dell'etichetta dopo una barra, da saltare prima di leggere il valore.
_TRANSLATION = re.compile(
    r"[ \t]*/[ \t]*(?i:(?:place and date|date and place) of birth|"
    r"date of birth|place of birth|date of issue|date of expiry|issuing authority|"
    r"issuing|issue|expiry|surname|given names?|names?|residence|address|authority|"
    r"date de naissance|date de d[eé]livrance|date d'expiration|pr[eé]noms?|nom|autorit[eé])"
    r"(?!\w)[ \t]*[:=]?[ \t]*"
)
## Abbreviazioni dei mesi in italiano e inglese, in ordine di calendario.
_MONTHS = (
    ("GEN", "JAN"),
    ("FEB",),
    ("MAR",),
    ("APR",),
    ("MAG", "MAY"),
    ("GIU", "JUN"),
    ("LUG", "JUL"),
    ("AGO", "AUG"),
    ("SET", "SEP"),
    ("OTT", "OCT"),
    ("NOV",),
    ("DIC", "DEC"),
)
## Data con mese abbreviato ed eventuale traduzione, ad esempio 01 GEN/JAN 2030.
_ABBREVIATED_DATE = re.compile(
    r"(\d{1,2})[ \t]+([A-Z]{3})(?:[ \t]*/[ \t]*([A-Z]{3}))?[ \t]+(\d{4})(?!\w)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class IdentityDocumentAnalysis:
    """!
    @brief Esito dell'analisi di una pagina come documento d'identità.
    """

    ## Intervalli sensibili individuati nella pagina.
    spans: tuple[Span, ...] = ()
    ## Tipi di documento riconosciuti (identity_card, passport, driving_licence), ordinati.
    document_types: tuple[str, ...] = ()

    @property
    def recognized(self):
        """!
        @brief Indica se la pagina contiene almeno un documento d'identità riconosciuto.
        @return True se è stato riconosciuto almeno un tipo di documento.
        """
        return bool(self.document_types)


def _type(value):
    """!
    @brief Riconduce il nome di un documento al suo tipo normalizzato.
    @param value Testo che nomina il documento.
    @return "passport", "driving_licence" oppure "identity_card".
    """
    value = value.casefold()
    if "pass" in value:
        return "passport"
    if "patente" in value or "licen" in value:
        return "driving_licence"
    return "identity_card"


def _mrz(text):
    """!
    @brief Individua zone MRZ italiane complete e strutturalmente valide.

    Riconosce passaporti (due righe da 44 caratteri) e carte d'identità (tre righe da 30)
    su righe consecutive. Le cifre di controllo non sono verificate e alcune lettere sono
    accettate al posto delle cifre, così da tollerare gli errori OCR.
    @param text Testo della pagina.
    @return Generatore di terne (inizio, fine, tipo di documento).
    """
    lines = list(_LINE.finditer(text))
    for index, line in enumerate(lines):
        first = re.sub(r"[ \t]", "", line.group())
        passport = bool(re.match(r"P[A-Z<]ITA", first))
        size, count, kind = (44, 2, "passport") if passport else (30, 3, "identity_card")
        if not (passport or re.match(r"[ACI][A-Z<]ITA", first)) or index + count > len(lines):
            continue
        selected = lines[index : index + count]
        compact = [re.sub(r"[ \t]", "", item.group()) for item in selected]
        if any(len(value) != size for value in compact):
            continue
        if not all(_MRZ_CHARS.fullmatch(item.group()) for item in selected):
            continue
        if any(
            not re.fullmatch(r"\r\n|\r|\n", text[a.end() : b.start()])
            for a, b in zip(selected, selected[1:], strict=False)
        ):
            continue
        names = compact[0][5:] if passport else compact[2]
        if not re.fullmatch(r"[A-Z<]+", names) or not any(c.isalpha() for c in names):
            continue
        # Structural positions survive erroneous check digits and common OCR digit substitutions.
        digits = r"[0-9OILZSB]"
        check = r"[A-Z0-9<]"
        second = (
            rf"[A-Z0-9<]{{9}}{check}[A-Z<]{{3}}{digits}{{6}}{check}[MFX<]"
            rf"{digits}{{6}}{check}[A-Z0-9<]{{16}}"
            if passport
            else rf"{digits}{{6}}{check}[MFX<]{digits}{{6}}{check}[A-Z<]{{3}}[A-Z0-9<]{{12}}"
        )
        if not re.fullmatch(second, compact[1]):
            continue
        yield selected[0].start(), selected[-1].end(), kind


def _damaged_mrz(page):
    """!
    @brief Individua MRZ di carte d'identità danneggiate dall'OCR.

    Accetta tre righe consecutive di lunghezza approssimata con struttura plausibile. Se
    l'emittente non è leggibile o non è italiano servono campi tipici del retro della
    carta nella stessa pagina; con la geometria disponibile le righe devono essere
    allineate verticalmente.
    @param page Pagina con testo e regioni OCR.
    @return Generatore di terne (inizio, fine, "identity_card").
    """
    text = page.text
    reverse_fields = (
        bool(re.search(r"(?i)codice\s*fiscale", text))
        and bool(re.search(r"(?i)residenza|residence", text))
        and bool(re.search(r"(?i)\bpadre\b", text))
        and bool(re.search(r"(?i)\bmadre\b", text))
    )
    corroborated = (
        bool(re.search(r"(?i)codice\s*fiscale", text))
        and bool(re.search(r"(?i)residenza|residence", text))
        and bool(re.search(r"(?i)atto\s+di\s+nascita|padre.*madre", text))
    )
    lines = list(_LINE.finditer(text))
    for index in range(len(lines) - 2):
        group = lines[index : index + 3]
        if any(
            text[a.end() : b.start()] not in ("\n", "\r", "\r\n")
            for a, b in zip(group, group[1:], strict=False)
        ):
            continue
        values = [re.sub(r"[ \t]", "", line.group()).replace("«", "<<").upper() for line in group]
        if not all(
            26 <= len(value) <= 40 and re.fullmatch(r"[A-Z0-9<]+", value) for value in values
        ):
            continue
        first, second, names = values
        issuer = re.match(r"[ACI][A-Z<]([A-Z]{3})", first)
        damaged_prefix = (
            reverse_fields and first.count("<") >= 3 and sum(c.isdigit() for c in first) >= 2
        )
        if (not issuer or issuer[1] != "ITA" and not corroborated) and not damaged_prefix:
            continue
        if not damaged_prefix and (first.count("<") < 8 or sum(c.isdigit() for c in first) < 4):
            continue
        if not re.match(r"[0-9OILZSB]{6,8}[MFX<][0-9OILZSB]{6,8}[A-Z<]{3}", second):
            continue
        if names.count("<") < 6 or not re.fullmatch(r"[A-Z]+(?:<[A-Z]+)*<<[A-Z<]+", names):
            continue
        boxes = []
        for line in group:
            regions = [
                r.box
                for r in page.regions
                if r.box and r.start < line.end() and line.start() < r.end
            ]
            if regions:
                boxes.append(
                    (
                        min(b[0] for b in regions),
                        min(b[1] for b in regions),
                        max(b[2] for b in regions),
                        max(b[3] for b in regions),
                    )
                )
        if page.regions:
            if len(boxes) != 3:
                continue
            aligned = True
            for a, b in zip(boxes, boxes[1:], strict=False):
                height = max(a[3] - a[1], b[3] - b[1])
                overlap = min(a[2], b[2]) - max(a[0], b[0])
                if not (
                    -0.5 * min(a[3] - a[1], b[3] - b[1]) <= b[1] - a[3] <= 2 * height
                    and overlap >= 0.7 * min(a[2] - a[0], b[2] - b[0])
                ):
                    aligned = False
            if not aligned:
                continue
        yield group[0].start(), group[-1].end(), "identity_card"


def _mode(label, licence):
    """!
    @brief Associa un'etichetta di campo alla modalità di lettura del suo valore.
    @param label Testo dell'etichetta trovata.
    @param licence True se il campo è vicino a una patente: abilita i campi numerati.
    @return Modalità ("name", "birth", "date", "number", "address", ...), oppure None se
            l'etichetta numerata non è applicabile.
    """
    value = label.casefold().rstrip(".").strip()
    if value in {"codice fiscale", "tax code", "fiscal code"}:
        return "tax_code"
    if value.startswith("estremi"):
        return "registration"
    numbered = {
        "1": "name",
        "2": "name",
        "3": "birth",
        "4a": "date",
        "4b": "date",
        "4c": "authority",
        "5": "number",
        "8": "address",
    }
    if value in numbered or value == "7":
        return numbered.get(value) if licence else None
    if value == "can":
        return "can"
    if value.startswith(("numero", "n.", "document")):
        return "number"
    if "birth" in value or "nascita" in value:
        return "location" if value.startswith(("luogo di", "place of")) else "birth"
    if (
        "data" in value
        or "date" in value
        or value in {"scadenza", "expiry", "rilascio", "emissione", "issuing"}
    ):
        return "date"
    if value.startswith(("autorit", "issuing", "rilasciat", "comune", "municipality")):
        return "authority"
    if value in {"residenza", "residence", "indirizzo", "address"} or value.startswith(
        "indirizzo di"
    ):
        return "address"
    return "name"


def _values(text, mode):
    """!
    @brief Estrae i valori di un campo dal testo che segue l'etichetta.

    Il testo è limitato a 180 caratteri e troncato alla successiva etichetta
    riconoscibile. In modalità birth separa luogo e data di nascita.
    @param text Testo a partire dall'inizio del valore.
    @param mode Modalità restituita da _mode().
    @return Generatore di tuple (inizio, fine, Kind, origine) relative a text.
    """
    text = text[:180]
    stop = _NEXT_FIELD.search(text)
    if stop:
        text = text[: stop.start()].rstrip()
    if mode == "tax_code":
        match = re.match(
            r"[.·•]?[ \t]*(?P<code>(?=[A-Z0-9]{14,18}(?!\w))(?=[A-Z0-9]*\d)[A-Z0-9]+)", text
        )
        if match and any(c.isalpha() for c in match.group("code")):
            yield *match.span("code"), Kind.CF, "tax_code"
    elif mode in {"number", "can", "registration"}:
        pattern = _NUMBER
        if mode == "can":
            pattern = re.compile(r"\d{6}(?!\w)")
        elif mode == "registration":
            pattern = re.compile(r"[A-Z0-9][A-Z0-9./-]{3,29}(?![\w./-])", re.IGNORECASE)
        match = pattern.match(text)
        if match and any(c.isdigit() for c in match.group()):
            yield (
                match.start(),
                match.end(),
                Kind.CASE_NUMBER,
                {"number": "document_number", "can": "can", "registration": "registration"}[mode],
            )
    elif mode in {"date", "birth"}:
        if mode == "date":
            numeric = re.match(r"\d{1,2}[./-]\d{1,2}[./-]\d{4}(?!\d)", text)
            if numeric:
                # An invalid OCR digit must not expose an explicitly labelled identity date.
                yield 0, numeric.end(), Kind.DATE, "date"
        abbreviated = _ABBREVIATED_DATE.match(text)
        if abbreviated:
            day, month, translated, year = abbreviated.groups()
            number = next((i for i, names in enumerate(_MONTHS, 1) if month.upper() in names), None)
            if number and (not translated or translated.upper() in _MONTHS[number - 1]):
                try:
                    date(int(year), number, int(day))
                except ValueError:
                    pass
                else:
                    yield (
                        0,
                        abbreviated.end(),
                        (Kind.BIRTH_DATE if mode == "birth" else Kind.DATE),
                        "birth_date" if mode == "birth" else "date",
                    )
        for start, end, _, _ in parse_event_value(text, 0, "datetime"):
            yield (
                start,
                end,
                Kind.BIRTH_DATE if mode == "birth" else Kind.DATE,
                ("birth_date" if mode == "birth" else "date"),
            )
        if mode == "birth":
            for match in re.finditer(r"(?<!\d)\d{1,2}[./-]\d{1,2}[./-]\d{4}(?!\d)", text):
                prefix = text[: match.start()].strip(" ,;-")
                syntax = re.sub(r"[\[({][ \t]*([A-Z]{2})[ \t]*[\])}]$", r"(\1)", prefix)
                words = re.findall(r"[^\W\d_]+", prefix)
                particles = {"di", "del", "della", "delle", "dei", "sul", "sulla", "da", "a", "e"}
                plausible = (
                    prefix
                    and len(words) <= 14
                    and all(word[0].isupper() or word in particles for word in words)
                    and re.fullmatch(r"[^\d\W]+(?:[ '\u2019()./-]+[^\d\W]+)*[)]?", syntax)
                )
                dates = list(parse_event_value(text, match.start(), "datetime"))
                if plausible and dates:
                    end = len(text[: match.start()].rstrip(" ,;-"))
                    yield 0, end, Kind.LOCATION, "location"
                    for start, date_end, _, _ in dates:
                        yield start, date_end, Kind.BIRTH_DATE, "birth_date"
                    return
            end = location_value_end(text, 0)
            if end:
                yield 0, end, Kind.LOCATION, "location"
                rest = re.match(r"[ ,;-]*", text[end:]).end() + end
                for start, date_end, _, _ in parse_event_value(text, rest, "datetime"):
                    yield start, date_end, Kind.BIRTH_DATE, "birth_date"
            else:
                dates = list(parse_event_value(text, 0, "datetime"))
                if dates:
                    rest = dates[-1][1] + re.match(r"[ ,;-]*", text[dates[-1][1] :]).end()
                    location_end = location_value_end(text, rest)
                    if location_end:
                        yield rest, location_end, Kind.LOCATION, "location"
    elif mode == "name":
        end = field_name_end(text, 0)
        if end:
            yield 0, end, Kind.PERSON, "name"
    elif mode == "location":
        end = location_value_end(text, 0)
        if end:
            yield 0, end, Kind.LOCATION, "location"
    elif mode in {"address", "authority"}:
        value = re.match(r"[^\r\n;|]{2,120}", text)
        if value and any(c.isalpha() for c in value.group()):
            kind = Kind.ADDRESS if mode == "address" else Kind.FACILITY
            yield 0, len(value.group().rstrip(" ,")), kind, mode


def _near_document_box(current, anchor):
    """!
    @brief Verifica se un riquadro è vicino a quello di un documento riconosciuto.
    @param current Riquadro (x0, y0, x1, y1) da valutare.
    @param anchor Riquadro di riferimento del documento.
    @return True se la distanza, proporzionale all'altezza del testo, è ammessa.
    """
    height = max(current[3] - current[1], anchor[3] - anchor[1])
    gap = max(0, current[0] - anchor[2], anchor[0] - current[2])
    return abs(current[1] - anchor[1]) <= 32 * height and gap <= 16 * height


def _identity_rows(units):
    """!
    @brief Raggruppa le unità di layout in righe orizzontali.
    @param units Unità di testo con riquadro.
    @return Righe dall'alto verso il basso, ciascuna ordinata da sinistra a destra.
    """
    rows = []
    for unit in sorted(units, key=lambda u: (u.box[1], u.box[0])):
        if rows:
            anchor = rows[-1][0].box
            if abs((anchor[1] + anchor[3]) - (unit.box[1] + unit.box[3])) <= min(
                anchor[3] - anchor[1], unit.box[3] - unit.box[1]
            ):
                rows[-1].append(unit)
                continue
        rows.append([unit])
    return [sorted(row, key=lambda u: u.box[0]) for row in rows]


def _identity_values(rows, row_index, stop, selected, height, max_units=8):
    """!
    @brief Trova le unità di layout che contengono il valore di un'etichetta.

    Cerca prima accanto all'etichetta, poi in una delle righe sottostanti con una sola
    unità allineata a sinistra con l'etichetta.
    @param rows Righe di layout.
    @param row_index Indice della riga dell'etichetta.
    @param stop Indice della prima unità che segue l'etichetta nella riga.
    @param selected Unità che compongono l'etichetta.
    @param height Altezza di riferimento del testo.
    @param max_units Con un valore diverso da 8 il valore viene esteso sulla sua riga
           fino a questo numero di unità contigue.
    @return Unità del valore, eventualmente nessuna.
    """
    from anonymizer.detect.layout import _nearby_values, _value_units

    def extended(values):
        """!
        @brief Estende il valore alle unità contigue della sua riga, entro max_units unità
        e 180 caratteri.
        """
        if not values or max_units == 8:
            return values
        containing = next(row for row in rows[row_index : row_index + 4] if values[0] in row)
        start = containing.index(values[0])
        result, count = [], 0
        for unit in containing[start : start + max_units]:
            if result and unit.box[0] - result[-1].box[2] > 2 * height:
                break
            count += unit.end - unit.start + 1
            if count > 180:
                break
            result.append(unit)
        return result

    values = _nearby_values(rows, row_index, stop, selected, height)
    if values or row_index + 1 >= len(rows):
        return extended(values)
    for below in rows[row_index + 1 : row_index + 4]:
        aligned = [
            i
            for i, unit in enumerate(below)
            if abs(unit.box[0] - selected[0].box[0]) <= 1.5 * height
        ]
        if len(aligned) == 1:
            gap = below[aligned[0]].box[1] - max(unit.box[3] for unit in selected)
            if 0 <= gap <= 2 * height:
                return extended(_value_units(below, aligned[0], height))
    return []


def analyze_identity_document(page: PageResult) -> IdentityDocumentAnalysis:
    """!
    @brief Analizza una pagina alla ricerca di documenti d'identità e dei loro campi.

    MRZ e menzioni con numero sono emesse sempre. I valori dei campi etichettati sono
    emessi solo vicino a un'intestazione o a una MRZ: per geometria se la pagina ha
    riquadri, altrimenti per distanza nel testo. I campi numerati della patente sono
    emessi solo se formano un gruppo coerente.
    @param page Pagina da analizzare.
    @return Intervalli trovati e tipi di documento riconosciuti.
    """
    # Imported locally: the shared layout parser itself imports generic field detectors.
    from anonymizer.detect.layout import _intervals, _joined, _rows, _units

    found, types, anchors = {}, set(), []
    numbered_fields = []
    electronic = False

    def emit(start, end, kind, origin):
        """!
        @brief Registra un intervallo senza duplicati, con origine "identity:" + origin.
        """
        key = start, end, kind, origin
        found[key] = Span(
            page.page_id,
            start,
            end,
            kind,
            1,
            "identity:" + origin,
            validation=Validation("unchecked", "explicit_identity_document"),
        )

    strict_zones = list(_mrz(page.text))
    damaged_zones = [
        zone
        for zone in _damaged_mrz(page)
        if not any(a <= zone[0] and zone[1] <= b for a, b, _ in strict_zones)
    ]
    for start, end, kind in (*strict_zones, *damaged_zones):
        electronic |= kind == "identity_card"
        emit(start, end, Kind.CASE_NUMBER, "mrz")
        types.add(kind)
        positions = [i for i in range(start, end) if not page.text[i].isspace()]
        first = 44 if kind == "passport" else 5
        number = positions[first : first + 9]
        if number and (start, end, kind) in strict_zones:
            emit(number[0], number[-1] + 1, Kind.CASE_NUMBER, "document_number")
        first_end = re.search(r"\r|\n", page.text[start:end])
        first_end = start + first_end.start() if first_end else end
        boxes = [r.box for r in page.regions if r.box and r.start < first_end and start < r.end]
        anchor_box = (
            (
                min(b[0] for b in boxes),
                min(b[1] for b in boxes),
                max(b[2] for b in boxes),
                max(b[3] for b in boxes),
            )
            if boxes
            else None
        )
        anchors.append((start, anchor_box, kind))
    for match in _MENTION.finditer(page.text):
        emit(*match.span("number"), Kind.CASE_NUMBER, "document_number")
    if not anchors and not re.search(_DOCUMENT, page.text, re.IGNORECASE):
        return IdentityDocumentAnalysis(tuple(found.values()), tuple(sorted(types)))
    geometric = bool(any(region.box for region in page.regions))
    # Rotated diagram captions must not join several horizontal field rows together.
    layout_page = replace(
        page,
        regions=tuple(r for r in page.regions if not (r.block_id or "").startswith("primary:")),
    )
    units = _units(layout_page) if geometric else []
    horizontal_units = [
        unit
        for unit in units
        if not (
            unit.box[3] - unit.box[1] > 2 * (unit.box[2] - unit.box[0])
            and sum(c.isalpha() for c in page.text[unit.start : unit.end]) >= 3
        )
    ]
    rows = _identity_rows(horizontal_units) if geometric else []
    views = (
        [(*_joined(page, row), row) for row in rows]
        if geometric
        else [(m.group(), list(range(m.start(), m.end())), []) for m in _LINE.finditer(page.text)]
    )
    field_types = {
        "surname"
        if m.group("label").casefold().startswith(("cognome", "surname"))
        else "name"
        if m.group("label").casefold().startswith(("nome", "given", "name"))
        else "birth"
        if "nascita" in m.group("label").casefold()
        else "other"
        for m in _LABEL.finditer(page.text)
    } - {"other"}
    issuer_context = "repubblica" in page.text.casefold() and "ministero" in page.text.casefold()
    field_cluster = (
        len(field_types) >= 3 or bool(field_types & {"surname", "name"}) and issuer_context
    )
    heading_views = (
        [(*_joined(page, row), row) for row in _rows(horizontal_units)] if geometric else views
    )
    for text, offsets, row in heading_views:
        serial = _SERIAL.search(text)
        heading_text = text[: serial.start()].rstrip(" :/-") if serial else text
        heading = _HEADING.fullmatch(heading_text)
        if not heading and "/" in heading_text:
            native, translation = heading_text.split("/", 1)
            if re.fullmatch(r"[ A-Z]{2,40}", translation):
                heading = _HEADING.fullmatch(native)
        if not heading and field_cluster:
            segment = re.search(rf"(?i)(?<!\w)(?P<document>{_DOCUMENT})(?!\w)", heading_text)
            if segment and len(segment.group("document").split()) >= 3:
                heading = segment
        if heading:
            kind = _type(heading.group("document"))
            types.add(kind)
            heading_offset = offsets[heading.start("document")]
            title_offsets = {
                o
                for o in offsets[heading.start("document") : heading.end("document")]
                if o is not None
            }
            title_units = [u for u in row if any(u.start <= o < u.end for o in title_offsets)]
            heading_box = (
                (
                    min(u.box[0] for u in title_units),
                    min(u.box[1] for u in title_units),
                    max(u.box[2] for u in title_units),
                    max(u.box[3] for u in title_units),
                )
                if title_units
                else None
            )
            anchors.append((heading_offset or offsets[0], heading_box, kind))
            electronic |= kind == "identity_card" and (
                bool(re.search(r"(?i)elettronica|\bCIE\b", heading_text))
                or bool(
                    serial and re.fullmatch(r"[A-Z]{2}\s*[0-9OIL]{5}\s*[A-Z]{2}", serial.group())
                )
            )
    electronic |= "identity_card" in types and bool(
        re.search(r"(?<!\w)[A-Z]{2}[ \t]{0,3}[0-9OIL]{5}[ \t]{0,3}[A-Z]{2}(?!\w)", page.text)
    )
    if not anchors:
        return IdentityDocumentAnalysis(tuple(found.values()), tuple(sorted(types)))
    for row_index, (text, offsets, row) in enumerate(views):
        nearby = []
        for offset, box, kind in anchors:
            if row and box:
                if any(_near_document_box(unit.box, box) for unit in row):
                    nearby.append(kind)
            elif (
                not geometric
                and abs(offsets[0] - offset) <= 1800
                and (
                    len(page.text[min(offset, offsets[0]) : max(offset, offsets[0])].splitlines())
                    <= 20
                )
            ):
                nearby.append(kind)
        if not nearby:
            continue
        if electronic and "identity_card" in nearby:
            isolated = re.fullmatch(r"[ \t]*(\d{6})[ \t]*", text)
            if isolated:
                for start, end in _intervals(page, offsets[isolated.start(1) : isolated.end(1)]):
                    emit(start, end, Kind.CASE_NUMBER, "can")
            if row and not isolated:
                for position, unit in enumerate(row):
                    value = page.text[unit.start : unit.end]
                    if not re.fullmatch(r"\d{6}", value):
                        continue
                    height = unit.box[3] - unit.box[1]
                    neighbours = (
                        row[max(0, position - 1) : position] + row[position + 1 : position + 2]
                    )
                    attached = any(
                        min(abs(other.box[0] - unit.box[2]), abs(unit.box[0] - other.box[2]))
                        <= 3 * height
                        and any(c.isalpha() for c in page.text[other.start : other.end])
                        for other in neighbours
                    )
                    if not attached:
                        emit(unit.start, unit.end, Kind.CASE_NUMBER, "can")
        for serial in _SERIAL.finditer(text):
            for start, end in _intervals(page, offsets[serial.start() : serial.end()]):
                emit(start, end, Kind.CASE_NUMBER, "document_number")
        last_number_end = None
        for label in _LABEL.finditer(text):
            numeric = label.group("label").casefold().rstrip(".")
            is_numeric = numeric in {"1", "2", "3", "4a", "4b", "4c", "5", "8"}
            if (
                is_numeric
                and text[: label.start()].strip()
                and (last_number_end is None or text[last_number_end : label.start()].strip())
            ):
                continue
            mode = _mode(label.group("label"), "driving_licence" in nearby)
            if mode is None or mode == "can" and "identity_card" not in nearby:
                continue
            value_text, value_offsets = text[label.end() :], offsets[label.end() :]
            if row:
                selected = [
                    u
                    for u in row
                    if any(
                        o is not None and u.start <= o < u.end
                        for o in offsets[label.start() : label.end()]
                    )
                ]
                if not selected:
                    continue
                label_box = (
                    min(u.box[0] for u in selected),
                    min(u.box[1] for u in selected),
                    max(u.box[2] for u in selected),
                    max(u.box[3] for u in selected),
                )
                if not any(box and _near_document_box(label_box, box) for _, box, _ in anchors):
                    continue
                label_end = offsets[label.end() - 1]
                if label_end is not None and selected[-1].end > label_end + 1:
                    count = selected[-1].end - label_end - 1
                    value_text, value_offsets = value_text[:count], value_offsets[:count]
                else:
                    stop = row.index(selected[-1]) + 1
                    height = max(u.box[3] - u.box[1] for u in selected)
                    limit = 16 if mode == "birth" else 8
                    values = _identity_values(rows, row_index, stop, selected, height, limit)
                    value_text, value_offsets = _joined(page, values)
                    if re.fullmatch(
                        r"[ \t]*/[ \t]*[A-ZÀ-ÖØ-Þ]{2,15}(?:[ \t]+[A-ZÀ-ÖØ-Þ]{2,15}){0,3}[ \t]*",
                        value_text,
                    ):
                        # A short damaged translation beside the label is not its value.
                        values = _identity_values(
                            rows, row_index, len(row), selected, height, limit
                        )
                        value_text, value_offsets = _joined(page, values)
            elif not value_text.strip():
                if row_index + 1 < len(views):
                    next_text, next_offsets, _ = views[row_index + 1]
                    if re.fullmatch(r"\r\n|\r|\n", page.text[offsets[-1] + 1 : next_offsets[0]]):
                        value_text, value_offsets = next_text, next_offsets
            for _ in range(3):
                translation = _TRANSLATION.match(value_text)
                if not translation:
                    break
                value_text = value_text[translation.end() :]
                value_offsets = value_offsets[translation.end() :]
            values = list(_values(value_text, mode))
            if is_numeric:
                if numeric == "5":
                    values = [
                        v
                        for v in values
                        if re.fullmatch(
                            r"(?=[A-Z0-9/-]{8,20}$)(?=.*[A-Z])(?=.*\d)[A-Z0-9/-]+",
                            value_text[v[0] : v[1]],
                            re.IGNORECASE,
                        )
                    ]
                numbered_fields.append((row_index, numeric, value_offsets, values))
                if values:
                    last_number_end = label.end() + max(v[1] for v in values)
                continue
            for start, end, kind, origin in values:
                for left, right in _intervals(page, value_offsets[start:end]):
                    emit(left, right, kind, origin)
    for index, numeric, offsets, values in numbered_fields:
        neighbours = {
            key
            for other, key, _, parsed in numbered_fields
            if abs(other - index) <= 12
            and not any(
                not line.strip()
                for line in page.text[
                    min(views[other][1][0], views[index][1][0]) : max(
                        views[other][1][0], views[index][1][0]
                    )
                ].splitlines()
            )
            and parsed
            and (key != "3" or any(v[2] == Kind.BIRTH_DATE for v in parsed))
        }
        coherent = {"1", "2", "3", "5"} <= neighbours or {"4a", "4b", "5"} <= neighbours
        if numeric != "5" and not coherent:
            continue
        if numeric == "3" and not any(v[2] == Kind.BIRTH_DATE for v in values):
            continue
        for start, end, kind, origin in values:
            for left, right in _intervals(page, offsets[start:end]):
                emit(left, right, kind, origin)
    return IdentityDocumentAnalysis(tuple(found.values()), tuple(sorted(types)))


def detect_identity_documents(page: PageResult) -> list[Span]:
    """!
    @brief Restituisce i soli intervalli prodotti da analyze_identity_document().
    @param page Pagina da analizzare.
    @return Intervalli trovati.
    """
    return list(analyze_identity_document(page).spans)


def detect_document_number_repetitions(pages, seeds):
    """!
    @brief Propaga i numeri di documento già trovati alle loro occorrenze nella stessa
    sorgente.

    Sono propagati solo i numeri di 8-20 caratteri che contengono sia lettere sia cifre;
    nelle occorrenze sono tollerati spazi tra i caratteri.
    @param pages Pagine del documento.
    @param seeds Intervalli già trovati; si usano quelli con origine
           identity:document_number.
    @return Intervalli per ogni occorrenza, comprese quelle già note.
    """
    by_page = {page.page_id: page for page in pages}
    patterns = {}
    for seed in seeds:
        page = by_page.get(seed.page_id)
        if not page or seed.origin != "identity:document_number":
            continue
        value = re.sub(r"[ \t]", "", page.text[seed.start : seed.end])
        if not re.fullmatch(r"[A-Z0-9]{8,20}", value):
            continue
        if not any(c.isalpha() for c in value) or not any(c.isdigit() for c in value):
            continue
        patterns[page.source_id, value] = re.compile(
            r"(?<!\w)" + r"[ \t]{0,3}".join(map(re.escape, value)) + r"(?!\w)"
        )
    return [
        Span(
            page.page_id,
            m.start(),
            m.end(),
            Kind.CASE_NUMBER,
            1,
            "identity:document_number",
            validation=Validation("unchecked", "same_source_serial"),
        )
        for page in pages
        for (source, _), pattern in patterns.items()
        if source == page.source_id
        for m in pattern.finditer(page.text)
    ]
