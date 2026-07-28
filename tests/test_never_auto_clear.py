"""The guardrail that survives a bad edit to the Brain: a hit is never auto-CLEARed."""

import pytest

from agent.brain import load_version
from agent.guardrails import GuardrailViolated, assert_no_auto_clear
from agent.rules import evaluate
from tests.conftest import clean_facts, hit


def test_a_clean_applicant_passes(brain):
    facts = clean_facts()

    assert_no_auto_clear(facts, evaluate(brain, facts))


def test_a_hit_that_reviews_passes(brain):
    """The guardrail is about CLEAR, not about severity: REVIEW on a hit is the policy working."""
    facts = clean_facts(hits=[hit(corroborated=False, corroboration_basis="none")])

    assert_no_auto_clear(facts, evaluate(brain, facts))


def test_a_brain_that_clears_a_corroborated_sanctions_hit_raises(v1_document, make_brain_dir):
    """Rule ordering cannot be trusted to produce this property, so it is asserted independently."""
    for rule in v1_document["rules"]:
        if rule["id"] in (1, 2):
            rule["decision"] = "CLEAR"
    brain = load_version(make_brain_dir(v1_document, version="wrong"), "wrong")
    facts = clean_facts(hits=[hit()])

    verdict = evaluate(brain, facts)
    assert verdict.decision == "CLEAR"

    with pytest.raises(GuardrailViolated, match="OFAC-1001"):
        assert_no_auto_clear(facts, verdict)


def test_the_violation_names_the_entries_and_no_one_else(v1_document, make_brain_dir):
    """The message goes to a log, so it may carry entry ids and never a subject's name."""
    for rule in v1_document["rules"]:
        rule["decision"] = "CLEAR"
    brain = load_version(make_brain_dir(v1_document, version="wrong"), "wrong")
    facts = clean_facts(hits=[hit(entry_id="EU-2001"), hit(entry_id="EU-2001", subject_ref="ubo[1]")])

    with pytest.raises(GuardrailViolated) as raised:
        assert_no_auto_clear(facts, evaluate(brain, facts))

    assert "EU-2001" in str(raised.value)
    assert "2 watchlist hit(s)" in str(raised.value)
