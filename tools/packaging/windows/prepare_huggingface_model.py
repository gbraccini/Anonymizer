## @file packaging/windows/prepare_huggingface_model.py
#  @brief Prepara il modello dall'export ONNX pubblico fissato su Hugging Face.
#
#  Scarica `model.onnx` secondo `huggingface-model.json` e lo affianca ai file di
#  configurazione e tokenizer verificati localmente, scrivendo il registro del
#  modello. La docstring di modulo resta in inglese perché è il testo di aiuto di
#  argparse.
"""Prepare the pinned public ONNX export with our verified offline tokenizer/config."""

import argparse
import json
import shutil
import threading
from pathlib import Path
from urllib.request import build_opener

from anonymizer.detect.ner import verify_model_artifacts
from anonymizer.model_download import (
    SecureRedirect,
    download,
    read_spec,
    verified,
)


def prepare(support, output):
    """!
    @brief Compone e verifica una cartella modello completa.
    @param support Cartella con configurazione e tokenizer già verificati.
    @param output Nuova cartella di destinazione, che non deve esistere.
    @throws ValueError Se un file di supporto o il modello scaricato non
            corrispondono agli hash attesi.
    """
    spec = read_spec(Path(__file__).with_name("huggingface-model.json"))
    cancelled = threading.Event()
    output.mkdir(parents=True, exist_ok=False)
    for name in ("gliner_config.json", "tokenizer.json", "tokenizer_config.json"):
        if not verified(support, {"files": {name: spec["files"][name]}}, cancelled):
            raise ValueError(f"Verified support file required: {name}")
        shutil.copyfile(support / name, output / name)
    ledger = output / "anonymizer_model.json"
    ledger.write_text(json.dumps(spec["ledger"], indent=2) + "\n", encoding="utf-8")
    part = output / "model.onnx.part"
    download(
        spec,
        part,
        cancelled,
        lambda message, _: print(message, flush=True),
        build_opener(SecureRedirect()),
    )
    part.rename(output / "model.onnx")
    if not verified(output, spec, cancelled):
        raise ValueError("Prepared model hash mismatch")
    verify_model_artifacts(output, "onnx")


def main():
    """!
    @brief Punto d'ingresso da riga di comando.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--support-model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.support_model, args.output)


if __name__ == "__main__":
    main()
