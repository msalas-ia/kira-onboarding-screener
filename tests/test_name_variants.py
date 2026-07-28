"""Recall is bought with more calls to the delivered tool, never with a new matcher. (D-009)"""

import pytest

from agent.screening import load_tool, name_variants

# Every one of these is a sanctions or PEP entity that screens clean on a single raw-name call.
REORDERED = [
    ("Kravchenko Olena", "PEP-3004"),
    ("Petrov Viktor", "OFAC-1001"),
    ("Sokolova Ivanka", "EU-2001"),
    ("Al-Rashid Muhammad", "OFAC-1003"),
    ("Okafor Adaeze", "PEP-3002"),
    ("Rivas Carlos Mendoza", "PEP-3001"),
]


@pytest.mark.parametrize("name,entry_id", REORDERED)
def test_the_delivered_tool_misses_a_reordered_name(name, entry_id):
    """The premise of D-009: without variants each of these is a false clear."""
    assert load_tool()(name) == []


@pytest.mark.parametrize("name,entry_id", REORDERED)
def test_a_variant_recovers_it_at_full_score(name, entry_id):
    scores = {
        match["entry_id"]: match["score"] for variant in name_variants(name) for match in load_tool()(variant)
    }

    assert scores.get(entry_id) == 1.0


def test_the_name_as_given_is_always_the_first_variant():
    """The union keeps the first of equal scores, so the given spelling has to win ties."""
    assert name_variants(" Viktor   Petrov ")[0] == "Viktor Petrov"


def test_variants_are_a_pure_function_of_the_string():
    assert name_variants("Olena Kravchenko") == name_variants("Olena Kravchenko")
    assert name_variants("olena kravchenko") != name_variants("Olena Kravchenko")


def test_a_single_token_has_nothing_to_reorder():
    assert name_variants("Sokolova") == ("Sokolova",)


def test_an_empty_name_produces_no_searches():
    assert name_variants("   ") == ()


def test_long_names_keep_the_given_order_and_the_reverse_only():
    """Permuting a four-token company name is 24 calls for nothing; the count stays linear."""
    variants = name_variants("Grupo Delta Naviera S.A.")

    assert variants == ("Grupo Delta Naviera S.A.", "S.A. Naviera Delta Grupo")


def test_three_tokens_are_fully_permuted():
    assert len(name_variants("Carlos Mendoza Rivas")) == 6
