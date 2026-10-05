from agent.check_disclosure import agent_turns, check_transcript

GOOD = """AGENT: Hello, this is Renewal Assist, an AI assistant calling for Loonstone Trust about your mortgage renewal. This call is recorded, and you can ask to speak with a person at any time. Am I speaking with [NAME]?
BORROWER: Yes.
AGENT: Thanks. Could you confirm your date of birth?

And the first line of your address?
BORROWER: [PERSONAL], [PERSONAL].
AGENT: Thank you. The 5-year rate is 3.65%."""


def test_turns_join_continuation_lines():
    turns = agent_turns(GOOD)
    assert len(turns) == 3 and "first line" in turns[1]


def test_disclosure_in_first_turn_passes():
    r = check_transcript(GOOD)
    assert r["passed"] and r["turn"] == 1 and r["before_offer"]


def test_missing_person_element_fails():
    r = check_transcript(GOOD.replace("you can ask to speak with a person at any time", "thanks"))
    assert not r["passed"] and r["elements"]["person"] is False


def test_disclosure_in_second_turn_fails_default_limit():
    late = """AGENT: Hello, am I speaking with [NAME]?
BORROWER: Yes.
AGENT: I'm an AI assistant, this call is recorded, and you can speak with a person."""
    r = check_transcript(late)
    assert r["present"] and r["turn"] == 2 and not r["passed"]
    assert check_transcript(late, max_turn=2)["passed"]


def test_disclosure_after_offer_fails():
    late = """AGENT: Hello. Your charge is [AMOUNT].
BORROWER: Okay.
AGENT: I'm an AI assistant, this call is recorded, and you can speak with a person."""
    r = check_transcript(late, max_turn=2)
    assert r["present"] and not r["before_offer"] and not r["passed"]
