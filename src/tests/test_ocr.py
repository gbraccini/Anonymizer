import os
import subprocess
from io import BytesIO

import pytest

from anonymizer.ingest import InputFile, inspect_inputs
from anonymizer.model import Kind, MergedSpan, PageResult, Span, TextRegion
from anonymizer.ocr import OCRConfig, from_tsv, recognize
from anonymizer.redact import propose_redactions
from anonymizer.visual_model import DocumentError, SourcePageGeometry

Image = pytest.importorskip("PIL.Image")
ImageDraw = pytest.importorskip("PIL.ImageDraw")
ImageFont = pytest.importorskip("PIL.ImageFont")


def item():
    buffer = BytesIO()
    Image.new("RGB", (800, 200), "white").save(buffer, "PNG")
    return inspect_inputs((InputFile(buffer.getvalue(), ".png"),))[1][0]


def tsv():
    return {
        "text": ["😀", "Elvio", "Veltrani", "Hb", "12", "g/dL"],
        "left": [2, 30, 120, 10, 80, 130],
        "top": [2, 2, 2, 60, 60, 60],
        "width": [20, 60, 100, 30, 30, 60],
        "height": [40] * 6,
        "conf": [99, 90, 40, 99, 99, 99],
        "block_num": [1] * 6,
        "par_num": [1] * 6,
        "line_num": [1, 1, 1, 2, 2, 2],
    }


def test_tsv_word_offsets_boxes_unicode_and_uncertain_reading_order():
    page = from_tsv(tsv(), item())
    assert page.text == "😀 Elvio Veltrani\nHb 12 g/dL"
    assert [page.text[region.start : region.end] for region in page.regions] == tsv()["text"]
    assert page.regions[1].start == 2
    assert page.regions[2].box == (120, 2, 220, 42)
    assert any(
        warning.code == "low_ocr_confidence" and warning.blocking for warning in page.warnings
    )


def test_empty_and_malformed_tsv_are_visible_failures():
    empty = {key: [] for key in tsv()}
    assert any(
        warning.code == "no_readable_text_manual_review"
        for warning in from_tsv(empty, item()).warnings
    )
    data = tsv()
    data["left"][0] = -1
    with pytest.raises(DocumentError):
        from_tsv(data, item())


def test_tesseract_timeout_and_process_errors_are_controlled(monkeypatch):
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(
            1, ["synthetic"], stderr="Synthetic private data must not leak"
        )

    monkeypatch.setenv("ANONYMIZER_TESSERACT", "synthetic-executable")
    monkeypatch.setattr("anonymizer.ocr.subprocess.run", fail)
    with pytest.raises(DocumentError, match="ocr_unavailable_failed_or_timeout") as error:
        recognize(Image.new("RGB", (10, 10)), item())
    assert "private" not in str(error.value)


def test_multiline_span_generates_separate_regions_without_masking_between_lines():
    geometry = SourcePageGeometry(400, 200, 400, 200, 72)
    page = PageResult(
        "p",
        "s",
        0,
        "Elvio\nVeltrani",
        regions=(
            TextRegion(0, 5, (10, 10, 60, 30)),
            TextRegion(6, 14, (10, 100, 100, 120)),
        ),
    )
    span = Span("p", 0, 14, Kind.PERSON, 1, "test")
    merged = MergedSpan("p", 0, 14, Kind.PERSON, (span,))
    masks, warnings, required = propose_redactions(page, [merged], geometry)
    assert len(masks) == 2 and not warnings and required == (merged.id,)
    assert max(point[1] for point in masks[0].polygon) < min(point[1] for point in masks[1].polygon)


@pytest.mark.skipif(
    not os.getenv("ANONYMIZER_TESSERACT"), reason="Explicit local Tesseract not configured"
)
def test_real_italian_ocr_has_readable_words_and_source_boxes():
    font = None
    for name in ("DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf"):
        try:
            font = ImageFont.truetype(name, 40)
            break
        except OSError:
            pass
    if font is None:
        pytest.skip("No test font available")
    image = Image.new("RGB", (800, 200), "white")
    ImageDraw.Draw(image).text((30, 40), "Elvio Veltrani", font=font, fill="black")
    page = recognize(image, item(), OCRConfig(language="ita", psm=6))
    assert "Elvio" in page.text and "Veltrani" in page.text
    assert all(region.box is not None for region in page.regions)


