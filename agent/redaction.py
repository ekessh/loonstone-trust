"""Personal-data redaction for traces and stored transcripts (risk R4).

Masks personal data before anything leaves the process (GDPR Art. 5(1)(c) data
minimisation, ISO/IEC 42001 A.7.4 data quality and A.7.5 provenance, NIST AI RMF
MEASURE 2.10 privacy risk): the borrower's name, account number, verification
answers and money amounts. Rates, offer dates and product names are kept, because
the record has to show the agent quoted the offer correctly.

Three layers:
  * exact values from the customer record (name parts, account number, date of
    birth, address, every money amount), each in the forms it can be written or
    heard, so a known identifier can never slip through a loose pattern
  * misheard forms of the name, because speech-to-text rarely spells it right
  * patterns, for amounts and account numbers that are not in the record

The date of birth and address are matched with the same parsing and normalising
the identity gate uses (agent/identity.py), so any answer the gate would accept is
also redacted: the two can't drift apart.

Known limits: an amount not in the record, said as a bare number below 1,000 with
no currency, is kept (it cannot be told apart from a count). A date of birth spelled
out in words ("the twelfth of March") is kept; the gate doesn't accept that form either.
"""

from __future__ import annotations

import difflib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .config import OFFER_RECORD
from .identity import parse_date

NAME = "[NAME]"
ACCOUNT = "[ACCOUNT]"
AMOUNT = "[AMOUNT]"
PERSONAL = "[PERSONAL]"

# Loonstone account numbers: LT-dddd-dddd-dd, with any separator or none
_ACCOUNT_RE = re.compile(r"\bLT[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{2}\b", re.IGNORECASE)

