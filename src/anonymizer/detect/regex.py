"""!
@file regex.py
@brief Rilevatori di livello 1 basati su espressioni regolari e validazione strutturale.

Combina email, IBAN, identificativi amministrativi, telefoni, codici fiscali, date
(distinguendo quelle di nascita), CAP e tessera sanitaria.
"""

import re

from anonymizer.cf import cf_variants, is_plausible_cf, is_valid_cf
from anonymizer.detect.phones import detect_phones
from anonymizer.detect.structured import detect_emails, detect_ibans
from anonymizer.model import Kind, Span, Validation

## Nomi dei mesi in italiano, in ordine.
ITALIAN_MONTHS = (
    "gennaio",
    "febbraio",
    "marzo",
    "aprile",
    "maggio",
    "giugno",
    "luglio",
    "agosto",
    "settembre",
    "ottobre",
    "novembre",
    "dicembre",
)
## Date ISO, gg/mm/aa(aa) con separatori / . - oppure con il mese in lettere.
DATE_PATTERN = (
    r"(?:\d{4}-\d{2}-\d{2}|\d{1,2}[/.-]\d{1,2}[/.-](?:\d{4}|\d{2})"
    rf"|\d{{1,2}}\s+(?:{'|'.join(ITALIAN_MONTHS)})\s+\d{{4}})"
)
## Candidati codice fiscale di 16 caratteri.
_CF_CANDIDATE = re.compile(r"(?<!\w)[A-Z0-9]{16}(?!\w)", re.IGNORECASE)
## Codici fiscali con i caratteri separati da singoli spazi.
_SPACED_CF = re.compile(r"(?<!\w)(?:[A-Z0-9][ \t]){15}[A-Z0-9](?!\w)", re.IGNORECASE)
## Date non adiacenti ad altre cifre.
_DATE = re.compile(rf"(?<!\d){DATE_PATTERN}(?!\d)", re.IGNORECASE)
## Contesto di nascita subito prima di una data, come "nato il" o "d.n.".
_BIRTH_CONTEXT = re.compile(
    r"\b(?:nat[oa](?:/[oa])?(?:\s+(?:il|a))?|nascita|d\.?\s*n\.?)\s*[:=]?\s*$",
    re.IGNORECASE,
)
## Parola di un toponimo, con apostrofi o trattini interni.
_PLACE_WORD = r"[^\W\d_]+(?:['’\-][^\W\d_]+)*"
## Contesto "nato a <luogo> il" prima di una data; "mato" copre un errore OCR.
_BIRTH_PLACE_CONTEXT = re.compile(
    rf"\b(?:nat[oa](?:/[oa])?|mat[oa])\s+a(?:\s*[:=]\s*|\s+)"
    rf"(?P<place>{_PLACE_WORD}(?:\s+{_PLACE_WORD}){{0,7}}"
    r"(?:\s*\([a-z]{2}\))?)\s*,?\s+(?:il|i|l)\s*[:=]?\s*$",
    re.IGNORECASE,
)
## Parole che indicano che il presunto luogo di nascita è altra prosa.
_BIRTH_PLACE_BREAK = re.compile(
    r"\b(?:il|e|nat[oa]|mat[oa]|ricover\w*|dimess\w*|visit\w*|controll\w*|"
    r"aggiornat\w*|esam\w*|refert\w*|preliev\w*|intervent\w*|access\w*|"
    r"terapi\w*|diagnos\w*|operat\w*|decedut\w*)\b",
    re.IGNORECASE,
)
## Valori con contesto esplicito: (tipo, regex, gruppo del valore).
_PATTERNS = (
    (Kind.POSTCODE, re.compile(r"\bCAP\s*[:=]?\s*(\d{5})(?!\d)", re.IGNORECASE), 1),
    (
        Kind.HEALTH_CARD,
        re.compile(r"\b(?:tessera\s+sanitaria|TS)\s*[:=]?\s*(\d{15,20})(?!\d)", re.IGNORECASE),
        1,
    ),
)


def _has_birth_context(text: str, date_start: int) -> bool:
    """!
    @brief Indica se una data è preceduta da un contesto di nascita entro 192 caratteri.
    @param text Testo della pagina.
    @param date_start Offset di inizio della data.
    @return True se il contesto è di nascita.
    """
    context_start = max(0, date_start - 192)
    direct = _BIRTH_CONTEXT.search(text, context_start, date_start)
    birthplace = _BIRTH_PLACE_CONTEXT.search(text, context_start, date_start)
    match = direct or birthplace
    if match is None:
        return False
    # OCR may wrap a birth field, but a blank line or distant section ends its scope.
    field = match.group()
    if field.count("\n") > 3 or re.search(r"\n[^\S\n]*\n", field):
        return False
    return direct is not None or not _BIRTH_PLACE_BREAK.search(birthplace["place"])


def detect_regex(text: str, page_id: str) -> list[Span]:
    """!
    @brief Esegue i rilevatori strutturati e a espressioni regolari su una pagina.

    Date e span già trovati sono esclusi dalla ricerca dei telefoni. I codici fiscali con
    checksum errato restano mascherati, marcati come non validi.
    @param text Testo della pagina.
    @param page_id Identificativo della pagina.
    @return Span di livello 1 ordinati per inizio, fine e tipo.
    """
    from anonymizer.detect.event_fields import detect_event_identifiers

    spans = [*detect_emails(text, page_id), *detect_ibans(text, page_id)]
    spans.extend(detect_event_identifiers(text, page_id))
    dates = list(_DATE.finditer(text))
    excluded = [(m.start(), m.end()) for m in dates] + [(s.start, s.end) for s in spans]
    spans.extend(detect_phones(text, page_id, excluded))
    for pattern in (_CF_CANDIDATE, _SPACED_CF):
        for match in pattern.finditer(text):
            value = re.sub(r"\s", "", match.group())
            variants = cf_variants(value)
            if not variants:
                continue
            candidate = variants[0] if is_plausible_cf(value) else variants[-1]
            valid = is_valid_cf(candidate)
            spans.append(
                Span(
                    page_id,
                    match.start(),
                    match.end(),
                    Kind.CF,
                    1,
                    "regex:cf",
                    validation=Validation(
                        "valid" if valid else "invalid",
                        "checksum_and_date"
                        if valid
                        else "plausible_identifier_masked_despite_validation",
                    ),
                )
            )
    for match in dates:
        birth = _has_birth_context(text, match.start())
        spans.append(
            Span(
                page_id,
                match.start(),
                match.end(),
                Kind.BIRTH_DATE if birth else Kind.DATE,
                1,
                "regex:birth_date" if birth else "regex:date",
                validation=Validation(
                    "unchecked", "birth_context" if birth else "event_or_unknown_date"
                ),
            )
        )
    for kind, pattern, group in _PATTERNS:
        for match in pattern.finditer(text):
            if kind == Kind.CASE_NUMBER and not any(char.isdigit() for char in match[group]):
                continue
            spans.append(
                Span(
                    page_id,
                    match.start(group),
                    match.end(group),
                    kind,
                    1,
                    f"regex:{kind.value.lower()}",
                    validation=Validation(
                        "unchecked", "explicit_context" if group else "structure"
                    ),
                )
            )
    return sorted(spans, key=lambda item: (item.start, item.end, item.kind))
