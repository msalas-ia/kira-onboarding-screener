"""The bounded loop: what it can do to a verdict, what it cannot, and what happens when it runs out of budget."""

import time

import pytest

from agent.constants import SEVERITY
from agent.orchestrate import screen
from agent.proposal import WATCHLIST_TOOL_SPEC, propose
from agent.schemas import Facts
from tests.conftest import FakeClient, extraction, fumbling, proposal, searching

# The reordered PEP name D-009 measured at 1.0, and a sanctions entity, both real.
FOUND = "Olena Kravchenko"
MISSED = "Nobody Whatsoever"


def run(packet, brain, *responses, max_steps=12, timeout=None):
    client = FakeClient(extraction(), *responses)
    case_file, trace = screen(
        packet, brain, client, run_id="run-0", model="claude-opus-5", max_steps=max_steps, timeout_seconds=timeout
    )
    return case_file, trace, client


def test_the_tool_is_offered_on_every_proposal_turn(packets, brain):
    _, _, client = run(packets["APP-001"], brain, proposal())

    assert client.calls[1]["tools"] == [WATCHLIST_TOOL_SPEC]
    assert client.calls[0]["tools"] is None  # extraction is not a tool-using step


def test_a_model_initiated_search_can_add_a_hit_to_a_clean_applicant(packets, brain):
    """The gap D-009 admits: a spelling no permutation of the given tokens can reach."""
    case_file, trace, _ = run(packets["APP-001"], brain, searching(FOUND), proposal(decision="CLEAR"))

    assert trace.evaluate[0].decision == "CLEAR"
    assert [entry.phase for entry in trace.evaluate] == ["initial", "final"]
    assert case_file.decision == "REVIEW"
    assert [hit.entry_id for hit in trace.screen.hits] == ["PEP-3004"]
    assert trace.screen.hits[0].subject_ref == "proposed"


def test_a_proposed_name_can_never_corroborate(packets, brain):
    """It is a spelling the model tried, not an identity the packet declared, so there is nothing to compare. (D-011)"""
    _, trace, _ = run(packets["APP-001"], brain, searching(FOUND), proposal())

    assert trace.screen.hits[0].corroborated is False
    assert trace.screen.hits[0].corroboration_basis == "none"
    assert trace.screen.hits[0].subject == "proposed"


@pytest.mark.parametrize("applicant_id", ["APP-001", "APP-011", "APP-009", "APP-005"])
def test_the_loop_can_only_raise_severity(packets, brain, applicant_id):
    """Monotonicity, tested against a proposer that searches a real hit rather than argued from the code."""
    _, trace, _ = run(packets[applicant_id], brain, searching(FOUND, "Viktor Petrov"), proposal())

    initial, final = trace.evaluate[0], trace.evaluate[-1]
    assert SEVERITY[final.decision] >= SEVERITY[initial.decision]


def test_a_search_that_finds_nothing_changes_nothing(packets, brain):
    case_file, trace, _ = run(packets["APP-001"], brain, searching(MISSED), proposal())

    assert case_file.decision == "CLEAR"
    assert [entry.phase for entry in trace.evaluate] == ["initial"]
    assert trace.propose.searches[0].entries == []


def test_the_searched_string_is_never_recorded_only_its_shape(packets, brain):
    _, trace, _ = run(packets["APP-001"], brain, searching(FOUND), proposal())

    record = trace.propose.searches[0]
    assert record.ordinal == 0
    assert record.tokens == 2
    assert record.accepted is True
    assert [entry.entry_id for entry in record.entries] == ["PEP-3004"]
    assert FOUND not in trace.model_dump_json()


@pytest.mark.parametrize(
    "arguments", [{}, {"name": ""}, {"name": "   "}, {"name": 42}, {"query": "Olena Kravchenko"}]
)
def test_a_malformed_tool_call_costs_a_step_and_does_not_raise(packets, brain, arguments):
    """A naive agent fumbling its tool is not a service fault."""
    case_file, trace, _ = run(packets["APP-001"], brain, fumbling(arguments), proposal())

    assert case_file.decision == "CLEAR"
    assert trace.propose.searches[0].accepted is False
    assert trace.propose.searches[0].entries == []


