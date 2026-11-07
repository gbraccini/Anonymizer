## @file experiments/ner/prepare_model.py
#  @brief Scarica e prepara in locale il modello GLiNER a revisione fissata.
#
#  È l'unico passo che usa la rete, eseguito solo su richiesta esplicita: scarica
#  modello e backbone a revisioni bloccate, verifica l'hash dei pesi, salva il
#  modello e un registro JSON con hash dei file e versioni usate. La docstring di
#  modulo resta invariata perché è usata come descrizione della riga di comando.
"""Explicit network setup; normal anonymizer inference never runs this script."""

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from importlib.metadata import version
from pathlib import Path

## Identificativo del modello GLiNER sul hub.
MODEL = "urchade/gliner_multi-v2.1"
## Commit del modello scaricato, fissato per riproducibilità.
REVISION = "443d26d654e0324125a96bebd8e796c14ff2efe6"
## Identificativo del backbone del modello.
BACKBONE = "microsoft/mdeberta-v3-base"
## Commit del backbone scaricato, fissato per riproducibilità.
BACKBONE_REVISION = "a0484667b22365f84929a935b5e50a51f71f159d"
## SHA-256 atteso del file dei pesi del modello.
WEIGHT_SHA256 = "2100142f31627531497850659dcb3821c99d5e71c08a8e01a98e4b11ef32a199"


def sha256(path):
    """!
    @brief Calcola l'hash SHA-256 di un file leggendolo a blocchi.
    @param path Percorso del file.
    @return Digest esadecimale.
    """
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def main():
    """!
    @brief Punto di ingresso: scarica, verifica e salva il modello con il registro.

    Telemetria e token impliciti sono disattivati prima di importare le librerie
    del hub; la directory di output non deve esistere.
    @throws ValueError Se l'hash dei pesi scaricati non corrisponde a quello atteso.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must not exist")
    os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    from gliner import GLiNER
    from huggingface_hub import snapshot_download

    backbone = snapshot_download(
        BACKBONE,
        revision=BACKBONE_REVISION,
        cache_dir=args.cache,
        token=False,
        allow_patterns=["config.json", "tokenizer*", "special_tokens_map.json", "spm.model"],
    )
    snapshot = Path(
        snapshot_download(
            MODEL,
            revision=REVISION,
            cache_dir=args.cache,
            token=False,
            allow_patterns=["gliner_config.json", "model.safetensors"],
        )
    )
    if sha256(snapshot / "model.safetensors") != WEIGHT_SHA256:
        raise ValueError("pinned_model_weight_hash_mismatch")
    # A pinned local backbone avoids resolving a legacy checkpoint's unpinned model_name.
    with tempfile.TemporaryDirectory(prefix="anonymizer-prepare-") as temporary:
        stage = Path(temporary)
        config = json.loads((snapshot / "gliner_config.json").read_text("utf-8"))
        config["model_name"] = str(Path(backbone).resolve())
        (stage / "gliner_config.json").write_text(json.dumps(config), "utf-8")
        try:
            os.link(
                (snapshot / "model.safetensors").resolve(strict=True), stage / "model.safetensors"
            )
        except OSError:
            shutil.copyfile(snapshot / "model.safetensors", stage / "model.safetensors")
        if not (stage / "model.safetensors").exists():
            (stage / "model.safetensors").unlink(missing_ok=True)
            shutil.copyfile(snapshot / "model.safetensors", stage / "model.safetensors")
        model = GLiNER.from_pretrained(
            stage,
            local_files_only=True,
            token=False,
            map_location="cpu",
            low_cpu_mem_usage=True,
        )
        model.config.model_name = BACKBONE
        args.output.mkdir(parents=True)
        model.save_pretrained(args.output, safe_serialization=True)
    files = {path.name: sha256(path) for path in args.output.iterdir() if path.is_file()}
    ledger = dict(
        model_id=MODEL,
        revision=REVISION,
        license="apache-2.0",
        backbone=dict(model_id=BACKBONE, revision=BACKBONE_REVISION, license="mit"),
        files=files,
        prepared_with={
            name: version(name)
            for name in (
                "gliner",
                "torch",
                "transformers",
                "huggingface_hub",
                "sentencepiece",
                "protobuf",
            )
        },
    )
    (args.output / "anonymizer_model.json").write_text(json.dumps(ledger, indent=2), "utf-8")
    print(json.dumps(dict(status="prepared", files=len(files), revision=REVISION)))


if __name__ == "__main__":
    main()
