from pathlib import Path

from app.content_strategy.validator import PublicationPackageValidator


def test_publication_package_validator_rejects_missing_language_files(
    tmp_path: Path,
) -> None:
    (tmp_path / "master").mkdir()
    findings = PublicationPackageValidator().validate(tmp_path)
    assert "MISSING_FILE:fa/display.txt" in findings
