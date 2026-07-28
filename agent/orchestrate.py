"""The composition. Every step is a pure function elsewhere; the order they run in lives only here."""

import logging
import time
from typing import Literal

from agent.extraction import extract
from agent.facts import from_packet
from agent.guardrails import assert_no_auto_clear
from agent.llm import StructuredClient
from agent.pricing import cost_of, total_usage
from agent.proposal import ProposalUnavailable, propose
from agent.rules import evaluate
from agent.schemas import (
    Applicant,
    Brain,
    CaseFile,
    EvaluateTrace,
    ExtractionResult,
    ExtractTrace,
    Facts,
    OverrideTrace,
    ProposeTrace,
    RunTrace,
    ScreeningTarget,
    ScreenTrace,
    Usage,
    Verdict,
)
from agent.screening import sweep, watchlist_digest

log = logging.getLogger(__name__)

NEVER_AUTO_CLEAR = "never_auto_clear"


def screen(
    packet: Applicant,
    brain: Brain,
    client: StructuredClient,
    *,
    run_id: str,
    model: str,
) -> tuple[CaseFile, RunTrace]:
    """One packet in, one case file and one trace out; `run_id` is supplied so nothing here needs a random source."""
    started = time.perf_counter()

    mark = time.perf_counter()
    extraction = extract(packet, brain, client)
    extract_trace = _extract_trace(extraction, _since(mark), model)

    mark = time.perf_counter()
    facts = from_packet(packet, extraction, brain.settings)
    screening = sweep(extraction.screening_targets, brain.settings.min_name_score)
    facts.hits = screening.hits
    screen_trace = ScreenTrace(duration_ms=_since(mark), searches=screening.searches, hits=screening.hits)

    mark = time.perf_counter()
    verdict = evaluate(brain, facts)
    evaluations = [_evaluate_trace("initial", verdict, _since(mark))]

    propose_trace = _propose(brain, facts, extraction.screening_targets, client, model)

    assert_no_auto_clear(facts, verdict)

    watchlist_hash = watchlist_digest()
    usage = total_usage(extraction.usage, propose_trace.usage)
    trace = RunTrace(
        run_id=run_id,
        applicant_id=packet.applicant_id,
        policy_version=brain.version,
        brain_hash=brain.brain_hash,
        watchlist_hash=watchlist_hash,
        model=model,
        duration_ms=_since(started),
        usage=usage,
        cost_usd=cost_of(usage, model),
        extract=extract_trace,
        screen=screen_trace,
        evaluate=evaluations,
        propose=propose_trace,
        override=OverrideTrace(
            proposed=propose_trace.decision,
            final=verdict.decision,
            overridden=propose_trace.decision is not None and propose_trace.decision != verdict.decision,
            deciding_rules=verdict.fired_rules,
        ),
        guardrails_passed=[NEVER_AUTO_CLEAR],
    )
    return case_file(packet.applicant_id, verdict, watchlist_hash, run_id), trace


def _propose(
    brain: Brain,
    facts: Facts,
    targets: list[ScreeningTarget],
    client: StructuredClient,
    model: str,
) -> ProposeTrace:
    """The naive proposal, recorded beside the verdict. A run that cannot get one is degraded, never wrong."""
    mark = time.perf_counter()
    try:
        proposal, usage = propose(brain, facts, targets, client)
    except ProposalUnavailable as exc:
        log.warning("no proposal recorded: %s", exc)
        return ProposeTrace(outcome="unavailable", duration_ms=_since(mark), usage=Usage(), cost_usd=0.0)

    return ProposeTrace(
        outcome="proposed",
        duration_ms=_since(mark),
        usage=usage,
        cost_usd=cost_of(usage, model),
        decision=proposal.decision,
        confidence=proposal.confidence,
        cited_entries=proposal.cited_entries,
    )


def case_file(applicant_id: str, verdict: Verdict, watchlist_hash: str, run_id: str) -> CaseFile:
    """The verdict addressed to a caller: the policy's contract, plus what state produced it."""
    return CaseFile(
        applicant_id=applicant_id,
        watchlist_hash=watchlist_hash,
        run_id=run_id,
        requires_human_review=verdict.decision != "CLEAR",
        **verdict.model_dump(exclude={"fired_rules"}),
    )


def _extract_trace(extraction: ExtractionResult, duration_ms: int, model: str) -> ExtractTrace:
    """What extraction produced, by shape: counts, kinds and refs, never a name or a quoted span."""
    usage = extraction.usage or Usage()
    return ExtractTrace(
        duration_ms=duration_ms,
        usage=usage,
        cost_usd=cost_of(usage, model),
        retries=extraction.retries,
        document_kinds=extraction.document_kinds,
        shell_signals=extraction.shell_signals,
        target_refs=[target.subject_ref for target in extraction.screening_targets],
        supplementary_targets=sum(1 for target in extraction.screening_targets if target.source == "document"),
        dropped_targets=extraction.dropped_targets,
        injection_suspected=extraction.injection_suspected,
    )


def _evaluate_trace(phase: Literal["initial", "final"], verdict: Verdict, duration_ms: int) -> EvaluateTrace:
    return EvaluateTrace(
        phase=phase,
        duration_ms=duration_ms,
        decision=verdict.decision,
        confidence=verdict.confidence,
        fired_rules=verdict.fired_rules,
    )


def _since(mark: float) -> int:
    """Elapsed milliseconds from a monotonic mark. A duration is not a clock reading, so Rule 7 stays date-pinned."""
    return round((time.perf_counter() - mark) * 1000)
