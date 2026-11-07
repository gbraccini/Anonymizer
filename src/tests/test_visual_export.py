import hashlib
import struct
import zlib
from dataclasses import replace
from io import BytesIO

import pytest

from anonymizer.cli import main
from anonymizer.export import export_document
from anonymizer.ingest import InputFile, inspect_inputs, render_page
from anonymizer.manifest import confirm_review
from anonymizer.model import PageResult
from anonymizer.pipeline import analyze_documents
from anonymizer.visual_model import (
    DocumentError,
    Limits,
    ReviewManifest,
    ReviewWarning,
    VisualPage,
    VisualRedaction,
)

Image = pytest.importorskip("PIL.Image")
ImageOps = pytest.importorskip("PIL.ImageOps")
PngImagePlugin = pytest.importorskip("PIL.PngImagePlugin")
pytest.importorskip("pypdfium2")
pypdf = pytest.importorskip("pypdf")
RectangleObject = pytest.importorskip("pypdf.generic").RectangleObject
ImageReader = pytest.importorskip("reportlab.lib.utils").ImageReader
Canvas = pytest.importorskip("reportlab.pdfgen.canvas").Canvas


def test_mrz_block_masks_omitted_edge_cells_with_shared_text_footprint():
    from anonymizer.model import TextRegion
    from anonymizer.redact import apply_redactions, propose_redactions
    from anonymizer.text_pipeline import analyze_text
    from anonymizer.visual_model import SourcePageGeometry
    from anonymizer.web.text import page_text

    lines = [
        "I<ITAAB12345CD0" + "<" * 15,
        "8001030F3001050FRA" + "<" * 11 + "9",
        "DORVINO<<LUCIA".ljust(30, "<"),
    ]
    text = "\n".join(lines)
    regions, offset = [], 0
    for index, line in enumerate(lines):
        regions.append(
            TextRegion(offset, offset + len(line), (60, 100 + index * 20, 360, 110 + index * 20))
        )
        offset += len(line) + 1
    page = PageResult("mrz", "s", 0, text, regions=tuple(regions))
    analysis = analyze_text([page])
    geometry = SourcePageGeometry(420, 200, 420, 200, 72)
    masks, warnings, _ = propose_redactions(page, list(analysis.merged_spans), geometry)
    assert not warnings
    assert len(masks) == 1
    masks = tuple(replace(mask, confirmed=True) for mask in masks)
    with Image.new("RGB", (420, 200), (200, 200, 200)) as original:
        with apply_redactions(original, masks, geometry) as output:
            for y in (105, 125, 145):
                assert output.getpixel((45, y)) == (0, 0, 0)
                assert output.getpixel((375, y)) == (0, 0, 0)
            assert output.getpixel((10, 20)) == original.getpixel((10, 20))
        assert original.getpixel((45, 105)) == (200, 200, 200)
    redacted = page_text(VisualPage(page, 0, geometry, masks))
    assert "DORVINO" not in redacted["redacted"]


def png_input(mode="RGB", size=(120, 80), **options):
    image = Image.new(mode, size, 100)
    buffer = BytesIO()
    image.save(buffer, "PNG", **options)
    return InputFile(buffer.getvalue(), ".png")


def pdf_input(*texts, rotation=0, crop=False, mixed=False, annotation=False, form=False):
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=(400, 300), invariant=1)
    canvas.setAuthor("Sensitive Author Synthetic")
    for text in texts or ("Elvio Veltrani",):
        canvas.drawString(40, 240, text)
        canvas.drawString(40, 150, "Hb 12 g/dL; non febbre")
        if mixed:
            image = Image.new("RGB", (40, 40), "red")
            canvas.drawImage(ImageReader(image), 40, 30, 40, 40)
        if annotation:
            canvas.textAnnotation("Synthetic hidden annotation", Rect=(200, 200, 220, 220))
        if form:
            canvas.acroForm.textfield(
                name="synthetic", value="Nerina Serralvi", x=40, y=40, width=120, height=25
            )
        canvas.showPage()
    canvas.save()
    if rotation or crop:
        reader = pypdf.PdfReader(BytesIO(buffer.getvalue()))
        writer = pypdf.PdfWriter()
        for page in reader.pages:
            if crop:
                page.cropbox = RectangleObject((20, 10, 380, 280))
            if rotation:
                page.rotate(rotation)
            writer.add_page(page)
        buffer = BytesIO()
        writer.write(buffer)
    return InputFile(buffer.getvalue(), ".pdf")


