"""Operator CLI for Ayin and Manasek import, inspection, and validation."""

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.core.ayin.importer import AyinImporter, default_seed_manifest
from app.core.ayin.service import AyinExtractionService, AyinReadService
from app.core.ayin.validator import AyinStructuralValidator
from app.core.config import get_settings
from app.db.session import Database, create_database
from app.knowledge.adapters.youtube import YouTubeAdapter
from app.knowledge.importer import ExternalKnowledgeImporter
from app.knowledge.llm.codex import CodexCliProvider
from app.knowledge.media import MediaService
from app.knowledge.resolution import (
    CrossrefResolver,
    OpenAlexResolver,
    OpenLibraryResolver,
    WikidataResolver,
)
from app.knowledge.resolution_service import ResolutionService
from app.knowledge.service import KnowledgeReadService
from app.knowledge.validator import KnowledgeStructuralValidator
from app.ops.logging import configure_logging
from app.retrieval.chunking import ChunkBuilder
from app.retrieval.domain import QueryLanguage, RetrievalLane
from app.retrieval.embeddings import (
    EmbeddingService,
    SentenceTransformerEmbeddingProvider,
)
from app.retrieval.evaluation import RetrievalEvaluationService
from app.retrieval.service import HybridRetrievalService
from app.retrieval.validator import RetrievalStructuralValidator
from app.ritual.importer import ManasekImporter
from app.ritual.models import SafetyValidationResult
from app.ritual.safety import VALIDATOR_VERSION, RitualSafetyValidator
from app.ritual.service import RitualReadService
from app.ritual.validator import RitualStructuralValidator
from app.storage.local import LocalObjectStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="emtedad")
    domains = parser.add_subparsers(dest="domain", required=True)
    ayin = domains.add_parser("ayin")
    commands = ayin.add_subparsers(dest="command", required=True)

    import_command = commands.add_parser("import")
    import_command.add_argument("file", type=Path)
    import_command.add_argument(
        "--without-seed",
        action="store_true",
        help="Import passages only; do not load the reviewed current-source seed.",
    )
    inspect = commands.add_parser("inspect-document")
    inspect.add_argument("id", type=UUID)
    commands.add_parser("list-concepts")
    show = commands.add_parser("show-concept")
    show.add_argument("stable_key")
    commands.add_parser("list-distinction", aliases=["list-distinctions"])
    commands.add_parser("list-principles")
    commands.add_parser("list-relations")
    commands.add_parser("list-open-questions")
    terminology = commands.add_parser("terminology")
    terminology.add_argument("term")
    commands.add_parser("validate")
    prefer = commands.add_parser("prefer-extraction")
    prefer.add_argument("run_id", type=UUID)
    prefer.add_argument("--selected-by", required=True)
    prefer.add_argument("--reason", required=True)

    manasek = domains.add_parser("manasek")
    ritual_commands = manasek.add_subparsers(dest="command", required=True)
    ritual_import = ritual_commands.add_parser("import")
    ritual_import.add_argument("file", type=Path)
    ritual_inspect = ritual_commands.add_parser("inspect-document")
    ritual_inspect.add_argument("id", type=UUID)
    ritual_commands.add_parser("list-gates")
    ritual_commands.add_parser("list-stages")
    ritual_commands.add_parser("list-rituals")
    ritual_show = ritual_commands.add_parser("show-ritual")
    ritual_show.add_argument("id", type=UUID)
    ritual_commands.add_parser("validate")
    safety_check = ritual_commands.add_parser("safety-check")
    safety_check.add_argument("ritual_id", type=UUID)

    knowledge = domains.add_parser("knowledge")
    knowledge_commands = knowledge.add_subparsers(dest="command", required=True)
    ingest_youtube = knowledge_commands.add_parser("ingest-youtube")
    ingest_youtube.add_argument("locator")
    ingest_youtube.add_argument("--model", default="configured-default")
    ingest_youtube.add_argument("--window-size", type=int, default=50)
    ingest_youtube.add_argument("--overlap", type=int, default=8)
    inspect_source = knowledge_commands.add_parser("inspect-source")
    inspect_source.add_argument("id", type=UUID)
    list_segments = knowledge_commands.add_parser("list-segments")
    list_segments.add_argument("version_id", type=UUID)
    list_mentions = knowledge_commands.add_parser("list-mentions")
    list_mentions.add_argument("--source-id", type=UUID)
    list_references = knowledge_commands.add_parser("list-references")
    list_references.add_argument("--source-id", type=UUID)
    knowledge_commands.add_parser("list-claims")
    knowledge_commands.add_parser("list-people")
    knowledge_commands.add_parser("list-works")
    inspect_person = knowledge_commands.add_parser("inspect-person")
    inspect_person.add_argument("id", type=UUID)
    inspect_work = knowledge_commands.add_parser("inspect-work")
    inspect_work.add_argument("id", type=UUID)
    knowledge_commands.add_parser("list-review")
    resolve = knowledge_commands.add_parser("resolve-pending")
    resolve.add_argument("--source-id", type=UUID)
    resolve.add_argument("--limit", type=int)
    knowledge_commands.add_parser("validate")

    retrieval = domains.add_parser("retrieval")
    retrieval_commands = retrieval.add_subparsers(dest="command", required=True)
    retrieval_commands.add_parser("build-chunks")
    build_embeddings = retrieval_commands.add_parser("build-embeddings")
    build_embeddings.add_argument("chunking_run_id", type=UUID)
    search = retrieval_commands.add_parser("search")
    search.add_argument("query")
    search.add_argument(
        "--language", choices=[item.value for item in QueryLanguage], required=True
    )
    search.add_argument("--chunking-run-id", type=UUID, required=True)
    search.add_argument("--embedding-model-id", type=UUID, required=True)
    search.add_argument(
        "--lane", action="append", choices=[item.value for item in RetrievalLane]
    )
    seed_evaluation = retrieval_commands.add_parser("seed-evaluation")
    seed_evaluation.add_argument("chunking_run_id", type=UUID)
    evaluate = retrieval_commands.add_parser("evaluate")
    evaluate.add_argument("chunking_run_id", type=UUID)
    evaluate.add_argument("embedding_model_id", type=UUID)
    validate_retrieval = retrieval_commands.add_parser("validate")
    validate_retrieval.add_argument("chunking_run_id", type=UUID)
    validate_retrieval.add_argument("--embedding-model-id", type=UUID)
    return parser


