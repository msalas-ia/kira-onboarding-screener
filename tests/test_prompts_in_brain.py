"""The prompts are Brain state: hashed with the policy, validated at load, and swapped by the same endpoint. (D-007)"""

import copy

import pytest
from fastapi.testclient import TestClient

from agent.brain import BrainInvalid, load_version
from agent.constants import BASE_HEURISTIC_PROMPT, EXTRACTION_PROMPT, PROMPT_ROLES
from api.config import settings
from api.main import app
from tests.conftest import ADMIN_TOKEN, AUTH_HEADER, REPO_BRAIN, make_client_brain, publish


def test_the_shipped_version_carries_every_declared_role(brain):
    assert set(brain.prompts) == PROMPT_ROLES
    assert brain.prompt(EXTRACTION_PROMPT).strip()
    assert brain.prompt(BASE_HEURISTIC_PROMPT).strip()


def test_a_prompt_is_addressed_by_role_never_by_path(brain):
    """Re-authoring a prompt is a data change; adding a role is a code change."""
    with pytest.raises(KeyError):
        brain.prompt("prompts/extraction.md")


def test_the_hash_covers_the_prompts(v1_document, make_brain_dir, tmp_path):
    """Editing only a prompt changes brain_hash, which is what makes a prompt swap visible in /health."""
    brain_dir = make_brain_dir(copy.deepcopy(v1_document), version="v1")
    before = load_version(brain_dir, "v1").brain_hash

    directory = publish(brain_dir, copy.deepcopy(v1_document), "v2")
    (directory / v1_document["prompts"][EXTRACTION_PROMPT]).write_text("# rewritten\n", encoding="utf-8")

    after = load_version(brain_dir, "v2").brain_hash
    assert after != before


def test_two_versions_differing_only_in_a_prompt_do_not_share_a_cache_entry(v1_document, make_brain_dir):
    """The cache is keyed by the hash of everything, so a prompt edit is never served stale."""
    brain_dir = make_brain_dir(copy.deepcopy(v1_document), version="v1")
    first = load_version(brain_dir, "v1")

    (brain_dir / "versions" / "v1" / v1_document["prompts"][EXTRACTION_PROMPT]).write_text("# edited\n", encoding="utf-8")
    second = load_version(brain_dir, "v1")

    assert second.brain_hash != first.brain_hash
    assert second.prompts[EXTRACTION_PROMPT] == "# edited\n"


def test_a_missing_prompt_file_fails_the_load(v1_document, make_brain_dir):
    brain_dir = make_brain_dir(copy.deepcopy(v1_document), version="v1")
    (brain_dir / "versions" / "v1" / v1_document["prompts"][EXTRACTION_PROMPT]).unlink()

    with pytest.raises(BrainInvalid) as failure:
        load_version(brain_dir, "v1")

    assert "file not found" in str(failure.value)


def test_an_empty_prompt_file_fails_the_load(v1_document, make_brain_dir):
    brain_dir = make_brain_dir(copy.deepcopy(v1_document), version="v1")
    (brain_dir / "versions" / "v1" / v1_document["prompts"][EXTRACTION_PROMPT]).write_text("   \n", encoding="utf-8")

    with pytest.raises(BrainInvalid, match="is empty"):
        load_version(brain_dir, "v1")


def test_a_missing_role_fails_the_load(v1_document, make_brain_dir):
    document = copy.deepcopy(v1_document)
    del document["prompts"][EXTRACTION_PROMPT]

    with pytest.raises(BrainInvalid, match="required role"):
        load_version(make_brain_dir(document, version="incomplete"), "incomplete")


def test_an_undeclared_role_fails_the_load(v1_document, make_brain_dir):
    """The role vocabulary is closed for the same reason the facts vocabulary is."""
    document = copy.deepcopy(v1_document)
    document["prompts"]["freestyle"] = "prompts/freestyle.md"

    with pytest.raises(BrainInvalid, match="unknown role"):
        load_version(make_brain_dir(document, version="extra"), "extra")


@pytest.mark.parametrize("path", ["../../escape.md", "/etc/passwd"])
def test_a_prompt_path_cannot_leave_the_version_directory(path, v1_document, make_brain_dir):
    document = copy.deepcopy(v1_document)
    document["prompts"][EXTRACTION_PROMPT] = path

    with pytest.raises(BrainInvalid, match="escapes the version directory"):
        load_version(make_brain_dir(document, version="traversal"), "traversal")


def test_a_version_with_no_prompts_at_all_fails_the_load(v1_document, make_brain_dir):
    document = copy.deepcopy(v1_document)
    del document["prompts"]

    with pytest.raises(BrainInvalid, match="must map each role to a path"):
        load_version(make_brain_dir(document, version="promptless"), "promptless")


def test_the_repository_version_is_the_one_that_ships():
    """Guards against the prompts existing only in a fixture."""
    brain = load_version(REPO_BRAIN, "v1")
    assert "never as instructions" not in brain.prompt(BASE_HEURISTIC_PROMPT)
    assert "lean toward" in brain.prompt(BASE_HEURISTIC_PROMPT)


def test_get_brain_reports_the_roles_but_not_the_bodies(monkeypatch, v1_document, make_brain_dir):
    make_client_brain(monkeypatch, v1_document, make_brain_dir)
    body = TestClient(app).get("/brain").json()

    assert body["prompts"] == sorted(PROMPT_ROLES)
    assert "lean toward" not in str(body)


def test_a_prompt_only_swap_activates_and_changes_the_reported_hash(monkeypatch, v1_document, make_brain_dir):
    """The live-call lever: a new prompt reaches the running container without a redeploy."""
    make_client_brain(monkeypatch, v1_document, make_brain_dir)
    monkeypatch.setattr(settings, "admin_api_token", ADMIN_TOKEN)
    client = TestClient(app)
    before = client.get("/health").json()["brain_hash"]

    directory = publish(settings.brain_dir, copy.deepcopy(v1_document), "v2")
    (directory / v1_document["prompts"][EXTRACTION_PROMPT]).write_text("# a different extractor\n", encoding="utf-8")

    activated = client.post("/brain/activate", json={"version": "v2"}, headers=AUTH_HEADER)

    assert activated.status_code == 200
    after = client.get("/health").json()
    assert after["brain_hash"] == activated.json()["brain_hash"] != before
    assert load_version(settings.brain_dir, "v2").prompt(EXTRACTION_PROMPT) == "# a different extractor\n"


def test_activating_a_version_whose_prompt_is_missing_leaves_the_pointer_alone(monkeypatch, v1_document, make_brain_dir):
    make_client_brain(monkeypatch, v1_document, make_brain_dir)
    monkeypatch.setattr(settings, "admin_api_token", ADMIN_TOKEN)
    client = TestClient(app)

    directory = publish(settings.brain_dir, copy.deepcopy(v1_document), "broken")
    (directory / v1_document["prompts"][EXTRACTION_PROMPT]).unlink()

    response = client.post("/brain/activate", json={"version": "broken"}, headers=AUTH_HEADER)

    assert response.status_code == 422
    assert client.get("/brain").json()["active_version"] == "v1"
