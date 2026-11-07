import hashlib
import struct
from io import BytesIO

import pytest

from anonymizer.export import export_document
from anonymizer.ingest import InputFile, inspect_inputs, render_page
from anonymizer.manifest import confirm_review
from anonymizer.model import PageResult
from anonymizer.visual_model import DocumentError, ReviewManifest, VisualPage

Image = pytest.importorskip("PIL.Image")
ImageCms = pytest.importorskip("PIL.ImageCms")
PngInfo = pytest.importorskip("PIL.PngImagePlugin").PngInfo


def source(*, icc=None, gamma=None, srgb=None, chroma=None):
    info = PngInfo()
    if gamma is not None:
        info.add(b"gAMA", struct.pack(">I", gamma))
    if srgb is not None:
        info.add(b"sRGB", bytes([srgb]))
    if chroma is not None:
        info.add(b"cHRM", struct.pack(">8I", *chroma))
    output = BytesIO()
    with Image.new("RGB", (50, 30), (64, 120, 200)) as image:
        image.save(output, "PNG", pnginfo=info, icc_profile=icc)
    return InputFile(output.getvalue(), ".png")


@pytest.mark.parametrize(
    "metadata",
    [
        {"srgb": 0, "gamma": 45455},
        {"icc": ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()},
        {"gamma": 100000},
        {"chroma": (31270, 32900, 64000, 33000, 30000, 60000, 15000, 6000)},
    ],
)
def test_normalized_analysis_and_export_have_identical_pixels_without_source_metadata(
    metadata, tmp_path
):
    original = source(**metadata)
    digest = hashlib.sha256(original.data).hexdigest()
    records, items = inspect_inputs((original,))
    item = items[0]
    with render_page(item) as reference:
        pixels = reference.tobytes()
        assert not reference.info
        if metadata.get("gamma") == 100000:
            # Linear-light 8-bit samples encoded with the IEC sRGB transfer curve.
            assert reference.getpixel((0, 0)) == (137, 182, 229)
        if "srgb" in metadata:
            assert reference.getpixel((0, 0)) == (64, 120, 200)
    page = PageResult(item.page_id, original.source_id, 0, "")
    manifest = confirm_review(
        ReviewManifest(records, (VisualPage(page, 0, item.geometry),), page_order=(page.page_id,))
    )
    path = tmp_path / "redacted.png"
    export_document((original,), manifest, path)
    with Image.open(path) as exported:
        assert exported.tobytes() == pixels
        assert not any(k in exported.info for k in ("icc_profile", "gamma", "chromaticity", "exif"))
    assert hashlib.sha256(original.data).hexdigest() == digest


@pytest.mark.parametrize(
    "metadata",
    [
        {"icc": b"corrupt profile"},
        {"gamma": 0},
        {"srgb": 9},
        {"chroma": (0,) * 8},
    ],
)
def test_malformed_profile_is_rejected_before_loading_pixels(metadata, monkeypatch):
    item = source(**metadata)
    monkeypatch.setattr(Image.Image, "load", lambda *_: pytest.fail("raster allocated"))
    with pytest.raises(DocumentError, match="invalid_color_profile"):
        inspect_inputs((item,))


def test_profile_mode_mismatch_fails_closed():
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("LAB")).tobytes()
    with pytest.raises(DocumentError, match="invalid_or_unsupported_color_profile"):
        inspect_inputs((source(icc=profile),))
