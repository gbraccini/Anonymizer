from anonymizer.merge import merge
from anonymizer.model import Kind, PageResult, Span
from anonymizer.pseudo import pseudonymize
from anonymizer.reassoc import reassociate


def test_exact_tokens_persona_1_vs_persona_10_and_unknowns():
    names = [f"Name{index}" for index in range(10)]
    text = ";".join(names)
    spans = [
        Span("p", text.index(name), text.index(name) + len(name), Kind.PERSON, 1, "test")
        for name in names
    ]
    result = pseudonymize([PageResult("p", "s", 0, text)], merge(text, spans))
    restored = reassociate(
        "[[PERSONA_10]] [[PERSONA_1]] PERSONA_1 [[PERSONA_99]] [[persona_1]]", result.map
    )
    assert restored.text == "Name9 Name0 PERSONA_1 [[PERSONA_99]] [[persona_1]]"
    assert restored.unknown_tokens == ("[[PERSONA_99]]", "[[persona_1]]")


def test_restoration_is_not_recursive_even_when_original_contains_a_token():
    text = "[[CF_1]]; value"
    spans = [Span("p", 0, 8, Kind.PERSON, 1, "test"), Span("p", 10, 15, Kind.CF, 1, "test")]
    result = pseudonymize([PageResult("p", "s", 0, text)], merge(text, spans))
    assert result.pages[0].text == "[[PERSONA_1]]; [[CF_2]]"
    restored = reassociate(result.pages[0].text, result.map)
    assert restored.text == text
    assert restored.unknown_tokens == ()
