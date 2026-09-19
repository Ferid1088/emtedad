"""Deterministic identities for extraction configurations and passage sets."""

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Protocol


class PassageFingerprint(Protocol):
    """Minimum passage fields included in an extraction output identity."""

    @property
    def sequence(self) -> int: ...

    @property
    def page_number(self) -> int: ...

    @property
    def printed_page_label(self) -> str | None: ...

    @property
    def heading_path(self) -> Sequence[str]: ...

    @property
    def paragraph_index(self) -> int: ...

    @property
    def content_hash(self) -> str: ...

    @property
    def normalized_text(self) -> str: ...


def configuration_hash(configuration: Mapping[str, object]) -> str:
    """Hash extraction configuration using a canonical JSON representation."""

    encoded = json.dumps(
        configuration,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def passage_set_hash(passages: Iterable[PassageFingerprint]) -> str:
    """Hash ordered passage locations and content without losing boundaries."""

    digest = hashlib.sha256()
    for passage in passages:
        fingerprint = json.dumps(
            [
                passage.sequence,
                passage.page_number,
                passage.printed_page_label,
                list(passage.heading_path),
                passage.paragraph_index,
                passage.content_hash,
                passage.normalized_text,
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        digest.update(fingerprint.encode())
        digest.update(b"\n")
    return digest.hexdigest()
