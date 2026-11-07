## @file packaging/windows/build_model_package.py
#  @brief Prepara l'archivio versionato del modello ONNX verificato e il suo descrittore.
#
#  Crea lo zip del modello e `model-download.json` con URL, hash e dimensioni,
#  da usare con l'installer che scarica il modello al primo avvio. Non pubblica
#  nulla. La docstring di modulo resta in inglese perché è il testo di aiuto di
#  argparse.
"""Prepare a versioned download from the verified ONNX model without publishing it."""

import argparse
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from anonymizer.detect.ner import verify_model_artifacts  # noqa: E402
from anonymizer.model_download import FILES, digest, secure_url  # noqa: E402


def build(model, output, base_url):
    """!
    @brief Crea l'archivio del modello e il descrittore di download.

    Il nome dell'archivio deriva dal digest del registro del modello, così ogni
    revisione ha un URL distinto.
    @param model Cartella del modello ONNX verificato.
    @param output Cartella di destinazione.
    @param base_url URL base HTTPS da cui sarà servito l'archivio.
    @return Dizionario con percorsi di archivio e descrittore e dimensione in byte.
    @throws ValueError Se l'archivio o il descrittore esistono già.
    """
    model, output = Path(model).resolve(), Path(output).resolve()
    _, ledger_digest = verify_model_artifacts(model, "onnx")
    filename = f"anonymizer-model-{ledger_digest[:16]}.zip"
    archive = output / filename
    spec_path = output / "model-download.json"
    if archive.exists() or spec_path.exists():
        raise ValueError("Model package output already exists")
    url = secure_url(base_url.rstrip("/") + "/" + filename)
    output.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as zipped:
        for name in sorted(FILES):
            zipped.write(model / name, name)
    spec = {
        "format": "anonymizer-model-download-v1",
        "url": url,
        "sha256": digest(archive),
        "size": archive.stat().st_size,
        "files": {
            name: {"sha256": digest(model / name), "size": (model / name).stat().st_size}
            for name in sorted(FILES)
        },
    }
    spec_path.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    return {"archive": str(archive), "descriptor": str(spec_path), "bytes": spec["size"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.model, args.output, args.base_url)))
