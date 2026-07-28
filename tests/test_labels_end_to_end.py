"""The twelve labelled applicants, packet to verdict, with no model anywhere on the path."""

import csv

import pytest

from agent.extraction import floor_of, merge
from agent.facts import from_packet
from agent.guardrails import assert_no_auto_clear
from agent.rules import evaluate
from agent.screening import sweep
from tests.conftest import ASSETS, extraction

# The rule the label attributes the verdict to. The right answer for the wrong
# reason is still wrong, so the test pins the rule, not only the decision.
EXPECTED_RULE = {
    "APP-001": 8,
    "APP-002": 3,
    "APP-003": 1,
    "APP-004": 4,
    "APP-005": 5,
    "APP-006": 6,
    "APP-007": 1,
    "APP-008": 7,
    "APP-009": 1,
    "APP-010": 8,
    "APP-011": 2,
    "APP-012": 3,
}


def labels() -> dict[str, str]:
    with (ASSETS / "labels_dev.csv").open(encoding="utf-8") as handle:
        return {row["applicant_id"]: row["expected_decision"] for row in csv.DictReader(handle)}


def screen(packet, brain):
    """The pipeline as 004 will compose it, driven by the deterministic floor rather than a model."""
    result = merge(packet, floor_of(packet), extraction())
    facts = from_packet(packet, result, brain.settings)
    facts.hits = sweep(result.screening_targets, brain.settings.min_name_score).hits
    verdict = evaluate(brain, facts)
    assert_no_auto_clear(facts, verdict)
    return facts, verdict


@pytest.mark.parametrize("applicant_id,expected", sorted(labels().items()))
def test_the_labelled_decision_is_reached_for_the_labelled_reason(packets, brain, applicant_id, expected):
    _, verdict = screen(packets[applicant_id], brain)

    assert verdict.decision == expected
    assert EXPECTED_RULE[applicant_id] in verdict.fired_rules


def test_the_false_clear_count_is_zero(packets, brain):
    """The headline metric, over every applicant the dev set gives a hit for."""
    cleared_with_a_hit = [
        applicant_id
        for applicant_id in labels()
        for facts, verdict in [screen(packets[applicant_id], brain)]
        if facts.hits and verdict.decision == "CLEAR"
    ]

    assert cleared_with_a_hit == []


def test_the_model_returning_nothing_still_reaches_every_label(packets, brain):
    """This whole file runs on the floor alone, which is D-008's guarantee stated as a result."""
    assert all(screen(packets[applicant_id], brain)[1].decision == expected for applicant_id, expected in labels().items())


def test_app_011_is_review_because_the_hit_is_unconfirmed(packets, brain):
    """The override case: a naive 'no exact match, lean CLEAR' heuristic gets this wrong; Rule 2 does not."""
    facts, verdict = screen(packets["APP-011"], brain)

    assert [(hit.entry_id, hit.corroborated) for hit in facts.hits] == [("EU-2001", False)]
    assert verdict.decision == "REVIEW"
    assert verdict.fired_rules == [2]


def test_app_009_blocks_with_the_injection_present(packets, brain):
    """The document asking for CLEAR is in the packet and changes nothing."""
    facts, verdict = screen(packets["APP-009"], brain)

    assert facts.injection_suspected is True
    assert verdict.decision == "BLOCK"
    assert verdict.fired_rules == [1]


def test_the_verdict_is_a_pure_function_of_the_packet(packets, brain):
    """Given a fixed extraction, nothing downstream reads a clock, an environment or a random source."""
    for applicant_id in labels():
        first = screen(packets[applicant_id], brain)[1]
        second = screen(packets[applicant_id], brain)[1]

        assert first.model_dump_json() == second.model_dump_json()


def test_the_unlabelled_applicants_that_hit_are_not_cleared(packets, brain):
    """APP-013 and APP-015 have no label; screening them silently CLEAR would be the failure worth catching."""
    decisions = {
        applicant_id: screen(packets[applicant_id], brain)[1].decision
        for applicant_id in ("APP-013", "APP-015")
    }

    assert decisions == {"APP-013": "REVIEW", "APP-015": "BLOCK"}
