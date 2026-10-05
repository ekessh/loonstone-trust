"""AIS-014 Renewal Assist: the outbound renewal voice agent. FICTIONAL BANK, DEMO ONLY.

Claude Sonnet 5 for dialogue, Deepgram Flux for speech-to-text and text-to-speech,
traced to Langfuse with personal data redacted (agent/telemetry.py).

    .venv/Scripts/python -m agent.renewal_agent dev

The worker registers as "loonstone-renewal" and joins a room only when dispatched
(agent/start_call.py). The job metadata picks the version (v0.9 or v1.0, see
agent/identity.py) and the mode (sim, or a phone line once one is approved).

Controls built in, each tied to the approved design (RNW-CTL):
  disclosure     first sentence says it's an AI, the call is recorded, and a person
                 is available (EU AI Act Art. 50(1); ISO/IEC 42001 A.8.2)
  identity gate  v0.9 prompt instruction (failed V); v1.0 account context withheld
                 until a code check passes (passed V)
  phrase filter  urgency, scarcity and binding-acceptance sentences never voiced
                 (agent/guardrails.py)
  handoff        request for a person, money trouble, distress, complaint or repeated
                 confusion goes to a person at once (agent/handoff.py)
  no acceptance  the agent can send an offer pack or book a specialist; it has no
                 tool to accept or bind a renewal

After each call it writes evidence to evidence/calls/<room>/:
  transcript.txt   the call, redacted the same way as the traces
  events.json      what the controls did, and when (agent/events.py)
  figures.json     every amount and rate the agent said, checked against the record
  evaluation.json  the per-call evaluation (agent/evaluate.py)
  latency.csv      per-turn timings
  stt_names.json   name recognition counts, no names
  ai_content.json  which transcript lines are AI-generated
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
import re

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (Agent, AgentServer, AgentSession, JobContext, RunContext, StopResponse, cli,
                            function_tool, llm, metrics)
from livekit.agents.voice.room_io import RoomOptions
from livekit.plugins import anthropic, deepgram, silero

from . import evaluate, guardrails, telemetry
from .config import (DEFAULT_VERSION, EVIDENCE_CALLS, OFFER_RECORD, ORGANISATION, PROMPTS, REPO, SYSTEM_ID,
                     SYSTEM_NAME, VERSIONS)
from .events import EventLog
from .figures import check_figures
from .handoff import HANDOFF_LINE, REASONS, HandoffMonitor, reason_category
from .identity import IdentityGate, account_context, pre_verification_context
from .redaction import Redactor

load_dotenv(REPO / ".env")

AGENT_NAME = "loonstone-renewal"
LLM_MODEL = "claude-sonnet-5"
STT_MODEL = "flux-general-en"
TTS_MODEL = "flux-alexis-en"

OPENING = (
    "Hello, this is {system}, an AI assistant calling for {org} about your mortgage renewal. "
    "This call is recorded, and you can ask to speak with a person at any time. "
    "Am I speaking with {name}?"
)


def load_record() -> dict:
    return json.loads(OFFER_RECORD.read_text(encoding="utf-8"))


def opening_line(record: dict) -> str:
    return OPENING.format(system=SYSTEM_NAME, org=ORGANISATION, name=record["borrower"]["name"])


def build_instructions(version: str, record: dict, verified: bool = False) -> str:
    text = (PROMPTS / f"{version}.md").read_text(encoding="utf-8")
    text = re.sub(r"<!--.*?-->\s*", "", text, flags=re.DOTALL)  # the governance header is not for the model
    if version == "v0.9":
        full = {k: v for k, v in record.items() if k != "_note"}
        return text.replace("{customer_record}", json.dumps(full, indent=2))
    context = account_context(record) if verified else pre_verification_context(record)
    return text.replace("{account_context}", json.dumps(context, indent=2))


def ai_content_label(room: str, transcript: list[str], version: str = DEFAULT_VERSION,
                     simulated: bool = True) -> dict:
    """Provenance annotation of the stored transcript.

    Lists which transcript.txt lines (1-based, a turn can span several lines) are
    AI-generated speech, and the models that produced them. This annotates the text
    record; it is not a machine-readable mark on the audio the borrower hears, so it
    does not by itself meet EU AI Act Art. 50(2). In a simulated call the borrower is
    the test simulator, so both speakers are synthetic.
    """
    lines, line = [], 1
    for entry in transcript:
        span = entry.count("\n") + 1
        if entry.startswith("AGENT:"):
            lines.append([line, line + span - 1])
        line += span
    borrower = ({"ai_generated": True, "source": "test simulator, synthetic voice"} if simulated
                else {"ai_generated": False, "source": "a person on the phone line"})
    return {
        "label": "loonstone-transcript-provenance/v1",
        "is_art_50_2_output_mark": False,
        "system_id": SYSTEM_ID,
        "call": room,
        "simulated_call": simulated,
        "ai_generated": {"speaker": "AGENT", "agent_version": version, "llm": LLM_MODEL,
                         "tts": TTS_MODEL, "synthetic_voice": True},
        "transcript": "transcript.txt",
        "ai_generated_line_ranges": lines,
        "borrower_lines": borrower,
    }


class RenewalAgent(Agent):
    """Shared behaviour for both versions: phrase filter, handoff, offer pack, specialist booking."""

    version = DEFAULT_VERSION

    def __init__(self, record: dict, events: EventLog, on_handoff) -> None:
        super().__init__(instructions=build_instructions(self.version, record))
        self.record = record
        self.events = events
        self.monitor = HandoffMonitor()
        self.handed_off = False
        self._on_handoff = on_handoff

    # ---- phrase filter: on the text to be spoken and on the transcript, sentence by sentence
    def _blocked(self, hits: list[dict]) -> None:
        self.events.add("guardrail_block", filter=guardrails.FILTER_VERSION,
                        categories=sorted({h["category"] for h in hits}))

    def tts_node(self, text, model_settings):
        return Agent.default.tts_node(self, guardrails.filter_stream(text, self._blocked), model_settings)

    def transcription_node(self, text, model_settings):
        return Agent.default.transcription_node(self, guardrails.filter_stream(text), model_settings)

    # ---- handoff: checked on every borrower turn before the agent replies
    async def on_user_turn_completed(self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage) -> None:
        if self.handed_off:
            raise StopResponse()
        reason = self.monitor.check(new_message.text_content or "")
        if reason:
            await self.hand_off(reason, source="trigger")
            raise StopResponse()

    async def hand_off(self, reason: str, source: str) -> None:
        if self.handed_off:
            return
        if reason not in REASONS:  # only fixed categories reach events and logs
            reason = reason_category(reason)
        self.handed_off = True
        self.events.add("handoff_triggered", reason=reason, source=source)
        handle = self.session.say(HANDOFF_LINE, allow_interruptions=False)

        async def finish() -> None:
            await handle
            self.events.add("handoff_spoken", reason=reason)
            self._on_handoff(reason)

        asyncio.create_task(finish())

    @function_tool
    async def transfer_to_person(self, context: RunContext, reason: str) -> None:
        """Connect the customer with a person on the renewals team, now.

        Args:
            reason: Short reason, e.g. "asked for a person", "money trouble", "complaint".
        """
        await self.hand_off(reason_category(reason), source="model")
        raise StopResponse()  # the handoff line is the whole reply; the model says nothing after it

    @function_tool
    async def send_offer_pack(self, context: RunContext) -> str:
        """Send the written offer pack, which the customer can accept in their own time."""
        self.events.add("offer_pack_sent")
        return "The offer pack is on its way. Tell the customer it explains how to accept and how the rate was set."

    @function_tool
    async def book_specialist(self, context: RunContext, preferred_time: str) -> str:
        """Book a call back from a renewals specialist.

        Args:
            preferred_time: When the customer would like the call, in their words.
        """
        self.events.add("specialist_booked")
        return "Booked. Confirm the time back to the customer."


class RenewalAgentV09(RenewalAgent):
    """Gate V: NOT MET (GR-004). The model holds the whole record and attests verification itself."""

    version = "v0.9"

    @function_tool
    async def record_identity_verified(self, context: RunContext) -> str:
        """Call once the customer's date of birth and address match the record."""
        self.events.add("identity_verified", method="model_attested")
        return "Recorded. Continue with the renewal."


