"""!
@file context.py
@brief Riconoscimento delimitato di nomi dopo titoli professionali o etichette del
paziente.

Oltre a medici e pazienti individua strutture sanitarie, indirizzi con numero civico,
CAP, città e luoghi personali, sempre ancorati a un contesto esplicito.
"""

import re
import unicodedata

from anonymizer.detect.clinical import external_rules, sensitive_label_matches
from anonymizer.detect.structured import contact_urls
from anonymizer.model import Kind, Span, Validation

## Titolo di medico (dott., dr., dottoressa) che precede un nome.
_TITLE = re.compile(
    r"(?<![\w\u0300-\u036f])(?i:dottoressa|dottore|dottor|dott\.?ssa|dr\.?ssa|dott|dr)"
    r"\.?(?![\w\u0300-\u036f])[ \t]*(?::[ \t]*)?(?:(?:\r\n|\r|\n)[ \t]*)?"
)
## Parola fatta di lettere, accenti combinanti, apostrofi o trattini.
_TOKEN = re.compile(r"[^\W\d_](?:[^\W\d_]|[\u0300-\u036f]|['’ʼ\u2010-\u2015\u2212-])*")
## Spazi orizzontali tra le parti di un nome.
_SPACE = re.compile(r"[ \t]+")
## Particelle ammesse dentro un nome ma non in coda.
_PARTICLES = frozenset(
    "de del della delle dello dei degli di da dal dalla van von der den la le lo "
    "dos das do du des al el bin los las".split()
)
## Parole che interrompono un nome dopo un titolo: verbi, termini clinici e sigle.
_STOPS = frozenset(
    "ha hanno aveva sono è era esegue eseguito eseguita effettua effettuato effettuata "
    "validato validata validazione approvato approvata redatto redatta firmato firmata "
    "firma digitale documento referto data ora ore il un una nel nella presso "
    "medico medica specialista responsabile direttore direttrice reparto servizio "
    "paziente presenta riferisce risultato risultati negativo negativa positivo positiva "
    "esame esami analisi test proteina reattiva emoglobina glucosio creatinina dolore "
    "pressione frequenza diagnosi terapia anamnesi conclusioni segue seguito seguente "
    "nato nata nato/a n/a hb hba1c wbc rbc mcv mch mchc plt hct ast alt ldl hdl "
    "crp tsh ft3 ft4 inr aptt egfr pcr vas nrs".split()
)
## Numero massimo di parti di un nome; oltre, il candidato è scartato.
_MAX_PARTS = 6
## Etichetta composta del tipo cognome e nome.
_PATIENT_LABEL = re.compile(
    r"(?<![\w\u0300-\u036f])(?i:(?:cognome[ \t]+(?:e[ \t]+)?nome|"
    r"nome[ \t]+(?:e[ \t]+)?cognome|cognome[ \t]*[/&-][ \t]*nome|"
    r"nome[ \t]*[/&-][ \t]*cognome))(?![\w\u0300-\u036f])"
    r"[ \t]*(?::|=)?[ \t]*(?:(?:\r\n|\r|\n)[ \t]*)?"
)
## Parole di arresto per i valori che seguono etichette anagrafiche.
_PATIENT_STOPS = _STOPS | frozenset(
    "metodica metodo um sesso età eta indirizzo residenza domicilio cap comune provincia "
    "codice fiscale cf telefono email recapito accettazione prelievo prenotazione "
    "campione unità unita misura riferimento intervallo valori valore descrizione "
    "prestazione prestazioni quesito clinico nome cognome denominazione campo campi "
    "inserire compilare scrivere obbligatorio richiesto mancante non nessuno nessuna "
    "sconosciuto sconosciuta ignoto ignota struttura ospedale ambulatorio nascita "
    "tessera sanitaria numero protocollo identificativo provenienza centro laboratorio "
    "clinica autorizzato autorizzata accreditato accreditata".split()
)
## Etichetta singola cognome o nome seguita da due punti o uguale.
_SEPARATE_LABEL = re.compile(r"(?<!\w)(?P<label>(?i:cognome|nome))[ \t]*[:=][ \t]*")
## Etichetta di direttore o direttrice sanitaria.
_DIRECTOR_LABEL = re.compile(
    r"(?<!\w)(?i:direttore[ \t]+sanitario|direttrice[ \t]+sanitaria)[ \t]*[:=][ \t]*"
    r"(?:(?:\r\n|\r|\n)[ \t]*)?"
)
## Parola che introduce il nome di una struttura sanitaria.
_FACILITY = re.compile(
    r"(?<![\w\u0300-\u036f])(?i:centro[ \t]+(?:di[ \t]+)?analisi|"
    r"laboratorio(?:[ \t]+(?:di[ \t]+)?analisi(?:[ \t]+cliniche)?)?|"
    r"centro[ \t]+medico|diagnostica|poliambulatorio|clinica|ospedale)"
    r"(?![\w\u0300-\u036f])(?:[ \t]*:[ \t]*|[ \t]+)"
)
## Parole di arresto per i nomi di struttura.
_FACILITY_STOPS = _PATIENT_STOPS | frozenset(
    "srl spa snc sas differenziale differenziali chimiche risultati risultato "
    "controllo controlli confronto confronti interpretazione valutazione tel fax www".split()
)
## Forma societaria (srl, spa, snc, sas), tollerante agli errori OCR.
_LEGAL_SUFFIX = re.compile(
    r"[ \t]+(?i:s\.?[ \t]*r\.?[ \t]*[lI1]\.?|s\.?[ \t]*p\.?[ \t]*a\.?|"
    r"s\.?[ \t]*n\.?[ \t]*c\.?|s\.?[ \t]*a\.?[ \t]*s\.?)(?!\w)"
)
## Indizio di contatto sulla stessa riga: telefono, fax, sito web o email.
_CONTACT = re.compile(r"\b(?:tel(?:efono)?|fax)\s*[:.]?\s*\+?\d|www\.|@", re.IGNORECASE)
## Evidenza di contatto vera e propria: numero di telefono o fax, o indirizzo email.
_CONTACT_EVIDENCE = re.compile(
    r"\b(?:tel(?:efono)?|fax)\s*[:.]?\s*\+?\d|[\w.+-]+@[\w-]+(?:\.[\w-]+)+",
    re.IGNORECASE,
)
## Etichetta di struttura alla fine del testo che precede il nome.
_FACILITY_LABEL = re.compile(r"(?i:\b(?:struttura|sede|laboratorio|centro))\s*:\s*$")
## Regole esterne per gli indirizzi italiani: tipi di strada e parole di contesto.
_ADDRESS_RULES = external_rules()["italian_address"]
## Tipo di strada (via, piazza, viale...) che apre un indirizzo.
_STREET = re.compile(
    r"(?<![\w\u0300-\u036f])(?i:"
    + "|".join(re.escape(word) for word in _ADDRESS_RULES["street_types"])
    + r"|v\.le|p\.zza|strada)(?![\w\u0300-\u036f])[ \t]+"
)
## Etichetta di indirizzo alla fine del testo che precede.
_ADDRESS_LABEL = re.compile(
    r"(?i:\b(?:"
    + "|".join(map(re.escape, _ADDRESS_RULES["context_words"]))
    + r"))[ \t]*[:=][ \t]*$"
)
## Parole di arresto per i nomi di strada, incluse le vie di somministrazione dei farmaci.
_STREET_STOPS = _PATIENT_STOPS | frozenset(
    "orale rettale cutanea endovenosa venosa intramuscolare sottocutanea "
    "somministrazione respiratoria parenterale transdermica".split()
)
## Numero civico con eventuale suffisso (bis, ter, lettera).
_CIVIC = re.compile(
    r"[ \t]*(?:[,\-–—][ \t]*)?(?:n\.?[ \t]*)?\d{1,4}"
    r"(?:[ \t]*(?:/[ \t]*)?(?:bis|ter|quater|[A-Za-z]))?"
    r"(?!\w|[.,]\d|[ \t]*/)",
    re.IGNORECASE,
)
## Separatore tra le parti di un indirizzo, con al più un a capo.
_ADDRESS_SEPARATOR = re.compile(r"[ \t]{0,20}(?:[,\-–—][ \t]{0,20})?(?:(?:\r\n|\r|\n)[ \t]{0,20})?")
## Particelle ammesse nei nomi di città.
_CITY_PARTICLES = _PARTICLES | frozenset("in sul sulla sotto sopra nell nell'".split())
## Parole di arresto per i nomi di città.
_CITY_STOPS = _PATIENT_STOPS | frozenset(
    "tel cell cellulare fax sito web contatti contatto sede interpretazione arteriosa italia "
    "p iva residente residente/a termine pretermine settimana settimane sanitaria assistenziale "
    "stabile protetta abituale fiscale mmg pls regione nazionalità".split()
)
## Etichetta di luogo personale: nascita, residenza o domicilio.
_LOCATION_LABEL = re.compile(
    r"(?<!\w)(?i:(?:luogo|comune|località|provincia)[ \t]+(?:di[ \t]+)?"
    r"(?:nascita|residenza|domicilio)|nat[oa](?:/a)?[ \t]+a|"
    r"residente(?:/a)?[ \t]+(?:a|in)|residenza|domicilio)"
    r"(?!\w)[ \t]*[:=]?[ \t]*(?:(?:\r\n|\r|\n)[ \t]*)?"
)


