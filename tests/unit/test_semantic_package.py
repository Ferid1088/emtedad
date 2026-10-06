"""Deterministic semantic-package validation tests (no LLM, no DB)."""

from uuid import uuid4

import pytest

from app.localization.semantic_package import (
    PackageClaimItem,
    SemanticPackageOutput,
    SemanticPackageService,
)


class _Export:
    """Duck-typed SemanticLectureMasterExport stand-in."""

    def __init__(self, claims: list[dict]) -> None:
        self.claims = claims


def _claim(claim_id=None, status="SUPPORTED"):
    cid = claim_id or uuid4()
    return {"id": str(cid), "epistemic_status": status, "semantic_proposition": "p"}


def _output(claim_ids) -> SemanticPackageOutput:
    return SemanticPackageOutput(
        thesis="t",
        conclusion="c",
        claim_ledger=[
            PackageClaimItem(
                claim_id=cid,
                semantic_proposition="p",
                epistemic_status="SUPPORTED",
                argument_role="main",
            )
            for cid in claim_ids
        ],
    )


def test_package_rejects_unknown_claim_id() -> None:
    master_claim = _claim()
    output = _output([uuid4()])
    with pytest.raises(ValueError, match="unknown claim"):
        SemanticPackageService._validate_against_master(output, _Export([master_claim]))


def test_package_rejects_changed_epistemic_status() -> None:
    claim_id = uuid4()
    output = _output([claim_id])
    master = _claim(claim_id, status="DISPUTED")
    with pytest.raises(ValueError, match="epistemic status"):
        SemanticPackageService._validate_against_master(output, _Export([master]))


def test_package_rejects_omitted_claims() -> None:
    c1, c2 = uuid4(), uuid4()
    output = _output([c1])
    master = [_claim(c1), _claim(c2)]
    with pytest.raises(ValueError, match="omitted"):
        SemanticPackageService._validate_against_master(output, _Export(master))


def test_package_valid_when_ledger_covers_master() -> None:
    c1 = uuid4()
    output = _output([c1])
    SemanticPackageService._validate_against_master(output, _Export([_claim(c1)]))
    # No master export: nothing to validate against.
    SemanticPackageService._validate_against_master(output, None)
