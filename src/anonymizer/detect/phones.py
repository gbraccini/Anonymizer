"""!
@file phones.py
@brief Riconoscimento offline e delimitato di numeri di contatto plausibili.

Gli intervalli restituiti conservano gli offset del testo sorgente; nessun numero
viene verificato in rete.
"""

import re

from anonymizer.model import Kind, Span, Validation

## Inizio di un numero: prefisso + facoltativo, parentesi facoltativa e cifre.
_SEED = re.compile(r"(?<![\w+])(?:\+[ \t]*)?\(?[0-9]+")
## Gruppo di cifre successivo, preceduto dai separatori ammessi.
_GROUP = re.compile(r"[ \t\u00a0\u202f()./\-\u2010-\u2015\u2212]{0,6}[0-9]+")
## Etichetta telefonica alla fine del testo che precede il numero.
_LABEL = re.compile(
    r"\b(?:tel(?:efono)?|cell(?:ulare)?|fax|recapito|mobile)\.?"
    r"(?:[ .]*(?:abitazione|ufficio|casa|cellulare|telefonico))?[ \t]*[:=]?[ \t]*$",
    re.I,
)
## Unità di misura dopo il numero: indica un valore clinico, non un telefono.
_UNIT = re.compile(r"[ \t]*(?:cellule|cell|mg|g|kg|ml|dl|mmol|mol|mmhg|bpm|ui|u/l|%)(?!\w)", re.I)


def _plausible(value: str, labeled: bool) -> bool:
    """!
    @brief Valuta se una sequenza ha una lunghezza plausibile per un numero di telefono.

    Gestisce i prefissi internazionali (+ o 00), i numeri fissi italiani (iniziali 0) e
    i mobili (iniziale 3); gli altri formati sono accettati solo se etichettati.
    @param value Testo candidato.
    @param labeled True se il numero è preceduto da un'etichetta telefonica.
    @return True se la sequenza è plausibile.
    """
    digits = re.sub(r"\D", "", value)
    if value.startswith("+") or digits.startswith("00"):
        international = digits if value.startswith("+") else digits[2:]
        if not international.startswith("39"):
            return 8 <= len(international) <= 15 and not international.startswith("0")
        digits = international[2:]
    if digits.startswith("0") and not digits.startswith("00"):
        return 6 <= len(digits) <= 11
    if digits.startswith("3"):
        return 9 <= len(digits) <= 10
    return labeled and 6 <= len(digits) <= 15


def detect_phones(text: str, page_id: str, excluded=()) -> list[Span]:
    """!
    @brief Individua numeri di telefono plausibili senza verifiche di rete.

    Per ogni inizio candidato sceglie l'estensione valida più lunga; numeri decimali,
    unità di misura e intervalli esclusi non vengono mai coperti.
    @param text Testo della pagina.
    @param page_id Identificativo della pagina.
    @param excluded Intervalli (inizio, fine) che i numeri non devono sovrapporre.
    @return Intervalli di tipo PHONE.
    """
    excluded = [*excluded, *(m.span() for m in re.finditer(r"(?<!\w)[0-9][.,][0-9]+(?!\w)", text))]
    spans, consumed = [], 0
    for seed in _SEED.finditer(text):
        start = seed.start()
        if start < consumed or any(a <= start < b for a, b in excluded):
            continue
        labeled = bool(_LABEL.search(text[max(0, start - 60) : start]))
        ends, cursor = [seed.end()], seed.end()
        while cursor - start < 80 and (group := _GROUP.match(text, cursor)):
            ends.append(group.end())
            cursor = group.end()
        for end in reversed(ends):
            value = text[start:end]
            if end < len(text) and (text[end].isalnum() or text[end] in "_@"):
                continue
            if any(start < b and a < end for a, b in excluded):
                continue
            if not _plausible(value, labeled) or (not labeled and _UNIT.match(text, end)):
                continue
            spans.append(
                Span(
                    page_id,
                    start,
                    end,
                    Kind.PHONE,
                    1,
                    "regex:phone",
                    validation=Validation("unchecked", "plausible_contact_number_no_network_check"),
                )
            )
            consumed = end
            break
    return spans