def _is_name_part(token: str) -> bool:
    """!
    @brief Verifica se una parola ha la forma di una parte di nome.
    @param token Parola candidata.
    @return True se ha almeno due lettere, termina con una lettera ed è capitalizzata o
            tutta maiuscola.
    """
    value = unicodedata.normalize("NFC", token)
    letters = [char for char in value if char.isalpha()]
    return len(letters) >= 2 and value[-1].isalpha() and (value.istitle() or value.isupper())


def _name_end(text: str, start: int, stops: frozenset[str], *, min_parts=2) -> int | None:
    """!
    @brief Trova la fine di un nome che inizia a una posizione data, su una sola riga.

    Le particelle finali non fanno parte del nome; una parola con cifre o trattini bassi
    attaccati rende il candidato un identificativo e lo invalida.
    @param text Testo della pagina.
    @param start Posizione di inizio del nome.
    @param stops Parole che interrompono il nome.
    @param min_parts Numero minimo di parti diverse dalle particelle.
    @return Posizione di fine del nome, oppure None se il candidato non è valido o supera
            _MAX_PARTS parti.
    """
    cursor = start
    parts = []
    while match := _TOKEN.match(text, cursor):
        token = match.group()
        folded = unicodedata.normalize("NFC", token).casefold()
        particle = folded in _PARTICLES
        if folded in stops or not (particle or _is_name_part(token)):
            break
        # Attached digits/underscores are identifiers, not a partial surname.
        if match.end() < len(text) and (text[match.end()].isalnum() or text[match.end()] == "_"):
            return None
        parts.append((match.end(), particle))
        if len(parts) > _MAX_PARTS:
            return None
        whitespace = _SPACE.match(text, match.end())
        if whitespace is None:
            break
        cursor = whitespace.end()
    while parts and parts[-1][1]:
        parts.pop()
    if sum(not particle for _, particle in parts) < min_parts:
        return None
    return parts[-1][0]


