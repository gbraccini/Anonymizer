"""!
@file structured.py
@brief Adattatori offline per i pattern Presidio fissati in data/presidio_rules.json.

Rileva email, IBAN e URL di contatto senza accesso alla rete.
"""

import json
import re
from functools import cache
from importlib.resources import files
from urllib.parse import urlsplit

from anonymizer.model import Kind, Span, Validation


@cache
def rules():
    """!
    @brief Carica una sola volta le regole Presidio incluse nel pacchetto.
    @return Dizionario delle regole.
    """
    return json.loads(files("anonymizer").joinpath("data/presidio_rules.json").read_text("utf-8"))


@cache
def _patterns():
    """!
    @brief Compila i pattern di email, IBAN, IBAN per paese e URL.
    @return Tupla (email, iban, pattern per codice paese, url).
    """
    data = rules()
    # Full candidate matches remove the upstream word boundaries, which omit leading + or !.
    email = re.compile(data["email_pattern"].removeprefix(r"\b").removesuffix(r"\b"))
    iban = re.compile(data["iban_pattern"].replace("[ -]?", "[ \\t-]?"), re.I | re.ASCII)
    countries = {
        code: re.compile(pattern, re.ASCII)
        for code, pattern in data["iban_country_patterns"].items()
    }
    url = re.compile(data["url_base_pattern"], re.I)
    return email, iban, countries, url


def detect_emails(text: str, page_id: str) -> list[Span]:
    """!
    @brief Rileva indirizzi email tollerando gli spazi OCR attorno alla chiocciola.

    Rimuove fino a 4 spazi orizzontali prima o dopo "@", rileva sul testo compattato e riporta
    gli span agli offset originali.
    @param text Testo della pagina.
    @param page_id Identificativo della pagina.
    @return Span di email.
    """
    # OCR often separates @ from its neighbours; retain a map to the original glyphs.
    removed = set()
    for gap in re.finditer(r"[^\S\r\n]{1,4}(?=@)|(?<=@)[^\S\r\n]{1,4}", text):
        removed.update(range(gap.start(), gap.end()))
    offsets = [i for i in range(len(text)) if i not in removed]
    normalized = "".join(text[i] for i in offsets)
    return [
        Span(
            page_id,
            offsets[s.start],
            offsets[s.end - 1] + 1,
            s.kind,
            s.level,
            s.origin,
            validation=s.validation,
        )
        for s in _detect_compact_emails(normalized, page_id)
    ]


def _detect_compact_emails(text: str, page_id: str) -> list[Span]:
    """!
    @brief Rileva email espandendo il candidato attorno a ogni "@".

    Valida il candidato con il pattern Presidio e con i limiti di lunghezza di parte locale,
    indirizzo ed etichette di dominio. Il dominio non viene verificato via DNS.
    @param text Testo senza spazi attorno alle chiocciole.
    @param page_id Identificativo della pagina.
    @return Span di livello 1.
    """
    pattern = _patterns()[0]
    spans = []
    local_symbols = "!#$%&'*+-/=?^_`{|}~."
    for at in re.finditer("@", text):
        start, end = at.start(), at.end()
        while start and at.start() - start <= 64:
            char = text[start - 1]
            if not (char.isalnum() or char == "_" or char in local_symbols):
                break
            start -= 1
        while end < len(text) and end - at.end() <= 253:
            char = text[end]
            if not (char.isalnum() or char in "_.-"):
                break
            end += 1
        candidate = text[start:end].rstrip(".")
        if len(candidate) > 254 or not pattern.fullmatch(candidate):
            continue
        local, domain = candidate.rsplit("@", 1)
        if len(local) > 64 or local.startswith(".") or ".." in local:
            continue
        labels = domain.split(".")
        if any(len(label) > 63 or "_" in label for label in labels):
            continue
        if start and text[start - 1] == "@":
            continue
        spans.append(
            Span(
                page_id,
                start,
                start + len(candidate),
                Kind.EMAIL,
                1,
                "structured:presidio_email",
                validation=Validation("unchecked", "presidio_pattern_syntactic_domain_no_dns"),
            )
        )
    return spans


