"""The override, measured as policy against policy: two versioned rule tables over one facts bag. (D-015)"""

import copy
from pathlib import Path

import pytest

from agent.brain import list_versions, load_version
from agent.guardrails import GuardrailViolated, assert_no_auto_clear
from agent.rules import evaluate
from evals.ablation import NAIVE_VERSION, compare, facts_of, override_demonstrated
from tests.conftest import REPO_BRAIN

# Measured over the delivered packets, not asserted from the rule table.
DISAGREE_LABELLED = {"APP-002", "APP-004", "APP-005", "APP-006", "APP-008", "APP-011", "APP-012"}
DISAGREE_ALL = DISAGREE_LABELLED | {"APP-013", "APP-017", "APP-018"}
GUARDRAIL_CATCHES = {"APP-002", "APP-004", "APP-011", "APP-012", "APP-013"}


@pytest.fixture
def naive():
    return load_version(REPO_BRAIN, NAIVE_VERSION)


@pytest.fixture
def rows(packets, brain, naive):
    return compare(packets, brain, naive)


def test_the_naive_version_is_an_ordinary_brain(naive, brain):
    """It loads through the same loader and validates the same way, or the comparison proves nothing about v1."""
    assert naive.version == NAIVE_VERSION
    assert naive.brain_hash != brain.brain_hash
    assert sorted(naive.prompts) == sorted(brain.prompts)
    assert {entry["version"]: entry["valid"] for entry in list_versions(REPO_BRAIN)} == {"v0-naive": True, "v1": True}


def test_only_the_rule_table_differs(naive, brain):
    """The claim the ablation rests on: settings and prompts are identical, so a difference measures the table."""
    assert naive.settings == brain.settings
    assert naive.prompts == brain.prompts
    assert [rule.id for rule in naive.rules] != [rule.id for rule in brain.rules]


def test_app_011_is_cleared_by_the_naive_table_and_reviewed_by_the_live_one(rows):
    """The designated override case, with no model anywhere on the path."""
    row = next(row for row in rows if row.applicant_id == "APP-011")

    assert (row.naive, row.live) == ("CLEAR", "REVIEW")
    assert row.live_rules == (2,)
    assert override_demonstrated(rows)


def test_the_two_policies_disagree_on_ten_packets_and_seven_labels(rows):
    """The override is not a staged single case: it fires on more than half the labelled set."""
    disagreeing = {row.applicant_id for row in rows if row.disagrees}

    assert disagreeing == DISAGREE_ALL
    assert {applicant_id for applicant_id in disagreeing if applicant_id <= "APP-012"} == DISAGREE_LABELLED


def test_every_disagreement_is_in_the_clear_direction(rows):
    """Which is what makes the naive table a legitimate baseline and a necessary thing to overrule."""
    assert all(row.naive == "CLEAR" for row in rows if row.disagrees)


def test_the_guardrail_catches_exactly_the_half_that_carries_a_hit(rows):
    """The uncomfortable half of the finding, pinned so it cannot quietly stop being true."""
    caught = {row.applicant_id for row in rows if row.guardrail == "raises"}

    assert caught == GUARDRAIL_CATCHES
    assert {row.applicant_id for row in rows if row.disagrees} - caught == {
        "APP-005",
        "APP-006",
        "APP-008",
        "APP-017",
        "APP-018",
    }


def test_the_guardrail_refuses_app_011_and_is_silent_on_app_005(packets, brain, naive):
    """The two halves directly: a bad policy is refused where a hit exists, and served where none does."""
    with pytest.raises(GuardrailViolated, match="EU-2001"):
        facts = facts_of(packets["APP-011"], brain.settings)
        assert_no_auto_clear(facts, evaluate(naive, facts))

    facts = facts_of(packets["APP-005"], brain.settings)
    verdict = evaluate(naive, facts)
    assert_no_auto_clear(facts, verdict)
    assert verdict.decision == "CLEAR"


def test_a_naive_version_with_different_settings_is_refused(packets, brain, v1_document, make_brain_dir):
    """If the two disagreed on a threshold, a difference in decisions would not isolate the rule table."""
    document = copy.deepcopy(v1_document)
    document["settings"]["min_name_score"] = 0.9
    other = load_version(make_brain_dir(document, version="other"), "other")

    with pytest.raises(ValueError, match="settings"):
        compare(packets, brain, other)


def test_the_comparison_reads_no_model(packets, brain, naive):
    """It is offline and free, which is what lets it gate on every run rather than on the ones somebody paid for."""
    source = Path("evals/ablation.py").read_text(encoding="utf-8")

    assert "client" not in source
    assert "extract(" not in source
