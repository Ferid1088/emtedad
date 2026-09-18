"""Safe content-addressed local immutable-object storage."""

import hashlib
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import BinaryIO

from app.core.exceptions import (
    InvalidStorageKeyError,
    ObjectConflictError,
    ObjectIntegrityError,
    ObjectNotFoundError,
)
from app.storage.base import StoredObject

_BUFFER_SIZE = 1024 * 1024
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_STORAGE_KEY_PATTERN = re.compile(
    r"^sha256/(?P<first>[0-9a-f]{2})/(?P<second>[0-9a-f]{2})/"
    r"(?P<digest>[0-9a-f]{64})$"
)


class LocalObjectStore:
    """Store immutable objects by SHA-256 without exposing caller paths."""

    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self._root = root.resolve(strict=True)
        self._temporary_root = self._root / ".tmp"
        self._temporary_root.mkdir(mode=0o700, exist_ok=True)
        self._assert_contained(self._temporary_root.resolve(strict=True))

    def put_stream(
        self,
        source: BinaryIO,
        *,
        expected_sha256: str | None = None,
    ) -> StoredObject:
        """Stream to a temporary file, verify, then atomically publish once."""

        expected_digest = self._validate_digest(expected_sha256)
        descriptor, temporary_name = tempfile.mkstemp(dir=self._temporary_root)
        temporary_path = Path(temporary_name)
        digest = hashlib.sha256()
        byte_size = 0

        try:
            with os.fdopen(descriptor, "wb") as temporary_file:
                while chunk := source.read(_BUFFER_SIZE):
                    digest.update(chunk)
                    byte_size += len(chunk)
                    temporary_file.write(chunk)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())

            actual_digest = digest.hexdigest()
            if expected_digest is not None and actual_digest != expected_digest:
                raise ObjectIntegrityError

            storage_key = self.storage_key_for_digest(actual_digest)
            destination = self._path_for_key(storage_key)
            destination.parent.mkdir(parents=True, exist_ok=True)
            self._assert_contained(destination.parent.resolve(strict=True))

            try:
                os.link(temporary_path, destination)
                self._sync_directory(destination.parent)
            except FileExistsError:
                self._verify_existing(destination, actual_digest, byte_size)

            return StoredObject(
                sha256=actual_digest,
                storage_key=storage_key,
                byte_size=byte_size,
            )
        finally:
            temporary_path.unlink(missing_ok=True)

    def read_bytes(
        self,
        storage_key: str,
        *,
        expected_sha256: str | None = None,
    ) -> bytes:
        """Read an object only when its key and bytes agree."""

        destination = self._path_for_key(storage_key)
        data = self._read_file_safely(destination)
        actual_digest = hashlib.sha256(data).hexdigest()
        key_digest = self._digest_from_key(storage_key)
        expected_digest = self._validate_digest(expected_sha256)

        if actual_digest != key_digest or (
            expected_digest is not None and actual_digest != expected_digest
        ):
            raise ObjectIntegrityError
        return data

    @staticmethod
    def storage_key_for_digest(digest: str) -> str:
        """Return the canonical shard path for one validated SHA-256 digest."""

        if not _SHA256_PATTERN.fullmatch(digest):
            raise InvalidStorageKeyError
        return f"sha256/{digest[:2]}/{digest[2:4]}/{digest}"

    @staticmethod
    def _validate_digest(digest: str | None) -> str | None:
        if digest is not None and not _SHA256_PATTERN.fullmatch(digest):
            raise ObjectIntegrityError
        return digest

    @staticmethod
    def _digest_from_key(storage_key: str) -> str:
        match = _STORAGE_KEY_PATTERN.fullmatch(storage_key)
        if match is None:
            raise InvalidStorageKeyError
        digest = match.group("digest")
        if digest[:2] != match.group("first") or digest[2:4] != match.group("second"):
            raise InvalidStorageKeyError
        return digest

    def _path_for_key(self, storage_key: str) -> Path:
        self._digest_from_key(storage_key)
        candidate = self._root.joinpath(*storage_key.split("/"))
        self._assert_contained(candidate.parent.resolve(strict=False))
        if candidate.is_symlink():
            raise InvalidStorageKeyError
        return candidate

    def _assert_contained(self, candidate: Path) -> None:
        try:
            candidate.relative_to(self._root)
        except ValueError as exc:
            raise InvalidStorageKeyError from exc

    @staticmethod
    def _verify_existing(path: Path, digest: str, byte_size: int) -> None:
        existing_data = LocalObjectStore._read_file_safely(path)
        if (
            len(existing_data) != byte_size
            or hashlib.sha256(existing_data).hexdigest() != digest
        ):
            raise ObjectConflictError

    @staticmethod
    def _read_file_safely(path: Path) -> bytes:
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags)
        except FileNotFoundError as exc:
            raise ObjectNotFoundError from exc
        except OSError as exc:
            raise InvalidStorageKeyError from exc

        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise InvalidStorageKeyError
            with os.fdopen(descriptor, "rb") as stored_file:
                descriptor = -1
                return stored_file.read()
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    @staticmethod
    def _sync_directory(directory: Path) -> None:
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
