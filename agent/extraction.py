"""Free text in, facts out: the model reads the documents, a deterministic floor reads the same packet, and the merge is a union. (D-008)"""

import re
from typing import Any

from agent.constants import (
    EXTRACTION_PROMPT,
    INCORPORATION_DOCUMENT_TYPES,
    MAX_SUPPLEMENTARY_NAMES,
    SHELL_SIGNAL_MASS_REGISTRATION,
    SHELL_SIGNAL_NOMINEE_DIRECTOR,
)
from agent.llm import ModelUnavailable, StructuredClient
from agent.schemas import (
    Applicant,
    Brain,
    Extraction,
    ExtractionResult,
    Floor,
    ScreeningTarget,
    Usage,
)


class ExtractionFailed(RuntimeError):
    """The packet could not be extracted; there is no partial result."""


NOMINEE = re.compile(r"\bnominee\b", re.IGNORECASE)
MASS_REGISTRATION = re.compile(
    r"""
      shared \s+ by \s+ \d[\d,]*\+? \s* (?:entities|companies|firms|businesses)
    | \b\d[\d,]*\+? \s+ (?:entities|companies) \s+ (?:registered|share)
    | mass[\s-]registration
    | registered \s+ agent \s+ address
    | virtual \s+ office
    | \b shared \s+ (?:office|address|premises) \b
    """,
    re.IGNORECASE | re.VERBOSE,
)
INSTRUCTION = re.compile(
    r"""
      \b ignore \s+ (?:all \s+)? (?:previous|prior|above|earlier) \s+ instructions
    | \b disregard \s+ (?:all \s+)? (?:previous|prior|above|earlier)
    | \b system \s+ note \b
    | \b output \s+ (?:the \s+)? decision \b
    | \b decision \s* = \s* (?:CLEAR|REVIEW|BLOCK) \b
    | \b pre-? approved \b
    | \b do \s+ not \s+ flag \b
    | \b override \s+ (?:the \s+)? (?:policy|watchlist|screening) \b
    """,
    re.IGNORECASE | re.VERBOSE,
)

WHITESPACE = re.compile(r"\s+")


def floor_of(packet: Applicant) -> Floor:
    """What the packet yields with no model involved; suppressing a finding means fooling this, not the model."""
    incorporation = [
        index
        for index, document in enumerate(packet.documents)
        if document.type.strip().lower() in INCORPORATION_DOCUMENT_TYPES
    ]

    signals: set[str] = set()
    instructed = False

    for ubo in packet.ubos:
        if ubo.role and NOMINEE.search(ubo.role):
            signals.add(SHELL_SIGNAL_NOMINEE_DIRECTOR)

    for document in packet.documents:
        content = document.content
        if NOMINEE.search(content):
            signals.add(SHELL_SIGNAL_NOMINEE_DIRECTOR)
        if MASS_REGISTRATION.search(content):
            signals.add(SHELL_SIGNAL_MASS_REGISTRATION)
        if INSTRUCTION.search(content):
            instructed = True

    return Floor(
        incorporation_indices=incorporation,
        shell_signals=sorted(signals),
        contains_instructions=instructed,
    )


def extract(packet: Applicant, brain: Brain, client: StructuredClient) -> ExtractionResult:
    """One model call, anchored and then unioned with the floor; fails closed, because an empty extraction is unsafe."""
    system = system_blocks(brain)
    messages: list[dict[str, Any]] = [{"role": "user", "content": render_packet(packet)}]

    for attempt in range(2):
        try:
            completion = client.parse(system=system, messages=messages, output_format=Extraction)
        except ModelUnavailable as exc:
            raise ExtractionFailed(f"{packet.applicant_id}: {exc}") from exc

        extraction: Extraction = completion.parsed
        problems = validate_anchors(extraction, packet)
        if not problems:
            return merge(packet, floor_of(packet), extraction, usage=completion.usage)

        if attempt == 0:
            messages = [
                *messages,
                {"role": "assistant", "content": extraction.model_dump_json()},
                {"role": "user", "content": _correction(problems)},
            ]

    raise ExtractionFailed(f"{packet.applicant_id}: unanchored extraction after one retry: " + "; ".join(problems))


def system_blocks(brain: Brain) -> list[dict[str, Any]]:
    """The extraction prompt and the authoritative policy, both Brain artifacts, as one cacheable prefix. (D-007)"""
    return [
        {"type": "text", "text": brain.prompt(EXTRACTION_PROMPT)},
        {
            "type": "text",
            "text": "# Reference: the compliance policy this feeds\n\n" + brain.policy_text,
            "cache_control": {"type": "ephemeral"},
        },
    ]


