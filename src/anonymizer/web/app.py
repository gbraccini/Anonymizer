"""!
@file app.py
@brief Applicazione FastAPI per la revisione locale dei documenti.

Serve l'interfaccia statica ed espone le API di analisi, anteprima ed
esportazione. Accetta solo connessioni di loopback e non conserva dati oltre la
singola richiesta.
"""

import base64
import ipaddress
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import zipfile
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from io import BytesIO
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from anonymizer.export import bind_sources, export_document
from anonymizer.ingest import InputFile, render_page
from anonymizer.ner_model import NerError
from anonymizer.performance import choose_profile
from anonymizer.pipeline import analyze_documents
from anonymizer.redact import apply_redactions
from anonymizer.version import VERSION
from anonymizer.visual_model import DEFAULT_LIMITS, DocumentError, review_digest
from anonymizer.web.review import ReviewSigner, apply_review
from anonymizer.web.text import document_text, page_text

## Cartella delle risorse statiche dell'interfaccia.
STATIC = Path(__file__).with_name("static")


def error(code, status=400):
    """!
    @brief Crea una risposta JSON d'errore.
    @param code Codice d'errore.
    @param status Stato HTTP.
    @return Risposta JSON con il codice d'errore.
    """
    return JSONResponse({"error": code}, status_code=status)


class LocalBoundary:
    """!
    @brief Middleware ASGI che confina il servizio all'uso locale.

    Ammette solo client di loopback con Host locale, richiede la stessa origine per
    le richieste che modificano stato, consente una sola operazione alla volta,
    limita la dimensione del corpo e aggiunge intestazioni di sicurezza a ogni
    risposta.
    """

    def __init__(self, app, max_body):
        """!
        @brief Crea il middleware.
        @param app Applicazione ASGI interna.
        @param max_body Dimensione massima del corpo della richiesta in byte.
        """
        self.app, self.max_body, self.busy = app, max_body, False

    async def __call__(self, scope, receive, send):
        """!
        @brief Applica i controlli e inoltra la richiesta all'applicazione interna.

        Per le richieste che modificano stato il corpo viene letto per intero prima di
        inoltrarlo, così il limite di dimensione vale anche senza Content-Length.
        @param scope Scope ASGI della connessione.
        @param receive Canale ASGI di ricezione.
        @param send Canale ASGI di invio.
        """
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        host = headers.get("host", "")
        try:
            parsed = urlsplit("http://" + host)
            peer = ipaddress.ip_address(scope["client"][0]).is_loopback
            valid_host = parsed.hostname in ("localhost", "127.0.0.1", "::1") and not parsed.path
        except (ValueError, TypeError, AttributeError):
            peer = False
            valid_host = False
        if not peer or not valid_host:
            return await error("local_access_only", 403)(scope, receive, send)
        mutation = scope["method"] not in ("GET", "HEAD")
        if mutation and headers.get("origin") != f"{scope['scheme']}://{host}":
            return await error("same_origin_required", 403)(scope, receive, send)
        if mutation and self.busy:
            return await error("operation_busy", 503)(scope, receive, send)
        if mutation:
            self.busy = True
        try:
            if mutation:
                parts, size = [], 0
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    block = message.get("body", b"")
                    size += len(block)
                    if size > self.max_body:
                        return await error("upload_byte_limit", 413)(scope, receive, send)
                    parts.append(block)
                    if not message.get("more_body", False):
                        break
                body = b"".join(parts)
                parts.clear()
                delivered = False
                original_receive = receive

                async def replay():
                    """!
                    @brief Riconsegna una sola volta il corpo già letto.

                    Le chiamate successive sono delegate al receive originale.
                    @return Messaggio ASGI di richiesta.
                    """
                    nonlocal delivered
                    if not delivered:
                        delivered = True
                        return {"type": "http.request", "body": body, "more_body": False}
                    return await original_receive()

                receive = replay

            async def secure_send(message):
                """!
                @brief Aggiunge le intestazioni di sicurezza all'inizio della risposta.
                @param message Messaggio ASGI da inviare.
                """
                if message["type"] == "http.response.start":
                    message["headers"] += [
                        (b"cache-control", b"no-store"),
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"no-referrer"),
                        (
                            b"content-security-policy",
                            b"default-src 'self'; img-src 'self' data: blob:; "
                            b"style-src 'self'; script-src 'self'; frame-ancestors 'none'; "
                            b"base-uri 'none'; form-action 'self'",
                        ),
                    ]
                await send(message)

            await self.app(scope, receive, secure_send)
        finally:
            if mutation:
                self.busy = False


