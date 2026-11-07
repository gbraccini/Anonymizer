"""!
@file mapstore.py
@brief Serializzazione JSON rigorosa della mappa di trasformazione.

La lettura rifiuta campi mancanti o in eccesso, tipi errati e riferimenti incoerenti
tra entità, sostituzioni e voci, così che una mappa caricata sia sempre utilizzabile
per la riassociazione.
"""

import json
import re
from dataclasses import asdict

from anonymizer.model import (
    SCHEMA_VERSION,
    Entity,
    Kind,
    MapEntry,
    Replacement,
    TransformationMap,
)
from anonymizer.pseudo import TOKEN_PATTERN


def dumps(mapping: TransformationMap) -> str:
    """!
    @brief Serializza la mappa in JSON compatto.

    Il risultato viene riletto prima di essere restituito, per non produrre mai una
    mappa che non si potrebbe caricare.
    @param mapping Mappa da serializzare.
    @return Testo JSON della mappa.
    @throws ValueError Se la mappa non supera la validazione di lettura.
    """
    raw = json.dumps(asdict(mapping), ensure_ascii=False, separators=(",", ":"))
    loads(raw)
    return raw


def _object(value: object, fields: set[str]) -> dict:
    """!
    @brief Verifica che il valore sia un oggetto JSON con esattamente i campi attesi.
    @param value Valore decodificato.
    @param fields Insieme dei nomi di campo richiesti.
    @return Il dizionario stesso.
    @throws ValueError Se il valore non è un oggetto o i campi non coincidono.
    """
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("Invalid map object fields")
    return value


def _string(value: object, *, empty: bool = False) -> str:
    """!
    @brief Verifica che il valore sia una stringa, non vuota salvo diversa indicazione.
    @param value Valore decodificato.
    @param empty Se vero, accetta anche la stringa vuota.
    @return La stringa stessa.
    @throws ValueError Se il valore non è una stringa valida.
    """
    if not isinstance(value, str) or (not value and not empty):
        raise ValueError("Invalid map string")
    return value


def _strings(value: object, *, empty: bool = False) -> tuple[str, ...]:
    """!
    @brief Verifica che il valore sia una lista di stringhe valide.
    @param value Valore decodificato.
    @param empty Se vero, accetta anche stringhe vuote come elementi.
    @return Le stringhe come tupla.
    @throws ValueError Se il valore non è una lista o un elemento non è valido.
    """
    if not isinstance(value, list):
        raise ValueError("Invalid map string list")
    return tuple(_string(item, empty=empty) for item in value)


def _optional_id(value: object) -> str | None:
    """!
    @brief Verifica un identificatore facoltativo.
    @param value Valore decodificato.
    @return None se il valore è nullo, altrimenti la stringa non vuota.
    @throws ValueError Se il valore non è nullo né una stringa non vuota.
    """
    return None if value is None else _string(value)


def _unique(values: list[str]) -> None:
    """!
    @brief Verifica che non ci siano identificatori ripetuti.
    @param values Identificatori da controllare.
    @throws ValueError Se un identificatore compare più volte.
    """
    if len(values) != len(set(values)):
        raise ValueError("Duplicate map identifier")


def loads(raw: str) -> TransformationMap:
    """!
    @brief Carica e valida una mappa di trasformazione da JSON.
    @param raw Testo JSON prodotto da dumps().
    @return Mappa di trasformazione ricostruita.
    @throws ValueError Con messaggio generico se il JSON o la mappa non sono validi;
        l'eccezione originale non viene concatenata.
    """
    try:
        return _decode(json.loads(raw))
    except (TypeError, KeyError, ValueError):
        raise ValueError("Invalid transformation map") from None


