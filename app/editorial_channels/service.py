"""Editorial channel service: channels, versioned strategies, resource links."""

from datetime import UTC, datetime
from typing import TypedDict
from uuid import UUID

from sqlalchemy import func, select, update

from app.core.exceptions import ApplicationError, ResourceNotFoundError
from app.db.session import Database
from app.editorial_channels.domain import (
    EDITORIAL_CHANNEL_SEEDS,
    ChannelResourceRole,
    ChannelSeed,
    EditorialChannelStatus,
    StrategyStatus,
)
from app.editorial_channels.models import (
    ChannelStrategyVersion,
    EditorialChannel,
    EditorialChannelResource,
)
from app.editorial_channels.schemas import ChannelSummary
from app.knowledge.models import Source


class ChannelNotFoundError(ResourceNotFoundError):
    code = "editorial_channel_not_found"
    public_message = "The editorial channel does not exist."


class StrategyNotFoundError(ResourceNotFoundError):
    code = "channel_strategy_not_found"
    public_message = "The channel strategy version does not exist."


class StrategyStateError(ApplicationError):
    code = "channel_strategy_state_error"
    public_message = "The strategy version cannot change state as requested."
    status_code = 409


class StrategyValidationError(ApplicationError):
    code = "channel_strategy_invalid"
    public_message = "The strategy draft is not valid."
    status_code = 422

    def __init__(self, errors: list[str]) -> None:
        super().__init__(self.public_message)
        self.errors = errors


# Editable payload keys on ChannelStrategyVersion — kept in one place so the
# draft editor and the compare view cannot drift apart.
STRATEGY_POLICY_KEYS: tuple[str, ...] = (
    "audience_json",
    "audience_problems_json",
    "domains_json",
    "preferred_angles_json",
    "forbidden_angles_json",
    "source_policy_json",
    "evidence_policy_json",
    "topic_scoring_policy_json",
    "narrative_policy_json",
    "style_policy_json",
    "hook_policy_json",
    "ending_policy_json",
    "agent_profile_json",
)

EDITORIAL_LANGUAGES: frozenset[str] = frozenset({"fa", "en", "ar"})

SCORING_WEIGHT_KEYS: tuple[str, ...] = (
    "channel_fit",
    "knowledge_coverage",
    "novelty",
    "curiosity",
    "emotional_relevance",
    "practical_value",
)


def validate_strategy(strategy: ChannelStrategyVersion) -> list[str]:
    """Owner-readable validation errors; an invalid draft cannot activate."""

    errors: list[str] = []
    if not strategy.core_question.strip():
        errors.append("Core question is empty.")
    if strategy.editorial_language not in EDITORIAL_LANGUAGES:
        errors.append(
            f"Editorial language '{strategy.editorial_language}' is not supported."
        )
    domains = strategy.domains_json.get("domains")
    if not isinstance(domains, list) or not [d for d in domains if str(d).strip()]:
        errors.append("Domains must contain at least one entry.")
    if not isinstance(strategy.evidence_policy_json, dict):
        errors.append("Evidence policy is not a valid policy object.")
    weights = strategy.topic_scoring_policy_json.get("weights", {})
    if not isinstance(weights, dict) or not weights:
        errors.append("Topic scoring policy has no weights.")
    else:
        for key, value in weights.items():
            if not isinstance(value, int | float) or isinstance(value, bool):
                errors.append(f"Scoring weight '{key}' is not a number.")
            elif value < 0:
                errors.append(f"Scoring weight '{key}' is negative.")
        numeric = [
            float(value)
            for value in weights.values()
            if isinstance(value, int | float) and not isinstance(value, bool)
        ]
        if numeric and sum(numeric) <= 0:
            errors.append("Scoring weights must not all be zero.")
    return errors


def _section_items(payload: dict[str, object]) -> dict[str, str]:
    """Flatten one policy JSON into readable label → value pairs."""

    items: dict[str, str] = {}
    for key, value in sorted(payload.items()):
        label = key.replace("_", " ")
        if isinstance(value, list):
            items[label] = ", ".join(str(item) for item in value) or "—"
        elif isinstance(value, dict):
            for sub_key, sub_value in sorted(value.items()):
                items[f"{label} · {sub_key.replace('_', ' ')}"] = str(sub_value)
        else:
            items[label] = str(value)
    return items


class StrategySectionDiff(TypedDict):
    section: str
    changed: bool
    before: dict[str, str]
    after: dict[str, str]
    added: list[str]
    removed: list[str]
    modified: list[str]


