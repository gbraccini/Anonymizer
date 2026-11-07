"""!
@file event_fields.py
@brief Eventi amministrativi e identificativi espliciti, distinti dalle durate cliniche.

Riconosce etichette come "data prelievo", "luogo e data" o "n. pratica" ed estrae il valore
che le segue: data, ora, luogo o identificativo.
"""

import re
from dataclasses import dataclass
from datetime import date

from anonymizer.detect.context import location_value_end
from anonymizer.detect.regex import ITALIAN_MONTHS
from anonymizer.model import Kind, Span, Validation

## Eventi amministrativi che possono seguire "data", "ora" o "luogo".
_EVENT = (
    r"prelievo|accettazione|ricovero|dimissione|visita|referto|refertazione|"
    r"esame|esecuzione|emissione|redazione|firma|validazione|registrazione"
)
## Separatore tra etichetta e valore: spazi, ":" o "=" opzionali e al piu' un a capo.
_ENDING = r"[ \t]{0,20}[:=]?[ \t]{0,20}(?:(?:\r\n|\r|\n)[ \t]{0,20})?"
## Giorni della settimana in italiano.
_DAY = r"(?:luned[iì]|marted[iì]|mercoled[iì]|gioved[iì]|venerd[iì]|sabato|domenica)"
## Mesi in italiano.
_MONTH = "(?:" + "|".join(ITALIAN_MONTHS) + ")"
## Date numeriche o testuali, con giorno della settimana opzionale.
_DATE = re.compile(
    rf"(?:(?P<weekday>{_DAY})[ \t]+)?(?:"
    r"(?P<yearfirst>\d{4})-(?P<monthfirst>\d{1,2})-(?P<dayfirst>\d{1,2})|"
    r"(?P<day>\d{1,2})[/.-](?P<month>\d{1,2})(?:[/.-](?P<year>\d{4}|\d{2}))?|"
    rf"(?P<textday>\d{{1,2}})[ \t]+(?P<textmonth>{_MONTH})(?:[ \t]+(?P<textyear>\d{{4}}))?"
    r")(?!\w|[/.-]\d)",
    re.IGNORECASE,
)
## Orari hh:mm o hh.mm con secondi opzionali.
_CLOCK = re.compile(r"(?P<hour>\d{1,2})[:.](?P<minute>\d{2})(?:[:.](?P<second>\d{2}))?(?![\w:.])")
## Identificativi alfanumerici fino a 40 caratteri.
_IDENTIFIER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9/_-]{0,38}[A-Za-z0-9])?(?![\w/.-])")
## Unità di misura o durate che rendono un numero un dato clinico.
_UNIT = re.compile(r"[ \t]*(?i:mg|g|kg|ml|dl|mm|cm|mmhg|ui|mesi|anni|giorni|ore)(?!\w)")
## Termini anatomici o clinici che escludono un valore di luogo.
_ANATOMY = re.compile(
    r"(?i:fegato|rene|reni|polmone|polmoni|torace|addome|cute|orale|rettale|"
    r"anatomica|anatomico|lesione|dolore|prelievo|campione|braccio|vena)(?!\w)"
)


@dataclass(frozen=True)
class EventField:
    """!
    @brief Etichetta di campo amministrativo e modalità di lettura del valore.
    """

    ## Valore atteso: "datetime", "time", "location", "location_date" o "identifier".
    mode: str
    ## Regex dell'etichetta, separatore compreso.
    pattern: re.Pattern


def _label(mode, expression):
    """!
    @brief Costruisce un EventField: etichetta non preceduta da lettere, seguita dal separatore.
    @param mode Modalità di lettura del valore.
    @param expression Espressione regolare dell'etichetta.
    @return Campo compilato.
    """
    return EventField(mode, re.compile(r"(?<![\w\u0300-\u036f])(?i:" + expression + ")" + _ENDING))


