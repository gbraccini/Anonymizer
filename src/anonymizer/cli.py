"""!
@file cli.py
@brief Interfaccia a riga di comando di Anonymizer.

Espone la pseudonimizzazione di testo semplice (anon/reassoc), l'analisi e
l'esportazione visuale dei documenti (analyze/export) e l'avvio del server di
revisione locale (serve). Gli esiti sono stampati come JSON.
"""

import argparse
import json
import sys
from pathlib import Path

from anonymizer.mapstore import dumps, loads
from anonymizer.model import PageResult, opaque_id
from anonymizer.reassoc import reassociate
from anonymizer.text_pipeline import analyze_text


def _read_text(path: Path) -> str:
    """!
    @brief Legge un file di testo UTF-8 preservando i fine riga originali.
    @param path Percorso del file.
    @return Contenuto del file.
    """
    with path.open("r", encoding="utf-8", newline="") as stream:
        return stream.read()


def _write_text(path: Path, value: str) -> None:
    """!
    @brief Scrive un testo UTF-8 in un file nuovo senza tradurre i fine riga.

    L'apertura in modalità esclusiva impedisce di sovrascrivere file esistenti.
    @param path Percorso di destinazione, che non deve esistere.
    @param value Testo da scrivere.
    """
    with path.open("x", encoding="utf-8", newline="") as stream:
        stream.write(value)


def _ner_options(parser) -> None:
    """!
    @brief Aggiunge al parser le opzioni comuni per NER e parallelismo OCR/NER.
    @param parser Parser o sotto-parser argparse da estendere.
    """
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--ner-model", type=Path, help="Verified local GLiNER directory; never downloads"
    )
    group.add_argument("--no-ner", action="store_true", help="Explicitly disable optional NER")
    parser.add_argument("--ner-threshold", type=float, default=0.5)
    parser.add_argument("--ner-runtime", choices=("torch", "onnx"), default="torch")
    parser.add_argument(
        "--ner-threads",
        type=int,
        choices=range(1, 33),
        help="NER CPU threads (default: hardware auto)",
    )
    parser.add_argument(
        "--ocr-threads", type=int, choices=range(1, 33), help="OCR child CPU threads (default: 1)"
    )
    parser.add_argument("--serial", action="store_true", help="Disable bounded OCR/NER overlap")


def _execution_profile(args):
    """!
    @brief Sceglie una sola volta il profilo di esecuzione e lo memorizza negli argomenti.

    Alla prima chiamata configura anche l'avvio del processo, prima che vengano
    importate le librerie native di inferenza.
    @param args Argomenti analizzati; viene aggiunto l'attributo `execution_profile`.
    @return Il profilo di esecuzione scelto.
    """
    from anonymizer.performance import choose_profile, configure_process_startup

    if not hasattr(args, "execution_profile"):
        args.execution_profile = choose_profile(
            ner_threads=args.ner_threads, ocr_threads=args.ocr_threads, serial=args.serial
        )
        configure_process_startup(args.execution_profile)
    return args.execution_profile


def _load_ner(args):
    """!
    @brief Carica il rilevatore GLiNER se è stato indicato un modello locale.
    @param args Argomenti analizzati con le opzioni NER.
    @return Il rilevatore NER, oppure None se il NER non è configurato.
    @throws NerError Se soglia o runtime sono personalizzati senza un modello.
    """
    if args.ner_model is None:
        if args.ner_threshold != 0.5 or args.ner_runtime != "torch":
            from anonymizer.ner_model import NerError

            raise NerError("ner_threshold_requires_model")
        return None
    profile = _execution_profile(args)
    from anonymizer.detect.ner import GLiNERDetector
    from anonymizer.ner_model import NerConfig

    return GLiNERDetector(
        NerConfig(
            args.ner_model,
            threshold=args.ner_threshold,
            runtime=args.ner_runtime,
            cpu_threads=profile.ner_threads,
        )
    )


