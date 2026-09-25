"""Operator CLI for Ayin and Manasek import, inspection, and validation."""

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.content_strategy.strategy_service import TopicStrategyService
from app.core.ayin.importer import AyinImporter, default_seed_manifest
from app.core.ayin.service import AyinExtractionService, AyinReadService
from app.core.ayin.validator import AyinStructuralValidator
from app.core.config import get_settings
from app.db.session import Database, create_database
from app.dialogue.classifier import EvidenceRoleClassifier
from app.dialogue.domain import (
    AyinTargetKind,
    RelationScope,
    RelationType,
    ReviewAction,
)
from app.dialogue.schemas import (
    CounterevidenceRequest,
    ProposeRequest,
    ReviewRequest,
)
from app.dialogue.service import DialogueService
from app.knowledge.adapters.youtube import YouTubeAdapter
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
from app.lecture.domain import LectureType
from app.lecture.schemas import LectureProjectCreate
from app.lecture.service import LectureMasterService
from app.ops.logging import configure_logging
from app.research.schemas import (
    AyinSpineBuildRequest,
    ResearchPackageBuildRequest,
    ResearchPlanCreate,
    ResearchProjectCreate,
)
from app.research.service import ResearchEngineService
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
from app.semantic_content.ingestion import SemanticKnowledgePipeline
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
    prepare_semantic = knowledge_commands.add_parser("prepare-semantic-all")
    prepare_semantic.add_argument("--model", default="configured-default")
    prepare_semantic.add_argument("--include-historical", action="store_true")
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

    dialogue = domains.add_parser("dialogue")
    dialogue_commands = dialogue.add_subparsers(dest="command", required=True)
    propose_dialogue = dialogue_commands.add_parser("propose")
    _add_ayin_target_arguments(propose_dialogue)
    propose_dialogue.add_argument(
        "--language", choices=[item.value for item in QueryLanguage], default="fa"
    )
    propose_dialogue.add_argument("--chunking-run-id", type=UUID)
    propose_dialogue.add_argument("--embedding-model-id", type=UUID)
    propose_dialogue.add_argument("--model", default="configured-default")
    propose_dialogue.add_argument("--max-candidates", type=int, default=5)
    inspect_dialogue = dialogue_commands.add_parser("inspect")
    inspect_dialogue.add_argument("relation_id", type=UUID)
    list_dialogue = dialogue_commands.add_parser("list")
    list_dialogue.add_argument(
        "--relation-type",
        type=str.upper,
        choices=[item.value for item in RelationType],
    )
    dialogue_commands.add_parser("list-review")
    dialogue_commands.add_parser("validate")
    counterevidence = dialogue_commands.add_parser("counterevidence")
    _add_ayin_target_arguments(counterevidence)
    counterevidence.add_argument(
        "--language", choices=[item.value for item in QueryLanguage], default="fa"
    )
    counterevidence.add_argument("--chunking-run-id", type=UUID)
    counterevidence.add_argument("--embedding-model-id", type=UUID)
    counterevidence.add_argument("--limit", type=int, default=10)
    review_dialogue = dialogue_commands.add_parser("review")
    review_dialogue.add_argument("relation_id", type=UUID)
    review_dialogue.add_argument(
        "--action",
        type=str.upper,
        choices=[item.value for item in ReviewAction],
        required=True,
    )
    review_dialogue.add_argument("--reviewer", required=True)
    review_dialogue.add_argument("--notes", required=True)
    review_dialogue.add_argument(
        "--relation-type",
        type=str.upper,
        choices=[item.value for item in RelationType],
    )
    review_dialogue.add_argument(
        "--scope",
        type=str.upper,
        choices=[item.value for item in RelationScope],
    )
    review_dialogue.add_argument("--explanation")

    research = domains.add_parser("research")
    research_commands = research.add_subparsers(dest="command", required=True)
    create_research = research_commands.add_parser("create")
    create_research.add_argument("question")
    create_research.add_argument("--created-by", default="operator")
    build_spine = research_commands.add_parser("build-spine")
    build_spine.add_argument("project_id", type=UUID)
    build_spine.add_argument("--primary-concept", required=True)
    build_spine.add_argument("--secondary-concept", action="append", default=[])
    build_spine.add_argument("--principle", action="append", default=[])
    build_spine.add_argument("--distinction", action="append", default=[])
    build_spine.add_argument("--open-question", action="append", default=[])
    build_spine.add_argument("--passage-id", action="append", type=UUID, default=[])
    build_spine.add_argument("--canon-version-id", type=UUID)
    build_spine.add_argument("--canonical-question")
    show_spine = research_commands.add_parser("show-spine")
    show_spine.add_argument("spine_id", type=UUID)
    make_plan = research_commands.add_parser("plan")
    make_plan.add_argument("spine_id", type=UUID)
    make_plan.add_argument("--manasek-relevant", action="store_true")
    make_plan.add_argument("--manasek-reason")
    show_plan = research_commands.add_parser("show-plan")
    show_plan.add_argument("plan_id", type=UUID)
    build_package = research_commands.add_parser("build-package")
    build_package.add_argument("plan_id", type=UUID)
    build_package.add_argument("--chunking-run-id", type=UUID)
    build_package.add_argument("--embedding-model-id", type=UUID)
    build_package.add_argument("--include-manasek", action="store_true")
    inspect_package = research_commands.add_parser("inspect-package")
    inspect_package.add_argument("package_id", type=UUID)
    research_commands.add_parser("list-packages")
    research_commands.add_parser("validate")

    lecture = domains.add_parser("lecture")
    lecture_commands = lecture.add_subparsers(dest="command", required=True)
    create_lecture = lecture_commands.add_parser("create")
    create_lecture.add_argument("--research-package", type=UUID, required=True)
    create_lecture.add_argument(
        "--lecture-type", choices=[item.value for item in LectureType], required=True
    )
    create_lecture.add_argument("--title", required=True)
    create_lecture.add_argument("--duration", type=int)
    create_lecture.add_argument("--audience")
    create_lecture.add_argument("--created-by", default="operator")
    architect_lecture = lecture_commands.add_parser("architect")
    architect_lecture.add_argument("lecture_id", type=UUID)
    inspect_lecture = lecture_commands.add_parser("inspect")
    inspect_lecture.add_argument("lecture_id", type=UUID)
    validate_lecture = lecture_commands.add_parser("validate")
    validate_lecture.add_argument("master_id", type=UUID)
    freeze_lecture = lecture_commands.add_parser("freeze")
    freeze_lecture.add_argument("master_id", type=UUID)
    export_lecture = lecture_commands.add_parser("export")
    export_lecture.add_argument("master_id", type=UUID)

    strategy = domains.add_parser("strategy")
    strategy_commands = strategy.add_subparsers(dest="command", required=True)
    reset_strategy = strategy_commands.add_parser(
        "reset", help="remove the legacy fixed strategy tree"
    )
    reset_strategy.add_argument(
        "--confirm",
        action="store_true",
        help="perform the destructive reset; without it only a preview is shown",
    )
    return parser