def iban_valid(value: str) -> bool:
    """!
    @brief Verifica il formato per paese e il checksum MOD97 di un IBAN.
    @param value IBAN, anche con spazi, tabulazioni o trattini.
    @return True se l'IBAN è valido.
    """
    value = re.sub(r"[ \t-]", "", value).upper()
    countries = _patterns()[2]
    country = countries.get(value[:2])
    if country is None or not country.fullmatch(value):
        return False
    # Streaming MOD97 avoids building an unbounded integer and follows Presidio's ISO check.
    remainder = 0
    for char in value[4:] + value[:4]:
        for digit in str(ord(char) - 55) if char.isalpha() else char:
            remainder = (remainder * 10 + int(digit)) % 97
    return remainder == 1


def detect_ibans(text: str, page_id: str) -> list[Span]:
    """!
    @brief Rileva IBAN, anche spezzati da spazi o trattini.

    Per ogni candidato sceglie la fine più corta, di almeno 15 caratteri, conforme al formato del
    paese. Un IBAN con checksum errato resta mascherato se italiano o preceduto dall'etichetta
    "IBAN", marcato come non valido.
    @param text Testo della pagina.
    @param page_id Identificativo della pagina.
    @return Span di livello 1.
    """
    _, pattern, countries, _ = _patterns()
    spans = []
    for seed in re.finditer(r"(?<!\w)[A-Za-z]{2}[0-9]{2}", text):
        match = pattern.match(text, seed.start())
        if match is None:
            continue
        start = match.start()
        if start and (text[start - 1].isalnum() or text[start - 1] == "_"):
            continue
        country = countries.get(text[start : start + 2].upper())
        if country is None:
            continue
        for end in range(start + 15, match.end() + 1):
            if text[end - 1] in " \t-":
                continue
            if end < len(text) and (text[end].isalnum() or text[end] == "_"):
                continue
            value = re.sub(r"[ \t-]", "", text[start:end]).upper()
            if not country.fullmatch(value):
                continue
            valid = iban_valid(value)
            labeled = re.search(r"\bIBAN[ \t]*[:=]?[ \t]*$", text[max(0, start - 24) : start], re.I)
            if valid or value.startswith("IT") or labeled:
                spans.append(
                    Span(
                        page_id,
                        start,
                        end,
                        Kind.IBAN,
                        1,
                        "structured:presidio_iban",
                        validation=Validation(
                            "valid" if valid else "invalid",
                            "country_format_and_mod97"
                            if valid
                            else "plausible_identifier_masked_despite_validation",
                        ),
                    )
                )
            break
    return spans


def contact_urls(text: str) -> list[tuple[int, int]]:
    """!
    @brief Restituisce gli offset degli URL; il chiamante deve stabilire il contesto di blocco
           struttura/contatti.

    Accetta URL che iniziano con http(s):// o www. con host sintatticamente valido e porta
    ammessa. Scarta gli host con un TLD noto a Presidio che il pattern non riconosce per intero.
    @param text Testo da analizzare.
    @return Lista di (inizio, fine), esclusa la punteggiatura finale.
    """
    spans = []
    for match in re.finditer(r"(?<![\w@.+-])(?:https?://|www\.)[^\s<>()\"']{1,2048}", text, re.I):
        value = match.group().rstrip(".,;:!?")
        try:
            parsed = urlsplit(value if "://" in value else "https://" + value)
            host = parsed.hostname
            port = parsed.port
        except ValueError:
            continue
        if not host or (port is not None and not 1 <= port <= 65535):
            continue
        # Fullmatch prevents upstream TLD alternatives from accepting .com inside .company.
        known = _patterns()[3].fullmatch(host)
        syntactic_domain = re.fullmatch(
            r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
            r"(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})",
            host,
            re.I | re.ASCII,
        )
        if not syntactic_domain or len(host) > 253:
            continue
        if known is None:
            upstream_tlds = set(re.findall(r"\(\?:([a-z]+)\)", rules()["url_base_pattern"]))
            if host.rsplit(".", 1)[-1] in upstream_tlds:
                continue
        spans.append((match.start(), match.start() + len(value)))
    return spans
