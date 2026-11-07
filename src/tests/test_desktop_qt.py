import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
pytest.importorskip("PySide6.QtWebEngineWidgets")
if os.name != "nt" and hasattr(os, "geteuid") and os.geteuid() == 0:
    pytest.skip("Qt WebEngine sandbox requires a non-root test user", allow_module_level=True)

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt, QUrl  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWebEngineCore import QWebEngineDownloadRequest, QWebEngineSettings  # noqa: E402
from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from anonymizer.desktop_qt import (  # noqa: E402
    Downloads,
    OriginPolicy,
    ReviewPage,
    ReviewWindow,
    private_profile,
)


@pytest.fixture(scope="module")
def app():
    assert not os.environ.get("QTWEBENGINE_DISABLE_SANDBOX")
    instance = QApplication.instance() or QApplication(["anonymizer-offscreen-test"])
    yield instance


def dispose(page, profile, view=None):
    page.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    profile.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    if view:
        view.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def until(app, predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "Offscreen Qt operation timed out"
        app.processEvents()
        QTest.qWait(10)


def evaluate(app, page, script):
    result = []
    page.runJavaScript(script, 0, result.append)
    until(app, lambda: bool(result))
    return result[0]


def click(app, view, page, element):
    position = json.loads(
        evaluate(
            app,
            page,
            f"""JSON.stringify((()=>{{
      const r=document.getElementById('{element}').getBoundingClientRect();
      return {{x:r.x+r.width/2,y:r.y+r.height/2}};
    }})())""",
        )
    )
    QTest.mouseClick(
        view.focusProxy() or view,
        Qt.MouseButton.LeftButton,
        pos=QPoint(round(position["x"]), round(position["y"])),
    )


def test_exact_origin_policy_rejects_remote_files_ports_and_blob_spoofing():
    policy = OriginPolicy()
    assert policy.navigation_allowed("about:blank")
    policy.bind("http://127.0.0.1:54123")
    assert policy.request_allowed("http://127.0.0.1:54123/api/preview")
    assert policy.request_allowed("data:image/png;base64,synthetic")
    assert policy.navigation_allowed("blob:http://127.0.0.1:54123/synthetic")
    for url in (
        "https://example.invalid",
        "http://127.0.0.1:54124",
        "file:///C:/secret.txt",
        "blob:https://example.invalid/synthetic",
        "http://127.0.0.1:54123@evil.invalid",
        "data:text/html,untrusted",
        "about:blank",
        "http://localhost:54123",
    ):
        assert not policy.navigation_allowed(url)
        assert not policy.request_allowed(url)


def test_profile_and_page_do_not_persist_or_grant_clipboard_read(app):
    from PySide6.QtCore import qInstallMessageHandler

    messages = []
    previous = qInstallMessageHandler(lambda _kind, _context, message: messages.append(message))
    policy = OriginPolicy()
    profile = private_profile(None, policy)
    page = ReviewPage(profile, policy)
    try:
        assert profile.isOffTheRecord()
        assert (
            profile.persistentCookiesPolicy() == profile.PersistentCookiesPolicy.NoPersistentCookies
        )
        assert profile.httpCacheType() == profile.HttpCacheType.MemoryHttpCache
        settings = page.settings()
        attributes = QWebEngineSettings.WebAttribute
        assert settings.testAttribute(attributes.JavascriptCanAccessClipboard)
        assert not settings.testAttribute(attributes.JavascriptCanPaste)
        assert not settings.testAttribute(attributes.LocalStorageEnabled)
        assert not settings.testAttribute(attributes.LocalContentCanAccessFileUrls)
        assert page.createWindow(page.WebWindowType.WebBrowserTab) is None
    finally:
        dispose(page, profile)
        qInstallMessageHandler(previous)
    assert not any("profile" in value.lower() and "deleted" in value.lower() for value in messages)


def test_close_during_startup_stops_backend_and_ignores_late_ready(app, tmp_path):
    entered = threading.Event()
    instances = []

    class PendingBackend:
        def __init__(self, _resources, _session):
            self.stopped = threading.Event()
            self.starts = 0
            instances.append(self)

        def start(self):
            self.starts += 1
            return True

        def wait_ready(self, _cancelled):
            entered.set()
            assert self.stopped.wait(timeout=5)
            return "http://127.0.0.1:54123"

        def stop(self):
            self.stopped.set()

    window = ReviewWindow(None, tmp_path, backend_factory=PendingBackend)
    try:
        window.start_backend()
        assert entered.wait(timeout=5)
        window.shutdown()
        window.load_ready("http://127.0.0.1:54123")
        app.processEvents()
        assert window.cancelled.is_set() and not window.worker.is_alive()
        assert window.policy.origin is None
        window.start_backend()
        assert instances[0].starts == 1
    finally:
        window.shutdown()
        dispose(window.page, window.profile)
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_startup_download_message_percentage_error_and_retry(app, tmp_path, monkeypatch):
    from anonymizer.desktop import Resources
    from anonymizer.model_download import ModelDownloadError

    attempts, instances = [], []
    parent_thread = threading.get_ident()

    def provision(root, cancelled, progress):
        assert threading.get_ident() != parent_thread
        attempts.append(root)
        progress("Download modello: 50 / 100 MB", 50)
        if len(attempts) == 1:
            raise ModelDownloadError("Connessione assente. Riprova.")
        return tmp_path / "cached-model"

    class FakeBackend:
        def __init__(self, resources, session):
            self.resources, self.started = resources, False
            instances.append(self)

        def start(self):
            self.started = True
            assert self.resources.model == tmp_path / "cached-model"
            return True

        def wait_ready(self, cancelled):
            return "http://127.0.0.1:54123"

        def stop(self):
            pass

    monkeypatch.setattr("anonymizer.desktop_qt.ensure_model", provision)
    window = ReviewWindow(Resources(tmp_path), tmp_path, backend_factory=FakeBackend)
    try:
        loaded = []
        window.page.loadFinished.connect(loaded.append)
        window.load_progress("Download modello", 50)
        until(app, lambda: bool(loaded))
        until(
            app,
            lambda: evaluate(app, window.page, "document.querySelector('progress')?.value") == 50,
        )
        window.start_backend()
        until(app, lambda: not window.statusBar().isHidden() and not window.worker.is_alive())
        assert not instances[0].started
        window.retry.click()
        until(app, lambda: window.policy.origin is not None)
        assert len(attempts) == 2 and instances[-1].started
        assert window.statusBar().isHidden()
    finally:
        window.shutdown()
        dispose(window.page, window.profile)
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


class Callbacks:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self):
        for callback in self.callbacks:
            callback()


