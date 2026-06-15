"""Local filesystem storage backend.

Stores files at {audio_storage_path}/{key}.
"""

import os
import aiofiles

from app.config import settings
from app.storage.base import StorageBackend


class LocalStorage(StorageBackend):
    """Local filesystem storage for audio files."""

    def __init__(self, base_path: str | None = None):
        self.base_path = base_path or settings.audio_storage_path
        os.makedirs(self.base_path, exist_ok=True)

    def _path(self, key: str) -> str:
        return os.path.join(self.base_path, key)

    async def save(self, key: str, data: bytes) -> None:
        path = self._path(key)
        async with aiofiles.open(path, "wb") as f:
            await f.write(data)

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        async with aiofiles.open(path, "rb") as f:
            return await f.read()

    async def delete(self, key: str) -> None:
        path = self._path(key)
        if os.path.exists(path):
            os.remove(path)
