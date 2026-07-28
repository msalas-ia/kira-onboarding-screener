"""The runner's contract: what it exits with, and that a budget is enforced rather than documented."""

import json
import re

import pytest

from agent.extraction import ExtractionFailed
from agent.guardrails import GuardrailViolated
from agent.llm import ModelUnavailable
from agent.orchestrate import screen
from evals import run_evals
from evals.run_evals import COULD_NOT_MEASURE, GATE_FAILED, Budget, BudgetExceeded, main, measure
from evals.scoring import Gate
from tests.conftest import FakeClient, extraction, proposal
from tests.test_trace_has_no_pii import pii_of


@pytest.fixture
def offline(monkeypatch, brain):
    """A transport that runs the real orchestrator with the model faked out, so main() is exercised for free."""

    def run(packet, run_id):
        client = FakeClient(extraction(), proposal(cited_entries=["EU-2001"]))
        return screen(packet, brain, client, run_id=run_id, model="claude-opus-5")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-used-by-the-fake-transport")
    monkeypatch.setattr(run_evals, "in_process", lambda *args, **kwargs: run)
    return run


def test_a_healthy_suite_exits_zero_and_writes_its_report(offline, tmp_path):
    report, results = tmp_path / "results.md", tmp_path / "results.json"

    code = main(["--runs", "2", "--concurrency", "2", "--report", str(report), "--json", str(results)])

    assert code == 0
    assert "# Eval results" in report.read_text(encoding="utf-8")
    assert [gate["passed"] for gate in json.loads(results.read_text(encoding="utf-8"))["gates"]] == [True] * 7


def test_every_labelled_applicant_is_screened_the_requested_number_of_times(offline, tmp_path):
    main(["--runs", "3", "--report", str(tmp_path / "r.md"), "--json", str(tmp_path / "r.json")])

    outcomes = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))["outcomes"]

    assert len(outcomes) == 36
    assert len({outcome["applicant_id"] for outcome in outcomes}) == 12


def test_a_failing_gate_exits_one(offline, tmp_path, monkeypatch):
    """Exit 1 is a fact about the change, and nothing else in this file may produce it."""
    monkeypatch.setattr(run_evals, "gates", lambda *args, **kwargs: [Gate("determinism", False, "2 applicants")])

    assert main(["--runs", "1", "--report", str(tmp_path / "r.md")]) == GATE_FAILED


def test_an_unreachable_model_exits_two_rather_than_failing_a_gate(monkeypatch, tmp_path):
    """A merge blocked because Anthropic was overloaded is not a merge blocked because the code regressed."""

    def unreachable(packet, run_id):
        raise ModelUnavailable("overloaded")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "present")
    monkeypatch.setattr(run_evals, "in_process", lambda *args, **kwargs: unreachable)

    assert main(["--runs", "1", "--report", str(tmp_path / "r.md")]) == COULD_NOT_MEASURE


def test_a_missing_credential_exits_two_before_spending_anything(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    assert main(["--runs", "1", "--report", str(tmp_path / "r.md")]) == COULD_NOT_MEASURE
    assert not (tmp_path / "r.md").exists()


def test_the_budget_stops_the_suite_rather_than_being_advisory(monkeypatch, brain, tmp_path):
    """A suite that would cost $18 against a $1 limit stops, and writes nothing it could not measure."""

    def priced(packet, run_id):
        case_file, trace = screen(
            packet, brain, FakeClient(extraction(), proposal()), run_id=run_id, model="claude-opus-5"
        )
        return case_file, trace.model_copy(update={"cost_usd": 0.5})

    monkeypatch.setenv("ANTHROPIC_API_KEY", "present")
    monkeypatch.setattr(run_evals, "in_process", lambda *args, **kwargs: priced)

    code = main(["--runs", "3", "--concurrency", "1", "--max-cost-usd", "1.0", "--report", str(tmp_path / "r.md")])

    assert code == COULD_NOT_MEASURE
    assert not (tmp_path / "r.md").exists()


def test_a_budget_charges_until_it_is_crossed():
    budget = Budget(limit=0.10)

    budget.charge(0.04)
    budget.charge(0.05)

    with pytest.raises(BudgetExceeded, match=r"\$0.1200 spent against a limit of \$0.10"):
        budget.charge(0.03)


def test_an_exhausted_budget_leaves_the_remaining_runs_unstarted(packets, brain):
    """The overshoot is bounded by what was already in flight, which is what makes the limit a limit."""
    started = []

    def priced(packet, run_id):
        started.append(run_id)
        case_file, trace = screen(
            packet, brain, FakeClient(extraction(), proposal()), run_id=run_id, model="claude-opus-5"
        )
        return case_file, trace.model_copy(update={"cost_usd": 1.0})

    with pytest.raises(BudgetExceeded):
        measure(priced, packets, sorted(packets)[:6], runs=2, concurrency=1, budget=Budget(limit=1.5))

    assert len(started) < 12


def test_a_run_that_could_not_extract_exits_two_rather_than_crashing(monkeypatch, tmp_path):
    """How an out-of-credit key actually arrives: as a failed extraction, not as a ModelUnavailable."""

    def broke(packet, run_id):
        raise ExtractionFailed(f"{packet.applicant_id}: credit balance is too low")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "present")
    monkeypatch.setattr(run_evals, "in_process", lambda *args, **kwargs: broke)

    assert main(["--runs", "1", "--report", str(tmp_path / "r.md")]) == COULD_NOT_MEASURE


def test_a_guardrail_violation_fails_the_gate_rather_than_reporting_it_unmeasurable(monkeypatch, brain, tmp_path):
    """A policy that clears a hit is a correctness fact about the change, so it exits 1, not 2."""

    def refused(packet, run_id):
        raise GuardrailViolated("CLEAR returned with 1 watchlist hit(s): EU-2001")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "present")
    monkeypatch.setattr(run_evals, "in_process", lambda *args, **kwargs: refused)

    assert main(["--runs", "1", "--report", str(tmp_path / "r.md")]) == GATE_FAILED


def test_the_machine_readable_dump_carries_no_pii_either(offline, tmp_path, packets):
    """It is not committed, but it is an artifact somebody will paste somewhere."""
    main(["--runs", "1", "--report", str(tmp_path / "r.md"), "--json", str(tmp_path / "r.json")])
    dumped = (tmp_path / "r.json").read_text(encoding="utf-8").casefold()

    # Whole words, not substrings: `reasons[]` carries the policy term
    # `nominee_director`, which contains a UBO's `role` without being it.
    leaks = {
        applicant_id: [
            value for value in pii_of(packet) if re.search(rf"\b{re.escape(value.casefold())}\b", dumped)
        ]
        for applicant_id, packet in packets.items()
    }

    assert {applicant_id: found for applicant_id, found in leaks.items() if found} == {}
