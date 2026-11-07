"""!
@file cf.py
@brief Verifica e decodifica del codice fiscale italiano.

Gestisce struttura, omocodia, carattere di controllo e correzione degli scambi tipici
dell'OCR tra lettere e cifre.
"""

import calendar
import re
from dataclasses import dataclass

## Struttura del codice fiscale, comprese le lettere sostitutive dell'omocodia.
_PATTERN = re.compile(
    r"[A-Z]{6}[0-9LMNPQRSTUV]{2}[ABCDEHLMPRST][0-9LMNPQRSTUV]{2}[A-Z][0-9LMNPQRSTUV]{3}[A-Z]"
)
## Lettera del mese di nascita verso il numero del mese.
_MONTHS = {letter: month for month, letter in enumerate("ABCDEHLMPRST", 1)}
## Traduzione delle lettere di omocodia nelle cifre originali.
_OMOCODIA = str.maketrans("LMNPQRSTUV", "0123456789")
## Valori dei caratteri in posizione dispari per il calcolo del carattere di controllo.
_ODD = dict(
    zip(
        "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        (
            1,
            0,
            5,
            7,
            9,
            13,
            15,
            17,
            19,
            21,
            1,
            0,
            5,
            7,
            9,
            13,
            15,
            17,
            19,
            21,
            2,
            4,
            18,
            20,
            11,
            3,
            6,
            8,
            12,
            14,
            16,
            10,
            22,
            25,
            24,
            23,
        ),
        strict=True,
    )
)


@dataclass(frozen=True)
class DecodedCF:
    """!
    @brief Dati anagrafici ricavati da un codice fiscale.
    """

    ## Ultime due cifre dell'anno di nascita.
    year_two_digits: int
    ## Mese di nascita (1-12).
    month: int
    ## Giorno di nascita.
    day: int
    ## Sesso: `M` oppure `F`.
    sex: str
    ## Codice catastale del luogo di nascita, senza omocodia.
    birthplace_code: str
    ## Vero se il carattere di controllo è corretto.
    checksum_valid: bool
    ## Sempre None: il codice fiscale non indica il secolo di nascita.
    century: None = None


def normalize_cf(value: str) -> str:
    """!
    @brief Rimuove gli spazi e converte in maiuscolo.
    @param value Codice fiscale come trovato nel testo.
    @return Codice normalizzato.
    """
    return re.sub(r"\s+", "", value).upper()


def is_plausible_cf(value: str) -> bool:
    """!
    @brief Indica se il valore ha la struttura di un codice fiscale.

    Non verifica la data né il carattere di controllo.
    @param value Valore da controllare.
    @return Vero se la struttura è compatibile.
    """
    return _PATTERN.fullmatch(normalize_cf(value)) is not None


def checksum(prefix: str) -> str:
    """!
    @brief Calcola il carattere di controllo del codice fiscale.
    @param prefix Primi quindici caratteri del codice.
    @return Lettera di controllo attesa.
    @throws ValueError Se il prefisso non è composto da quindici caratteri ASCII
        alfanumerici.
    """
    prefix = prefix.upper()
    if len(prefix) != 15 or not prefix.isascii() or not prefix.isalnum():
        raise ValueError("CF checksum requires fifteen ASCII alphanumeric characters")
    total = sum(
        _ODD[char] if index % 2 == 0 else int(char) if char.isdigit() else ord(char) - 65
        for index, char in enumerate(prefix)
    )
    return chr(65 + total % 26)


def decode_cf(value: str) -> DecodedCF:
    """!
    @brief Decodifica data di nascita, sesso e luogo da un codice fiscale.

    Il 29 febbraio è ammesso negli anni a due cifre divisibili per quattro, dato che il
    secolo non è determinabile. Un carattere di controllo errato non è un errore ma è
    segnalato nel risultato.
    @param value Codice fiscale, anche con spazi o in minuscolo.
    @return Dati decodificati.
    @throws ValueError Se la struttura non è valida o la data di nascita è impossibile.
    """
    value = normalize_cf(value)
    if not is_plausible_cf(value):
        raise ValueError("Invalid CF structure")
    year = int(value[6:8].translate(_OMOCODIA))
    month = _MONTHS[value[8]]
    encoded_day = int(value[9:11].translate(_OMOCODIA))
    sex = "F" if encoded_day > 40 else "M"
    day = encoded_day - 40 if sex == "F" else encoded_day
    # A two-digit year cannot establish a century, including for leap-year validation.
    max_day = 29 if month == 2 and year % 4 == 0 else calendar.monthrange(2001, month)[1]
    if not 1 <= day <= max_day:
        raise ValueError("Impossible CF birth date")
    return DecodedCF(
        year,
        month,
        day,
        sex,
        value[11] + value[12:15].translate(_OMOCODIA),
        checksum(value[:15]) == value[15],
    )


def is_valid_cf(value: str) -> bool:
    """!
    @brief Indica se il codice fiscale è valido in struttura, data e carattere di controllo.
    @param value Codice fiscale da verificare.
    @return Vero se tutte le verifiche sono superate.
    """
    value = normalize_cf(value)
    try:
        decode_cf(value)
    except ValueError:
        return False
    return checksum(value[:15]) == value[15]


def cf_variants(value: str) -> tuple[str, ...]:
    """!
    @brief Produce le letture plausibili di un codice fiscale con possibili errori OCR.

    Corregge gli scambi `O/0`, `I/1`, `Z/2`, `S/5`, `B/8` in base alla posizione:
    lettere dove sono attese cifre e viceversa.
    @param value Codice fiscale letto, anche con spazi o in minuscolo.
    @return Valore normalizzato ed eventuale correzione, senza duplicati e solo se
        strutturalmente plausibili; vuota se la lunghezza non è sedici.
    """
    value = normalize_cf(value)
    if len(value) != 16:
        return ()
    corrected = list(value)
    for index in (6, 7, 9, 10, 12, 13, 14):
        if corrected[index] in "OIZSB":
            corrected[index] = corrected[index].translate(str.maketrans("OIZSB", "01258"))
    for index in (0, 1, 2, 3, 4, 5, 8, 11, 15):
        if corrected[index] in "01258":
            corrected[index] = corrected[index].translate(str.maketrans("01258", "OIZSB"))
    return tuple(
        dict.fromkeys(item for item in (value, "".join(corrected)) if is_plausible_cf(item))
    )
