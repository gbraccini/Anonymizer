"""!
@file desktop.py
@brief Host desktop Windows che riusa senza modifiche l'applicazione di revisione locale.

Avvia il backend web in un processo Python isolato, ne attende la disponibilità e
apre la finestra Qt. Lo stesso modulo fa da punto di ingresso del backend
(opzione `--backend`).
"""

import argparse
import ctypes
import json
import os
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.request import ProxyHandler, build_opener


class DesktopError(ValueError):
    """!
    @brief Errore dell'host desktop con un messaggio in italiano da mostrare all'utente.
    """

    pass


@dataclass(frozen=True)
class Resources:
    """!
    @brief Percorsi delle risorse del bundle portable.
    """

    ## Cartella radice del bundle.
    root: Path
    ## Cartella del modello NER alternativa; None usa quella del bundle.
    model_path: Path | None = None

    @property
    def python(self):
        """!
        @brief Interprete Python senza console del runtime incluso.
        @return Percorso di pythonw.exe.
        """
        return self.root / "runtime" / "pythonw.exe"

    @property
    def model(self):
        """!
        @brief Cartella effettiva del modello NER.
        @return model_path se impostato, altrimenti models/gliner del bundle.
        """
        return self.model_path or self.root / "models" / "gliner"

    @property
    def ocr(self):
        """!
        @brief Eseguibile Tesseract incluso nel bundle.
        @return Percorso di tesseract.exe.
        """
        return self.root / "ocr" / "tesseract.exe"

    def validate(self, *, require_model=True):
        """!
        @brief Verifica che i file indispensabili del bundle siano presenti.
        @param require_model Se True richiede anche i file del modello ONNX.
        @throws DesktopError Se manca almeno un file.
        """
        required = (
            self.python,
            self.ocr,
            self.root / "ocr" / "tessdata" / "ita.traineddata",
            *(
                self.model / name
                for name in (
                    "anonymizer_model.json",
                    "model.onnx",
                    "gliner_config.json",
                    "tokenizer.json",
                    "tokenizer_config.json",
                )
                if require_model
            ),
            self.root
            / "runtime"
            / "Lib"
            / "site-packages"
            / "anonymizer"
            / "web"
            / "static"
            / "index.html",
        )
        if not all(path.is_file() for path in required):
            raise DesktopError(
                "File dell'applicazione mancanti. Ripristina la cartella portable completa."
            )


def backend_environment(resources, session):
    """!
    @brief Costruisce le variabili d'ambiente del processo backend.

    Rimuove le variabili che farebbero caricare un Python o dati Tesseract estranei,
    forza la modalità offline dei componenti Hugging Face, confina cache e file
    temporanei nella cartella di sessione e limita i thread nativi.
    @param resources Risorse del bundle.
    @param session Cartella di sessione temporanea.
    @return Dizionario delle variabili d'ambiente.
    """
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper()
        not in (
            "PYTHONHOME",
            "PYTHONPATH",
            "VIRTUAL_ENV",
            "CONDA_PREFIX",
            "TESSDATA_PREFIX",
        )
        and not key.upper().startswith("_PYI_")
    }
    environment.update(
        ANONYMIZER_TESSERACT=str(resources.ocr),
        ANONYMIZER_TESSDATA=str(resources.root / "ocr" / "tessdata"),
        ANONYMIZER_EXECUTION_LOCATION="this_computer",
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        HF_HUB_DISABLE_IMPLICIT_TOKEN="1",
        HF_HUB_DISABLE_TELEMETRY="1",
        HF_HOME=str(session / "cache"),
        TOKENIZERS_PARALLELISM="false",
        TMP=str(session),
        TEMP=str(session),
        TMPDIR=str(session),
        PYTHONDONTWRITEBYTECODE="1",
        OMP_NUM_THREADS="4",
        OMP_THREAD_LIMIT="4",
        MKL_NUM_THREADS="4",
    )
    return environment


