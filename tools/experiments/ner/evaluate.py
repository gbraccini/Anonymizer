## @file experiments/ner/evaluate.py
#  @brief Valuta il rilevatore NER su una partizione del corpus sintetico.
#
#  Confronta l'analisi senza NER con quella che usa il modello GLiNER indicato e
#  scrive un report JSON con sole metriche (mai testo dei documenti). La docstring
#  di modulo resta invariata perché è usata come descrizione della riga di comando.
"""Evaluate one explicitly selected synthetic split; output contains metrics, never text."""

import argparse
import ctypes
import json
import math
import os
import statistics
import time
from dataclasses import asdict
from pathlib import Path

from anonymizer.detect.ner import GLiNERDetector
from anonymizer.model import PageResult
from anonymizer.ner_model import NerConfig
from anonymizer.pseudo import should_mask
from anonymizer.text_pipeline import analyze_text

## Tipi di entità valutati; DOCTOR viene contato come PERSON.
KINDS = ("PERSON", "LOCATION", "FACILITY")


def matched_count(expected, predicted, partial):
    """!
    @brief Conta le corrispondenze uno a uno tra intervalli attesi e predetti.

    Costruisce un grafo bipartito e calcola un abbinamento massimo con cammini
    aumentanti, così ogni predizione vale al più per un'entità attesa.
    @param expected Intervalli attesi come coppie (inizio, fine).
    @param predicted Intervalli predetti come coppie (inizio, fine).
    @param partial Se vero basta una sovrapposizione, altrimenti serve uguaglianza esatta.
    @return Numero di entità attese abbinate.
    """
    edges = [
        [
            i
            for i, p in enumerate(predicted)
            if (max(e[0], p[0]) < min(e[1], p[1]) if partial else e == p)
        ]
        for e in expected
    ]
    matched = {}

    def augment(index, visited):
        """!
        @brief Cerca un cammino aumentante a partire da un'entità attesa.
        @param index Indice dell'entità attesa da abbinare.
        @param visited Predizioni già esplorate in questa ricerca.
        @return Vero se l'abbinamento è stato esteso.
        """
        for target in edges[index]:
            if target in visited:
                continue
            visited.add(target)
            if target not in matched or augment(matched[target], visited):
                matched[target] = index
                return True
        return False

    return sum(augment(index, set()) for index in range(len(expected)))


