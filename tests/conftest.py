"""Shared fixtures: Brain volumes built on disk, and factories for synthetic facts."""

import copy
import json
from pathlib import Path

import pytest
import yaml

from agent.brain import load_version
from agent.constants import POINTER_FILE, POLICY_FILE, RULES_FILE
from agent.llm import Completion, ToolCall
from agent.schemas import (
    Applicant,
    Brain,
    DocumentClassification,
    Extraction,
    ExtractedName,
    Facts,
    Hit,
    Proposal,
    ShellSignalFinding,
    Usage,
)

REPO_BRAIN = Path("company_brain")
ASSETS = Path("assets/data")
ADMIN_TOKEN = "test-admin-token"
AUTH_HEADER = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
PLACEHOLDER_POLICY = "# policy prose\n"
PLACEHOLDER_PROMPT = "# prompt\n"


@pytest.fixture
def brain() -> Brain:
    """The real v1 policy: tests assert against the Brain that ships, not a mock."""
    return load_version(REPO_BRAIN, "v1")


@pytest.fixture
def v1_document() -> dict:
    """The shipped rule table, as a mutable document to derive variants from."""
    return yaml.safe_load((REPO_BRAIN / "versions" / "v1" / RULES_FILE).read_text(encoding="utf-8"))


def publish(brain_dir: Path, document: dict, version: str) -> Path:
    """Write a version onto a Brain volume the way an operator would: prose, table and every declared prompt."""
    document = copy.deepcopy(document) | {"policy_version": version}
    directory = brain_dir / "versions" / version
    directory.mkdir(parents=True, exist_ok=True)
    (directory / POLICY_FILE).write_text(PLACEHOLDER_POLICY, encoding="utf-8")
    (directory / RULES_FILE).write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    for relative in (document.get("prompts") or {}).values():
        if not isinstance(relative, str):
            continue
        path = (directory / relative).resolve()
        if Path(relative).is_absolute() or not path.is_relative_to(directory.resolve()):
            continue  # the traversal cases: an operator only ever writes inside the version
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(PLACEHOLDER_PROMPT, encoding="utf-8")
    return directory


def make_client_brain(monkeypatch, v1_document, make_brain_dir, version: str = "v1") -> Path:
    """Point the running app at a throwaway copy of a Brain volume."""
    from api.config import settings

    brain_dir = make_brain_dir(copy.deepcopy(v1_document), version=version)
    monkeypatch.setattr(settings, "brain_dir", brain_dir)
    return brain_dir


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


@pytest.fixture(scope="session")
def packets() -> dict[str, Applicant]:
    """The delivered packets, by applicant id. Tests assert against real data, not fixtures of it."""
    raw = json.loads((ASSETS / "applicants.json").read_text(encoding="utf-8"))
    return {entry["applicant_id"]: Applicant.model_validate(entry) for entry in raw}


class FakeClient:
    """A model that answers with whatever the test primed it with, and records how it was called."""

    def __init__(self, *responses, usage: Usage | None = None) -> None:
        self.responses = list(responses)
        self.usage = usage or Usage()
        self.calls: list[dict] = []

    def parse(self, *, system, messages, output_format, tools=None):
        self.calls.append({"system": system, "messages": messages, "output_format": output_format, "tools": tools})
        if not self.responses:
            raise AssertionError("the fake client was called more times than it was primed for")
        answer = self.responses.pop(0)
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, Completion):
            return answer
        return Completion(parsed=answer, usage=self.usage)


def searching(*names: str, usage: Usage | None = None) -> Completion:
    """A model turn that asks for searches instead of answering."""
    calls = tuple(
        ToolCall(id=f"call-{index}", name="watchlist_search", arguments={"name": name})
        for index, name in enumerate(names)
    )
    return Completion(parsed=None, usage=usage or Usage(), tool_calls=calls, content=[{"type": "tool_use"}])


def fumbling(*arguments: dict) -> Completion:
    """A model turn whose tool call is malformed — a missing name, an empty one, the wrong type."""
    calls = tuple(
        ToolCall(id=f"call-{index}", name="watchlist_search", arguments=argument)
        for index, argument in enumerate(arguments)
    )
    return Completion(parsed=None, usage=Usage(), tool_calls=calls, content=[{"type": "tool_use"}])


def extraction(**overrides) -> Extraction:
    """A model response that reports nothing, unless the test says otherwise."""
    defaults = dict(documents=[], shell_signals=[], names=[], contains_instructions=False)
    return Extraction(**{**defaults, **overrides})


def proposal(**overrides) -> Proposal:
    """The naive agent's answer, defaulting to the CLEAR its heuristic leans toward."""
    defaults = dict(decision="CLEAR", confidence=0.8, cited_entries=[])
    return Proposal(**{**defaults, **overrides})


def classify(index: int, kind: str, span: str) -> DocumentClassification:
    return DocumentClassification(index=index, kind=kind, evidence_span=span)


def signal(name: str, index: int, span: str) -> ShellSignalFinding:
    return ShellSignalFinding(signal=name, source_index=index, evidence_span=span)


def named(name: str, index: int, span: str, kind: str = "person") -> ExtractedName:
    return ExtractedName(name=name, kind=kind, source_index=index, evidence_span=span)


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
