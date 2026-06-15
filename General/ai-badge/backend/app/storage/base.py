"""Abstract storage interface for audio files."""

from abc import ABC, abstractmethod


class StorageBackend(ABC):
    """Abstract base for file storage backends."""

    @abstractmethod
    async def save(self, key: str, data: bytes) -> None:
        """Save binary data with the given key."""
        ...

    @abstractmethod
    async def get(self, key: str) -> bytes:
        """Retrieve binary data by key."""
        ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete data by key."""
        ...
