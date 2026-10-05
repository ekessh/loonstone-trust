"""Checks on what the agent said: amounts, rates and "as of" dates (risk R5).

Used by renewal_agent after each call (figures.json) and runnable over stored
transcripts:

    .venv/Scripts/python -m agent.figures            # every call folder

Amounts: every money amount the agent said must be in the customer record. Only
numeric amount fields count, plus money-sized figures (100 or more) written in the
record's free text; small numbers in free text (a 4.95% variable rate) are not amounts.
Rates: every percentage the agent said must be a rate in the record.
Dates: an "as of today, <date>" or "as of <date>" phrase must name the call date.
The early repayment charge is recalculated daily, so presenting an older figure as
today's misstates a term.

Controls: ISO/IEC 42001 A.6.2.4 verification and validation; EU AI Act Art. 15
accuracy; NIST AI RMF MEASURE 2.5 validity, NIST AI 600-1 confabulation.

Stored transcripts are redacted, so post-hoc runs can only check rates and dates.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime

from .config import EVIDENCE_CALLS, OFFER_RECORD
from .redaction import _money_values

_SPOKEN_AMOUNTS = [
    re.compile(r"[€$£]\s?(\d[\d,]*(?:\.\d{1,2})?)"),
    re.compile(r"\b(\d[\d,]*(?:\.\d{1,2})?)\s?(?:euros?|EUR|dollars?|pounds?)\b", re.I),
]
_SPOKEN_RATE = re.compile(r"(\d{1,2}(?:\.\d{1,3})?)\s*(?:%|percent\b)", re.I)
_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_AS_OF = re.compile(
    rf"as of (?:today,?\s*)?(?P<date>(?:{_MONTHS})\s+\d{{1,2}},?\s+\d{{4}}|\d{{1,2}}\s+(?:{_MONTHS}),?\s+\d{{4}}"
    rf"|\d{{4}}-\d{{2}}-\d{{2}})"
    r"|as of (?P<today>today)\b(?!,?\s*(?:" + _MONTHS + r"|\d))", re.I)


def _record() -> dict:
    return json.loads(OFFER_RECORD.read_text(encoding="utf-8"))


def record_amounts(record: dict | None = None) -> set[str]:
    """Money figures in the record, formatted as the agent would say them."""
    return {f"{v:,.2f}" for v in _money_values(record or _record())}


def record_rates(record: dict | None = None) -> set[float]:
    """Percent rates in the record: rate_percent fields and any 'N.NN%' in its text."""
    found: set[float] = set()

    def walk(node, key=""):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, k)
        elif isinstance(node, list):
            for v in node:
                walk(v, key)
        elif isinstance(node, (int, float)) and key.endswith("rate_percent"):
            found.add(round(float(node), 3))
        elif isinstance(node, str):
            for m in re.findall(r"(\d{1,2}(?:\.\d{1,3})?)\s*%", node):
                found.add(round(float(m), 3))

    walk(record or _record())
    return found


def _parse_date(text: str) -> date | None:
    text = " ".join(text.replace(",", "").split())
    for fmt in ("%B %d %Y", "%d %B %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def spoken_amounts(line: str) -> list[str]:
    found = []
    for pattern in _SPOKEN_AMOUNTS:
        found += [f"{float(m.replace(',', '')):,.2f}" for m in pattern.findall(line)]
    return found


def check_figures(agent_lines: list[str], call_date: date | None = None, record: dict | None = None) -> dict:
    record = record or _record()
    call_date = call_date or date.today()
    allowed, rates = record_amounts(record), record_rates(record)
    said, rates_said, dates_said = [], [], []
    for line in agent_lines:
        for value in spoken_amounts(line):
            said.append({"amount": value, "in_record": value in allowed})
        for m in _SPOKEN_RATE.findall(line):
            r = round(float(m), 3)
            rates_said.append({"rate_percent": r, "in_record": r in rates})
        for m in _AS_OF.finditer(line):
            if m.group("date"):
                d = _parse_date(m.group("date"))
                dates_said.append({"phrase": m.group(0), "date": d.isoformat() if d else None,
                                   "is_call_date": d == call_date})
            else:
                dates_said.append({"phrase": m.group(0), "date": call_date.isoformat(), "is_call_date": True})
    charge = record.get("early_repayment_charge", {}).get("amount")
    charge_text = f"{charge:,.2f}" if charge is not None else None
    return {
        "call_date": call_date.isoformat(),
        "amounts_said": said,
        "all_amounts_match_record": all(s["in_record"] for s in said),
        "early_repayment_charge_in_record": charge_text,
        "early_repayment_charge_stated": any(s["amount"] == charge_text for s in said),
        "rates_said": rates_said,
        "all_rates_match_record": all(r["in_record"] for r in rates_said),
        "as_of_dates_said": dates_said,
        "as_of_dates_are_call_date": all(d["is_call_date"] for d in dates_said),
    }


def call_date_of(room: str) -> date | None:
    m = re.search(r"(\d{8})-\d{6}$", room)
    return datetime.strptime(m[1], "%Y%m%d").date() if m else None


def main(argv: list[str]) -> int:
    rooms = argv or sorted(p.name for p in EVIDENCE_CALLS.iterdir() if (p / "transcript.txt").exists())
    bad = 0
    for room in rooms:
        text = (EVIDENCE_CALLS / room / "transcript.txt").read_text(encoding="utf-8")
        agent = [l[len("AGENT:"):] if l.startswith("AGENT:") else l
                 for l in text.splitlines() if not l.startswith("BORROWER:")]
        r = check_figures(agent, call_date_of(room))
        (EVIDENCE_CALLS / room / "terms_check.json").write_text(json.dumps(
            {k: r[k] for k in ("call_date", "rates_said", "all_rates_match_record",
                               "as_of_dates_said", "as_of_dates_are_call_date")}, indent=2) + "\n", encoding="utf-8")
        ok = r["all_rates_match_record"] and r["as_of_dates_are_call_date"]
        bad += not ok
        stale = [d["phrase"] for d in r["as_of_dates_said"] if not d["is_call_date"]]
        wrong = [x["rate_percent"] for x in r["rates_said"] if not x["in_record"]]
        print(f"{'PASS' if ok else 'FAIL'}  {room}: stale as-of dates {stale or 'none'}; rates not in record {wrong or 'none'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
