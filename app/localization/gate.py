"""Owner-approval gate for all localization entry points (§25/§26).

No target-language production may begin until an explicit owner action
approved the *Persian* script draft — the approval is a persisted
``DraftStatus.APPROVED`` transition recorded with the approver's
identity, never inferred from findings or review state.

After approval the exact approved draft is locked by content hash:
``LocalizationSemanticPackage.source_draft_hash`` pins every downstream
run to the approved text. A later change to the Persian script
invalidates the package and marks dependent runs ``STALE_SOURCE``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content_engine.domain import DraftStatus
from app.content_engine.models import ScriptDraft
from app.content_engine.service import GateBlockedError
from app.db.session import Database
from app.localization.models import LocalizationSemanticPackage


async def approved_persian_draft(
    session: AsyncSession, brief_id: UUID
) -> ScriptDraft | None:
    """The owner-approved primary Persian draft for a brief, if any."""

    result = await session.scalar(
        select(ScriptDraft)
        .where(
            ScriptDraft.content_brief_id == brief_id,
            ScriptDraft.language == "fa",
            ScriptDraft.lineage == "primary",
            ScriptDraft.status == DraftStatus.APPROVED,
        )
        .order_by(ScriptDraft.version_number.desc())
        .limit(1)
    )
    return result if isinstance(result, ScriptDraft) else None


async def require_approved_persian_draft(
    database: Database, brief_id: UUID
) -> ScriptDraft:
    """Hard gate: localization requires an owner-approved Persian script."""

    async with database.transaction() as session:
        draft = await approved_persian_draft(session, brief_id)
        if draft is None:
            raise GateBlockedError(
                "LOCALIZATION_GATE — no owner-approved Persian script draft. "
                "Target-language production starts only after the owner "
                "approves the exact Persian script."
            )
        return draft


async def package_is_current(
    session: AsyncSession, package: LocalizationSemanticPackage
) -> bool:
    """The package is stale when the approved Persian text has changed.

    Stale when: the pinned draft is gone or no longer APPROVED, its hash
    no longer matches the locked source hash, or a *newer* Persian
    primary draft has since been approved for the same brief (the
    package must be rebuilt from the new master).
    """

    draft = await session.get(ScriptDraft, package.script_draft_id)
    if draft is None:
        return False
    if draft.content_hash != package.source_draft_hash:
        return False
    # Certification packages pin an explicitly-marked dry_run draft
    # (lineage='dry_run', declared via package provenance). The
    # owner-approval rule governs production packages only — a
    # certification package is current while its pinned text is
    # unchanged. Such packages can only be minted outside the
    # production ``create_for_draft`` gate, which still requires
    # lineage='primary' + APPROVED.
    if draft.lineage == "dry_run" and (package.provenance_json or {}).get(
        "certification"
    ):
        return True
    if draft.status is not DraftStatus.APPROVED:
        return False
    latest = await approved_persian_draft(session, package.content_brief_id)
    return latest is not None and latest.id == package.script_draft_id


# -------------------------------------------------------------------
# Localization eligibility — current policy, never approval history
# -------------------------------------------------------------------


@dataclass(frozen=True)
class LocalizationEligibility:
    """Whether a Persian source draft may seed NEW localization today.

    Owner approval is a historical fact and stays untouched; eligibility
    is a derived, current-policy verdict. A historically approved master
    that no longer meets current duration/encoding/provenance standards
    reports eligible=False and must be re-reviewed or regenerated —
    approval is never silently rewritten.
    """

    eligible: bool
    reasons: list[str] = field(default_factory=list)


_ALLOWED_CONTROLS = {"\n", "\t"}


def evaluate_localization_eligibility(
    draft: ScriptDraft,
    *,
    min_minutes: float,
    max_minutes: float,
    wpm: int,
) -> LocalizationEligibility:
    """Current-policy prerequisites on the pinned Persian source draft.

    Checks only what can be derived deterministically from the draft:
    spoken-length band at the canonical Persian WPM, encoding/control
    integrity, and provenance freshness (content hash consistency is
    enforced by ``package_is_current`` upstream).
    """

    reasons: list[str] = []
    text = draft.text or ""
    words = len(text.split())
    minutes = words / wpm if wpm > 0 else 0.0
    if words < int(min_minutes * wpm):
        reasons.append(
            f"DURATION_TOO_SHORT — {words} words ≈ {minutes:.1f} min at "
            f"{wpm} wpm is below the {min_minutes:g}-min localization floor"
        )
    elif words > int(max_minutes * wpm):
        reasons.append(
            f"DURATION_TOO_LONG — {words} words ≈ {minutes:.1f} min at "
            f"{wpm} wpm is above the {max_minutes:g}-min localization ceiling"
        )
    if "\ufffd" in text:
        reasons.append("ENCODING_CORRUPTION — replacement characters present")
    if any(
        unicodedata.category(ch) == "Cc" and ch not in _ALLOWED_CONTROLS for ch in text
    ):
        reasons.append("CONTROL_CHARS — disallowed control characters present")
    if not draft.content_hash or not re.fullmatch(r"[0-9a-f]{64}", draft.content_hash):
        reasons.append("PROVENANCE — draft content hash missing or malformed")
    return LocalizationEligibility(eligible=not reasons, reasons=reasons)