def manually_reviewed(source, polygon=((5, 5), (30, 5), (30, 25), (5, 25))):
    records, pages = inspect_inputs((source,), dpi=144)
    item = pages[0]
    page = PageResult(item.page_id, source.source_id, 0, "")
    mask = VisualRedaction(page.page_id, polygon)
    visual = VisualPage(page, 0, item.geometry, (mask,), (ReviewWarning("manual_review"),))
    return confirm_review(ReviewManifest(records, (visual,), page_order=(page.page_id,)))


def png_chunks(raw):
    cursor = 8
    chunks = []
    while cursor < len(raw):
        size = struct.unpack(">I", raw[cursor : cursor + 4])[0]
        chunks.append(raw[cursor + 4 : cursor + 8])
        cursor += 12 + size
    return chunks


def test_png_exact_pixels_outside_masks_and_metadata_removed(tmp_path):
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("patient", "Synthetic Sensitive Header")
    source = png_input(pnginfo=metadata)
    before = hashlib.sha256(source.data).hexdigest()
    manifest = manually_reviewed(source)
    output = tmp_path / "copy.png"
    export_document((source,), manifest, output)
    with Image.open(BytesIO(source.data)) as original, Image.open(output) as exported:
        assert exported.size == original.size
        for y in range(original.height):
            for x in range(original.width):
                assert exported.getpixel((x, y)) == (
                    (0, 0, 0) if 5 <= x < 30 and 5 <= y < 25 else original.getpixel((x, y))
                )
        assert exported.info == {}
    assert set(png_chunks(output.read_bytes())) <= {b"IHDR", b"IDAT", b"IEND"}
    assert hashlib.sha256(source.data).hexdigest() == before


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_native_pdf_crop_rotation_geometry_redaction_and_independent_reopen(
    tmp_path, monkeypatch, rotation
):
    source = pdf_input(rotation=rotation, crop=True)
    monkeypatch.setattr(
        "anonymizer.pipeline.recognize", lambda *_: pytest.fail("Native PDF must skip OCR")
    )
    analysis = analyze_documents((source,), dpi=144)
    visual = analysis.manifest.pages[0]
    assert visual.page.extraction_mode == "native_pdf"
    assert "Elvio Veltrani" in visual.page.text
    assert visual.geometry.rotation == rotation
    assert visual.geometry.pdf_crop_box == (20, 10, 380, 280)
    assert visual.redactions
    approved = confirm_review(analysis.manifest)
    output = tmp_path / "redacted.pdf"
    export_document((source,), approved, output)
    reader = pypdf.PdfReader(output)
    page = reader.pages[0]
    assert page.extract_text() == ""
    assert not page.get("/Annots") and not reader.attachments
    assert "/AcroForm" not in reader.trailer["/Root"]
    assert "Sensitive Author" not in str(reader.metadata)
    assert float(page.mediabox.width) == pytest.approx(visual.geometry.width_points)
    assert float(page.mediabox.height) == pytest.approx(visual.geometry.height_points)
    embedded = list(page.images)
    assert len(embedded) == 1
    image = embedded[0].image
    assert image.size == (visual.geometry.width, visual.geometry.height)
    _, originals = inspect_inputs((source,), dpi=144)
    reference = render_page(originals[0])
    for y in range(reference.height):
        for x in range(reference.width):
            masked = any(
                min(p[0] for p in mask.polygon) <= x < max(p[0] for p in mask.polygon)
                and min(p[1] for p in mask.polygon) <= y < max(p[1] for p in mask.polygon)
                for mask in visual.redactions
            )
            assert image.getpixel((x, y)) == ((0, 0, 0) if masked else reference.getpixel((x, y)))
    reference.close()