def probe_health(port):
    """!
    @brief Interroga l'endpoint di salute del backend locale ignorando eventuali proxy.
    @param port Porta locale del backend.
    @return True se il backend è in modalità solo locale con NER e OCR pronti.
    @throws DesktopError Se il modello NER o l'OCR italiano non sono disponibili.
    """
    with build_opener(ProxyHandler({})).open(
        f"http://127.0.0.1:{port}/api/health", timeout=1
    ) as response:
        health = json.loads(response.read(16_384))
    if health.get("ner") == "failed":
        raise DesktopError(
            "Il modello locale non si avvia. Ripristina la cartella portable completa."
        )
    if health.get("ocr") in ("failed", "unavailable"):
        raise DesktopError(
            "OCR italiano non disponibile. Ripristina la cartella portable completa."
        )
    return health.get("mode") == "local_only" and health.get("ner") == health.get("ocr") == "ready"


class Backend:
    """!
    @brief Gestisce il ciclo di vita del processo backend locale.
    """

    def __init__(self, resources, session):
        """!
        @brief Prepara il gestore senza avviare il processo.
        @param resources Risorse del bundle.
        @param session Cartella di sessione condivisa con il backend.
        """
        self.resources, self.session, self.process = resources, session, None
        self.lock, self.stopped = threading.Lock(), False

    def start(self):
        """!
        @brief Avvia il processo backend isolato e senza finestra.

        Rimuove prima i file di coordinamento lasciati da un avvio precedente.
        @return False se il gestore è già stato fermato, altrimenti True.
        """
        with self.lock:
            if self.stopped:
                return False
            self.resources.validate()
            for name in ("stop", "backend.json"):
                (self.session / name).unlink(missing_ok=True)
            self.process = subprocess.Popen(
                [
                    str(self.resources.python),
                    "-I",
                    "-B",
                    "-m",
                    "anonymizer.desktop",
                    "--backend",
                    "--bundle-root",
                    str(self.resources.root),
                    "--session",
                    str(self.session),
                    "--model-path",
                    str(self.resources.model),
                ],
                cwd=self.resources.root,
                env=backend_environment(self.resources, self.session),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True

    def wait_ready(self, cancelled, *, timeout=180, probe=probe_health):
        """!
        @brief Attende che il backend pubblichi la porta e risulti pronto.
        @param cancelled Evento che interrompe l'attesa.
        @param timeout Secondi massimi di attesa.
        @param probe Funzione che verifica la salute del backend su una porta.
        @return URL base del backend, oppure None se l'attesa è stata annullata.
        @throws DesktopError Se il processo termina o segnala un errore, se la porta
                pubblicata non è valida o se il tempo scade.
        """
        deadline = time.monotonic() + timeout
        while not cancelled.is_set() and time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise DesktopError(
                    "Il servizio locale non si avvia. Ripristina la cartella portable completa."
                )
            try:
                state = json.loads((self.session / "backend.json").read_text("utf-8"))
                if state.get("error"):
                    raise DesktopError("Avvio del servizio locale non riuscito.")
                port = state["port"]
                if type(port) is not int or not 1024 <= port <= 65535:
                    raise DesktopError("Risposta del servizio locale non valida.")
                if probe(port):
                    return f"http://127.0.0.1:{port}"
            except (OSError, KeyError, json.JSONDecodeError):
                pass
            cancelled.wait(0.1)
        if cancelled.is_set():
            return None
        raise DesktopError("Avvio troppo lungo. Chiudi e riapri Anonymizer.")

    def stop(self):
        """!
        @brief Ferma il backend in modo cooperativo, terminandolo se non esce in tempo.

        L'arresto è segnalato dal file `stop` nella cartella di sessione.
        """
        with self.lock:
            self.stopped = True
            if self.process is None:
                return
        (self.session / "stop").touch()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


def run_backend(resources, session):
    """!
    @brief Corpo del processo backend: serve l'applicazione su una porta effimera di loopback.

    Pubblica la porta in `backend.json` e termina quando compare il file `stop`
    nella cartella di sessione.
    @param resources Risorse del bundle.
    @param session Cartella di sessione condivisa con la finestra.
    """
    from anonymizer.performance import choose_profile, configure_process_startup

    profile = choose_profile()
    # This is the dedicated backend's startup, before importing native inference libraries.
    configure_process_startup(profile)
    import uvicorn

    from anonymizer.ner_model import NerConfig
    from anonymizer.web.app import create_app

    resources.validate()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        app = create_app(
            local_only=True,
            ner_config=NerConfig(
                resources.model,
                runtime="onnx",
                cpu_threads=profile.ner_threads,
            ),
            execution_profile=profile,
        )
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=port,
                workers=1,
                access_log=False,
                proxy_headers=False,
                log_level="critical",
            )
        )
        (session / "backend.json").write_text(json.dumps({"port": port}), encoding="utf-8")

        def watch_close():
            """!
            @brief Chiede l'arresto del server quando compare il file di stop.
            """
            while not server.should_exit:
                if (session / "stop").exists():
                    server.should_exit = True
                    return
                time.sleep(0.2)

        threading.Thread(target=watch_close, daemon=True).start()
        server.run(sockets=[listener])