def compare_strategies(
    before: ChannelStrategyVersion | None,
    after: ChannelStrategyVersion,
) -> list[StrategySectionDiff]:
    """Readable field-level diff between two strategy versions."""

    sections: list[tuple[str, dict[str, object], dict[str, object]]] = [
        (
            "Core question",
            {"core_question": before.core_question if before else ""},
            {"core_question": after.core_question},
        ),
        (
            "Editorial language",
            {"editorial_language": before.editorial_language if before else ""},
            {"editorial_language": after.editorial_language},
        ),
    ]
    for key in STRATEGY_POLICY_KEYS:
        label = key.removesuffix("_json").replace("_", " ").title()
        sections.append(
            (
                label,
                getattr(before, key) if before is not None else {},
                getattr(after, key),
            )
        )
    diffs: list[StrategySectionDiff] = []
    for label, old_payload, new_payload in sections:
        old_items = _section_items(old_payload)
        new_items = _section_items(new_payload)
        added = sorted(set(new_items) - set(old_items))
        removed = sorted(set(old_items) - set(new_items))
        modified = sorted(
            key
            for key in set(old_items) & set(new_items)
            if old_items[key] != new_items[key]
        )
        diffs.append(
            StrategySectionDiff(
                section=label,
                changed=bool(added or removed or modified),
                before=old_items,
                after=new_items,
                added=added,
                removed=removed,
                modified=modified,
            )
        )
    return diffs


def _strategy_payload(seed: ChannelSeed) -> dict[str, dict[str, object]]:
    """Build the initial policy payload for one channel seed."""

    evidence_policy: dict[str, object] = {
        "require_source_provenance": True,
        "require_counterevidence_search": True,
    }
    agent_profile: dict[str, object] = {"special_roles": list(seed.special_roles)}
    override_targets: dict[str, dict[str, object]] = {
        "review_checks": agent_profile,
        "epistemic_statuses": evidence_policy,
        "content_rules": evidence_policy,
        "always_consider": evidence_policy,
    }
    for key, value in seed.policy_overrides.items():
        override_targets.get(key, agent_profile)[key] = value
    return {
        "audience_json": {"description": seed.description},
        "audience_problems_json": {"problems": list(seed.domains)},
        "domains_json": {"domains": list(seed.domains)},
        "preferred_angles_json": {"angles": list(seed.preferred_angles)},
        "forbidden_angles_json": {"angles": list(seed.forbidden_angles)},
        "source_policy_json": {
            "channel_assigned_resources_only": True,
            "shared_knowledge_base": True,
        },
        "evidence_policy_json": evidence_policy,
        "topic_scoring_policy_json": {
            "weights": {
                "channel_fit": 1.0,
                "knowledge_coverage": 1.0,
                "novelty": 1.0,
                "curiosity": 1.0,
                "emotional_relevance": 1.0,
                "practical_value": 1.0,
            }
        },
        "narrative_policy_json": {},
        "style_policy_json": {},
        "hook_policy_json": {},
        "ending_policy_json": {},
        "agent_profile_json": agent_profile,
    }


