from pathlib import Path

from app.config import settings
from app.storage import SampleStorage


def test_store_and_load_round_trip(tmp_path: Path) -> None:
    store = SampleStorage(str(tmp_path), settings.storage_key)
    data = b"MZ\x90\x00 malicious-looking bytes"
    sha = "a" * 64

    path = store.store(sha, data)
    assert Path(path).exists()
    assert store.load(sha) == data


def test_stored_blob_is_encrypted_not_plaintext(tmp_path: Path) -> None:
    store = SampleStorage(str(tmp_path), settings.storage_key)
    data = b"secret marker string that must not appear on disk"
    store.store("b" * 64, data)

    on_disk = (tmp_path / f"{'b' * 64}.enc").read_bytes()
    assert b"secret marker string" not in on_disk  # ciphertext, not plaintext


def test_blob_permissions_are_restrictive(tmp_path: Path) -> None:
    store = SampleStorage(str(tmp_path), settings.storage_key)
    path = Path(store.store("c" * 64, b"data"))
    assert (path.stat().st_mode & 0o777) == 0o600
