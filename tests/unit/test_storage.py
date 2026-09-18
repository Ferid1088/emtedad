"""Immutable local object storage behavior and safety tests."""

import hashlib
from io import BytesIO
from pathlib import Path

import pytest

from app.core.exceptions import (
    InvalidStorageKeyError,
    ObjectConflictError,
    ObjectIntegrityError,
    ObjectNotFoundError,
)
from app.storage.local import LocalObjectStore


class FailingStream(BytesIO):
    """Return one chunk and then simulate an interrupted source."""

    def __init__(self, initial_bytes: bytes) -> None:
        super().__init__(initial_bytes)
        self._reads = 0

    def read(self, size: int | None = -1) -> bytes:
        self._reads += 1
        if self._reads > 1:
            raise OSError("simulated stream failure")
        return super().read(2 if size != 0 else size)


def test_put_is_content_addressed_verified_and_idempotent(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "objects")
    payload = b"immutable-source-bytes"
    expected_digest = hashlib.sha256(payload).hexdigest()

    first = store.put_stream(BytesIO(payload), expected_sha256=expected_digest)
    second = store.put_stream(BytesIO(payload), expected_sha256=expected_digest)

    assert first == second
    assert first.sha256 == expected_digest
    assert first.byte_size == len(payload)
    assert (
        store.read_bytes(first.storage_key, expected_sha256=expected_digest) == payload
    )


def test_expected_hash_mismatch_publishes_nothing(tmp_path: Path) -> None:
    root = tmp_path / "objects"
    store = LocalObjectStore(root)

    with pytest.raises(ObjectIntegrityError):
        store.put_stream(BytesIO(b"actual"), expected_sha256="0" * 64)

    assert list(root.glob("sha256/**/*")) == []
    assert list((root / ".tmp").iterdir()) == []


def test_interrupted_write_is_not_exposed(tmp_path: Path) -> None:
    root = tmp_path / "objects"
    store = LocalObjectStore(root)

    with pytest.raises(OSError, match="simulated"):
        store.put_stream(FailingStream(b"partial-data"))

    assert list(root.glob("sha256/**/*")) == []
    assert list((root / ".tmp").iterdir()) == []


def test_existing_corrupt_object_cannot_be_overwritten(tmp_path: Path) -> None:
    root = tmp_path / "objects"
    store = LocalObjectStore(root)
    payload = b"canonical-bytes"
    stored = store.put_stream(BytesIO(payload))
    object_path = root / stored.storage_key
    object_path.write_bytes(b"corrupt")

    with pytest.raises(ObjectConflictError):
        store.put_stream(BytesIO(payload))
    with pytest.raises(ObjectIntegrityError):
        store.read_bytes(stored.storage_key)
    assert object_path.read_bytes() == b"corrupt"


@pytest.mark.parametrize(
    "storage_key",
    [
        "../outside",
        "/absolute/path",
        "sha256/aa/bb/not-a-digest",
        f"sha256/ff/ff/{'0' * 64}",
    ],
)
def test_unsafe_or_inconsistent_storage_keys_are_rejected(
    tmp_path: Path,
    storage_key: str,
) -> None:
    store = LocalObjectStore(tmp_path / "objects")

    with pytest.raises(InvalidStorageKeyError):
        store.read_bytes(storage_key)


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "objects"
    outside = tmp_path / "outside"
    outside.mkdir()
    store = LocalObjectStore(root)
    (root / "sha256").symlink_to(outside, target_is_directory=True)

    with pytest.raises(InvalidStorageKeyError):
        store.put_stream(BytesIO(b"must-stay-contained"))

    assert list(outside.iterdir()) == []


def test_leaf_symlink_escape_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "objects"
    outside_file = tmp_path / "outside-secret"
    outside_file.write_bytes(b"must-not-be-read")
    store = LocalObjectStore(root)
    payload = b"known-content"
    digest = hashlib.sha256(payload).hexdigest()
    storage_key = store.storage_key_for_digest(digest)
    object_path = root / storage_key
    object_path.parent.mkdir(parents=True)
    object_path.symlink_to(outside_file)

    with pytest.raises(InvalidStorageKeyError):
        store.read_bytes(storage_key)
    with pytest.raises(InvalidStorageKeyError):
        store.put_stream(BytesIO(payload))


def test_missing_object_is_explicit(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "objects")
    digest = "0" * 64

    with pytest.raises(ObjectNotFoundError):
        store.read_bytes(store.storage_key_for_digest(digest))


def test_invalid_expected_digest_is_explicit(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "objects")

    with pytest.raises(ObjectIntegrityError):
        store.put_stream(BytesIO(b"content"), expected_sha256="not-a-sha256")
