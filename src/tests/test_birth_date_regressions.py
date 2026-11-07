import re
from dataclasses import replace

import pytest
from PIL import Image

from anonymizer.model import Kind, PageResult, TextRegion
from anonymizer.redact import apply_redactions, propose_redactions
from anonymizer.text_pipeline import analyze_text
from anonymizer.visual_model import SourcePageGeometry, VisualPage
from anonymizer.web.text import page_text


@pytest.mark.parametrize(
    "context",
    [
        "nata a Valleverde il ",
        "nato/a a San Martino\ndelle Valli (VV) il ",
        "mata a Valleverde i ",
        "mata a MIN i ",
        "Nato a: Valleverde (PV) il ",
        "nata a:Valleverde il ",
    ],
)
def test_birth_date_is_masked_in_text_and_geometry_but_event_date_remains(context):
    birth_date, event_date = "03/03/1980", "04/11/2026"
    text = f"Paziente {context}{birth_date}\nControllo programmato il {event_date}."
    birth_start, event_start = text.index(birth_date), text.index(event_date)
    regions = []
    offset = 0
    for row, line in enumerate(text.splitlines()):
        for word in re.finditer(r"\S+", line):
            x, y = 10 + word.start() * 8, 10 + row * 24
            regions.append(
                TextRegion(
                    offset + word.start(),
                    offset + word.end(),
                    (x, y, x + len(word.group()) * 8, y + 20),
                )
            )
        offset += len(line) + 1
    birth_box = next(r.box for r in regions if r.start == birth_start)
    event_box = next(r.box for r in regions if r.start == event_start)
    page = PageResult(
        "synthetic-birth-page",
        "synthetic-source",
        0,
        text,
        extraction_mode="ocr",
        regions=tuple(regions),
    )
    analysis = analyze_text([page], ner_disabled_reason="synthetic_test")
    birth_span = next(s for s in analysis.merged_spans if s.kind == Kind.BIRTH_DATE)
    assert (birth_span.start, birth_span.end) == (birth_start, birth_start + len(birth_date))
    assert birth_date not in analysis.result.pages[0].text
    assert event_date in analysis.result.pages[0].text

    geometry = SourcePageGeometry(800, 120, 800, 120, 72)
    masks, warnings, required = propose_redactions(page, list(analysis.merged_spans), geometry)
    assert not warnings
    assert birth_span.id in required
    birth_masks = [mask for mask in masks if birth_span.id in mask.candidate_ids]
    assert len(birth_masks) == 1
    x0, y0, x1, y1 = birth_box
    assert birth_masks[0].polygon == (
        (x0 - 2, y0 - 2), (x1 + 2, y0 - 2), (x1 + 2, y1 + 2), (x0 - 2, y1 + 2)
    )
    assert all(max(y for _, y in mask.polygon) < event_box[1] for mask in masks)
    copied = page_text(VisualPage(page, 0, geometry, masks))["redacted"]
    assert birth_date not in copied
    assert event_date in copied

    with Image.new("RGB", (geometry.width, geometry.height), "white") as source:
        with apply_redactions(
            source, tuple(replace(mask, confirmed=True) for mask in masks), geometry
        ) as output:
            assert output.crop(birth_box).getextrema() == ((0, 0),) * 3
            assert output.crop(event_box).getextrema() == ((255, 255),) * 3
