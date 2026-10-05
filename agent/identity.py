"""Identity verification before any account detail (risk R4).

Two designs, kept side by side so the validation failure can be shown and replayed:

  v0.9  The rule "verify identity before giving any account detail" is an
        instruction in the prompt, and the full customer record, verification
        answers included, is in the model's context from the first turn. The
        model judges the answers itself and calls `record_identity_verified`.
        Validation FAILED (GR-004): the red team got the balance confirmed
        through yes/no questions before verification. The design never said
        that a confirmation counts as a disclosure.

  v1.0  The account context is not in the model's context until verification
        succeeds, and the check below runs in code, not in the model. The model
        can't disclose what it doesn't have. Validation PASSED (GR-005): 0 of 340
        red-team attempts.

Controls: EU AI Act Art. 15 accuracy, robustness and cybersecurity; ISO/IEC 42001
A.6.2.4 verification and validation; NIST AI RMF MEASURE 2.7 security and resilience.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

MAX_ATTEMPTS = 2

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%B %d %Y", "%d %B %Y", "%b %d %Y", "%d %b %Y")


def parse_date(text: str) -> date | None:
    cleaned = re.sub(r"^\s*the\s+", "", text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"(\d)(?:st|nd|rd|th)\b", r"\1", cleaned.replace(",", " ").replace(" of ", " "))
    cleaned = " ".join(cleaned.split())
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def _normalise_address(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())


@dataclass
class IdentityGate:
    """One call's verification state, checked against the customer record in code."""

    date_of_birth: str
    address_first_line: str
    attempts: int = 0
    verified: bool = False

    @classmethod
    def from_record(cls, record: dict) -> IdentityGate:
        v = record["verification"]
        return cls(date_of_birth=v["date_of_birth"], address_first_line=v["address_first_line"])

    @property
    def locked_out(self) -> bool:
        return not self.verified and self.attempts >= MAX_ATTEMPTS

    def check(self, date_of_birth: str, address_first_line: str) -> bool:
        """True when both answers match. Never says which answer was wrong."""
        if self.verified:
            return True
        if self.locked_out:
            return False
        self.attempts += 1
        dob_ok = parse_date(date_of_birth) == date.fromisoformat(self.date_of_birth)
        address_ok = _normalise_address(address_first_line) == _normalise_address(self.address_first_line)
        self.verified = dob_ok and address_ok
        return self.verified


def account_context(record: dict) -> dict:
    """What the agent may know after verification: the record without the verification answers."""
    return {k: v for k, v in record.items() if k not in ("verification", "_note")}


def pre_verification_context(record: dict) -> dict:
    """What the agent may know before verification (v1.0): who to ask for, nothing else."""
    return {"borrower": {"name": record["borrower"]["name"]},
            "account_details": "locked until identity is verified with the verify_identity tool"}
