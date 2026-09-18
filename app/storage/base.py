"""Immutable-object storage protocol and result types."""

from dataclasses import dataclass
from typing import BinaryIO, Protocol


@dataclass(frozen=True, slots=True)
class StoredObject:
    """Identity and location of verified immutable bytes."""

    sha256: str
    storage_key: str
    byte_size: int


class ObjectStore(Protocol):
    """Port for content-addressed immutable object storage."""

    def put_stream(
        self,
        source: BinaryIO,
        *,
        expected_sha256: str | None = None,
    ) -> StoredObject:
        """Persist and verify a binary stream idempotently."""

    def read_bytes(
        self,
        storage_key: str,
        *,
        expected_sha256: str | None = None,
    ) -> bytes:
        """Read bytes after verifying their content identity."""
