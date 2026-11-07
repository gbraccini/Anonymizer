"""!
@file known.py
@brief Rilevamento di livello 0 dei valori noti delle identità dichiarate.

Cerca nel testo nomi, date di nascita e altri valori forniti, normalizzando Unicode e
punteggiatura e tollerando le confusioni OCR più comuni.
"""

import re
import unicodedata

from anonymizer.model import Kind, Span, Validation
from anonymizer.patient import KnownIdentity, KnownValue, birth_date_values

## Cifre che l'OCR confonde con lettere.
_OCR = str.maketrans({"0": "o", "1": "i", "5": "s"})
## Varianti tipografiche di apostrofi e trattini ricondotte alla forma ASCII.
_PUNCTUATION = str.maketrans(
    {char: "'" for char in "’ʼ‘＇"} | {char: "-" for char in "‐‑‒–—−﹘﹣－"}
)
## Tipi i cui valori si confrontano sul testo normalizzato.
_NORMALIZED_KINDS = {Kind.PERSON, Kind.DOCTOR, Kind.ADDRESS, Kind.LOCATION, Kind.FACILITY}


def normalized_context(text: str) -> tuple[str, list[tuple[int, int]]]:
    """!
    @brief Normalizza il testo per il confronto senza perdere punteggiatura né offset originali.

    Applica NFC a ogni carattere con i suoi combinanti, uniforma apostrofi e trattini, applica il
    casefold e comprime gli spazi consecutivi in uno solo.
    @param text Testo originale.
    @return Coppia (testo normalizzato, intervallo originale (inizio, fine) di ogni carattere).
    """
    values, offsets = [], []
    cursor = 0
    while cursor < len(text):
        end = cursor + 1
        while end < len(text) and unicodedata.combining(text[end]):
            end += 1
        value = unicodedata.normalize("NFC", text[cursor:end]).translate(_PUNCTUATION).casefold()
        if value.isspace():
            if values and values[-1] == " ":
                offsets[-1] = (offsets[-1][0], end)
            else:
                values.append(" ")
                offsets.append((cursor, end))
        else:
            values.extend(value)
            offsets.extend([(cursor, end)] * len(value))
        cursor = end
    return "".join(values), offsets


def _ocr_pattern(value: str) -> str:
    """!
    @brief Costruisce una regex che tollera le confusioni OCR o/0, i/l/1, s/5 e spazi multipli.
    @param value Valore da cercare.
    @return Espressione regolare.
    """
    groups = {"o": "[o0]", "i": "[il1]", "l": "[li1]", "s": "[s5]"}
    return "".join(
        r"\s+" if char.isspace() else groups.get(char.translate(_OCR), re.escape(char))
        for char in value.casefold()
    )


def detect_known(text: str, page_id: str, identities: tuple[KnownIdentity, ...]) -> list[Span]:
    """!
    @brief Rileva le occorrenze dei valori noti delle identità.

    Oltre ai valori dichiarati cerca nome e cognome in entrambi gli ordini, il cognome da solo
    se lungo almeno 5 caratteri o se manca il nome, e le varianti della data di nascita. Per i
    valori di almeno 5 caratteri con lettere usa il pattern tollerante all'OCR.
    @param text Testo della pagina.
    @param page_id Identificativo della pagina.
    @param identities Identità note.
    @return Span di livello 0 ordinati, "confirmed" o "proposed" secondo l'identità.
    """
    if not identities:
        return []
    spans = []
    normalized, offsets = None, None
    for identity in identities:
        values = identity.values
        if identity.given_name and identity.surname:
            values += (
                KnownValue(Kind.PERSON, f"{identity.given_name} {identity.surname}"),
                KnownValue(Kind.PERSON, f"{identity.surname} {identity.given_name}"),
            )
            if len(identity.surname) >= 5:
                values += (KnownValue(Kind.PERSON, identity.surname),)
        elif identity.surname:
            values += (KnownValue(Kind.PERSON, identity.surname),)
        elif identity.given_name:
            values += (KnownValue(Kind.PERSON, identity.given_name),)
        if identity.birth_date:
            values += birth_date_values(identity.birth_date)
        seen = set()
        for value in values:
            use_normalized = value.kind in _NORMALIZED_KINDS
            if use_normalized and normalized is None:
                normalized, offsets = normalized_context(text)
            needle = normalized_context(value.value)[0] if use_normalized else value.value
            haystack = normalized if use_normalized else text
            pattern = re.escape(needle).replace(r"\ ", r"\s+")
            if len(value.value) >= 5 and any(char.isalpha() for char in value.value):
                pattern = _ocr_pattern(needle)
            for match in re.finditer(
                rf"(?<![\w\u0300-\u036f]){pattern}(?![\w\u0300-\u036f])", haystack, re.IGNORECASE
            ):
                start = offsets[match.start()][0] if use_normalized else match.start()
                end = offsets[match.end() - 1][1] if use_normalized else match.end()
                key = (start, end, value.kind)
                if key in seen:
                    continue
                seen.add(key)
                exact = text[start:end].casefold() == value.value.casefold()
                normalized_match = match.group().casefold() == needle.casefold()
                spans.append(
                    Span(
                        page_id,
                        start,
                        end,
                        value.kind,
                        0,
                        f"known:{value.origin}",
                        entity_id=identity.id,
                        validation=Validation(
                            "confirmed" if identity.confirmed else "proposed",
                            "exact_known_value"
                            if exact
                            else "normalized_known_value"
                            if normalized_match and use_normalized
                            else "explicit_ocr_variant",
                        ),
                    )
                )
    return sorted(spans, key=lambda item: (item.start, item.end))
