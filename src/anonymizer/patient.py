"""!
@file patient.py
@brief Identità note fornite dall'utente e loro conversione in entità.

Permettono di collegare al soggetto corretto le occorrenze dei suoi dati nel testo e di
assegnargli valori canonici per la riassociazione.
"""

import re
from dataclasses import dataclass, field
from datetime import date

from anonymizer.model import Entity, Kind, opaque_id


@dataclass(frozen=True)
class KnownValue:
    """!
    @brief Valore noto di un'identità per una categoria di dato.
    """

    ## Categoria del dato.
    kind: Kind
    ## Valore così come può comparire nel testo; non vuoto.
    value: str
    ## Provenienza del valore.
    origin: str = "clinician"

    def __post_init__(self) -> None:
        """!
        @brief Rifiuta valori vuoti o composti solo da spazi.
        @throws ValueError Se il valore è vuoto.
        """
        if not self.value.strip():
            raise ValueError("Known value must not be empty")


@dataclass(frozen=True)
class KnownIdentity:
    """!
    @brief Identità nota, ad esempio il paziente, con i suoi valori per categoria.
    """

    ## Valori noti; per ogni categoria è ammesso un solo valore canonico, a meno di spazi e
    ## maiuscole.
    values: tuple[KnownValue, ...]
    ## Identificatore opaco, riusato come identificatore dell'entità.
    id: str = field(default_factory=opaque_id)
    ## Ruolo dell'identità (es. `patient`).
    role: str = "unknown"
    ## Se vero, l'identità è confermata.
    confirmed: bool = False
    ## Provenienza dell'identità.
    origin: str = "clinician"
    ## Data di nascita, se nota.
    birth_date: date | None = None
    ## Nome, se noto.
    given_name: str | None = None
    ## Cognome, se noto.
    surname: str | None = None

    def __post_init__(self) -> None:
        """!
        @brief Verifica che ogni categoria abbia un solo valore normalizzato.
        @throws ValueError Se una categoria ha valori diversi.
        """
        by_kind = {}
        for value in self.values:
            normalized = re.sub(r"\s+", " ", value.value.strip()).casefold()
            if value.kind in by_kind and by_kind[value.kind] != normalized:
                raise ValueError("An identity supports one canonical value per kind")
            by_kind[value.kind] = normalized

    def to_entity(self) -> Entity:
        """!
        @brief Converte l'identità in un'entità per la pseudonimizzazione.

        Per ogni categoria il valore canonico è il primo fornito; nome e cognome, se
        presenti, definiscono quello della persona e la data di nascita è espressa in
        formato ISO.
        @return Entità con valori canonici e varianti osservate.
        """
        canonical = dict((value.kind, value.value) for value in reversed(self.values))
        name = " ".join(part for part in (self.given_name, self.surname) if part)
        if name:
            canonical[Kind.PERSON] = name
        if self.birth_date:
            canonical[Kind.BIRTH_DATE] = self.birth_date.isoformat()
        return Entity(
            id=self.id,
            role=self.role,
            confirmed=self.confirmed,
            origin=self.origin,
            observed_variants=tuple(value.value for value in self.values),
            canonical_values=tuple(canonical.items()),
        )


def birth_date_values(value: date) -> tuple[KnownValue, ...]:
    """!
    @brief Genera le scritture comuni di una data di nascita da cercare nel testo.

    Include formati numerici con `/`, `-` e `.`, con e senza zeri iniziali, il formato
    ISO e quello con mese in lettere italiano.
    @param value Data di nascita.
    @return Valori noti di categoria data di nascita, uno per ogni scrittura.
    """
    from anonymizer.detect.regex import ITALIAN_MONTHS

    return tuple(
        KnownValue(Kind.BIRTH_DATE, representation)
        for representation in (
            value.strftime("%d/%m/%Y"),
            value.strftime("%d-%m-%Y"),
            value.strftime("%d.%m.%Y"),
            value.isoformat(),
            f"{value.day}/{value.month}/{value.year}",
            f"{value.day}-{value.month}-{value.year}",
            f"{value.day}.{value.month}.{value.year}",
            f"{value.day} {ITALIAN_MONTHS[value.month - 1]} {value.year}",
        )
    )
