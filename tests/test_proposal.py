"""The naive agent: what it is shown, what it is not, and that being overruled is recorded rather than demonstrated."""

import re

import pytest

from agent.llm import ModelUnavailable
from agent.orchestrate import screen
from agent.proposal import render_case
from agent.schemas import Facts
from tests.conftest import FakeClient, clean_facts, extraction, hit, proposal


def run(packet, brain, proposed=None):
    client = FakeClient(extraction(), proposed if proposed is not None else proposal())
    case_file, trace = screen(packet, brain, client, run_id="run-0", model="claude-opus-5")
    return case_file, trace, client


def proposal_call(client) -> str:
    """Everything the second call put in front of the model, system prompt included."""
    call = client.calls[1]
    return "\n".join(block["text"] for block in call["system"]) + "\n" + str(call["messages"])


def test_the_proposal_carries_the_brains_base_heuristic_by_role(packets, brain):
    _, _, client = run(packets["APP-011"], brain)

    assert client.calls[1]["system"] == [{"type": "text", "text": brain.prompt("base_heuristic")}]
    assert "lean toward\nCLEAR" in client.calls[1]["system"][0]["text"]


def test_the_proposal_never_sees_the_policy(packets, brain):
    """A step that can read the rule table is not carrying the naive instruction any more. (D-010)"""
    shown = proposal_call(run(packets["APP-011"], brain)[2])

    assert brain.policy_text not in shown
    for rule in brain.rules:
        assert rule.cite not in shown


@pytest.mark.parametrize("applicant_id", ["APP-009", "APP-008", "APP-011", "APP-001"])
def test_the_proposal_never_sees_a_document(packets, brain, applicant_id):
    """APP-009's injection lives in a document, and this is the only step with a decision field to land in. (D-010)"""
    packet = packets[applicant_id]
    shown = proposal_call(run(packet, brain)[2])
    # The names being screened are shown on purpose — the loop searches them. Any
    # other run of document text would have to have arrived from the free text.
    searched = " | ".join([packet.business.legal_name, *(ubo.name for ubo in packet.ubos)])

    leaked = [
        phrase.strip()
        for document in packet.documents
        for phrase in re.findall(r"[A-Za-z][A-Za-z ,\-]{15,}", document.content)
        if phrase.strip() in shown and phrase.strip() not in searched
    ]

    assert leaked == []


def test_the_injection_reaches_the_proposal_only_as_a_boolean(packets, brain):
    _, trace, client = run(packets["APP-009"], brain)

    assert trace.extract.injection_suspected is True
    assert "documents_contained_instructions: true" in proposal_call(client)
    assert "Ignore all previous instructions" not in proposal_call(client)


def test_the_override_is_recorded_when_the_two_disagree(packets, brain):
    """APP-011: the heuristic clears a 0.966 near-match; Rule 2 does not."""
    case_file, trace, _ = run(packets["APP-011"], brain, proposal(decision="CLEAR", cited_entries=["EU-2001"]))

    assert trace.override.proposed == "CLEAR"
    assert trace.override.final == "REVIEW"
    assert trace.override.overridden is True
    assert trace.override.deciding_rules == [2]
    assert case_file.decision == "REVIEW"


def test_the_override_is_recorded_when_the_two_agree(packets, brain):
    """Agreement is evidence too; a field that only appears on disagreement is a demonstration mode."""
    _, trace, _ = run(packets["APP-009"], brain, proposal(decision="BLOCK", cited_entries=["EU-2001"]))

    assert trace.override.proposed == "BLOCK"
    assert trace.override.overridden is False


def test_nothing_the_proposal_says_reaches_the_case_file(packets, brain):
    """It proposes BLOCK on an applicant the policy clears, and the case file is unmoved."""
    case_file, trace, _ = run(packets["APP-001"], brain, proposal(decision="BLOCK", confidence=1.0))

    assert case_file.decision == "CLEAR"
    assert case_file.confidence != 1.0
    assert all("BLOCK" not in reason for reason in case_file.reasons)
    assert trace.propose.decision == "BLOCK"


def test_a_run_whose_proposal_fails_still_returns_a_case_file(packets, brain):
    """The verdict does not depend on the proposal, so losing one is a degraded run, not a failed one."""
    client = FakeClient(extraction(), ModelUnavailable("overloaded"))

    case_file, trace = screen(packets["APP-011"], brain, client, run_id="run-0", model="claude-opus-5")

    assert case_file.decision == "REVIEW"
    assert trace.propose.outcome == "unavailable"
    assert trace.propose.decision is None
    assert trace.override.proposed is None
    assert trace.override.overridden is False


def test_the_case_shows_the_tools_output_and_not_the_policys_conclusion():
    """`corroborated` is defined by the policy, so showing it would leak the rule table into this step. (D-010)"""
    facts = clean_facts(hits=[hit(entry_id="EU-2001", corroborated=True, corroboration_basis="dob", name_score=0.966)])

    rendered = render_case(facts, [])

    assert "ubo[0] matched EU-2001" in rendered
    assert "name_score=0.966" in rendered
    assert "corroborated" not in rendered
    assert "dob" not in rendered


def test_an_applicant_with_no_hits_is_told_so_rather_than_shown_an_empty_block():
    """Silence and 'nothing matched' read the same to a model, and only one of them is a statement."""
    assert "(no name reached the match threshold)" in render_case(Facts(), [])
