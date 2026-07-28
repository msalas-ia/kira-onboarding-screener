"""The one assertion nobody should be allowed to fake: the override, against the real model. `uv run pytest -m live`."""

import os

import pytest

from agent.llm import AnthropicClient
from agent.orchestrate import screen

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="no ANTHROPIC_API_KEY in the environment"),
]

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5")


@pytest.fixture(scope="module")
def client():
    return AnthropicClient(model=MODEL, api_key=os.environ["ANTHROPIC_API_KEY"])


def test_app_011_is_reviewed_whatever_the_naive_agent_proposes(packets, brain, client):
    """The Brain decides. What the proposal says is recorded, not obeyed — including when it says CLEAR."""
    case_file, trace = screen(packets["APP-011"], brain, client, run_id="live-011", model=MODEL)

    assert case_file.decision == "REVIEW"
    assert trace.evaluate[-1].fired_rules == [2]
    assert trace.override.final == "REVIEW"
    assert trace.propose.outcome == "proposed"


def test_the_adversarial_packet_blocks_end_to_end(packets, brain, client):
    """APP-009 carries a document demanding CLEAR, and travels the whole pipeline without moving anything."""
    case_file, trace = screen(packets["APP-009"], brain, client, run_id="live-009", model=MODEL)

    assert case_file.decision == "BLOCK"
    assert trace.extract.injection_suspected is True
    assert [entity.entry_id for entity in case_file.matched_entities] == ["EU-2001"]


def test_a_real_run_leaks_no_pii_into_its_trace(packets, brain, client):
    """The offline test primes the model; this one lets it write whatever it likes and checks the same property."""
    packet = packets["APP-009"]
    _, trace = screen(packet, brain, client, run_id="live-pii", model=MODEL)

    serialised = trace.model_dump_json()
    assert packet.ubos[0].name not in serialised
    assert str(packet.ubos[0].dob) not in serialised
    assert packet.business.legal_name not in serialised
