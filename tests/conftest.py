"""Shared fixtures: Brain volumes built on disk, and factories for synthetic facts."""

import copy
import json
from pathlib import Path

import pytest
import yaml

from agent.brain import load_version
from agent.constants import POINTER_FILE, POLICY_FILE, RULES_FILE
from agent.schemas import Brain, Facts, Hit

REPO_BRAIN = Path("company_brain")
ADMIN_TOKEN = "test-admin-token"
AUTH_HEADER = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
PLACEHOLDER_POLICY = "# policy prose\n"


@pytest.fixture
def brain() -> Brain:
    """The real v1 policy: tests assert against the Brain that ships, not a mock."""
    return load_version(REPO_BRAIN, "v1")


@pytest.fixture
def v1_document() -> dict:
    """The shipped rule table, as a mutable document to derive variants from."""
    return yaml.safe_load((REPO_BRAIN / "versions" / "v1" / RULES_FILE).read_text(encoding="utf-8"))


def publish(brain_dir: Path, document: dict, version: str) -> Path:
    """Write a version onto a Brain volume the way an operator would."""
    document = copy.deepcopy(document) | {"policy_version": version}
    directory = brain_dir / "versions" / version
    directory.mkdir(parents=True, exist_ok=True)
    (directory / POLICY_FILE).write_text(PLACEHOLDER_POLICY, encoding="utf-8")
    (directory / RULES_FILE).write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return directory


@pytest.fixture
def make_brain_dir(tmp_path):
    """Build a Brain volume from a rules document and point it at that version."""

    def _make(document: dict, version: str | None = None) -> Path:
        version = version or document["policy_version"]
        publish(tmp_path, document, version)
        (tmp_path / POINTER_FILE).write_text(json.dumps({"active_version": version}), encoding="utf-8")
        return tmp_path

    return _make


@pytest.fixture
def without_rule(v1_document, make_brain_dir):
    """A Brain identical to v1 except that one rule was never written."""

    def _without(rule_id: int, version: str = "ablated") -> Path:
        document = copy.deepcopy(v1_document)
        document["rules"] = [rule for rule in document["rules"] if rule["id"] != rule_id]
        return make_brain_dir(document, version=version)

    return _without


def clean_facts(**overrides) -> Facts:
    """An applicant that trips nothing: documents present, benign MCC, long established."""
    defaults = dict(
        mcc="5734",
        has_incorporation_doc=True,
        has_ubo_list=True,
        formation_age_days=1000,
        shell_signals=[],
        hits=[],
    )
    return Facts(**{**defaults, **overrides})


def hit(**overrides) -> Hit:
    """A corroborated sanctions hit against the first UBO, unless overridden."""
    defaults = dict(
        entry_id="OFAC-1001",
        hit_type="sanctions",
        subject="ubo",
        subject_ref="ubo[0]",
        name_score=1.0,
        corroborated=True,
        corroboration_basis="dob",
    )
    return Hit(**{**defaults, **overrides})
