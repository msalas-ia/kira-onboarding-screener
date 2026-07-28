"""The naive agent: it carries the base heuristic the policy permits, searches what it likes, and is then overruled."""

import time
from dataclasses import dataclass, field
from typing import Any, Literal

from agent.constants import BASE_HEURISTIC_PROMPT
from agent.llm import ModelUnavailable, StructuredClient, ToolCall
from agent.pricing import total_usage
from agent.schemas import (
    Brain,
    Facts,
    Hit,
    Proposal,
    ScreeningTarget,
    SearchOutcome,
    SearchRecord,
    Usage,
)
from agent.screening import Search, sweep

Budget = Literal["within", "steps_exhausted", "time_exhausted"]

WATCHLIST_TOOL_SPEC: dict[str, Any] = {
    "name": "watchlist_search",
    "description": (
        "Search the sanctions, PEP and adverse-media watchlist for one name. The names in the case were "
        "already searched as written and in every token order, so repeating those returns nothing new. "
        "Use this for a spelling those cannot reach: a transliteration, a form without diacritics, an "
        "initial in place of a given name, a maiden or married surname."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "The single name to search for."}},
        "required": ["name"],
    },
}


class ProposalUnavailable(RuntimeError):
    """No proposal could be obtained. The verdict does not depend on one, so the run continues without it."""


@dataclass(frozen=True)
class Adjudication:
    """What the naive agent produced: its answer, the hits its searching added, and what the whole turn cost."""

    proposal: Proposal | None
    hits: tuple[Hit, ...] = ()
    searches: tuple[SearchRecord, ...] = ()
    usage: Usage = field(default_factory=Usage)
    steps: int = 0
    budget: Budget = "within"


def propose(
    brain: Brain,
    facts: Facts,
    targets: list[ScreeningTarget],
    client: StructuredClient,
    *,
    max_steps: int,
    deadline: float | None = None,
    search: Search | None = None,
) -> Adjudication:
    """The bounded loop. The model returns names; the deterministic sweep executes them and keeps the scores. (D-011)"""
    system = [{"type": "text", "text": brain.prompt(BASE_HEURISTIC_PROMPT)}]
    messages: list[dict[str, Any]] = [{"role": "user", "content": render_case(facts, targets)}]

    usage = Usage()
    searches: list[SearchRecord] = []
    found: dict[tuple[str, str], Hit] = {}
    budget: Budget = "within"
    steps = 0

    while steps < max_steps:
        if deadline is not None and time.monotonic() >= deadline:
            budget = "time_exhausted"
            break

        steps += 1
        try:
            completion = client.parse(
                system=system, messages=messages, output_format=Proposal, tools=[WATCHLIST_TOOL_SPEC]
            )
        except ModelUnavailable as exc:
            raise ProposalUnavailable(str(exc)) from exc

        usage = total_usage(usage, completion.usage)
        if completion.parsed is not None:
            return Adjudication(completion.parsed, _ordered(found), tuple(searches), usage, steps, budget)
        if not completion.tool_calls:
            break

        messages.append({"role": "assistant", "content": completion.content})
        results = []
        for call in completion.tool_calls:
            record, hits = _run(call, len(searches), brain.settings.min_name_score, search)
            searches.append(record)
            for hit in hits:
                key = (hit.subject_ref, hit.entry_id)
                if key not in found or hit.name_score > found[key].name_score:
                    found[key] = hit
            results.append({"type": "tool_result", "tool_use_id": call.id, "content": _render_result(record)})
        messages.append({"role": "user", "content": results})
    else:
        budget = "steps_exhausted"

    return Adjudication(None, _ordered(found), tuple(searches), usage, steps, budget)


def _run(call: ToolCall, ordinal: int, min_score: float, search: Search | None) -> tuple[SearchRecord, list[Hit]]:
    """One model-initiated search, executed by the same sweep as every other one — same variants, same threshold."""
    name = call.arguments.get("name")
    if not isinstance(name, str) or not name.strip():
        return SearchRecord(ordinal=ordinal, tokens=0, accepted=False), []

    # One ref for every spelling, not one per call: an arrival-ordered ref would
    # make the same two searches in a different order a different verdict.
    target = ScreeningTarget(name=name.strip(), subject="proposed", subject_ref="proposed", source="proposed")
    hits = sweep([target], min_score, search).hits
    record = SearchRecord(
        ordinal=ordinal,
        tokens=len(name.split()),
        accepted=True,
        entries=[SearchOutcome(entry_id=hit.entry_id, name_score=hit.name_score) for hit in hits],
    )
    return record, hits


def _render_result(record: SearchRecord) -> str:
    """What the model is told back. It knows the name it sent; the trace is where the name must not go."""
    if not record.accepted:
        return "That call had no usable `name`. Send a single name as a string."
    if not record.entries:
        return "No watchlist entry matched at or above the threshold."
    return "\n".join(f"{entry.entry_id} matched at {entry.name_score:.3f}" for entry in record.entries)


def _ordered(found: dict[tuple[str, str], Hit]) -> tuple[Hit, ...]:
    """Sorted by the same key the sweep uses, so a run's hits do not depend on which search happened first."""
    return tuple(found[key] for key in sorted(found))


def render_case(facts: Facts, targets: list[ScreeningTarget]) -> str:
    """The case as the naive agent sees it: no rule table, so it cannot borrow the answer, and no free text (D-010)."""
    lines = [
        "<applicant_facts>",
        f"mcc: {facts.mcc or 'unknown'}",
        f"has_incorporation_doc: {_flag(facts.has_incorporation_doc)}",
        f"has_ubo_list: {_flag(facts.has_ubo_list)}",
        f"formation_age_days: {facts.formation_age_days if facts.formation_age_days is not None else 'unknown'}",
        f"shell_signals: {', '.join(facts.shell_signals) or 'none'}",
        f"documents_contained_instructions: {_flag(facts.injection_suspected)}",
        "</applicant_facts>",
        "<names_searched>",
    ]
    for target in targets:
        lines.append(f"{target.subject_ref}: {target.name}")
    lines.append("</names_searched>")

    # `corroborated` is a conclusion the policy defines, so showing it would leak
    # the rule table into the step built to reason without one. (D-010)
    lines.append("<watchlist_results>")
    for hit in facts.hits:
        lines.append(f"{hit.subject_ref} matched {hit.entry_id} (type={hit.hit_type}, name_score={hit.name_score:.3f})")
    if not facts.hits:
        lines.append("(no name reached the match threshold)")
    lines.append("</watchlist_results>")
    return "\n".join(lines)


def _flag(value: bool) -> str:
    return "true" if value else "false"
