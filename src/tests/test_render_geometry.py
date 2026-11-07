from contextlib import closing
from dataclasses import replace
from io import BytesIO

import pytest

pdfium = pytest.importorskip("pypdfium2")
pytest.importorskip("PIL")
Canvas = pytest.importorskip("reportlab.pdfgen.canvas").Canvas
pypdf = pytest.importorskip("pypdf")

from anonymizer.extraction import render_pdf_for_analysis  # noqa: E402
from anonymizer.ingest import InputFile, inspect_inputs, render_page  # noqa: E402
from anonymizer.visual_model import DocumentError, Limits  # noqa: E402


def letter_document(*, rotation=0, crop=False):
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=(612, 792), invariant=1)
    for number in (1, 2):
        canvas.drawString(80, 700, f"Synthetic page {number}; Hb 12 g/dL")
        canvas.showPage()
    canvas.save()
    if rotation or crop:
        reader = pypdf.PdfReader(BytesIO(buffer.getvalue()))
        writer = pypdf.PdfWriter()
        for page in reader.pages:
            if crop:
                page.cropbox = pypdf.generic.RectangleObject((36, 18, 576, 774))
            if rotation:
                page.rotate(rotation)
            writer.add_page(page)
        buffer = BytesIO()
        writer.write(buffer)
    return InputFile(buffer.getvalue(), ".pdf")


def test_letter_300_dpi_geometry_matches_original_and_analysis_render():
    source = letter_document()
    _, pages = inspect_inputs((source,), dpi=300)
    assert len(pages) == 2
    with pdfium.PdfDocument(source.data) as document:
        for item in pages:
            geometry = item.geometry
            # 792 * (300 / 72) rounds just above 3300, as in PdfPage.render.
            assert (geometry.width, geometry.height) == (2550, 3301)
            assert geometry.pdf_device == (0, 0, 2550, 3301, 0)
            with closing(document[item.source_page_index]) as page:
                with closing(page.render(scale=300 / 72, draw_annots=True)) as bitmap:
                    expected = bitmap.to_pil().convert("RGB")
            with expected, render_page(item) as original:
                rendered = render_pdf_for_analysis(item)
                with rendered.image as analysis:
                    assert original.size == analysis.size == expected.size == (2550, 3301)
                    assert original.tobytes() == analysis.tobytes() == expected.tobytes()


@pytest.mark.parametrize("dpi", [72, 200, 300])
@pytest.mark.parametrize("rotation,crop", [(0, False), (90, True)])
def test_geometry_matches_pdfium_at_selected_dpi_crop_and_rotation(dpi, rotation, crop):
    source = letter_document(rotation=rotation, crop=crop)
    _, pages = inspect_inputs((source,), dpi=dpi)
    with pdfium.PdfDocument(source.data) as document:
        with closing(document[0]) as page:
            with closing(page.render(scale=dpi / 72, draw_annots=True)) as bitmap:
                assert (pages[0].geometry.width, pages[0].geometry.height) == (
                    bitmap.width,
                    bitmap.height,
                )
    with render_page(pages[0]) as image:
        assert image.size == (pages[0].geometry.width, pages[0].geometry.height)


def test_real_geometry_mismatch_is_still_rejected():
    _, pages = inspect_inputs((letter_document(),), dpi=72)
    item = replace(pages[0], geometry=replace(pages[0].geometry, width=613))
    for render in (render_page, render_pdf_for_analysis):
        with pytest.raises(DocumentError, match="render_geometry_mismatch"):
            render(item)


def test_budget_includes_pdfium_rounding_pixel_before_render():
    with pytest.raises(DocumentError, match="page_pixel_limit"):
        inspect_inputs((letter_document(),), dpi=300, limits=Limits(max_page_pixels=2550 * 3300))


def budget_document(count, size=(595.276, 841.89)):
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=size, invariant=1)
    for index in range(count):
        canvas.drawString(40, 100, f"Synthetic budget page {index + 1}")
        canvas.showPage()
    canvas.save()
    return InputFile(buffer.getvalue(), ".pdf")


def test_default_budget_accepts_thirty_a4_pages_at_300_dpi():
    records, pages = inspect_inputs((budget_document(30),), dpi=300)
    assert records[0].page_count == len(pages) == 30
    total = sum(item.geometry.width * item.geometry.height for item in pages)
    assert 260_000_000 < total < 300_000_000
    assert all(item.geometry.dpi == 300 for item in pages)


def test_default_page_count_limit_still_rejects_thirty_one_pages():
    with pytest.raises(DocumentError, match="^page_count_limit$"):
        inspect_inputs((budget_document(31),), dpi=300)


def test_total_budget_rejects_allowed_page_count_with_large_individual_pages():
    # Each page is about 11.3 MP, below 25 MP, but thirty exceed the 300 MP total.
    with pytest.raises(DocumentError, match="^total_pixel_limit$"):
        inspect_inputs((budget_document(30, (720, 900)),), dpi=300)


def test_custom_total_budget_is_preserved_and_dpi_choice_remains_explicit():
    source = budget_document(30)
    limits = Limits(max_total_pixels=150_000_000)
    with pytest.raises(DocumentError, match="^total_pixel_limit$"):
        inspect_inputs((source,), dpi=300, limits=limits)
    _, pages = inspect_inputs((source,), dpi=200, limits=limits)
    assert len(pages) == 30 and all(item.geometry.dpi == 200 for item in pages)
