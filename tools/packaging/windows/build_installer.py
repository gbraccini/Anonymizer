## @file packaging/windows/build_installer.py
#  @brief Compila l'installer Windows per utente a partire dal bundle portable verificato.
#
#  Verifica l'inventario hash del bundle, prepara i file sovrascritti (versione,
#  manifest, descrittore del modello scaricabile), genera l'elenco [Files] per Inno
#  Setup e invoca ISCC. La docstring di modulo resta in inglese perché è il testo
#  di aiuto di argparse.
"""Compile a per-user installer from the exact verified portable inventory."""

import argparse
import hashlib
import json
import os
import py_compile
import re
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

## File JSON con versione base e contatore di build dell'installer.
VERSION_FILE = Path(__file__).with_name("version.json")
## Percorso del pacchetto applicativo dentro il bundle.
APP = "runtime/Lib/site-packages/anonymizer"
## Percorso di PySide6 dentro il bundle.
QT = "runtime/Lib/site-packages/PySide6"
## Risorse che il manifest del bundle deve obbligatoriamente elencare.
REQUIRED = {
    "Anonymizer.exe",
    "LICENSE.txt",
    "runtime/python.exe",
    "runtime/pythonw.exe",
    "runtime/python312.dll",
    "ocr/tesseract.exe",
    "ocr/tessdata/ita.traineddata",
    *(
        "models/gliner/" + name
        for name in (
            "anonymizer_model.json",
            "model.onnx",
            "gliner_config.json",
            "tokenizer.json",
            "tokenizer_config.json",
        )
    ),
    *(
        APP + "/web/static/" + name
        for name in ("index.html", "app.js", "style.css", "anonymizer.ico")
    ),
    APP + "/desktop.py",
    APP + "/desktop_qt.py",
    APP + "/model_download.py",
    APP + "/version.py",
    QT + "/QtWebEngineProcess.exe",
    QT + "/plugins/platforms/qwindows.dll",
    QT + "/resources/qtwebengine_resources.pak",
    QT + "/resources/qtwebengine_resources_100p.pak",
    QT + "/resources/qtwebengine_resources_200p.pak",
    QT + "/resources/icudtl.dat",
}