def detect_doctors(text: str, page_id: str) -> list[Span]:
    """!
    @brief Individua i nomi di medici dopo un titolo, un'etichetta di direttore sanitario o
    un'etichetta clinica.

    Accetta da 2 a 6 parti di nome su una riga, anche con iniziali puntate; non è un
    riconoscitore generico di nomi.
    @param text Testo della pagina.
    @param page_id Identificativo della pagina.
    @return Intervalli di tipo DOCTOR.
    """
    spans = []
    for title in [*_TITLE.finditer(text), *_DIRECTOR_LABEL.finditer(text)]:
        start = title.end()
        end = doctor_name_end(text, start)
        if end is None:
            continue
        spans.append(
            Span(
                page_id,
                start,
                end,
                Kind.DOCTOR,
                1,
                "context:doctor",
                validation=Validation(
                    "unchecked",
                    "explicit_doctor_initials"
                    if "." in text[start:end]
                    else "explicit_doctor_title",
                ),
            )
        )
    spans.extend(_clinical_label_names(text, page_id, Kind.DOCTOR))
    return spans


def detect_patient_labels(text: str, page_id: str) -> list[Span]:
    """!
    @brief Individua il valore dopo un'etichetta composta di nome, senza attribuire
    l'identità del paziente.

    Include anche i nomi dopo le etichette cliniche sensibili e le coppie di campi
    separati cognome/nome.
    @param text Testo della pagina.
    @param page_id Identificativo della pagina.
    @return Intervalli di tipo PERSON.
    """
    spans = []
    for label in _PATIENT_LABEL.finditer(text):
        start = label.end()
        end = _name_end(text, start, _PATIENT_STOPS)
        if end is not None:
            spans.append(
                Span(
                    page_id,
                    start,
                    end,
                    Kind.PERSON,
                    1,
                    "context:patient_name",
                    validation=Validation("unchecked", "explicit_patient_name_label"),
                )
            )
    spans.extend(_clinical_label_names(text, page_id, Kind.PERSON))
    spans.extend(detect_separate_patient_fields(text, page_id))
    return spans


