import hashlib
import json
from pathlib import Path

import pytest

from anonymizer.detect.structured import (
    contact_urls,
    detect_emails,
    detect_ibans,
    iban_valid,
    rules,
)


@pytest.mark.parametrize(
    "email",
    [
        "elvio@example.invalid",
        "+tag@xn--bcher-kva.de",
        "a.b+tag@example.company",
        "\u00e9lodie@exemple.fr",
        "a@sub-domain.example.it",
    ],
)
def test_email_patterns_preserve_whole_candidates_and_unicode_offsets(email):
    text = "\U0001f600 <" + email + ">."
    spans = detect_emails(text, "p")
    assert [text[s.start : s.end] for s in spans] == [email]
    assert all(s.origin == "structured:presidio_email" for s in spans)


@pytest.mark.parametrize(
    "text",
    [
        "a..b@example.org",
        ".a@example.org",
        "a@-example.org",
        "a@example_.org",
        "a@example.org_bad",
        "a@b@domain.org",
        "Hb 12.5 mg/dL",
        "a@" + "x" * 300 + ".org",
        "a" * 65 + "@example.org",
    ],
)
def test_email_rejects_malformed_or_unbounded_candidates(text):
    assert detect_emails(text, "p") == []


@pytest.mark.parametrize(
    "iban",
    [
        "IT60X0542811101000000123456",
        "IT60 X054 2811 1010 0000 0123 456",
        "DE89 3704 0044 0532 0130 00",
        "GB82 WEST 1234 5698 7654 32",
        "FR14 2004 1010 0505 0001 3M02 606",
        "it60x0542811101000000123456",
        "DE89-3704-0044-0532-0130-00",
    ],
)
def test_iban_country_formats_and_mod97(iban):
    text = "\U0001f600 " + iban + "; visita"
    assert iban_valid(iban)
    spans = detect_ibans(text, "p")
    assert [(text[s.start : s.end], s.validation.status) for s in spans] == [(iban, "valid")]


def test_invalid_checksum_policy_and_explicit_label():
    italian = "IT61X0542811101000000123456"
    german = "DE88 3704 0044 0532 0130 00"
    assert not iban_valid(italian) and not iban_valid(german)
    assert detect_ibans(italian, "p")[0].validation.status == "invalid"
    assert detect_ibans(german, "p") == []
    assert detect_ibans("IBAN: " + german, "p")[0].validation.status == "invalid"


@pytest.mark.parametrize(
    "text",
    [
        "xIT60X0542811101000000123456",
        "IT60X0542811101000000123456X",
        "_IT60X0542811101000000123456",
        "IT60X0542811101000000123456_",
        "IT60 X054 2811\n1010 0000 0123 456",
        "IT60 X054 2811\r\n1010 0000 0123 456",
        "PA 120/80; Hb 13; glicemia 100; IT12 pressione 25 mg",
    ],
)
def test_iban_strict_boundaries_and_no_multiline_join(text):
    assert detect_ibans(text, "p") == []


def test_two_adjacent_ibans_and_trailing_prose_are_not_swallowed():
    first, second = "DE89370400440532013000", "IT60X0542811101000000123456"
    text = first + " " + second + " 2 giorni"
    assert [text[s.start : s.end] for s in detect_ibans(text, "p")] == [first, second]


@pytest.mark.parametrize(
    "url",
    [
        "https://example.company",
        "www.example.company",
        "https://example.it/path?q=1",
        "https://xn--bcher-kva.de/test",
        "www.example.it",
    ],
)
def test_url_tld_boundary_does_not_truncate_longer_alternative(url):
    text = "(" + url + "),"
    assert [text[a:b] for a, b in contact_urls(text)] == [url]


@pytest.mark.parametrize("text", ["info@example.it", "example.it", "https://example..it"])
def test_url_does_not_match_email_fragments_or_partial_domains(text):
    assert contact_urls(text) == []


def test_rule_payload_contains_runtime_patterns_and_pinned_provenance():
    data = rules()
    assert data["revision"] == "05b60e1a6805f3b2c0ad6cbe7526ccd226647971"
    assert "IT" in data["iban_country_patterns"] and len(data["iban_country_patterns"]) > 60
    root = Path("build/artifacts/presidio-upstream")
    if root.is_dir():
        for name, source in data["sources"].items():
            assert hashlib.sha256((root / name).read_bytes()).hexdigest() == source["sha256"]
    rules_path = Path(__file__).parents[1] / "anonymizer/data/presidio_rules.json"
    assert json.loads(rules_path.read_text("utf-8")) == data


@pytest.mark.parametrize(
    "url", ["www.example.it", "https://example.it:443/path?q=1#part", "www.example.newtld"]
)
def test_url_complete_suffix_and_terminal_punctuation(url):
    text = "Contatti " + url + "."
    assert [text[a:b] for a, b in contact_urls(text)] == [url]
