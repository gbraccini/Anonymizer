import os
from contextlib import closing
from ctypes import byref, c_float
from io import BytesIO

import pytest

pdfium = pytest.importorskip("pypdfium2")
raw = pytest.importorskip("pypdfium2.raw")
Image = pytest.importorskip("PIL.Image")
Canvas = pytest.importorskip("reportlab.pdfgen.canvas").Canvas

from anonymizer.extraction import render_pdf_for_analysis  # noqa: E402
from anonymizer.ingest import InputFile, inspect_inputs, render_page  # noqa: E402
from anonymizer.model import PageResult, TextRegion, Warning  # noqa: E402
from anonymizer.pipeline import analyze_documents  # noqa: E402
from anonymizer.visual_model import DocumentError  # noqa: E402


def vector_label(canvas, font, text, x=40, y=160, size=24):
    for char in text:
        glyph = raw.FPDFFont_GetGlyphPath(font, ord(char), size)
        path = canvas.beginPath()
        if glyph:
            points = []
            for i in range(raw.FPDFGlyphPath_CountGlyphSegments(glyph)):
                segment = raw.FPDFGlyphPath_GetGlyphPathSegment(glyph, i)
                px, py = c_float(), c_float()
                assert raw.FPDFPathSegment_GetPoint(segment, byref(px), byref(py))
                kind = raw.FPDFPathSegment_GetType(segment)
                point = (x + px.value * size, y + py.value * size)
                if kind == raw.FPDF_SEGMENT_MOVETO:
                    path.moveTo(*point)
                elif kind == raw.FPDF_SEGMENT_LINETO:
                    path.lineTo(*point)
                else:
                    points.extend(point)
                    if len(points) == 6:
                        path.curveTo(*points)
                        points = []
                if raw.FPDFPathSegment_GetClose(segment):
                    path.close()
            canvas.drawPath(path, stroke=0, fill=1)
        width = c_float()
        assert raw.FPDFFont_GetGlyphWidth(font, ord(char), size, byref(width))
        x += width.value


def source(
    *,
    white=False,
    alpha=False,
    image=False,
    form=False,
    invisible=False,
    overlap=False,
    native=True,
):
    seed = BytesIO()
    seed_canvas = Canvas(seed)
    seed_canvas.drawString(10, 10, "Helvetica")
    seed_canvas.save()
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=(400, 300), invariant=1)
    if native:
        canvas.drawString(40, 250, "Elvio Veltrani; Hb 12 g/dL; non febbre")
    if invisible:
        text = canvas.beginText(40, 200)
        text.setTextRenderMode(3)
        text.textLine("Hidden synthetic text")
        canvas.drawText(text)
    if alpha:
        canvas.setFillAlpha(0.5)
    if white:
        canvas.setFillColorRGB(1, 1, 1)
    with pdfium.PdfDocument(seed.getvalue()) as document:
        with closing(document[0]) as page:
            font = raw.FPDFTextObj_GetFont(next(page.get_objects()))
            vector_label(canvas, font, "Nerina Serralvi", y=250 if overlap else 160)
    if image:
        from reportlab.lib.utils import ImageReader

        canvas.drawImage(ImageReader(Image.new("RGB", (5, 5), "black")), 20, 30, 20, 20)
    if form:
        canvas.acroForm.textfield(name="field", value="Synthetic", x=40, y=40, width=100)
        canvas.showPage()
    canvas.save()
    return InputFile(buffer.getvalue(), ".pdf")


def test_residual_preserves_vector_letters_and_removes_native_pixels():
    original = source()
    _, items = inspect_inputs((original,), dpi=72)
    rendered = render_pdf_for_analysis(items[0], hybrid=True)
    reference = render_page(items[0])
    try:
        assert rendered.residual and "Elvio Veltrani" in rendered.native.text
        native_area = rendered.image.crop((35, 30, 350, 60))
        assert native_area.getextrema() == ((255, 255),) * 3
        native_area.close()
        vector_area = rendered.image.crop((35, 115, 230, 150))
        reference_area = reference.crop((35, 115, 230, 150))
        assert vector_area.tobytes() == reference_area.tobytes()
        assert vector_area.getextrema()[0][0] == 0
        vector_area.close()
        reference_area.close()
    finally:
        rendered.image.close()
        reference.close()
    legacy = render_pdf_for_analysis(items[0])
    assert legacy.native is None and not legacy.residual
    legacy.image.close()