## Etichette dei campi amministrativi riconosciuti.
EVENT_FIELDS = (
    _label(
        "datetime",
        rf"(?:data(?:[ \t]*(?:e|/)[ \t]*ora)?|giorno)[ \t]+"
        rf"(?:(?:di|del|della)[ \t]+)?(?:{_EVENT})(?!\w)",
    ),
    _label("time", rf"(?:ora|orario)[ \t]+(?:(?:di|del|della)[ \t]+)?(?:{_EVENT})(?!\w)"),
    _label("datetime", rf"(?:{_EVENT})(?!\w)[ \t]*(?:(?:del|il|in[ \t]+data)[ \t]+)?"),
    _label("datetime", r"(?:firmato|validato|emesso|refertato)[ \t]+(?:il|in[ \t]+data)[ \t]+"),
    _label("datetime", r"data(?:[ \t]*(?:e|/)[ \t]*ora)?[ \t]*[:=]"),
    _label("time", r"(?:ora|orario)[ \t]*[:=]"),
    _label("location_date", r"luogo[ \t]+e[ \t]+data[ \t]*[:=]"),
    _label(
        "location",
        rf"(?:luogo|comune|citt[aà]|localit[aà])[ \t]+"
        rf"(?:(?:di|del|della)[ \t]+)?(?:{_EVENT})(?!\w)",
    ),
    _label(
        "location",
        r"(?:luogo|sede[ \t]+(?:operativa|amministrativa|legale)|comune|citt[aà])[ \t]*[:=]",
    ),
    _label(
        "identifier",
        r"(?:(?:n(?:umero)?\.?|n[°º])[ \t]+)?"
        r"(?:cartella[ \t]+clinica|cartella|protocollo|prot\.)(?!\w)"
        r"[ \t]*(?:(?:n(?:umero)?\.?|n[°º])[ \t]*)?",
    ),
    _label(
        "identifier",
        r"(?:n(?:umero)?\.?|n[°º])[ \t]+(?:di[ \t]+)?"
        r"(?:referto|accettazione|pratica|ricovero|esame)(?!\w)",
    ),
    _label("identifier", r"(?:id|cod(?:ice)?\.?)?[ \t]*(?:paziente)[ \t]*[:=]"),
    _label("identifier", r"(?:id|cod(?:ice)?\.?)[ \t]+(?:del[ \t]+)?paziente(?!\w)"),
    _label(
        "identifier",
        r"(?:accettazione|pratica|referto)(?!\w)[ \t]*"
        r"(?:(?:n(?:umero)?\.?|n[°º])[ \t]*)?",
    ),
)


def _date_end(text, start):
    """!
    @brief Restituisce la fine di una data valida che inizia in start.

    Accetta anche il solo giorno della settimana o "mese anno". Rifiuta date inesistenti,
    giorno/mese senza anno non separati da "/" e giorno/mese seguiti da un'unità di misura.
    @param text Testo da analizzare.
    @param start Offset di inizio.
    @return Offset di fine, oppure None.
    """
    match = _DATE.match(text, start)
    if match is None:
        partial = re.match(rf"(?:{_DAY}|{_MONTH}[ \t]+\d{{4}})(?!\w)", text[start:], re.IGNORECASE)
        return start + partial.end() if partial else None
    values = match.groupdict()
    if values["day"] and not values["year"] and "/" not in match.group():
        return None
    if values["yearfirst"]:
        year, month, day = (
            int(values["yearfirst"]),
            int(values["monthfirst"]),
            int(values["dayfirst"]),
        )
    else:
        day = int(values["day"] or values["textday"])
        month = (
            int(values["month"])
            if values["month"]
            else ITALIAN_MONTHS.index(values["textmonth"].casefold()) + 1
        )
        raw_year = values["year"] or values["textyear"]
        year = int(raw_year) if raw_year and len(raw_year) == 4 else 2000
    try:
        date(year, month, day)
    except ValueError:
        return None
    if values["day"] and not values["year"] and _UNIT.match(text, match.end()):
        return None
    return match.end()