@pytest.mark.skipif(
    not os.getenv("ANONYMIZER_TESSERACT") or not os.getenv("ANONYMIZER_TESSDATA"),
    reason="Explicit local Tesseract and tessdata not configured",
)
def test_real_tessdata_path_with_spaces(tmp_path, monkeypatch):
    import shutil
    from pathlib import Path

    directory = tmp_path / "tessdata with spaces"
    directory.mkdir()
    shutil.copy2(Path(os.environ["ANONYMIZER_TESSDATA"]) / "ita.traineddata", directory)
    monkeypatch.setenv("ANONYMIZER_TESSDATA", str(directory))
    image = Image.new("RGB", (800, 200), "white")
    data = recognize(image, item(), OCRConfig(language="ita", psm=6))
    assert data.text == ""


def test_timeout_cleans_input_temp_and_keeps_environment_unchanged(monkeypatch):
    from pathlib import Path

    original_prefix = os.environ.get("TESSDATA_PREFIX")
    paths = []

    def timeout(command, **kwargs):
        paths.append(Path(command[1]))
        assert paths[0].exists()
        assert kwargs["env"] is not os.environ
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setenv("ANONYMIZER_TESSERACT", "synthetic-executable")
    monkeypatch.setattr("anonymizer.ocr.subprocess.run", timeout)
    with pytest.raises(DocumentError):
        recognize(Image.new("RGB", (10, 10)), item())
    assert not paths[0].exists()
    assert os.environ.get("TESSDATA_PREFIX") == original_prefix


def test_raw_tsv_quotes_are_literal_word_characters(monkeypatch):
    raw = (
        "left\ttop\twidth\theight\tconf\tblock_num\tpar_num\tline_num\ttext\n"
        '10\t10\t50\t20\t99\t1\t1\t1\t"Elvio\n'
        "70\t10\t90\t20\t99\t1\t1\t1\tVeltrani\n"
    )
    monkeypatch.setenv("ANONYMIZER_TESSERACT", "synthetic-executable")
    monkeypatch.setattr(
        "anonymizer.ocr.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, stdout=raw.encode()),
    )
    page = recognize(Image.new("RGB", (800, 200)), item())
    assert page.text == '"Elvio Veltrani'
    assert len(page.regions) == 2


@pytest.mark.parametrize("threads", [0, 33, True, 1.5])
def test_invalid_ocr_thread_budget_is_rejected(threads):
    with pytest.raises(DocumentError, match="invalid_ocr_thread_count"):
        OCRConfig(cpu_threads=threads)


def test_ocr_thread_budget_is_child_only_and_preserves_timeout(monkeypatch):
    monkeypatch.setenv("ANONYMIZER_TESSERACT", "synthetic-executable")
    monkeypatch.setenv("OMP_THREAD_LIMIT", "9")
    monkeypatch.setenv("OMP_NUM_THREADS", "9")
    captured = {}

    def run(command, **kwargs):
        captured.update(kwargs)
        raw = b"text\tleft\ttop\twidth\theight\tconf\tblock_num\tpar_num\tline_num\n"
        return subprocess.CompletedProcess(command, 0, stdout=raw)

    monkeypatch.setattr("anonymizer.ocr.subprocess.run", run)
    with Image.new("RGB", (10, 10)) as image:
        recognize(image, item(), OCRConfig(cpu_threads=1, timeout=3))
    assert captured["env"]["OMP_THREAD_LIMIT"] == "1"
    assert captured["env"]["OMP_NUM_THREADS"] == "1"
    assert 0 < captured["timeout"] <= 3
    assert os.environ["OMP_THREAD_LIMIT"] == os.environ["OMP_NUM_THREADS"] == "9"


