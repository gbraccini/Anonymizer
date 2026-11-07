"""!
@file model_download.py
@brief Preparazione verificata del modello al primo avvio; l'elaborazione resta offline.

Scarica, con ripresa, il modello descritto da model-download.json, ne verifica
dimensioni e SHA-256 e lo installa in una cache locale indicizzata per hash.
"""

import hashlib
import http.client
import json
import os
import re
import shutil
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

## File che compongono una cartella di modello completa.
FILES = frozenset(
    (
        "anonymizer_model.json",
        "model.onnx",
        "gliner_config.json",
        "tokenizer.json",
        "tokenizer_config.json",
    )
)


class ModelDownloadError(ValueError):
    """!
    @brief Errore di preparazione del modello con un messaggio in italiano per l'utente.
    """

    pass


class DownloadCancelled(Exception):
    """!
    @brief Segnala che la preparazione del modello è stata annullata.
    """

    pass


def check_cancelled(cancelled):
    """!
    @brief Interrompe l'operazione se è stato richiesto l'annullamento.
    @param cancelled Evento di annullamento.
    @throws DownloadCancelled Se l'evento è impostato.
    """
    if cancelled.is_set():
        raise DownloadCancelled()


def digest(path, cancelled=None):
    """!
    @brief Calcola l'hash SHA-256 di un file leggendolo a blocchi.
    @param path File da verificare.
    @param cancelled Evento di annullamento facoltativo, controllato a ogni blocco.
    @return Digest esadecimale.
    """
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            if cancelled is not None:
                check_cancelled(cancelled)
            result.update(block)
    return result.hexdigest()


def secure_url(url):
    """!
    @brief Verifica che l'URL sia HTTPS, con un host e senza credenziali.
    @param url URL da verificare.
    @return L'URL invariato.
    @throws ModelDownloadError Se l'URL non è un download HTTPS valido.
    """
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ModelDownloadError("L'indirizzo del modello non è un download HTTPS valido.")
    return url