def test_removing_text_objects_preserves_overlapping_vector_strokes():
    _, items = inspect_inputs((source(overlap=True),), dpi=72)
    rendered = render_pdf_for_analysis(items[0], hybrid=True)
    _, vector_items = inspect_inputs((source(overlap=True, native=False),), dpi=72)
    vector_only = render_page(vector_items[0])
    try:
        assert rendered.residual
        assert rendered.image.tobytes() == vector_only.tobytes()
    finally:
        rendered.image.close()
        vector_only.close()


def test_pipeline_merges_residual_offsets_and_never_skips_empty_ocr(monkeypatch):
    calls = []

    def recognize(image, item, config):
        calls.append(True)
        return PageResult(
            item.page_id,
            item.source.source_id,
            item.source_page_index,
            "Nerina Serralvi",
            "ocr",
            (TextRegion(0, len("Nerina Serralvi"), (40, 115, 230, 150)),),
        )

    monkeypatch.setattr("anonymizer.pipeline.recognize", recognize)
    analysis = analyze_documents((source(),), dpi=72, pdf_hybrid=True)
    page = analysis.manifest.pages[0].page
    assert calls == [True]
    assert page.extraction_mode == "native_pdf+residual_ocr"
    assert page.text.endswith("\nNerina Serralvi")
    last = page.regions[-1]
    assert page.text[last.start : last.end] == "Nerina Serralvi"
    assert any(
        page.text[s.start : s.end] == "Nerina Serralvi" for s in analysis.text_analysis.candidates
    )
    assert any(w.code == "residual_graphics_ocr_requires_review" for w in page.warnings)

    def empty(image, item, config):
        calls.append(True)
        return PageResult(
            item.page_id,
            item.source.source_id,
            item.source_page_index,
            "",
            "ocr",
            warnings=(Warning("no_readable_text_manual_review"),),
        )

    monkeypatch.setattr("anonymizer.pipeline.recognize", empty)
    page = analyze_documents((source(),), dpi=72, pdf_hybrid=True).manifest.pages[0].page
    assert len(calls) == 2
    assert "Elvio Veltrani" in page.text
    assert not any(w.code == "no_readable_text_manual_review" for w in page.warnings)
    assert any(w.code == "residual_graphics_ocr_requires_review" for w in page.warnings)


@pytest.mark.parametrize(
    "options",
    [dict(white=True), dict(alpha=True), dict(image=True), dict(form=True), dict(invisible=True)],
)
def test_uncertain_objects_and_compositing_fall_back_to_full_ocr(options):
    _, items = inspect_inputs((source(**options),), dpi=72)
    rendered = render_pdf_for_analysis(items[0], hybrid=True)
    try:
        assert rendered.native is None and not rendered.residual
        reference = render_page(items[0])
        try:
            assert rendered.image.tobytes() == reference.tobytes()
        finally:
            reference.close()
    finally:
        rendered.image.close()


def test_residual_setup_failure_restores_original_and_ocr_failure_is_not_partial(monkeypatch):
    import anonymizer.extraction as extraction

    original = source()
    _, items = inspect_inputs((original,), dpi=72)
    monkeypatch.setattr(
        extraction,
        "_render_image",
        lambda *args: (_ for _ in ()).throw(RuntimeError("Synthetic failure")),
    )
    rendered = render_pdf_for_analysis(items[0], hybrid=True)
    assert rendered.native is None and not rendered.residual
    reference = render_page(items[0])
    assert rendered.image.tobytes() == reference.tobytes()
    rendered.image.close()
    reference.close()
    monkeypatch.undo()
    captured = []

    def fail_ocr(image, *args):
        captured.append(image)
        raise DocumentError("ocr_unavailable_failed_or_timeout")

    monkeypatch.setattr("anonymizer.pipeline.recognize", fail_ocr)
    with pytest.raises(DocumentError, match="ocr_unavailable"):
        analyze_documents((original,), dpi=72, pdf_hybrid=True)
    with pytest.raises(ValueError, match="closed"):
        captured[0].getpixel((0, 0))


