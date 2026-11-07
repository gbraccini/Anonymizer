import hashlib
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from anonymizer.detect import ner
from anonymizer.ner_model import LABELS, NerAudit, NerConfig, NerError


def bundle(path, *, runtime="onnx", graph=b"synthetic graph"):
    path.mkdir()
    content = {
        "gliner_config.json": b"{}",
        "tokenizer_config.json": b"{}",
        "tokenizer.json": b"{}",
        "model.onnx" if runtime == "onnx" else "model.safetensors": graph,
    }
    for name, data in content.items():
        (path / name).write_bytes(data)
    ledger = {
        "model_id": "synthetic/model",
        "revision": "fixed",
        "runtime": runtime,
        "precision": "fp32",
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in content.items()},
    }
    (path / "anonymizer_model.json").write_text(json.dumps(ledger), "utf-8")
    return path


def test_onnx_adapter_has_explicit_cpu_options_and_never_calls_eval(tmp_path, monkeypatch):
    path = bundle(tmp_path / "model")
    verified = []
    monkeypatch.setattr(ner, "verify_onnx_graph", lambda p: verified.append(p))
    monkeypatch.setattr(ner, "version", lambda name: "test-" + name)
    calls = []
    model = SimpleNamespace(
        data_processor=SimpleNamespace(transformer_tokenizer=SimpleNamespace(model_max_length=512)),
        config=SimpleNamespace(
            max_len=384,
            max_width=12,
            encoder_config=SimpleNamespace(max_position_embeddings=512),
        ),
    )

    def load(path, **kwargs):
        calls.append(kwargs)
        return model  # No eval method: calling it would fail this test.

    monkeypatch.setitem(
        sys.modules, "gliner", SimpleNamespace(GLiNER=SimpleNamespace(from_pretrained=load))
    )
    monkeypatch.setitem(
        sys.modules,
        "onnxruntime",
        SimpleNamespace(
            SessionOptions=SimpleNamespace,
            ExecutionMode=SimpleNamespace(ORT_SEQUENTIAL="sequential"),
            GraphOptimizationLevel=SimpleNamespace(ORT_ENABLE_ALL="all"),
        ),
    )
    detector = ner.GLiNERDetector(NerConfig(path, runtime="onnx", cpu_threads=2))
    options = calls[0]
    assert verified == [path / "model.onnx"]
    assert options["local_files_only"] is True and options["token"] is False
    assert options["runtime"] == "onnxruntime"
    assert options["runtime_model_file"] == "model.onnx"
    runtime = options["runtime_options"]
    assert runtime["providers"] == ["CPUExecutionProvider"]
    assert vars(runtime["session_options"]) == {
        "intra_op_num_threads": 2,
        "inter_op_num_threads": 1,
        "execution_mode": "sequential",
        "graph_optimization_level": "all",
    }
    audit = NerAudit(**asdict(detector.audit))
    assert (audit.runtime, audit.cpu_threads, audit.precision) == ("onnx", 2, "fp32")
    assert audit.runtime_version == "test-onnxruntime"


@pytest.mark.parametrize("damage", ["missing", "modified", "runtime"])
def test_bad_bundle_rejected_before_graph_parser_or_runtime(tmp_path, monkeypatch, damage):
    path = bundle(tmp_path / "model")
    monkeypatch.setattr(ner, "verify_onnx_graph", lambda p: pytest.fail("must verify hashes first"))
    if damage == "missing":
        (path / "model.onnx").unlink()
    elif damage == "modified":
        (path / "model.onnx").write_bytes(b"changed")
    with pytest.raises(NerError):
        ner.verify_model_artifacts(path, "torch" if damage == "runtime" else "onnx")


def test_real_onnx_parser_rejects_external_initializers_and_nested_attributes(tmp_path):
    onnx = pytest.importorskip("onnx")
    from onnx import TensorProto, helper

    tensor = helper.make_tensor("weight", TensorProto.FLOAT, [1], [1.0])
    graph = helper.make_graph([], "synthetic", [], [], [tensor])
    model = helper.make_model(graph)
    path = tmp_path / "model.onnx"
    onnx.save(model, path)
    ner.verify_onnx_graph(path)
    external = TensorProto(name="external", data_type=TensorProto.FLOAT, dims=[1])
    external.data_location = TensorProto.EXTERNAL
    external.external_data.add(key="location", value="../secret")
    model.graph.node.append(helper.make_node("Constant", [], ["out"], value=external))
    path.write_bytes(model.SerializeToString())
    with pytest.raises(NerError, match="ner_onnx_external_data_unsupported"):
        ner.verify_onnx_graph(path)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"runtime": "cuda"},
        {"cpu_threads": 0},
        {"cpu_threads": 33},
        {"cpu_threads": True},
    ],
)
def test_config_rejects_unsupported_runtime_and_thread_settings(kwargs):
    with pytest.raises(NerError):
        NerConfig(Path("unused"), **kwargs)


