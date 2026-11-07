"""!
@file reassoc.py
@brief Reinserimento dei valori originali al posto dei token di un testo pseudonimizzato.

Usa la mappa di trasformazione per riassociare i token a valori canonici, ad esempio
su un testo elaborato a valle che contiene ancora i segnaposto.
"""

import re
from dataclasses import dataclass

from anonymizer.model import TransformationMap
from anonymizer.pseudo import TOKEN_PATTERN


@dataclass(frozen=True)
class ReassociationResult:
    """!
    @brief Esito della riassociazione di un testo.
    """

    ## Testo con i token noti sostituiti dai valori canonici.
    text: str
    ## Token non presenti nella mappa, senza duplicati e in ordine di prima comparsa; restano
    ## invariati nel testo.
    unknown_tokens: tuple[str, ...]


def reassociate(text: str, mapping: TransformationMap) -> ReassociationResult:
    """!
    @brief Sostituisce ogni token della mappa con il suo valore canonico.
    @param text Testo contenente token nel formato `[[ETICHETTA]]`.
    @param mapping Mappa di trasformazione che associa i token ai valori canonici.
    @return Testo ripristinato ed elenco dei token sconosciuti lasciati invariati.
    """
    values = {entry.token: entry.canonical_value for entry in mapping.entries}
    unknown = []

    def restore(match: re.Match[str]) -> str:
        """!
        @brief Restituisce il valore canonico del token o lo lascia invariato se sconosciuto.
        @param match Occorrenza del token trovata nel testo.
        @return Valore canonico oppure il token originale.
        """
        token = match.group()
        if token in values:
            return values[token]
        unknown.append(token)
        return token

    restored = re.sub(TOKEN_PATTERN, restore, text)
    return ReassociationResult(restored, tuple(dict.fromkeys(unknown)))
