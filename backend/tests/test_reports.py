import io

import pytest
from fastapi.testclient import TestClient

from app.reports.builder import ReportData, build_html, build_pdf
from app.reports.containment import Recommendation, recommend
from tests.conftest import auth_header


def _sample_data() -> ReportData:
    return ReportData(
        sample_sha256="a" * 64,
        filename="sample.bin",
        job_id=1,
        status="completed",
        conditions={"internet": True},
        timeline=[(0, "dns", "query", "c2.test")],
        findings=[("network", "Outbound network communication", "medium", "c2-like traffic")],
        iocs=[("domain", "c2.test"), ("file_hash", "a" * 64)],
        attack=[("T1071", "Application Layer Protocol", "Command and Control", "c2")],
        containment=[Recommendation("Isolate host", "limits impact")],
        notes=None,
    )


def test_build_html_contains_all_sections() -> None:
    html = build_html(_sample_data())
    sections = ["Executive Summary", "Behavior Findings", "MITRE ATT", "Indicators", "Containment"]
    for section in sections:
        assert section in html
    assert "do not assert certainty" in html


def test_build_pdf_returns_real_pdf_bytes() -> None:
    data = build_pdf(_sample_data())
    assert isinstance(data, bytes)
    assert data.startswith(b"%PDF")  # a genuine PDF document


def test_recommendations_scale_with_evidence() -> None:
    from dataclasses import dataclass

    @dataclass
    class F:
        category: str

    @dataclass
    class IocStub:
        value: str
        type: str

    recs = recommend([F("persistence")], [IocStub("evil.test", "domain")])
    actions = " ".join(r.action.lower() for r in recs)
    assert "isolate" in actions
    assert "block" in actions  # network IOC present
    assert "persistence" in actions  # persistence finding present


@pytest.fixture()
def analyst_headers(client: TestClient, admin: dict[str, str]) -> dict[str, str]:
    headers = auth_header(client, admin["username"], admin["password"])
    client.post(
        "/api/v1/users",
        json={"username": "ana", "password": "analyst-pass-1", "role": "analyst"},
        headers=headers,
    )
    return auth_header(client, "ana", "analyst-pass-1")


def test_report_endpoint_returns_html_and_pdf(
    client: TestClient, analyst_headers: dict[str, str]
) -> None:
    sample_id = client.post(
        "/api/v1/samples",
        files={"file": ("s.bin", io.BytesIO(b"MZ report"), "application/octet-stream")},
        headers=analyst_headers,
    ).json()["sample"]["id"]
    job_id = client.post(
        "/api/v1/jobs",
        json={"sample_id": sample_id, "conditions": {"internet": True}},
        headers=analyst_headers,
    ).json()["id"]

    html_resp = client.get(f"/api/v1/jobs/{job_id}/report?format=html", headers=analyst_headers)
    assert html_resp.status_code == 200
    assert "Cerberus Analysis Report" in html_resp.text

    pdf_resp = client.get(f"/api/v1/jobs/{job_id}/report?format=pdf", headers=analyst_headers)
    assert pdf_resp.status_code == 200
    assert pdf_resp.headers["content-type"] == "application/pdf"
    assert pdf_resp.content.startswith(b"%PDF")
