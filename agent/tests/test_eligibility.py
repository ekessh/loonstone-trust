import copy
import json
from datetime import datetime

import pytest

from agent.config import OFFER_RECORD
from agent.eligibility import check

RECORD = json.loads(OFFER_RECORD.read_text(encoding="utf-8"))
NOON = datetime(2026, 10, 5, 12, 0)


def with_flag(flag: str) -> dict:
    r = copy.deepcopy(RECORD)
    r["borrower"]["segment_flags"][flag] = True
    return r


def test_sample_customer_is_eligible():
    assert check(RECORD, NOON, live=True) == []


@pytest.mark.parametrize("flag", ["vulnerable", "arrears", "forbearance"])
def test_excluded_segments_never_called_even_in_simulation(flag):
    assert check(with_flag(flag), NOON, live=False)


def test_unsupported_language():
    r = copy.deepcopy(RECORD)
    r["borrower"]["language"] = "pl"
    assert check(r, NOON, live=True)


def test_call_window_applies_to_live_calls_only():
    late = datetime(2026, 10, 5, 21, 30)
    assert check(RECORD, late, live=True)
    assert check(RECORD, late, live=False) == []


def test_at_most_two_calls_per_renewal():
    assert check(RECORD, NOON, live=True, previous_calls=2)
