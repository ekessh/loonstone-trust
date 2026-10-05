import asyncio

import pytest

from agent.guardrails import REPLACEMENT, filter_stream, filter_text, find


@pytest.mark.parametrize(
    "line, category",
    [
        ("This rate is reserved for you until 5pm today.", "scarcity"),
        ("It's a limited-time offer.", "scarcity"),
        ("You need to decide today.", "pressure"),
        ("Rates are about to go up, so act now.", "pressure"),
        ("The offer expires today.", "deadline"),
        ("Shall I lock that in for you?", "binding_acceptance"),
        ("I'll lock you in now.", "binding_acceptance"),
        ("Great, you're now renewed.", "binding_acceptance"),
    ],
)
def test_banned_phrases_found(line, category):
    assert category in {h["category"] for h in find(line)}


@pytest.mark.parametrize(
    "line",
    [
        "Your offer is valid until December 26, 2026.",
        "Take whatever time you need.",
        "I can send you the offer pack, and you can accept it in your own time.",
        "The 5-year fixed rate is 3.65%.",
        "Would you like me to book a call with a specialist?",
    ],
)
def test_normal_lines_pass(line):
    assert find(line) == []


def test_only_the_offending_sentence_is_replaced():
    safe, blocked = filter_text("The 5-year rate is 3.65%. This rate is reserved for you until 5pm today.")
    assert safe == f"The 5-year rate is 3.65%. {REPLACEMENT}"
    assert blocked


def test_stream_filter_never_emits_a_banned_sentence():
    async def chunks():
        for c in ["The rate is 3.65%. This rate is res", "erved for you. Act now", " before rates go up. ",
                  "I can send the pack."]:
            yield c

    async def run():
        blocks = []
        out = "".join([s async for s in filter_stream(chunks(), blocks.append)])
        return out, blocks

    out, blocks = asyncio.run(run())
    assert find(out) == []
    assert out.count(REPLACEMENT) == 1
    assert "3.65%" in out and "send the pack" in out
    assert len(blocks) == 2


def test_paraphrased_urgency_is_a_known_gap():
    """Lexical by design. This is the gap the per-call evaluation and human sampling must cover."""
    assert find("Honestly, I wouldn't sit on this one too long if I were you.") == []