def _decode(value: object) -> TransformationMap:
    """!
    @brief Ricostruisce la mappa dal JSON decodificato verificandone la coerenza.

    Controlla versione dello schema, campi di ogni oggetto, offset e lunghezze delle
    sostituzioni, formato dei token, riferimenti alle entità e corrispondenza biunivoca
    tra voci e sostituzioni reversibili.
    @param value Radice del documento JSON decodificato.
    @return Mappa di trasformazione validata.
    @throws ValueError Se una qualsiasi verifica fallisce.
    """
    root = _object(
        value,
        {
            "schema_version",
            "document_id",
            "session_id",
            "entities",
            "entries",
            "replacements",
        },
    )
    if type(root["schema_version"]) is not int or root["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Unsupported map version")
    for key in ("entities", "entries", "replacements"):
        if not isinstance(root[key], list):
            raise ValueError("Invalid map collection")
    entities = []
    for data in root["entities"]:
        item = _object(
            data,
            {
                "id",
                "role",
                "confirmed",
                "canonical_value",
                "observed_variants",
                "placeholders",
                "origin",
                "canonical_values",
            },
        )
        if type(item["confirmed"]) is not bool or not isinstance(item["canonical_values"], list):
            raise ValueError("Invalid entity confirmation or values")
        canonical = []
        for pair in item["canonical_values"]:
            if not isinstance(pair, list) or len(pair) != 2:
                raise ValueError("Invalid canonical value")
            canonical.append((Kind(pair[0]), _string(pair[1])))
        entities.append(
            Entity(
                id=_string(item["id"]),
                role=_string(item["role"]),
                confirmed=item["confirmed"],
                canonical_value=_optional_id(item["canonical_value"]),
                observed_variants=_strings(item["observed_variants"]),
                placeholders=_strings(item["placeholders"]),
                origin=_string(item["origin"]),
                canonical_values=tuple(canonical),
            )
        )
    _unique([entity.id for entity in entities])
    entity_ids = {entity.id for entity in entities}
    replacements = []
    for data in root["replacements"]:
        item = _object(
            data,
            {
                "id",
                "page_id",
                "start",
                "end",
                "original",
                "replacement",
                "result_start",
                "result_end",
                "entity_id",
                "span_id",
                "reversible_token",
            },
        )
        for key in ("start", "end", "result_start", "result_end"):
            if type(item[key]) is not int or item[key] < 0:
                raise ValueError("Invalid replacement offset")
        if type(item["reversible_token"]) is not bool:
            raise ValueError("Invalid reversible flag")
        operation = Replacement(
            _string(item["id"]),
            _string(item["page_id"]),
            item["start"],
            item["end"],
            _string(item["original"]),
            _string(item["replacement"]),
            item["result_start"],
            item["result_end"],
            _optional_id(item["entity_id"]),
            _string(item["span_id"]),
            item["reversible_token"],
        )
        if operation.end - operation.start != len(operation.original):
            raise ValueError("Invalid original interval length")
        if operation.result_end - operation.result_start != len(operation.replacement):
            raise ValueError("Invalid result interval length")
        if operation.entity_id is not None and operation.entity_id not in entity_ids:
            raise ValueError("Unknown replacement entity")
        if (
            operation.reversible_token
            and re.fullmatch(TOKEN_PATTERN, operation.replacement) is None
        ):
            raise ValueError("Invalid replacement token")
        replacements.append(operation)
    _unique([operation.id for operation in replacements])
    by_id = {operation.id: operation for operation in replacements}
    entries = []
    referenced = []
    for data in root["entries"]:
        item = _object(
            data,
            {
                "token",
                "canonical_value",
                "entity_id",
                "replacement_ids",
                "observed_values",
            },
        )
        entry = MapEntry(
            _string(item["token"]),
            _string(item["canonical_value"]),
            _optional_id(item["entity_id"]),
            _strings(item["replacement_ids"]),
            _strings(item["observed_values"]),
        )
        if re.fullmatch(TOKEN_PATTERN, entry.token) is None or not entry.replacement_ids:
            raise ValueError("Invalid token entry")
        if len(entry.replacement_ids) != len(entry.observed_values):
            raise ValueError("Missing observed occurrence")
        if entry.entity_id is not None and entry.entity_id not in entity_ids:
            raise ValueError("Unknown entry entity")
        for operation_id, observed in zip(
            entry.replacement_ids, entry.observed_values, strict=True
        ):
            operation = by_id.get(operation_id)
            if (
                operation is None
                or not operation.reversible_token
                or (
                    operation.replacement != entry.token
                    or operation.original != observed
                    or operation.entity_id != entry.entity_id
                )
            ):
                raise ValueError("Inconsistent token occurrence")
            referenced.append(operation_id)
        entries.append(entry)
    _unique([entry.token for entry in entries])
    _unique(referenced)
    if set(referenced) != {
        operation.id for operation in replacements if operation.reversible_token
    }:
        raise ValueError("Missing map entry")
    return TransformationMap(
        _string(root["document_id"]),
        _string(root["session_id"]),
        tuple(entities),
        tuple(entries),
        tuple(replacements),
    )
