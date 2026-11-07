import asyncio
import base64
import copy
import json
from io import BytesIO

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("PIL")
pytest.importorskip("pypdfium2")
Canvas = pytest.importorskip("reportlab.pdfgen.canvas").Canvas
TestClient = pytest.importorskip("fastapi.testclient").TestClient

from anonymizer.web.app import LocalBoundary, create_app  # noqa: E402


def source(text="Elvio Veltrani; Hb 12 g/dL; non febbre"):
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=(400, 300), invariant=1)
    canvas.drawString(40, 240, text)
    canvas.save()
    return buffer.getvalue()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("anonymizer.web.app.probe_ocr", lambda: "unavailable")
    with TestClient(
        create_app(local_only=True), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)
    ) as client:
        yield client


def post(client, operation, data=None, original=None):
    return client.post(
        "/api/" + operation,
        data=data or {},
        files=[("files", ("synthetic.pdf", original or source(), "application/pdf"))],
        headers={"Origin": "http://127.0.0.1"},
    )


def analyzed(client):
    response = post(client, "analyze", {"dpi": "72"})
    assert response.status_code == 200, response.text
    return response.json()


def edits_for(analysis, confirmed=True):
    pages = analysis["contract"]["manifest"]["pages"]
    return dict(
        decisions={
            m["id"]: dict(confirmed=confirmed, decision="apply", reason="")
            for p in pages
            for m in p["redactions"]
        },
        acknowledgments={p["page"]["page_id"]: list(range(len(p["warnings"]))) for p in pages},
        manual_masks=[],
        final_confirmation=False,
    )


def fields(analysis, review):
    return dict(
        contract=json.dumps(analysis["contract"]),
        signature=analysis["signature"],
        review=json.dumps(review),
    )


def ready(client, analysis, review):
    response = post(client, "preview", fields(analysis, review))
    assert response.status_code == 200, response.text
    preview = response.json()
    assert base64.b64decode(preview["redacted"]).startswith(b"\x89PNG")
    review["preview_digest"] = preview["preview_digest"]
    review["final_confirmation"] = True
    return preview


def test_local_mode_is_explicit_and_boundary_rejects_origins_hosts(client):
    with pytest.raises(ValueError, match="explicit_local"):
        create_app()
    assert client.get("/api/health").json()["ner"] == "disabled"
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.post("/api/analyze").status_code == 403
    assert client.post("/api/analyze", headers={"Origin": "http://evil.invalid"}).status_code == 403
    for host in ("evil.invalid", "[", "localhost/evil"):
        assert client.get("/api/health", headers={"Host": host}).status_code == 403


@pytest.mark.parametrize("location", [None, "trial-server"])
def test_health_reports_execution_location(monkeypatch, location):
    if location is None:
        monkeypatch.delenv("ANONYMIZER_EXECUTION_LOCATION", raising=False)
    else:
        monkeypatch.setenv("ANONYMIZER_EXECUTION_LOCATION", location)
    monkeypatch.setattr("anonymizer.web.app.probe_ocr", lambda: "ready")
    with TestClient(
        create_app(local_only=True), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)
    ) as client:
        state = client.get("/api/health").json()
        assert state["execution_location"] == (location or "this_computer")
        assert state["mode"] == "local_only"


def test_analyze_preview_review_export_png_pdf(client):
    from PIL import Image

    analysis = analyzed(client)
    assert all(value >= 0 for value in analysis["timings"].values())
    assert {"ingest", "render", "ocr", "ner", "proposals"} <= analysis["timings"].keys()
    review = edits_for(analysis)
    page = analysis["contract"]["manifest"]["pages"][0]
    review["manual_masks"] = [
        dict(
            id="manual-one",
            page_id=page["page"]["page_id"],
            polygon=[[5, 5], [20, 5], [20, 20], [5, 20]],
            confirmed=True,
            candidate_ids=[],
        )
    ]
    shown = ready(client, analysis, review)
    response = post(client, "export", dict(**fields(analysis, review), format="png"))
    assert response.status_code == 200, response.text
    with (
        Image.open(BytesIO(response.content)) as exported,
        Image.open(BytesIO(base64.b64decode(shown["redacted"]))) as preview,
    ):
        assert exported.tobytes() == preview.tobytes()
        assert exported.getpixel((10, 10)) == (0, 0, 0)
    assert float(response.headers["X-Export-Seconds"]) >= 0
    response = post(client, "export", dict(**fields(analysis, review), format="pdf"))
    assert response.status_code == 200 and response.content.startswith(b"%PDF")
    assert response.headers["cache-control"] == "no-store"


