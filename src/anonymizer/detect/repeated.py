"""!
@file repeated.py
@brief Propaga i nomi completi affidabili alle altre pagine dello stesso documento.

I nomi rilevati con un'etichetta esplicita (livello 1) o dal NER con confidenza almeno 0.9
vengono cercati in tutte le pagine dello stesso documento sorgente.
"""

import re

from anonymizer.detect.clinical import clinical_rules, protected_clinical_spans
from anonymizer.detect.context import _PARTICLES, _PATIENT_STOPS, _TOKEN, _is_name_part
from anonymizer.detect.known import normalized_context
from anonymizer.model import Kind, Span, Validation

## Origini dei rilevamenti espliciti ammessi come nomi da propagare.
_ORIGINS = {"context:doctor", "context:patient_name", "layout:doctor_name", "layout:patient_name"}
## Motivazioni di validazione esplicite ammesse come nomi da propagare.
_REASONS = {"explicit_doctor_title", "explicit_patient_name_label", "explicit_spatial_label"} | {
    "clinical_it_label:" + rule["id"]
    for rule in clinical_rules()["rules"]
    if rule["action"] == "sensitive"
}


def detect_person_repetitions(pages, seeds) -> list[Span]:
    """!
    @brief Rileva le ripetizioni dei nomi completi affidabili nel documento.

    Un nome è ammesso se ha da 2 a 6 token, senza punti, con almeno due parti che non sono
    particelle e al più un a capo. Per i nomi del NER si escludono i valori dopo "nome:" o
    "cognome:" e i frammenti di campi separati. Per i nomi di due parti si cerca anche l'ordine
    inverso. Le ripetizioni di livello 3 non duplicano rilevamenti esistenti né intervalli
    clinici protetti.
    @param pages Pagine dell'elaborazione.
    @param seeds Span già rilevati.
    @return Span delle ripetizioni.
    """
    by_id = {page.page_id: page for page in pages}
    detected = {(s.page_id, s.start, s.end, s.kind) for s in seeds}
    names = {}
    for seed in seeds:
        explicit = (
            seed.origin in _ORIGINS and seed.level == 1 and seed.validation.reason in _REASONS
        )
        model = (
            seed.origin == "ner:gliner"
            and seed.level == 3
            and seed.confidence is not None
            and seed.confidence >= 0.9
        )
        if not (explicit or model) or seed.entity_id is not None:
            continue
        if seed.kind not in (Kind.PERSON, Kind.DOCTOR) or seed.page_id not in by_id:
            continue
        page = by_id[seed.page_id]
        if not 0 <= seed.start < seed.end <= len(page.text):
            continue
        if model and (
            re.search(r"(?i)\b(?:nome|cognome)\s*[:=]\s*$", page.text[: seed.start])
            or any(
                other.page_id == seed.page_id
                and other.start <= seed.start < seed.end <= other.end
                and (
                    other.origin.endswith(":patient_field")
                    or other.validation.reason == "explicit_spatial_label_fragment"
                )
                for other in seeds
            )
        ):
            continue
        value = page.text[seed.start : seed.end]
        tokens = list(_TOKEN.finditer(value))
        if (
            not 2 <= len(tokens) <= 6
            or "." in value
            or tokens[0].start() != 0
            or tokens[-1].end() != len(value)
            or any(
                not value[a.end() : b.start()].isspace()
                for a, b in zip(tokens, tokens[1:], strict=False)
            )
            or not all(
                _is_name_part(t.group()) or t.group().casefold() in _PARTICLES for t in tokens
            )
            or any(t.group().casefold() in _PATIENT_STOPS for t in tokens)
            or sum(t.group().casefold() not in _PARTICLES for t in tokens) < 2
            or not re.fullmatch(
                r"[^\W\d_][\w\u0300-\u036f'\u2019\u02bc\u2010-\u2015\u2212\-\s]*", value
            )
            or len(re.findall(r"\r\n|\r|\n", value)) > 1
        ):
            continue
        name = normalized_context(value)[0]
        variants = {name}
        if len(tokens) == 2 and all(t.group().casefold() not in _PARTICLES for t in tokens):
            variants.add(" ".join(reversed(name.split())))
        for variant in variants:
            names.setdefault(page.source_id, {}).setdefault(variant, []).append(seed)
    if not names:
        return []
    patterns = {
        source: [
            (
                re.compile(r"(?<![\w\u0300-\u036f])" + re.escape(name) + r"(?![\w\u0300-\u036f])"),
                evidence,
            )
            for name, evidence in sorted(values.items())
        ]
        for source, values in names.items()
    }
    spans = []
    for page in pages:
        if page.source_id not in patterns:
            continue
        text, offsets = normalized_context(page.text)
        protected = protected_clinical_spans(page.text)
        for pattern, evidence in patterns[page.source_id]:
            kinds = {seed.kind for seed in evidence}
            kind = next(iter(kinds)) if len(kinds) == 1 else Kind.PERSON
            level = min(seed.level for seed in evidence)
            confidence = max((seed.confidence or 0 for seed in evidence), default=0)
            for match in pattern.finditer(text):
                start, end = offsets[match.start()][0], offsets[match.end() - 1][1]
                if len(re.findall(r"\r\n|\r|\n", page.text[start:end])) > 1:
                    continue
                if level == 3 and (page.page_id, start, end, kind) in detected:
                    continue
                if level == 3 and any(k == kind and a <= start < end <= b for a, b, k in protected):
                    continue
                spans.append(
                    Span(
                        page.page_id,
                        start,
                        end,
                        kind,
                        level,
                        "context:person_repeat" if level == 1 else "ner:person_repeat",
                        confidence=confidence if level == 3 else None,
                        validation=Validation(
                            "unchecked",
                            "exact_explicit_fullname"
                            if level == 1
                            else "high_confidence_name_repeat",
                        ),
                    )
                )
    return spans