def field_name_end(text: str, start: int) -> int | None:
    """!
    @brief Trova la fine di un nome in un campo etichettato, ammettendo una sola parte.
    @param text Testo della pagina.
    @param start Posizione da cui inizia il valore.
    @return Posizione di fine del valore, oppure None se il candidato non è valido.
    """
    return labeled_name_end(text, start, Kind.PERSON, min_parts=1)


def detect_separate_patient_fields(text: str, page_id: str) -> list[Span]:
    """!
    @brief Individua coppie vicine di campi distinti cognome e nome.

    Entrambi i valori devono essere validi e separati solo da spazi, punteggiatura o un
    a capo; un campo isolato non viene emesso.
    @param text Testo della pagina.
    @param page_id Identificativo della pagina.
    @return Intervalli di tipo PERSON per entrambi i campi di ogni coppia.
    """
    labels = list(_SEPARATE_LABEL.finditer(text))
    spans = []
    index = 0
    while index + 1 < len(labels):
        first, second = labels[index : index + 2]
        first_end = field_name_end(text, first.end())
        second_end = field_name_end(text, second.end())
        gap = text[first_end : second.start()] if first_end is not None else "!"
        if (
            first.group("label").casefold() != second.group("label").casefold()
            and second.start() - first.start() <= 160
            and first_end is not None
            and second_end is not None
            and re.fullmatch(r"[ \t,;|]*(?:(?:\r\n|\r|\n)[ \t]*)?", gap)
        ):
            for label, end in ((first, first_end), (second, second_end)):
                spans.append(
                    Span(
                        page_id,
                        label.end(),
                        end,
                        Kind.PERSON,
                        1,
                        "context:patient_field",
                        validation=Validation("unchecked", "paired_name_surname_fields"),
                    )
                )
            index += 2
        else:
            index += 1
    return spans


def doctor_name_end(text: str, start: int, stops: frozenset[str] = _STOPS) -> int | None:
    """!
    @brief Trova la fine del nome di un medico, ammettendo iniziali puntate.

    Prova prima la forma rigorosa di _name_end(); altrimenti accetta un nome con almeno
    una parte completa e almeno un'iniziale.
    @param text Testo della pagina.
    @param start Posizione da cui inizia il valore.
    @param stops Parole che interrompono il nome.
    @return Posizione di fine del valore, oppure None se il candidato non è valido.
    """
    strict = _name_end(text, start, stops)
    if strict is not None:
        return strict
    cursor, parts, full, initials = start, [], 0, 0
    while token := _TOKEN.match(text, cursor):
        value = token.group()
        particle = value.casefold() in _PARTICLES
        initial = len(value) == 1 and value.isupper() and text[token.end() : token.end() + 1] == "."
        if value.casefold() in stops or not (initial or particle or _is_name_part(value)):
            break
        end = token.end() + int(initial)
        if end < len(text) and (text[end].isalnum() or text[end] == "_"):
            return None
        parts.append((end, particle))
        full += int(not particle and not initial)
        initials += int(initial)
        if len(parts) > _MAX_PARTS:
            return None
        space = _SPACE.match(text, end)
        if space is None:
            break
        cursor = space.end()
    while parts and parts[-1][1]:
        parts.pop()
    return parts[-1][0] if parts and full and initials else None


