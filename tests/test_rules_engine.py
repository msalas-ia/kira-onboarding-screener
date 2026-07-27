"""One test per policy rule, plus the properties the brief grades: determinism, order independence, and that only the Brain decides."""

import random

from agent.brain import load_brain
from agent.constants import SHELL_SIGNAL_RECENT_FORMATION
from agent.rules import evaluate
from tests.conftest import clean_facts, hit


def test_rule_1_corroborated_sanctions_hit_blocks(brain):
    verdict = evaluate(brain, clean_facts(hits=[hit(corroborated=True)]))

    assert verdict.decision == "BLOCK"
    assert verdict.fired_rules == [1]
    assert "OFAC-1001" in verdict.reasons[0]
    assert verdict.matched_entities[0].entry_id == "OFAC-1001"


def test_rule_2_unconfirmed_sanctions_hit_reviews_and_never_clears(brain):
    """APP-011's shape: the name nearly matches, DOB and country conflict."""
    verdict = evaluate(
        brain,
        clean_facts(
            hits=[hit(entry_id="EU-2001", name_score=0.966, corroborated=False, corroboration_basis="none")]
        ),
    )

    assert verdict.decision == "REVIEW"
    assert verdict.fired_rules == [2]
    assert "Rule 2" in verdict.reasons[0]
    assert "EU-2001" in verdict.reasons[0]


def test_rule_3_pep_hit_reviews(brain):
    verdict = evaluate(brain, clean_facts(hits=[hit(entry_id="PEP-3001", hit_type="pep", corroborated=False)]))

    assert verdict.decision == "REVIEW"
    assert verdict.fired_rules == [3]


def test_rule_4_adverse_media_hit_reviews(brain):
    verdict = evaluate(
        brain,
        clean_facts(
            hits=[
                hit(
                    entry_id="AM-4001",
                    hit_type="adverse_media",
                    subject="business",
                    subject_ref="business",
                    corroborated=False,
                )
            ]
        ),
    )

    assert verdict.decision == "REVIEW"
    assert verdict.fired_rules == [4]


def test_rule_5_high_risk_mcc_reviews_even_with_clean_screens(brain):
    verdict = evaluate(brain, clean_facts(mcc="6051"))

    assert verdict.decision == "REVIEW"
    assert verdict.fired_rules == [5]
    assert verdict.matched_entities == []


def test_rule_6_missing_incorporation_document_reviews(brain):
    verdict = evaluate(brain, clean_facts(has_incorporation_doc=False))

    assert verdict.decision == "REVIEW"
    assert verdict.fired_rules == [6]
    assert verdict.missing_docs == ["certificate_of_incorporation"]


def test_rule_6_treats_an_empty_ubo_array_as_a_missing_ubo_list(brain):
    """APP-017's shape: an incorporation document, but ubos: []."""
    verdict = evaluate(brain, clean_facts(has_ubo_list=False))

    assert verdict.decision == "REVIEW"
    assert verdict.missing_docs == ["ubo_list"]


def test_rule_7_needs_two_shell_signals(brain):
    one = evaluate(brain, clean_facts(shell_signals=["nominee_director"]))
    two = evaluate(brain, clean_facts(shell_signals=["nominee_director", "mass_registration_address"]))

    assert one.decision == "CLEAR"
    assert two.decision == "REVIEW"
    assert two.fired_rules == [7]


def test_rule_7_counts_a_recent_formation_using_the_brain_date_not_the_clock(brain):
    """APP-008's shape: the window is a Brain setting, so signals and count cannot disagree with the policy."""
    verdict = evaluate(brain, clean_facts(shell_signals=["nominee_director"], formation_age_days=30))

    assert verdict.decision == "REVIEW"
    assert verdict.fired_rules == [7]
    assert SHELL_SIGNAL_RECENT_FORMATION in verdict.reasons[0]


def test_rule_8_is_the_only_thing_that_fires_on_a_clean_applicant(brain):
    verdict = evaluate(brain, clean_facts())

    assert verdict.decision == "CLEAR"
    assert verdict.fired_rules == [8]
    assert verdict.reasons == ["Rule 8 — no rule triggered"]
    assert verdict.missing_docs == []


def test_rule_9_is_inert_a_bare_name_collision_still_reviews(brain):
    """Rules 2/3/4 catch every name hit first, and a CLEAR rule cannot lower a verdict another rule raised."""
    verdict = evaluate(
        brain,
        clean_facts(
            hits=[
                hit(
                    entry_id="OFAC-1004",
                    subject="business",
                    subject_ref="business",
                    name_score=0.79,
                    corroborated=False,
                    corroboration_basis="none",
                )
            ]
        ),
    )

    assert verdict.decision == "REVIEW"
    assert verdict.fired_rules == [2]


def test_severity_aggregation_keeps_every_rule_that_fired(brain):
    """The policy says the most severe outcome wins, not that the rest vanish."""
    verdict = evaluate(brain, clean_facts(mcc="6051", hits=[hit(corroborated=True)]))

    assert verdict.decision == "BLOCK"
    assert verdict.confidence == 0.95
    assert verdict.fired_rules == [1, 5]
    assert len(verdict.reasons) == 2
    assert verdict.reasons[0].startswith("Rule 1")


def test_every_ubo_is_evaluated_not_only_the_first(brain):
    verdict = evaluate(
        brain,
        clean_facts(
            hits=[
                hit(entry_id="PEP-3002", hit_type="pep", subject_ref="ubo[1]", corroborated=False),
                hit(entry_id="EU-2001", subject_ref="ubo[0]", corroborated=True),
            ]
        ),
    )

    assert verdict.decision == "BLOCK"
    assert verdict.fired_rules == [1, 3]
    assert [entity.entry_id for entity in verdict.matched_entities] == ["EU-2001", "PEP-3002"]


def test_the_order_hits_arrive_in_cannot_change_a_single_byte(brain):
    hits = [
        hit(entry_id="EU-2001", subject_ref="ubo[0]", corroborated=True),
        hit(entry_id="PEP-3002", hit_type="pep", subject_ref="ubo[1]", corroborated=False),
        hit(
            entry_id="AM-4001",
            hit_type="adverse_media",
            subject="business",
            subject_ref="business",
            corroborated=False,
        ),
    ]
    baseline = evaluate(brain, clean_facts(hits=hits)).model_dump_json()

    shuffler = random.Random(0)
    for _ in range(20):
        shuffled = list(hits)
        shuffler.shuffle(shuffled)
        assert evaluate(brain, clean_facts(hits=shuffled)).model_dump_json() == baseline


def test_the_same_facts_produce_one_distinct_output_over_a_hundred_runs(brain):
    facts = clean_facts(mcc="6051", hits=[hit(entry_id="EU-2001", corroborated=False)])

    outputs = {evaluate(brain, facts).model_dump_json() for _ in range(100)}

    assert len(outputs) == 1


def test_only_the_brain_changes_the_outcome(brain, without_rule):
    """The override demo as an ablation: same facts, same code, and Rule 2 is the only difference."""
    facts = clean_facts(hits=[hit(entry_id="EU-2001", name_score=0.966, corroborated=False)])

    assert evaluate(brain, facts).decision == "REVIEW"

    ablated = load_brain(without_rule(rule_id=2))
    assert evaluate(ablated, facts).decision == "CLEAR"


def test_the_verdict_carries_the_policy_state_that_produced_it(brain):
    verdict = evaluate(brain, clean_facts())

    assert verdict.policy_version == "v1"
    assert verdict.brain_hash == brain.brain_hash
    assert verdict.brain_hash.startswith("sha256:")
