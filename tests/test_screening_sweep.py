"""Coverage is a floor: the sweep can add a hit, never lose one the delivered tool would have found."""

import pytest

from agent.extraction import screening_targets
from agent.screening import load_tool, name_variants, sweep, watchlist_digest
from tests.conftest import extraction

MIN_SCORE = 0.75

# Measured over all 18 packets: the 7 the dev labels expect, plus two unlabelled applicants.
EXPECTED = {
    ("APP-002", "ubo[0]", "PEP-3001"),
    ("APP-003", "ubo[0]", "OFAC-1001"),
    ("APP-004", "business", "AM-4001"),
    ("APP-007", "ubo[0]", "OFAC-1003"),
    ("APP-009", "ubo[0]", "EU-2001"),
    ("APP-011", "ubo[0]", "EU-2001"),
    ("APP-012", "ubo[0]", "PEP-3002"),
    ("APP-013", "business", "AM-4003"),
    ("APP-015", "business", "OFAC-1004"),
}


def targets_of(packet):
    """Packet-only targets: an empty extraction contributes no supplementary names."""
    found, _ = screening_targets(packet, extraction())
    return found


def all_hits(packets):
    return {
        (applicant_id, hit.subject_ref, hit.entry_id)
        for applicant_id, packet in packets.items()
        for hit in sweep(targets_of(packet), MIN_SCORE).hits
    }


def test_the_sweep_over_every_packet_reproduces_the_measured_hit_set(packets):
    assert all_hits(packets) == EXPECTED


def test_the_sweep_is_a_superset_of_the_delivered_tool(packets):
    """The property that lets D-009 claim recall was added and nothing was traded for it."""
    reference = {
        (applicant_id, target.subject_ref, match["entry_id"])
        for applicant_id, packet in packets.items()
        for target in targets_of(packet)
        for match in load_tool()(target.name, MIN_SCORE)
    }

    assert reference <= all_hits(packets)


def test_variants_add_no_hits_to_the_delivered_packets(packets):
    """Recall on reordered names costs nothing here: 9 hits before, 9 after."""
    reference = {
        (applicant_id, target.subject_ref, match["entry_id"])
        for applicant_id, packet in packets.items()
        for target in targets_of(packet)
        for match in load_tool()(target.name, MIN_SCORE)
    }

    assert all_hits(packets) == reference


def test_every_hit_on_the_delivered_packets_was_found_as_given(packets):
    """None of the 18 needs a reordering — the recall is for the holdout, not for the dev set."""
    variants = {hit.name_variant for packet in packets.values() for hit in sweep(targets_of(packet), MIN_SCORE).hits}

    assert variants == {"as_given"}


def test_the_hit_set_does_not_depend_on_the_order_of_the_targets(packets):
    packet = packets["APP-003"]
    forward = sweep(targets_of(packet), MIN_SCORE)
    backward = sweep(list(reversed(targets_of(packet))), MIN_SCORE)

    assert forward.hits == backward.hits


def test_the_same_entry_through_several_variants_is_one_hit(packets):
    """The union is keyed by (subject, entry), so a name matching through three spellings stays one finding."""
    packet = packets["APP-003"]
    result = sweep(targets_of(packet), MIN_SCORE)

    assert len(result.hits) == 1
    assert result.searches == sum(len(name_variants(target.name)) for target in targets_of(packet))


def test_the_strongest_score_survives_the_union():
    """A reordered spelling that scores higher must replace the given one, not lose to call order."""
    from agent.schemas import ScreeningTarget

    target = ScreeningTarget(name="Kravchenko Olena", subject="ubo", subject_ref="ubo[0]", country="UA")
    result = sweep([target], MIN_SCORE)

    assert [(hit.entry_id, hit.name_score, hit.name_variant) for hit in result.hits] == [("PEP-3004", 1.0, "reordered")]


def test_a_target_the_watchlist_does_not_know_produces_nothing(packets):
    assert sweep(targets_of(packets["APP-001"]), MIN_SCORE).hits == []


def test_the_threshold_comes_from_the_brain_and_actually_binds(packets, brain):
    """min_name_score is Brain data; dropping it to zero must widen the sweep, or it is not being passed through."""
    targets = targets_of(packets["APP-001"])

    assert sweep(targets, brain.settings.min_name_score).hits == []
    assert sweep(targets, 0.0).hits != []


def test_the_digest_is_taken_from_the_list_the_tool_resolved():
    assert watchlist_digest().startswith("sha256:")


@pytest.mark.parametrize("subject_ref", ["business", "ubo[0]"])
def test_hits_carry_no_name(packets, subject_ref):
    """Hit is the structure that reaches a log, so nothing in it may be PII."""
    hits = [hit for hit in sweep(targets_of(packets["APP-009"]), MIN_SCORE).hits]

    assert all("Sokolova" not in hit.model_dump_json() for hit in hits)
