import hashlib
import io
import json
import threading
import zipfile

import pytest

from anonymizer.model_download import (
    FILES,
    DownloadCancelled,
    ModelDownloadError,
    SecureRedirect,
    ensure_model,
    read_spec,
)


def fixture_model(tmp_path):
    bundle, cache = tmp_path / "bundle", tmp_path / "cache"
    bundle.mkdir()
    contents = {name: ("synthetic model " + name).encode() for name in FILES}
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        for name, value in contents.items():
            archive.writestr(name, value)
    payload = data.getvalue()
    spec = {
        "format": "anonymizer-model-download-v1",
        "url": "https://example.org/model.zip",
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "files": {
            name: {"size": len(value), "sha256": hashlib.sha256(value).hexdigest()}
            for name, value in contents.items()
        },
    }
    (bundle / "model-download.json").write_text(json.dumps(spec), encoding="utf-8")
    return bundle, cache, contents, payload, spec


class Response(io.BytesIO):
    def __init__(self, payload, status=200, headers=None):
        super().__init__(payload)
        self.status, self.headers = status, headers or {}


class Opener:
    def __init__(self, payload, *, resume=True):
        self.payload, self.resume, self.requests = payload, resume, []

    def open(self, request, timeout):
        self.requests.append(request)
        assert timeout == 20
        assert request.full_url == "https://example.org/model.zip"
        assert not request.has_header("Authorization") and request.data is None
        offset = (
            int(request.get_header("Range").split("=")[1].split("-")[0])
            if request.has_header("Range")
            else 0
        )
        if offset and self.resume:
            return Response(
                self.payload[offset:],
                206,
                {"Content-Range": f"bytes {offset}-{len(self.payload) - 1}/{len(self.payload)}"},
            )
        return Response(self.payload)


def test_first_start_download_and_second_start_offline(tmp_path):
    bundle, cache, contents, payload, spec = fixture_model(tmp_path)
    opener, messages = Opener(payload), []
    target = ensure_model(
        bundle, threading.Event(), lambda *m: messages.append(m), cache=cache, opener=opener
    )
    assert {p.name: p.read_bytes() for p in target.iterdir()} == contents
    assert any(percent == 100 for _, percent in messages)
    assert not list(cache.glob("*.part"))
    assert (
        ensure_model(bundle, threading.Event(), lambda *_: None, cache=cache, opener=opener)
        == target
    )
    assert len(opener.requests) == 1
    assert target.name == spec["sha256"]


def test_bundled_model_is_reused_and_corrupt_cache_is_repaired(tmp_path):
    bundle, cache, contents, payload, _ = fixture_model(tmp_path)
    model = bundle / "models/gliner"
    model.mkdir(parents=True)
    for name, data in contents.items():
        (model / name).write_bytes(data)
    opener = Opener(payload)
    assert (
        ensure_model(bundle, threading.Event(), lambda *_: None, cache=cache, opener=opener)
        == model
    )
    assert not opener.requests
    (model / "model.onnx").write_bytes(b"corrupt")
    target = ensure_model(bundle, threading.Event(), lambda *_: None, cache=cache, opener=opener)
    (target / "model.onnx").write_bytes(b"corrupt")
    assert (
        ensure_model(bundle, threading.Event(), lambda *_: None, cache=cache, opener=opener)
        == target
    )
    assert len(opener.requests) == 2
    assert (target / "model.onnx").read_bytes() == contents["model.onnx"]


@pytest.mark.parametrize("supports_range", [True, False])
def test_interrupted_download_resumes_or_restarts_for_nonrange_server(tmp_path, supports_range):
    bundle, cache, _, payload, spec = fixture_model(tmp_path)
    with pytest.raises(ModelDownloadError, match="interrotto"):
        ensure_model(
            bundle, threading.Event(), lambda *_: None, cache=cache, opener=Opener(payload[:100])
        )
    part = cache / (spec["sha256"] + ".zip.part")
    assert part.read_bytes() == payload[:100]
    opener = Opener(payload, resume=supports_range)
    target = ensure_model(bundle, threading.Event(), lambda *_: None, cache=cache, opener=opener)
    assert opener.requests[0].get_header("Range") == "bytes=100-"
    assert (target / "model.onnx").exists() and not part.exists()


def test_wrong_archive_digest_never_installs_and_allows_clean_retry(tmp_path):
    bundle, cache, _, payload, spec = fixture_model(tmp_path)
    bad = b"X" + payload[1:]
    with pytest.raises(ModelDownloadError, match="integrità"):
        ensure_model(bundle, threading.Event(), lambda *_: None, cache=cache, opener=Opener(bad))
    assert not (cache / spec["sha256"]).exists()
    assert not list(cache.glob("*.part"))


def test_malicious_zip_member_never_writes_outside_staging(tmp_path):
    bundle, cache, _, _, spec = fixture_model(tmp_path)
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("../escaped.txt", "bad")
    payload = data.getvalue()
    spec.update(size=len(payload), sha256=hashlib.sha256(payload).hexdigest())
    (bundle / "model-download.json").write_text(json.dumps(spec), encoding="utf-8")
    with pytest.raises(ModelDownloadError, match="pacchetto"):
        ensure_model(
            bundle, threading.Event(), lambda *_: None, cache=cache, opener=Opener(payload)
        )
    assert not list(tmp_path.rglob("escaped.txt"))
    assert not (cache / spec["sha256"]).exists()


