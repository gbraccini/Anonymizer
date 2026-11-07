import math
from dataclasses import replace

import pytest

Image = pytest.importorskip("PIL.Image")
ImageDraw = pytest.importorskip("PIL.ImageDraw")

from anonymizer.model import Kind, MergedSpan, PageResult, Span, TextRegion  # noqa: E402
from anonymizer.redact import (  # noqa: E402
    _compact_span_rectangles,
    apply_redactions,
    propose_redactions,
)
from anonymizer.visual_model import SourcePageGeometry, VisualRedaction  # noqa: E402


def mask(left, top, right, bottom, candidate="one", **kwargs):
    return VisualRedaction(
        "p",
        ((left, top), (right, top), (right, bottom), (left, bottom)),
        origin="automatic",
        candidate_ids=(candidate,),
        **kwargs,
    )


def pixels(masks, size=(500, 400)):
    result = Image.new("L", size, 0)
    draw = ImageDraw.Draw(result)
    for item in masks:
        x0, y0 = item.polygon[0]
        x1, y1 = item.polygon[2]
        draw.rectangle((x0, y0, x1 - 1, y1 - 1), fill=255)
    return result.tobytes()


def test_only_exact_same_row_touching_intervals_merge():
    original = [
        mask(2, 3, 10, 20),
        mask(10, 3, 18, 20),
        mask(16, 3, 25, 20),
        mask(27, 3, 35, 20),
        mask(2, 23, 10, 40),
        mask(8, 23, 15, 41),
    ]
    compacted = _compact_span_rectangles(original)
    assert len(compacted) == 4
    assert pixels(compacted) == pixels(original)
    assert any(m.polygon == ((2, 3), (25, 3), (25, 20), (2, 20)) for m in compacted)


def test_different_candidates_manual_and_different_review_states_never_merge():
    original = [mask(2, 3, 10, 20, candidate="one"), mask(8, 3, 18, 20, candidate="two")]
    assert len(_compact_span_rectangles(original)) == 2
    original = [mask(2, 3, 10, 20), replace(mask(8, 3, 18, 20), origin="manual")]
    assert len(_compact_span_rectangles(original)) == 2
    original = [mask(2, 3, 10, 20), mask(8, 3, 18, 20, confirmed=True)]
    assert len(_compact_span_rectangles(original)) == 2


@pytest.mark.parametrize("dpi", [72, 144, 300])
def test_proposals_have_identical_footprint_at_multiple_dpis_and_preserve_other_pixels(dpi):
    scale = dpi / 72
    boxes = [
        (10.1, 20.2, 15.8, 30.7),
        (16.1, 20.2, 21.7, 30.7),
        (28.1, 20.2, 34.9, 30.7),
        (10.1, 40.2, 15.8, 50.7),
    ]
    boxes = [tuple(value * scale for value in box) for box in boxes]
    width, height = round(100 * scale), round(80 * scale)
    geometry = SourcePageGeometry(width, height, 100, 80, dpi)
    page = PageResult(
        "p",
        "s",
        0,
        "ABCD",
        "native_pdf",
        tuple(TextRegion(i, i + 1, box) for i, box in enumerate(boxes)),
    )
    candidate = Span("p", 0, 4, Kind.PERSON, 3, "synthetic")
    span = MergedSpan("p", 0, 4, Kind.PERSON, (candidate,))
    compacted, warnings, required = propose_redactions(page, [span], geometry)
    original = []
    for x0, y0, x1, y1 in boxes:
        original.append(
            mask(
                max(0, math.floor(x0) - 2),
                max(0, math.floor(y0) - 2),
                min(width, math.ceil(x1) + 2),
                min(height, math.ceil(y1) + 2),
                candidate=span.id,
            )
        )
    assert len(compacted) < len(original)
    assert not warnings and required == (span.id,)
    assert pixels(compacted, (width, height)) == pixels(original, (width, height))
    background = Image.new("RGB", (width, height))
    background.putdata(
        [(x % 255, y % 255, (x + y) % 255) for y in range(height) for x in range(width)]
    )
    before = apply_redactions(
        background, tuple(replace(m, confirmed=True) for m in original), geometry
    )
    after = apply_redactions(
        background, tuple(replace(m, confirmed=True) for m in compacted), geometry
    )
    try:
        assert before.tobytes() == after.tobytes()
        assert background.getpixel((width - 1, height - 1)) == after.getpixel(
            (width - 1, height - 1)
        )
    finally:
        before.close()
        after.close()
        background.close()
