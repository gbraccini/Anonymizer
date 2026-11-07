"""!
@file experiments/ner/make_corpus.py
@brief Ricostruisce il corpus sintetico scritto a mano.

Non contiene dati di pazienti e non usa generazione casuale. I documenti sono
marcati con tag inline per persone, luoghi, strutture e segmenti clinici; lo
script li converte in testo puro con gli offset delle annotazioni e scrive
corpus.json accanto a sé, usato da evaluate.py.
"""

import json
import re
from pathlib import Path

## Documenti marcati della partizione di sviluppo, usabile per tarare i parametri.
DEVELOPMENT = [
    (
        "<CLINICAL>Morbo di Parkinson escluso; test di Romberg negativo. Forte dolore "
        "alla testa, grasso sottocutaneo regolare. Non febbre.</CLINICAL>"
    ),
    (
        "<CLINICAL>OCT: retina aderente, 246 µm; nessun edema. Pressione 14 mmHg. La "
        "terapia resta invariata, 5 mg al giorno.</CLINICAL>"
    ),
    (
        "Visita di <PERSON>Zoë Évora</PERSON> presso <FACILITY>Clinica delle "
        "Lanterne</FACILITY>. <CLINICAL>Non presenta diplopia.</CLINICAL>"
    ),
    (
        "Da <LOCATION>Valleverde</LOCATION> arriva <PERSON>Elvio Neranti</PERSON>: "
        "<CLINICAL>forte dolore al ginocchio, VAS 7/10.</CLINICAL>"
    ),
    (
        "<PERSON>Łukasz Żur</PERSON> — <CLINICAL>morbo di Parkinson in terapia; "
        "nessuna caduta.</CLINICAL>"
    ),
    (
        "Controllo OCT: <PERSON>Amélie Duvant</PERSON>. <CLINICAL>Spessore maculare "
        "240 µm, retina aderente.</CLINICAL>"
    ),
    (
        "Il medico <PERSON>Kenji Morisaki</PERSON> lavora al <FACILITY>Centro "
        "Oculistico del Glicine</FACILITY>. <CLINICAL>Pressione 16 mmHg.</CLINICAL>"
    ),
    (
        "<PERSON>Inés Valmora</PERSON> e <PERSON>Nadir Solventi</PERSON> riferiscono "
        "<CLINICAL>assenza di febbre.</CLINICAL>"
    ),
    (
        "Sede di invio <LOCATION>Roccalume</LOCATION>; assistita <PERSON>Astrid "
        "Vellner</PERSON>. <CLINICAL>Test di Romberg negativo.</CLINICAL>"
    ),
    (
        "<CLINICAL>La testa è dolente, grasso sottocutaneo conservato.</CLINICAL> "
        "Firmato <PERSON>Bruno Ellanti</PERSON>."
    ),
    (
        "Ricovero <FACILITY>Ospedale delle Comete</FACILITY>, <PERSON>Maëlle "
        "Orvani</PERSON>. <CLINICAL>FC 72 bpm e SpO2 98%.</CLINICAL>"
    ),
    (
        "<PERSON>Yusuf Dalmiri</PERSON> residente in <LOCATION>Borgofiore</LOCATION>. "
        "<CLINICAL>Non evidenza di edema.</CLINICAL>"
    ),
    (
        "Consulente <PERSON>Petra Černova</PERSON>: <CLINICAL>malattia di Alzheimer, "
        "quadro stabile.</CLINICAL>"
    ),
    (
        "Trasferire <PERSON>Omar Zefrani</PERSON> alla <FACILITY>Casa di Cura del "
        "Melograno</FACILITY>. <CLINICAL>Cammino autonomo.</CLINICAL>"
    ),
    (
        "<CLINICAL>Rachide senza lesioni focali.</CLINICAL> Refertante: <PERSON>Hélène "
        "Farcetti</PERSON>."
    ),
    (
        "<PERSON>Santiago Velmori</PERSON> [<LOCATION>Montebrina</LOCATION>] — "
        "<CLINICAL>Glicemia 89 mg/dL.</CLINICAL>"
    ),
    (
        "<FACILITY>Ambulatorio delle Felci</FACILITY> riceve <PERSON>Daria "
        "Quersoli</PERSON>. <CLINICAL>Nessuna allergia dichiarata.</CLINICAL>"
    ),
    (
        "Prenotazione per <PERSON>Mihai Călinescu</PERSON>; <CLINICAL>testa e collo "
        "senza adenopatie.</CLINICAL>"
    ),
    (
        "Relazione di <PERSON>Leila Benrali</PERSON>, valutata da <PERSON>Erik "
        "Nordanti</PERSON>. <CLINICAL>Riflessi presenti e simmetrici.</CLINICAL>"
    ),
    (
        "<CLINICAL>OCT: nessun liquido sottoretinico.</CLINICAL> Destinazione "
        "<FACILITY>Istituto Visivo delle Querce</FACILITY>."
    ),
    "<CLINICAL>Controllo programmato tra 6 mesi; terapia invariata.</CLINICAL> "
    + "Rilevazione clinica stabile. " * 180
    + "Utente <PERSON>Camila Viorenti</PERSON>.",
    "<CLINICAL>Nessun dolore toracico.</CLINICAL> "
    + "parametro " * 246
    + "<PERSON>Renée Alvorni</PERSON> valutata a <LOCATION>Pianaluna</LOCATION>.",
]

