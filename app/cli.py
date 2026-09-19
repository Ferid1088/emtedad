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
from app.ops.logging import configure_logging
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


def main() -> None:
    """Parse operator arguments and run one explicit Ayin command."""

    raise SystemExit(asyncio.run(_run(_parser().parse_args())))


if __name__ == "__main__":
    main()
