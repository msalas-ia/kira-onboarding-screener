import json

import pytest
from fastapi.testclient import TestClient

from api.brain import BrainUnavailable, active_version
from api.main import app

client = TestClient(app)


def test_health_reports_ready_with_the_active_brain_version():
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["brain_version"] == "v1"


def test_health_is_readiness_not_liveness(tmp_path):
    """An instance that cannot read its policy must not receive traffic."""
    with pytest.raises(BrainUnavailable):
        active_version(tmp_path)


def test_active_version_rejects_a_pointer_to_a_missing_policy(tmp_path):
    (tmp_path / "active_version.json").write_text(json.dumps({"active_version": "v9"}))

    with pytest.raises(BrainUnavailable, match="v9"):
        active_version(tmp_path)
