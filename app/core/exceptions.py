"""Explicit application exceptions safe for transport translation."""


class ApplicationError(Exception):
    """Base exception with a stable public error contract."""

    code = "application_error"
    public_message = "The request could not be completed."
    status_code = 500


class StorageError(ApplicationError):
    """Base immutable-object storage error."""

    code = "storage_error"
    public_message = "The stored object operation failed."


class InvalidStorageKeyError(StorageError):
    """Raised when a storage key is malformed or unsafe."""

    code = "invalid_storage_key"
    public_message = "The storage key is invalid."
    status_code = 400


class ObjectNotFoundError(StorageError):
    """Raised when an immutable object does not exist."""

    code = "object_not_found"
    public_message = "The stored object was not found."
    status_code = 404


class ObjectIntegrityError(StorageError):
    """Raised when object bytes do not match their expected identity."""

    code = "object_integrity_error"
    public_message = "The stored object failed integrity verification."
    status_code = 409


class ObjectConflictError(StorageError):
    """Raised when immutable storage already contains conflicting bytes."""

    code = "object_conflict"
    public_message = "The immutable storage location contains conflicting data."
    status_code = 409


class ResourceNotFoundError(ApplicationError):
    """Raised when a requested domain identity does not exist."""

    code = "resource_not_found"
    public_message = "The requested resource was not found."
    status_code = 404