class RenewalAgentV10(RenewalAgent):
    """Gate V: MET (GR-005). Account context loaded only after a code check passes."""

    version = "v1.0"

    def __init__(self, record: dict, events: EventLog, on_handoff) -> None:
        super().__init__(record, events, on_handoff)
        self.gate = IdentityGate.from_record(record)

    @function_tool
    async def verify_identity(self, context: RunContext, date_of_birth: str, address_first_line: str) -> str:
        """Check the customer's answers. Account details are available only after this succeeds.

        Args:
            date_of_birth: The date of birth exactly as the customer said it.
            address_first_line: The first line of their address exactly as the customer said it.
        """
        if self.gate.check(date_of_birth, address_first_line):
            self.events.add("identity_verified", method="code_checked", attempts=self.gate.attempts)
            await self.update_instructions(build_instructions(self.version, self.record, verified=True))
            return "Verified. The account context is now in your instructions. Thank the customer and continue."
        if self.gate.locked_out:
            self.events.add("identity_locked_out", attempts=self.gate.attempts)
            return ("Not verified, and no attempts left. Tell the customer you can't go through the account "
                    "today and a person will call them back, then call transfer_to_person.")
        self.events.add("identity_failed", attempts=self.gate.attempts)
        return "Not verified. Don't say which answer didn't match. Ask the customer to try once more."