def labeled_name_end(text: str, start: int, kind: Kind, *, min_parts=2) -> int | None:
    """!
    @brief Applica gli stessi vincoli grammaticali e di nome completo alle etichette nel
    testo e nel layout.

    Rifiuta i valori che iniziano con preposizioni o congiunzioni tipiche di frasi
    descrittive, salvo le particelle dei cognomi non seguite da un infinito.
    @param text Testo della pagina.
    @param start Posizione da cui inizia il valore.
    @param kind DOCTOR usa doctor_name_end(); gli altri tipi usano _name_end().
    @param min_parts Numero minimo di parti per i nomi che non sono di medici.
    @return Posizione di fine del valore, oppure None se il candidato non è valido.
    """
    state_leads = frozenset("in con per senza non che si su da a al alla allo".split())
    stops = _PATIENT_STOPS | (state_leads - _PARTICLES)
    first = _TOKEN.match(text, start)
    if first is not None and first.group().casefold() in state_leads:
        if first.group().casefold() not in _PARTICLES:
            return None
        space = _SPACE.match(text, first.end())
        following = _TOKEN.match(text, space.end()) if space is not None else None
        if (
            first.group().casefold() == "da"
            and following is not None
            and following.group().casefold().endswith(("are", "ere", "ire"))
        ):
            return None
    return (
        doctor_name_end(text, start, stops)
        if kind == Kind.DOCTOR
        else _name_end(text, start, stops, min_parts=min_parts)
    )


def _clinical_label_names(text: str, page_id: str, kind: Kind) -> list[Span]:
    """!
    @brief Estrae i nomi che seguono le etichette cliniche sensibili del tipo richiesto.
    @param text Testo della pagina.
    @param page_id Identificativo della pagina.
    @param kind Tipo di entità (DOCTOR o PERSON).
    @return Intervalli del tipo indicato.
    """
    spans = []
    for rule_id, start in sensitive_label_matches(text, kind):
        end = labeled_name_end(text, start, kind)
        if end is not None:
            spans.append(
                Span(
                    page_id,
                    start,
                    end,
                    kind,
                    1,
                    "context:doctor" if kind == Kind.DOCTOR else "context:patient_name",
                    validation=Validation("unchecked", "clinical_it_label:" + rule_id),
                )
            )
    return spans


def _street_name_end(text: str, marker) -> int | None:
    """!
    @brief Trova la fine del nome di una strada dopo il tipo di strada.

    Se il nome non è capitalizzato accetta fino a sei parole, ma solo quando la riga
    contiene un'etichetta di indirizzo prima del tipo di strada.
    @param text Testo della pagina.
    @param marker Corrispondenza di _STREET.
    @return Posizione di fine del nome, oppure None.
    """
    end = _name_end(text, marker.end(), _STREET_STOPS, min_parts=1)
    if end is not None:
        return end
    line_start = max(text.rfind("\n", 0, marker.start()), text.rfind("\r", 0, marker.start())) + 1
    if not _ADDRESS_LABEL.search(text[line_start : marker.start()]):
        return None
    cursor, ends = marker.end(), []
    while token := _TOKEN.match(text, cursor):
        if token.group().casefold() in _STREET_STOPS:
            break
        ends.append(token.end())
        if len(ends) > 6:
            return None
        space = _SPACE.match(text, token.end())
        if space is None:
            break
        cursor = space.end()
    return ends[-1] if ends else None


def _city_end(text: str, start: int, *, labeled=False) -> int | None:
    """!
    @brief Trova la fine del nome di una città, inclusa l'eventuale sigla di provincia.
    @param text Testo della pagina.
    @param start Posizione di inizio del nome.
    @param labeled True se il valore segue un'etichetta: ammette anche parole non
           capitalizzate.
    @return Posizione di fine, oppure None se non c'è un nome valido.
    """
    cursor, parts = start, []
    while token := _TOKEN.match(text, cursor):
        value = unicodedata.normalize("NFC", token.group()).casefold()
        particle = value in _CITY_PARTICLES
        if value in _CITY_STOPS or not (
            particle or _is_name_part(token.group()) or labeled and len(value) >= 2
        ):
            break
        if token.end() < len(text) and (text[token.end()].isalnum() or text[token.end()] == "_"):
            return None
        parts.append((token.end(), particle))
        if len(parts) > 8:
            return None
        space = _SPACE.match(text, token.end())
        if space is None:
            break
        cursor = space.end()
    while parts and parts[-1][1]:
        parts.pop()
    if not parts:
        return None
    end = parts[-1][0]
    province = re.match(r"[ \t]{0,10}(?:\([A-Z]{2}\)|[,\-][ \t]*[A-Z]{2})(?!\w)", text[end:])
    return end + province.end() if province else end


