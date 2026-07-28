"""The composition, end to end, with a model that answers from a fixture instead of the network."""

import csv

import pytest

from agent.guardrails import GuardrailViolated
from agent.orchestrate import screen
from agent.pricing import cost_of
from agent.schemas import Usage
from tests.conftest import ASSETS, FakeClient, extraction

USAGE = Usage(input_tokens=300, output_tokens=200, cache_read_input_tokens=3800, cache_creation_input_tokens=0)


def labels() -> dict[str, str]:
    with (ASSETS / "labels_dev.csv").open(encoding="utf-8") as handle:
        return {row["applicant_id"]: row["expected_decision"] for row in csv.DictReader(handle)}


def run(packet, brain, **overrides):
    client = FakeClient(extraction(**overrides), usage=USAGE)
    return screen(packet, brain, client, run_id="run-0", model="claude-opus-5")


@pytest.mark.parametrize("applicant_id,expected", sorted(labels().items()))
def test_the_labelled_decision_survives_the_orchestrator(packets, brain, applicant_id, expected):
    """003 reached these through a hand-composed pipeline; the endpoint must reach the same ones."""
    case_file, _ = run(packets[applicant_id], brain)

    assert case_file.decision == expected
    assert case_file.applicant_id == applicant_id


def test_the_case_file_carries_the_policy_contract_and_the_state_that_produced_it(packets, brain):
    case_file, _ = run(packets["APP-009"], brain)

    assert case_file.decision == "BLOCK"
    assert case_file.policy_version == "v1"
    assert case_file.brain_hash == brain.brain_hash
    assert case_file.watchlist_hash.startswith("sha256:")
    assert case_file.run_id == "run-0"
    assert [entity.entry_id for entity in case_file.matched_entities] == ["EU-2001"]
    assert case_file.reasons


def test_human_routing_is_a_field_not_an_inference(packets, brain):
    """REVIEW and BLOCK route to a human, so the contract says so rather than leaving a caller to derive it."""
    routed = {
        applicant_id: run(packets[applicant_id], brain)[0].requires_human_review
        for applicant_id in ("APP-001", "APP-011", "APP-009")
    }

    assert routed == {"APP-001": False, "APP-011": True, "APP-009": True}


def test_the_false_clear_count_is_zero_through_the_orchestrator(packets, brain):
    cleared_with_a_hit = [
        applicant_id
        for applicant_id in labels()
        for case_file, trace in [run(packets[applicant_id], brain)]
        if trace.screen.hits and case_file.decision == "CLEAR"
    ]

    assert cleared_with_a_hit == []


def test_the_trace_records_every_step_of_the_run(packets, brain):
    _, trace = run(packets["APP-011"], brain)

    assert trace.run_id == "run-0"
    assert trace.applicant_id == "APP-011"
    assert trace.brain_hash == brain.brain_hash
    assert trace.extract.target_refs == ["business", "ubo[0]"]
    assert trace.screen.searches > 0
    assert [entry.phase for entry in trace.evaluate] == ["initial"]
    assert trace.evaluate[0].fired_rules == [2]
    assert trace.guardrails_passed == ["never_auto_clear"]


def test_the_run_cost_is_arithmetic_over_its_calls(packets, brain):
    """A total that is measured separately from its parts is a second claim that can disagree with the first."""
    _, trace = run(packets["APP-001"], brain)

    assert trace.usage == USAGE
    assert trace.cost_usd == cost_of(USAGE, "claude-opus-5")
    assert trace.cost_usd == trace.extract.cost_usd


def test_a_second_run_of_the_same_packet_produces_the_same_case_file(packets, brain):
    """Durations vary; nothing a caller decides on does."""
    first, _ = run(packets["APP-011"], brain)
    second, _ = run(packets["APP-011"], brain)

    assert first.model_dump_json() == second.model_dump_json()


def test_the_guardrail_runs_before_a_case_file_is_returned(packets, brain):
    """A Brain whose table clears a corroborated sanctions hit must raise, not return the CLEAR to a caller."""
    permissive = brain.model_copy(deep=True)
    for rule in permissive.rules:
        rule.decision = "CLEAR"

    with pytest.raises(GuardrailViolated, match="EU-2001"):
        run(packets["APP-009"], permissive)
