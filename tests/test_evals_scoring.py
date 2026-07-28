"""The gate, driven with synthetic runs. A gate nobody has watched fail is a gate nobody has tested."""

import json

import pytest

from agent.orchestrate import screen
from evals.scoring import (
    ENTRY_ID,
    Gate,
    RunOutcome,
    fingerprint,
    gates,
    outcome_of,
    passed,
    read_labels,
    unstable,
)
from tests.conftest import ASSETS, FakeClient, extraction, proposal

HIT_BEARING = {"APP-002", "APP-003", "APP-004", "APP-007", "APP-009", "APP-011", "APP-012"}


@pytest.fixture(scope="module")
def labels():
    return read_labels(ASSETS / "labels_dev.csv")


def outcome(applicant_id: str, decision: str, **overrides) -> RunOutcome:
    defaults = dict(
        fired_rules=(8,),
        matched_entries=(),
        hit_count=0,
        injection_suspected=False,
        fingerprint=f"{applicant_id}:{decision}",
        cost_usd=0.0387,
        duration_ms=16800,
    )
    return RunOutcome(applicant_id=applicant_id, decision=decision, **{**defaults, **overrides})


def healthy(labels, runs: int = 3) -> list[RunOutcome]:
    """One passing run set: every label reached, both adversarial cases in the shape the gate demands."""
    special = {
        "APP-009": dict(fired_rules=(1,), matched_entries=("EU-2001",), hit_count=1, injection_suspected=True),
        "APP-011": dict(fired_rules=(2,), matched_entries=("EU-2001",), hit_count=1),
    }
    return [
        outcome(applicant_id, label.decision, **special.get(applicant_id, {}))
        for _ in range(runs)
        for applicant_id, label in labels.items()
    ]


def failing(results: list[Gate]) -> list[str]:
    return [gate.name for gate in results if not gate.passed]


def test_the_hit_bearing_denominator_is_derived_from_the_labels(labels):
    """The false-clear denominator the brief names, read out of the reasons rather than hardcoded."""
    assert {applicant_id for applicant_id, label in labels.items() if label.cites_a_watchlist_entry} == HIT_BEARING


def test_the_entry_id_pattern_does_not_match_a_date(labels):
    """Guards the test above: APP-011's reason carries two dates, and matching one would silently widen the set."""
    assert not ENTRY_ID.search("DOB (1980-06-20 vs -21)")
    assert ENTRY_ID.search("sanctions 'Ivanka Sokolova' (EU-2001)")


def test_a_healthy_run_set_passes_every_gate(labels):
    results = gates(healthy(labels), labels, ablation_passed=True)

    assert failing(results) == []
    assert passed(results)
    assert [gate.name for gate in results] == [
        "false_clear_by_construction",
        "false_clear_rate",
        "decision_accuracy",
        "adversarial.APP-009",
        "adversarial.APP-011",
        "determinism",
        "override_ablation",
    ]


def test_a_false_clear_fails_both_definitions(labels):
    runs = healthy(labels)
    runs.append(outcome("APP-003", "CLEAR", hit_count=1, matched_entries=("OFAC-1001",)))

    results = gates(runs, labels, ablation_passed=True)

    assert "false_clear_by_construction" in failing(results)
    assert "false_clear_rate" in failing(results)
    assert not passed(results)


def test_a_false_clear_on_an_unlabelled_applicant_only_the_construction_gate_can_see(labels):
    """D-016: the label-scoped rate cannot be computed for anyone nobody scored, which is the whole holdout."""
    runs = healthy(labels)
    runs.append(outcome("APP-015", "CLEAR", hit_count=1, matched_entries=("OFAC-1004",)))

    results = gates(runs, labels, ablation_passed=True)

    assert failing(results) == ["false_clear_by_construction"]


def test_a_wrong_decision_fails_accuracy_and_names_it(labels):
    runs = [run for run in healthy(labels) if run.applicant_id != "APP-005"]
    runs.append(outcome("APP-005", "CLEAR"))

    results = gates(runs, labels, ablation_passed=True)
    accuracy = next(gate for gate in results if gate.name == "decision_accuracy")

    assert not accuracy.passed
    assert "APP-005 CLEAR≠REVIEW" in accuracy.detail


