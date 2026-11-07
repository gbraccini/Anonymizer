"""!
@file desktop_qt.py
@brief Host Qt in sessione privata per l'interfaccia di revisione locale condivisa.

Incapsula l'interfaccia web in un QWebEngineView con profilo non persistente,
limita richieste e navigazione all'origine del backend locale e gestisce il
salvataggio dei documenti esportati.
"""

import html
import shutil
import tempfile
import threading
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWebEngineCore import (
    QWebEngineDownloadRequest,
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineSettings,
    QWebEngineUrlRequestInterceptor,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox, QPushButton

from anonymizer.desktop import LOADING_HTML, Backend, DesktopError
from anonymizer.model_download import DownloadCancelled, ModelDownloadError, ensure_model
from anonymizer.version import VERSION

## Cartella delle risorse statiche dell'interfaccia web.
STATIC = Path(__file__).resolve().parent / "web" / "static"


def application_icon():
    """!
    @brief Crea l'icona dell'applicazione dalle immagini PNG incluse.
    @return Icona con le risoluzioni disponibili.
    """
    icon = QIcon()
    for size in (256, 512):
        icon.addFile(str(STATIC / f"anonymizer-{size}.png"))
    return icon


class OriginPolicy:
    """!
    @brief Politica che limita richieste e navigazione all'origine del backend locale.

    Durante il bootstrap, prima che l'origine sia nota, sono ammesse solo
    about:blank e le pagine HTML inline usate per lo stato di avvio.
    """

    def __init__(self):
        """!
        @brief Crea la politica in fase di bootstrap, senza origine associata.
        """
        self.origin = None
        self.bootstrap = True

    @staticmethod
    def origin_of(url):
        """!
        @brief Estrae l'origine di un URL se è un indirizzo HTTP di loopback valido.
        @param url URL da analizzare.
        @return Tupla (schema, host, porta), oppure None se l'URL non è ammesso.
        """
        try:
            parsed = urlsplit(url)
            if parsed.username is not None or parsed.password is not None:
                return None
            if parsed.scheme != "http" or parsed.hostname != "127.0.0.1":
                return None
            if parsed.port is None or not 1024 <= parsed.port <= 65535:
                return None
            return parsed.scheme, parsed.hostname, parsed.port
        except ValueError:
            return None

    def bind(self, url):
        """!
        @brief Associa la politica all'origine del backend e chiude il bootstrap.
        @param url URL del backend.
        @throws DesktopError Se l'URL non è un'origine locale valida.
        """
        origin = self.origin_of(url)
        if origin is None:
            raise DesktopError("Indirizzo del servizio locale non valido.")
        self.origin, self.bootstrap = origin, False

    def local(self, url):
        """!
        @brief Indica se l'URL appartiene all'origine associata.
        @param url URL da verificare.
        @return True se l'origine coincide con quella associata.
        """
        return self.origin is not None and self.origin_of(url) == self.origin

    def blob(self, url):
        """!
        @brief Indica se l'URL è un blob creato dall'origine associata.
        @param url URL da verificare.
        @return True se è un blob dell'origine locale.
        """
        return url.startswith("blob:") and self.local(url[5:])

    def request_allowed(self, url):
        """!
        @brief Decide se una richiesta di rete è ammessa.

        Oltre all'origine locale e ai suoi blob consente le immagini inline.
        @param url URL richiesto.
        @return True se la richiesta è ammessa.
        """
        return (
            self.local(url)
            or self.blob(url)
            or url.startswith("data:image/")
            or (self.bootstrap and (url == "about:blank" or url.startswith("data:text/html")))
        )

    def navigation_allowed(self, url):
        """!
        @brief Decide se una navigazione è ammessa.
        @param url URL di destinazione.
        @return True se la navigazione è ammessa.
        """
        return (
            self.local(url)
            or self.blob(url)
            or (self.bootstrap and (url == "about:blank" or url.startswith("data:text/html")))
        )


class RequestBoundary(QWebEngineUrlRequestInterceptor):
    """!
    @brief Intercettore che blocca le richieste non ammesse dalla politica di origine.
    """

    def __init__(self, policy, parent=None):
        """!
        @brief Crea l'intercettore.
        @param policy Politica di origine da applicare.
        @param parent Oggetto Qt proprietario.
        """
        super().__init__(parent)
        self.policy = policy

    def interceptRequest(self, info):
        """!
        @brief Blocca la richiesta se la politica non la consente.
        @param info Informazioni sulla richiesta fornite da Qt WebEngine.
        """
        if not self.policy.request_allowed(info.requestUrl().toString()):
            info.block(True)


class ReviewPage(QWebEnginePage):
    """!
    @brief Pagina web con le funzionalità del browser ridotte al minimo necessario.

    Disabilita popup, archiviazione locale, accesso a file e URL remoti, plugin e
    visualizzatore PDF; nega permessi e accesso al file system, lasciando solo
    l'accesso agli appunti.
    """

    def __init__(self, profile, policy, parent=None):
        """!
        @brief Crea la pagina e applica le restrizioni.
        @param profile Profilo WebEngine privato.
        @param policy Politica di origine per le navigazioni.
        @param parent Oggetto Qt proprietario.
        """
        super().__init__(profile, parent)
        self.policy = policy
        settings = self.settings()
        for attribute in (
            "JavascriptCanOpenWindows",
            "JavascriptCanPaste",
            "LocalStorageEnabled",
            "LocalContentCanAccessFileUrls",
            "LocalContentCanAccessRemoteUrls",
            "PluginsEnabled",
            "DnsPrefetchEnabled",
            "NavigateOnDropEnabled",
            "PdfViewerEnabled",
        ):
            settings.setAttribute(getattr(QWebEngineSettings.WebAttribute, attribute), False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)
        self.permissionRequested.connect(lambda request: request.deny())
        self.fileSystemAccessRequested.connect(lambda request: request.reject())

    def acceptNavigationRequest(self, url, _kind, _main_frame):
        """!
        @brief Consente solo le navigazioni ammesse dalla politica.
        @param url URL di destinazione.
        @param _kind Tipo di navigazione (ignorato).
        @param _main_frame Indica se riguarda il frame principale (ignorato).
        @return True se la navigazione è ammessa.
        """
        return self.policy.navigation_allowed(url.toString())

    def createWindow(self, _kind):
        """!
        @brief Impedisce l'apertura di nuove finestre.
        @param _kind Tipo di finestra richiesta (ignorato).
        @return Sempre None.
        """
        return None

    def javaScriptConsoleMessage(self, _level, _message, _line, _source):
        """!
        @brief Scarta i messaggi della console JavaScript.
        @param _level Livello del messaggio (ignorato).
        @param _message Testo del messaggio (ignorato).
        @param _line Riga di origine (ignorata).
        @param _source Sorgente del messaggio (ignorata).
        """
        # Extracted document text must not enter native diagnostic logs.
        pass


def private_profile(parent, policy):
    """!
    @brief Crea un profilo WebEngine privato senza dati persistenti.

    Usa cache solo in memoria, nessun cookie o permesso persistente e installa
    l'intercettore delle richieste, il cui riferimento è conservato sul profilo per
    evitarne la distruzione.
    @param parent Oggetto Qt proprietario.
    @param policy Politica di origine per le richieste.
    @return Il profilo configurato.
    @throws DesktopError Se il profilo non è in modalità off-the-record.
    """
    profile = QWebEngineProfile(parent)
    if not profile.isOffTheRecord():
        raise DesktopError("Impossibile attivare la sessione privata.")
    profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
    profile.setPersistentCookiesPolicy(
        QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies
    )
    profile.setPersistentPermissionsPolicy(
        QWebEngineProfile.PersistentPermissionsPolicy.AskEveryTime
    )
    boundary = RequestBoundary(policy, profile)
    profile.setUrlRequestInterceptor(boundary)
    profile._boundary = boundary
    return profile


class Downloads:
    """!
    @brief Salva i download dell'interfaccia nel percorso scelto dall'utente.

    Il file viene scaricato in una cartella temporanea della sessione e copiato
    nella destinazione solo a download completato, senza sovrascrivere file
    esistenti.
    """

    def __init__(self, parent, policy, session, choose=None, notify=None):
        """!
        @brief Crea il gestore dei download.
        @param parent Finestra proprietaria dei dialoghi.
        @param policy Politica di origine che stabilisce i download ammessi.
        @param session Cartella di sessione per i file temporanei.
        @param choose Funzione che sceglie il percorso di salvataggio; None usa il
               dialogo Qt.
        @param notify Funzione che segnala un errore; None usa un avviso Qt.
        """
        self.parent, self.policy, self.session = parent, policy, session
        self.choose = choose or self.choose_path
        self.notify = notify or self.show_error
        self.active = {}
        self.closed = False

    def choose_path(self, filename):
        """!
        @brief Chiede all'utente dove salvare il documento.
        @param filename Nome di file proposto.
        @return Percorso scelto, oppure stringa vuota se l'utente annulla.
        """
        return QFileDialog.getSaveFileName(self.parent, "Salva il documento", filename)[0]

    def show_error(self):
        """!
        @brief Mostra l'avviso di salvataggio non riuscito.
        """
        QMessageBox.warning(
            self.parent,
            "Anonymizer",
            "Salvataggio non riuscito. Scegli un nuovo percorso e riprova.",
        )

    def requested(self, request):
        """!
        @brief Gestisce una nuova richiesta di download.

        Accetta solo download dall'origine locale o dai suoi blob, chiede la
        destinazione e rifiuta percorsi già esistenti.
        @param request Richiesta di download Qt.
        """
        url = request.url().toString()
        if self.closed or not (self.policy.local(url) or self.policy.blob(url)):
            request.cancel()
            return
        filename = Path(request.downloadFileName()).name or "documento-oscurato.pdf"
        selected = self.choose(filename)
        if not selected:
            request.cancel()
            return
        destination = Path(selected)
        if self.closed or destination.exists():
            request.cancel()
            if not self.closed:
                self.notify()
            return
        staging = tempfile.TemporaryDirectory(
            prefix="download-", dir=self.session, ignore_cleanup_errors=True
        )
        key = id(request)
        self.active[key] = (request, destination, staging)
        request.setDownloadDirectory(staging.name)
        request.setDownloadFileName("payload")
        request.isFinishedChanged.connect(lambda: self.finished(key))
        request.accept()

    def finished(self, key):
        """!
        @brief Completa un download copiando il file nella destinazione scelta.

        Se la copia fallisce rimuove il file parziale e avvisa l'utente; la cartella
        temporanea viene sempre eliminata.
        @param key Identificativo del download attivo.
        """
        item = self.active.get(key)
        if item is None or not item[0].isFinished():
            return
        request, destination, staging = self.active.pop(key)
        created = False
        try:
            if not self.closed and request.state() == (
                QWebEngineDownloadRequest.DownloadState.DownloadCompleted
            ):
                with destination.open("xb") as output:
                    created = True
                    with (Path(staging.name) / "payload").open("rb") as source:
                        shutil.copyfileobj(source, output)
            elif not self.closed and request.state() != (
                QWebEngineDownloadRequest.DownloadState.DownloadCancelled
            ):
                self.notify()
        except OSError:
            if created:
                destination.unlink(missing_ok=True)
            if not self.closed:
                self.notify()
        finally:
            staging.cleanup()

    def close(self):
        """!
        @brief Annulla i download in corso e ne elimina i file temporanei.
        """
        self.closed = True
        for key in list(self.active):
            item = self.active.get(key)
            if item is not None:
                item[0].cancel()
            item = self.active.pop(key, None)
            if item is not None:
                item[2].cleanup()


class StartupSignals(QObject):
    """!
    @brief Segnali Qt che riportano sul thread dell'interfaccia l'esito dell'avvio.
    """

    ## Emesso con l'URL del backend pronto.
    ready = Signal(str)
    ## Emesso con il messaggio d'errore da mostrare.
    failed = Signal(str)
    ## Emesso con messaggio e percentuale di avanzamento (-1 se indeterminata).
    progress = Signal(str, int)


class ReviewWindow(QMainWindow):
    """!
    @brief Finestra principale: mostra lo stato di avvio e poi l'interfaccia di revisione.
    """

    def __init__(self, resources, session, backend_factory=Backend):
        """!
        @brief Costruisce finestra, pagina privata e schermata di caricamento.
        @param resources Risorse del bundle.
        @param session Cartella di sessione temporanea.
        @param backend_factory Fabbrica del gestore del backend.
        """
        super().__init__()
        self.setWindowTitle(f"Anonymizer {VERSION}")
        self.setWindowIcon(application_icon())
        self.resize(1440, 900)
        self.setMinimumSize(900, 650)
        self.policy, self.cancelled = OriginPolicy(), threading.Event()
        self.stopping = False
        self.worker = None
        self.resources, self.session, self.backend_factory = resources, session, backend_factory
        self.backend = backend_factory(resources, session)
        self.profile = private_profile(self, self.policy)
        self.view = QWebEngineView(self)
        self.page = ReviewPage(self.profile, self.policy, self.view)
        self.view.setPage(self.page)
        self.setCentralWidget(self.view)
        self.downloads = Downloads(self, self.policy, session)
        self.profile.downloadRequested.connect(self.downloads.requested)
        self.signals = StartupSignals(self)
        self.signals.ready.connect(self.load_ready)
        self.signals.failed.connect(self.load_error)
        self.signals.progress.connect(self.load_progress)
        self.retry = QPushButton("Riprova", self)
        self.retry.clicked.connect(self.retry_startup)
        self.statusBar().addPermanentWidget(self.retry)
        self.statusBar().hide()
        mark = (
            (STATIC / "anonymizer.svg")
            .read_text("utf-8")
            .replace("<svg ", '<svg style="display:block;width:100%;height:100%" ', 1)
        )
        self.loading_html = LOADING_HTML.replace(
            "<!--brand-->",
            '<div style="width:88px;height:88px;margin:0 auto" aria-hidden="true">'
            + mark
            + "</div>",
        )
        self.page.setHtml(self.loading_html, QUrl("about:blank"))

    def start_backend(self):
        """!
        @brief Avvia in un thread separato la preparazione del modello e del backend.

        Non fa nulla se la finestra è in chiusura o se un avvio è già in corso.
        """
        if self.stopping or self.worker is not None:
            return

        def prepare():
            """!
            @brief Prepara il modello, avvia il backend e ne segnala l'esito tramite segnali.
            """
            try:
                if self.resources is not None:
                    model = ensure_model(
                        self.resources.root, self.cancelled, self.signals.progress.emit
                    )
                    self.backend.resources = replace(self.resources, model_path=model)
                if self.cancelled.is_set():
                    return
                self.signals.progress.emit("Avvio di OCR e modello locale…", -1)
                if not self.backend.start():
                    return
                url = self.backend.wait_ready(self.cancelled)
                if url and not self.cancelled.is_set():
                    self.signals.ready.emit(url)
            except DownloadCancelled:
                return
            except (DesktopError, ModelDownloadError, OSError) as exception:
                if not self.cancelled.is_set():
                    explanation = (
                        str(exception)
                        if isinstance(exception, (DesktopError, ModelDownloadError))
                        else ("Avvio non riuscito. Ripristina la cartella portable completa.")
                    )
                    self.signals.failed.emit(explanation)

        self.worker = threading.Thread(target=prepare, daemon=True)
        self.worker.start()

    @Slot(str)
    def load_ready(self, url):
        """!
        @brief Associa la politica all'URL del backend e carica l'interfaccia.
        @param url URL base del backend.
        """
        if not self.cancelled.is_set():
            self.statusBar().hide()
            self.policy.bind(url)
            self.page.setUrl(QUrl(url))

    @Slot(str, int)
    def load_progress(self, message, percent):
        """!
        @brief Aggiorna la schermata di caricamento con messaggio e barra di avanzamento.
        @param message Messaggio da mostrare.
        @param percent Percentuale tra 0 e 100; un valore fuori intervallo nasconde la
               barra.
        """
        if self.cancelled.is_set() or self.policy.origin is not None:
            return
        progress = (
            f'<progress max="100" value="{percent}" style="width:360px;max-width:90vw" '
            f'aria-label="Download modello: {percent}%"></progress><p>{percent}%</p>'
            if 0 <= percent <= 100
            else ""
        )
        self.page.setHtml(
            self.loading_html.replace("Avvio di OCR e modello locale...", html.escape(message))
            .replace(
                "Il primo avvio potrebbe richiedere qualche istante.",
                "Il modello viene scaricato solo se manca. Poi puoi lavorare offline.",
            )
            .replace("</body>", progress + f"<p>Versione {VERSION}</p></body>"),
            QUrl("about:blank"),
        )

    @Slot()
    def retry_startup(self):
        """!
        @brief Ricrea il gestore del backend e ripete l'avvio dopo un errore.
        """
        if self.stopping or self.worker is not None and self.worker.is_alive():
            return
        self.backend.stop()
        self.backend = self.backend_factory(self.resources, self.session)
        self.worker = None
        self.statusBar().hide()
        self.load_progress("Preparazione del modello…", -1)
        self.start_backend()

    @Slot(str)
    def load_error(self, explanation):
        """!
        @brief Mostra il messaggio d'errore e il pulsante Riprova.

        Riapre la fase di bootstrap per poter mostrare la pagina inline.
        @param explanation Messaggio d'errore da mostrare.
        """
        if self.cancelled.is_set():
            return
        self.policy.bootstrap = True
        self.page.setHtml(
            self.loading_html.replace("Avvio di OCR e modello locale...", html.escape(explanation))
            .replace(
                "Il primo avvio potrebbe richiedere qualche istante.",
                "Premi Riprova oppure chiudi la finestra per uscire.",
            )
            .replace('<span class="startup-spinner" aria-hidden="true"></span>', ""),
            QUrl("about:blank"),
        )
        self.statusBar().show()

    def closeEvent(self, event):
        """!
        @brief Arresta backend e download prima di chiudere la finestra.
        @param event Evento di chiusura Qt.
        """
        self.shutdown()
        super().closeEvent(event)

    def shutdown(self):
        """!
        @brief Arresta in modo idempotente download, backend e thread di avvio.
        """
        if self.stopping:
            return
        self.stopping = True
        self.cancelled.set()
        self.downloads.close()
        self.backend.stop()
        if self.worker is not None:
            self.worker.join(timeout=1)


def run_window(resources):
    """!
    @brief Crea l'applicazione Qt e mostra la finestra di revisione.

    La cartella di sessione temporanea viene eliminata all'uscita, dopo aver
    distrutto esplicitamente pagina, profilo e finestra WebEngine.
    @param resources Risorse del bundle.
    @return Codice di uscita del ciclo eventi Qt.
    """
    resources.validate(require_model=False)
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("Anonymizer")
    app.setWindowIcon(application_icon())
    with tempfile.TemporaryDirectory(
        prefix="anonymizer-desktop-", ignore_cleanup_errors=True
    ) as directory:
        window = ReviewWindow(resources, Path(directory))
        window.showMaximized()
        QTimer.singleShot(0, window.start_backend)
        try:
            return app.exec()
        finally:
            window.shutdown()
            window.page.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            window.profile.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
