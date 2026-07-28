"""The results summary is a committed artifact, so it is checked over its bytes the same way the trace is."""

import re

import pytest

from agent.brain import load_version
from agent.orchestrate import screen
from evals.ablation import NAIVE_VERSION, compare
from evals.report import Report, render
from evals.scoring import Gate, gates, outcome_of, read_labels
from tests.conftest import ASSETS, REPO_BRAIN, FakeClient, extraction, proposal
from tests.test_trace_has_no_pii import pii_of


@pytest.fixture(scope="module")
def labels():
    return read_labels(ASSETS / "labels_dev.csv")


@pytest.fixture
def report(packets, brain, labels):
    """A real report: real packets, the real ablation, real orchestrator runs with the model faked out."""
    outcomes = [
        outcome_of(
            *screen(
                packets[applicant_id],
                brain,
                FakeClient(extraction(), proposal(cited_entries=["EU-2001"])),
                run_id=f"eval-{applicant_id}",
                model="claude-opus-5",
            )
        )
        for applicant_id in sorted(labels)
    ]
    naive = load_version(REPO_BRAIN, NAIVE_VERSION)
    ablation = compare(packets, brain, naive)
    return Report(
        commit="abc1234",
        model="claude-opus-5",
        runs=1,
        brain_version=brain.version,
        brain_hash=brain.brain_hash,
        naive_version=naive.version,
        watchlist_hash="sha256:0cca8d5",
        gates=gates(outcomes, labels, ablation_passed=True),
        outcomes=outcomes,
        labels=labels,
        ablation=ablation,
        unlabelled=sorted(set(packets) - set(labels)),
    )


def test_no_packet_pii_reaches_the_report(report, packets):
    """The report is committed and shared, which makes this stricter than the same claim about a log."""
    rendered = render(report).casefold()
    leaks = {
        applicant_id: [value for value in pii_of(packet) if value.casefold() in rendered]
        for applicant_id, packet in packets.items()
    }

    assert {applicant_id: found for applicant_id, found in leaks.items() if found} == {}


def test_no_document_text_reaches_the_report(report, packets):
    rendered = render(report)
    offenders = [
        phrase.strip()
        for packet in packets.values()
        for document in packet.documents
        for phrase in re.findall(r"[A-Za-z][A-Za-z ,\-]{15,}", document.content)
        if phrase.strip() and phrase.strip() in rendered
    ]

    assert offenders == []


def test_the_report_states_which_policy_produced_it(report):
    """A results table that does not name its policy state is a screenshot."""
    rendered = render(report)

    assert report.brain_hash in rendered
    assert "`abc1234`" in rendered
    assert report.watchlist_hash in rendered


def test_every_gate_appears_with_its_verdict(report):
    rendered = render(report)

    assert all(f"`{gate.name}`" in rendered for gate in report.gates)
    assert "**FAIL**" not in rendered


def test_a_failed_gate_is_impossible_to_miss(report):
    failed = Gate(name="determinism", passed=False, detail="2 applicants")
    rendered = render(Report(**{**report.__dict__, "gates": [failed]}))

    assert "| `determinism` | **FAIL** | 2 applicants |" in rendered


def test_the_ablation_section_carries_the_finding_and_not_just_the_rows(report):
    """The count of what the guardrail does not catch is the point of the section."""
    rendered = render(report)

    assert "disagree on **10 of 18**" in rendered
    assert "refuses **5**" in rendered
    assert "serves the other **5**" in rendered


def test_the_six_unlabelled_applicants_are_reported_without_being_scored(report):
    rendered = render(report).split("## The six unlabelled applicants", 1)[1]

    assert report.unlabelled == ["APP-013", "APP-014", "APP-015", "APP-016", "APP-017", "APP-018"]
    assert all(applicant_id in rendered for applicant_id in report.unlabelled)
    assert "expected" not in rendered


def test_the_two_adversarial_cases_are_named_rows_rather_than_an_average(report):
    """The brief singles both out by name, and so does the gate table a reviewer reads."""
    names = [gate.name for gate in report.gates]

    assert "adversarial.APP-009" in names and "adversarial.APP-011" in names


def test_the_override_section_says_what_the_model_proposed_and_not_only_that_it_differed(report):
    """"They disagreed" is a field; "it proposed CLEAR and the Brain said REVIEW" is the demonstration."""
    section = render(report).split("## The override, against the live model", 1)[1].split("## Reported", 1)[0]

    assert "| applicant | runs overruled | the model proposed | the Brain decided |" in section
    assert "| APP-011 | 1 of 1 | CLEAR | **REVIEW** |" in section


def test_a_run_where_nothing_disagreed_says_so_rather_than_showing_an_empty_table(report):
    """Agreement is a result, not a missing feature."""
    agreed = [outcome.__class__(**{**outcome.__dict__, "overridden": False}) for outcome in report.outcomes]
    section = render(Report(**{**report.__dict__, "outcomes": agreed}))

    assert "No run disagreed." in section