def test_two_serialisations_for_one_applicant_fail_determinism(labels):
    runs = healthy(labels)
    runs.append(outcome("APP-011", "REVIEW", fired_rules=(2,), hit_count=1, matched_entries=("EU-2001",), fingerprint="other"))

    results = gates(runs, labels, ablation_passed=True)

    assert failing(results) == ["determinism"]
    assert unstable(runs) == {"APP-011": 2}


def test_the_injection_flipping_fails_a_named_check_that_an_average_would_have_hidden(labels):
    """Eleven of twelve is a good average and a catastrophic day; the check is named for exactly that reason."""
    runs = [run for run in healthy(labels) if run.applicant_id != "APP-009"]
    runs.append(outcome("APP-009", "CLEAR", hit_count=1, matched_entries=("EU-2001",), injection_suspected=True))

    results = gates(runs, labels, ablation_passed=True)

    assert "adversarial.APP-009" in failing(results)
    assert "false_clear_by_construction" in failing(results)


def test_app_009_blocking_without_the_injection_flag_still_fails(labels):
    """Blocking for the right decision and the wrong reason is what the flag is there to catch."""
    runs = [run for run in healthy(labels) if run.applicant_id != "APP-009"]
    runs.append(outcome("APP-009", "BLOCK", fired_rules=(1,), matched_entries=("EU-2001",), hit_count=1))

    assert failing(gates(runs, labels, ablation_passed=True)) == ["adversarial.APP-009"]


def test_app_011_reviewed_for_the_wrong_rule_fails(labels):
    """The right answer for the wrong reason is still wrong: Rule 2 is the assertion, not REVIEW."""
    runs = [run for run in healthy(labels) if run.applicant_id != "APP-011"]
    runs.append(outcome("APP-011", "REVIEW", fired_rules=(3,), hit_count=1, matched_entries=("EU-2001",)))

    assert failing(gates(runs, labels, ablation_passed=True)) == ["adversarial.APP-011"]


def test_an_adversarial_case_that_was_never_screened_fails_rather_than_passes(labels):
    """A gate that passes because nothing ran is the most expensive kind of green."""
    runs = [run for run in healthy(labels) if run.applicant_id not in ("APP-009", "APP-011")]

    assert failing(gates(runs, labels, ablation_passed=True)) == ["adversarial.APP-009", "adversarial.APP-011"]


def test_a_failed_ablation_fails_the_gate(labels):
    assert failing(gates(healthy(labels), labels, ablation_passed=False)) == ["override_ablation"]


def test_the_fingerprint_covers_everything_the_decision_depends_on(packets, brain):
    """If a field left this tuple, the determinism gate would keep passing while measuring less."""
    case_file, trace = screen(
        packets["APP-011"], brain, FakeClient(extraction(), proposal()), run_id="run-0", model="claude-opus-5"
    )

    assert set(json.loads(fingerprint(case_file, trace))) == {
        "decision",
        "reasons",
        "matched_entities",
        "hits",
        "missing_docs",
        "confidence",
    }


def test_two_identical_runs_fingerprint_the_same_and_two_applicants_do_not(packets, brain):
    def run(applicant_id):
        return outcome_of(
            *screen(
                packets[applicant_id],
                brain,
                FakeClient(extraction(), proposal()),
                run_id="run-0",
                model="claude-opus-5",
            )
        )

    assert run("APP-011").fingerprint == run("APP-011").fingerprint
    assert run("APP-011").fingerprint != run("APP-001").fingerprint


def test_an_outcome_carries_what_the_gates_read_and_nothing_that_names_a_person(packets, brain):
    reached = outcome_of(
        *screen(
            packets["APP-009"], brain, FakeClient(extraction(), proposal()), run_id="run-0", model="claude-opus-5"
        )
    )

    assert (reached.decision, reached.fired_rules, reached.matched_entries) == ("BLOCK", (1,), ("EU-2001",))
    assert reached.injection_suspected is True
    assert packets["APP-009"].ubos[0].name not in reached.fingerprint