AGENTS = {"v0.9": RenewalAgentV09, "v1.0": RenewalAgentV10}

server = AgentServer()


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: JobContext) -> None:
    meta = json.loads(ctx.job.metadata or "{}")
    mode = meta.get("mode", "sim")
    version = meta.get("agent_version") or os.environ.get("RENEWAL_AGENT_VERSION", DEFAULT_VERSION)
    if version not in VERSIONS:
        raise ValueError(f"unknown agent version {version!r}; approved: {VERSIONS}")
    if version == "v0.9" and mode != "sim":
        raise ValueError("v0.9 failed validation (GR-004) and may only run against the simulator")
    scenario = f"renewal.{version.replace('.', '_')}.{meta.get('scenario', 'baseline')}"
    provider = telemetry.setup(
        "loonstone-renewal-agent",
        {
            "langfuse.session.id": ctx.room.name,
            "loonstone.system_id": SYSTEM_ID,
            "loonstone.agent_version": version,
            "loonstone.scenario": scenario,
            "loonstone.mode": mode,
            "loonstone.llm": LLM_MODEL,
            "loonstone.stt": STT_MODEL,
            "loonstone.tts": TTS_MODEL,
        },
    )

    # sim: the borrower is the simulator agent; a live call would be a SIP participant
    kinds = (
        [rtc.ParticipantKind.PARTICIPANT_KIND_AGENT]
        if mode == "sim"
        else [rtc.ParticipantKind.PARTICIPANT_KIND_SIP]
    )

    session = AgentSession(
        stt=deepgram.STTv2(model=STT_MODEL),
        llm=anthropic.LLM(model=LLM_MODEL, caching="ephemeral", max_tokens=300),
        tts=deepgram.TTSv2(model=TTS_MODEL),
        vad=silero.VAD.load(),
        # Flux decides end of turn; interruptions detected locally by VAD
        turn_handling={"turn_detection": "stt", "interruption": {"mode": "vad"}},
    )

    record = load_record()
    turns: dict[str, dict] = {}
    agent_lines: list[str] = []
    transcript: list[str] = []
    events = EventLog(transcript)
    redactor = Redactor.from_record(record)

    @session.on("metrics_collected")
    def _on_metrics(ev) -> None:
        m = ev.metrics
        sid = getattr(m, "speech_id", None)
        if not sid:
            return
        row = turns.setdefault(sid, {"speech_id": sid})
        if isinstance(m, metrics.EOUMetrics):
            row["end_of_turn_delay_s"] = round(m.end_of_utterance_delay, 3)
            row["transcription_delay_s"] = round(m.transcription_delay, 3)
        elif isinstance(m, metrics.LLMMetrics):
            row["llm_ttft_s"] = round(m.ttft, 3)
            row["llm_duration_s"] = round(m.duration, 3)
        elif isinstance(m, metrics.TTSMetrics):
            row.setdefault("tts_ttfb_s", round(m.ttfb, 3))
            row["tts_audio_s"] = round(row.get("tts_audio_s", 0) + m.audio_duration, 3)

    @session.on("conversation_item_added")
    def _on_item(ev) -> None:
        item = ev.item
        text = getattr(item, "text_content", None)
        if not text or getattr(item, "role", None) not in ("assistant", "user"):
            return
        who = "AGENT" if item.role == "assistant" else "BORROWER"
        if who == "AGENT":
            agent_lines.append(text)
        transcript.append(f"{who}: {text}")

    async def write_evidence() -> None:
        events.add("call_ended")
        out = EVIDENCE_CALLS / ctx.room.name
        out.mkdir(parents=True, exist_ok=True)
        cols = ["speech_id", "end_of_turn_delay_s", "transcription_delay_s", "llm_ttft_s",
                "tts_ttfb_s", "response_latency_s", "llm_duration_s", "tts_audio_s"]
        with (out / "latency.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for row in turns.values():
                parts = [row.get(k) for k in ("end_of_turn_delay_s", "llm_ttft_s", "tts_ttfb_s")]
                if all(p is not None for p in parts[1:]):
                    row["response_latency_s"] = round(sum(p or 0 for p in parts), 3)
                w.writerow({k: row.get(k, "") for k in cols})
        (out / "figures.json").write_text(json.dumps(check_figures(agent_lines, record=record), indent=2),
                                          encoding="utf-8")
        # name recognition, counted on the unredacted text in memory; counts only
        heard = "\n".join(t[len("BORROWER:"):] for t in transcript if t.startswith("BORROWER:"))
        (out / "stt_names.json").write_text(json.dumps(redactor.name_hearings(heard), indent=2), encoding="utf-8")
        (out / "transcript.txt").write_text("\n".join(redactor.text(t) for t in transcript) + "\n",
                                            encoding="utf-8")
        events.write(out / "events.json")
        (out / "ai_content.json").write_text(json.dumps(
            ai_content_label(ctx.room.name, transcript, version, simulated=(mode == "sim")), indent=2),
            encoding="utf-8")
        evaluate.evaluate(ctx.room.name, version=version)
        provider.force_flush()

    def on_handoff(reason: str) -> None:
        # No live transfer target yet: in simulation the call ends once the handoff line is spoken.
        if mode == "sim":
            asyncio.get_running_loop().call_later(2, ctx.shutdown, f"handed off: {reason}")

    ctx.add_shutdown_callback(write_evidence)
    session.on("close", lambda _ev: ctx.shutdown(reason="call ended"))

    await ctx.connect()
    await ctx.room.local_participant.set_attributes({"loonstone.role": "renewal-agent",
                                                     "loonstone.agent_version": version})
    borrower = await ctx.wait_for_participant(kind=kinds)
    events.add("call_started", version=version, mode=mode)
    await session.start(
        agent=AGENTS[version](record, events, on_handoff),
        room=ctx.room,
        room_options=RoomOptions(participant_kinds=kinds, participant_identity=borrower.identity),
    )
    # the disclosure is fixed text, not generated, so it is identical on every call
    await session.say(opening_line(record), allow_interruptions=False)
    events.add("opening_spoken")


if __name__ == "__main__":
    cli.run_app(server)
