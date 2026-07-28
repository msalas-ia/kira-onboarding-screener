"""The union of the floor and the model. Extraction may raise severity; it may not lower it. (D-008)"""

import copy

from agent.constants import (
    MAX_SUPPLEMENTARY_NAMES,
    SHELL_SIGNAL_MASS_REGISTRATION,
    SHELL_SIGNAL_NOMINEE_DIRECTOR,
)
from agent.extraction import extract
from agent.facts import from_packet
from agent.rules import evaluate
from tests.conftest import FakeClient, classify, extraction, named, signal

APPLICANT_WITHOUT_INCORPORATION = "APP-006"
APPLICANT_WITH_SHELL_SIGNALS = "APP-008"
APPLICANT_WITH_INJECTION = "APP-009"


def _extract(packet, brain, response=None):
    return extract(packet, brain, FakeClient(response if response is not None else extraction()))


def test_a_model_that_reports_nothing_cannot_suppress_the_shell_signals(packets, brain):
    """The suppression path, closed by construction: this is what an injection would try to do."""
    packet = packets[APPLICANT_WITH_SHELL_SIGNALS]

    result = _extract(packet, brain)

    assert result.shell_signals == [SHELL_SIGNAL_MASS_REGISTRATION, SHELL_SIGNAL_NOMINEE_DIRECTOR]
    assert evaluate(brain, from_packet(packet, result, brain.settings)).decision == "REVIEW"


def test_the_two_extracted_signals_reach_rule_7_on_their_own(packets, brain):
    """APP-008 is 238 days old at the pinned as_of_date, so the label holds on the two signals alone. (D-006)"""
    packet = packets[APPLICANT_WITH_SHELL_SIGNALS]
    facts = from_packet(packet, _extract(packet, brain), brain.settings)

    verdict = evaluate(brain, facts)

    assert facts.formation_age_days == 238
    assert verdict.fired_rules == [7]
    assert "formation_less_than_threshold" not in str(verdict.reasons)


def test_the_brain_adds_the_date_window_signal_when_the_window_does_reach(packets, brain):
    """A company young enough gets a third signal that extraction never reported."""
    packet = copy.deepcopy(packets[APPLICANT_WITH_SHELL_SIGNALS])
    packet.business.incorporation_date = brain.settings.as_of_date

    facts = from_packet(packet, _extract(packet, brain), brain.settings)

    assert evaluate(brain, facts).reasons == [
        "Rule 7 — shell-company signals: shell_signals=[mass_registration_address, "
        "nominee_director, formation_less_than_threshold]"
    ]


def test_the_model_can_add_a_signal_the_floor_did_not_see(packets, brain):
    """Escalation is the direction that is allowed to come from the model alone."""
    packet = copy.deepcopy(packets["APP-010"])
    packet.documents[0].content = "Registered through an agency arrangement."
    response = extraction(
        shell_signals=[signal(SHELL_SIGNAL_NOMINEE_DIRECTOR, 0, "agency arrangement")],
    )

    result = _extract(packet, brain, response)

    assert result.shell_signals == [SHELL_SIGNAL_NOMINEE_DIRECTOR]


def test_the_injection_changes_nothing_that_reaches_a_rule(packets, brain):
    """APP-009 with and without its compliance_note produce identical facts, bar the flag itself."""
    packet = packets[APPLICANT_WITH_INJECTION]
    without = copy.deepcopy(packet)
    without.documents = [document for document in without.documents if "SYSTEM NOTE" not in document.content]

    injected = from_packet(packet, _extract(packet, brain), brain.settings)
    clean = from_packet(without, _extract(without, brain), brain.settings)

    assert injected.injection_suspected is True
    assert clean.injection_suspected is False
    assert injected.model_dump(exclude={"injection_suspected"}) == clean.model_dump(exclude={"injection_suspected"})
    assert injected.has_incorporation_doc is True


def test_no_rule_in_v1_reads_the_injection_flag(brain):
    """The sensor exists; the policy has not been given an opinion about it yet."""
    referenced = {name for rule in brain.rules for name in list(rule.when) + rule.evidence}

    assert "injection_suspected" not in referenced


def test_the_model_catches_a_spelling_the_floor_does_not_know(packets, brain):
    """The reason an LLM is on this path: the holdout may spell it a third way."""
    packet = copy.deepcopy(packets[APPLICANT_WITHOUT_INCORPORATION])
    packet.documents[0].type = "constitutive_act"
    packet.documents[0].content = "Acta constitutiva, registry folio 4471."

    blind = _extract(packet, brain)
    seeing = _extract(packet, brain, extraction(documents=[classify(0, "incorporation", "Acta constitutiva")]))

    assert blind.has_incorporation_doc is False
    assert seeing.has_incorporation_doc is True