def test_contract_tampering_and_unknown_review_identity(client):
    analysis = analyzed(client)
    review = edits_for(analysis)
    for mutate in (
        lambda c: c["manifest"]["pages"][0]["redactions"].clear(),
        lambda c: c["manifest"]["sources"][0].update(sha256="a" * 64),
    ):
        changed = copy.deepcopy(analysis)
        mutate(changed["contract"])
        response = post(client, "preview", fields(changed, review))
        assert response.json()["error"] == "analysis_contract_signature_invalid"
    review["decisions"]["foreign-mask"] = dict(confirmed=True)
    assert (
        post(client, "preview", fields(analysis, review)).json()["error"]
        == "unknown_review_identity"
    )


def test_unconfirmed_and_stale_approval_cannot_export(client):
    analysis = analyzed(client)
    review = edits_for(analysis, confirmed=False)
    ready(client, analysis, review)
    assert (
        post(client, "export", fields(analysis, review)).json()["error"] == "unconfirmed_redaction"
    )
    review = edits_for(analysis)
    ready(client, analysis, review)
    first = next(iter(review["decisions"]))
    review["decisions"][first].update(decision="reject", reason="Synthetic review decision")
    assert (
        post(client, "export", fields(analysis, review)).json()["error"]
        == "review_changed_since_preview"
    )
    ready(client, analysis, review)
    response = post(client, "export", fields(analysis, review), original=source("Other source"))
    assert response.json()["error"] == "original_source_hash_or_order_mismatch"


def test_rejection_reason_out_of_bounds_and_manual_removal(client):
    analysis = analyzed(client)
    review = edits_for(analysis)
    first = next(iter(review["decisions"]))
    review["decisions"][first].update(decision="reject", reason="")
    assert (
        post(client, "preview", fields(analysis, review)).json()["error"]
        == "rejection_requires_reason"
    )
    review = edits_for(analysis)
    page_id = analysis["contract"]["manifest"]["pages"][0]["page"]["page_id"]
    review["manual_masks"] = [
        dict(
            id="manual",
            page_id=page_id,
            confirmed=True,
            candidate_ids=[],
            polygon=[[-1, 0], [20, 0], [20, 20], [-1, 20]],
        )
    ]
    assert (
        post(client, "preview", fields(analysis, review)).json()["error"]
        == "redaction_out_of_bounds"
    )
    review["manual_masks"] = []
    assert post(client, "preview", fields(analysis, review)).status_code == 200


def test_chunked_upload_limit_precedes_multipart_parser():
    called, messages = [], []

    async def app(scope, receive, send):
        called.append(True)

    incoming = iter(
        [
            dict(type="http.request", body=b"a" * 6, more_body=True),
            dict(type="http.request", body=b"b" * 6, more_body=False),
        ]
    )

    async def receive():
        return next(incoming)

    async def send(message):
        messages.append(message)

    scope = dict(
        type="http",
        method="POST",
        scheme="http",
        client=("127.0.0.1", 1),
        headers=[(b"host", b"localhost"), (b"origin", b"http://localhost")],
    )
    asyncio.run(LocalBoundary(app, max_body=10)(scope, receive, send))
    assert not called
    assert messages[0]["status"] == 413


