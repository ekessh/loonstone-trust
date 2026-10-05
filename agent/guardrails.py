"""Banned-phrase filter: urgency, scarcity and binding-acceptance language (risk R1).

Runs on the agent's text before it is spoken and before it is written to the
transcript, one sentence at a time. A sentence that matches is never voiced; the
agent says a neutral replacement instead, and the block is logged as an event.

Why: scripted false urgency may be a manipulative technique under EU AI Act
Art. 5(1)(a), and the agent must never accept a renewal on the call (G0 exclusion,
GR-002). Controls: ISO/IEC 42001 A.6.2.2 requirements, A.9.2 responsible use;
NIST AI RMF MANAGE 1.3 risk response, MEASURE 2.6 safety.

Known limit, on purpose: this is a lexical filter. Paraphrased urgency the list
does not name gets through. That gap is what the per-call evaluation and human
sampling of its scores exist to catch (MON-RNW, MEASURE 2.13).
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterable, Callable

FILTER_VERSION = "banned-phrases/v1"

REPLACEMENT = (
    "There's no rush. Your offer stays open until the expiry date in your offer pack, "
    "and you can take whatever time you need."
)

BANNED: dict[str, re.Pattern] = {
    "deadline": re.compile(
        r"\b(?:today only|only today|by (?:the )?end of (?:today|the day)|before (?:\d{1,2}(?::\d{2})?\s*(?:am|pm)|"
        r"midnight|close of business)|until (?:\d{1,2}(?::\d{2})?\s*(?:am|pm)|midnight|tonight)|expires? (?:today|tonight)|"
        r"(?:within|in) the next (?:hour|\d+ (?:minutes|hours)))\b", re.I),
    "scarcity": re.compile(
        r"\b(?:reserved (?:just |only )?for you|limited(?:-| )time|while (?:stocks|supplies|it) lasts?|"
        r"(?:only|just) (?:a few|\d+) (?:left|remaining|spots?)|won't (?:last|be (?:here|available)) (?:long|for long)|"
        r"last chance|once it'?s gone|exclusive (?:to you|offer for you))\b", re.I),
    "pressure": re.compile(
        r"\b(?:act now|don'?t (?:miss out|wait|delay)|you(?:'d| would) be (?:mad|crazy|foolish) (?:not )?to|"
        r"rates? (?:are|is) (?:about to|going to|set to) (?:go up|rise|increase)|before (?:rates|prices) (?:go up|rise)|"
        r"you need to decide (?:now|today|right now)|decide (?:right )?now|everyone else is (?:taking|locking))\b", re.I),
    "binding_acceptance": re.compile(
        r"\b(?:I(?:'ll| will| can)? (?:lock (?:that|it|you) in|confirm (?:your|the) renewal|accept (?:that|it|this) for you|"
        r"sign you up|renew (?:it|you) now)|(?:you'?re|you are) (?:now )?(?:locked in|renewed|signed up)|"
        r"shall I (?:lock|renew|sign)|(?:just )?say yes and (?:it'?s|you'?re) done)\b", re.I),
}

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def find(text: str) -> list[dict]:
    """Every banned phrase in `text`, with its category."""
    return [{"category": c, "phrase": m.group(0)} for c, p in BANNED.items() for m in p.finditer(text)]


def filter_text(text: str) -> tuple[str, list[dict]]:
    """Replace each sentence that holds a banned phrase. Returns the safe text and what was blocked."""
    out, blocked = [], []
    for sentence in _SENTENCE_END.split(text):
        hits = find(sentence)
        if hits:
            blocked += hits
            if REPLACEMENT not in out:
                out.append(REPLACEMENT)
        else:
            out.append(sentence)
    return " ".join(s for s in out if s), blocked


async def filter_stream(text: AsyncIterable[str], on_block: Callable[[list[dict]], None] | None = None
                        ) -> AsyncIterable[str]:
    """Filter a streamed reply sentence by sentence.

    Holds back each sentence until it ends, so a banned phrase is never spoken
    before the filter has seen the whole sentence. Costs the length of one
    sentence of latency on the first audio, which is the price of the control.
    """
    buffer = ""
    replaced = False
    async for chunk in text:
        buffer += chunk
        parts = _SENTENCE_END.split(buffer)
        buffer = parts.pop()  # the unfinished sentence waits for more text
        for sentence in parts:
            safe, blocked = filter_text(sentence)
            if blocked:
                if on_block:
                    on_block(blocked)
                if replaced:
                    continue  # say the replacement once per reply
                replaced = True
            yield safe + " "
    if buffer.strip():
        safe, blocked = filter_text(buffer)
        if blocked and on_block:
            on_block(blocked)
        if not (blocked and replaced):
            yield safe
