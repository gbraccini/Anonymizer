"""!
@file model.py
@brief Modello dati della pseudonimizzazione testuale.

Definisce pagine estratte, intervalli rilevati e fusi, entità, sostituzioni e mappa di
trasformazione condivisi da rilevamento, pseudonimizzazione e serializzazione.
Tutte le strutture sono immutabili.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4

## Versione dello schema di mappa e risultato; cambia solo con formati incompatibili.
SCHEMA_VERSION = 1


def opaque_id() -> str:
    """!
    @brief Genera un identificatore opaco casuale, privo di informazioni sul contenuto.
    @return Stringa esadecimale di 32 caratteri derivata da un UUID4.
    """
    return uuid4().hex


class Kind(StrEnum):
    """!
    @brief Categorie di dato identificativo riconosciute.

    Determinano l'etichetta del token sostitutivo e le regole di mascheramento.
    """

    CF = "CF"
    HEALTH_CARD = "HEALTH_CARD"
    DATE = "DATE"
    BIRTH_DATE = "BIRTH_DATE"
    PHONE = "PHONE"
    EMAIL = "EMAIL"
    POSTCODE = "POSTCODE"
    IBAN = "IBAN"
    CASE_NUMBER = "CASE_NUMBER"
    PERSON = "PERSON"
    DOCTOR = "DOCTOR"
    LOCATION = "LOCATION"
    FACILITY = "FACILITY"
    ADDRESS = "ADDRESS"
    COMPOSITE = "COMPOSITE"


@dataclass(frozen=True)
class Warning:
    """!
    @brief Avviso prodotto durante l'elaborazione di una pagina.
    """

    ## Codice simbolico dell'avviso.
    code: str
    ## Pagina a cui si riferisce, se pertinente.
    page_id: str | None = None
    ## Intervalli coinvolti.
    span_ids: tuple[str, ...] = ()
    ## Se vero, richiede una decisione prima di poter procedere.
    blocking: bool = False


@dataclass(frozen=True)
class Validation:
    """!
    @brief Esito della validazione semantica di un valore rilevato.
    """

    ## Stato della verifica (`unchecked` se non eseguita).
    status: str = "unchecked"
    ## Motivazione dell'esito.
    reason: str = ""


@dataclass(frozen=True)
class TextRegion:
    """!
    @brief Porzione del testo di una pagina con la sua eventuale posizione grafica.
    """

    ## Offset iniziale, in codepoint, nel testo della pagina.
    start: int
    ## Offset finale esclusivo, in codepoint.
    end: int
    ## Rettangolo sulla pagina, se noto.
    box: tuple[float, float, float, float] | None = None
    ## Confidenza dell'estrazione (es. OCR), se disponibile.
    confidence: float | None = None
    ## Blocco di layout di appartenenza, se noto.
    block_id: str | None = None


@dataclass(frozen=True)
class PageResult:
    """!
    @brief Testo estratto da una pagina di un documento sorgente.
    """

    ## Identificatore univoco della pagina.
    page_id: str
    ## Documento sorgente di provenienza.
    source_id: str
    ## Posizione della pagina, non negativa.
    index: int
    ## Testo estratto.
    text: str
    ## Modalità di estrazione (es. `text` oppure OCR).
    extraction_mode: str = "text"
    ## Regioni del testo con la relativa geometria.
    regions: tuple[TextRegion, ...] = ()
    ## Avvisi emersi durante l'estrazione.
    warnings: tuple[Warning, ...] = ()

    def __post_init__(self) -> None:
        """!
        @brief Verifica l'indice e che ogni regione cada entro il testo.
        @throws ValueError Se l'indice è negativo o una regione non è valida.
        """
        if self.index < 0:
            raise ValueError("Page index must be nonnegative")
        for region in self.regions:
            validate_interval(self.text, region.start, region.end)


def validate_interval(text: str, start: int, end: int) -> None:
    """!
    @brief Verifica che `[start, end)` sia un intervallo non vuoto interno al testo.

    Gli estremi devono essere esattamente `int`: booleani e altri tipi numerici sono
    rifiutati.
    @param text Testo di riferimento.
    @param start Offset iniziale in codepoint.
    @param end Offset finale esclusivo in codepoint.
    @throws ValueError Se l'intervallo non è valido.
    """
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
        raise ValueError("Invalid codepoint interval")


@dataclass(frozen=True)
class Span:
    """!
    @brief Candidato prodotto da un singolo rilevatore.
    """

    ## Pagina che contiene l'intervallo.
    page_id: str
    ## Offset iniziale in codepoint.
    start: int
    ## Offset finale esclusivo in codepoint.
    end: int
    ## Categoria del dato rilevato.
    kind: Kind
    ## Livello di rilevamento, da 0 a 3.
    level: int
    ## Regola o rilevatore che ha prodotto il candidato.
    origin: str
    ## Identificatore opaco del candidato.
    id: str = field(default_factory=opaque_id)
    ## Confidenza in `[0, 1]`, se il rilevatore la fornisce.
    confidence: float | None = None
    ## Esito della validazione semantica.
    validation: Validation = field(default_factory=Validation)
    ## Entità nota a cui il valore è stato collegato, se presente.
    entity_id: str | None = None

    def __post_init__(self) -> None:
        """!
        @brief Verifica intervallo, livello e confidenza.
        @throws ValueError Se uno dei valori è fuori dominio.
        """
        if self.start < 0 or self.end <= self.start:
            raise ValueError("Invalid span interval")
        if self.level not in (0, 1, 2, 3):
            raise ValueError("Invalid detection level")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("Invalid confidence")


@dataclass(frozen=True)
class MergedSpan:
    """!
    @brief Intervallo ottenuto fondendo candidati sovrapposti o contigui.

    Conserva tutti i candidati originari per mantenere la provenienza del rilevamento.
    """

    ## Pagina che contiene l'intervallo.
    page_id: str
    ## Offset iniziale in codepoint.
    start: int
    ## Offset finale esclusivo in codepoint.
    end: int
    ## Categoria risultante dalla fusione.
    kind: Kind
    ## Candidati che hanno contribuito.
    candidates: tuple[Span, ...]
    ## Identificatore opaco dell'intervallo fuso.
    id: str = field(default_factory=opaque_id)
    ## Entità comune ai candidati, se univoca.
    entity_id: str | None = None
    ## Codici dei conflitti di tipo o di entità emersi nella fusione.
    conflicts: tuple[str, ...] = ()

    @property
    def levels(self) -> tuple[int, ...]:
        """!
        @brief Livelli di rilevamento distinti dei candidati.
        @return Livelli in ordine crescente.
        """
        return tuple(sorted({candidate.level for candidate in self.candidates}))

    @property
    def origins(self) -> tuple[str, ...]:
        """!
        @brief Origini distinte dei candidati.
        @return Origini in ordine alfabetico.
        """
        return tuple(sorted({candidate.origin for candidate in self.candidates}))


@dataclass(frozen=True)
class Entity:
    """!
    @brief Persona o soggetto a cui sono riconducibili più occorrenze nel documento.
    """

    ## Identificatore dell'entità.
    id: str
    ## Ruolo (es. `patient`), `unknown` se non determinato.
    role: str = "unknown"
    ## Se vero, l'identità è stata confermata dall'utente.
    confirmed: bool = False
    ## Valore canonico generico, se presente.
    canonical_value: str | None = None
    ## Forme del valore osservate nel testo.
    observed_variants: tuple[str, ...] = ()
    ## Token reversibili assegnati all'entità.
    placeholders: tuple[str, ...] = ()
    ## Provenienza dell'entità (documento o dati inseriti dall'utente).
    origin: str = "document"
    ## Valore canonico per ciascuna categoria di dato.
    canonical_values: tuple[tuple[Kind, str], ...] = ()


@dataclass(frozen=True)
class Replacement:
    """!
    @brief Singola sostituzione applicata al testo di una pagina.

    Registra le posizioni sia nel testo originale sia in quello risultante, così da
    poter annullare l'operazione.
    """

    ## Identificatore opaco dell'operazione.
    id: str
    ## Pagina interessata.
    page_id: str
    ## Offset iniziale nel testo originale.
    start: int
    ## Offset finale esclusivo nel testo originale.
    end: int
    ## Testo originale sostituito.
    original: str
    ## Testo inserito (token o descrizione non reversibile).
    replacement: str
    ## Offset iniziale nel testo risultante.
    result_start: int
    ## Offset finale esclusivo nel testo risultante.
    result_end: int
    ## Entità collegata, se presente.
    entity_id: str | None
    ## Intervallo fuso da cui deriva la sostituzione.
    span_id: str
    ## Se vero, il testo inserito è un token riassociabile.
    reversible_token: bool = True


@dataclass(frozen=True)
class MapEntry:
    """!
    @brief Associazione tra un token e il valore che rappresenta.
    """

    ## Token inserito nel testo.
    token: str
    ## Valore canonico ripristinato in riassociazione.
    canonical_value: str
    ## Entità collegata, se presente.
    entity_id: str | None
    ## Sostituzioni che hanno prodotto il token.
    replacement_ids: tuple[str, ...]
    ## Testo originale di ciascuna sostituzione, nello stesso ordine.
    observed_values: tuple[str, ...]


@dataclass(frozen=True)
class TransformationMap:
    """!
    @brief Mappa completa che consente di ricondurre i token ai valori originali.
    """

    ## Identificatore del documento.
    document_id: str
    ## Identificatore della sessione di elaborazione.
    session_id: str
    ## Entità con varianti osservate e token assegnati.
    entities: tuple[Entity, ...]
    ## Voci token-valore.
    entries: tuple[MapEntry, ...]
    ## Tutte le sostituzioni eseguite.
    replacements: tuple[Replacement, ...]
    ## Versione dello schema della mappa.
    schema_version: int = SCHEMA_VERSION


@dataclass(frozen=True)
class PseudonymizedPage:
    """!
    @brief Testo di una pagina dopo la pseudonimizzazione.
    """

    ## Identificatore della pagina.
    page_id: str
    ## Testo con i dati sostituiti.
    text: str


@dataclass(frozen=True)
class PseudonymizationResult:
    """!
    @brief Risultato complessivo della pseudonimizzazione di un documento.
    """

    ## Pagine pseudonimizzate nell'ordine di ingresso.
    pages: tuple[PseudonymizedPage, ...]
    ## Sostituzioni eseguite.
    replacements: tuple[Replacement, ...]
    ## Mappa di trasformazione per la riassociazione.
    map: TransformationMap
    ## Avvisi da sottoporre a revisione.
    warnings: tuple[Warning, ...]
    ## Versione dello schema del risultato.
    schema_version: int = SCHEMA_VERSION