def test_browser_number_serialization_preserves_opaque_signed_payload(client):
    analysis = analyzed(client)
    encoded = json.dumps(analysis)
    browser = json.loads(
        encoded,
        parse_float=lambda value: int(float(value)) if float(value).is_integer() else float(value),
    )
    assert browser["contract"]["payload"] == analysis["contract"]["payload"]
    review = edits_for(browser)
    assert post(client, "preview", fields(browser, review)).status_code == 200
    browser["contract"]["payload"] += " "
    assert (
        post(client, "preview", fields(browser, review)).json()["error"]
        == "analysis_contract_signature_invalid"
    )


def test_gate_busy_and_health_responsive_during_analysis(client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    import anonymizer.web.app as web

    entered, release = Event(), Event()
    real = web.analyze_documents

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return real(*args, **kwargs)

    monkeypatch.setattr(web, "analyze_documents", blocked)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(post, client, "analyze", {"dpi": "72"})
        assert entered.wait(10)
        try:
            assert client.get("/api/health").status_code == 200
            assert post(client, "analyze").status_code == 503
        finally:
            release.set()
        assert future.result().status_code == 200


def test_expired_contract_and_final_confirmation_required(client, monkeypatch):
    analysis = analyzed(client)
    review = edits_for(analysis)
    ready(client, analysis, review)
    review["final_confirmation"] = False
    assert (
        post(client, "export", fields(analysis, review)).json()["error"]
        == "final_review_confirmation_required"
    )
    monkeypatch.setattr(
        "anonymizer.web.review.time.time", lambda: analysis["contract"]["expires"] + 1
    )
    assert (
        post(client, "preview", fields(analysis, review)).json()["error"]
        == "analysis_contract_expired"
    )


def test_failed_ner_is_visible_and_blocks_analysis(monkeypatch):
    monkeypatch.setattr("anonymizer.web.app.probe_ocr", lambda: "unavailable")
    monkeypatch.setattr(
        "anonymizer.detect.ner.GLiNERDetector",
        lambda config: (_ for _ in ()).throw(RuntimeError("private source should not be logged")),
    )
    with TestClient(
        create_app(local_only=True, ner_config=object()),
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 1),
    ) as client:
        assert client.get("/api/health").json()["ner"] == "failed"
        assert post(client, "analyze").json()["error"] == "ner_model_load_failed"


def test_injected_model_threads_and_explicit_profile_must_agree(monkeypatch):
    from types import SimpleNamespace

    from anonymizer.performance import ExecutionProfile

    monkeypatch.setattr("anonymizer.web.app.probe_ocr", lambda: "ready")
    loaded = SimpleNamespace(config=SimpleNamespace(cpu_threads=2))
    with TestClient(
        create_app(local_only=True, ner=loaded),
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 50000),
    ) as client:
        assert client.get("/api/health").json()["performance"]["ner_threads"] == 2
    with pytest.raises(ValueError, match="loaded_ner_thread_override_conflict"):
        create_app(local_only=True, ner=loaded, ner_threads=3)
    profile = ExecutionProfile(4, 3, 1, True, "test")
    with pytest.raises(ValueError, match="execution_profile_thread_override_conflict"):
        create_app(local_only=True, ner=loaded, execution_profile=profile)



def test_gate_remains_busy_while_ner_consumer_is_running(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from types import SimpleNamespace

    from anonymizer.ner_model import NerAudit
    from anonymizer.performance import ExecutionProfile

    entered, release = Event(), Event()

    class BlockingNer:
        config = SimpleNamespace(runtime="onnx", cpu_threads=2)
        audit = NerAudit(reason="synthetic")

        def detect(self, text, page_id):
            entered.set()
            assert release.wait(5)
            return []

    monkeypatch.setattr("anonymizer.web.app.probe_ocr", lambda: "ready")
    app = create_app(
        local_only=True,
        ner=BlockingNer(),
        execution_profile=ExecutionProfile(3, 2, 1, True, "test"),
    )
    with TestClient(
        app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)
    ) as client, ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(post, client, "analyze", {"dpi": "72"})
        try:
            assert entered.wait(5)
            assert client.get("/api/health").status_code == 200
            assert post(client, "analyze").status_code == 503
        finally:
            release.set()
        assert future.result(timeout=5).status_code == 200