class EditorialChannelService:
    """Manage editorial verticals, their strategies, and resource assignment."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def seed_channels(self) -> list[EditorialChannel]:
        """Idempotently create the five channels and their first strategies."""

        async with self.database.transaction() as session:
            channels: list[EditorialChannel] = []
            for seed in EDITORIAL_CHANNEL_SEEDS:
                channel = await session.scalar(
                    select(EditorialChannel).where(EditorialChannel.slug == seed.slug)
                )
                if channel is None:
                    channel = EditorialChannel(
                        slug=seed.slug,
                        name=seed.name,
                        description=seed.description,
                        status=EditorialChannelStatus.ACTIVE,
                    )
                    session.add(channel)
                    await session.flush()
                channels.append(channel)

                has_strategy = await session.scalar(
                    select(func.count(ChannelStrategyVersion.id)).where(
                        ChannelStrategyVersion.editorial_channel_id == channel.id
                    )
                )
                if not has_strategy:
                    session.add(
                        ChannelStrategyVersion(
                            editorial_channel_id=channel.id,
                            version_number=1,
                            core_question=seed.core_question,
                            status=StrategyStatus.ACTIVE,
                            activated_at=datetime.now(UTC),
                            **_strategy_payload(seed),
                        )
                    )
            await session.flush()
            return channels

    async def list_channels(self) -> list[EditorialChannel]:
        async with self.database.transaction() as session:
            return list(
                await session.scalars(
                    select(EditorialChannel).order_by(EditorialChannel.name)
                )
            )

    async def get_channel(self, slug: str) -> EditorialChannel:
        async with self.database.transaction() as session:
            channel = await session.scalar(
                select(EditorialChannel).where(EditorialChannel.slug == slug)
            )
            if channel is None:
                raise ChannelNotFoundError(slug)
            return channel

    async def get_active_strategy(self, channel_id: UUID) -> ChannelStrategyVersion:
        async with self.database.transaction() as session:
            strategy = await session.scalar(
                select(ChannelStrategyVersion).where(
                    ChannelStrategyVersion.editorial_channel_id == channel_id,
                    ChannelStrategyVersion.status == StrategyStatus.ACTIVE,
                )
            )
            if strategy is None:
                raise StrategyNotFoundError(str(channel_id))
            return strategy

    async def list_strategies(self, channel_id: UUID) -> list[ChannelStrategyVersion]:
        async with self.database.transaction() as session:
            return list(
                await session.scalars(
                    select(ChannelStrategyVersion)
                    .where(ChannelStrategyVersion.editorial_channel_id == channel_id)
                    .order_by(ChannelStrategyVersion.version_number.desc())
                )
            )

    async def create_strategy_draft(
        self,
        channel_id: UUID,
        *,
        core_question: str | None = None,
        policies: dict[str, dict[str, object]] | None = None,
    ) -> ChannelStrategyVersion:
        """Create the next DRAFT strategy version for a channel.

        With no explicit payload the draft clones the currently active
        strategy so owners edit a version rather than the live record.
        """

        async with self.database.transaction() as session:
            channel = await session.get(EditorialChannel, channel_id)
            if channel is None:
                raise ChannelNotFoundError(str(channel_id))
            latest = await session.scalar(
                select(ChannelStrategyVersion)
                .where(ChannelStrategyVersion.editorial_channel_id == channel_id)
                .order_by(ChannelStrategyVersion.version_number.desc())
                .limit(1)
            )
            payload: dict[str, object] = {}
            if latest is not None:
                for key in (
                    "audience_json",
                    "audience_problems_json",
                    "domains_json",
                    "preferred_angles_json",
                    "forbidden_angles_json",
                    "source_policy_json",
                    "evidence_policy_json",
                    "topic_scoring_policy_json",
                    "narrative_policy_json",
                    "style_policy_json",
                    "hook_policy_json",
                    "ending_policy_json",
                    "agent_profile_json",
                ):
                    payload[key] = getattr(latest, key)
            if policies:
                payload.update(policies)
            draft = ChannelStrategyVersion(
                editorial_channel_id=channel_id,
                version_number=(latest.version_number if latest else 0) + 1,
                core_question=core_question
                or (latest.core_question if latest else channel.description),
                status=StrategyStatus.DRAFT,
                **payload,
            )
            session.add(draft)
            await session.flush()
            return draft

    async def update_strategy_draft(
        self,
        strategy_id: UUID,
        *,
        core_question: str,
        editorial_language: str,
        policies: dict[str, dict[str, object]],
    ) -> ChannelStrategyVersion:
        """Replace the editable payload of a DRAFT version after validation.

        ACTIVE and ARCHIVED versions are immutable — the owner always edits a
        draft clone, never the live strategy.
        """

        async with self.database.transaction() as session:
            strategy = await session.get(ChannelStrategyVersion, strategy_id)
            if strategy is None:
                raise StrategyNotFoundError(str(strategy_id))
            if strategy.status is not StrategyStatus.DRAFT:
                raise StrategyStateError(str(strategy_id))
            unknown = set(policies) - set(STRATEGY_POLICY_KEYS)
            if unknown:
                raise StrategyValidationError(
                    [f"Unknown policy section: {key}" for key in sorted(unknown)]
                )
            strategy.core_question = core_question
            strategy.editorial_language = editorial_language
            for key, value in policies.items():
                # Merge into the stored policy so keys the form does not cover
                # (e.g. channel-specific overrides) survive an edit.
                merged = dict(getattr(strategy, key) or {})
                merged.update(value)
                setattr(strategy, key, merged)
            errors = validate_strategy(strategy)
            if errors:
                raise StrategyValidationError(errors)
            await session.flush()
            return strategy

    async def activate_strategy(self, strategy_id: UUID) -> ChannelStrategyVersion:
        """Activate one draft; archives the previously ACTIVE version."""

        async with self.database.transaction() as session:
            strategy = await session.get(ChannelStrategyVersion, strategy_id)
            if strategy is None:
                raise StrategyNotFoundError(str(strategy_id))
            if strategy.status is StrategyStatus.ACTIVE:
                return strategy
            if strategy.status is not StrategyStatus.DRAFT:
                raise StrategyStateError(str(strategy_id))
            errors = validate_strategy(strategy)
            if errors:
                raise StrategyValidationError(errors)
            await session.execute(
                update(ChannelStrategyVersion)
                .where(
                    ChannelStrategyVersion.editorial_channel_id
                    == strategy.editorial_channel_id,
                    ChannelStrategyVersion.status == StrategyStatus.ACTIVE,
                    ChannelStrategyVersion.id != strategy.id,
                )
                .values(status=StrategyStatus.ARCHIVED)
            )
            strategy.status = StrategyStatus.ACTIVE
            strategy.activated_at = datetime.now(UTC)
            await session.flush()
            return strategy

    async def assign_resource(
        self,
        channel_id: UUID,
        source_id: UUID,
        *,
        relevance: float = 1.0,
        role: ChannelResourceRole = ChannelResourceRole.SUPPORTING,
    ) -> EditorialChannelResource:
        """Link a shared source to a channel without duplicating the Source."""

        async with self.database.transaction() as session:
            if await session.get(EditorialChannel, channel_id) is None:
                raise ChannelNotFoundError(str(channel_id))
            if await session.get(Source, source_id) is None:
                raise ResourceNotFoundError(str(source_id))
            link = await session.get(EditorialChannelResource, (channel_id, source_id))
            if link is None:
                link = EditorialChannelResource(
                    editorial_channel_id=channel_id,
                    source_id=source_id,
                    relevance=relevance,
                    role=role,
                )
                session.add(link)
            else:
                link.relevance = relevance
                link.role = role
            await session.flush()
            return link

    async def unassign_resource(self, channel_id: UUID, source_id: UUID) -> bool:
        """Remove the channel link; the Source row itself is untouched."""

        async with self.database.transaction() as session:
            link = await session.get(EditorialChannelResource, (channel_id, source_id))
            if link is None:
                return False
            await session.delete(link)
            await session.flush()
            return True

    async def list_channel_resources(
        self, channel_id: UUID
    ) -> list[EditorialChannelResource]:
        async with self.database.transaction() as session:
            return list(
                await session.scalars(
                    select(EditorialChannelResource)
                    .where(EditorialChannelResource.editorial_channel_id == channel_id)
                    .order_by(EditorialChannelResource.assigned_at.desc())
                )
            )

    async def channel_summaries(self) -> list[ChannelSummary]:
        """Real per-channel counts for the Studio switcher cards."""

        from app.briefs.models import ContentBrief
        from app.content_engine.domain import DraftStatus
        from app.content_engine.models import ScriptDraft
        from app.topics.models import ScriptSignature, TopicCandidate

        async with self.database.transaction() as session:
            channels = list(
                await session.scalars(
                    select(EditorialChannel).order_by(EditorialChannel.name)
                )
            )
            rows = (
                await session.execute(
                    select(
                        EditorialChannelResource.editorial_channel_id,
                        func.count(),
                    ).group_by(EditorialChannelResource.editorial_channel_id)
                )
            ).all()
            resource_counts: dict[UUID, int] = {row[0]: int(row[1]) for row in rows}
            topic_rows = (
                await session.execute(
                    select(
                        TopicCandidate.editorial_channel_id,
                        func.count(),
                    ).group_by(TopicCandidate.editorial_channel_id)
                )
            ).all()
            topic_counts: dict[UUID, int] = {row[0]: int(row[1]) for row in topic_rows}
            brief_rows = (
                await session.execute(
                    select(
                        ContentBrief.editorial_channel_id,
                        func.count(),
                    ).group_by(ContentBrief.editorial_channel_id)
                )
            ).all()
            brief_counts: dict[UUID, int] = {row[0]: int(row[1]) for row in brief_rows}
            approved_rows = (
                await session.execute(
                    select(
                        ContentBrief.editorial_channel_id,
                        func.count(func.distinct(ScriptDraft.content_brief_id)),
                    )
                    .join(
                        ScriptDraft,
                        ScriptDraft.content_brief_id == ContentBrief.id,
                    )
                    .where(ScriptDraft.status == DraftStatus.APPROVED)
                    .group_by(ContentBrief.editorial_channel_id)
                )
            ).all()
            approved_counts: dict[UUID, int] = {
                row[0]: int(row[1]) for row in approved_rows
            }
            published_rows = (
                await session.execute(
                    select(
                        ScriptSignature.editorial_channel_id,
                        func.count(),
                    ).group_by(ScriptSignature.editorial_channel_id)
                )
            ).all()
            published_counts: dict[UUID, int] = {
                row[0]: int(row[1]) for row in published_rows
            }
            return [
                ChannelSummary(
                    id=channel.id,
                    slug=channel.slug,
                    name=channel.name,
                    description=channel.description,
                    status=channel.status,
                    resource_count=int(resource_counts.get(channel.id, 0)),
                    topic_count=topic_counts.get(channel.id, 0),
                    active_production_count=brief_counts.get(channel.id, 0)
                    - approved_counts.get(channel.id, 0),
                    published_count=published_counts.get(channel.id, 0),
                )
                for channel in channels
            ]
