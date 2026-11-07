## @file packaging/windows/build_portable.py
#  @brief Costruisce il bundle portable Windows da input locali verificati.
#
#  Produce con PyInstaller un piccolo bootstrap onedir (launcher.py) e gli affianca
#  un runtime CPython 3.12 rilocabile con le dipendenze, il pacchetto applicativo,
#  il modello ONNX verificato, Tesseract e le licenze; infine scrive `bundle.json`
#  con l'hash di ogni file. La docstring di modulo resta in inglese perché è il
#  testo di aiuto di argparse.
"""Build an onedir bootstrap plus a relocatable CPython runtime from verified local inputs."""

import argparse
import compileall
import hashlib
import importlib.metadata as metadata
import json
import py_compile
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import tomllib
from collections import deque
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

## Radice del repository.
REPO = Path(__file__).resolve().parents[3]
## Cartella dei sorgenti Python del repository.
SRC = REPO / "src"
sys.path.insert(0, str(SRC))

from anonymizer.detect.ner import verify_model_artifacts, verify_onnx_graph  # noqa: E402


def dependency_closure(requirements):
    """!
    @brief Calcola la chiusura transitiva delle dipendenze installate.

    Segue i requisiti dichiarati, inclusi quelli attivati dagli extra, e verifica
    che le versioni installate li soddisfino.
    @param requirements Stringhe di requisito PEP 508 di partenza.
    @return Mappa nome normalizzato -> distribuzione installata.
    @throws ValueError Se una dipendenza installata non soddisfa il requisito.
    """
    pending = deque(Requirement(value) for value in requirements)
    distributions, visited = {}, set()
    while pending:
        requirement = pending.popleft()
        key = (canonicalize_name(requirement.name), frozenset(requirement.extras))
        if key in visited:
            continue
        visited.add(key)
        distribution = metadata.distribution(requirement.name)
        if requirement.specifier and distribution.version not in requirement.specifier:
            raise ValueError(f"Installed dependency does not satisfy {requirement.name}")
        distributions[key[0]] = distribution
        for dependency in distribution.requires or ():
            child = Requirement(dependency)
            if child.marker is None or any(
                child.marker.evaluate({"extra": extra}) for extra in ("", *requirement.extras)
            ):
                pending.append(child)
    return distributions


def copy_distributions(distributions, target):
    """!
    @brief Copia nel bundle i file installati delle distribuzioni.

    Salta bytecode, file `.pth`, metadati di installazione e file editable;
    conta i file di licenza di ciascuna distribuzione.
    @param distributions Mappa nome -> distribuzione da copiare.
    @param target Cartella site-packages di destinazione.
    @return Inventario con nome, versione, licenza e numero di file di licenza.
    @throws ValueError Se manca l'inventario dei file o un file dichiarato.
    """
    site = Path(sysconfig.get_path("purelib")).resolve()
    inventory = []
    for name, distribution in sorted(distributions.items()):
        if distribution.files is None:
            raise ValueError(f"Missing installed-file inventory: {name}")
        license_files = 0
        for relative in distribution.files:
            source = Path(distribution.locate_file(relative)).resolve()
            if not source.is_relative_to(site):
                continue
            destination = target / source.relative_to(site)
            if (
                source.suffix in (".pth", ".pyc")
                or source.name in ("direct_url.json", "RECORD", "INSTALLER", "REQUESTED")
                or "__pycache__" in source.parts
                or source.name.startswith("__editable__")
            ):
                continue
            if not source.is_file():
                raise ValueError(f"Missing dependency file: {name}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            if "license" in source.name.lower() or "licenses" in source.parts:
                license_files += 1
        inventory.append(
            {
                "name": name,
                "version": distribution.version,
                "license_expression": distribution.metadata.get("License-Expression"),
                "license_files": license_files,
            }
        )
    return inventory


def copy_runtime(source, destination):
    """!
    @brief Copia il runtime CPython standalone escludendo i componenti superflui.
    @param source Cartella di un CPython 3.12 per Windows.
    @param destination Cartella `runtime` del bundle.
    @throws ValueError Se la sorgente non contiene gli eseguibili e la DLL attesi.
    """
    if not all(
        (source / name).is_file() for name in ("python.exe", "pythonw.exe", "python312.dll")
    ):
        raise ValueError("A standalone Windows CPython 3.12 directory is required")
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(
            "site-packages",
            "__pycache__",
            "*.pyc",
            "pyvenv.cfg",
            "*.pth",
            "include",
            "libs",
            "Scripts",
            "tcl",
            ".temp",
        ),
    )


def copy_app(destination):
    """!
    @brief Copia il pacchetto anonymizer e ne crea i metadati di distribuzione minimi.
    @param destination Cartella site-packages di destinazione.
    """
    package = destination / "anonymizer"
    for source in (SRC / "anonymizer").rglob("*"):
        if source.is_file() and source.suffix in (
            ".py",
            ".json",
            ".txt",
            ".html",
            ".css",
            ".js",
            ".svg",
            ".png",
            ".ico",
            ".woff2",
        ):
            target = package / source.relative_to(SRC / "anonymizer")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    info = destination / "anonymizer-0.1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: anonymizer\nVersion: 0.1.0\n", encoding="utf-8"
    )


