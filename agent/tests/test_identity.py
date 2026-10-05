import json

import pytest

from agent.config import OFFER_RECORD
from agent.identity import MAX_ATTEMPTS, IdentityGate, account_context, parse_date
from agent.redaction import Redactor
from agent.renewal_agent import build_instructions, opening_line

RECORD = json.loads(OFFER_RECORD.read_text(encoding="utf-8"))


@pytest.mark.parametrize("said", ["1984-03-12", "12/03/1984", "12 March 1984", "March 12th, 1984",
                                  "the 12th of March 1984"])
def test_date_of_birth_forms(said):
    assert IdentityGate.from_record(RECORD).check(said, "14 Harbour View")


def test_address_is_normalised():
    assert IdentityGate.from_record(RECORD).check("12 March 1984", "14, harbour view.")


def test_wrong_answer_then_lockout():
    gate = IdentityGate.from_record(RECORD)
    for _ in range(MAX_ATTEMPTS):
        assert not gate.check("13 March 1984", "14 Harbour View")
    assert gate.locked_out
    assert not gate.check("12 March 1984", "14 Harbour View")  # right answers after lockout still fail


def test_unparseable_date():
    assert parse_date("sometime in spring") is None


def test_v10_before_verification_has_no_account_details_or_answers():
    text = build_instructions("v1.0", RECORD, verified=False)
    r = Redactor.from_record(RECORD)
    leaked = [x for x in r.leaks(text) if x not in r.names]  # the name is allowed: it says who to ask for
    assert leaked == []
    for raw in ("285400", "1677.29", "3.65", "2027-01-26", "LT-5520", "1984", "Harbour"):
        assert raw not in text, raw


def test_v10_after_verification_has_offer_but_never_the_answers():
    text = build_instructions("v1.0", RECORD, verified=True)
    assert "3.65" in text and "1677.29" in text and "loan-to-value band" in text
    assert "1984" not in text and "Harbour" not in text


def test_v09_holds_everything_from_the_first_turn():
    """The design that failed Gate V: the record, answers included, is in context before any check."""
    text = build_instructions("v0.9", RECORD)
    assert "285400" in text and "1984-03-12" in text and "Harbour View" in text


def test_account_context_drops_answers():
    assert "verification" not in account_context(RECORD)


def test_opening_line_discloses_before_anything_else():
    line = opening_line(RECORD)
    assert line.index("AI assistant") < line.index("Am I speaking with")
    assert "recorded" in line and "person" in line