def probe_ocr():
    """!
    @brief Verifica che Tesseract sia disponibile con la lingua italiana.
    @return "ready", "failed" oppure "unavailable".
    """
    executable = os.environ.get("ANONYMIZER_TESSERACT") or shutil.which("tesseract")
    if not executable:
        return "unavailable"
    args = [executable, "--list-langs"]
    if directory := os.environ.get("ANONYMIZER_TESSDATA"):
        args.extend(["--tessdata-dir", directory])
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            timeout=10,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return "ready" if result.returncode == 0 and b"ita" in result.stdout.split() else "failed"
    except (OSError, subprocess.SubprocessError):
        return "failed"


def preview(inputs, manifest, index, limits):
    """!
    @brief Genera l'anteprima di una pagina, originale e oscurata.

    Le maschere sono applicate come confermate; le immagini sono ridotte a 1800 px
    e codificate in PNG senza metadati.
    @param inputs File sorgente caricati.
    @param manifest Manifest revisionato.
    @param index Indice della pagina da mostrare.
    @param limits Limiti di elaborazione.
    @return Dizionario con immagini in base64, dimensioni, digest di revisione,
            testo della pagina e tempi.
    @throws DocumentError Se l'indice di pagina non è valido.
    """
    started = perf_counter()
    originals = bind_sources(inputs, manifest, limits)
    if type(index) is not int or not 0 <= index < len(manifest.pages):
        raise DocumentError("invalid_preview_page")
    page = manifest.pages[index]
    original = originals[(page.page.source_id, page.source_page_index)]
    image = render_page(original)
    try:
        masks = tuple(replace(mask, confirmed=True) for mask in page.redactions)
        masked = apply_redactions(image, masks, page.geometry)
        try:
            images = []
            for item in (image, masked):
                resized = item.copy()
                try:
                    resized.thumbnail((1800, 1800))
                    buffer = BytesIO()
                    resized.save(buffer, "PNG", exif=b"", icc_profile=None)
                    images.append(base64.b64encode(buffer.getvalue()).decode())
                finally:
                    resized.close()
        finally:
            masked.close()
    finally:
        image.close()
    return dict(
        original=images[0],
        redacted=images[1],
        width=page.geometry.width,
        height=page.geometry.height,
        preview_digest=review_digest(manifest),
        text=page_text(page, include_lines=True),
        timings={"preview": perf_counter() - started},
    )


