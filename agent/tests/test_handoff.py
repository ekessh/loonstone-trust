import pytest

from agent.handoff import HandoffMonitor


@pytest.mark.parametrize(
    "said, reason",
    [
        ("Can I speak to a real person please?", "asked_for_person"),
        ("Are you a robot?", "asked_for_person"),
        ("I lost my job last month.", "money_trouble"),
        ("I'm behind on my payments.", "money_trouble"),
        ("We're separating, actually.", "life_event"),
        ("My father passed away in June.", "life_event"),
        ("I'm really stressed about all this.", "distress"),
        ("I want to make a complaint.", "complaint"),
    ],
)
def test_triggers(said, reason):
    assert HandoffMonitor().check(said) == reason


@pytest.mark.parametrize(
    "said",
    ["I'd like to compare a couple of other lenders first.", "I'd want to talk it over at home.",
     "Not right now, thanks.", "Could you send me the written offer?", "I'll think about it.",
     "Yes, this is Alex.", "Still interested, I will call back."],
)
def test_ordinary_lines_do_not_trigger(said):
    assert HandoffMonitor().check(said) is None


def test_confusion_twice_triggers():
    m = HandoffMonitor()
    assert m.check("Sorry, I don't understand.") is None
    assert m.check("What do you mean?") == "confused_twice"


@pytest.mark.parametrize(
    "model_text, category",
    [
        ("Alex Carrow said he lost his job", "money_trouble"),
        ("customer wants a human", "asked_for_person"),
        ("could not verify identity (DOB 12 March 1984)", "identity_not_verified"),
        ("Alex asked about a car loan", "other"),
    ],
)
def test_model_reasons_become_fixed_categories(model_text, category):
    from agent.handoff import REASONS, reason_category
    assert reason_category(model_text) == category
    assert category in REASONS
