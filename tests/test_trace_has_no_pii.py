"""The trace, checked over its bytes rather than over a list of fields somebody remembered to redact. (D-012)"""

import json
import re

import pytest

from agent.orchestrate import screen
from agent.schemas import RunTrace
from agent.trace import emit, render
from tests.conftest import FakeClient, classify, extraction, named, signal

# Short enough and common enough that a substring test would fire on unrelated text.
TOO_SHORT = 4


def traced(packet, brain, **overrides):
    client = FakeClient(extraction(**overrides))
    return screen(packet, brain, client, run_id="run-0", model="claude-opus-5")[1]


def pii_of(packet) -> list[str]:
    """Everything in the packet a person could be identified by."""
    values = [packet.business.legal_name, packet.business.registration_number, packet.business.address.line]
    for ubo in packet.ubos:
        values += [ubo.name, str(ubo.dob) if ubo.dob else None, ubo.role]
    return [value for value in values if value and len(value) > TOO_SHORT]


def test_no_packet_pii_reaches_the_trace(packets, brain):
    """All 18 packets, every name, date of birth, address line and registration number."""
    leaks = {
        applicant_id: [value for value in pii_of(packet) if value.casefold() in render(traced(packet, brain)).casefold()]
        for applicant_id, packet in packets.items()
    }

    assert {applicant_id: found for applicant_id, found in leaks.items() if found} == {}


def test_no_document_text_reaches_the_trace(packets, brain):
    """Evidence spans are verbatim quotes from documents, which is exactly what must not be logged."""
    offenders = []
    for applicant_id, packet in packets.items():
        serialised = render(traced(packet, brain))
        for document in packet.documents:
            for phrase in re.findall(r"[A-Za-z][A-Za-z ,\-]{15,}", document.content):
                if phrase.strip() and phrase.strip() in serialised:
                    offenders.append((applicant_id, phrase.strip()))

    assert offenders == []


def test_a_model_reporting_names_and_spans_still_leaks_nothing(packets, brain):
    """The floor cannot be the reason it stays clean: prime the model with the very strings that must not appear."""
    packet = packets["APP-009"]
    # "UBO: Ivanka Sokolova, DOB 1980-06-21." — a name and a date of birth, quoted verbatim.
    span = packet.documents[1].content
    trace = traced(
        packet,
        brain,
        documents=[classify(1, "ubo_declaration", span)],
        # The second name is not a packet UBO, so it becomes a document-sourced
        # target and is searched — the path where a name is likeliest to leak.
        names=[named("Ivanka Sokolova", 1, span), named("Sokolova", 1, span)],
        shell_signals=[signal("nominee_director", 1, span)],
    )

    serialised = render(trace)
    assert "Ivanka Sokolova" in span and "1980-06-21" in span
    assert trace.extract.supplementary_targets == 1
    assert "document[1]" in trace.extract.target_refs
    assert span not in serialised
    assert "sokolova" not in serialised.casefold()
    assert "1980-06-21" not in serialised


def test_the_schema_has_no_field_that_could_hold_a_name(packets, brain):
    """Redaction by construction: an open dict or a free string field is where PII would eventually land."""
    serialised = json.loads(render(traced(packets["APP-011"], brain)))

    assert set(serialised) == set(RunTrace.model_fields)
    assert all(key.isdigit() for key in serialised["extract"]["document_kinds"])
    assert all(re.fullmatch(r"business|ubo\[\d+\]|document\[\d+\]", ref) for ref in serialised["extract"]["target_refs"])


def test_the_trace_in_the_response_is_the_trace_in_the_log(packets, brain, tmp_path):
    """Not equal — identical. There is one serialisation, and both sinks get it."""
    trace = traced(packets["APP-003"], brain)

    returned = emit(trace, tmp_path)
    written = (tmp_path / "runs.jsonl").read_text(encoding="utf-8")

    assert written == returned + "\n"


def test_an_unwritable_trace_volume_does_not_fail_the_run(packets, brain, tmp_path):
    """Observability degrading is not the same event as screening failing."""
    directory = tmp_path / "readonly"
    directory.mkdir()
    directory.chmod(0o555)

    try:
        assert emit(traced(packets["APP-001"], brain), directory / "traces")
    finally:
        directory.chmod(0o755)


@pytest.mark.parametrize("applicant_id", ["APP-009", "APP-011", "APP-015"])
def test_the_trace_still_says_what_matched(packets, brain, applicant_id):
    """Carrying no PII must not mean carrying no information: entry ids are list data, not applicant data."""
    trace = traced(packets[applicant_id], brain)

    assert trace.screen.hits
    assert all(hit.entry_id and hit.subject_ref for hit in trace.screen.hits)