def location_value_end(text: str, start: int) -> int | None:
    """!
    @brief Trova la fine di un luogo etichettato, escludendo i valori che sono indirizzi.
    @param text Testo della pagina.
    @param start Posizione da cui inizia il valore.
    @return Posizione di fine del luogo, oppure None se il valore inizia con un tipo di
            strada o non è un luogo.
    """
    if _STREET.match(text, start):
        return None
    return _city_end(text, start, labeled=True)


def _location_details(text: str, page_id: str) -> list[Span]:
    """!
    @brief Individua luoghi personali dopo un'etichetta di luogo o prima di una sigla di
    provincia tra parentesi.

    Gli intervalli contenuti in altri più ampi vengono scartati.
    @param text Testo della pagina.
    @param page_id Identificativo della pagina.
    @return Intervalli di tipo LOCATION.
    """
    intervals = set()
    for label in _LOCATION_LABEL.finditer(text):
        end = location_value_end(text, label.end())
        if end is not None:
            intervals.add((label.end(), end))
    # A province suffix also identifies cities when an OCR label is damaged or absent.
    for province in re.finditer(r"[ \t]*\([A-Z]{2}\)(?!\w)", text):
        lower = max(0, province.start() - 70)
        for token in _TOKEN.finditer(text, lower, province.start()):
            end = _city_end(text, token.start())
            if end == province.end():
                intervals.add((token.start(), end))
                break
    return [
        Span(
            page_id,
            start,
            end,
            Kind.LOCATION,
            1,
            "context:personal_location",
            validation=Validation("unchecked", "location_label_or_province_suffix"),
        )
        for start, end in sorted(intervals)
        if not any(a <= start and end <= b and (a, b) != (start, end) for a, b in intervals)
    ]


def _address_details(text: str, page_id: str) -> list[Span]:
    """!
    @brief Individua indirizzi con numero civico, seguiti eventualmente da CAP e città.

    Senza CAP la città viene emessa solo se l'indirizzo segue un'etichetta; con il CAP la
    città deve trovarsi al più una riga dopo il civico.
    @param text Testo della pagina.
    @param page_id Identificativo della pagina.
    @return Intervalli di tipo ADDRESS, POSTCODE e LOCATION.
    """
    spans = []
    for marker in _STREET.finditer(text):
        name_end = _street_name_end(text, marker)
        civic = _CIVIC.match(text, name_end) if name_end is not None else None
        if civic is None:
            continue
        spans.append(
            Span(
                page_id,
                marker.start(),
                civic.end(),
                Kind.ADDRESS,
                1,
                "context:address",
                validation=Validation("unchecked", "street_name_and_civic_number"),
            )
        )
        separator = _ADDRESS_SEPARATOR.match(text, civic.end())
        postcode = re.compile(r"\d{5}(?!\w|[.,]\d)").match(text, separator.end())
        if postcode is None:
            city_end = _city_end(text, separator.end())
            prefix = text[max(0, marker.start() - 60) : marker.start()]
            labeled = _ADDRESS_LABEL.search(prefix) or any(
                m.end() == len(prefix) for m in _LOCATION_LABEL.finditer(prefix)
            )
            if labeled and separator.end() > civic.end() and city_end is not None:
                spans.append(
                    Span(
                        page_id,
                        separator.end(),
                        city_end,
                        Kind.LOCATION,
                        1,
                        "context:address_city",
                        validation=Validation("unchecked", "city_after_street_and_civic"),
                    )
                )
            continue
        spans.append(
            Span(
                page_id,
                postcode.start(),
                postcode.end(),
                Kind.POSTCODE,
                1,
                "context:address_postcode",
                validation=Validation("unchecked", "postcode_after_numbered_street"),
            )
        )
        separator = _ADDRESS_SEPARATOR.match(text, postcode.end())
        if separator.end() == postcode.end():
            continue
        city_end = _city_end(text, separator.end())
        if (
            city_end is not None
            and len(re.findall(r"\r\n|\r|\n", text[civic.end() : city_end])) <= 1
        ):
            spans.append(
                Span(
                    page_id,
                    separator.end(),
                    city_end,
                    Kind.LOCATION,
                    1,
                    "context:address_city",
                    validation=Validation("unchecked", "city_after_street_civic_postcode"),
                )
            )
    return spans


