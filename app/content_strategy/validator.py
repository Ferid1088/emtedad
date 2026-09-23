"""Deterministic publication package export validation."""

import json
from pathlib import Path


class PublicationPackageValidator:
    """Validate the standalone directory contract without database access."""

    def validate(self, root: Path) -> list[str]:
        findings: list[str] = []
        required = [
            "master/metadata.json",
            "citations.json",
            "sources.json",
            "provenance.json",
            "manifest.json",
        ]
        for language in ("fa", "de", "en", "ar"):
            required.extend(
                [
                    f"{language}/display.txt",
                    f"{language}/voice.txt",
                    f"{language}/metadata.json",
                ]
            )
        for relative in required:
            if not (root / relative).is_file():
                findings.append(f"MISSING_FILE:{relative}")
        forbidden_suffixes = {".mp3", ".wav", ".mp4", ".mov", ".png", ".jpg"}
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in forbidden_suffixes:
                findings.append(f"MEDIA_PRESENT:{path.name}")
        for language in ("fa", "de", "en", "ar"):
            metadata_path = root / language / "metadata.json"
            if metadata_path.is_file():
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                if metadata.get("status") != "READY_FOR_VOICE":
                    findings.append(f"LANGUAGE_NOT_READY:{language}")
            for name in ("display.txt", "voice.txt"):
                path = root / language / name
                if path.is_file() and not path.read_text(encoding="utf-8").strip():
                    findings.append(f"EMPTY_TEXT:{language}/{name}")
        return findings