def _document_command(args) -> int:
    """!
    @brief Esegue i sottocomandi visuali `analyze` ed `export`.

    Controlla i limiti e che le destinazioni siano distinte dagli input e non
    esistenti, poi scrive il manifest di revisione (analyze) oppure il documento
    oscurato (export). In caso di errore rimuove i file creati e stampa il codice
    d'errore in JSON su stderr.
    @param args Argomenti analizzati del sottocomando.
    @return Codice di uscita: 0 in caso di successo, 1 in caso di errore.
    """
    from anonymizer.export import export_document
    from anonymizer.ingest import InputFile
    from anonymizer.manifest import confirm_review
    from anonymizer.manifest import dumps as dump_manifest
    from anonymizer.manifest import loads as load_manifest
    from anonymizer.pipeline import analyze_documents
    from anonymizer.visual_model import DocumentError, Limits

    created = []
    try:
        limits = Limits()
        if len(args.inputs) > limits.max_files:
            raise DocumentError("input_file_limit")
        source_paths = {path.resolve() for path in args.inputs}
        destinations = [args.manifest] if args.command == "analyze" else [args.output]
        if args.command == "export":
            source_paths.add(args.manifest.resolve())
        resolved = [path.resolve() for path in destinations]
        if len(set(resolved)) != len(resolved) or any(path in source_paths for path in resolved):
            raise DocumentError("output_must_be_distinct_from_inputs")
        if any(path.exists() for path in destinations):
            raise DocumentError("output_already_exists")
        inputs, size = [], 0
        for path in args.inputs:
            with path.open("rb") as stream:
                data = stream.read(limits.max_bytes - size + 1)
            size += len(data)
            if size > limits.max_bytes:
                raise DocumentError("input_byte_limit")
            inputs.append(InputFile(data, path.suffix))
        if args.command == "analyze":
            ner = _load_ner(args)
            analysis = analyze_documents(
                tuple(inputs),
                limits=limits,
                dpi=args.dpi,
                ner=ner,
                ner_disabled_reason="explicitly_disabled" if args.no_ner else "not_configured",
                execution_profile=_execution_profile(args),
            )
            values = [(args.manifest, dump_manifest(analysis.manifest))]
            for path, value in values:
                with path.open("x", encoding="utf-8", newline="") as stream:
                    created.append(path)
                    stream.write(value)
            print(
                json.dumps(
                    {
                        "pages": len(analysis.manifest.pages),
                        "review_required": True,
                        "ner_status": analysis.manifest.ner_audit.status,
                    }
                )
            )
        else:
            manifest = load_manifest(_read_text(args.manifest))
            if args.confirm_review:
                manifest = confirm_review(manifest)
            export_document(tuple(inputs), manifest, args.output, limits=limits)
            print(json.dumps({"pages": len(manifest.pages), "visual_export": True}))
        return 0
    except (OSError, UnicodeError, ValueError, ImportError, RuntimeError, OverflowError):
        for path in created:
            path.unlink(missing_ok=True)
        error = sys.exception()
        from anonymizer.ner_model import NerError

        code = (
            error.code
            if isinstance(error, (DocumentError, NerError))
            else "document_operation_failed"
        )
        print(json.dumps({"error": code}), file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    """!
    @brief Punto di ingresso della CLI: costruisce il parser e smista il sottocomando.
    @param argv Argomenti da analizzare; None usa quelli del processo.
    @return Codice di uscita del processo.
    """
    parser = argparse.ArgumentParser(
        description="Reviewable image/PDF redaction with a separate plain-text core prototype.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    anon = commands.add_parser("anon", help="Text-only core prototype: pseudonymize UTF-8 text")
    anon.add_argument("input", type=Path)
    anon.add_argument("--output", required=True, type=Path)
    anon.add_argument("--map", required=True, type=Path, dest="map_path")
    _ner_options(anon)
    restore = commands.add_parser("reassoc", help="Restore exact map tokens in a UTF-8 text file")
    restore.add_argument("input", type=Path)
    restore.add_argument("--map", required=True, type=Path, dest="map_path")
    restore.add_argument("--output", required=True, type=Path)
    analyze = commands.add_parser(
        "analyze",
        help="Analyze PDF/JPEG/PNG/HEIC into a review manifest; DICOM excluded",
        description=(
            "Visual analysis: opaque 8-bit RGB/L single-frame images only; "
            "ICC, alpha and HDR rejected."
        ),
    )
    analyze.add_argument("inputs", nargs="+", type=Path)
    analyze.add_argument("--manifest", required=True, type=Path)
    analyze.add_argument("--dpi", type=int, default=300)
    _ner_options(analyze)
    export = commands.add_parser(
        "export", help="Export reviewed originals as opaque PNG or raster PDF"
    )
    export.add_argument("inputs", nargs="+", type=Path)
    export.add_argument("--manifest", required=True, type=Path)
    export.add_argument("--output", required=True, type=Path)
    export.add_argument(
        "--confirm-review",
        action="store_true",
        help="Explicitly confirm all current mask decisions and review warnings",
    )
    serve = commands.add_parser("serve", help="Local-only browser review development prototype")
    serve.add_argument("--local-only", action="store_true", required=True)
    serve.add_argument("--port", type=int, default=8765)
    _ner_options(serve)
    args = parser.parse_args(argv)
    if args.command == "serve":
        if not 1024 <= args.port <= 65535:
            parser.error("Invalid local port or NER thread count")
        try:
            import uvicorn

            from anonymizer.ner_model import NerConfig
            from anonymizer.web.app import create_app

            profile = _execution_profile(args)
            config = (
                NerConfig(
                    args.ner_model,
                    threshold=args.ner_threshold,
                    runtime=args.ner_runtime,
                    cpu_threads=profile.ner_threads,
                )
                if args.ner_model
                else None
            )
            if config is None and (args.ner_threshold != 0.5 or args.ner_runtime != "torch"):
                parser.error("NER threshold requires a local model")
            app = create_app(local_only=True, ner_config=config, execution_profile=profile)
            uvicorn.run(
                app,
                host="127.0.0.1",
                port=args.port,
                workers=1,
                access_log=False,
                proxy_headers=False,
                log_level="critical",
            )
            return 0
        except (ImportError, ValueError, OSError):
            print(json.dumps({"error": "local_server_start_failed"}), file=sys.stderr)
            return 1
    if args.command in ("analyze", "export"):
        return _document_command(args)
    paths = [args.input.resolve(), args.output.resolve(), args.map_path.resolve()]
    if len(set(paths)) != len(paths):
        parser.error("Input, output and map paths must be distinct")
    if args.output.exists() or (args.command == "anon" and args.map_path.exists()):
        parser.error("Output paths must not already exist")
    try:
        text = _read_text(args.input)
        if args.command == "anon":
            if args.input.suffix.lower() != ".txt":
                parser.error("Only .txt input is supported by this command")
            page = PageResult(opaque_id(), opaque_id(), 0, text)
            analysis = analyze_text(
                [page],
                ner=_load_ner(args),
                ner_disabled_reason="explicitly_disabled" if args.no_ner else "not_configured",
            )
            result = analysis.result
            _write_text(args.map_path, dumps(result.map))
            _write_text(args.output, result.pages[0].text)
            print(
                json.dumps(
                    {
                        "replacements": len(result.replacements),
                        "review_required": True,
                        "ner_status": analysis.ner_audit.status,
                    }
                )
            )
        else:
            result = reassociate(text, loads(_read_text(args.map_path)))
            _write_text(args.output, result.text)
            print(json.dumps({"unknown_tokens": len(result.unknown_tokens)}))
        return 0
    except (OSError, UnicodeError, ValueError):
        from anonymizer.ner_model import NerError

        if isinstance(sys.exception(), NerError):
            print(json.dumps({"error": sys.exception().code}), file=sys.stderr)
            return 1
        print("Operation failed: check input format and output access.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
