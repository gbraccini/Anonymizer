## @file experiments/ner/prepare_onnx.py
#  @brief Deriva offline un modello ONNX FP32 da un bundle Torch locale verificato.
#
#  Esporta il grafo ONNX, copia i file ausiliari e scrive un registro che lega il
#  risultato al registro del modello sorgente. La docstring di modulo resta
#  invariata perché è usata come descrizione della riga di comando.
"""Offline FP32 ONNX derivation from a verified local Torch bundle."""

import argparse
import gc
import json
import shutil
from importlib.metadata import version
from pathlib import Path

from anonymizer.detect.ner import LocalGLiNERBackend, _sha256, verify_model_artifacts
from anonymizer.ner_model import NerConfig


def prepare(source: Path, output: Path, cpu_threads: int = 4) -> None:
    """!
    @brief Verifica il bundle sorgente, esporta in ONNX e scrive il registro derivato.

    Il registro viene scritto per ultimo, dopo la verifica del grafo, così un
    export interrotto non risulta mai caricabile come verificato.
    @param source Directory del bundle Torch verificato.
    @param output Directory di destinazione, che non deve esistere.
    @param cpu_threads Thread CPU usati per caricare il modello sorgente.
    """
    ledger, digest = verify_model_artifacts(source)
    config = NerConfig(source, cpu_threads=cpu_threads)
    # Exclusive creation prevents both overwriting and races with another preparer.
    output.mkdir(parents=True, exist_ok=False)
    backend = LocalGLiNERBackend(config)
    backend.model.export_to_onnx(
        save_dir=str(output), onnx_filename="model.onnx", opset=19, quantize=False
    )
    del backend
    gc.collect()
    for name in ledger["files"]:
        if name != "model.safetensors":
            shutil.copyfile(source / name, output / name)
    files = {p.name: _sha256(p) for p in output.iterdir() if p.is_file()}
    derived = {
        "model_id": ledger["model_id"],
        "revision": ledger["revision"],
        "license": ledger.get("license"),
        "runtime": "onnx",
        "precision": "fp32",
        "source_ledger_sha256": digest,
        "source_files": ledger["files"],
        "source_provenance": {key: value for key, value in ledger.items() if key != "files"},
        "exporter": "gliner.export_to_onnx",
        "opset": 19,
        "versions": {
            name: version(name) for name in ("gliner", "torch", "onnx", "onnxruntime", "onnxscript")
        },
        "files": files,
    }
    # No ledger means an interrupted/failed export can never be loaded as verified.
    from anonymizer.detect.ner import verify_onnx_graph

    verify_onnx_graph(output / "model.onnx")
    (output / "anonymizer_model.json").write_text(
        json.dumps(derived, indent=2, ensure_ascii=False), "utf-8"
    )
    verify_model_artifacts(output, "onnx")


def main():
    """!
    @brief Punto di ingresso: legge gli argomenti e avvia la preparazione.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cpu-threads", type=int, choices=range(1, 33), default=4)
    args = parser.parse_args()
    prepare(args.source, args.output, args.cpu_threads)


if __name__ == "__main__":
    main()
