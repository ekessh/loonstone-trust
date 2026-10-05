"""Who may be called, and when (risks R2, R5; G0 and G1 scope).

Checked before a call is dialled. An excluded customer is never called by the
agent; their renewal goes to a specialist instead.

Excluded: customers flagged vulnerable, in arrears or on forbearance, and anyone
whose language preference is not English. The vulnerability flag alone is not
enough: the data review found 11% of known hardship cases had no flag (RNW-DR),
so arrears and forbearance are separate exclusions.

Live calls only between 09:00 and 20:00 local time, and no more than twice per
customer per renewal. Simulated calls to the test harness are exempt from the
call window so testing can run at any hour; they are never exempt from the
segment exclusions.

Controls: ISO/IEC 42001 A.9.4 intended use, A.5.4 impact on individuals;
EU AI Act Art. 9 risk management; NIST AI RMF MAP 3.3 application scope.
"""

from __future__ import annotations

from datetime import datetime, time

CALL_WINDOW = (time(9, 0), time(20, 0))
MAX_CALLS_PER_RENEWAL = 2
EXCLUDED_FLAGS = ("vulnerable", "arrears", "forbearance")
SUPPORTED_LANGUAGES = ("en",)


def check(record: dict, now: datetime, *, live: bool, previous_calls: int = 0) -> list[str]:
    """Reasons this customer must not be called now. An empty list means the call may go ahead."""
    borrower = record["borrower"]
    reasons = [f"excluded segment: {flag}" for flag in EXCLUDED_FLAGS
               if borrower.get("segment_flags", {}).get(flag)]
    if borrower.get("language", "en") not in SUPPORTED_LANGUAGES:
        reasons.append(f"language preference not supported: {borrower.get('language')}")
    if live:
        start, end = CALL_WINDOW
        if not start <= now.time() < end:
            reasons.append(f"outside the call window {start:%H:%M}-{end:%H:%M}")
        if previous_calls >= MAX_CALLS_PER_RENEWAL:
            reasons.append(f"already called {previous_calls} times for this renewal")
    return reasons