class Download:
    def __init__(self, url="blob:http://127.0.0.1:54123/synthetic"):
        self.location = QUrl(url)
        self.isFinishedChanged = Callbacks()
        self.accepted = self.cancelled = self.done = False
        self.status = QWebEngineDownloadRequest.DownloadState.DownloadInProgress

    def url(self):
        return self.location

    def downloadFileName(self):
        return "documento-oscurato.zip"

    def setDownloadDirectory(self, directory):
        self.directory = Path(directory)

    def setDownloadFileName(self, filename):
        self.filename = filename

    def accept(self):
        self.accepted = True

    def cancel(self):
        self.cancelled = self.done = True
        self.status = QWebEngineDownloadRequest.DownloadState.DownloadCancelled
        self.isFinishedChanged.emit()

    def isFinished(self):
        return self.done

    def state(self):
        return self.status

    def finish(self, state, payload=None):
        if payload is not None:
            (self.directory / self.filename).write_bytes(payload)
        self.status, self.done = state, True
        self.isFinishedChanged.emit()


def downloads(tmp_path, choose=None):
    policy = OriginPolicy()
    policy.bind("http://127.0.0.1:54123")
    target = tmp_path / "chosen output.zip"
    errors = []
    manager = Downloads(
        None,
        policy,
        tmp_path,
        choose=choose or (lambda _name: str(target)),
        notify=lambda: errors.append(True),
    )
    return manager, target, errors