def test_uninspectable_font_falls_back(monkeypatch):
    monkeypatch.setattr(raw, "FPDFFont_GetFontData", lambda *args: False)
    _, items = inspect_inputs((source(),), dpi=72)
    rendered = render_pdf_for_analysis(items[0], hybrid=True)
    try:
        assert rendered.native is None and not rendered.residual
    finally:
        rendered.image.close()


def test_default_pipeline_keeps_conservative_full_ocr_for_pdf_paths(monkeypatch):
    calls = []

    def full_ocr(image, item, config):
        region = image.crop((35, 30, 350, 60))
        try:
            assert region.getextrema()[0][0] < 255
        finally:
            region.close()
        calls.append(True)
        return PageResult(
            item.page_id, item.source.source_id, item.source_page_index, "Synthetic full OCR", "ocr"
        )

    monkeypatch.setattr("anonymizer.pipeline.recognize", full_ocr)
    page = analyze_documents((source(),), dpi=72).manifest.pages[0].page
    assert page.extraction_mode == "ocr"
    assert calls == [True]
    with pytest.raises(DocumentError, match="invalid_pdf_hybrid_option"):
        analyze_documents((source(),), pdf_hybrid="false")


def test_crop_rotation_and_export_use_unchanged_original_not_residual(monkeypatch, tmp_path):
    import hashlib

    pypdf = pytest.importorskip("pypdf")
    from pypdf.generic import RectangleObject

    from anonymizer.export import export_document
    from anonymizer.manifest import confirm_review
    from anonymizer.redact import apply_redactions

    original = source()
    reader = pypdf.PdfReader(BytesIO(original.data))
    writer = pypdf.PdfWriter()
    page = reader.pages[0]
    page.cropbox = RectangleObject((20, 10, 380, 280))
    page.rotate(90)
    writer.add_page(page)
    buffer = BytesIO()
    writer.write(buffer)
    original = InputFile(buffer.getvalue(), ".pdf")
    digest = hashlib.sha256(original.data).hexdigest()
    calls = []

    def empty_ocr(image, item, config):
        calls.append(True)
        assert image.size == (item.geometry.width, item.geometry.height)
        return PageResult(item.page_id, item.source.source_id, item.source_page_index, "", "ocr")

    monkeypatch.setattr("anonymizer.pipeline.recognize", empty_ocr)
    analysis = analyze_documents((original,), dpi=144, pdf_hybrid=True)
    assert calls == [True]
    visual = analysis.manifest.pages[0]
    assert visual.page.extraction_mode == "native_pdf+residual_ocr"
    assert "Hb 12 g/dL; non febbre" in visual.page.text
    assert visual.geometry.rotation == 90
    for region in visual.page.regions:
        x0, y0, x1, y1 = region.box
        assert 0 <= x0 < x1 <= visual.geometry.width
        assert 0 <= y0 < y1 <= visual.geometry.height
    approved = confirm_review(analysis.manifest)
    _, items = inspect_inputs((original,), dpi=144)
    reference = render_page(items[0])
    expected = apply_redactions(reference, approved.pages[0].redactions, visual.geometry)
    try:
        output = tmp_path / "copy.png"
        export_document((original,), approved, output)
        with Image.open(output) as exported:
            assert exported.tobytes() == expected.tobytes()
        output_pdf = tmp_path / "copy.pdf"
        export_document((original,), approved, output_pdf)
        reopened = pypdf.PdfReader(output_pdf)
        assert reopened.pages[0].extract_text() == ""
        images = list(reopened.pages[0].images)
        assert len(images) == 1
        assert images[0].image.tobytes() == expected.tobytes()
        assert hashlib.sha256(original.data).hexdigest() == digest
    finally:
        expected.close()
        reference.close()


@pytest.mark.skipif(not os.getenv("ANONYMIZER_TESSERACT"), reason="real OCR opt-in")
def test_real_ocr_reads_vector_identifier_and_proposes_mask():
    analysis = analyze_documents((source(),), dpi=144, pdf_hybrid=True)
    page = analysis.manifest.pages[0].page
    assert page.extraction_mode == "native_pdf+residual_ocr"
    assert "Nerina Serralvi" in page.text
    assert any(
        page.text[s.start : s.end] == "Nerina Serralvi" for s in analysis.text_analysis.candidates
    )