def memory_peak_bytes():
    """!
    @brief Restituisce il picco di memoria residente del processo corrente.

    Su sistemi POSIX usa resource (kilobyte su Linux, byte su macOS); su Windows
    interroga GetProcessMemoryInfo e ne legge il picco del working set.
    @return Picco di memoria in byte.
    @throws RuntimeError Se la misura su Windows fallisce.
    """
    if os.name != "nt":
        import resource
        import sys

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return peak if sys.platform == "darwin" else peak * 1024

    class Counters(ctypes.Structure):
        """!
        @brief Layout della struttura PROCESS_MEMORY_COUNTERS di Windows.
        """

        _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [
            (name, ctypes.c_size_t)
            for name in (
                "peak_working",
                "working",
                "peak_paged",
                "paged",
                "peak_nonpaged",
                "nonpaged",
                "pagefile",
                "peak_pagefile",
            )
        ]

    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.windll.kernel32
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
    get_memory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    if not get_memory(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise RuntimeError("memory_measurement_failed")
    return counters.peak_working


def evaluate(documents, detector):
    """!
    @brief Esegue l'analisi sui documenti e aggrega metriche e tempi.

    Calcola richiamo e precisione per tipo (esatti e parziali), la copertura
    effettiva del mascheramento sulle entità e i caratteri clinici mascherati
    per errore, oltre a tempi totale, mediano e al 95° percentile.
    @param documents Documenti del corpus con testo, entità e segmenti clinici.
    @param detector Rilevatore NER da usare, oppure None per la sola baseline.
    @return Dizionario con metriche per entità, copertura e tempi di esecuzione.
    """
    totals = {kind: dict(expected=0, predicted=0, exact=0, partial=0) for kind in KINDS}
    coverage = dict(
        entity_characters=0,
        masked_entity_characters=0,
        entities=0,
        fully_covered_entities=0,
        clinical_characters=0,
        falsely_masked_clinical_characters=0,
        clinical_segments=0,
        affected_clinical_segments=0,
        documents_with_residual_entities=0,
    )
    durations = []
    for document in documents:
        page = PageResult(document["id"], "synthetic", 0, document["text"])
        started = time.perf_counter()
        analysis = analyze_text([page], ner=detector)
        durations.append(time.perf_counter() - started)
        predictions = {
            ("PERSON" if s.kind.value == "DOCTOR" else s.kind.value, s.start, s.end)
            for s in analysis.candidates
        }
        for kind in KINDS:
            expected = [(s["start"], s["end"]) for s in document["entities"] if s["kind"] == kind]
            predicted = [(start, end) for k, start, end in predictions if k == kind]
            totals[kind]["expected"] += len(expected)
            totals[kind]["predicted"] += len(predicted)
            totals[kind]["exact"] += matched_count(expected, predicted, False)
            totals[kind]["partial"] += matched_count(expected, predicted, True)
        masked = set()
        for span in analysis.merged_spans:
            if should_mask(span):
                masked.update(range(span.start, span.end))
        residual = False
        for entity in document["entities"]:
            characters = set(range(entity["start"], entity["end"]))
            coverage["entities"] += 1
            coverage["entity_characters"] += len(characters)
            coverage["masked_entity_characters"] += len(characters & masked)
            covered = characters <= masked
            coverage["fully_covered_entities"] += covered
            residual |= not covered
        coverage["documents_with_residual_entities"] += residual
        for segment in document["clinical_segments"]:
            characters = set(range(segment["start"], segment["end"]))
            coverage["clinical_segments"] += 1
            coverage["clinical_characters"] += len(characters)
            coverage["falsely_masked_clinical_characters"] += len(characters & masked)
            coverage["affected_clinical_segments"] += bool(characters & masked)
    metrics = {}
    for kind, counts in totals.items():
        metrics[kind] = dict(counts)
        for mode in ("exact", "partial"):
            metrics[kind][f"{mode}_recall"] = (
                counts[mode] / counts["expected"] if counts["expected"] else None
            )
            metrics[kind][f"{mode}_precision"] = (
                counts[mode] / counts["predicted"] if counts["predicted"] else None
            )
    ordered = sorted(durations)
    return dict(
        entity_metrics=metrics,
        output_mask_coverage=coverage,
        runtime_seconds=dict(
            total=sum(durations),
            median=statistics.median(durations),
            p95=ordered[math.ceil(0.95 * len(ordered)) - 1],
        ),
    )


def main():
    """!
    @brief Punto di ingresso: legge gli argomenti, valuta e scrive il report.

    Il file di output non deve esistere e viene creato in modo esclusivo.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path(__file__).with_name("corpus.json"))
    parser.add_argument("--split", choices=("development", "evaluation"), required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.threads < 1:
        parser.error("threads must be positive")
    if args.output.exists():
        parser.error("output must not exist")
    corpus_raw = args.corpus.read_bytes()
    corpus = json.loads(corpus_raw)
    documents = [doc for doc in corpus["docs"] if doc["split"] == args.split]
    import hashlib

    import torch

    torch.set_num_threads(args.threads)
    baseline = evaluate(documents, None)
    started = time.perf_counter()
    detector = GLiNERDetector(NerConfig(args.model, threshold=args.threshold))
    cold_load = time.perf_counter() - started
    enhanced = evaluate(documents, detector)
    report = dict(
        schema_version=1,
        split=args.split,
        documents=len(documents),
        corpus_sha256=hashlib.sha256(corpus_raw).hexdigest(),
        model=asdict(detector.audit),
        baseline=baseline,
        with_ner=enhanced,
        cold_load_seconds=cold_load,
        process_peak_rss_bytes=memory_peak_bytes(),
        threads=args.threads,
        limitations=[
            "synthetic corpus only",
            "max_width bounds entity length",
            "partial matching is same-type overlap, not privacy coverage",
            "RAM is process lifetime peak; includes baseline and model",
        ],
    )
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
    print(json.dumps(dict(status="evaluated", split=args.split, documents=len(documents))))


if __name__ == "__main__":
    main()
