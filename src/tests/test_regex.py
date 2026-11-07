from anonymizer.detect.context import detect_contact_details
from anonymizer.detect.regex import detect_regex
from anonymizer.model import Kind


def test_structured_adapter_is_used_without_changing_cf_phone_policy():
    text = "a+tag@xn--bcher-kva.de; IT61X0542811101000000123456; Tel: +39 012 3456789"
    spans = detect_regex(text, "p")
    assert {s.origin for s in spans} >= {
        "structured:presidio_email",
        "structured:presidio_iban",
        "regex:phone",
    }
    assert next(s for s in spans if s.kind == Kind.IBAN).validation.status == "invalid"


def test_url_patterns_require_facility_contact_context_not_bibliography():
    text = (
        "Clinica Vallerin s.r.l.\nTel. 0123456789 www.vallerin.company\n\n"
        "Bibliografia https://example.org/study info@example.org"
    )
    spans = [s for s in detect_contact_details(text, "p") if s.origin == "context:facility_web"]
    assert [text[s.start : s.end] for s in spans] == ["www.vallerin.company"]
    assert "presidio_commonregex" in spans[0].validation.reason
