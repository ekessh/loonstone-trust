"""Automatic handoff to a person (risks R1, R2).

Checked on every borrower turn, before the agent replies. Any trigger means the
agent stops the conversation about the offer and connects the borrower to a
person; it does not try to answer first.

Triggers: a request for a person, distress or money-trouble phrases, a complaint,
or confusion twice in one call. The informal rule specialists used ("stop selling
and switch to support when money trouble, separation, illness or bereavement
comes up") is written down here so the agent keeps it on purpose.

Controls: EU AI Act Art. 14 human oversight; ISO/IEC 42001 A.9.2 responsible use,
A.9.4 intended use; NIST AI RMF MAP 3.5 human oversight, MANAGE 2.4 disengage.
The decision owner for handoff is the Contact Centre Manager (RNW-RACI).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

HANDOFF_LINE = (
    "Of course. I'll connect you with a person on our team now. "
    "They'll have the details of this call, so you won't need to repeat yourself."
)

TRIGGERS: dict[str, re.Pattern] = {
    "asked_for_person": re.compile(
        r"\b(?:(?:speak|talk|chat) (?:to|with) (?:a |an |some(?:one|body) |a real |an actual )?"
        r"(?:person|human|someone|somebody|agent|advisor|adviser|specialist|representative|manager)|"
        r"real person|human being|not a (?:robot|machine|bot)|are you a (?:robot|bot|machine)|"
        r"put me through|transfer me|get me a (?:person|human))\b", re.I),
    "money_trouble": re.compile(
        r"\b(?:can'?t (?:afford|pay|make (?:the|my) payments?|keep up)|(?:lost|losing) my job|made redundant|"
        r"laid off|out of work|behind (?:on|with) (?:my |the )?(?:payments?|mortgage)|in arrears|"
        r"struggling (?:to pay|with (?:money|payments|the mortgage))|money (?:is|has been) (?:tight|difficult)|"
        r"debt|bankrupt)", re.I),
    "life_event": re.compile(
        r"\b(?:separat(?:ed|ing|ion)|divorc(?:e|ed|ing)|(?:passed away|died|bereave(?:d|ment))|funeral|"
        r"(?:seriously |really )?ill(?:ness)?\b|in hospital|diagnos(?:ed|is)|cancer)", re.I),
    "distress": re.compile(
        r"\b(?:I'?m (?:so |really )?(?:stressed|anxious|scared|panicking|upset|overwhelmed)|"
        r"this is (?:too much|stressing me)|I can'?t (?:cope|deal with this))\b", re.I),
    "complaint": re.compile(r"\b(?:complain(?:t)?|this is (?:harassment|unacceptable)|stop calling)\b", re.I),
}

REASONS = (*TRIGGERS, "confused_twice", "identity_not_verified", "out_of_scope", "other")


def reason_category(text: str) -> str:
    """Map free text (a reason the model gave) to a fixed category.

    Only categories are logged or used as a shutdown reason: model-written text can
    repeat what the customer said, including personal details, and logs and events
    must hold none.
    """
    for reason, pattern in TRIGGERS.items():
        if pattern.search(text):
            return reason
    # the model describes the customer in the third person ("lost his job"), so match keywords
    lowered = text.lower()
    for reason, words in _REASON_KEYWORDS:
        if any(w in lowered for w in words):
            return reason
    return "other"


_REASON_KEYWORDS = (
    ("money_trouble", ("job", "money", "afford", "arrears", "hardship", "financial", "redundan", "debt",
                       "behind on", "payments")),
    ("life_event", ("bereave", "died", "death", "passed away", "illness", " ill ", "hospital", "divorc", "separat")),
    ("distress", ("distress", "upset", "anxious", "stress", "overwhelm", "crying")),
    ("complaint", ("complain",)),
    ("asked_for_person", ("person", "human", "specialist", "advisor", "adviser")),
    ("identity_not_verified", ("verif", "identity")),
    ("confused_twice", ("confus",)),
    ("out_of_scope", ("scope", "outside", "not about the renewal")),
)


CONFUSION = re.compile(
    r"\b(?:I (?:don'?t|do not) (?:understand|follow|get it)|what do you mean|I'?m (?:confused|lost)|"
    r"(?:sorry, )?(?:what|pardon)\?$|you'?re not making sense)", re.I)
CONFUSION_LIMIT = 2


@dataclass
class HandoffMonitor:
    """Watches borrower turns for one call. `check` returns a reason when the call must go to a person."""

    confusion: int = 0
    reasons: list[str] = field(default_factory=list)

    def check(self, borrower_text: str) -> str | None:
        for reason, pattern in TRIGGERS.items():
            if pattern.search(borrower_text):
                self.reasons.append(reason)
                return reason
        if CONFUSION.search(borrower_text.strip()):
            self.confusion += 1
            if self.confusion >= CONFUSION_LIMIT:
                self.reasons.append("confused_twice")
                return "confused_twice"
        return None