@pytest.mark.parametrize("options", [{"mixed": True}, {"annotation": True}, {"form": True}])
def test_mixed_annotations_and_forms_use_full_page_ocr(monkeypatch, options):
    source = pdf_input(**options)
    calls = []

    def fake_ocr(image, item, config):
        calls.append(image.size)
        return PageResult(item.page_id, item.source.source_id, 0, "", "ocr")

    monkeypatch.setattr("anonymizer.pipeline.recognize", fake_ocr)
    result = analyze_documents((source,), dpi=144)
    assert calls == [(800, 600)]
    assert result.manifest.pages[0].page.extraction_mode == "ocr"


def test_exif_orientation_export_uses_original_decoded_pixels(tmp_path):
    image = Image.new("RGB", (40, 20), "red")
    for x in range(20):
        for y in range(20):
            image.putpixel((x, y), (0, 0, 255))
    exif = Image.Exif()
    exif[274] = 6
    exif[315] = "Synthetic Private Author"
    buffer = BytesIO()
    image.save(buffer, "JPEG", exif=exif, quality=95)
    source = InputFile(buffer.getvalue(), ".jpg")
    manifest = manually_reviewed(source, ((0, 0), (5, 0), (5, 5), (0, 5)))
    assert (manifest.pages[0].geometry.width, manifest.pages[0].geometry.height) == (20, 40)
    output = tmp_path / "copy.png"
    export_document((source,), manifest, output)
    with Image.open(BytesIO(source.data)) as original:
        reference = ImageOps.exif_transpose(original)
    with Image.open(output) as exported:
        assert exported.size == reference.size and not exported.getexif()
        assert exported.getpixel((10, 20)) == reference.getpixel((10, 20))
        assert exported.getpixel((2, 2)) == (0, 0, 0)


@pytest.mark.parametrize(
    "mode,options,code",
    [
        ("RGBA", {}, "unsupported_depth"),
        ("I;16", {}, "unsupported_depth"),
        ("L", {"transparency": 0}, "unsupported_depth"),
        ("RGB", {"icc_profile": b"synthetic-profile"}, "invalid_color_profile"),
    ],
)
def test_unsupported_image_semantics_rejected(mode, options, code):
    with pytest.raises(DocumentError, match=code):
        inspect_inputs((png_input(mode, **options),))


def test_rgb16_png_rejected_before_pillow_can_downconvert():
    def chunk(kind, payload):
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload))
        )

    raw = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 16, 2, 0, 0, 0))
    raw += chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\x00\x00\x00\x00")) + chunk(b"IEND", b"")
    with pytest.raises(DocumentError, match="unsupported_depth"):
        inspect_inputs((InputFile(raw, ".png"),))


def test_budget_limits_apply_before_rasterization(monkeypatch):
    source = pdf_input("Elvio Veltrani", "Nerina Serralvi")
    monkeypatch.setattr(
        "anonymizer.pipeline.render_pdf_for_analysis",
        lambda *_: pytest.fail("Must reject before render"),
    )
    for limits in (Limits(max_pages=1), Limits(max_page_pixels=100), Limits(max_total_pixels=100)):
        with pytest.raises(DocumentError, match="limit"):
            analyze_documents((source,), limits=limits)


def test_export_rejects_changed_original_geometry_and_missing_pages(tmp_path):
    source = png_input()
    approved = manually_reviewed(source)
    with pytest.raises(DocumentError, match="source_hash"):
        export_document((png_input(size=(121, 80)),), approved, tmp_path / "no.png")
    altered_page = replace(
        approved.pages[0], geometry=replace(approved.pages[0].geometry, width=121)
    )
    with pytest.raises(DocumentError, match="geometry_mismatch"):
        export_document(
            (source,), confirm_review(replace(approved, pages=(altered_page,))), tmp_path / "no.png"
        )
    with pytest.raises(DocumentError, match="page_order|missing_document"):
        confirm_review(replace(approved, pages=()))
    assert not list(tmp_path.iterdir())


