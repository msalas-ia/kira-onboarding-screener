"""Every way a Brain can be wrong, with the same assertion each time: it fails loudly instead of degrading."""

import copy
import re
from datetime import date
from pathlib import Path

import pytest

from agent.brain import BrainInvalid, BrainUnavailable, load_brain, load_version, read_pointer
from agent.constants import POINTER_FILE, RULES_FILE

WALL_CLOCK = re.compile(r"\b(datetime\.now|date\.today|time\.time|utcnow)\b")


def test_the_shipped_policy_loads(brain):
    assert brain.version == "v1"
    assert brain.settings.min_name_score == 0.75
    assert [rule.id for rule in brain.rules] == [1, 2, 3, 4, 5, 6, 7, 8]


def test_the_evaluation_date_is_policy_data(brain):
    assert brain.settings.as_of_date == date(2026, 7, 27)
    assert brain.settings.formation_recent_days == 90


def test_no_decision_path_reads_the_wall_clock():
    """Rule 7 depends on company age; from now() the same applicant would decide differently on a different day."""
    offenders = [
        path.name
        for path in sorted(Path("agent").glob("*.py"))
        if WALL_CLOCK.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == []


def test_the_hash_covers_the_prose_and_the_table_together(brain, make_brain_dir, v1_document):
    changed = copy.deepcopy(v1_document)
    changed["settings"]["min_name_score"] = 0.9

    other = load_version(make_brain_dir(changed, version="edited"), "edited")

    assert other.brain_hash != brain.brain_hash


def test_a_rule_naming_an_undeclared_fact_is_rejected(v1_document, make_brain_dir):
    v1_document["rules"].append(
        {"id": 99, "when": {"risk_vibes": "high"}, "decision": "REVIEW", "confidence": 0.5, "cite": "x"}
    )

    with pytest.raises(BrainInvalid, match="undeclared fact 'risk_vibes'"):
        load_brain(make_brain_dir(v1_document))


def test_a_rule_using_an_unknown_operator_is_rejected(v1_document, make_brain_dir):
    v1_document["rules"].append(
        {"id": 99, "when": {"mcc": {"matches": "60.*"}}, "decision": "REVIEW", "confidence": 0.5, "cite": "x"}
    )

    with pytest.raises(BrainInvalid, match="unknown operator 'matches'"):
        load_brain(make_brain_dir(v1_document))


def test_a_duplicate_rule_id_is_rejected(v1_document, make_brain_dir):
    v1_document["rules"].append(copy.deepcopy(v1_document["rules"][0]))

    with pytest.raises(BrainInvalid, match="duplicate id"):
        load_brain(make_brain_dir(v1_document))


def test_a_confidence_outside_the_unit_interval_is_rejected(v1_document, make_brain_dir):
    v1_document["rules"][0]["confidence"] = 1.4

    with pytest.raises(BrainInvalid, match=r"confidence 1.4 outside"):
        load_brain(make_brain_dir(v1_document))


def test_a_policy_with_no_default_rule_is_rejected(v1_document, make_brain_dir):
    v1_document["rules"] = [rule for rule in v1_document["rules"] if rule["when"]]

    with pytest.raises(BrainInvalid, match="exactly one default rule"):
        load_brain(make_brain_dir(v1_document))


def test_a_default_rule_that_does_not_clear_is_rejected(v1_document, make_brain_dir):
    v1_document["rules"][-1]["decision"] = "BLOCK"

    with pytest.raises(BrainInvalid, match="default rule must decide CLEAR"):
        load_brain(make_brain_dir(v1_document))


def test_a_required_document_pointing_at_a_non_boolean_fact_is_rejected(v1_document, make_brain_dir):
    v1_document["settings"]["required_documents"].append({"id": "audit", "satisfied_by": "mcc"})

    with pytest.raises(BrainInvalid, match="not a declared boolean fact"):
        load_brain(make_brain_dir(v1_document))


def test_a_version_that_disagrees_with_its_directory_is_rejected(v1_document, make_brain_dir):
    """The directory name is the version; a table claiming otherwise is not activatable."""
    brain_dir = make_brain_dir(v1_document, version="v3")
    table = brain_dir / "versions" / "v3" / RULES_FILE
    table.write_text(table.read_text().replace("policy_version: v3", "policy_version: v7"))

    with pytest.raises(BrainInvalid, match="does not match directory"):
        load_version(brain_dir, "v3")


def test_a_pointer_to_a_version_that_is_not_there_fails_readiness(tmp_path):
    (tmp_path / POINTER_FILE).write_text('{"active_version": "v9"}')

    with pytest.raises(BrainUnavailable, match="v9"):
        load_brain(tmp_path)


def test_a_missing_volume_fails_readiness(tmp_path):
    with pytest.raises(BrainUnavailable, match="pointer file not found"):
        load_brain(tmp_path)


def test_the_pointer_is_read_fresh_so_a_swap_needs_no_restart(v1_document, make_brain_dir):
    brain_dir = make_brain_dir(v1_document, version="v1")
    assert read_pointer(brain_dir).active_version == "v1"

    (brain_dir / POINTER_FILE).write_text('{"active_version": "v2"}')

    assert read_pointer(brain_dir).active_version == "v2"
