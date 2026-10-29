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


def test_analyst_can_create_and_list_cases(
    client: TestClient, analyst_headers: dict[str, str]
) -> None:
    created = client.post(
        "/api/v1/cases",
        json={"name": "Operation Cerberus", "description": "test case"},
        headers=analyst_headers,
    )
    assert created.status_code == 201, created.text

    listing = client.get("/api/v1/cases", headers=analyst_headers)
    assert any(c["name"] == "Operation Cerberus" for c in listing.json())


def test_duplicate_case_name_conflicts(
    client: TestClient, analyst_headers: dict[str, str]
) -> None:
    payload = {"name": "dupe-case", "description": None}
    assert client.post("/api/v1/cases", json=payload, headers=analyst_headers).status_code == 201
    assert client.post("/api/v1/cases", json=payload, headers=analyst_headers).status_code == 409


def test_sample_can_be_associated_with_case(
    client: TestClient, analyst_headers: dict[str, str]
) -> None:
    case_id = client.post(
        "/api/v1/cases", json={"name": "case-with-sample"}, headers=analyst_headers
    ).json()["id"]

    response = client.post(
        "/api/v1/samples",
        files={"file": ("s.bin", io.BytesIO(b"MZ in a case"), "application/octet-stream")},
        data={"case_id": str(case_id)},
        headers=analyst_headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["sample"]["case_id"] == case_id


def test_upload_to_unknown_case_rejected(
    client: TestClient, analyst_headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/samples",
        files={"file": ("s.bin", io.BytesIO(b"MZ orphan"), "application/octet-stream")},
        data={"case_id": "9999"},
        headers=analyst_headers,
    )
    assert response.status_code == 404