def _json(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    elif isinstance(value, list) and value and isinstance(value[0], BaseModel):
        value = [item.model_dump(mode="json") for item in value]
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.log_json)
    database = create_database(settings)
    store = LocalObjectStore(settings.storage_root)
    try:
        if args.domain == "manasek":
            return await _run_manasek(args, database, store)
        if args.domain == "knowledge":
            return await _run_knowledge(args, database, store)
        if args.domain == "retrieval":
            return await _run_retrieval(args, database, settings.storage_root)
        if args.command == "import":
            manifest = None if args.without_seed else default_seed_manifest()
            result = await AyinImporter(database, store).import_file(
                args.file, seed_manifest=manifest
            )
            print(_json(asdict(result)))
            return 0

        async with database.transaction() as session:
            if args.command == "prefer-extraction":
                preference_output = await AyinExtractionService(session).prefer(
                    args.run_id,
                    selected_by=args.selected_by,
                    reason=args.reason,
                )
                print(_json(preference_output))
                return 0
            service = AyinReadService(session)
            if args.command == "inspect-document":
                output: Any = await service.document(args.id)
            elif args.command == "list-concepts":
                output = await service.concepts()
            elif args.command == "show-concept":
                output = await service.concept(args.stable_key)
            elif args.command in {"list-distinction", "list-distinctions"}:
                output = await service.distinctions()
            elif args.command == "list-principles":
                output = await service.principles()
            elif args.command == "list-relations":
                output = await service.relations()
            elif args.command == "list-open-questions":
                output = await service.open_questions()
            elif args.command == "terminology":
                output = await service.terms(args.term)
            elif args.command == "validate":
                output = await AyinStructuralValidator(session, store).validate()
            else:  # argparse protects this branch
                raise RuntimeError(f"unsupported command: {args.command}")
        print(_json(output))
        if args.command == "validate" and not output.valid:
            return 1
        return 0
    finally:
        await database.dispose()