class SecureRedirect(HTTPRedirectHandler):
    """!
    @brief Gestore dei redirect che rifiuta destinazioni non HTTPS.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """!
        @brief Valida la destinazione del redirect prima di seguirlo.
        @param req Richiesta originale.
        @param fp Risposta del redirect.
        @param code Codice di stato HTTP.
        @param msg Messaggio di stato HTTP.
        @param headers Intestazioni della risposta.
        @param newurl URL di destinazione del redirect.
        @return Nuova richiesta prodotta dal gestore standard.
        """
        secure_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def read_spec(path):
    """!
    @brief Legge e valida la specifica di download del modello.

    Controlla formato, URL, hash e dimensioni dell'archivio e di ogni file; nel
    formato ONNX diretto il download deve coincidere con model.onnx.
    @param path File JSON della specifica.
    @return Specifica validata.
    @throws ModelDownloadError Se il file manca o non è valido.
    """
    try:
        spec = json.loads(path.read_text("utf-8"))
        secure_url(spec["url"])
        if (
            spec["format"] not in ("anonymizer-model-download-v1", "anonymizer-model-onnx-v1")
            or not re.fullmatch(r"[0-9a-f]{64}", spec["sha256"])
            or type(spec["size"]) is not int
            or not 0 < spec["size"] <= 4_000_000_000
            or set(spec["files"]) != FILES
        ):
            raise ValueError("invalid_model_download_spec")
        for item in spec["files"].values():
            if (
                not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
                or type(item["size"]) is not int
                or not 0 < item["size"] <= 4_000_000_000
            ):
                raise ValueError("invalid_model_file")
        if spec["format"] == "anonymizer-model-onnx-v1" and any(
            spec[key] != spec["files"]["model.onnx"][key] for key in ("size", "sha256")
        ):
            raise ValueError("invalid_onnx_download")
        return spec
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise ModelDownloadError("Configurazione del download mancante o non valida.") from None


def cache_root():
    """!
    @brief Cartella della cache dei modelli scaricati.
    @return Percorso sotto LOCALAPPDATA, oppure sotto ~/.cache se non definita.
    """
    local = os.environ.get("LOCALAPPDATA")
    return (Path(local) if local else Path.home() / ".cache") / "Anonymizer" / "models"


@contextmanager
def model_lock(path, cancelled, progress):
    """!
    @brief Context manager che acquisisce un lock esclusivo su file tra processi.

    Attende finché il lock non è libero, segnalando l'attesa una sola volta, così
    più finestre non preparano il modello contemporaneamente.
    @param path File di lock.
    @param cancelled Evento di annullamento controllato durante l'attesa.
    @param progress Callback di avanzamento (messaggio, percentuale).
    """
    with path.open("a+b") as lock:
        lock.seek(0, 2)
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        waiting = False
        while True:
            check_cancelled(cancelled)
            try:
                lock.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if not waiting:
                    progress("Un'altra finestra sta preparando il modello. Attendi…", -1)
                    waiting = True
                cancelled.wait(0.2)
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def verified(directory, spec, cancelled):
    """!
    @brief Verifica dimensioni e hash dei file del modello in una cartella.
    @param directory Cartella da verificare.
    @param spec Specifica con la mappa `files` dei file attesi.
    @param cancelled Evento di annullamento.
    @return True se tutti i file sono presenti e corrispondono.
    """
    for name, item in spec["files"].items():
        check_cancelled(cancelled)
        path = directory / name
        if not path.is_file() or path.stat().st_size != item["size"]:
            return False
        if digest(path, cancelled) != item["sha256"]:
            return False
    return True


def download(spec, part, cancelled, progress, opener):
    """!
    @brief Scarica l'archivio del modello in un file parziale, riprendendo se possibile.

    Usa richieste Range per riprendere un download interrotto e verifica l'hash
    finale; un file parziale che non supera la verifica viene eliminato.
    @param spec Specifica di download validata.
    @param part File parziale di destinazione.
    @param cancelled Evento di annullamento.
    @param progress Callback di avanzamento (messaggio, percentuale).
    @param opener Opener urllib usato per la richiesta.
    @throws ModelDownloadError Se risposta, dimensione o hash non sono validi.
    """
    total = spec["size"]
    offset = part.stat().st_size if part.exists() else 0
    if offset > total:
        part.unlink()
        offset = 0
    if offset != total:
        request = Request(spec["url"], headers={"User-Agent": "Anonymizer-model-setup"})
        if offset:
            request.add_header("Range", f"bytes={offset}-")
        progress("Download del modello al primo avvio…", int(offset * 100 / total))
        with opener.open(request, timeout=20) as response:
            if response.status == 206:
                expected = f"bytes {offset}-{total - 1}/{total}"
                if response.headers.get("Content-Range") != expected:
                    raise ModelDownloadError("Risposta di download non valida. Riprova.")
            elif response.status == 200:
                offset = 0
            else:
                raise ModelDownloadError("Download del modello non disponibile. Riprova.")
            last_percent = -1
            with part.open("ab" if offset else "wb") as output:
                while True:
                    check_cancelled(cancelled)
                    block = response.read(min(1024 * 1024, total - offset + 1))
                    if not block:
                        break
                    if offset + len(block) > total:
                        raise ModelDownloadError("Dimensione del download non valida.")
                    output.write(block)
                    offset += len(block)
                    percent = int(offset * 100 / total)
                    if percent != last_percent:
                        progress(
                            f"Download modello: {offset / 1_000_000:.0f} / "
                            f"{total / 1_000_000:.0f} MB",
                            percent,
                        )
                        last_percent = percent
        if offset != total:
            raise ModelDownloadError("Download interrotto. Premi Riprova per riprenderlo.")
    progress("Verifica del modello scaricato…", -1)
    if digest(part, cancelled) != spec["sha256"]:
        part.unlink()
        raise ModelDownloadError("Il download non supera la verifica di integrità. Riprova.")


def ensure_model(bundle, cancelled, progress, *, cache=None, opener=None):
    """!
    @brief Restituisce una cartella di modello verificata, scaricandolo se necessario.

    Senza specifica di download usa il modello incluso nel bundle. Altrimenti
    riusa una copia già verificata (bundle o cache) oppure scarica, estrae e
    verifica il modello in una cartella temporanea prima di spostarlo nella cache.
    @param bundle Radice del bundle portable.
    @param cancelled Evento di annullamento.
    @param progress Callback di avanzamento (messaggio, percentuale).
    @param cache Cartella della cache; None usa cache_root().
    @param opener Opener urllib; None ne crea uno che accetta solo redirect HTTPS.
    @return Cartella del modello pronta all'uso.
    @throws ModelDownloadError Se spazio, configurazione, pacchetto o verifica non
            sono validi o il download non riesce.
    """
    bundled = bundle / "models" / "gliner"
    spec_path = bundle / "model-download.json"
    if not spec_path.exists() and all((bundled / name).is_file() for name in FILES):
        return bundled
    spec = read_spec(spec_path)
    root = cache if cache is not None else cache_root()
    root.mkdir(parents=True, exist_ok=True)
    target = root / spec["sha256"]
    with model_lock(root / (spec["sha256"] + ".lock"), cancelled, progress):
        progress("Verifica del modello presente sul computer…", -1)
        for directory in (bundled, target):
            if verified(directory, spec, cancelled):
                return directory
        direct = spec["format"] == "anonymizer-model-onnx-v1"
        part = root / (spec["sha256"] + (".onnx.part" if direct else ".zip.part"))
        needed = spec["size"] + sum(f["size"] for f in spec["files"].values())
        if shutil.disk_usage(root).free < needed:
            raise ModelDownloadError("Spazio insufficiente per scaricare e preparare il modello.")
        try:
            if direct:
                for name, item in spec["files"].items():
                    if name != "model.onnx" and not verified(
                        bundled, {"files": {name: item}}, cancelled
                    ):
                        raise ModelDownloadError(
                            "Configurazione locale del modello danneggiata. Reinstalla Anonymizer."
                        )
            download(spec, part, cancelled, progress, opener or build_opener(SecureRedirect()))
            progress("Preparazione del modello per l'uso offline…", -1)
            with tempfile.TemporaryDirectory(prefix="prepare-", dir=root) as temporary:
                stage = Path(temporary) / "model"
                stage.mkdir()
                if direct:
                    for name in spec["files"]:
                        check_cancelled(cancelled)
                        shutil.copyfile(
                            part if name == "model.onnx" else bundled / name, stage / name
                        )
                else:
                    with zipfile.ZipFile(part) as archive:
                        if (
                            len(archive.infolist()) != len(FILES)
                            or set(archive.namelist()) != FILES
                        ):
                            raise ModelDownloadError("Il pacchetto del modello non è valido.")
                        for name, item in spec["files"].items():
                            if archive.getinfo(name).file_size != item["size"]:
                                raise ModelDownloadError(
                                    "Dimensione dei file del modello non valida."
                                )
                            with archive.open(name) as source, (stage / name).open("wb") as output:
                                while block := source.read(1024 * 1024):
                                    check_cancelled(cancelled)
                                    output.write(block)
                if not verified(stage, spec, cancelled):
                    raise ModelDownloadError(
                        "Il modello estratto non supera la verifica di integrità."
                    )
                check_cancelled(cancelled)
                if target.exists():
                    shutil.rmtree(target)
                stage.rename(target)
            part.unlink(missing_ok=True)
            return target
        except (OSError, http.client.HTTPException, zipfile.BadZipFile) as error:
            raise ModelDownloadError(
                "Impossibile scaricare il modello. Controlla connessione e spazio libero, "
                "poi premi Riprova. Il download incompleto verrà ripreso."
            ) from error
