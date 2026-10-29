import os
from pathlib import Path

from cryptography.fernet import Fernet

from app.config import settings


class SampleStorage:
    """Encrypts sample bytes at rest. Blobs are named by SHA-256, stored with
    restrictive permissions, and never written under the user-supplied filename."""

    def __init__(self, directory: str, key: str) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._fernet = Fernet(key.encode())

    def path_for(self, sha256: str) -> Path:
        return self._dir / f"{sha256}.enc"

    def store(self, sha256: str, data: bytes) -> str:
        path = self.path_for(sha256)
        token = self._fernet.encrypt(data)
        # Write with 0600 so only the service account can read the ciphertext.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(token)
        return str(path)

    def load(self, sha256: str) -> bytes:
        return self._fernet.decrypt(self.path_for(sha256).read_bytes())


storage = SampleStorage(settings.sample_storage_dir, settings.storage_key)