## Documenti marcati della partizione di valutazione, da non usare per la taratura.
EVALUATION = [
    (
        "<CLINICAL>La diagnosi differenziale non sostiene Alzheimer. Non deficit di "
        "forza; Romberg nei limiti, assenza di vertigini.</CLINICAL>"
    ),
    (
        "<CLINICAL>Esame della testa senza lesioni. Grasso periviscerale conservato; "
        "glicemia 92 mg/dL, SpO2 99%, non assume farmaci.</CLINICAL>"
    ),
    (
        "Scheda ambulatoriale\nIntestataria: <PERSON>Ágata "
        "Mirens</PERSON>\n<CLINICAL>Rima articolare conservata.</CLINICAL>"
    ),
    (
        "Alla cortese attenzione del <FACILITY>Poliambulatorio delle Vele</FACILITY>: "
        "<PERSON>Teodor Istrate</PERSON>. <CLINICAL>Non si rilevano "
        "fratture.</CLINICAL>"
    ),
    (
        "Accompagnatore <PERSON>Samir Kelvani</PERSON>; paziente <PERSON>Élodie "
        "Courvane</PERSON>. <CLINICAL>Nega vertigini.</CLINICAL>"
    ),
    (
        "Esame eseguito a <LOCATION>Collevento</LOCATION> per <PERSON>Akiko "
        "Hanasori</PERSON>. <CLINICAL>Macula asciutta, 253 µm.</CLINICAL>"
    ),
    (
        "<CLINICAL>Sospetto morbo di Parkinson escluso.</CLINICAL> Interprete: "
        "<PERSON>Viktor Želani</PERSON>."
    ),
    (
        "<FACILITY>Unità Diagnostica del Corallo</FACILITY> / <PERSON>Alma "
        "Fiorvelli</PERSON> / <CLINICAL>FE 62%, ritmo sinusale.</CLINICAL>"
    ),
    (
        "Per conoscenza <PERSON>Sofía Armenti</PERSON>, "
        "<LOCATION>Fontesole</LOCATION>. <CLINICAL>Forte dolore riferito alla "
        "testa.</CLINICAL>"
    ),
    (
        "Referto consegnato da <PERSON>Józef Branecki</PERSON>. <CLINICAL>Test di "
        "Romberg non patologico.</CLINICAL>"
    ),
    (
        "Viene dimessa <PERSON>Nur Alevanti</PERSON> dal <FACILITY>Presidio Sanitario "
        "del Cedro</FACILITY>. <CLINICAL>Apiretica da 48 ore.</CLINICAL>"
    ),
    (
        "<CLINICAL>Il grasso periviscerale non appare aumentato.</CLINICAL> "
        "Responsabile <PERSON>Gaël Vernot</PERSON>."
    ),
    (
        "In attesa a <LOCATION>Lagogemma</LOCATION>: <PERSON>Milena Dravska</PERSON>. "
        "<CLINICAL>Dolore 2/10; nessuna nausea.</CLINICAL>"
    ),
    (
        "Registrazione firmata <PERSON>Idris Malvani</PERSON>. <CLINICAL>Alzheimer "
        "familiare non documentato.</CLINICAL>"
    ),
    (
        "Laboratorio: <FACILITY>Centro Analisi delle Dune</FACILITY>. Richiedente "
        "<PERSON>Chiara Zelvetti</PERSON>. <CLINICAL>Hb 13,4 g/dL.</CLINICAL>"
    ),
    (
        "<PERSON>Étienne Rovard</PERSON> invia a <PERSON>Luz Soriani</PERSON> il "
        "controllo. <CLINICAL>Nessun sanguinamento.</CLINICAL>"
    ),
    (
        "Località <LOCATION>Pratovetro</LOCATION>; pratica di <PERSON>Elena "
        "Kovařík</PERSON>. <CLINICAL>Rene destro regolare.</CLINICAL>"
    ),
    (
        "Il <FACILITY>Servizio Retina dei Salici</FACILITY> comunica: <PERSON>Arun "
        "Devmori</PERSON>, <CLINICAL>papilla rosea senza edema.</CLINICAL>"
    ),
    (
        "<CLINICAL>La dose resta 5 mg una volta al giorno.</CLINICAL> Assistito: "
        "<PERSON>Olivia Marvaux</PERSON> 😀."
    ),
    (
        "Comunicazione a <PERSON>Hugo Castellori</PERSON> presso <FACILITY>Studio "
        "Medico della Rugiada</FACILITY>: <CLINICAL>nessun deficit motorio.</CLINICAL>"
    ),
    "<CLINICAL>Decorso senza complicanze; controllo a dodici mesi.</CLINICAL> "
    + "Esame obiettivo nella norma. " * 190
    + "Conclusioni a cura di <PERSON>Frida Södervik</PERSON>.",
    "<CLINICAL>Non assume anticoagulanti.</CLINICAL> "
    + "osservazione " * 247
    + "<PERSON>André Talvori</PERSON> — domicilio <LOCATION>Rivachiara</LOCATION>.",
]


