"""The prose is authoritative and the table is what executes, so they must agree."""

import re

import yaml

from agent.constants import POLICY_FILE, RULES_FILE
from tests.conftest import REPO_BRAIN

DECISION = re.compile(r"\b(BLOCK|REVIEW|CLEAR)\b")
NUMBERED_RULE = re.compile(r"^(\d+)\.\s+(.*)$")
RULE_WITHOUT_AN_ENTRY = 9
PROSE_MATRIX = {1: "BLOCK", 2: "REVIEW", 3: "REVIEW", 4: "REVIEW", 5: "REVIEW", 6: "REVIEW", 7: "REVIEW", 8: "CLEAR", 9: "CLEAR"}


def _matrix_from_prose() -> dict[int, str]:
    """Parse the decision matrix out of the authoritative markdown."""
    text = (REPO_BRAIN / "versions" / "v1" / POLICY_FILE).read_text(encoding="utf-8")
    section = text.split("## Decision matrix", 1)[1].split("\n## ", 1)[0]

    matrix: dict[int, str] = {}
    for line in section.splitlines():
        numbered = NUMBERED_RULE.match(line.strip())
        if not numbered or "→" not in numbered.group(2):
            continue
        outcome = DECISION.search(numbered.group(2).split("→", 1)[1])
        if outcome:
            matrix[int(numbered.group(1))] = outcome.group(1)
    return matrix


def test_the_prose_matrix_was_parsed_at_all():
    """Guards the test itself: a silent parse failure would make the next one vacuous."""
    assert _matrix_from_prose() == PROSE_MATRIX


def test_every_prose_rule_has_a_table_entry_with_the_same_decision():
    """Rule 9 is the one deliberate omission, recorded in D-005."""
    document = yaml.safe_load((REPO_BRAIN / "versions" / "v1" / RULES_FILE).read_text(encoding="utf-8"))
    table = {rule["id"]: rule["decision"] for rule in document["rules"]}

    expected = {rule: decision for rule, decision in PROSE_MATRIX.items() if rule != RULE_WITHOUT_AN_ENTRY}

    assert table == expected