def create_app(
    *,
    local_only=False,
    ner_config=None,
    ner=None,
    limits=DEFAULT_LIMITS,
    ner_threads=None,
    execution_profile=None,
):
    """!
    @brief Crea l'applicazione FastAPI di revisione in modalità solo locale.

    Risolve il numero di thread NER verificando la coerenza tra rilevatore già
    caricato, configurazione e profilo di esecuzione.
    @param local_only Deve valere True: la modalità solo locale è obbligatoria.
    @param ner_config Configurazione per caricare il NER all'avvio.
    @param ner Rilevatore NER già caricato.
    @param limits Limiti di elaborazione.
    @param ner_threads Numero esplicito di thread NER.
    @param execution_profile Profilo di esecuzione da usare.
    @return L'applicazione FastAPI configurata.
    @throws ValueError Se manca la modalità solo locale o le impostazioni dei thread
            sono in conflitto.
    """
    if local_only is not True:
        raise ValueError("explicit_local_only_mode_required")
    loaded_threads = getattr(getattr(ner, "config", None), "cpu_threads", None)
    if loaded_threads is None:
        loaded_threads = getattr(getattr(ner, "audit", None), "cpu_threads", None)
    configured_threads = getattr(ner_config, "cpu_threads", None)
    explicit_threads = (
        ner_threads if ner_threads is not None else configured_threads or loaded_threads
    )
    if loaded_threads is not None and explicit_threads != loaded_threads:
        raise ValueError("loaded_ner_thread_override_conflict")
    if execution_profile is not None and explicit_threads is not None:
        if execution_profile.ner_threads != explicit_threads:
            raise ValueError("execution_profile_thread_override_conflict")
    execution_profile = execution_profile or choose_profile(ner_threads=explicit_threads)
    if ner_config is not None and hasattr(ner_config, "cpu_threads"):
        ner_config = replace(ner_config, cpu_threads=execution_profile.ner_threads)
    execution_location = os.environ.get("ANONYMIZER_EXECUTION_LOCATION", "this_computer")

    @asynccontextmanager
    async def lifespan(app):
        """!
        @brief Inizializza NER, firmatario dei contratti e stato OCR; li rilascia alla chiusura.
        @param app Applicazione FastAPI.
        """
        started = perf_counter()
        app.state.ner, app.state.ner_status = ner, "ready" if ner else "disabled"
        if ner_config is not None:
            try:
                from anonymizer.detect.ner import GLiNERDetector

                app.state.ner = await run_in_threadpool(GLiNERDetector, ner_config)
                app.state.ner_status = "ready"
            except Exception:
                app.state.ner_status = "failed"
        app.state.signer = ReviewSigner(secrets.token_bytes(32))
        app.state.ocr = await run_in_threadpool(probe_ocr)
        app.state.startup_seconds = perf_counter() - started
        yield
        app.state.ner = None
        app.state.signer = None

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(LocalBoundary, max_body=limits.max_bytes + 8_000_000)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.exception_handler(Exception)
    async def failure(request, exception):
        """!
        @brief Converte le eccezioni non gestite in risposte d'errore senza dettagli interni.
        @param request Richiesta che ha causato l'errore.
        @param exception Eccezione sollevata.
        @return Risposta JSON d'errore.
        """
        code = (
            exception.code
            if isinstance(exception, (DocumentError, NerError))
            else "operation_failed"
        )
        return error(code)

    @app.get("/", response_class=HTMLResponse)
    async def home():
        """!
        @brief Restituisce la pagina principale con la versione dell'applicazione.
        @return Pagina HTML.
        """
        return HTMLResponse(
            (STATIC / "index.html").read_text("utf-8").replace("{{APP_VERSION}}", VERSION)
        )

    @app.get("/api/health")
    async def health():
        """!
        @brief Riporta versione, stato dei componenti, limiti e profilo di esecuzione.
        @return Dizionario serializzato in JSON.
        """
        return dict(
            version=VERSION,
            mode="local_only",
            execution_location=execution_location,
            ner=app.state.ner_status,
            ocr=app.state.ocr,
            startup_seconds=app.state.startup_seconds,
            limits=vars(limits),
            persistence="request_only",
            workers=1,
            performance=asdict(execution_profile),
        )

    @app.post("/api/{operation}")
    async def operation(operation: str, request: Request):
        """!
        @brief Esegue un'operazione sui documenti caricati.

        `analyze` restituisce un contratto firmato con il manifest; `preview`, `export`
        e `text-export` verificano il contratto, applicano le modifiche di revisione e
        producono rispettivamente anteprima, documento esportato (PDF/PNG, oppure ZIP
        con PDF e testo) o testo oscurato.
        @param operation Nome dell'operazione.
        @param request Richiesta multipart con file e campi di revisione.
        @return Risposta JSON o binaria.
        """
        if operation not in ("analyze", "preview", "export", "text-export"):
            return error("unknown_operation", 404)
        try:
            async with request.form(
                max_files=limits.max_files, max_fields=8, max_part_size=8_000_000
            ) as form:
                uploads = form.getlist("files")
                if not uploads or any(not isinstance(file, UploadFile) for file in uploads):
                    raise DocumentError("missing_input_files")
                inputs, size = [], 0
                for upload in uploads:
                    data = await upload.read(limits.max_bytes + 1)
                    size += len(data)
                    if size > limits.max_bytes:
                        raise DocumentError("upload_byte_limit")
                    inputs.append(InputFile(data, Path(upload.filename or "").suffix.lower()))
                inputs = tuple(inputs)
                if operation == "analyze":
                    if app.state.ner_status == "failed":
                        return error("ner_model_load_failed", 503)
                    dpi = int(form.get("dpi", "300"))
                    analysis = await run_in_threadpool(
                        analyze_documents,
                        inputs,
                        limits=limits,
                        dpi=dpi,
                        ner=app.state.ner,
                        execution_profile=execution_profile,
                    )
                    contract, signature = app.state.signer.issue(analysis.manifest)
                    return dict(contract=contract, signature=signature, timings=analysis.timings)
                contract = json.loads(form["contract"])
                base = app.state.signer.verify(contract, form["signature"])
                edits = json.loads(form["review"])
                manifest = apply_review(base, edits, final=operation in ("export", "text-export"))
                if operation == "preview":
                    return await run_in_threadpool(
                        preview,
                        inputs,
                        manifest,
                        int(form.get("page", "0")),
                        limits,
                    )
                if operation == "text-export":
                    await run_in_threadpool(bind_sources, inputs, manifest, limits)
                    text = await run_in_threadpool(document_text, manifest)
                    return Response(text, media_type="text/plain; charset=utf-8")
                format = form.get("format", "pdf")
                if format not in ("png", "pdf"):
                    raise DocumentError("invalid_export_format")
                include_text = form.get("include_text", "false")
                if include_text not in ("true", "false") or (
                    include_text == "true" and format != "pdf"
                ):
                    raise DocumentError("invalid_export_format")
                started = perf_counter()
                timings = {}

                def generate():
                    """!
                    @brief Esporta il documento in una cartella temporanea e ne restituisce i byte.
                    @return Contenuto del file esportato o dell'archivio ZIP.
                    """
                    with tempfile.TemporaryDirectory(prefix="anonymizer-export-") as directory:
                        path = Path(directory) / f"redacted.{format}"
                        export_document(inputs, manifest, path, limits=limits, timings=timings)
                        if include_text == "true":
                            buffer = BytesIO()
                            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                                archive.writestr("documento-oscurato.pdf", path.read_bytes())
                                archive.writestr("testo-oscurato.txt", document_text(manifest))
                            return buffer.getvalue()
                        return path.read_bytes()

                data = await run_in_threadpool(generate)
                return Response(
                    data,
                    media_type=(
                        "application/zip"
                        if include_text == "true"
                        else "image/png"
                        if format == "png"
                        else "application/pdf"
                    ),
                    headers={
                        "Content-Disposition": (
                            'attachment; filename="documento-oscurato.'
                            + ("zip" if include_text == "true" else format)
                            + '"'
                        ),
                        "X-Export-Seconds": str(perf_counter() - started),
                        "X-Phase-Timings": json.dumps(timings),
                    },
                )
        except Exception as exception:
            code = (
                exception.code
                if isinstance(exception, (DocumentError, NerError))
                else "operation_failed"
            )
            status = 413 if code == "upload_byte_limit" else 400
            if code.startswith("unsupported_"):
                status = 415
            return error(code, status)

    return app