@pytest.mark.parametrize("width,scale", [(800, 2), (1600, 2), (1601, 1)])
def test_small_images_are_enlarged_with_boxes_mapped_to_original(monkeypatch, width, scale):
    from dataclasses import replace

    monkeypatch.setenv("ANONYMIZER_TESSERACT", "synthetic-executable")

    def run(command, **kwargs):
        with Image.open(command[1]) as saved:
            assert saved.size == (width * scale, 200 * scale)
        raw = "left\ttop\twidth\theight\tconf\tblock_num\tpar_num\tline_num\ttext\n"
        raw += f"{10 * scale}\t{20 * scale}\t{80 * scale}\t{12 * scale}\t99\t1\t1\t1\t3201234567\n"
        return subprocess.CompletedProcess(command, 0, stdout=raw.encode())

    monkeypatch.setattr("anonymizer.ocr.subprocess.run", run)
    original = item()
    original = replace(original, geometry=replace(original.geometry, width=width))
    with Image.new("RGB", (width, 200)) as image:
        page = recognize(image, original)
        assert image.size == (width, 200)
        assert image.getpixel((0, 0)) == (0, 0, 0)
    assert page.regions[0].box == (10, 20, 90, 32)
    assert page.text == "3201234567"
    span = Span(page.page_id, 0, 10, Kind.PHONE, 1, "test")
    merged = MergedSpan(page.page_id, 0, 10, Kind.PHONE, (span,))
    masks, _, _ = propose_redactions(page, [merged], original.geometry)
    assert len(masks) == 1
    xs, ys = zip(*masks[0].polygon, strict=True)
    assert min(xs) <= 10 and max(xs) >= 90 and max(xs) < 100
    assert min(ys) <= 20 and max(ys) >= 32 and max(ys) < 40


def identity_retry_pages():
    import re

    def page(text):
        regions = tuple(
            TextRegion(m.start(), m.end(), (m.start() * 2, 10, m.end() * 2, 20))
            for m in re.finditer(r"\S+", text)
        )
        return PageResult("p", "s", 0, text, regions=regions)

    primary = page("REPUBBLICA ITALIANA MINISTERO DELL'INTERNO")
    secondary = page(
        "CARTA DI IDENTITA\nCOGNOME: VALLERIN\nNOME: LUCIA\nDATA DI NASCITA: 03/11/1980"
    )
    return primary, secondary


def test_identity_retry_has_one_shared_timeout_and_never_changes_source_pixels(monkeypatch):
    from anonymizer import ocr

    primary, secondary = identity_retry_pages()
    monkeypatch.setattr(ocr, "_identity_retry_needed", lambda page: page is primary)
    calls = []

    def once(image, item, config, **kwargs):
        calls.append(config)
        assert image.mode == ("RGB" if len(calls) == 1 else "L")
        return primary if len(calls) == 1 else secondary

    clock = iter((10.0, 12.0))
    monkeypatch.setattr(ocr, "perf_counter", lambda: next(clock))
    monkeypatch.setattr(ocr, "_recognize_once", once)
    with Image.new("RGB", (800, 200), (80, 160, 210)) as image:
        before = image.tobytes()
        result = recognize(image, item(), OCRConfig(timeout=10, cpu_threads=2))
        assert image.tobytes() == before
    assert len(calls) == 2
    assert calls[1].timeout == 8 and calls[1].cpu_threads == 2
    assert result.extraction_mode == "ocr+identity_fallback"
    assert any(w.code == "identity_ocr_fallback_requires_review" for w in result.warnings)


def test_identity_retry_preserves_primary_identifier_or_rejects_secondary():
    from dataclasses import replace

    from anonymizer.ocr import _accept_identity_retry

    primary, secondary = identity_retry_pages()
    primary = replace(primary, text=primary.text + "\nTelefono: 3201234567", regions=())
    assert not _accept_identity_retry(primary, secondary)
    secondary = replace(secondary, text=secondary.text + "\nTelefono: 3201234567", regions=())
    assert _accept_identity_retry(primary, secondary)