def test_legacy_audit_defaults_and_onnx_ready_requires_runtime_metadata():
    old = dict(
        status="ready",
        backend="gliner",
        model_id="id",
        revision="rev",
        artifact_sha256="a" * 64,
        library_version="old",
        threshold=0.5,
        labels=LABELS,
        word_limit=384,
        subword_limit=512,
        max_width=12,
        window_words=256,
        overlap_words=11,
    )
    assert NerAudit(**old).runtime == "torch"
    with pytest.raises(NerError, match="ner_incomplete_runtime_audit"):
        NerAudit(**old, runtime="onnx")


def test_cli_anon_passes_runtime_and_threads_to_config(tmp_path, monkeypatch):
    from anonymizer.cli import main

    source = tmp_path / "input.txt"
    source.write_text("Synthetic", "utf-8")
    seen = []

    def load(config):
        seen.append(config)
        raise NerError("synthetic_stop")

    monkeypatch.setattr(ner, "GLiNERDetector", load)
    assert (
        main(
            [
                "anon",
                str(source),
                "--output",
                str(tmp_path / "out.txt"),
                "--map",
                str(tmp_path / "map.json"),
                "--ner-model",
                str(tmp_path / "model"),
                "--ner-runtime",
                "onnx",
                "--ner-threads",
                "3",
            ]
        )
        == 1
    )
    assert seen[0].runtime == "onnx" and seen[0].cpu_threads == 3
    assert not (tmp_path / "out.txt").exists()


def test_web_explicit_thread_override_is_applied_before_model_load(monkeypatch):
    pytest.importorskip("fastapi")
    TestClient = pytest.importorskip("fastapi.testclient").TestClient
    from anonymizer.web.app import create_app

    seen = []
    monkeypatch.setattr(ner, "GLiNERDetector", lambda config: seen.append(config) or object())
    monkeypatch.setattr("anonymizer.web.app.probe_ocr", lambda: "unavailable")
    original = NerConfig(Path("unused"), runtime="onnx", cpu_threads=2)
    with TestClient(
        create_app(local_only=True, ner_config=original, ner_threads=3),
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 50000),
    ) as client:
        assert client.get("/api/health").json()["ner"] == "ready"
    assert seen[0].runtime == "onnx" and seen[0].cpu_threads == 3
    assert original.cpu_threads == 2


def test_onnx_audit_manifest_roundtrip_and_digest_binding():
    from dataclasses import replace

    from test_visual_model import sample

    from anonymizer.manifest import confirm_review, dumps, loads
    from anonymizer.visual_model import review_digest

    audit = NerAudit(
        status="ready",
        backend="gliner",
        model_id="id",
        revision="fixed",
        artifact_sha256="a" * 64,
        library_version="test",
        threshold=0.5,
        labels=LABELS,
        word_limit=384,
        subword_limit=512,
        max_width=12,
        window_words=256,
        overlap_words=11,
        runtime="onnx",
        runtime_version="test",
        provider="CPUExecutionProvider",
        precision="fp32",
        cpu_threads=4,
    )
    manifest = confirm_review(replace(sample(), ner_audit=audit))
    assert loads(dumps(manifest)).ner_audit == audit
    changed = replace(manifest, ner_audit=replace(audit, cpu_threads=2))
    assert review_digest(changed) != manifest.reviewed_digest


@pytest.mark.skipif(
    not os.environ.get("ANONYMIZER_TEST_NER_ONNX_MODEL"),
    reason="verified ONNX bundle not configured",
)
def test_real_offline_onnx_backend():
    path = Path(os.environ["ANONYMIZER_TEST_NER_ONNX_MODEL"])
    detector = ner.GLiNERDetector(NerConfig(path, runtime="onnx", cpu_threads=4))
    text = "La paziente Giulia Rossi arriva in ambulatorio."
    spans = detector.detect(text, "synthetic")
    assert any(text[span.start : span.end] == "Giulia Rossi" for span in spans)
    assert all(span.level == 3 and span.entity_id is None for span in spans)
    assert detector.audit.provider == "CPUExecutionProvider"