def test_download_only_publishes_complete_file_at_explicit_path(tmp_path):
    manager, target, errors = downloads(tmp_path)
    request = Download()
    manager.requested(request)
    assert request.accepted and not target.exists()
    request.finish(
        QWebEngineDownloadRequest.DownloadState.DownloadCompleted, b"synthetic masked ZIP"
    )
    assert target.read_bytes() == b"synthetic masked ZIP"
    assert not manager.active and not request.directory.exists() and not errors


def test_download_denies_remote_picker_cancel_and_existing_file(tmp_path):
    manager, target, errors = downloads(tmp_path)
    remote = Download("https://example.invalid/document.zip")
    manager.requested(remote)
    assert remote.cancelled and not remote.accepted
    manager.choose = lambda _name: ""
    request = Download()
    manager.requested(request)
    assert request.cancelled and not target.exists()
    manager.choose = lambda _name: str(target)
    target.write_bytes(b"existing user file")
    request = Download()
    manager.requested(request)
    assert request.cancelled and target.read_bytes() == b"existing user file" and errors


def test_download_race_preserves_existing_file_and_cleans_staging(tmp_path):
    manager, target, errors = downloads(tmp_path)
    request = Download()
    manager.requested(request)
    target.write_bytes(b"created by another operation")
    request.finish(QWebEngineDownloadRequest.DownloadState.DownloadCompleted, b"new payload")
    assert target.read_bytes() == b"created by another operation"
    assert errors and not request.directory.exists()


@pytest.mark.parametrize("close", [False, True])
def test_interruption_and_close_leave_no_partial_output(tmp_path, close):
    manager, target, errors = downloads(tmp_path)
    request = Download()
    manager.requested(request)
    (request.directory / request.filename).write_bytes(b"partial synthetic data")
    if close:
        manager.close()
        assert request.cancelled and not errors
    else:
        request.finish(QWebEngineDownloadRequest.DownloadState.DownloadInterrupted)
        assert errors
    assert not target.exists() and not manager.active and not request.directory.exists()


def test_real_offscreen_blob_download_and_gesture_clipboard_without_read_access(app, tmp_path):
    content = b"""<!doctype html><html><body>
    <button id="copy" onclick="copyText()">Copy synthetic</button>
    <button id="read" onclick="readText()">Read synthetic</button>
    <button id="save" onclick="save()">Save synthetic</button><p id="status"></p>
    <script>
    async function copyText(){await new Promise(r=>setTimeout(r,30));
      try{await navigator.clipboard.writeText('synthetic masked text');
      document.getElementById('status').textContent='copied';}
      catch(e){document.getElementById('status').textContent='copy denied';}}
    async function readText(){try{await navigator.clipboard.readText();
      document.getElementById('status').textContent='read allowed';}
      catch(e){document.getElementById('status').textContent='read denied';}}
    function save(){const a=document.createElement('a');
      a.href=URL.createObjectURL(new Blob(['synthetic archive'],{type:'application/zip'}));
      a.download='documento-oscurato.zip';a.click();}
    </script></body></html>"""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *_args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        policy = OriginPolicy()
        url = f"http://127.0.0.1:{server.server_port}"
        policy.bind(url)
        view = QWebEngineView()
        profile = private_profile(view, policy)
        page = ReviewPage(profile, policy, view)
        view.setPage(page)
        manager, target, errors = downloads(tmp_path)
        manager.policy = policy
        profile.downloadRequested.connect(manager.requested)
        loaded = []
        page.loadFinished.connect(loaded.append)
        try:
            view.resize(640, 400)
            view.show()
            page.setUrl(QUrl(url))
            until(app, lambda: bool(loaded))
            assert loaded[-1]
            click(app, view, page, "copy")
            until(
                app,
                lambda: evaluate(app, page, "document.getElementById('status').textContent") != "",
            )
            assert app.clipboard().text() == "synthetic masked text"
            click(app, view, page, "read")
            until(
                app,
                lambda: (
                    evaluate(app, page, "document.getElementById('status').textContent")
                    == "read denied"
                ),
            )
            click(app, view, page, "save")
            until(app, target.exists)
            assert target.read_bytes() == b"synthetic archive" and not errors
        finally:
            manager.close()
            dispose(page, profile, view)
            server.shutdown()
            thread.join(timeout=2)
