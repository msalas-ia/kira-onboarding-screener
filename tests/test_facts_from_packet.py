"""The packet is read here and nowhere else, so `/screen` is composition. Hits are spec 003's half of the bag."""

from datetime import date

import pytest

from agent.extraction import extract
from agent.facts import from_packet
from agent.rules import evaluate
from tests.conftest import FakeClient, extraction

# Everything else is CLEAR until spec 003 fills hits[].
NON_WATCHLIST_REVIEWS = {
    "APP-005": (5, "money-services MCC"),
    "APP-006": (6, "no incorporation document"),
    "APP-008": (7, "shell-company signals"),
    "APP-017": (6, "an empty ubos[] array"),
    "APP-018": (5, "money-services MCC"),
}


@pytest.fixture
def facts_for(packets, brain):
    """Facts for one applicant, with a model that reports nothing: the floor alone."""

    def _facts(applicant_id: str):
        packet = packets[applicant_id]
        return from_packet(packet, extract(packet, brain, FakeClient(extraction())), brain.settings)

    return _facts


def test_every_delivered_packet_parses(packets):
    assert len(packets) == 18


def test_the_only_applicant_without_an_incorporation_document(facts_for, packets):
    missing = [applicant_id for applicant_id in packets if not facts_for(applicant_id).has_incorporation_doc]

    assert missing == ["APP-006"]


def test_the_ubo_list_is_a_populated_array_not_a_document(facts_for, packets):
    """D-004: APP-001 is labelled CLEAR with no ubo_declaration; APP-017 has the document and no owners."""
    without = [applicant_id for applicant_id in packets if not facts_for(applicant_id).has_ubo_list]

    assert without == ["APP-017"]
    assert facts_for("APP-001").has_ubo_list is True


def test_company_age_comes_from_the_brain_not_the_clock(facts_for, packets, brain):
    """D-006: the same packet must decide the same way tomorrow."""
    assert brain.settings.as_of_date == date(2026, 7, 27)
    assert facts_for("APP-008").formation_age_days == (date(2026, 7, 27) - date(2025, 12, 1)).days
    assert facts_for("APP-001").formation_age_days == (date(2026, 7, 27) - date(2021, 4, 10)).days


def test_the_mcc_is_carried_through_verbatim(facts_for, packets):
    assert {applicant_id: facts_for(applicant_id).mcc for applicant_id in ("APP-005", "APP-018")} == {
        "APP-005": "6051",
        "APP-018": "6051",
    }


def test_only_the_injected_applicant_carries_the_flag(facts_for, packets):
    flagged = [applicant_id for applicant_id in packets if facts_for(applicant_id).injection_suspected]

    assert flagged == ["APP-009"]


def test_no_applicant_arrives_with_hits(facts_for, packets):
    """Screening is spec 003's job; nothing here may invent a match."""
    assert all(facts_for(applicant_id).hits == [] for applicant_id in packets)


@pytest.mark.parametrize("applicant_id, expected", sorted(NON_WATCHLIST_REVIEWS.items()))
def test_the_reviews_that_do_not_depend_on_the_watchlist_already_hold(applicant_id, expected, facts_for, brain):
    """Three of these five are labelled; the extraction step is what makes them fire."""
    rule, _reason = expected
    verdict = evaluate(brain, facts_for(applicant_id))

    assert verdict.decision == "REVIEW"
    assert verdict.fired_rules == [rule]


def test_every_other_applicant_is_clear_until_screening_runs(facts_for, packets, brain):
    clear = {
        applicant_id
        for applicant_id in packets
        if evaluate(brain, facts_for(applicant_id)).decision == "CLEAR"
    }

    assert clear == set(packets) - set(NON_WATCHLIST_REVIEWS)


def test_the_injection_does_not_move_its_own_verdict(facts_for, brain):
    """APP-009 is labelled BLOCK on a hit spec 003 supplies; what matters here is that asking for CLEAR bought nothing."""
    verdict = evaluate(brain, facts_for("APP-009"))

    assert verdict.decision == "CLEAR"
    assert "injection" not in str(verdict.reasons)
