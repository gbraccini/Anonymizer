"""!
@file clinical.py
@brief Pattern clinici italiani delimitati, con provenienza a monte per ogni regola.

Carica le regole dai file dati del pacchetto e le usa per proteggere i termini clinici
dal riconoscimento di entità e per trovare le etichette cliniche sensibili.
"""

import json
import re
from functools import cache
from importlib.resources import files

from anonymizer.model import Kind


@cache
def clinical_rules() -> dict:
    """!
    @brief Carica, una sola volta, le regole cliniche italiane del pacchetto.
    @return Contenuto di data/clinical_it_rules.json.
    """
    return json.loads(
        files("anonymizer").joinpath("data/clinical_it_rules.json").read_text("utf-8")
    )


@cache
def external_rules() -> dict:
    """!
    @brief Carica, una sola volta, le regole derivate da fonti esterne.
    @return Contenuto di data/external_rules.json.
    """
    return json.loads(files("anonymizer").joinpath("data/external_rules.json").read_text("utf-8"))


@cache
def _compiled_rules():
    """!
    @brief Compila in modalità multilinea i pattern delle regole cliniche italiane.
    @return Tuple di coppie (regola, pattern compilato), calcolate una sola volta.
    """
    return tuple(
        (rule, re.compile(rule["pattern"], re.MULTILINE)) for rule in clinical_rules()["rules"]
    )


@cache
def _external_clinical_rules():
    """!
    @brief Compila in modalità multilinea le regole cliniche delle fonti esterne.
    @return Tuple di coppie (regola, pattern compilato), calcolate una sola volta.
    """
    return tuple(
        (rule, re.compile(rule["pattern"], re.MULTILINE))
        for rule in external_rules()["clinical_rules"]
    )


def protected_clinical_spans(text: str) -> list[tuple[int, int, Kind]]:
    """!
    @brief Calcola gli intervalli clinici da proteggere dal riconoscimento di entità.

    Usa le regole con azione "safe", scartando le corrispondenze con più a capo del
    consentito, e tutte le regole cliniche esterne.
    @param text Testo della pagina.
    @return Terne (inizio, fine, Kind): ogni tipo di entità da non riconoscere
            nell'intervallo produce una terna.
    """
    protected = []
    for rule, pattern in _compiled_rules():
        if rule["action"] != "safe":
            continue
        for match in pattern.finditer(text):
            if len(re.findall(r"\r\n|\r|\n", match.group())) > rule["max_newlines"]:
                continue
            start, end = match.span(rule.get("value_group", 0))
            protected.extend((start, end, Kind(kind)) for kind in rule["ner_kinds"])
    for rule, pattern in _external_clinical_rules():
        for match in pattern.finditer(text):
            start, end = match.span(rule["value_group"])
            protected.extend((start, end, Kind(kind)) for kind in rule["ner_kinds"])
    return protected


def sensitive_label_matches(text: str, kind: Kind) -> list[tuple[str, int]]:
    """!
    @brief Trova le etichette cliniche sensibili che introducono un'entità del tipo dato.
    @param text Testo della pagina.
    @param kind Tipo di entità introdotto dall'etichetta.
    @return Coppie (id della regola, posizione di fine dell'etichetta) da cui inizia il
            valore.
    """
    return [
        (rule["id"], match.end())
        for rule, pattern in _compiled_rules()
        if rule["action"] == "sensitive" and rule["kind"] == kind
        for match in pattern.finditer(text)
    ]
