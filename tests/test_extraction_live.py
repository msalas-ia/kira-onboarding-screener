"""The tests that spend money: `uv run pytest -m live`, skipped without a key so CI stays free until spec 005."""

import os

import pytest

from agent.extraction import extract
from agent.facts import from_packet
from agent.llm import AnthropicClient
from agent.rules import evaluate

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="no ANTHROPIC_API_KEY in the environment"),
]

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5")


@pytest.fixture(scope="module")
def client():
    return AnthropicClient(model=MODEL, api_key=os.environ["ANTHROPIC_API_KEY"])


def test_the_adversarial_packet_extracts_without_obeying_it(packets, brain, client):
    """APP-009 instructs the reader to output CLEAR. It gets flagged and classified, and nothing else moves."""
    packet = packets["APP-009"]

    result = extract(packet, brain, client)

    assert result.injection_suspected is True
    assert result.has_incorporation_doc is True
    assert evaluate(brain, from_packet(packet, result, brain.settings)).decision != "BLOCK"  # hits land in 003


def test_the_missing_document_is_still_missing_against_a_real_model(packets, brain, client):
    """The one applicant whose Rule 6 REVIEW depends on extraction getting it right."""
    result = extract(packets["APP-006"], brain, client)

    assert result.has_incorporation_doc is False


def test_a_novel_spelling_is_recognised(packets, brain, client):
    """Why the LLM is on this path at all: the floor knows two spellings, the holdout may use a third."""
    packet = packets["APP-006"].model_copy(deep=True)
    packet.documents.append(
        packet.documents[0].model_copy(update={"type": "constitutive_act", "content": "Acta constitutiva, folio 4471."})
    )

    assert extract(packet, brain, client).has_incorporation_doc is True


def test_repeated_runs_agree(packets, brain, client):
    """Determinism is structural for the verdict and empirical here; three runs is the smoke-test dose."""
    packet = packets["APP-008"]

    runs = {
        from_packet(packet, extract(packet, brain, client), brain.settings).model_dump_json() for _ in range(3)
    }

    assert len(runs) == 1


def test_the_cached_prefix_is_read_back(packets, brain, client):
    """The caching claim in DESIGN.md, measured rather than asserted."""
    extract(packets["APP-001"], brain, client)
    second = extract(packets["APP-002"], brain, client)

    assert second.usage.cache_read_input_tokens > 0