def test_cli_two_phase_roundtrip_and_original_not_overwritten(tmp_path):
    source = pdf_input()
    original = tmp_path / "original.pdf"
    original.write_bytes(source.data)
    manifest, output = tmp_path / "review.json", tmp_path / "copy.pdf"
    assert main(["analyze", str(original), "--manifest", str(manifest), "--dpi", "144"]) == 0
    assert (
        main(["export", str(original), "--manifest", str(manifest), "--output", str(output)]) == 1
    )
    assert not output.exists()
    assert (
        main(
            [
                "export",
                str(original),
                "--manifest",
                str(manifest),
                "--output",
                str(output),
                "--confirm-review",
            ]
        )
        == 0
    )
    assert original.read_bytes() == source.data
    assert (
        main(
            [
                "export",
                str(original),
                "--manifest",
                str(manifest),
                "--output",
                str(original),
                "--confirm-review",
            ]
        )
        == 1
    )


def test_output_cleanup_if_later_page_fails(tmp_path, monkeypatch):
    source = pdf_input("Elvio Veltrani", "Nerina Serralvi")
    manifest = confirm_review(analyze_documents((source,), dpi=144).manifest)
    from anonymizer import export as exporter

    actual = exporter.render_page

    def fail_second(item):
        if item.source_page_index == 1:
            raise DocumentError("synthetic_render_failure")
        return actual(item)

    monkeypatch.setattr(exporter, "render_page", fail_second)
    output = tmp_path / "partial.pdf"
    with pytest.raises(DocumentError):
        export_document((source,), manifest, output)
    assert not output.exists()


def test_multiframe_and_dicom_rejected():
    first, second = Image.new("RGB", (10, 10)), Image.new("RGB", (10, 10), "red")
    buffer = BytesIO()
    first.save(buffer, "PNG", save_all=True, append_images=[second])
    with pytest.raises(DocumentError, match="multiple_frames"):
        inspect_inputs((InputFile(buffer.getvalue(), ".png"),))
    with pytest.raises(DocumentError, match="dicom_excluded"):
        inspect_inputs((InputFile(b"DICM", ".dcm"),))


def test_heic_8bit_is_exported_as_clean_lossless_png(tmp_path):
    pillow_heif = pytest.importorskip("pillow_heif")
    buffer = BytesIO()
    pillow_heif.from_pillow(Image.new("RGB", (120, 80), "green")).save(buffer)
    source = InputFile(buffer.getvalue(), ".heic")
    manifest = manually_reviewed(source)
    output = tmp_path / "copy.png"
    export_document((source,), manifest, output)
    _, items = inspect_inputs((source,), dpi=144)
    reference = render_page(items[0])
    with Image.open(output) as exported:
        assert exported.getpixel((80, 40)) == reference.getpixel((80, 40))
        assert exported.getpixel((10, 10)) == (0, 0, 0)
        assert exported.info == {}
    reference.close()


def test_acroform_value_reaches_visible_raster_and_invisible_text_forces_ocr(monkeypatch):
    from anonymizer.extraction import render_pdf_for_analysis

    _, items = inspect_inputs((pdf_input(form=True),), dpi=144)
    image, native = render_pdf_for_analysis(items[0])
    assert native is None
    interior = image.crop((85, 475, 310, 510))
    assert (
        sum(
            min(interior.getpixel((x, y))) < 100
            for y in range(interior.height)
            for x in range(interior.width)
        )
        > 50
    )
    image.close()
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=(400, 300))
    text = canvas.beginText(40, 240)
    text.setTextRenderMode(3)
    text.textLine("Elvio Veltrani")
    canvas.drawText(text)
    canvas.save()
    _, items = inspect_inputs((InputFile(buffer.getvalue(), ".pdf"),), dpi=144)
    image, native = render_pdf_for_analysis(items[0])
    assert native is None
    image.close()


