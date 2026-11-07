import importlib.util
import json
import marshal
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from anonymizer.desktop import (
    Backend,
    DesktopError,
    Resources,
    backend_environment,
    run_backend,
)


@pytest.fixture
def resources(tmp_path):
    root = tmp_path / "Portable with spaces"
    for relative in (
        "runtime/pythonw.exe",
        "ocr/tesseract.exe",
        "ocr/tessdata/ita.traineddata",
        "models/gliner/anonymizer_model.json",
        "models/gliner/model.onnx",
        "models/gliner/gliner_config.json",
        "models/gliner/tokenizer.json",
        "models/gliner/tokenizer_config.json",
        "runtime/Lib/site-packages/anonymizer/web/static/index.html",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    return Resources(root)


def test_resources_are_relocatable_and_missing_files_block_spawn(resources, tmp_path, monkeypatch):
    resources.validate()
    assert resources.python.is_relative_to(resources.root)
    resources.ocr.unlink()
    monkeypatch.setattr(
        subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("must not spawn")
    )
    with pytest.raises(DesktopError, match="mancanti"):
        Backend(resources, tmp_path).start()


def test_backend_environment_is_offline_and_isolated(resources, tmp_path, monkeypatch):
    for key in (
        "PYTHONPATH",
        "PYTHONHOME",
        "VIRTUAL_ENV",
        "CONDA_PREFIX",
        "_PYI_PARENT_PROCESS_LEVEL",
    ):
        monkeypatch.setenv(key, "unwanted-development-path")
    monkeypatch.setenv("ANONYMIZER_EXECUTION_LOCATION", "other-server")
    environment = backend_environment(resources, tmp_path)
    assert not any(key in environment for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"))
    assert not any(key.startswith("_PYI_") for key in environment)
    assert environment["ANONYMIZER_EXECUTION_LOCATION"] == "this_computer"
    assert environment["ANONYMIZER_TESSERACT"] == str(resources.ocr)
    assert environment["HF_HUB_OFFLINE"] == environment["TRANSFORMERS_OFFLINE"] == "1"
    assert environment["TMP"] == str(tmp_path)


def test_close_before_start_prevents_late_spawn(resources, tmp_path, monkeypatch):
    backend = Backend(resources, tmp_path)
    backend.stop()
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("late spawn"))
    assert backend.start() is False


def test_start_passes_space_paths_as_argv_and_no_console(resources, tmp_path, monkeypatch):
    captured = {}

    def spawn(argv, **kwargs):
        captured.update(argv=argv, **kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(subprocess, "Popen", spawn)
    backend = Backend(resources, tmp_path)
    assert backend.start() is True
    assert captured["argv"][0] == str(resources.python)
    assert captured["argv"][1:5] == ["-I", "-B", "-m", "anonymizer.desktop"]
    assert str(resources.root) in captured["argv"]
    assert captured["stdout"] == captured["stderr"] == subprocess.DEVNULL


def test_readiness_requires_current_backend_and_health(resources, tmp_path):
    backend = Backend(resources, tmp_path)
    backend.process = SimpleNamespace(poll=lambda: None)
    (tmp_path / "backend.json").write_text(json.dumps({"port": 54123}))
    calls = []
    assert (
        backend.wait_ready(
            threading.Event(),
            probe=lambda port: calls.append(port) or True,
        )
        == "http://127.0.0.1:54123"
    )
    assert calls == [54123]
    backend.process = SimpleNamespace(poll=lambda: 1)
    with pytest.raises(DesktopError, match="non si avvia"):
        backend.wait_ready(threading.Event(), probe=lambda _port: True)


def test_readiness_cancellation_timeout_and_failed_model(resources, tmp_path):
    backend = Backend(resources, tmp_path)
    backend.process = SimpleNamespace(poll=lambda: None)
    cancelled = threading.Event()
    cancelled.set()
    assert backend.wait_ready(cancelled) is None
    with pytest.raises(DesktopError, match="troppo lungo"):
        backend.wait_ready(threading.Event(), timeout=0)
    (tmp_path / "backend.json").write_text(json.dumps({"port": 54123}))

    def fail(_port):
        raise DesktopError("modello guasto")

    with pytest.raises(DesktopError, match="modello guasto"):
        backend.wait_ready(threading.Event(), probe=fail)


def test_shutdown_signals_then_kills_only_owned_backend(resources, tmp_path):
    calls = []

    def wait(*, timeout):
        calls.append(("wait", timeout))
        if len(calls) == 1:
            raise subprocess.TimeoutExpired("owned-backend", timeout)

    backend = Backend(resources, tmp_path)
    backend.process = SimpleNamespace(wait=wait, kill=lambda: calls.append(("kill",)))
    backend.stop()
    assert (tmp_path / "stop").is_file()
    assert calls == [("wait", 5), ("kill",), ("wait", 5)]


def test_backend_prebinds_dynamic_loopback_socket_and_reuses_local_app(
    resources, tmp_path, monkeypatch
):
    from anonymizer.performance import ExecutionProfile

    profile = ExecutionProfile(6, 4, 1, True, "synthetic")
    monkeypatch.setattr("anonymizer.performance.choose_profile", lambda: profile)
    for key in ("OMP_NUM_THREADS", "OMP_THREAD_LIMIT", "MKL_NUM_THREADS"):
        monkeypatch.setenv(key, "1")
    monkeypatch.setenv("TOKENIZERS_PARALLELISM", "true")
    captured = {}

    def create_app(**kwargs):
        import os

        assert os.environ["TOKENIZERS_PARALLELISM"] == "false"

        assert all(
            os.environ[key] == "4"
            for key in ("OMP_NUM_THREADS", "OMP_THREAD_LIMIT", "MKL_NUM_THREADS")
        )
        captured.update(kwargs)
        return "same-shared-app"

    class Server:
        should_exit = False

        def __init__(self, config):
            captured["config"] = config

        def run(self, *, sockets):
            captured["address"] = sockets[0].getsockname()
            assert (
                json.loads((tmp_path / "backend.json").read_text())["port"]
                == captured["address"][1]
            )
            self.should_exit = True

    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        SimpleNamespace(
            Server=Server,
            Config=lambda app, **kwargs: dict(app=app, **kwargs),
        ),
    )
    monkeypatch.setitem(sys.modules, "anonymizer.web.app", SimpleNamespace(create_app=create_app))
    run_backend(resources, tmp_path)
    assert captured["address"][0] == "127.0.0.1"
    assert captured["address"][1] != 8765
    assert captured["local_only"] is True
    assert captured["ner_config"].runtime == "onnx"
    assert captured["ner_config"].cpu_threads == profile.ner_threads
    assert captured["execution_profile"] is profile
    assert captured["config"]["proxy_headers"] is False
    assert captured["config"]["access_log"] is False
    assert captured["config"]["workers"] == 1


def load_builder():
    path = Path(__file__).resolve().parents[2] / "tools/packaging/windows/build_portable.py"
    spec = importlib.util.spec_from_file_location("portable_builder_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(sys.platform != "win32", reason="Windows job lifecycle")
def test_launcher_job_close_terminates_its_child():
    path = Path(__file__).resolve().parents[2] / "tools/packaging/windows/launcher.py"
    spec = importlib.util.spec_from_file_location("portable_launcher_test", path)
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    job = launcher.ProcessJob()
    child = subprocess.Popen(
        [sys.executable, "-I", "-B", "-c", "import time; time.sleep(60)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        job.assign(child)
        assert child.poll() is None
        job.close()
        assert child.wait(timeout=5) is not None
    finally:
        job.close()
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def test_distribution_copy_excludes_editable_paths_but_keeps_metadata_and_licenses(
    tmp_path, monkeypatch
):
    pytest.importorskip("packaging")
    builder = load_builder()
    site = tmp_path / "development-site"
    relative_files = [
        "module/data.json",
        "module/native.dll",
        "module/__pycache__/x.pyc",
        "test.pth",
        "__editable__test.py",
        "test.dist-info/METADATA",
        "test.dist-info/direct_url.json",
        "test.dist-info/licenses/LICENSE.txt",
    ]
    for relative in relative_files:
        source = site / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("synthetic")
    distribution = SimpleNamespace(
        files=relative_files,
        locate_file=lambda path: site / path,
        version="1.0",
        metadata={},
    )
    monkeypatch.setattr(builder.sysconfig, "get_path", lambda _name: str(site))
    target = tmp_path / "bundle-site"
    inventory = builder.copy_distributions({"test": distribution}, target)
    assert (target / "module/native.dll").is_file()
    assert (target / "test.dist-info/METADATA").is_file()
    assert (target / "test.dist-info/licenses/LICENSE.txt").is_file()
    assert not list(target.rglob("*.pth"))
    assert not list(target.rglob("direct_url.json"))
    assert not list(target.rglob("__editable__*"))
    assert inventory[0]["license_files"] == 1


def test_portable_includes_all_shared_ui_assets_for_offline_use(tmp_path):
    pytest.importorskip("packaging")
    builder = load_builder()
    builder.copy_app(tmp_path)
    assets = Path("anonymizer/web/static")
    for source in (builder.SRC / assets).iterdir():
        if source.is_file():
            assert (tmp_path / assets / source.name).read_bytes() == source.read_bytes()


def test_precompiled_cache_is_relocatable_readonly_and_checks_source_hash(tmp_path, monkeypatch):
    pytest.importorskip("packaging")
    builder = load_builder()
    bundle = tmp_path / "build location"
    source = bundle / "runtime/Lib/site-packages/synthetic_module.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = 'synthetic'\ndef answer():\n    return value\n", encoding="utf-8")
    original_source = source.read_bytes()
    builder.precompile_runtime(bundle)
    cache = Path(importlib.util.cache_from_source(str(source)))
    data = cache.read_bytes()
    assert int.from_bytes(data[4:8], "little") == 3
    stored_code = marshal.loads(data[16:])
    assert not Path(stored_code.co_filename).is_absolute()
    assert str(tmp_path) not in stored_code.co_filename
    assert source.read_bytes() == original_source

    relocated = tmp_path / "portable moved elsewhere"
    bundle.rename(relocated)
    source = relocated / source.relative_to(bundle)
    before = {path.relative_to(relocated) for path in relocated.rglob("*")}

    def compile_source(*_args, **_kwargs):
        pytest.fail("source compilation instead of valid existing cache")

    loader = importlib.util.spec_from_file_location("synthetic_module", source).loader
    monkeypatch.setattr(loader, "source_to_code", compile_source)
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    namespace = {}
    exec(loader.get_code("synthetic_module"), namespace)
    assert namespace["answer"]() == "synthetic"
    assert {path.relative_to(relocated) for path in relocated.rglob("*")} == before
    source.write_text("value = 'changed'\n", encoding="utf-8")
    with pytest.raises(pytest.fail.Exception, match="source compilation"):
        loader.get_code("synthetic_module")
