import json

import pytest

from agent.redaction import ACCOUNT, AMOUNT, NAME, OFFER_RECORD, PERSONAL, Redactor


@pytest.fixture(scope="module")
def r() -> Redactor:
    return Redactor.from_offer_record()


@pytest.mark.parametrize(
    "line, expected",
    [
        ("Hi, is this Alex Carrow?", f"Hi, is this {NAME}?"),
        ("Thanks, Alex.", f"Thanks, {NAME}."),
        ("Mr. carrow, your offer", f"Mr. {NAME}, your offer"),
        ("Account LT-5520-3371-08 is due.", f"Account {ACCOUNT} is due."),
        ("Another account LT-1234-5678-90.", f"Another account {ACCOUNT}."),
        ("account LT 5520 3371 08", f"account {ACCOUNT}"),
        ("the number is 5520 3371 08", f"the number is {ACCOUNT}"),
        ("digits 5520337108", f"digits {ACCOUNT}"),
        ("The charge is €4,210.55 today.", f"The charge is {AMOUNT} today."),
        ("Your balance is 285,400.00.", f"Your balance is {AMOUNT}."),
        ("Payments of 1677.29 euro a month", f"Payments of {AMOUNT} a month"),
        ("about four thousand two hundred euro", f"about {AMOUNT}"),
        ("That is $2575 a month.", f"That is {AMOUNT} a month."),
        ("£1,200 a month", f"{AMOUNT} a month"),
    ],
)
def test_masks_names_accounts_amounts(r, line, expected):
    assert r.text(line) == expected


@pytest.mark.parametrize(
    "line",
    [
        "is my balance still 285400",            # bare known amount, no currency or separator
        "it's 285 400 or so",                     # spaced
        "is it around 4210",                      # bare whole number, not a year
        "two hundred and eighty-five thousand",   # number words, no currency
        "my payment is 1752 a month",
    ],
)
def test_masks_amounts_without_currency_markers(r, line):
    out = r.text(line)
    assert AMOUNT in out
    assert r.leaks(out) == []


@pytest.mark.parametrize(
    "line",
    ["born 1984-03-12", "it's 12/03/1984", "March 12th, 1984", "the 12th of March 1984",
     "I live at 14 Harbour View", "harbour view, number fourteen"],
)
def test_masks_verification_answers(r, line):
    out = r.text(line)
    assert PERSONAL in out
    assert "1984" not in out and "harbour" not in out.lower()


@pytest.mark.parametrize(
    "line",
    [
        "The 5-year fixed rate is 3.65%.",
        "Your offer is valid until 2026-12-26.",
        "Your mortgage matures on January 26, 2027.",
        "a 3-year fixed term at 3.80%",
        "over the remaining 20 years",
    ],
)
def test_keeps_rates_dates_and_terms(r, line):
    assert r.text(line) == line


def test_customer_record_has_no_identifiers_amounts_or_answers_after_redaction(r):
    record = OFFER_RECORD.read_text(encoding="utf-8")
    out = r.text(record)
    assert r.leaks(out) == []
    for raw in ("285400", "1752.11", "1677.29", "1699.54", "4210.55", "1,875.64", "1984-03-12", "Harbour"):
        assert raw not in out, raw
    assert "3.65" in out and "2026-12-26" in out  # rates and offer dates survive
    assert '"outstanding_balance_amount": [AMOUNT]' in out  # still a readable record


def test_attribute_sequences(r):
    attrs = {"a": ["Alex said", 3], "b": 7, "c": ("LT-5520-3371-08",)}
    assert r.attributes(attrs) == {"a": [f"{NAME} said", 3], "b": 7, "c": (ACCOUNT,)}


def test_record_is_valid_json():
    json.loads(OFFER_RECORD.read_text(encoding="utf-8"))


@pytest.mark.parametrize("heard", ["That's Carow. Yes.", "Mr. Carro, hello", "karrow"])
def test_misheard_surname_is_redacted(r, heard):
    out = r.text(heard)
    assert NAME in out
    assert r.leaks(heard)


@pytest.mark.parametrize("fine", ["I have a carrot", "the career", "tomorrow and arrows", "Alexandria"])
def test_similar_ordinary_words_are_kept(r, fine):
    assert r.text(fine) == fine
    assert r.leaks(fine) == []


def test_name_hearings_counts_exact_and_misheard_without_names(r):
    counts = r.name_hearings("That's Carow. Yes, this is Alex Carrow.")
    assert counts == {"exact": 2, "misheard": 1}


# ---- no parser differential: anything the identity gate accepts must be redacted


def _dob_renderings():
    from datetime import date

    from agent.identity import _DATE_FORMATS
    d = date(1984, 3, 12)
    out = {d.strftime(f) for f in _DATE_FORMATS}
    out |= {"12.3.1984", "3/12/1984".replace("3/12", "12/3"), "Mar 12th, 1984", "12th of Mar 1984",
            "the 12th of March, 1984", "12 mar 1984", "MARCH 12 1984"}
    return sorted(out)


@pytest.mark.parametrize("said", _dob_renderings())
def test_every_date_the_gate_accepts_is_redacted(r, said):
    from agent.identity import IdentityGate
    record = json.loads(OFFER_RECORD.read_text(encoding="utf-8"))
    assert IdentityGate.from_record(record).check(said, "14 Harbour View"), said
    blob = json.dumps({"date_of_birth": said})
    out = r.text(blob)
    assert PERSONAL in out and "1984" not in out, out
    assert r.leaks(out) == []


@pytest.mark.parametrize("said", ["14, harbour view.", "14 Harbour-View", "14  HARBOUR   VIEW", "harbour_view"])
def test_every_address_form_the_gate_normalises_is_redacted(r, said):
    out = r.text(f'{{"address_first_line": "{said}"}}')
    assert "harbour" not in out.lower(), out


def test_other_dates_are_kept(r):
    line = "renews 2027-01-26, offer until 26 December 2026, as of 12 March 2026"
    assert r.text(line) == line