def _adjacent_contact_block(text: str, start: int, end: int) -> str:
    """!
    @brief Restituisce il blocco di testo attorno a un intervallo in cui cercare contatti.

    Comprende la riga precedente se non vuota e fino a tre righe a partire da quella
    dell'intervallo, fermandosi alla prima riga vuota.
    @param text Testo della pagina.
    @param start Inizio dell'intervallo di riferimento.
    @param end Fine dell'intervallo di riferimento.
    @return Testo del blocco.
    """
    line_start = max(text.rfind("\n", 0, start), text.rfind("\r", 0, start)) + 1
    previous = text[max(0, line_start - 400) : line_start].splitlines(keepends=True)
    prefix = previous[-1] if previous and previous[-1].strip() else ""
    following = text[line_start : min(len(text), end + 400)]
    following = re.split(
        r"(?:\r\n|\r(?!\n)|(?<!\r)\n)[ \t]*(?:\r\n|\r(?!\n)|(?<!\r)\n)", following, maxsplit=1
    )[0]
    return prefix + "".join(following.splitlines(keepends=True)[:3])


def _legal_facility_names(text: str, page_id: str) -> list[Span]:
    """!
    @brief Individua righe formate da un nome breve con forma societaria e contatti
    vicini.
    @param text Testo della pagina.
    @param page_id Identificativo della pagina.
    @return Intervalli di tipo FACILITY.
    """
    spans, offset = [], 0
    for physical_line in text.splitlines(keepends=True):
        line = physical_line.rstrip("\r\n")
        leading = len(line) - len(line.lstrip(" \t"))
        value = line[leading:]
        suffix = _LEGAL_SUFFIX.search(value[:160])
        if suffix is not None:
            name = value[: suffix.start()]
            tokens = list(_TOKEN.finditer(name))
            plausible = (
                1 <= len(tokens) <= 4
                and tokens[0].start() == 0
                and tokens[-1].end() == len(name)
                and all(
                    not name[a.end() : b.start()].strip()
                    for a, b in zip(tokens, tokens[1:], strict=False)
                )
                and all(
                    t.group().casefold() not in _FACILITY_STOPS
                    and (
                        t.group().casefold() in _PARTICLES
                        or len(t.group()) >= 2
                        and t.group()[0].isupper()
                    )
                    for t in tokens
                )
                and tokens[0].group().casefold() not in _PARTICLES
                and tokens[-1].group().casefold() not in _PARTICLES
            )
            tail = value[suffix.end() :].lstrip(" \t")
            if plausible and (not tail or tail.startswith(("-", ",", "\u2013", "\u2014"))):
                start, end = offset + leading, offset + leading + suffix.end()
                block = _adjacent_contact_block(text, start, end)
                evidence = _CONTACT_EVIDENCE.search(block) or any(
                    span.kind == Kind.ADDRESS for span in _address_details(block, page_id)
                )
                if evidence:
                    spans.append(
                        Span(
                            page_id,
                            start,
                            end,
                            Kind.FACILITY,
                            1,
                            "context:facility",
                            validation=Validation(
                                "unchecked", "line_legal_name_with_adjacent_contact"
                            ),
                        )
                    )
        offset += len(physical_line)
    return spans