def parse(marked):
    """!
    @brief Rimuove i tag da un documento marcato e ne calcola le annotazioni.
    @param marked Testo con tag PERSON, LOCATION, FACILITY e CLINICAL non annidati.
    @return Dizionario con testo pulito, entità tipizzate e segmenti clinici, con
            offset in caratteri sul testo pulito.
    """
    text, spans, clinical = "", [], []
    cursor = 0
    for match in re.finditer(r"<(PERSON|LOCATION|FACILITY|CLINICAL)>(.*?)</\1>", marked):
        text += marked[cursor : match.start()]
        start = len(text)
        text += match[2]
        record = dict(start=start, end=len(text))
        if match[1] == "CLINICAL":
            clinical.append(record)
        else:
            spans.append(dict(**record, kind=match[1]))
        cursor = match.end()
    text += marked[cursor:]
    return dict(text=text, entities=spans, clinical_segments=clinical)


def main():
    """!
    @brief Costruisce il corpus da entrambe le partizioni e lo scrive su corpus.json.
    """
    corpus = dict(
        schema_version=1, provenance="authored synthetic; invented names and facilities", docs=[]
    )
    for split, documents in (("development", DEVELOPMENT), ("evaluation", EVALUATION)):
        for index, document in enumerate(documents):
            corpus["docs"].append(dict(id=f"{split}-{index:02}", split=split, **parse(document)))
    Path(__file__).with_name("corpus.json").write_text(
        json.dumps(corpus, ensure_ascii=False, indent=2),
        "utf-8",
    )


if __name__ == "__main__":
    main()
