"""SQLAlchemy model for immutable object metadata."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, CheckConstraint, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PostgresSchema


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)


class ObjectAsset(Base):
    """Identity and storage location for immutable bytes."""

    __tablename__ = "object_assets"
    __table_args__ = (
        CheckConstraint("checksum_algorithm = 'sha256'", name="sha256_algorithm"),
        CheckConstraint("byte_size >= 0", name="nonnegative_byte_size"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="valid_sha256"),
        UniqueConstraint("checksum_algorithm", "sha256"),
        {"schema": PostgresSchema.OPS.value},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    checksum_algorithm: Mapped[str] = mapped_column(String(16), default="sha256")
    sha256: Mapped[str] = mapped_column(String(64))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    media_type: Mapped[str] = mapped_column(String(255))
    storage_backend: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(512), unique=True)
    original_filename: Mapped[str] = mapped_column(String(512))
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