def precompile_runtime(bundle):
    """!
    @brief Precompila il runtime in bytecode con hash verificato.

    I percorsi incorporati sono relativi al bundle, così il risultato è
    riproducibile e rilocabile.
    @param bundle Cartella del bundle.
    @throws ValueError Se la compilazione fallisce.
    """
    if not compileall.compile_dir(
        bundle / "runtime" / "Lib",
        force=True,
        quiet=1,
        optimize=0,
        stripdir=str(bundle),
        prependdir="",
        invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH,
        workers=1,
    ):
        raise ValueError("Runtime bytecode compilation failed")


def build(args):
    """!
    @brief Costruisce il bundle portable completo nella cartella di output.

    Lavora in una cartella temporanea accanto all'output e la rinomina solo alla
    fine, così un errore non lascia un bundle parziale.
    @param args Argomenti della riga di comando (cartelle di runtime, OCR, modello,
           licenze e output).
    @throws ValueError Se piattaforma, interprete, ambiente di build o input non
            sono quelli richiesti.
    """
    if sys.platform != "win32":
        raise ValueError("Build the Windows portable on Windows")
    if sys.version_info[:2] != (3, 12):
        raise ValueError("Build with CPython 3.12 to match the bundled runtime")
    icon = SRC / "anonymizer" / "web" / "static" / "anonymizer.ico"
    if not icon.is_file():
        raise ValueError("Run tools/packaging/windows/build_icons.py before building the portable")
    output = args.output.resolve()
    if output.exists():
        raise ValueError("Output must be a new directory")
    if not metadata.version("torch").endswith("+cpu"):
        raise ValueError("The build environment must contain CPU-only Torch")
    project = tomllib.loads((REPO / "pyproject.toml").read_text("utf-8"))["project"]
    requirements = list(project["dependencies"])
    for group in ("web", "visual", "ocr", "ner-onnx", "desktop"):
        requirements.extend(project["optional-dependencies"][group])
    distributions = dependency_closure(requirements)
    if {"pywebview", "pythonnet", "clr-loader"} & distributions.keys():
        raise ValueError("Legacy desktop dependencies must not enter the Qt bundle")
    ledger, digest = verify_model_artifacts(args.model, "onnx")
    verify_onnx_graph(args.model / "model.onnx")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="anonymizer-build-", dir=output.parent) as temporary:
        stage = Path(temporary)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--onedir",
                "--windowed",
                "--icon",
                str(icon),
                "--name",
                "Anonymizer",
                "--distpath",
                str(stage / "dist"),
                "--workpath",
                str(stage / "work"),
                "--specpath",
                str(stage),
                str(Path(__file__).with_name("launcher.py")),
            ],
            check=True,
            cwd=stage,
        )
        bundle = stage / "dist" / "Anonymizer"
        runtime = bundle / "runtime"
        copy_runtime(args.python_root.resolve(), runtime)
        site = runtime / "Lib" / "site-packages"
        site.mkdir(parents=True)
        inventory = copy_distributions(distributions, site)
        copy_app(site)
        shutil.copy2(REPO / "LICENSE", bundle / "LICENSE.txt")
        model = bundle / "models" / "gliner"
        model.mkdir(parents=True)
        for name in (*ledger["files"], "anonymizer_model.json"):
            shutil.copy2(args.model / name, model / name)
        ocr = bundle / "ocr"
        ocr.mkdir()
        binary = args.ocr_root / "Library" / "bin"
        shutil.copy2(binary / "tesseract.exe", ocr / "tesseract.exe")
        for source in binary.glob("*.dll"):
            shutil.copy2(source, ocr / source.name)
        (ocr / "tessdata").mkdir()
        shutil.copy2(args.tessdata / "ita.traineddata", ocr / "tessdata" / "ita.traineddata")
        shutil.copytree(args.ocr_licenses, bundle / "licenses" / "ocr")
        shutil.copytree(args.model_licenses, bundle / "licenses" / "model")
        shutil.copytree(args.qt_licenses, bundle / "licenses" / "qt")
        precompile_runtime(bundle)
        files = {}
        for path in sorted(bundle.rglob("*")):
            if path.is_file():
                digest_file = hashlib.sha256()
                with path.open("rb") as stream:
                    while block := stream.read(1024 * 1024):
                        digest_file.update(block)
                files[path.relative_to(bundle).as_posix()] = digest_file.hexdigest()
        (bundle / "bundle.json").write_text(
            json.dumps(
                {
                    "format": "anonymizer-windows-portable-v1",
                    "python": "3.12",
                    "bytecode": "checked-hash-cpython312",
                    "model_id": ledger["model_id"],
                    "model_revision": ledger["revision"],
                    "model_ledger_sha256": digest,
                    "runtime": "onnx",
                    "precision": "fp32",
                    "dependencies": inventory,
                    "desktop_engine": "QtWebEngine",
                    "qt_version": metadata.version("PySide6"),
                    "files": files,
                    "prerequisites": [],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        bundle.rename(output)
    print(json.dumps({"output": str(output), "dependency_count": len(inventory)}))


def main():
    """!
    @brief Punto d'ingresso da riga di comando.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "python-root",
        "ocr-root",
        "tessdata",
        "model",
        "ocr-licenses",
        "model-licenses",
        "qt-licenses",
        "output",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    build(parser.parse_args())


if __name__ == "__main__":
    main()