def sha256(path):
    """!
    @brief Calcola l'impronta SHA-256 di un file.
    @param path Percorso del file da leggere.
    @return Digest esadecimale in minuscolo.
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_relative(name):
    """!
    @brief Valida un percorso relativo del bundle e lo converte in PurePosixPath.

    Rifiuta percorsi assoluti, componenti `.`/`..`, caratteri non ammessi da
    Windows o da Inno Setup e nomi di dispositivo riservati (CON, COM1, ...).
    @param name Percorso relativo in formato POSIX come compare nel manifest.
    @return Percorso validato.
    @throws ValueError Se il percorso non è sicuro o non è valido.
    """
    if not isinstance(name, str) or not name or any(ord(c) < 32 for c in name):
        raise ValueError("Invalid bundle path")
    if any(c in name for c in '\\:*?";{}'):
        raise ValueError("Unsafe bundle path")
    path = PurePosixPath(name)
    if path.is_absolute() or path.as_posix() != name or any(p in (".", "..") for p in path.parts):
        raise ValueError("Unsafe bundle path")
    reserved = {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
    if any(p.rstrip(" .") != p or p.split(".")[0].casefold() in reserved for p in path.parts):
        raise ValueError("Unsafe Windows bundle path")
    return path


def verify_bundle(bundle):
    """!
    @brief Verifica l'integrità del bundle portable rispetto al suo manifest.

    Controlla formato del manifest, presenza delle risorse obbligatorie, unicità
    dei percorsi (senza distinzione di maiuscole), confinamento nella radice e
    hash di ogni file. È un controllo di integrità, non una firma dell'editore.
    @param bundle Cartella del bundle portable.
    @return Dizionario con l'elenco dei file, la dimensione totale e lo SHA-256
            del manifest.
    @throws ValueError Se il manifest o un file non superano la verifica.
    """
    bundle = Path(bundle).resolve(strict=True)
    manifest_path = bundle / "bundle.json"
    if not manifest_path.resolve(strict=True).is_relative_to(bundle):
        raise ValueError("Manifest escapes bundle root")
    manifest = json.loads(manifest_path.read_text("utf-8"))
    inventory = manifest.get("files")
    if manifest.get("format") != "anonymizer-windows-portable-v1" or not isinstance(
        inventory, dict
    ):
        raise ValueError("Invalid portable manifest")
    if not REQUIRED <= inventory.keys():
        raise ValueError("Missing required application resources in manifest")
    names, seen, total = [], set(), 0
    for name, expected in sorted(inventory.items()):
        relative = safe_relative(name)
        if name.casefold() in seen or name.casefold() == "bundle.json":
            raise ValueError("Duplicate bundle path")
        seen.add(name.casefold())
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError("Invalid bundle digest")
        source = bundle.joinpath(*relative.parts).resolve(strict=True)
        if not source.is_relative_to(bundle) or not source.is_file():
            raise ValueError("Bundle path escapes root or is not a file")
        if sha256(source) != expected:
            raise ValueError(f"Bundle hash mismatch: {name}")
        total += source.stat().st_size
        names.append(name)
    # This is an inventory integrity check, not an authenticated publisher signature.
    return {
        "files": names + ["bundle.json"],
        "bytes": total + manifest_path.stat().st_size,
        "manifest_sha256": sha256(manifest_path),
    }


def iss_quote(value):
    """!
    @brief Racchiude un valore tra virgolette per uno script Inno Setup.

    Raddoppia le parentesi graffe, che Inno Setup interpreta come costanti.
    @param value Valore da quotare.
    @return Stringa quotata.
    @throws ValueError Se il valore contiene virgolette, a capo o NUL.
    """
    value = str(value)
    if any(c in value for c in ('"', "\r", "\n", "\0")):
        raise ValueError("Unsafe installer string")
    return '"' + value.replace("{", "{{") + '"'


def write_file_include(bundle, verified, target, overrides=None):
    """!
    @brief Scrive il file di inclusione con le voci [Files] dell'installer.
    @param bundle Cartella del bundle portable.
    @param verified Dizionario con la chiave `files` da includere.
    @param target File `.iss` da generare.
    @param overrides Eventuale mappa nome -> file sostitutivo da usare al posto
           di quello del bundle.
    """
    lines = []
    for name in verified["files"]:
        relative = safe_relative(name)
        directory = str(relative.parent).replace("/", "\\")
        destination = "{app}" + ("\\" + directory if directory != "." else "")
        source = (overrides or {}).get(name, bundle.joinpath(*relative.parts))
        lines.append(
            f'Source: {iss_quote(source)}; DestDir: "{destination}"; '
            f"DestName: {iss_quote(relative.name)}; Flags: ignoreversion"
        )
    target.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")


def compiler_version(compiler):
    """!
    @brief Ricava la versione del motore Inno Setup compilando uno script di sonda.

    La versione PE degli eseguibili ISCC ufficiali può essere zero, per questo si
    legge `Ver` dal preprocessore.
    @param compiler Percorso di ISCC.exe.
    @return Tupla (major, minor, patch).
    @throws ValueError Se la versione non è leggibile o non è valida.
    """
    # Official ISCC binaries can have a zero PE version; query the engine's ISPP Ver instead.
    with tempfile.TemporaryDirectory(prefix="anonymizer-iscc-probe-") as temporary:
        script = Path(temporary) / "version.iss"
        script.write_text(
            '#pragma message "ANONYMIZER_COMPILER_BIN_VERSION=" + Str(Ver)\n'
            "[Setup]\nAppName=Compiler version probe\nAppVersion=1\n"
            "DefaultDirName={tmp}\\anonymizer-version-probe\n"
            "Uninstallable=no\nCreateAppDir=no\nOutput=no\n",
            encoding="utf-8-sig",
        )
        result = subprocess.run(
            [str(compiler), "/O-", str(script)],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
    markers = re.findall(r"ANONYMIZER_COMPILER_BIN_VERSION=(\d+)", result.stdout)
    if len(markers) != 1:
        raise ValueError("Cannot verify Inno Setup compiler engine version")
    packed = int(markers[0])
    if not 0 <= packed <= 0xFFFFFFFF:
        raise ValueError("Invalid compiler engine version")
    return packed >> 24, (packed >> 16) & 0xFF, (packed >> 8) & 0xFF


def find_compiler(explicit=None):
    """!
    @brief Individua un ISCC.exe compatibile (>=6.5.2, <7).

    Senza percorso esplicito cerca nel PATH e nelle cartelle di installazione
    predefinite di Inno Setup 6.
    @param explicit Percorso del compilatore indicato dall'utente, o None.
    @return Coppia (percorso risolto del compilatore, versione).
    @throws ValueError Se il compilatore manca o ha una versione non supportata.
    """
    candidates = [Path(explicit)] if explicit else []
    if not explicit:
        found = shutil.which("ISCC.exe")
        if found:
            candidates.append(Path(found))
        for key in ("LOCALAPPDATA", "ProgramFiles(x86)", "ProgramFiles"):
            if os.environ.get(key):
                base = Path(os.environ[key])
                candidates.extend(
                    (base / "Programs/Inno Setup 6/ISCC.exe", base / "Inno Setup 6/ISCC.exe")
                )
    for candidate in candidates:
        if candidate.is_file():
            compiler = candidate.resolve()
            version = compiler_version(compiler)
            if not (6, 5, 2) <= version < (7, 0, 0):
                raise ValueError("Inno Setup >=6.5.2,<7 is required")
            return compiler, version
    raise ValueError("ISCC.exe not found; pass --iscc with the local compiler path")


def installer_payload(bundle, verified, stage, version, model_download):
    """!
    @brief Prepara l'inventario effettivo dell'installer e i file sostitutivi.

    Esclude le risorse di sviluppo, rimuove il modello se viene scaricato al
    primo avvio (dopo averne confrontato hash e dimensioni con il bundle), riscrive
    `version.py` con il relativo bytecode e rigenera `bundle.json`.
    @param bundle Cartella del bundle portable.
    @param verified Esito di verify_bundle (non usato direttamente).
    @param stage Cartella temporanea in cui scrivere i file sostitutivi.
    @param version Versione dell'applicazione da incorporare.
    @param model_download Descrittore del modello scaricabile, o None per
           includere il modello nell'installer.
    @return Coppia (dizionario con file e byte totali, mappa dei file sostitutivi).
    @throws ValueError Se il modello scaricabile differisce da quello verificato.
    """
    from anonymizer.model_download import read_spec

    manifest = json.loads((bundle / "bundle.json").read_text("utf-8"))
    inventory = dict(manifest["files"])
    removed = [name for name in inventory if development_resource(name)]
    for name in removed:
        del inventory[name]
    manifest["excluded_development_files"] = len(removed)
    overrides = {}
    if model_download is not None:
        spec = read_spec(model_download)
        for name, item in spec["files"].items():
            key = "models/gliner/" + name
            if (
                inventory.get(key) != item["sha256"]
                or (bundle / key).stat().st_size != item["size"]
            ):
                raise ValueError("Download model differs from the verified bundled model")
        if spec["format"] == "anonymizer-model-onnx-v1":
            del inventory["models/gliner/model.onnx"]
        else:
            inventory = {
                name: digest for name, digest in inventory.items() if not name.startswith("models/")
            }
        descriptor = stage / "model-download.json"
        descriptor.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
        overrides["model-download.json"] = descriptor
        manifest["model_distribution"] = "first_start_download"
    source = stage / "version.py"
    source.write_text(f'VERSION = "{version}"\n', encoding="utf-8")
    overrides[APP + "/version.py"] = source
    cache = stage / "version.cpython-312.pyc"
    py_compile.compile(
        str(source),
        cfile=str(cache),
        dfile=APP + "/version.py",
        doraise=True,
        invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH,
    )
    overrides[APP + "/__pycache__/version.cpython-312.pyc"] = cache
    for name, path in overrides.items():
        inventory[name] = sha256(path)
    manifest["files"] = inventory
    manifest["app_version"] = version
    staged_manifest = stage / "bundle.json"
    staged_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    overrides["bundle.json"] = staged_manifest
    files = sorted(inventory) + ["bundle.json"]
    return {
        "files": files,
        "bytes": sum(overrides.get(n, bundle / n).stat().st_size for n in files),
    }, overrides


def development_resource(name):
    """!
    @brief Indica se un file del bundle è una risorsa di sviluppo da non installare.

    Sono tali librerie di import, simboli di debug, header C/C++ e le risorse
    devtools di QtWebEngine.
    @param name Percorso relativo del file nel bundle.
    @return True se il file va escluso dall'installer.
    """
    prefix = "runtime/Lib/site-packages/"
    if not name.startswith(prefix):
        return False
    relative = PurePosixPath(name[len(prefix) :])
    if relative.suffix.lower() in (".lib", ".pdb", ".h", ".hpp"):
        return True
    if relative.parts[0] in ("torch", "numpy", "PySide6") and "include" in relative.parts:
        return True
    return name == QT + "/resources/qtwebengine_devtools_resources.debug.pak"


def next_version(path):
    """!
    @brief Calcola la prossima versione dell'installer dal contatore di build.
    @param path File JSON con la versione base e il numero di build.
    @return Coppia (versione a quattro componenti, stato aggiornato da salvare).
    @throws ValueError Se il contatore non è valido o ha raggiunto il limite.
    """
    state = json.loads(path.read_text("utf-8"))
    if (
        not re.fullmatch(r"\d+\.\d+\.\d+", state["base"])
        or type(state["build"]) is not int
        or not 0 <= state["build"] < 65535
        or any(int(part) > 65535 for part in state["base"].split("."))
    ):
        raise ValueError("Invalid installer version counter")
    state["build"] += 1
    return f"{state['base']}.{state['build']}", state


def build(bundle, output, compiler=None, *, model_download=None, version_file=None):
    """!
    @brief Compila l'installer incrementando il contatore di versione.

    Il contatore viene salvato solo dopo una compilazione riuscita, sotto un lock
    di file che serializza build concorrenti sullo stesso file di versione.
    @param bundle Cartella del bundle portable.
    @param output Cartella di destinazione dell'installer.
    @param compiler Percorso esplicito di ISCC.exe, o None per cercarlo.
    @param model_download Descrittore del modello scaricabile, o None.
    @param version_file File del contatore di versione, o None per quello predefinito.
    @return Rapporto della build (vedi _build).
    """
    import threading

    from anonymizer.model_download import model_lock

    version_file = Path(version_file or VERSION_FILE)
    lock_id = hashlib.sha256(str(version_file.resolve()).encode()).hexdigest()
    lock_path = Path(tempfile.gettempdir()) / f"anonymizer-build-{lock_id}.lock"
    with model_lock(lock_path, threading.Event(), lambda *_: None):
        version, state = next_version(version_file)
        report = _build(bundle, output, compiler, model_download, version)
        temporary = version_file.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        temporary.replace(version_file)
        return report


def _build(bundle, output, compiler, model_download, version):
    """!
    @brief Esegue la compilazione vera e propria per una versione già assegnata.

    Verifica il bundle, genera i file di staging, invoca ISCC e scrive accanto
    all'eseguibile il file `.sha256` e il rapporto `.json`.
    @param bundle Cartella del bundle portable.
    @param output Cartella di destinazione, esterna al bundle.
    @param compiler Percorso esplicito di ISCC.exe, o None.
    @param model_download Descrittore del modello scaricabile, o None.
    @param version Versione dell'applicazione.
    @return Rapporto con nome, hash, dimensioni e versioni dell'installer.
    @throws ValueError Se l'output è dentro il bundle, esiste già o il compilatore
            non produce l'eseguibile atteso.
    """
    bundle, output = Path(bundle).resolve(), Path(output).resolve()
    if output.is_relative_to(bundle):
        raise ValueError("Installer output must be outside the application bundle")
    executable = output / f"Anonymizer-Setup-{version}-x64.exe"
    if any(
        path.exists()
        for path in (
            executable,
            executable.with_suffix(".exe.sha256"),
            executable.with_suffix(".exe.json"),
        )
    ):
        raise ValueError("Installer output already exists")
    compiler, compiler_release = find_compiler(compiler)
    verified = verify_bundle(bundle)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="anonymizer-installer-") as temporary:
        stage = Path(temporary)
        include = stage / "bundle-files.iss"
        payload, overrides = installer_payload(bundle, verified, stage, version, model_download)
        write_file_include(bundle, payload, include, overrides)
        # Inno Setup legge una licenza in testo semplice come ANSI se manca il BOM UTF-8.
        license_page = stage / "LICENSE.txt"
        license_page.write_text((bundle / "LICENSE.txt").read_text("utf-8"), encoding="utf-8-sig")
        command = [
            str(compiler),
            "/Q",
            f"/O{output}",
            f"/DBundleFiles={include}",
            f"/DBundleIcon={bundle / APP / 'web/static/anonymizer.ico'}",
            f"/DAppVersion={version}",
            f"/DLicenseFile={license_page}",
            str(Path(__file__).with_name("installer.iss")),
        ]
        try:
            subprocess.run(command, check=True)
        except (OSError, subprocess.SubprocessError):
            executable.unlink(missing_ok=True)
            raise
    if not executable.is_file():
        raise ValueError("Compiler did not produce the expected installer")
    digest = sha256(executable)
    executable.with_suffix(".exe.sha256").write_text(
        f"{digest}  {executable.name}\n", encoding="ascii"
    )
    report = {
        "installer": executable.name,
        "sha256": digest,
        "bytes": executable.stat().st_size,
        "app_version": version,
        "compiler_version": list(compiler_release),
        "bundle_manifest_sha256": verified["manifest_sha256"],
        "bundle_file_count": len(payload["files"]),
        "bundle_bytes": payload["bytes"],
        "model_distribution": "first_start_download" if model_download else "bundled",
    }
    executable.with_suffix(".exe.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    """!
    @brief Punto d'ingresso da riga di comando: compila e stampa il rapporto JSON.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("dist/installer"))
    parser.add_argument("--iscc", type=Path)
    parser.add_argument(
        "--model-download",
        type=Path,
        help="Verified download descriptor: omit the model from the installer",
    )
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                build(args.bundle, args.output, args.iscc, model_download=args.model_download)
            )
        )
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Installer build failed: {error}\n")


if __name__ == "__main__":
    main()
