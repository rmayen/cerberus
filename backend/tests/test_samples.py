import io

import pytest
from fastapi.testclient import TestClient

from tests.conftest import auth_header


@pytest.fixture()
def analyst_headers(client: TestClient, admin: dict[str, str]) -> dict[str, str]:
    headers = auth_header(client, admin["username"], admin["password"])
    client.post(
        "/api/v1/users",
        json={"username": "ana", "password": "analyst-pass-1", "role": "analyst"},
        headers=headers,
    )
    return auth_header(client, "ana", "analyst-pass-1")


def _upload(client: TestClient, headers: dict[str, str], data: bytes, name: str = "sample.bin"):
    return client.post(
        "/api/v1/samples",
        files={"file": (name, io.BytesIO(data), "application/octet-stream")},
        headers=headers,
    )


def test_upload_hashes_and_detects_type(
    client: TestClient, analyst_headers: dict[str, str]
) -> None:
    response = _upload(client, analyst_headers, b"MZ\x90\x00 fake PE header and body")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["duplicate"] is False
    assert len(body["sample"]["sha256"]) == 64
    assert body["sample"]["detected_type"] == "pe"
    assert body["sample"]["status"] == "quarantined"


def test_duplicate_detection(client: TestClient, analyst_headers: dict[str, str]) -> None:
    data = b"\x7fELF duplicate content here"
    first = _upload(client, analyst_headers, data)
    second = _upload(client, analyst_headers, data)
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True
    assert first.json()["sample"]["id"] == second.json()["sample"]["id"]


def test_empty_upload_rejected(client: TestClient, analyst_headers: dict[str, str]) -> None:
    assert _upload(client, analyst_headers, b"").status_code == 400


def test_disallowed_type_rejected(
    client: TestClient, analyst_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "allowed_file_types", "pe")  # only PE allowed now
    response = _upload(client, analyst_headers, b"\x7fELF this is an elf, not pe")
    assert response.status_code == 422


def test_viewer_cannot_upload(client: TestClient, admin: dict[str, str]) -> None:
    admin_headers = auth_header(client, admin["username"], admin["password"])
    client.post(
        "/api/v1/users",
        json={"username": "vwr", "password": "viewer-pass-1", "role": "viewer"},
        headers=admin_headers,
    )
    viewer_headers = auth_header(client, "vwr", "viewer-pass-1")
    assert _upload(client, viewer_headers, b"MZ data").status_code == 403


def test_list_get_and_tags(client: TestClient, analyst_headers: dict[str, str]) -> None:
    sample_id = _upload(client, analyst_headers, b"MZ taggable").json()["sample"]["id"]

    listing = client.get("/api/v1/samples", headers=analyst_headers)
    assert listing.status_code == 200
    assert any(s["id"] == sample_id for s in listing.json())

    tagged = client.put(
        f"/api/v1/samples/{sample_id}/tags",
        json={"tags": ["ransomware", "wannacry", "ransomware"]},
        headers=analyst_headers,
    )
    assert tagged.status_code == 200
    assert tagged.json()["tags"] == ["ransomware", "wannacry"]  # de-duplicated
