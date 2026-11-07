import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "name",
    [
        "torch/lib/dnnl.lib",
        "torch/include/ATen/test.h",
        "PySide6/resources/qtwebengine_devtools_resources.debug.pak",
    ],
)
def test_development_resources_are_excluded(name):
    assert builder.development_resource("runtime/Lib/site-packages/" + name)


@pytest.mark.parametrize(
    "name",
    [
        "torch/lib/torch_cpu.dll",
        "cv2/cv2.pyd",
        "numpy/__pycache__/__init__.cpython-312.pyc",
        "PySide6/resources/qtwebengine_resources.pak",
        "torch-2.7.1.dist-info/licenses/LICENSE",
    ],
)
def test_runtime_resources_and_licenses_are_retained(name):
    assert not builder.development_resource("runtime/Lib/site-packages/" + name)


SPEC = importlib.util.spec_from_file_location(
    "build_installer", Path(__file__).parents[2] / "tools/packaging/windows/build_installer.py"
)
builder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = builder
SPEC.loader.exec_module(builder)


@pytest.fixture(autouse=True)
def version_counter(tmp_path, monkeypatch):
    path = tmp_path / "version.json"
    path.write_text('{"base":"0.1.0","build":1}', encoding="utf-8")
    monkeypatch.setattr(builder, "VERSION_FILE", path)
    return path


