"""The floor: what the packet yields with no model involved. Everything the model adds is unioned on top. (D-008)"""

from agent.constants import SHELL_SIGNAL_MASS_REGISTRATION, SHELL_SIGNAL_NOMINEE_DIRECTOR
from agent.extraction import floor_of
from agent.schemas import Applicant, Business, Document, Ubo

APPLICANT_WITHOUT_INCORPORATION = "APP-006"
APPLICANT_WITH_SHELL_SIGNALS = "APP-008"
APPLICANT_WITH_INJECTION = "APP-009"


def _packet(**overrides) -> Applicant:
    defaults = dict(applicant_id="APP-000", business=Business(legal_name="Test Ltd"), ubos=[], documents=[])
    return Applicant(**{**defaults, **overrides})


def test_the_known_spellings_are_caught_without_a_model(packets):
    """APP-001 spells it certificate_of_incorporation, sixteen others spell it incorporation."""
    caught = {
        applicant_id: bool(floor_of(packet).incorporation_indices) for applicant_id, packet in packets.items()
    }

    assert caught[APPLICANT_WITHOUT_INCORPORATION] is False
    assert sum(caught.values()) == len(packets) - 1


def test_a_literal_comparison_against_one_spelling_would_have_missed_the_others(packets):
    """The finding that justifies putting an LLM on this path at all."""
    spellings = {
        document.type for packet in packets.values() for document in packet.documents if "incorporat" in document.type
    }

    assert spellings == {"incorporation", "certificate_of_incorporation"}


def test_the_shell_signals_are_read_out_of_free_text(packets):
    floor = floor_of(packets[APPLICANT_WITH_SHELL_SIGNALS])

    assert floor.shell_signals == [SHELL_SIGNAL_MASS_REGISTRATION, SHELL_SIGNAL_NOMINEE_DIRECTOR]


def test_only_the_shell_applicant_shows_signals(packets):
    """A floor that fired on benign text would turn clean applicants into REVIEWs."""
    firing = {applicant_id for applicant_id, packet in packets.items() if floor_of(packet).shell_signals}

    assert firing == {APPLICANT_WITH_SHELL_SIGNALS}


def test_a_nominee_role_alone_is_enough(packets):
    """The signal is in the structured role as well as the note; both sources are packet data."""
    packet = _packet(ubos=[Ubo(name="A. Director", role="Nominee Director")])

    assert floor_of(packet).shell_signals == [SHELL_SIGNAL_NOMINEE_DIRECTOR]


def test_only_the_injected_applicant_is_flagged(packets):
    """APP-009's compliance_note is the adversarial case; the other seventeen must stay quiet."""
    flagged = {applicant_id for applicant_id, packet in packets.items() if floor_of(packet).contains_instructions}

    assert flagged == {APPLICANT_WITH_INJECTION}


def test_the_injection_is_recognised_by_more_than_one_phrase(packets):
    """Rewording one sentence should not be enough to slip past the floor."""
    content = next(
        document.content
        for document in packets[APPLICANT_WITH_INJECTION].documents
        if "SYSTEM NOTE" in document.content
    )
    sentences = [sentence for sentence in content.split(". ") if sentence.strip()]

    caught = [
        sentence
        for sentence in sentences
        if floor_of(_packet(documents=[Document(type="note", content=sentence)])).contains_instructions
    ]

    assert len(caught) >= 3


def test_the_floor_is_a_pure_function_of_the_packet(packets):
    packet = packets[APPLICANT_WITH_SHELL_SIGNALS]

    assert floor_of(packet) == floor_of(packet)
