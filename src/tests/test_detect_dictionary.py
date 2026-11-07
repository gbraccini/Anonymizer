from anonymizer.detect.dictionary import Vocabulary, detect_dictionary, load_vocabulary
from anonymizer.model import Kind


def test_synthetic_names_locations_and_facilities_have_bounded_coverage():
    text = (
        "Elvio Veltrani, nato a Valleverde. Dott. Nerina Serralvi. "
        "Clinica del Glicine: Hb 12 g/dL; non febbre."
    )
    spans = detect_dictionary(text, "p")
    found = [(span.kind, text[span.start : span.end]) for span in spans]
    assert (Kind.PERSON, "Elvio Veltrani") in found
    assert (Kind.DOCTOR, "Nerina Serralvi") in found
    assert (Kind.LOCATION, "Valleverde") in found
    assert (Kind.FACILITY, "Clinica del Glicine") in found
    assert all("Hb" not in text[span.start : span.end] for span in spans)
    assert all("synthetic_subset" in span.origin for span in spans)


def test_ambiguous_surnames_require_context():
    assert detect_dictionary("Forte dolore alla testa, grasso viscerale.", "p") == []
    spans = detect_dictionary("Sig. Forte e Dott. Testa", "p")
    assert [span.kind for span in spans] == [Kind.PERSON, Kind.DOCTOR]


def test_custom_vocabulary_and_explicit_limit():
    vocabulary = Vocabulary(("Luigi",), ("Verdi",), (), (), source="test")
    text = "Dott. Luigi Verdi: pressione 120/80"
    found = detect_dictionary(text, "p", vocabulary)
    assert any(
        span.kind == Kind.DOCTOR and text[span.start : span.end] == "Luigi Verdi" for span in found
    )
    assert load_vocabulary().source == "synthetic_subset:CC0-1.0"