def test_the_floor_wins_when_the_model_mislabels_a_known_document(packets, brain):
    """A document the packet itself declares as incorporation cannot be talked out of that label."""
    packet = packets["APP-001"]

    result = _extract(packet, brain, extraction(documents=[classify(0, "other", "State of Delaware certificate")]))

    assert result.document_kinds[0] == "incorporation"
    assert result.has_incorporation_doc is True


def test_every_packet_screens_the_business_and_every_ubo_whatever_the_model_says(packets, brain):
    """Coverage is not a judgment call; the base set is never filtered and never capped."""
    for packet in packets.values():
        result = _extract(packet, brain)
        names = [target.name for target in result.screening_targets]

        assert packet.business.legal_name in names
        assert [ubo.name for ubo in packet.ubos] == [t.name for t in result.screening_targets if t.subject == "ubo"]
        assert [t.subject_ref for t in result.screening_targets][: 1 + len(packet.ubos)] == [
            "business",
            *[f"ubo[{index}]" for index in range(len(packet.ubos))],
        ]


def test_a_supplementary_name_is_added_and_carries_no_corroborating_fields(packets, brain):
    packet = packets["APP-005"]
    response = extraction(names=[named("Sofia Duarte", 1, "UBOs Laura Restrepo, Mateo Gil")])
    response.names[0].name = "Laura"  # a partial that is not already a UBO name
    response.names[0].evidence_span = "UBOs Laura Restrepo"

    result = _extract(packet, brain, response)
    supplementary = [target for target in result.screening_targets if target.source == "document"]

    assert [target.name for target in supplementary] == ["Laura"]
    assert supplementary[0].subject_ref == "document[1]"
    assert supplementary[0].dob is None and supplementary[0].country is None


def test_a_name_already_screened_is_not_added_twice(packets, brain):
    """Deduplication is by casefolded, whitespace-collapsed name."""
    packet = packets["APP-003"]
    response = extraction(names=[named("  viktor   petrov ", 1, "UBO: Viktor Petrov, DOB 1968-03-12")])
    response.names[0].evidence_span = "Viktor Petrov"
    response.names[0].name = "  viktor   petrov "

    result = _extract(packet, brain, response)

    assert len([target for target in result.screening_targets if target.source == "document"]) == 0


def test_supplementary_names_are_capped_and_the_overflow_is_recorded(packets, brain):
    packet = copy.deepcopy(packets["APP-004"])
    people = [f"Person {index:02d}" for index in range(MAX_SUPPLEMENTARY_NAMES + 4)]
    packet.documents[1].content = "Directors listed: " + ", ".join(people) + "."
    span = packet.documents[1].content
    response = extraction(names=[named(person, 1, span) for person in people])

    result = _extract(packet, brain, response)
    supplementary = [target for target in result.screening_targets if target.source == "document"]

    assert len(supplementary) == MAX_SUPPLEMENTARY_NAMES
    assert result.dropped_targets == 4


def test_shuffling_the_model_output_produces_an_identical_result(packets, brain):
    """Nothing downstream may depend on the order the model happened to answer in."""
    packet = packets[APPLICANT_WITH_SHELL_SIGNALS]
    note = packet.documents[1].content
    findings = [
        signal(SHELL_SIGNAL_NOMINEE_DIRECTOR, 1, "Nominee director listed"),
        signal(SHELL_SIGNAL_MASS_REGISTRATION, 1, "shared by 900+ entities"),
    ]
    names = [named("30 Churn Address", 1, note, kind="business"), named("Nominee director", 1, note)]
    assert all(found.name in note for found in names)  # the spans are the note itself

    forward = _extract(packet, brain, extraction(shell_signals=findings, names=names))
    reversed_ = _extract(packet, brain, extraction(shell_signals=findings[::-1], names=names[::-1]))

    assert forward.model_dump_json() == reversed_.model_dump_json()


def test_usage_is_carried_out_of_the_call(packets, brain):
    """Spec 004 puts this in the trace; it has to survive the merge to get there."""
    from agent.schemas import Usage

    client = FakeClient(extraction(), usage=Usage(input_tokens=1200, output_tokens=90, cache_read_input_tokens=1100))
    result = extract(packets["APP-001"], brain, client)

    assert result.usage.cache_read_input_tokens == 1100
