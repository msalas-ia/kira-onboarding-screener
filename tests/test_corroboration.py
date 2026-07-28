"""Corroboration is a field comparison the policy already specifies; one agreeing comparable pair is enough. (D-003)"""

from datetime import date

import pytest

from agent.corroborate import corroborate
from agent.schemas import ScreeningTarget
from agent.screening import sweep
from tests.test_screening_sweep import MIN_SCORE, targets_of


def entry(**overrides) -> dict:
    """EU-2001 as the watchlist states it, unless the case under test changes a field."""
    return {"entry_id": "EU-2001", "dob": "1980-06-21", "country": "BY"} | overrides


def person(**overrides) -> ScreeningTarget:
    defaults = dict(name="Ivanka Sokolova", subject="ubo", subject_ref="ubo[0]", dob=date(1980, 6, 21), country="BY")
    return ScreeningTarget(**{**defaults, **overrides})


def test_both_pairs_agreeing_corroborates_on_the_stronger_one():
    assert corroborate(person(), entry()) == (True, "dob")


def test_the_dob_alone_is_enough():
    assert corroborate(person(country="PL"), entry()) == (True, "dob")


def test_the_country_alone_is_enough():
    """This is D-003 stated as a test: a conflicting DOB does not veto an agreeing country."""
    assert corroborate(person(dob=date(1980, 6, 20)), entry()) == (True, "country")


def test_both_pairs_conflicting_leaves_it_unconfirmed():
    assert corroborate(person(dob=date(1980, 6, 20), country="PL"), entry()) == (False, "none")


@pytest.mark.parametrize(
    "target,candidate",
    [
        (person(dob=None, country=None), entry()),
        (person(), entry(dob=None, country=None)),
        (person(dob=None), entry(country=None)),
    ],
)
def test_no_comparable_pair_is_never_corroborated(target, candidate):
    """Missing identity is not confirmed identity, and the policy says so in as many words."""
    assert corroborate(target, candidate) == (False, "none")


def test_a_business_corroborates_on_country_because_it_has_no_dob():
    target = ScreeningTarget(name="Zephyr Logistics FZE", subject="business", subject_ref="business", country="AE")

    assert corroborate(target, {"entry_id": "OFAC-1004", "dob": None, "country": "AE"}) == (True, "country")


def test_country_comparison_ignores_case_and_padding():
    assert corroborate(person(dob=None, country=" by "), entry(dob=None)) == (True, "country")


def test_a_name_found_in_a_document_can_never_corroborate():
    """A supplementary target has no DOB and no country, so a sanctions hit against it is Rule 2, not Rule 1."""
    target = ScreeningTarget(
        name="Viktor Petrov", subject="ubo", subject_ref="document[1]", source="document"
    )

    assert corroborate(target, {"entry_id": "OFAC-1001", "dob": "1968-03-12", "country": "RU"}) == (False, "none")


CORROBORATED = {"APP-003": "dob", "APP-007": "dob", "APP-009": "dob", "APP-015": "country"}


@pytest.mark.parametrize("applicant_id,basis", sorted(CORROBORATED.items()))
def test_the_labelled_block_cases_corroborate(packets, applicant_id, basis):
    hits = sweep(targets_of(packets[applicant_id]), MIN_SCORE).hits

    assert [(hit.corroborated, hit.corroboration_basis) for hit in hits] == [(True, basis)]


def test_app_011_is_the_override_case_and_stays_unconfirmed(packets):
    """DOB 1980-06-20 against -21 and PL against BY: both comparable, both disagreeing, nothing agrees."""
    hits = sweep(targets_of(packets["APP-011"]), MIN_SCORE).hits

    assert [(hit.entry_id, hit.hit_type, hit.corroborated) for hit in hits] == [("EU-2001", "sanctions", False)]