def test_explicit_page_reordering_preserves_identity_and_output_sizes(tmp_path):
    buffer = BytesIO()
    canvas = Canvas(buffer)
    for size, text in (((300, 200), "Elvio Veltrani"), ((400, 250), "Nerina Serralvi")):
        canvas.setPageSize(size)
        canvas.drawString(20, 100, text)
        canvas.showPage()
    canvas.save()
    source = InputFile(buffer.getvalue(), ".pdf")
    manifest = analyze_documents((source,), dpi=144).manifest
    pages = tuple(reversed(manifest.pages))
    with pytest.raises(DocumentError, match="page_order_mismatch"):
        confirm_review(replace(manifest, pages=pages))
    reviewed = confirm_review(
        replace(manifest, pages=pages, page_order=tuple(page.page.page_id for page in pages))
    )
    output = tmp_path / "reordered.pdf"
    export_document((source,), reviewed, output)
    reader = pypdf.PdfReader(output)
    assert [(float(page.mediabox.width), float(page.mediabox.height)) for page in reader.pages] == [
        (400, 250),
        (300, 200),
    ]


def test_quad_manual_mask_uses_declared_conservative_footprint(tmp_path):
    source = png_input()
    polygon = ((10.2, 10.2), (70.1, 20.1), (60.7, 60.3), (15.1, 50.8))
    manifest = manually_reviewed(source, polygon)
    output = tmp_path / "quad.png"
    export_document((source,), manifest, output)
    with Image.open(output) as image:
        assert image.getpixel((35, 30)) == (0, 0, 0)
        assert image.getpixel((0, 0)) == (100, 0, 0)
        assert image.getpixel((100, 70)) == (100, 0, 0)
    assert (
        manifest.pages[0].redactions[0].raster_policy == "rectangle_outward_quad_rounded_edge3_v1"
    )


def test_attachments_and_original_text_do_not_transfer_to_export(tmp_path):
    original = pdf_input()
    writer = pypdf.PdfWriter(clone_from=BytesIO(original.data))
    writer.add_attachment("sensitive-original.txt", b"Synthetic private attachment")
    buffer = BytesIO()
    writer.write(buffer)
    source = InputFile(buffer.getvalue(), ".pdf")
    manifest = confirm_review(analyze_documents((source,), dpi=144).manifest)
    output = tmp_path / "copy.pdf"
    export_document((source,), manifest, output)
    reader = pypdf.PdfReader(output)
    assert not reader.attachments and reader.pages[0].extract_text() == ""


def test_xfa_is_rejected_before_render(monkeypatch):
    import pypdfium2.raw as raw

    monkeypatch.setattr(raw, "FPDF_GetFormType", lambda *_: raw.FORMTYPE_XFA_FULL)
    with pytest.raises(DocumentError, match="unsupported_xfa"):
        inspect_inputs((pdf_input(),))


def test_corrupt_and_encrypted_pdf_cli_errors_are_controlled(tmp_path, capsys):
    for data in (b"%PDF-corrupt",):
        path = tmp_path / "sensitive-name.pdf"
        path.write_bytes(data)
        assert main(["analyze", str(path), "--manifest", str(tmp_path / "none.json")]) == 1
        captured = capsys.readouterr()
        assert "Traceback" not in captured.err and "sensitive-name" not in captured.err
    writer = pypdf.PdfWriter()
    writer.add_blank_page(100, 100)
    writer.encrypt("synthetic-password")
    encrypted = tmp_path / "encrypted.pdf"
    writer.write(encrypted)
    assert main(["analyze", str(encrypted), "--manifest", str(tmp_path / "encrypted.json")]) == 1