def _clock_end(text, start):
    """!
    @brief Restituisce la fine di un orario valido che inizia in start.
    @param text Testo da analizzare.
    @param start Offset di inizio.
    @return Offset di fine, oppure None se ore, minuti o secondi sono fuori intervallo.
    """
    match = _CLOCK.match(text, start)
    if match and int(match["hour"]) <= 23 and int(match["minute"]) <= 59:
        if match["second"] is None or int(match["second"]) <= 59:
            return match.end()
    return None


def parse_event_value(text: str, start: int, mode: str):
    """!
    @brief Restituisce gli intervalli originali del valore, senza mai includere campi intermedi o
           prosa clinica.

    Un identificativo deve contenere una cifra e non essere seguito da un'unità di misura; un
    luogo non deve essere un termine anatomico e, per "location_date", può essere seguito da una
    data dopo una virgola; una data può essere seguita da un orario.
    @param text Testo da analizzare.
    @param start Offset di inizio del valore.
    @param mode Modalità del campo.
    @return Lista di tuple (inizio, fine, tipo, origine).
    """
    if mode == "identifier":
        match = _IDENTIFIER.match(text, start)
        if match and any(c.isdigit() for c in match.group()) and not _UNIT.match(text, match.end()):
            return [(start, match.end(), Kind.CASE_NUMBER, "event:identifier")]
        return []
    if mode in ("location", "location_date"):
        if _ANATOMY.match(text, start):
            return []
        end = location_value_end(text, start)
        if end is None:
            return []
        result = [(start, end, Kind.LOCATION, "event:location")]
        if mode == "location_date":
            separator = re.match(r"[ \t]*,[ \t]*", text[end:])
            if separator:
                result.extend(parse_event_value(text, end + separator.end(), "datetime"))
        return result
    if mode == "time":
        end = _clock_end(text, start)
        return [(start, end, Kind.DATE, "event:time")] if end else []
    end = _date_end(text, start)
    if end is None:
        return []
    result = [(start, end, Kind.DATE, "event:date")]
    separator = re.match(
        r"[ \t]{0,20}(?:,[ \t]{0,20})?(?:(?:\r\n|\r|\n)[ \t]{0,20})?"
        r"(?:(?:ore|alle|h)[ \t]*:?[ \t]*)?",
        text[end:],
        re.IGNORECASE,
    )
    if separator and separator.end():
        time_start = end + separator.end()
        time_end = _clock_end(text, time_start)
        if time_end:
            result.append((time_start, time_end, Kind.DATE, "event:time"))
    return result


def detect_event_fields(text: str, page_id: str, *, identifiers=None) -> list[Span]:
    """!
    @brief Rileva i valori di tutti i campi amministrativi del testo.

    Scarta gli identificativi che coincidono con una data già riconosciuta.
    @param text Testo da analizzare.
    @param page_id Identificativo della pagina.
    @param identifiers True per i soli identificativi, False per escluderli, None per tutto.
    @return Span di livello 1 ordinati.
    """
    found = {}
    for field in EVENT_FIELDS:
        for label in field.pattern.finditer(text):
            for start, end, kind, origin in parse_event_value(text, label.end(), field.mode):
                found[start, end, kind, origin] = Span(
                    page_id,
                    start,
                    end,
                    kind,
                    1,
                    origin,
                    validation=Validation("unchecked", "explicit_administrative_field"),
                )
    date_intervals = {(s.start, s.end) for s in found.values() if s.origin == "event:date"}
    return sorted(
        (
            s
            for s in found.values()
            if not (s.kind == Kind.CASE_NUMBER and (s.start, s.end) in date_intervals)
            and (identifiers is None or (s.kind == Kind.CASE_NUMBER) == identifiers)
        ),
        key=lambda s: (s.start, s.end, s.kind),
    )


def detect_event_identifiers(text: str, page_id: str) -> list[Span]:
    """!
    @brief Rileva solo gli identificativi amministrativi, come numeri di pratica o referto.
    @param text Testo da analizzare.
    @param page_id Identificativo della pagina.
    @return Span di livello 1 ordinati.
    """
    return detect_event_fields(text, page_id, identifiers=True)