def test_the_step_budget_stops_a_proposer_that_never_answers(packets, brain):
    """Ten turns primed, three allowed: the run still returns a case file."""
    case_file, trace, _ = run(packets["APP-011"], brain, *[searching(MISSED)] * 10, max_steps=3)

    assert case_file.decision == "REVIEW"
    assert trace.propose.budget == "steps_exhausted"
    assert trace.propose.steps == 3
    assert trace.propose.outcome == "no_answer"
    assert trace.override.proposed is None


def test_an_expired_deadline_stops_the_loop_before_it_starts(packets, brain):
    """The time guard is checked before each turn, so an already-late run spends nothing more."""
    client = FakeClient(extraction(), proposal())

    _, trace = screen(
        packets["APP-011"], brain, client, run_id="run-0", model="claude-opus-5", timeout_seconds=-1.0
    )

    assert trace.propose.budget == "time_exhausted"
    assert trace.propose.steps == 0
    assert trace.propose.usage.input_tokens == 0


def test_hits_are_ordered_independently_of_which_search_ran_first(packets, brain):
    """Two searches, both orders, one serialisation — the union is keyed, not appended."""
    forward = run(packets["APP-001"], brain, searching(FOUND, "Viktor Petrov"), proposal())[1]
    backward = run(packets["APP-001"], brain, searching("Viktor Petrov", FOUND), proposal())[1]

    assert [hit.entry_id for hit in forward.screen.hits] == [hit.entry_id for hit in backward.screen.hits]


def test_the_same_search_twice_is_one_hit(packets, brain):
    _, trace, _ = run(packets["APP-001"], brain, searching(FOUND), searching(FOUND), proposal())

    assert len(trace.screen.hits) == 1
    assert len(trace.propose.searches) == 2


def test_the_loop_is_skipped_entirely_when_no_step_is_allowed(brain, packets):
    client = FakeClient(extraction())

    _, trace = screen(packets["APP-001"], brain, client, run_id="run-0", model="claude-opus-5", max_steps=0)

    assert trace.propose.steps == 0
    assert trace.propose.budget == "steps_exhausted"


def test_propose_asks_the_model_nothing_the_case_did_not_contain(brain):
    """The loop's messages grow with tool results, never with policy or document text."""
    client = FakeClient(searching(MISSED), proposal())

    propose(brain, Facts(), [], client, max_steps=4)

    followup = str(client.calls[1]["messages"])
    assert "tool_result" in followup
    assert brain.policy_text not in followup


def test_a_deadline_that_expires_mid_loop_stops_it(brain):
    """Not a mocked clock: the budget is checked against a real monotonic deadline between turns."""
    client = FakeClient(searching(MISSED), searching(MISSED), proposal())

    result = propose(brain, Facts(), [], client, max_steps=8, deadline=time.monotonic() + 0.0)

    assert result.budget == "time_exhausted"
    assert result.proposal is None


def test_a_hit_on_an_entity_the_sweep_already_found_is_dropped(packets, brain):
    """It cites nothing new and fires no rule that has not fired — and it was the whole measured instability. (D-013)"""
    before, _, _ = run(packets["APP-009"], brain, proposal())
    after, trace, _ = run(packets["APP-009"], brain, searching("Ivanka Sokolova"), proposal())

    assert trace.propose.searches[0].entries[0].entry_id == "EU-2001"
    assert trace.propose.hits_redundant == 1
    assert trace.propose.hits_added == 0
    assert [entry.phase for entry in trace.evaluate] == ["initial"]
    assert after.model_dump_json(exclude={"run_id"}) == before.model_dump_json(exclude={"run_id"})


def test_a_hit_on_an_entity_the_sweep_missed_still_counts(packets, brain):
    """The case the loop exists for: an entity no permutation of the packet's names could reach."""
    _, trace, _ = run(packets["APP-001"], brain, searching(FOUND), proposal())

    assert trace.propose.hits_added == 1
    assert trace.propose.hits_redundant == 0


def test_the_redundant_drop_cannot_hide_a_second_entity(packets, brain):
    """Dropping by entry_id must not drop a different entry found in the same search turn."""
    _, trace, _ = run(packets["APP-009"], brain, searching("Ivanka Sokolova", FOUND), proposal())

    assert trace.propose.hits_added == 1
    assert trace.propose.hits_redundant == 1
    assert sorted(hit.entry_id for hit in trace.screen.hits) == ["EU-2001", "PEP-3004"]