def test_cancellation_and_no_space_do_not_start_network(tmp_path, monkeypatch):
    from types import SimpleNamespace

    bundle, cache, _, payload, _ = fixture_model(tmp_path)
    cancelled, opener = threading.Event(), Opener(payload)
    cancelled.set()
    with pytest.raises(DownloadCancelled):
        ensure_model(bundle, cancelled, lambda *_: None, cache=cache, opener=opener)
    cancelled.clear()
    monkeypatch.setattr(
        "anonymizer.model_download.shutil.disk_usage", lambda _: SimpleNamespace(free=0)
    )
    with pytest.raises(ModelDownloadError, match="Spazio"):
        ensure_model(bundle, cancelled, lambda *_: None, cache=cache, opener=opener)
    assert not opener.requests


@pytest.mark.parametrize(
    "url",
    ["http://example.org/model.zip", "file:///model.zip", "https://u:p@example.org/model.zip"],
)
def test_manifest_and_redirects_require_https_without_credentials(tmp_path, url):
    bundle, _, _, _, spec = fixture_model(tmp_path)
    spec["url"] = url
    (bundle / "model-download.json").write_text(json.dumps(spec), encoding="utf-8")
    with pytest.raises(ModelDownloadError):
        read_spec(bundle / "model-download.json")
    with pytest.raises(ModelDownloadError):
        SecureRedirect().redirect_request(None, None, 302, "", {}, url)


def test_two_windows_share_one_download(tmp_path):
    bundle, cache, _, payload, _ = fixture_model(tmp_path)
    entered, release = threading.Event(), threading.Event()
    opener = Opener(payload)
    original = opener.open

    def open_once(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    opener.open = open_once
    results, errors = [], []

    def start():
        try:
            results.append(
                ensure_model(bundle, threading.Event(), lambda *_: None, cache=cache, opener=opener)
            )
        except Exception as error:
            errors.append(error)

    first, second = threading.Thread(target=start), threading.Thread(target=start)
    first.start()
    assert entered.wait(5)
    second.start()
    release.set()
    first.join(5)
    second.join(5)
    assert not first.is_alive() and not second.is_alive() and not errors
    assert len(results) == 2 and results[0] == results[1]
    assert len(opener.requests) == 1


def direct_model(tmp_path):
    bundle, cache, contents, _, spec = fixture_model(tmp_path)
    payload = contents["model.onnx"]
    spec.update(format="anonymizer-model-onnx-v1", **spec["files"]["model.onnx"])
    (bundle / "model-download.json").write_text(json.dumps(spec), encoding="utf-8")
    support = bundle / "models/gliner"
    support.mkdir(parents=True)
    for name, value in contents.items():
        if name != "model.onnx":
            (support / name).write_bytes(value)
    return bundle, cache, contents, payload, spec


def test_direct_onnx_download_uses_local_support_and_reuses_offline(tmp_path):
    bundle, cache, contents, payload, _ = direct_model(tmp_path)
    opener = Opener(payload)
    target = ensure_model(bundle, threading.Event(), lambda *_: None, cache=cache, opener=opener)
    assert {p.name: p.read_bytes() for p in target.iterdir()} == contents
    assert not (bundle / "models/gliner/model.onnx").exists()
    assert (
        ensure_model(bundle, threading.Event(), lambda *_: None, cache=cache, opener=opener)
        == target
    )
    assert len(opener.requests) == 1


def test_direct_onnx_interrupted_transfer_resumes(tmp_path):
    bundle, cache, contents, payload, _ = direct_model(tmp_path)
    with pytest.raises(ModelDownloadError, match="interrotto"):
        ensure_model(
            bundle, threading.Event(), lambda *_: None, cache=cache, opener=Opener(payload[:5])
        )
    opener = Opener(payload)
    target = ensure_model(bundle, threading.Event(), lambda *_: None, cache=cache, opener=opener)
    assert opener.requests[0].get_header("Range") == "bytes=5-"
    assert (target / "model.onnx").read_bytes() == contents["model.onnx"]


def test_direct_onnx_rejects_corrupt_support_before_network(tmp_path):
    bundle, cache, _, payload, _ = direct_model(tmp_path)
    (bundle / "models/gliner/tokenizer.json").write_bytes(b"corrupt")
    opener = Opener(payload)
    with pytest.raises(ModelDownloadError, match="Reinstalla"):
        ensure_model(bundle, threading.Event(), lambda *_: None, cache=cache, opener=opener)
    assert not opener.requests


def test_direct_onnx_rejects_inconsistent_digest(tmp_path):
    bundle, _, _, _, spec = direct_model(tmp_path)
    spec["sha256"] = "0" * 64
    (bundle / "model-download.json").write_text(json.dumps(spec), encoding="utf-8")
    with pytest.raises(ModelDownloadError):
        read_spec(bundle / "model-download.json")
