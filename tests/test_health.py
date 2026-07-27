"""Readiness means the policy is executable, not merely that a pointer parses."""

import json

import pytest
from fastapi.testclient import TestClient

from agent.brain import BrainUnavailable, load_brain
from agent.constants import POINTER_FILE
from api.config import settings
from api.main import app

client = TestClient(app)


def test_health_reports_ready_with_the_active_brain_version():
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["brain_version"] == "v1"
    assert body["brain_hash"].startswith("sha256:")


def test_health_is_readiness_not_liveness(tmp_path):
    """An instance that cannot read its policy must not receive traffic."""
    with pytest.raises(BrainUnavailable):
        load_brain(tmp_path)


def test_readiness_rejects_a_pointer_to_a_missing_policy(tmp_path):
    (tmp_path / POINTER_FILE).write_text(json.dumps({"active_version": "v9"}))

    with pytest.raises(BrainUnavailable, match="v9"):
        load_brain(tmp_path)


def test_readiness_fails_when_the_rule_table_will_not_execute(monkeypatch, v1_document, make_brain_dir):
    v1_document["rules"][0]["when"] = {"undeclared_fact": True}
    monkeypatch.setattr(settings, "brain_dir", make_brain_dir(v1_document))

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
