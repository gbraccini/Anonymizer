"""!
@file dictionary.py
@brief Riconoscimento di nomi, luoghi e strutture a partire da un vocabolario.

Il vocabolario predefinito è un sottoinsieme sintetico incluso nel pacchetto; nomi e
luoghi sono emessi solo in combinazioni o contesti espliciti.
"""

import json
import re
from dataclasses import dataclass
from importlib.resources import files

from anonymizer.model import Kind, Span, Validation


@dataclass(frozen=True)
class Vocabulary:
    """!
    @brief Elenchi di valori noti usati dal riconoscimento a dizionario.
    """

    ## Nomi propri.
    given_names: tuple[str, ...]
    ## Cognomi.
    surnames: tuple[str, ...]
    ## Comuni e località.
    locations: tuple[str, ...]
    ## Nomi di strutture sanitarie.
    facilities: tuple[str, ...]
    ## Cognomi che coincidono con parole comuni.
    ambiguous_surnames: tuple[str, ...] = ()
    ## Provenienza del vocabolario, riportata nell'origine degli intervalli.
    source: str = "user_supplied"


def load_vocabulary() -> Vocabulary:
    """!
    @brief Carica il vocabolario sintetico incluso nel pacchetto (data/subset.json).
    @return Vocabolario con provenienza synthetic_subset:CC0-1.0.
    """
    data = json.loads(files("anonymizer").joinpath("data/subset.json").read_text("utf-8"))
    return Vocabulary(
        **{
            key: tuple(data[key])
            for key in ("given_names", "surnames", "locations", "facilities", "ambiguous_surnames")
        },
        source="synthetic_subset:CC0-1.0",
    )


def _alternatives(values: tuple[str, ...]) -> str:
    """!
    @brief Costruisce un'alternanza regex non catturante dei valori.

    I valori sono ordinati dal più lungo al più corto, così prevale la forma più estesa.
    @param values Valori letterali da alternare.
    @return Pattern regex con i valori protetti da escape.
    """
    return (
        "(?:" + "|".join(re.escape(value) for value in sorted(values, key=len, reverse=True)) + ")"
    )


def detect_dictionary(
    text: str,
    page_id: str,
    vocabulary: Vocabulary | None = None,
) -> list[Span]:
    """!
    @brief Individua persone, medici, luoghi e strutture presenti nel vocabolario.

    Nomi e cognomi sono riconosciuti solo in coppia o dopo titoli e appellativi; i luoghi
    solo dopo espressioni come "nato a" o "residente a".
    @param text Testo della pagina.
    @param page_id Identificativo della pagina.
    @param vocabulary Vocabolario da usare; se None si carica quello predefinito.
    @return Intervalli ordinati per posizione.
    """
    vocabulary = vocabulary or load_vocabulary()
    spans = []

    def collect(pattern: str, kind: Kind, group: int = 0) -> None:
        """!
        @brief Aggiunge un intervallo per ogni corrispondenza del pattern.
        @param pattern Pattern regex, applicato senza distinzione di maiuscole.
        @param kind Tipo di entità da assegnare.
        @param group Gruppo della corrispondenza che delimita l'intervallo.
        """
        for match in re.finditer(pattern, text, re.IGNORECASE):
            spans.append(
                Span(
                    page_id,
                    match.start(group),
                    match.end(group),
                    kind,
                    2,
                    f"dictionary:{vocabulary.source}",
                    validation=Validation("unchecked", "dictionary_and_context"),
                )
            )

    if vocabulary.given_names and vocabulary.surnames:
        first, last = _alternatives(vocabulary.given_names), _alternatives(vocabulary.surnames)
        collect(rf"\b(?:{first}\s+{last}|{last}\s+{first})\b", Kind.PERSON)
        collect(
            rf"\b(?:dott(?:\.|or|ore|oressa)?|dr\.?)\s+({first}\s+{last}|{last}\s+{first})\b",
            Kind.DOCTOR,
            1,
        )
    if vocabulary.surnames:
        surname = _alternatives(vocabulary.surnames)
        collect(rf"\b(?:dott(?:\.|or|ore|oressa)?|dr\.?)\s+({surname})\b", Kind.DOCTOR, 1)
        collect(rf"\b(?:sig(?:\.|nor|nora)?|paziente)\s+({surname})\b", Kind.PERSON, 1)
    if vocabulary.locations:
        location = _alternatives(vocabulary.locations)
        collect(
            rf"\b(?:nat[oa]\s+a|residente\s+a|domicilio\s*:?|comune\s+di)\s+({location})\b",
            Kind.LOCATION,
            1,
        )
    if vocabulary.facilities:
        collect(rf"\b{_alternatives(vocabulary.facilities)}\b", Kind.FACILITY)
    return sorted(spans, key=lambda item: (item.start, item.end))
