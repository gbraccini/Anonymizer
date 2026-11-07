import pytest

from anonymizer.merge import merge
from anonymizer.model import Kind, Span


def span(start, end, *, entity=None, page="p", kind=Kind.PERSON, level=1):
    return Span(page, start, end, kind, level, f"test:{level}", entity_id=entity)


@pytest.mark.parametrize(
    "intervals,expected",
    [
        ([(0, 10), (8, 16)], [(0, 16)]),
        ([(0, 16), (4, 8)], [(0, 16)]),
        ([(0, 5), (4, 9), (8, 15)], [(0, 15)]),
        ([(0, 5), (5, 10)], [(0, 5), (5, 10)]),
    ],
)
def test_coverage_union(intervals, expected):
    source = [span(start, end) for start, end in intervals]
    result = merge("x" * 20, source)
    assert [(item.start, item.end) for item in result] == expected
    assert {candidate.id for item in result for candidate in item.candidates} == {
        s.id for s in source
    }
    input_points = {point for s in source for point in range(s.start, s.end)}
    output_points = {point for s in result for point in range(s.start, s.end)}
    assert input_points <= output_points


def test_adjacent_same_entity_requires_compatible_separator():
    assert len(merge("Elvio Veltrani", [span(0, 5, entity="a"), span(6, 14, entity="a")])) == 1
    assert len(merge("Elvio;Veltrani", [span(0, 5, entity="a"), span(6, 14, entity="a")])) == 2
    assert len(merge("Elvio Veltrani", [span(0, 5, entity="a"), span(6, 14, entity="b")])) == 2


def test_conflicts_keep_all_origins_and_levels_without_identity_merge():
    result = merge(
        "x" * 20, [span(0, 10, entity="a", level=0), span(8, 16, entity="b", kind=Kind.CF)]
    )[0]
    assert (result.start, result.end) == (0, 16)
    assert result.entity_id is None and result.kind == Kind.COMPOSITE
    assert set(result.conflicts) == {"entity_conflict", "type_conflict"}
    assert result.levels == (0, 1)
    assert result.origins == ("test:0", "test:1")


def test_pages_never_merge_and_bounds_are_checked():
    result = merge({"a": "xx", "b": "xx"}, [span(0, 2, page="a"), span(0, 2, page="b")])
    assert len(result) == 2
    with pytest.raises(ValueError):
        merge("xx", [span(0, 2, page="a"), span(0, 2, page="b")])
    with pytest.raises(ValueError):
        merge("xx", [span(0, 3)])