def bundle(tmp_path):
    root = tmp_path / "portable with spaces"
    inventory = {}
    for name in builder.REQUIRED:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("synthetic " + name).encode())
        inventory[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (root / "bundle.json").write_text(
        json.dumps({"format": "anonymizer-windows-portable-v1", "files": inventory}),
        encoding="utf-8",
    )
    return root, inventory


@pytest.mark.parametrize(
    "unsafe",
    [
        "../secret.pdf",
        "/secret.pdf",
        "C:/secret.pdf",
        "ocr/../secret.pdf",
        "ocr\\secret.pdf",
        "ocr/file:stream",
        "ocr/*.pdf",
        "ocr/secret;flag.pdf",
        "ocr/secret\nfile",
        "ocr/NUL.txt",
        "ocr/trailing.",
        "ocr/{userdocs}.pdf",
        "ocr//duplicate.pdf",
    ],
)
def test_inventory_rejects_unsafe_windows_paths(tmp_path, unsafe):
    root, inventory = bundle(tmp_path)
    inventory[unsafe] = "0" * 64
    (root / "bundle.json").write_text(
        json.dumps({"format": "anonymizer-windows-portable-v1", "files": inventory}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="path"):
        builder.verify_bundle(root)


def test_tampered_payload_and_missing_essential_resource_are_rejected(tmp_path):
    root, inventory = bundle(tmp_path)
    (root / "Anonymizer.exe").write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        builder.verify_bundle(root)
    del inventory["Anonymizer.exe"]
    (root / "bundle.json").write_text(
        json.dumps({"format": "anonymizer-windows-portable-v1", "files": inventory}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="required"):
        builder.verify_bundle(root)


def test_only_inventory_files_are_included_not_user_documents(tmp_path):
    root, inventory = bundle(tmp_path)
    (root / "private-report.pdf").write_bytes(b"must never be packaged")
    (root / "session.json").write_text("not application data")
    verified = builder.verify_bundle(root)
    include = tmp_path / "files.iss"
    builder.write_file_include(root, verified, include)
    lines = include.read_text("utf-8-sig").splitlines()
    assert len(lines) == len(inventory) + 1
    assert all("Flags: ignoreversion" in line for line in lines)
    assert "private-report" not in include.read_text("utf-8-sig")
    assert "session.json" not in include.read_text("utf-8-sig")
    assert not any("*" in line or "recursesubdirs" in line for line in lines)
    assert any('DestDir: "{app}\\models\\gliner"' in line for line in lines)


def test_case_colliding_names_fail_even_on_case_sensitive_build_hosts(tmp_path):
    root, inventory = bundle(tmp_path)
    inventory["anonymizer.exe"] = inventory["Anonymizer.exe"]
    (root / "bundle.json").write_text(
        json.dumps({"format": "anonymizer-windows-portable-v1", "files": inventory}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Duplicate"):
        builder.verify_bundle(root)


@pytest.mark.parametrize("version", [(6, 4, 3), (6, 5, 1), (7, 0, 0)])
def test_old_or_unsupported_compiler_versions_fail_before_build(tmp_path, monkeypatch, version):
    compiler = tmp_path / "ISCC.exe"
    compiler.write_bytes(b"fake")
    monkeypatch.setattr(builder, "compiler_version", lambda _: version)
    with pytest.raises(ValueError, match="6.5.2"):
        builder.find_compiler(compiler)


def test_build_passes_exact_include_and_writes_matching_hash_report(tmp_path, monkeypatch):
    root, inventory = bundle(tmp_path)
    output = tmp_path / "installer output"
    compiler = tmp_path / "compiler" / "ISCC.exe"
    monkeypatch.setattr(builder, "find_compiler", lambda _: (compiler, (6, 7, 0)))
    calls = []

    def run(argv, *, check):
        assert check
        include = Path(next(a.split("=", 1)[1] for a in argv if a.startswith("/DBundleFiles=")))
        assert len(include.read_text("utf-8-sig").splitlines()) == len(inventory) + 2
        calls.append(argv)
        version = next(a.split("=", 1)[1] for a in argv if a.startswith("/DAppVersion="))
        (output / f"Anonymizer-Setup-{version}-x64.exe").write_bytes(b"synthetic installer")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(builder.subprocess, "run", run)
    report = builder.build(root, output)
    executable = output / "Anonymizer-Setup-0.1.0.2-x64.exe"
    assert report["sha256"] == hashlib.sha256(executable.read_bytes()).hexdigest()
    assert report["bundle_file_count"] == len(inventory) + 2
    assert executable.with_suffix(".exe.sha256").read_text().startswith(report["sha256"])
    assert len(calls) == 1
    second = builder.build(root, output)
    assert second["app_version"] == "0.1.0.3"
    assert (output / second["installer"]).is_file()
    assert executable.is_file()


def test_installer_output_cannot_be_written_inside_bundle(tmp_path):
    root, _ = bundle(tmp_path)
    with pytest.raises(ValueError, match="outside"):
        builder.build(root, root / "installer")


def test_failed_build_preserves_counter_and_cleans_partial_executable(
    tmp_path, monkeypatch, version_counter
):
    root, _ = bundle(tmp_path)
    output = tmp_path / "output"
    before = version_counter.read_bytes()
    monkeypatch.setattr(builder, "find_compiler", lambda _: (tmp_path / "ISCC.exe", (6, 7, 0)))

    def fail(argv, **kwargs):
        (output / "Anonymizer-Setup-0.1.0.2-x64.exe").write_bytes(b"partial")
        raise subprocess.CalledProcessError(1, argv)

    monkeypatch.setattr(builder.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        builder.build(root, output)
    assert version_counter.read_bytes() == before
    assert not list(output.glob("*.exe"))


@pytest.mark.parametrize("direct", [False, True])
def test_light_installer_omits_model_and_stamps_matching_version_and_manifest(tmp_path, direct):
    from anonymizer.model_download import FILES

    root, inventory = bundle(tmp_path)
    descriptor = tmp_path / "model-download.json"
    spec = {
        "format": "anonymizer-model-download-v1",
        "url": "https://example.org/model.zip",
        "size": 123,
        "sha256": "a" * 64,
        "files": {
            name: {
                "sha256": inventory["models/gliner/" + name],
                "size": (root / "models/gliner" / name).stat().st_size,
            }
            for name in FILES
        },
    }
    if direct:
        spec.update(format="anonymizer-model-onnx-v1", **spec["files"]["model.onnx"])
    descriptor.write_text(json.dumps(spec), encoding="utf-8")
    stage = tmp_path / "stage"
    stage.mkdir()
    original = (root / builder.APP / "version.py").read_bytes()
    payload, overrides = builder.installer_payload(
        root, builder.verify_bundle(root), stage, "0.1.0.42", descriptor
    )
    assert "models/gliner/model.onnx" not in payload["files"]
    assert ("models/gliner/tokenizer.json" in payload["files"]) == direct
    assert "model-download.json" in payload["files"]
    assert overrides[builder.APP + "/version.py"].read_text() == 'VERSION = "0.1.0.42"\n'
    manifest = json.loads(overrides["bundle.json"].read_text())
    assert manifest["app_version"] == "0.1.0.42"
    for name, expected in manifest["files"].items():
        assert builder.sha256(overrides.get(name, root / name)) == expected
    assert (root / builder.APP / "version.py").read_bytes() == original
    spec["files"]["model.onnx"]["sha256"] = "0" * 64
    if direct:
        spec["sha256"] = "0" * 64
    descriptor.write_text(json.dumps(spec), encoding="utf-8")
    with pytest.raises(ValueError, match="differs"):
        builder.installer_payload(root, builder.verify_bundle(root), stage, "0.1.0.43", descriptor)


def test_compiler_probe_reads_engine_version_without_pe_metadata(monkeypatch):
    def run(argv, **kwargs):
        assert "/O-" in argv and kwargs["timeout"] == 60
        script = Path(argv[-1]).read_text("utf-8-sig")
        assert "Str(Ver)" in script and "Output=no" in script
        return subprocess.CompletedProcess(
            argv,
            0,
            "Inno Setup 6 Command-Line Compiler\nANONYMIZER_COMPILER_BIN_VERSION=101122816\n",
            "",
        )

    monkeypatch.setattr(builder.subprocess, "run", run)
    assert builder.compiler_version(Path("ISCC.exe")) == (6, 7, 3)


@pytest.mark.parametrize(
    "stdout",
    [
        "Inno Setup 6",
        "ANONYMIZER_COMPILER_BIN_VERSION=999999999999",
        "ANONYMIZER_COMPILER_BIN_VERSION=1\nANONYMIZER_COMPILER_BIN_VERSION=2",
    ],
)
def test_compiler_probe_rejects_ambiguous_or_missing_engine_marker(monkeypatch, stdout):
    monkeypatch.setattr(
        builder.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout, "")
    )
    with pytest.raises(ValueError, match="version"):
        builder.compiler_version(Path("ISCC.exe"))