_CURRENCY_SYMBOL = r"[€$£]"
_CURRENCY_WORD = r"(?:euros?|EUR|dollars?|USD|pounds?|GBP)"
_NUMBER_WORDS = (
    "zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|"
    "fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|"
    "sixty|seventy|eighty|ninety|hundred|thousand|million|and|point"
)
_AMOUNT_RES = [
    # JSON money fields: "outstanding_balance_amount": 285400.0, "amount": 4210.55
    re.compile(r'("(?:[a-z_]*_)?amount"\s*:\s*)-?\d+(?:\.\d+)?'),
    # €285,400.00  € 4,210.55  $2575  £1,200
    re.compile(rf"{_CURRENCY_SYMBOL}\s?\d(?:[\d,]|\s(?=\d))*(?:\.\d+)?(?:\s?(?:k|thousand|million)\b)?", re.IGNORECASE),
    # 285,400.00  4,210.55  (digits with a thousands separator)
    re.compile(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b"),
    # 1677.29 euro  5040 EUR  285k euros
    re.compile(rf"\b\d+(?:\.\d+)?\s?(?:k\s?)?{_CURRENCY_WORD}\b", re.IGNORECASE),
    # a bare figure with cents: 1677.29 (3+ digits, so a rate like 3.65 is kept)
    re.compile(r"\b\d{3,}\.\d{2}\b(?!\s*%)"),
    # a bare whole number of 4+ digits that is not a year: 285400, 4210
    re.compile(r"\b(?!(?:19|20)\d{2}\b)\d{4,}\b(?!\s*%)"),
    # number words with a currency word: "four thousand two hundred euro"
    re.compile(rf"\b(?:(?:{_NUMBER_WORDS})[\s-]+)+{_CURRENCY_WORD}\b", re.IGNORECASE),
    # number words that reach hundreds or more, with no currency: "two hundred and eighty-five thousand"
    re.compile(rf"\b(?:(?:{_NUMBER_WORDS})[\s-]+)*(?:hundred|thousand|million)(?:[\s-]+(?:{_NUMBER_WORDS}))*\b",
               re.IGNORECASE),
]


# date candidates for the date-of-birth scan: runs of up to six tokens that start with
# a number, a month name or "the", tried against the identity gate's own parser
_DATE_TOKEN = re.compile(r"[A-Za-z]+|\d+(?:st|nd|rd|th)?(?:[/.-]\d+)*")
_DATE_START = re.compile(r"^(?:\d|the$|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", re.IGNORECASE)
_DATE_MAX_TOKENS = 6


def _skeleton(word: str) -> str:
    """Consonants only, hard c as k, doubles collapsed: "Carrow" and "karrow" -> "krw"."""
    word = re.sub(r"c(?![eiy])", "k", word.lower()).replace("kk", "k")
    return re.sub(r"(.)\1+", r"\1", re.sub(r"[aeiouy']", "", word))


def sounds_like(word: str, name: str) -> bool:
    """True when `word` is plausibly speech-to-text mishearing `name`.

    Only names of five letters or more: shorter ones ("Alex") would catch common
    words. A match is the same consonant skeleton, or near-identical spelling; the
    spelling bar is higher for short names, where one letter is a bigger share
    ("Carrow" must not catch "carrot" or "arrows").
    """
    word, name = word.lower(), name.lower()
    if len(word) < 5 or len(name) < 5 or word == name:
        return False
    if len(_skeleton(name)) >= 3 and _skeleton(word) == _skeleton(name):
        return True
    bar = 0.8 if len(name) >= 8 else 0.88
    return difflib.SequenceMatcher(None, word, name).ratio() >= bar


def amount_forms(value: float) -> set[str]:
    """Every way a money amount from the record is likely to be written or transcribed."""
    whole = int(value)
    forms = {f"{value:,.2f}", f"{value:.2f}", f"{whole:,}", str(whole), f"{whole:,}".replace(",", " ")}
    if value != whole:
        forms.add(f"{value:,.2f}".replace(",", " "))
    return {f for f in forms if len(f.replace(",", "").replace(" ", "")) >= 3}


def date_of_birth_forms(iso: str) -> list[str]:
    """Regexes for a date of birth in digit forms: 1984-03-12, 12/03/1984, March 12th, 1984, 12 March 1984."""
    d = date.fromisoformat(iso)
    month = d.strftime("%B")
    day = rf"0?{d.day}(?:st|nd|rd|th)?"
    return [
        rf"\b{d:%Y}-{d:%m}-{d:%d}\b",
        rf"\b0?{d.day}[/.-]0?{d.month}[/.-]{d.year}\b",
        rf"\b0?{d.month}[/.-]0?{d.day}[/.-]{d.year}\b",
        rf"\b{month}\s+{day},?\s+{d.year}\b",
        rf"\b{day}\s+(?:of\s+)?{month},?\s+{d.year}\b",
    ]


def _money_values(record: dict) -> set[float]:
    found: set[float] = set()
    stack: list = [record]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for k, v in node.items():
                if (k == "amount" or k.endswith("_amount")) and isinstance(v, (int, float)):
                    found.add(float(v))
                elif isinstance(v, str):
                    for m in re.findall(r"(?<![\d.])\d[\d,]*\.\d{2}(?!\s*%)", v):
                        if float(m.replace(",", "")) >= 100:
                            found.add(float(m.replace(",", "")))
                else:
                    stack.append(v)
        elif isinstance(node, list):
            stack.extend(node)
    return found


@dataclass(frozen=True)
class Redactor:
    names: tuple[str, ...]
    accounts: tuple[str, ...]
    amounts: tuple[str, ...] = ()
    personal: tuple[str, ...] = ()  # regexes: date of birth, address
    date_of_birth: str | None = None  # ISO; also matched through identity.parse_date

    @classmethod
    def from_record(cls, record: dict) -> Redactor:
        borrower = record["borrower"]
        full = borrower["name"].strip()
        # longest first, so "Alex Carrow" is replaced before "Alex"
        names = sorted({full, *full.split()}, key=len, reverse=True)
        amounts = sorted({f for v in _money_values(record) for f in amount_forms(v)}, key=len, reverse=True)
        personal: list[str] = []
        verification = record.get("verification", {})
        if dob := verification.get("date_of_birth"):
            personal += date_of_birth_forms(dob)
        if address := verification.get("address_first_line"):
            # any punctuation or spacing between words, as the gate's normalising allows
            words = re.findall(r"[a-z0-9]+", address.lower())
            personal.append(r"\b" + r"[\W_]+".join(map(re.escape, words)) + r"\b")
            street = [w for w in words if not w.isdigit()]
            if street and street != words:
                personal.append(r"\b" + r"[\W_]+".join(map(re.escape, street)) + r"\b")
        return cls(names=tuple(names), accounts=(borrower["account_number"],),
                   amounts=tuple(amounts), personal=tuple(personal),
                   date_of_birth=verification.get("date_of_birth"))

    @classmethod
    def from_offer_record(cls, path: Path = OFFER_RECORD) -> Redactor:
        return cls.from_record(json.loads(path.read_text(encoding="utf-8")))

    def _account_patterns(self) -> list[re.Pattern]:
        # the known account's digits with any separators or none: "5520 3371 08", "5520337108"
        out = []
        for account in self.accounts:
            digits = re.sub(r"\D", "", account)
            if len(digits) >= 6:
                out.append(re.compile(r"(?<!\d)" + r"[\s-]?".join(digits) + r"(?!\d)"))
        return out

    def text(self, value: str) -> str:
        for account in self.accounts:
            value = re.sub(re.escape(account), ACCOUNT, value, flags=re.IGNORECASE)
        value = _ACCOUNT_RE.sub(ACCOUNT, value)
        for pattern in self._account_patterns():
            value = pattern.sub(ACCOUNT, value)
        for pattern in self.personal:
            value = re.sub(pattern, PERSONAL, value, flags=re.IGNORECASE)
        value = self._redact_parsed_dates(value)
        for name in self.names:
            value = re.sub(rf"\b{re.escape(name)}\b", NAME, value, flags=re.IGNORECASE)
        # misheard forms of the name, which exact matching misses
        single = [n for n in self.names if " " not in n]
        value = re.sub(r"[A-Za-z']+", lambda m: NAME if any(sounds_like(m[0], n) for n in single) else m[0], value)
        for form in self.amounts:
            value = re.sub(rf"(?<![\d.,]){re.escape(form)}(?![\d]|[.,]\d)", AMOUNT, value)
        for pattern in _AMOUNT_RES:
            if pattern.groups:
                value = pattern.sub(lambda m: m.group(1) + AMOUNT, value)
            else:
                value = pattern.sub(AMOUNT, value)
        # a known amount replaced before the currency patterns ran leaves its symbol or word behind
        value = re.sub(rf"{_CURRENCY_SYMBOL}\s?\[AMOUNT\]", AMOUNT, value)
        return re.sub(rf"\[AMOUNT\]\s?{_CURRENCY_WORD}\b", AMOUNT, value, flags=re.IGNORECASE)

    def _dob_spans(self, value: str) -> list[tuple[int, int]]:
        """Spans of `value` that identity.parse_date reads as the date of birth."""
        if not self.date_of_birth:
            return []
        dob = date.fromisoformat(self.date_of_birth)
        tokens = list(_DATE_TOKEN.finditer(value))
        spans, i = [], 0
        while i < len(tokens):
            hit = None
            if _DATE_START.match(tokens[i][0]):
                for j in range(min(len(tokens), i + _DATE_MAX_TOKENS) - 1, i - 1, -1):
                    if parse_date(value[tokens[i].start():tokens[j].end()]) == dob:
                        hit = j
                        break
            if hit is not None:
                spans.append((tokens[i].start(), tokens[hit].end()))
                i = hit + 1
            else:
                i += 1
        return spans

    def _redact_parsed_dates(self, value: str) -> str:
        for start, end in reversed(self._dob_spans(value)):
            value = value[:start] + PERSONAL + value[end:]
        return value

    def name_hearings(self, value: str) -> dict:
        """How often the borrower's name parts were heard exactly or misheard in `value`.

        Counts only, so the result holds no personal data. Used for speech-to-text
        accuracy on names, which word error rate on redacted text cannot see.
        """
        single = [n for n in self.names if " " not in n]
        exact = misheard = 0
        for word in re.findall(r"[A-Za-z']+", value):
            if any(word.lower() == n.lower() for n in single):
                exact += 1
            elif any(sounds_like(word, n) for n in single):
                misheard += 1
        return {"exact": exact, "misheard": misheard}

    def value(self, value):
        """Redact a trace attribute value: str, or a sequence of str."""
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, (list, tuple)):
            return type(value)(self.text(v) if isinstance(v, str) else v for v in value)
        return value

    def attributes(self, attributes) -> dict:
        return {k: self.value(v) for k, v in (attributes or {}).items()}

    def leaks(self, value: str) -> list[str]:
        """Known identifiers still present in `value` (used by tests and the trace check)."""
        found = [n for n in self.names if re.search(rf"\b{re.escape(n)}\b", value, re.IGNORECASE)]
        single = [n for n in self.names if " " not in n]
        found += sorted({w for w in re.findall(r"[A-Za-z']+", value) if any(sounds_like(w, n) for n in single)})
        found += [a for a in self.accounts if a.lower() in value.lower()]
        found += [p.pattern for p in self._account_patterns() if p.search(value)]
        found += [p for p in self.personal if re.search(p, value, re.IGNORECASE)]
        found += [value[a:b] for a, b in self._dob_spans(value)]
        found += [f for f in self.amounts if re.search(rf"(?<![\d.,]){re.escape(f)}(?![\d]|[.,]\d)", value)]
        return found


def redact_all(redactor: Redactor, values: Iterable[str]) -> list[str]:
    return [redactor.text(v) for v in values]