async def _run_retrieval(
    args: argparse.Namespace, database: Database, storage_root: Path
) -> int:
    provider = SentenceTransformerEmbeddingProvider(
        cache_folder=storage_root / "models"
    )
    if args.command == "build-chunks":
        output: Any = asdict(await ChunkBuilder(database).build())
    elif args.command == "build-embeddings":
        output = asdict(
            await EmbeddingService(database, provider).build(args.chunking_run_id)
        )
    elif args.command == "search":
        output = await HybridRetrievalService(database, provider).search(
            args.query,
            QueryLanguage(args.language),
            chunking_run_id=args.chunking_run_id,
            embedding_model_id=args.embedding_model_id,
            lanes=[RetrievalLane(item) for item in args.lane] if args.lane else None,
        )
    elif args.command == "seed-evaluation":
        count = await RetrievalEvaluationService(
            database, HybridRetrievalService(database, provider)
        ).seed_ayin_queries(args.chunking_run_id)
        output = {"query_count": count}
    elif args.command == "evaluate":
        summary = await RetrievalEvaluationService(
            database, HybridRetrievalService(database, provider)
        ).evaluate(
            chunking_run_id=args.chunking_run_id,
            embedding_model_id=args.embedding_model_id,
        )
        output = asdict(summary)
        print(_json(output))
        return 0 if summary.passed else 1
    elif args.command == "validate":
        async with database.transaction() as session:
            result = await RetrievalStructuralValidator(session).validate(
                args.chunking_run_id, args.embedding_model_id
            )
        output = asdict(result)
        print(_json(output))
        return 0 if result.valid else 1
    else:
        raise RuntimeError(f"unsupported retrieval command: {args.command}")
    print(_json(output))
    return 0


async def _run_manasek(
    args: argparse.Namespace, database: Database, store: LocalObjectStore
) -> int:
    if args.command == "import":
        result = await ManasekImporter(database, store).import_file(args.file)
        print(_json(asdict(result)))
        return 0
    async with database.transaction() as session:
        service = RitualReadService(session)
        if args.command == "inspect-document":
            documents = await service.documents()
            output: Any = next((item for item in documents if item.id == args.id), None)
            if output is None:
                raise RuntimeError("ritual document not found")
        elif args.command == "list-gates":
            output = await service.gates()
        elif args.command == "list-stages":
            output = await service.stages()
        elif args.command == "list-rituals":
            output = await service.rituals()
        elif args.command == "show-ritual":
            output = await service.ritual(args.id)
        elif args.command == "validate":
            output = await RitualStructuralValidator(session, store).validate()
        elif args.command == "safety-check":
            ritual = await service.ritual(args.ritual_id)
            output = await RitualSafetyValidator(session).validate_version(
                ritual.version_id
            )
            session.add(
                SafetyValidationResult(
                    ritual_version_id=ritual.version_id,
                    valid=output.valid,
                    publishable=output.publishable,
                    issues=[item.model_dump(mode="json") for item in output.issues],
                    validator_version=VALIDATOR_VERSION,
                )
            )
        else:
            raise RuntimeError(f"unsupported Manasek command: {args.command}")
    print(_json(output))
    return 0 if not hasattr(output, "valid") or output.valid else 1


async def _run_knowledge(
    args: argparse.Namespace, database: Database, store: LocalObjectStore
) -> int:
    if args.command == "ingest-youtube":
        result = await ExternalKnowledgeImporter(
            database,
            YouTubeAdapter(),
            CodexCliProvider(),
            model=args.model,
            window_size=args.window_size,
            overlap=args.overlap,
            media_service=MediaService(database, store),
        ).ingest(args.locator)
        print(_json(asdict(result)))
        return 0 if result.failed_windows == 0 else 1
    if args.command == "resolve-pending":
        resolution_result = await ResolutionService(
            database,
            [
                CrossrefResolver(),
                OpenAlexResolver(),
                OpenLibraryResolver(),
                WikidataResolver(),
            ],
        ).resolve_pending(args.source_id, limit=args.limit)
        print(_json(asdict(resolution_result)))
        return 0
    async with database.transaction() as session:
        service = KnowledgeReadService(session)
        if args.command == "inspect-source":
            output: Any = {
                "source": await service.source(args.id),
                "versions": await service.versions(args.id),
            }
        elif args.command == "list-segments":
            output = await service.segments(args.version_id)
        elif args.command in {"list-mentions", "list-references"}:
            output = (
                await service.source_mentions(args.source_id)
                if args.source_id
                else await service.mentions()
            )
        elif args.command == "list-claims":
            output = await service.claims()
        elif args.command == "list-people":
            output = await service.people()
        elif args.command == "list-works":
            output = await service.works()
        elif args.command == "inspect-person":
            output = await service.person(args.id)
        elif args.command == "inspect-work":
            output = await service.work(args.id)
        elif args.command == "list-review":
            output = await service.review_queue()
        elif args.command == "validate":
            output = await KnowledgeStructuralValidator(session).validate()
        else:
            raise RuntimeError(f"unsupported knowledge command: {args.command}")
    print(_json(output))
    return 0 if not hasattr(output, "valid") or output.valid else 1


def main() -> None:
    """Parse operator arguments and run one explicit Ayin command."""

    raise SystemExit(asyncio.run(_run(_parser().parse_args())))


if __name__ == "__main__":
    main()
