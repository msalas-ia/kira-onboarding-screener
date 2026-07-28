"""The naive agent: it carries the base heuristic the policy permits, proposes a decision, and is then overruled."""

from agent.constants import BASE_HEURISTIC_PROMPT
from agent.llm import ModelUnavailable, StructuredClient
from agent.schemas import Brain, Facts, Proposal, ScreeningTarget, Usage


class ProposalUnavailable(RuntimeError):
    """No proposal could be obtained. The verdict does not depend on one, so the run continues without it."""


def propose(
    brain: Brain, facts: Facts, targets: list[ScreeningTarget], client: StructuredClient
) -> tuple[Proposal, Usage]:
    """One call carrying the Brain's `base_heuristic` prompt (D-007), over facts and hits — never policy or documents."""
    try:
        completion = client.parse(
            system=[{"type": "text", "text": brain.prompt(BASE_HEURISTIC_PROMPT)}],
            messages=[{"role": "user", "content": render_case(facts, targets)}],
            output_format=Proposal,
        )
    except ModelUnavailable as exc:
        raise ProposalUnavailable(str(exc)) from exc

    return completion.parsed, completion.usage


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

    # The tool's own output and nothing else. `corroborated` is a conclusion the
    # policy defines, so showing it here would leak the rule table into the step
    # that is supposed to reason without one. (D-010)
    lines.append("<watchlist_results>")
    for hit in facts.hits:
        lines.append(
            f"{hit.subject_ref} matched {hit.entry_id} (type={hit.hit_type}, name_score={hit.name_score:.3f})"
        )
    if not facts.hits:
        lines.append("(no name reached the match threshold)")
    lines.append("</watchlist_results>")
    return "\n".join(lines)


def _flag(value: bool) -> str:
    return "true" if value else "false"
