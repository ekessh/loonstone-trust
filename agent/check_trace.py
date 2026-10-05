"""Check a call: personal data redacted in its Langfuse trace, turn spans and timings recorded,
and the AI disclosure spoken (from the transcript, via agent.check_disclosure).

    .venv/Scripts/python -m agent.check_trace <room>

Reads every observation in the Langfuse session for the room (the room name is
the session id) and writes evidence/calls/<room>/trace_check.json.
Fails (exit 1) if any known identifier, verification answer or amount from the
customer record (or a misheard form of the borrower's name) appears anywhere in the trace, if there
are no turn spans, or if the disclosure check fails. It cannot tell whether every
turn of the call reached the trace: it checks that turn spans exist, not how many
the call had.

Controls: GDPR Art. 5(1)(c) data minimisation and Art. 32 security; ISO/IEC 42001
A.7.4 data quality; NIST AI RMF MEASURE 2.10 privacy risk.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import Counter
from dotenv import load_dotenv

from . import check_disclosure
from .config import EVIDENCE_CALLS, OFFER_RECORD, REPO
from .redaction import Redactor, amount_forms

load_dotenv(REPO / ".env")


def observations(session_id: str) -> list[dict]:
    host = os.environ.get("LANGFUSE_HOST", "http://localhost:3000").rstrip("/")
    auth = base64.b64encode(
        f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}".encode()
    ).decode()
    out, cursor = [], None
    while True:
        q = {"limit": 100, "fields": "core,basic,io,metadata", "sessionId": session_id}
        if cursor:
            q["cursor"] = cursor
        req = urllib.request.Request(
            f"{host}/api/public/v2/observations?{urllib.parse.urlencode(q)}",
            headers={"Authorization": f"Basic {auth}"},
        )
        page = json.load(urllib.request.urlopen(req, timeout=30))
        out += page["data"]
        cursor = (page.get("meta") or {}).get("cursor")
        if not cursor or not page["data"]:
            return out


def raw_values() -> list[str]:
    """Identifiers and amounts that must never appear, in the forms they could be written."""
    record = json.loads(OFFER_RECORD.read_text(encoding="utf-8"))
    values = [record["borrower"]["account_number"], *record.get("verification", {}).values()]
    stack = [record]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for k, v in node.items():
                if (k == "amount" or k.endswith("_amount")) and isinstance(v, (int, float)):
                    values += sorted(amount_forms(v))
                stack.append(v)
        elif isinstance(node, list):
            stack.extend(node)
    return values


def check(room: str) -> dict:
    obs = observations(room)
    blob = json.dumps(obs)
    redactor = Redactor.from_offer_record()
    leaks = redactor.leaks(blob) + [v for v in raw_values() if v in blob]
    names = Counter(o["name"] for o in obs)
    turns = {n: c for n, c in names.items() if n in ("user_turn", "agent_turn")}
    timed = [o for o in obs if o.get("latency") is not None]
    result = {
        "room": room,
        "observations": len(obs),
        "turn_spans": turns,
        "spans_with_timings": len(timed),
        "span_names": dict(names.most_common()),
        "placeholders": {p: blob.count(p) for p in ("[NAME]", "[ACCOUNT]", "[AMOUNT]", "[PERSONAL]")},
        "leaks": sorted(set(leaks)),
    }
    disclosure = check_disclosure.check(room)
    result["disclosure"] = {k: disclosure.get(k) for k in ("present", "elements", "turn", "before_offer", "passed")}
    result["passed"] = not leaks and bool(turns) and bool(disclosure.get("passed"))
    out = EVIDENCE_CALLS / room
    out.mkdir(parents=True, exist_ok=True)
    (out / "trace_check.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    res = check(sys.argv[1])
    print(json.dumps({k: v for k, v in res.items() if k != "span_names"}, indent=2))
    sys.exit(0 if res["passed"] else 1)
