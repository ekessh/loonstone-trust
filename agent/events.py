"""Per-call event log: what the controls did, and when.

Written to events.json next to the transcript. Each event carries its time from
call start and `transcript_entry`, the number of transcript entries when it
happened, so the evaluation can tell what was said before and after it (for
example, before identity was verified). Events hold no personal data: no
verification answers, no amounts.

Controls: EU AI Act Art. 12 record-keeping and Art. 26(6) log retention;
ISO/IEC 42001 A.6.2.8 event logs; NIST AI RMF MEASURE 2.4 production monitoring.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

EVENT_TYPES = (
    "call_started", "opening_spoken",
    "identity_verified", "identity_failed", "identity_locked_out",
    "guardrail_block",
    "handoff_triggered", "handoff_spoken",
    "offer_pack_sent", "specialist_booked",
    "call_ended",
)


@dataclass
class EventLog:
    transcript: list[str]
    started: float = field(default_factory=time.monotonic)
    events: list[dict] = field(default_factory=list)

    def add(self, type: str, **data) -> dict:
        if type not in EVENT_TYPES:
            raise ValueError(f"unknown event type: {type}")
        event = {"t_s": round(time.monotonic() - self.started, 3), "type": type,
                 "transcript_entry": len(self.transcript), **data}
        self.events.append(event)
        return event

    def first(self, type: str) -> dict | None:
        return next((e for e in self.events if e["type"] == type), None)

    def write(self, path: Path) -> None:
        path.write_text(json.dumps(self.events, indent=2) + "\n", encoding="utf-8")
