import pytest

from agent.stt_accuracy import heard_by_agent, wer, words


def test_words_normalises_case_punctuation_and_redaction_tokens():
    assert words("Yes. This is [NAME]!") == ["yes", "this", "is", "name"]
    assert words("I'd like to compare") == ["i'd", "like", "to", "compare"]


def test_identical_text_is_zero():
    assert wer("Not right now, thanks.", "not right now thanks")["wer"] == 0.0


@pytest.mark.parametrize(
    "hyp, s, d, n",
    [
        ("not right now tanks", 1, 0, 0),
        ("not now thanks", 0, 1, 0),
        ("not right now thanks a lot", 0, 0, 2),
    ],
)
def test_counts_each_error_type(hyp, s, d, n):
    r = wer("not right now thanks", hyp)
    assert (r["substitutions"], r["deletions"], r["insertions"]) == (s, d, n)
    assert r["wer"] == pytest.approx((s + d + n) / 4)


def test_empty_reference():
    assert wer("", "anything")["wer"] == 0.0


def test_heard_by_agent_keeps_only_borrower_lines():
    transcript = "AGENT: Hello, am I speaking with [NAME]?\nBORROWER: Yes. This is [NAME].\nAGENT: Thanks."
    assert heard_by_agent(transcript).strip() == "Yes. This is [NAME]."


def test_compound_spellings_are_not_errors():
    assert wer("Call back, please. That's all right.", "Callback please. That's alright.")["wer"] == 0.0


def test_name_token_error_counted_separately():
    r = wer("Yes, this is [NAME].", "Yes, this is disresures.")
    assert r["substitutions"] == 1 and r["name_token_errors_in_alignment"] == 1
    assert wer("Yes, this is [NAME].", "Yes, this is [NAME].")["name_token_errors_in_alignment"] == 0