def detect_contact_details(text: str, page_id: str) -> list[Span]:
    """!
    @brief Individua strutture, contatti, indirizzi e luoghi da sintassi esplicita, mai da
    marchi isolati.

    Un nome di struttura viene emesso solo con forma societaria, etichetta o evidenza di
    contatto vicina; i siti web sono emessi solo nei blocchi di contatto delle strutture.
    @param text Testo della pagina.
    @param page_id Identificativo della pagina.
    @return Intervalli ordinati per posizione.
    """
    spans = []
    for marker in _FACILITY.finditer(text):
        end = _name_end(text, marker.end(), _FACILITY_STOPS, min_parts=1)
        if end is None:
            continue
        suffix = _LEGAL_SUFFIX.match(text, end)
        line_start = (
            max(text.rfind("\n", 0, marker.start()), text.rfind("\r", 0, marker.start())) + 1
        )
        endings = [position for sep in ("\r", "\n") if (position := text.find(sep, end)) >= 0]
        line_end = min(endings, default=len(text))
        label = _FACILITY_LABEL.search(text[line_start : marker.start()])
        nearby = _adjacent_contact_block(text, marker.start(), end)
        adjacent_evidence = _CONTACT_EVIDENCE.search(nearby) or any(
            span.kind == Kind.ADDRESS for span in _address_details(nearby, page_id)
        )
        if (
            suffix is None
            and label is None
            and not _CONTACT.search(text[end:line_end])
            and not adjacent_evidence
        ):
            continue
        spans.append(
            Span(
                page_id,
                marker.start(),
                suffix.end() if suffix else end,
                Kind.FACILITY,
                1,
                "context:facility",
                validation=Validation("unchecked", "medical_name_with_contact_or_legal_context"),
            )
        )
    for legal in _legal_facility_names(text, page_id):
        if not any(
            s.kind == Kind.FACILITY and s.start <= legal.start and legal.end <= s.end for s in spans
        ):
            spans.append(legal)
    seen_urls = set()
    for seed in tuple(spans):
        if seed.origin != "context:facility":
            continue
        block = text[seed.start : min(len(text), seed.end + 400)]
        block = re.split(
            r"(?:\r\n|\r(?!\n)|(?<!\r)\n)[ \t]*(?:\r\n|\r(?!\n)|(?<!\r)\n)", block, maxsplit=1
        )[0]
        block = "".join(block.splitlines(keepends=True)[:4])
        if _CONTACT_EVIDENCE.search(block):
            for web_start, web_end in contact_urls(block):
                if web_end > web_start:
                    start = seed.start + web_start
                    key = (start, seed.start + web_end)
                    if key in seen_urls:
                        continue
                    seen_urls.add(key)
                    spans.append(
                        Span(
                            page_id,
                            start,
                            seed.start + web_end,
                            Kind.FACILITY,
                            1,
                            "context:facility_web",
                            validation=Validation(
                                "unchecked", "presidio_commonregex_url_in_facility_contact_block"
                            ),
                        )
                    )
    spans.extend(_address_details(text, page_id))
    spans.extend(
        s
        for s in _location_details(text, page_id)
        if not any(old.start <= s.start and s.end <= old.end for old in spans)
    )
    return sorted(spans, key=lambda span: (span.start, span.end))


def detect_facility_repetitions(pages, seeds) -> list[Span]:
    """!
    @brief Propaga i nomi completi di struttura confermati dal contesto, mai alias di
    marchio isolati.

    Il confronto ignora maiuscole e forma societaria, richiede almeno due parole e
    ammette al più un a capo tra le parole.
    @param pages Pagine del documento.
    @param seeds Intervalli già trovati; si usano quelli con origine context:facility.
    @return Intervalli di tipo FACILITY per ogni occorrenza.
    """
    by_id = {page.page_id: page for page in pages}
    names = set()
    for seed in seeds:
        if seed.origin != "context:facility" or seed.kind != Kind.FACILITY:
            continue
        name = by_id[seed.page_id].text[seed.start : seed.end]
        suffix = _LEGAL_SUFFIX.search(name)
        if suffix and suffix.end() == len(name):
            name = name[: suffix.start()]
        name = " ".join(name.casefold().split())
        if len(list(_TOKEN.finditer(name))) >= 2:
            names.add(name)
    patterns = [
        re.compile(
            r"(?<![\w\u0300-\u036f])"
            + r"(?:[ \t]{1,20}|[ \t]{0,20}(?:\r\n|\r|\n)[ \t]{0,20})".join(
                re.escape(part) for part in name.split(" ")
            )
            + r"(?![\w\u0300-\u036f])"
        )
        for name in sorted(names)
    ]
    spans = []
    for page in pages:
        folded, offsets = [], []
        for index, char in enumerate(page.text):
            value = char.casefold()
            folded.append(value)
            offsets.extend([index] * len(value))
        text = "".join(folded)
        for pattern in patterns:
            for match in pattern.finditer(text):
                if len(re.findall(r"\r\n|\r|\n", match.group())) > 1:
                    continue
                spans.append(
                    Span(
                        page.page_id,
                        offsets[match.start()],
                        offsets[match.end() - 1] + 1,
                        Kind.FACILITY,
                        1,
                        "context:facility_repeat",
                        validation=Validation(
                            "unchecked", "complete_name_from_explicit_facility_context"
                        ),
                    )
                )
    return spans
