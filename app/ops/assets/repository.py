"""Persistence operations for immutable asset metadata."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ops.assets.models import ObjectAsset, utc_now
from app.storage.base import StoredObject


class AssetRepository:
    """Read and register immutable assets without owning transactions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_sha256(self, sha256: str) -> ObjectAsset | None:
        result = await self._session.execute(
            select(ObjectAsset).where(ObjectAsset.sha256 == sha256)
        )
        return result.scalar_one_or_none()

    async def get_or_create(
        self,
        stored: StoredObject,
        *,
        media_type: str,
        original_filename: str,
    ) -> tuple[ObjectAsset, bool]:
        existing = await self.get_by_sha256(stored.sha256)
        if existing is not None:
            return existing, False
        asset = ObjectAsset(
            sha256=stored.sha256,
            byte_size=stored.byte_size,
            media_type=media_type,
            storage_backend="local",
            storage_key=stored.storage_key,
            original_filename=original_filename,
            verified_at=utc_now(),
        )
        self._session.add(asset)
        await self._session.flush()
        return asset, True