def _add_ayin_target_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--ayin-concept")
    group.add_argument("--ayin-principle")
    group.add_argument("--ayin-distinction")
    group.add_argument("--ayin-open-question")


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
        if args.domain == "dialogue":
            return await _run_dialogue(args, database, settings.storage_root)
        if args.domain == "research":
            return await _run_research(args, database, settings.storage_root)
        if args.domain == "lecture":
            return await _run_lecture(args, database)
        if args.domain == "strategy":
            return await _run_strategy(args, database)
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


async def _run_research(
    args: argparse.Namespace, database: Database, storage_root: Path
) -> int:
    service = ResearchEngineService(
        database,
        SentenceTransformerEmbeddingProvider(cache_folder=storage_root / "models"),
    )
    if args.command == "create":
        output: Any = await service.create_project(
            ResearchProjectCreate(
                human_question=args.question, created_by=args.created_by
            )
        )
    elif args.command == "build-spine":
        output = await service.build_spine(
            AyinSpineBuildRequest(
                project_id=args.project_id,
                primary_concept=args.primary_concept,
                secondary_concepts=args.secondary_concept,
                principle_ids=args.principle,
                distinction_ids=args.distinction,
                open_question_ids=args.open_question,
                passage_ids=args.passage_id,
                canon_version_id=args.canon_version_id,
                canonical_question=args.canonical_question,
            )
        )
    elif args.command == "show-spine":
        output = await service.spine(args.spine_id)
    elif args.command == "plan":
        output = await service.create_plan(
            ResearchPlanCreate(
                spine_id=args.spine_id,
                manasek_relevant=args.manasek_relevant,
                manasek_reason=args.manasek_reason,
            )
        )
    elif args.command == "show-plan":
        output = await service.plan(args.plan_id)
    elif args.command == "build-package":
        output = await service.build_package(
            ResearchPackageBuildRequest(
                plan_id=args.plan_id,
                chunking_run_id=args.chunking_run_id,
                embedding_model_id=args.embedding_model_id,
                include_manasek=args.include_manasek,
            )
        )
    elif args.command == "inspect-package":
        output = await service.package(args.package_id)
    elif args.command == "list-packages":
        output = await service.packages()
    elif args.command == "validate":
        output = await service.validate()
        print(_json(output))
        return 0 if output.valid else 1
    else:
        raise RuntimeError(f"unsupported research command: {args.command}")
    print(_json(output))
    return 0