def render_packet(packet: Applicant) -> str:
    """Frame the packet as delimited, numbered data that cannot close its own delimiter."""
    business = packet.business
    lines = [
        f'<applicant id="{packet.applicant_id}">',
        "<business_fields>",
        f"legal_name: {business.legal_name}",
        f"registration_country: {business.registration_country or 'unknown'}",
        f"address: {business.address.line or 'unknown'} ({business.address.country or 'unknown'})",
        f"activity: {business.activity or 'unknown'}",
        f"mcc: {business.mcc or 'unknown'}",
        f"incorporation_date: {business.incorporation_date or 'unknown'}",
        "</business_fields>",
        "<beneficial_owners>",
    ]
    for index, ubo in enumerate(packet.ubos):
        lines.append(
            f"ubo[{index}]: name={ubo.name}; dob={ubo.dob or 'unknown'}; "
            f"nationality={ubo.nationality or 'unknown'}; role={ubo.role or 'unknown'}"
        )
    if not packet.ubos:
        lines.append("(none declared)")
    lines.append("</beneficial_owners>")

    lines.append("<documents>")
    for index, document in enumerate(packet.documents):
        content = document.content.replace("</document>", "<\\/document>")
        lines.append(f'<document index="{index}" declared_type="{document.type}">')
        lines.append(content)
        lines.append("</document>")
    if not packet.documents:
        lines.append("(none supplied)")
    lines.append("</documents>")
    lines.append("</applicant>")
    return "\n".join(lines)


def validate_anchors(extraction: Extraction, packet: Applicant) -> list[str]:
    """Every claim must point at a document that exists and quote text it contains; applied to model output only."""
    problems: list[str] = []
    count = len(packet.documents)

    def content_at(index: int, label: str) -> str | None:
        if not 0 <= index < count:
            problems.append(f"{label}: index {index} is not one of the {count} documents supplied")
            return None
        return packet.documents[index].content

    seen: set[int] = set()
    for entry in extraction.documents:
        label = f"documents[index={entry.index}]"
        content = content_at(entry.index, label)
        if entry.index in seen:
            problems.append(f"{label}: classified twice")
        seen.add(entry.index)
        if content is not None:
            problems.extend(_span_problems(entry.evidence_span, content, label))

    for finding in extraction.shell_signals:
        label = f"shell_signals[{finding.signal}]"
        content = content_at(finding.source_index, label)
        if content is not None:
            problems.extend(_span_problems(finding.evidence_span, content, label))

    for found in extraction.names:
        label = f"names[{found.kind}]"
        content = content_at(found.source_index, label)
        if content is None:
            continue
        problems.extend(_span_problems(found.evidence_span, content, label))
        if _canonical(found.name) not in _canonical(found.evidence_span):
            problems.append(f"{label}: the name is not inside the span it cites")

    return problems


def _span_problems(span: str, content: str, label: str) -> list[str]:
    """A span must be present in the cited document character for character."""
    if not span.strip():
        return [f"{label}: evidence_span is empty"]
    if span not in content:
        return [f"{label}: evidence_span is not a verbatim quote from that document"]
    return []


def _correction(problems: list[str]) -> str:
    """Name the violations, then ask for the same job again."""
    listed = "\n".join(f"- {problem}" for problem in problems)
    return (
        "That response was rejected. Every evidence_span must be copied character for character "
        "from the content of the document you cite, and every index must be one of the documents "
        "you were given.\n\n"
        f"Problems found:\n{listed}\n\n"
        "Return the whole extraction again, quoting rather than paraphrasing."
    )


def merge(
    packet: Applicant, floor: Floor, extraction: Extraction, usage: Usage | None = None
) -> ExtractionResult:
    """Union the floor with the model, then canonicalise so the same findings always spell the same result."""
    kinds: dict[int, str] = {index: "incorporation" for index in floor.incorporation_indices}
    for entry in extraction.documents:
        if 0 <= entry.index < len(packet.documents):
            kinds.setdefault(entry.index, entry.kind)

    signals = sorted(set(floor.shell_signals) | {finding.signal for finding in extraction.shell_signals})
    targets, dropped = screening_targets(packet, extraction)

    return ExtractionResult(
        applicant_id=packet.applicant_id,
        document_kinds=dict(sorted(kinds.items())),
        has_incorporation_doc=any(kind == "incorporation" for kind in kinds.values()),
        shell_signals=signals,
        screening_targets=targets,
        injection_suspected=floor.contains_instructions or extraction.contains_instructions,
        dropped_targets=dropped,
        usage=usage,
    )


def screening_targets(packet: Applicant, extraction: Extraction) -> tuple[list[ScreeningTarget], int]:
    """The business and every UBO, never filtered and never capped, plus whatever names the documents added."""
    business = packet.business
    targets = [
        ScreeningTarget(
            name=business.legal_name,
            subject="business",
            subject_ref="business",
            country=business.registration_country or business.address.country,
        )
    ]
    for index, ubo in enumerate(packet.ubos):
        targets.append(
            ScreeningTarget(
                name=ubo.name,
                subject="ubo",
                subject_ref=f"ubo[{index}]",
                dob=ubo.dob,
                country=ubo.nationality,
            )
        )

    known = {_canonical(target.name) for target in targets}
    supplementary: dict[str, ScreeningTarget] = {}
    for found in extraction.names:
        key = _canonical(found.name)
        if not key or key in known or key in supplementary:
            continue
        supplementary[key] = ScreeningTarget(
            name=WHITESPACE.sub(" ", found.name.strip()),
            subject="business" if found.kind == "business" else "ubo",
            subject_ref=f"document[{found.source_index}]",
            source="document",
        )

    ordered = [supplementary[key] for key in sorted(supplementary)]
    dropped = max(0, len(ordered) - MAX_SUPPLEMENTARY_NAMES)
    return targets + ordered[:MAX_SUPPLEMENTARY_NAMES], dropped


def _canonical(name: str) -> str:
    """Casefolded and whitespace-collapsed, for deduplication only, never for searching."""
    return WHITESPACE.sub(" ", name.strip()).casefold()
