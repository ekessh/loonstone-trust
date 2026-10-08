"""Identity of the AI system and shared paths. FICTIONAL BANK, DEMO ONLY.

UC-1 Mortgage Renewal Agent is the system's entry in the AI system register
(ISO/IEC 42001 A.4.2 resources, NIST AI RMF GOVERN 1.6 inventory). The register
is VerifyWise, and it issues the ID: UC-<n> from its own sequence when the use
case is created. Nobody picks it, so it can't be reused or chosen to look tidy. Every trace,
evidence file and transcript label carries this ID and the agent version, so a
record can always be traced to the exact configuration that produced it
(ISO/IEC 42001 A.6.2.7 technical documentation, EU AI Act Art. 12 record-keeping).
"""

from __future__ import annotations

from pathlib import Path

ORGANISATION = "Loonstone Trust"
SYSTEM_ID = "UC-1"
SYSTEM_NAME = "Renewal Assist"

REPO = Path(__file__).resolve().parents[1]
AGENT_DIR = Path(__file__).resolve().parent
PROMPTS = AGENT_DIR / "prompts"
OFFER_RECORD = AGENT_DIR / "data" / "offer_record.json"

# Per-call evidence: transcript, events, checks. Git-ignored; kept per the retention schedule.
EVIDENCE_CALLS = REPO / "evidence" / "calls"

# Agent versions with an approved prompt. v0.9 is the design that failed validation
# (ID gate as a prompt instruction, GR-004); v1.0 is the redesign that passed (GR-005).
VERSIONS = ("v0.9", "v1.0")
DEFAULT_VERSION = "v1.0"