async def _run_lecture(args: argparse.Namespace, database: Database) -> int:
    service = LectureMasterService(database)
    if args.command == "create":
        output: Any = await service.create_project(
            LectureProjectCreate(
                research_package_id=args.research_package,
                lecture_type=LectureType(args.lecture_type),
                working_title=args.title,
                target_duration_seconds=args.duration,
                target_audience=args.audience,
                created_by=args.created_by,
            )
        )
    elif args.command == "architect":
        output = await service.architect(args.lecture_id)
    elif args.command == "inspect":
        output = await service.master(args.lecture_id)
    elif args.command == "validate":
        output = await service.validate(args.master_id)
    elif args.command == "freeze":
        output = await service.freeze(args.master_id)
    elif args.command == "export":
        output = await service.export(args.master_id)
    else:
        raise RuntimeError(f"unsupported lecture command: {args.command}")
    print(_json(output))
    return 0


async def _run_strategy(args: argparse.Namespace, database: Database) -> int:
    if args.command != "reset":
        raise RuntimeError(f"unsupported strategy command: {args.command}")
    result = await TopicStrategyService(database).reset_legacy(confirm=args.confirm)
    print(_json(result))
    return 0 if args.confirm else 2


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


def _dialogue_target(args: argparse.Namespace) -> tuple[AyinTargetKind, str]:
    for attribute, kind in (
        ("ayin_concept", AyinTargetKind.CONCEPT_VERSION),
        ("ayin_principle", AyinTargetKind.PRINCIPLE_VERSION),
        ("ayin_distinction", AyinTargetKind.DISTINCTION_VERSION),
        ("ayin_open_question", AyinTargetKind.OPEN_QUESTION_VERSION),
    ):
        value = getattr(args, attribute, None)
        if value:
            return kind, value
    raise RuntimeError("an Ayin target is required")


async def _run_dialogue(
    args: argparse.Namespace, database: Database, storage_root: Path
) -> int:
    model = getattr(args, "model", "configured-default")
    service = DialogueService(
        database,
        SentenceTransformerEmbeddingProvider(cache_folder=storage_root / "models"),
        EvidenceRoleClassifier(CodexCliProvider(), model=model),
    )
    if args.command == "propose":
        kind, identifier = _dialogue_target(args)
        output: Any = await service.propose(
            ProposeRequest(
                ayin_target_kind=kind,
                ayin_identifier=identifier,
                language=QueryLanguage(args.language),
                chunking_run_id=args.chunking_run_id,
                embedding_model_id=args.embedding_model_id,
                model=args.model,
                max_candidates=args.max_candidates,
            )
        )
    elif args.command == "counterevidence":
        kind, identifier = _dialogue_target(args)
        output = await service.counterevidence(
            CounterevidenceRequest(
                ayin_target_kind=kind,
                ayin_identifier=identifier,
                language=QueryLanguage(args.language),
                chunking_run_id=args.chunking_run_id,
                embedding_model_id=args.embedding_model_id,
                limit=args.limit,
            )
        )
    elif args.command == "inspect":
        output = await service.relation(args.relation_id)
    elif args.command == "list":
        output = await service.relations(
            relation_type=RelationType(args.relation_type)
            if args.relation_type
            else None
        )
    elif args.command == "list-review":
        output = await service.review_queue()
    elif args.command == "validate":
        output = await service.validate()
        print(_json(output))
        return 0 if output.valid else 1
    elif args.command == "review":
        output = await service.review(
            args.relation_id,
            ReviewRequest(
                action=ReviewAction(args.action),
                reviewer=args.reviewer,
                notes=args.notes,
                relation_type=RelationType(args.relation_type)
                if args.relation_type
                else None,
                scope=RelationScope(args.scope) if args.scope else None,
                explanation=args.explanation,
            ),
        )
    else:
        raise RuntimeError(f"unsupported dialogue command: {args.command}")
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
        result = await SemanticKnowledgePipeline(
            database,
            YouTubeAdapter(),
            CodexCliProvider(),
            SentenceTransformerEmbeddingProvider(),
            model=args.model,
            extraction_window_size=args.window_size,
            extraction_overlap=args.overlap,
            media_service=MediaService(database, store),
        ).ingest(args.locator)
        print(_json(asdict(result)))
        return 0 if result.failed_extraction_windows == 0 else 1
    if args.command == "prepare-semantic-all":
        result = await SemanticKnowledgePipeline(
            database,
            YouTubeAdapter(),
            CodexCliProvider(),
            SentenceTransformerEmbeddingProvider(),
            model=args.model,
        ).backfill_existing(include_historical=args.include_historical)
        print(_json(asdict(result)))
        return 0 if not result.failed_source_version_ids else 1
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
