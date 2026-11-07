from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from io import BytesIO
from threading import Event, current_thread
from threading import enumerate as threads
from types import SimpleNamespace

import pytest

Image = pytest.importorskip("PIL.Image")

from anonymizer.ingest import InputFile  # noqa: E402
from anonymizer.model import Kind, PageResult, Span, TextRegion  # noqa: E402
from anonymizer.ner_model import NerAudit  # noqa: E402
from anonymizer.performance import ExecutionProfile  # noqa: E402
from anonymizer.pipeline import analyze_documents  # noqa: E402
from anonymizer.visual_model import DocumentError  # noqa: E402

SERIAL = ExecutionProfile(3, 2, 1, False, "test")
OVERLAP = replace(SERIAL, overlap=True)


def inputs(count=5):
    buffer = BytesIO()
    with Image.new("RGB", (200, 80), "white") as image:
        image.save(buffer, "PNG")
    return tuple(InputFile(buffer.getvalue(), ".png", source_id=str(i)) for i in range(count))


def fixtures(monkeypatch, *, producer_error=None, consumer_error=None, blocked=False):
    import anonymizer.pipeline as pipeline

    state = SimpleNamespace(
        open=0, maximum_open=0, count=0, calls=[], render_threads=set(), ner_threads=set()
    )
    entered, release, third_closed = Event(), Event(), Event()

    class Bitmap:
        def __init__(self, index):
            self.index = index
            state.open += 1
            state.maximum_open = max(state.maximum_open, state.open)

        def close(self):
            state.open -= 1
            if self.index == 2:
                third_closed.set()

    def render(item):
        state.render_threads.add(current_thread().ident)
        return Bitmap(int(item.source.source_id))

    def ocr(image, item, config):
        assert config.cpu_threads == 1
        index = int(item.source.source_id)
        state.count += 1
        if index == producer_error:
            raise DocumentError("synthetic_producer_error")
        facility = "Clinica Vallerin s.r.l." if index == 0 else "Clinica Vallerin"
        text = facility + "\nMario Astravelli"
        return PageResult(
            item.page_id,
            item.source.source_id,
            index,
            text,
            regions=(
                TextRegion(0, len(facility), (0, 0, 195, 10)),
                TextRegion(len(facility) + 1, len(text), (0, 30, 150, 40)),
            ),
        )

    class Ner:
        audit = NerAudit(reason="synthetic")
        config = SimpleNamespace(runtime="onnx", cpu_threads=2)

        def detect(self, text, page_id):
            state.ner_threads.add(current_thread().ident)
            state.calls.append(page_id)
            if blocked and len(state.calls) == 1:
                entered.set()
                assert release.wait(5)
            if consumer_error is not None and len(state.calls) == consumer_error:
                raise DocumentError("synthetic_consumer_error")
            target = "Mario Astravelli"
            start = text.index(target)
            return [Span(page_id, start, start + len(target), Kind.PERSON, 3, "ner:test")]

    monkeypatch.setattr(pipeline, "render_page", render)
    monkeypatch.setattr(pipeline, "recognize", ocr)
    return Ner(), state, entered, release, third_closed


def signature(result):
    return [
        (
            page.page.text,
            [m.polygon for m in page.redactions],
            [(w.code, w.blocking) for w in page.warnings],
        )
        for page in result.manifest.pages
    ], [(s.start, s.end, s.kind, s.level, s.origin) for s in result.text_analysis.candidates]


def test_overlap_matches_serial_once_per_page_and_keeps_document_wide_rules(monkeypatch):
    sources = inputs()
    ner, state, *_ = fixtures(monkeypatch)
    serial = analyze_documents(sources, ner=ner, execution_profile=SERIAL)
    assert len(state.calls) == 5 and state.maximum_open == 1
    ner, state, *_ = fixtures(monkeypatch)
    parallel = analyze_documents(sources, ner=ner, execution_profile=OVERLAP)
    assert signature(parallel) == signature(serial)
    assert len(state.calls) == 5 and state.maximum_open == 1 and state.open == 0
    assert len(state.render_threads) == 1 and len(state.ner_threads) == 1
    assert state.render_threads.isdisjoint(state.ner_threads)
    assert any(s.origin == "context:facility_repeat" for s in parallel.text_analysis.candidates)
    assert parallel.timings["analysis_wall"] > 0 and parallel.timings["text_other"] >= 0
    assert parallel.timings["overlap_enabled"] == 1
    assert not any(t.name.startswith("anonymizer-ner") for t in threads())


def test_queue_backpressure_retains_no_bitmaps_and_at_most_one_waiting_page(monkeypatch):
    ner, state, entered, release, third_closed = fixtures(monkeypatch, blocked=True)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(analyze_documents, inputs(), ner=ner, execution_profile=OVERLAP)
        try:
            assert entered.wait(5) and third_closed.wait(5)
            assert state.count == 3 and state.open == 0
            assert state.maximum_open == 1 and not future.done()
        finally:
            release.set()
        assert len(future.result(timeout=5).manifest.pages) == 5


@pytest.mark.parametrize("producer_error,consumer_error", [(1, None), (None, 1), (None, 3)])
def test_producer_or_consumer_failure_closes_resources_and_joins_worker(
    monkeypatch, producer_error, consumer_error
):
    ner, state, *_ = fixtures(
        monkeypatch, producer_error=producer_error, consumer_error=consumer_error
    )
    with pytest.raises(DocumentError, match="synthetic_"):
        analyze_documents(inputs(), ner=ner, execution_profile=OVERLAP)
    assert state.open == 0 and state.maximum_open == 1
    assert not any(t.name.startswith("anonymizer-ner") for t in threads())


def test_profile_mismatch_and_expired_deadline_fail_without_partial_result(monkeypatch):
    ner, state, *_ = fixtures(monkeypatch)
    with pytest.raises(DocumentError, match="threads_mismatch"):
        analyze_documents(inputs(), ner=ner, execution_profile=replace(SERIAL, ner_threads=1))
    with pytest.raises(DocumentError, match="deadline_exceeded"):
        analyze_documents(inputs(), ner=ner, execution_profile=OVERLAP, deadline_seconds=1e-9)
    assert state.open == 0
