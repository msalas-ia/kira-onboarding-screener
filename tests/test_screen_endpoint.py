"""POST /screen: the surface, its auth, and the states in which it refuses to answer."""

import json

import pytest
from fastapi.testclient import TestClient

from agent.schemas import CaseFile
from api.config import settings
from api.main import app
from api.screen_routes import model_client
from tests.conftest import FakeClient, extraction, proposal

SCREEN_TOKEN = "test-screen-token"
HEADER = {"Authorization": f"Bearer {SCREEN_TOKEN}"}


@pytest.fixture
def client(monkeypatch, tmp_path, packets):
    """The app with a primed model and a throwaway trace volume; the Brain is the real v1."""
    monkeypatch.setattr(settings, "screen_api_token", SCREEN_TOKEN)
    monkeypatch.setattr(settings, "traces_dir", tmp_path)
    monkeypatch.setattr("api.screen_routes.model_client", lambda: FakeClient(extraction(), proposal()))
    return TestClient(app)


def body(packets, applicant_id: str) -> dict:
    return json.loads(packets[applicant_id].model_dump_json())


def test_a_packet_is_screened_and_the_case_file_comes_back(client, packets):
    response = client.post("/screen", json=body(packets, "APP-011"), headers=HEADER)

    assert response.status_code == 200
    case_file = CaseFile.model_validate(response.json()["case_file"])
    assert case_file.decision == "REVIEW"
    assert case_file.applicant_id == "APP-011"
    assert case_file.requires_human_review is True


def test_the_response_carries_the_run_trace(client, packets):
    trace = client.post("/screen", json=body(packets, "APP-009"), headers=HEADER).json()["trace"]

    assert trace["applicant_id"] == "APP-009"
    assert trace["run_id"] == trace["run_id"]
    assert [hit["entry_id"] for hit in trace["screen"]["hits"]] == ["EU-2001"]


def test_the_persisted_trace_is_byte_identical_to_the_returned_one(client, packets, tmp_path):
    response = client.post("/screen", json=body(packets, "APP-003"), headers=HEADER)

    written = (tmp_path / "runs.jsonl").read_text(encoding="utf-8").strip()
    returned = response.text.split('"trace":', 1)[1].rsplit("}", 1)[0]

    assert returned == written


def test_screening_without_a_token_is_refused(client, packets):
    assert client.post("/screen", json=body(packets, "APP-001")).status_code == 401
    assert client.post("/screen", json=body(packets, "APP-001"), headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_an_unconfigured_screen_token_closes_the_endpoint(client, packets, monkeypatch):
    """The same posture as the admin surface: no token configured means no traffic, not open traffic."""
    monkeypatch.setattr(settings, "screen_api_token", "")

    assert client.post("/screen", json=body(packets, "APP-001"), headers=HEADER).status_code == 503


def test_the_screen_token_does_not_open_the_admin_surface(client):
    """Screening an applicant and swapping the policy under it are different privileges."""
    response = client.post("/brain/activate", json={"version": "v1"}, headers=HEADER)

    assert response.status_code in (401, 503)


def test_a_malformed_packet_is_rejected_before_a_model_is_called(client):
    assert client.post("/screen", json={"business": {}}, headers=HEADER).status_code == 422


def test_an_instance_that_cannot_load_its_policy_refuses_to_screen(client, packets, monkeypatch, tmp_path):
    """The same condition /health reports 503 for: an instance that cannot execute its policy does not guess."""
    monkeypatch.setattr(settings, "brain_dir", tmp_path / "empty")

    assert client.post("/screen", json=body(packets, "APP-001"), headers=HEADER).status_code == 503


def test_the_model_client_is_built_once_and_never_at_import(monkeypatch):
    """Constructing it must not need a key, or /health would depend on one."""
    model_client.cache_clear()
    monkeypatch.setattr(settings, "anthropic_api_key", "")

    assert model_client() is model_client()
    model_client.cache_clear()