def test_retry_acceptance_uses_physical_coverage_not_transcription_or_other_occurrence():
    from dataclasses import replace

    from anonymizer.ocr import _accept_identity_retry, _retain_primary_geometry

    primary_text = "Luogo nascita: Valleverde"
    primary_start = primary_text.index("Valleverde")
    primary = PageResult(
        "p",
        "s",
        0,
        primary_text,
        regions=(
            TextRegion(0, primary_start, (10, 10, 110, 25)),
            TextRegion(primary_start, len(primary_text), (115, 10, 195, 25)),
        ),
    )
    secondary_text = "CARTA DI IDENTITA\nLUOGO DI NASCITA: Vallevérde"
    label = secondary_text.index("LUOGO")
    start = secondary_text.index("Vallev")
    secondary = PageResult(
        "p",
        "s",
        0,
        secondary_text,
        regions=(
            TextRegion(0, 16, (10, 40, 160, 55)),
            TextRegion(label, start, (10, 10, 110, 25)),
            TextRegion(start, len(secondary_text), (115, 10, 195, 25)),
        ),
    )
    geometry = SourcePageGeometry(400, 200, 400, 200, 72)
    assert _accept_identity_retry(primary, secondary, geometry)
    relocated = replace(
        secondary,
        text=secondary.text.replace("Vallevérde", "Valleverde"),
        regions=(*secondary.regions[:-1], replace(secondary.regions[-1], box=(250, 100, 330, 115))),
    )
    assert not _accept_identity_retry(primary, relocated, geometry)
    uncertain = replace(
        primary,
        regions=(*primary.regions[:-1], replace(primary.regions[-1], box=(115, 8, 195, 29))),
    )
    assert not _accept_identity_retry(uncertain, secondary, geometry)
    preserved = _retain_primary_geometry(uncertain, secondary)
    assert _accept_identity_retry(uncertain, preserved, geometry)
    assert preserved.text == secondary.text
    assert preserved.regions[-1].box == uncertain.regions[-1].box
    assert not _accept_identity_retry(
        uncertain, _retain_primary_geometry(uncertain, relocated), geometry
    )


def test_identity_retry_merge_keeps_only_nonoverlapping_primary_regions():
    from anonymizer.ocr import _merge_identity_retry

    primary = PageResult(
        "p",
        "s",
        0,
        "old extra",
        regions=(
            TextRegion(0, 3, (10, 10, 30, 20)),
            TextRegion(4, 9, (100, 80, 150, 90)),
        ),
    )
    secondary = PageResult("p", "s", 0, "new", regions=(TextRegion(0, 3, (9, 9, 31, 21)),))
    merged = _merge_identity_retry(primary, secondary)
    assert merged.text == "new\nextra"
    assert len(merged.regions) == 2
    assert merged.text[merged.regions[1].start : merged.regions[1].end] == "extra"


def test_normal_clinical_report_does_not_retry(monkeypatch):
    from anonymizer import ocr

    calls = []
    page = PageResult("p", "s", 0, "Emoglobina 12 g/dL. Terapia 2 compresse.")
    monkeypatch.setattr(ocr, "_recognize_once", lambda *args: calls.append(args) or page)
    with Image.new("RGB", (800, 200)) as image:
        assert recognize(image, item()) is page
    assert len(calls) == 1


def test_retry_budget_exhaustion_preserves_primary_without_second_process(monkeypatch):
    from anonymizer import ocr

    primary, _ = identity_retry_pages()
    calls = []
    monkeypatch.setattr(ocr, "_recognize_once", lambda *args: calls.append(args) or primary)
    clock = iter((10.0, 16.0))
    monkeypatch.setattr(ocr, "perf_counter", lambda: next(clock))
    with Image.new("RGB", (800, 200)) as image:
        result = recognize(image, item(), OCRConfig(timeout=5))
    assert result.text == primary.text
    assert any(w.code == "identity_ocr_retry_inconclusive" for w in result.warnings)
    assert len(calls) == 1


def test_normal_report_name_and_birth_labels_do_not_trigger_retry(monkeypatch):
    from anonymizer import ocr

    calls = []
    page = PageResult(
        "p", "s", 0, "Cognome: Vallerin\nNome: Lucia\nData nascita: 03/11/1980\nHb 12 g/dL"
    )
    monkeypatch.setattr(ocr, "_recognize_once", lambda *args: calls.append(args) or page)
    with Image.new("RGB", (800, 200)) as image:
        assert recognize(image, item()) is page
    assert len(calls) == 1


def test_obstetric_narrative_is_not_identity_retry_evidence():
    from anonymizer.ocr import _identity_retry_needed

    page = PageResult(
        "p", "s", 0, "Gravidanza in atto. Madre e padre informati. Data nascita prevista."
    )
    assert not _identity_retry_needed(page)


def test_partial_mrz_retry_requires_document_prefix_and_numeric_sex_structure():
    from anonymizer.ocr import _identity_retry_needed

    page = PageResult(
        "p",
        "s",
        0,
        "A<AAAO00OOOOOOO<<<<<<<<<<<<<<<<<<\n9001010F3001010AAA<<<<<<<<<<<\nOCR missing name",
    )
    assert _identity_retry_needed(page)
    assert not _identity_retry_needed(
        PageResult("p", "s", 0, "Esame A<30\nValore F 12\nRisultato < 90")
    )
