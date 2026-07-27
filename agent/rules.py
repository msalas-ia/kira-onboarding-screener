"""The generic evaluator: one pure function over (Brain, Facts), with no I/O, clock, randomness or global state."""

from dataclasses import dataclass
from typing import Any

from agent.constants import SEVERITY
from agent.facts import applicant_bag, hit_bag
from agent.schemas import Brain, Facts, Hit, MatchedEntity, Rule, Verdict


@dataclass(frozen=True)
class Finding:
    """One rule that fired, against one subject."""

    rule: Rule
    subject_ref: str | None
    hit: Hit | None
    evidence: tuple[tuple[str, Any], ...]

    @property
    def sort_key(self) -> tuple[int, int, str, str]:
        """Severity, then the policy's numbering, then a tiebreak that ignores arrival order."""
        return (
            -SEVERITY[self.rule.decision],
            self.rule.id,
            self.subject_ref or "",
            self.hit.entry_id if self.hit else "",
        )


def evaluate(brain: Brain, facts: Facts) -> Verdict:
    """Apply the Brain to one applicant's facts."""
    base = applicant_bag(facts, brain.settings)

    findings: list[Finding] = []
    for rule in brain.rules:
        if rule.scope == "each_hit":
            for hit in facts.hits:
                bag = base | hit_bag(hit)
                if _matches(rule.when, bag):
                    findings.append(Finding(rule, hit.subject_ref, hit, _quote(rule, bag)))
        elif _matches(rule.when, base):
            findings.append(Finding(rule, None, None, _quote(rule, base)))

    findings.sort(key=lambda finding: finding.sort_key)
    reported = [finding for finding in findings if finding.rule.when] or findings

    decision = reported[0].rule.decision if reported else "REVIEW"
    confidence = min(
        (finding.rule.confidence for finding in reported if finding.rule.decision == decision),
        default=0.0,
    )

    return Verdict(
        decision=decision,
        confidence=confidence,
        reasons=[_reason(finding) for finding in reported],
        matched_entities=_matched_entities(reported),
        missing_docs=list(base["missing_docs"]),
        policy_version=brain.version,
        fired_rules=sorted({finding.rule.id for finding in reported}),
        brain_hash=brain.brain_hash,
    )


def _matches(when: dict[str, Any], bag: dict[str, Any]) -> bool:
    """All conditions must hold; an empty `when` is the default rule and always matches."""
    return all(_holds(bag.get(name), condition) for name, condition in when.items())


def _holds(value: Any, condition: Any) -> bool:
    """Evaluate one condition; a fact with no value satisfies nothing, including `ne`."""
    if value is None:
        return False
    if not isinstance(condition, dict):
        return bool(value == condition)

    ((operator, operand),) = condition.items()
    if operator == "in":
        return value in operand
    if operator == "ne":
        return value != operand
    if operator in ("gte", "lte") and isinstance(value, (int, float)) and not isinstance(value, bool):
        return value >= operand if operator == "gte" else value <= operand
    return False


def _quote(rule: Rule, bag: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
    """Pull the facts the rule asked to have quoted in its reason."""
    return tuple((name, bag.get(name)) for name in rule.evidence)


def _reason(finding: Finding) -> str:
    """Render a finding as a citation of the rule and the evidence behind it."""
    text = f"Rule {finding.rule.id} — {finding.rule.cite}"
    if finding.subject_ref:
        text += f" ({finding.subject_ref})"
    if finding.evidence:
        text += ": " + ", ".join(f"{name}={_render(value)}" for name, value in finding.evidence)
    return text


def _render(value: Any) -> str:
    """Format a fact value stably, so the same facts always spell the same reason."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return str(round(value, 3))
    if isinstance(value, list):
        return "[" + ", ".join(_render(item) for item in value) + "]"
    return str(value)


def _matched_entities(findings: list[Finding]) -> list[MatchedEntity]:
    """The watchlist entries behind the findings, deduplicated and ordered."""
    seen: dict[tuple[str, str], MatchedEntity] = {}
    for finding in findings:
        hit = finding.hit
        if hit is None:
            continue
        seen.setdefault(
            (hit.entry_id, hit.subject_ref),
            MatchedEntity(
                entry_id=hit.entry_id,
                hit_type=hit.hit_type,
                subject_ref=hit.subject_ref,
                name_score=hit.name_score,
                corroborated=hit.corroborated,
            ),
        )
    return [seen[key] for key in sorted(seen)]
