"""The override as a comparison between two policy versions: same packet, same facts, two rule tables. (D-015)"""

from dataclasses import dataclass
from typing import Literal

from agent.extraction import floor_of, merge
from agent.facts import from_packet
from agent.guardrails import GuardrailViolated, assert_no_auto_clear
from agent.rules import evaluate
from agent.schemas import Applicant, Brain, BrainSettings, Extraction, Facts
from agent.screening import sweep

NAIVE_VERSION = "v0-naive"
OVERRIDE_CASE = "APP-011"


@dataclass(frozen=True)
class AblationRow:
    """One applicant under both policies, and whether the guardrail would refuse the naive verdict."""

    applicant_id: str
    live: str
    live_rules: tuple[int, ...]
    naive: str
    naive_rules: tuple[int, ...]
    guardrail: Literal["passes", "raises"]

    @property
    def disagrees(self) -> bool:
        return self.live != self.naive


def facts_of(packet: Applicant, settings: BrainSettings) -> Facts:
    """The facts bag with no model involved: the deterministic floor, then the unconditional sweep."""
    extraction = merge(packet, floor_of(packet), Extraction(documents=[], shell_signals=[], names=[], contains_instructions=False))
    facts = from_packet(packet, extraction, settings)
    facts.hits = sweep(extraction.screening_targets, settings.min_name_score).hits
    return facts


def compare(packets: dict[str, Applicant], live: Brain, naive: Brain) -> list[AblationRow]:
    """One facts bag per applicant, evaluated twice. No model, no network, no cost."""
    if live.settings != naive.settings:
        raise ValueError("the two versions disagree on settings, so a difference would not isolate the rule table")

    rows = []
    for applicant_id in sorted(packets):
        facts = facts_of(packets[applicant_id], live.settings)
        under_live = evaluate(live, facts)
        under_naive = evaluate(naive, facts)
        rows.append(
            AblationRow(
                applicant_id=applicant_id,
                live=under_live.decision,
                live_rules=tuple(under_live.fired_rules),
                naive=under_naive.decision,
                naive_rules=tuple(under_naive.fired_rules),
                guardrail=_guardrail(facts, under_naive),
            )
        )
    return rows


def override_demonstrated(rows: list[AblationRow]) -> bool:
    """The designated case: cleared by the naive table, reviewed by the live one."""
    return any(row.applicant_id == OVERRIDE_CASE and row.naive == "CLEAR" and row.live == "REVIEW" for row in rows)


def _guardrail(facts: Facts, verdict) -> Literal["passes", "raises"]:
    try:
        assert_no_auto_clear(facts, verdict)
    except GuardrailViolated:
        return "raises"
    return "passes"
