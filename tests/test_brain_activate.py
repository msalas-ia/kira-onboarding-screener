"""Hot-swap and rollback through the API the demo uses, on a running process with no restart between decisions."""

import copy
import json
import os

import pytest
from fastapi.testclient import TestClient

from agent.brain import load_brain
from agent.rules import evaluate
from api.config import settings
from api.main import app
from tests.conftest import ADMIN_TOKEN, AUTH_HEADER, clean_facts, publish


@pytest.fixture
def client(monkeypatch, v1_document, make_brain_dir):
    """A client whose Brain volume is a throwaway copy of v1."""
    monkeypatch.setattr(settings, "brain_dir", make_brain_dir(copy.deepcopy(v1_document), version="v1"))
    monkeypatch.setattr(settings, "admin_api_token", ADMIN_TOKEN)
    return TestClient(app)


def test_a_swap_changes_the_decision_without_a_restart(client, v1_document):
    """v2 extends the high-risk MCC set to APP-001's code: the applicant does not change, the policy does."""
    facts = clean_facts(mcc="5734")
    assert evaluate(load_brain(settings.brain_dir), facts).decision == "CLEAR"

    document = copy.deepcopy(v1_document)
    for rule in document["rules"]:
        if rule["id"] == 5:
            rule["when"]["mcc"]["in"].append("5734")
    publish(settings.brain_dir, document, "v2")

    response = client.post("/brain/activate", json={"version": "v2"}, headers=AUTH_HEADER)

    assert response.status_code == 200
    assert response.json()["previous"] == "v1"
    assert evaluate(load_brain(settings.brain_dir), facts).decision == "REVIEW"


def test_rollback_is_the_same_call_with_the_version_the_api_reported(client, v1_document):
    """No operator has to remember what was live before the swap."""
    publish(settings.brain_dir, v1_document, "v2")
    client.post("/brain/activate", json={"version": "v2"}, headers=AUTH_HEADER)

    previous = client.get("/brain").json()["previous_version"]
    assert previous == "v1"

    response = client.post("/brain/activate", json={"version": previous}, headers=AUTH_HEADER)

    assert response.status_code == 200
    assert client.get("/brain").json()["active_version"] == "v1"


def test_health_reports_the_new_hash_after_a_swap(client, v1_document):
    """The hash is what makes "same applicant, same Brain state" checkable."""
    before = client.get("/health").json()["brain_hash"]

    document = copy.deepcopy(v1_document)
    document["settings"]["min_name_score"] = 0.8
    publish(settings.brain_dir, document, "v2")
    client.post("/brain/activate", json={"version": "v2"}, headers=AUTH_HEADER)

    after = client.get("/health").json()
    assert after["brain_version"] == "v2"
    assert after["brain_hash"] != before


def test_an_unexecutable_policy_cannot_be_activated(client, v1_document):
    """Validation happens before the write, so the pointer never moves onto a broken version."""
    broken = copy.deepcopy(v1_document)
    broken["rules"].append(
        {"id": 99, "when": {"gut_feeling": "bad"}, "decision": "BLOCK", "confidence": 0.5, "cite": "x"}
    )
    publish(settings.brain_dir, broken, "v2")

    response = client.post("/brain/activate", json={"version": "v2"}, headers=AUTH_HEADER)

    assert response.status_code == 422
    assert "undeclared fact" in json.dumps(response.json()["detail"])
    assert client.get("/brain").json()["active_version"] == "v1"


def test_activating_a_version_that_does_not_exist_is_a_404(client):
    """A typo in a version name leaves the live policy alone."""
    response = client.post("/brain/activate", json={"version": "v9"}, headers=AUTH_HEADER)

    assert response.status_code == 404
    assert client.get("/brain").json()["active_version"] == "v1"


def test_the_swap_endpoint_requires_a_bearer_token(client):
    """The only mutating endpoint in the service is not reachable anonymously."""
    assert client.post("/brain/activate", json={"version": "v1"}).status_code == 401

    wrong = client.post("/brain/activate", json={"version": "v1"}, headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401


def test_an_unconfigured_token_closes_the_endpoint_rather_than_opening_it(client, monkeypatch):
    """A missing feature is safer than an open mutation."""
    monkeypatch.setattr(settings, "admin_api_token", "")

    response = client.post("/brain/activate", json={"version": "v1"}, headers=AUTH_HEADER)

    assert response.status_code == 503


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores the permission bits this test relies on")
def test_a_volume_that_cannot_be_written_says_so(client):
    """A read-only or wrongly-owned mount is an operational fault, and must not surface as a mute 500."""
    settings.brain_dir.chmod(0o555)
    try:
        response = client.post("/brain/activate", json={"version": "v1"}, headers=AUTH_HEADER)
    finally:
        settings.brain_dir.chmod(0o755)

    assert response.status_code == 503
    assert "cannot record the swap" in response.json()["detail"]


def test_versions_lists_the_broken_ones_with_their_errors(client, v1_document):
    """An operator can see a candidate version is unusable before trying to activate it."""
    broken = copy.deepcopy(v1_document)
    broken["rules"][0]["confidence"] = 3.0
    publish(settings.brain_dir, broken, "v2")

    versions = {entry["version"]: entry for entry in client.get("/brain/versions").json()["versions"]}

    assert versions["v1"]["valid"] is True
    assert versions["v2"]["valid"] is False
    assert versions["v2"]["errors"]
