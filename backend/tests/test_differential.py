import io
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from app.analysis.differential import compare
from tests.conftest import auth_header


@dataclass
class Ev:
    category: str
    action: str
    target: str


def test_compare_flags_disappearing_category_as_high_confidence() -> None:
    baseline = [Ev("dns", "query", "c2.test"), Ev("file", "write", "a")]
    variant = [Ev("file", "write", "a")]  # network gone
    result = compare("internet", True, False, baseline, variant)
    assert result is not None
    assert result.confidence == "high"  # a whole category disappeared
    assert {"category": "dns", "action": "query", "target": "c2.test"} in result.removed


def test_compare_returns_none_when_identical() -> None:
    events = [Ev("file", "write", "a")]
    assert compare("hostname", "a", "b", events, events) is None


def test_compare_avoids_certainty_language() -> None:
    result = compare("internet", True, False, [Ev("dns", "query", "x")], [])
    assert result is not None
    assert "observed behavioral dependency" in result.summary.lower()


@pytest.fixture()
def analyst_headers(client: TestClient, admin: dict[str, str]) -> dict[str, str]:
    headers = auth_header(client, admin["username"], admin["password"])
    client.post(
        "/api/v1/users",
        json={"username": "ana", "password": "analyst-pass-1", "role": "analyst"},
        headers=headers,
    )
    return auth_header(client, "ana", "analyst-pass-1")


def test_differential_detects_internet_dependency(
    client: TestClient, analyst_headers: dict[str, str]
) -> None:
    sample_id = client.post(
        "/api/v1/samples",
        files={"file": ("s.bin", io.BytesIO(b"MZ diff"), "application/octet-stream")},
        headers=analyst_headers,
    ).json()["sample"]["id"]

    response = client.post(
        "/api/v1/differential",
        json={
            "sample_id": sample_id,
            "baseline_conditions": {"internet": True},
            "variations": [{"internet": False}, {"existing_mutex": True}],
        },
        headers=analyst_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "completed"

    by_axis = {f["axis"]: f for f in body["findings"]}
    # Disabling the internet should remove the network activity, high confidence.
    assert "internet" in by_axis
    assert by_axis["internet"]["confidence"] == "high"
    assert any(e["category"] in ("dns", "network") for e in by_axis["internet"]["removed"])
    # The existing-mutex condition changes behaviour too (early exit).
    assert "existing_mutex" in by_axis


def test_differential_unknown_sample_is_404(
    client: TestClient, analyst_headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/differential",
        json={"sample_id": 9999, "variations": [{"internet": False}]},
        headers=analyst_headers,
    )
    assert response.status_code == 404


def test_viewer_cannot_run_differential(client: TestClient, admin: dict[str, str]) -> None:
    admin_headers = auth_header(client, admin["username"], admin["password"])
    client.post(
        "/api/v1/users",
        json={"username": "vwr", "password": "viewer-pass-1", "role": "viewer"},
        headers=admin_headers,
    )
    viewer = auth_header(client, "vwr", "viewer-pass-1")
    response = client.post(
        "/api/v1/differential",
        json={"sample_id": 1, "variations": [{"internet": False}]},
        headers=viewer,
    )
    assert response.status_code == 403