def error_dialog(message):
    """!
    @brief Mostra una finestra di errore nativa di Windows.
    @param message Testo da mostrare.
    """
    ctypes.windll.user32.MessageBoxW(None, message, "Anonymizer", 0x10)


## Pagina mostrata durante l'avvio; il commento HTML `brand` segna dove inserire il logo.
LOADING_HTML = """<!doctype html><html lang="it"><meta charset="utf-8">
<title>Anonymizer</title><style>
.startup-status{display:flex;align-items:center;justify-content:center;gap:12px}
.startup-spinner{width:22px;height:22px;border:3px solid #b9d7d0;border-top-color:#087f77;
border-radius:50%;animation:startup-spin 1s linear infinite}
@keyframes startup-spin{to{transform:rotate(360deg)}}
@media(prefers-reduced-motion:reduce){.startup-spinner{animation:none}}
</style><body style="font-family:Segoe UI,sans-serif;background:#f4f8f7;
color:#173139;display:grid;place-content:center;min-height:90vh;text-align:center">
<!--brand--><h1>Anonymizer</h1><p class="startup-status" role="status" aria-live="polite">
<span class="startup-spinner" aria-hidden="true"></span>Avvio di OCR e modello locale...</p>
<p>Il primo avvio potrebbe richiedere qualche istante.</p></body></html>"""


def run_window(resources):
    """!
    @brief Prepara il processo e apre la finestra Qt di revisione.

    Imposta l'identificativo dell'applicazione per la barra delle applicazioni e
    rimuove le variabili Qt esterne che potrebbero alterare il runtime incluso.
    @param resources Risorse del bundle.
    @return Codice di uscita del ciclo eventi Qt.
    """
    if os.name == "nt":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("GianlucaBraccini.Anonymizer")
    for name in tuple(os.environ):
        if name.upper().startswith(("QT_", "QTWEBENGINE", "QML_", "QML2_")):
            os.environ.pop(name)
    from anonymizer.desktop_qt import run_window as run_qt_window

    return run_qt_window(resources)


def main(argv=None):
    """!
    @brief Punto di ingresso dell'host desktop e del processo backend.

    Con --backend esegue il server e segnala i fallimenti di avvio in
    `backend.json`; altrimenti apre la finestra e mostra gli errori in un dialogo.
    @param argv Argomenti da analizzare; None usa quelli del processo.
    @return Codice di uscita del processo.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--backend", action="store_true")
    parser.add_argument("--session", type=Path)
    parser.add_argument("--model-path", type=Path)
    args = parser.parse_args(argv)
    resources = Resources(args.bundle_root.resolve(), args.model_path)
    if args.backend:
        if args.session is None:
            return 1
        try:
            run_backend(resources, args.session)
            return 0
        except Exception:
            (args.session / "backend.json").write_text('{"error":"backend_start_failed"}')
            return 1
    try:
        run_window(resources)
        return 0
    except Exception as exception:
        error_dialog(
            str(exception)
            if isinstance(exception, DesktopError)
            else (
                "Impossibile aprire Anonymizer. Ripristina la cartella portable completa, "
                "inclusi i componenti Qt forniti con l'applicazione."
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
