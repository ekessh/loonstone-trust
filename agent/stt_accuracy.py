"""Speech-to-text accuracy for the agent's Flux STT, as word error rate (WER).

    .venv/Scripts/python -m agent.stt_accuracy

For each call folder in evidence/calls/ that has both files:

  borrower_said.txt   what the simulated borrower actually said (written by borrower_sim)
  transcript.txt      the BORROWER lines are what the agent's STT heard

it writes stt_accuracy.json with the WER over the whole call, then prints a summary.
The whole call is compared as one text because Flux may split or merge turns.

Method and its limits:
- Both files are redacted on disk. [NAME], [ACCOUNT], [AMOUNT] and [PERSONAL] compare
  as single words. A misheard surname is also redacted to [NAME], so the WER on
  redacted text cannot see name errors. Name errors are therefore reported
  separately: from the alignment (a reference [NAME] matched to anything else), and
  from stt_names.json, which renewal_agent writes from the unredacted text in memory
  (counts only, no names).
- Spelling variants are normalised before comparing ("call back"/"callback",
  "all right"/"alright", "ok"/"okay"), so they are not counted as recognition errors.
- The reference is the simulator's text, not what its TTS actually voiced, and the
  voice is one synthetic standard-accent English voice. This understates real error,
  and the known limitation (strong regional accents, poor lines) is not measured here;
  the accessibility and multi-voice tests at validation are the numbers that count.
- No headline WER is reported below MIN_WORDS reference words: the summary says
  "insufficient sample" instead, and always shows the word and call counts.
"""

from __future__ import annotations

import json
import re
import sys
from .config import EVIDENCE_CALLS as CALLS
MIN_WORDS = 200

_COMPOUNDS = [
    (r"\bcall back\b", "callback"), (r"\ball right\b", "alright"), (r"\bok\b", "okay"),
    (r"\bany more\b", "anymore"), (r"\bsome time\b", "sometime"), (r"\bmhm+\b", "mhm"),
]


def words(text: str) -> list[str]:
    text = re.sub(r"\[(\w+)\]", r" \1 ", text.lower())  # [NAME] -> name, one word
    for pattern, repl in _COMPOUNDS:
        text = re.sub(pattern, repl, text)
    return re.sub(r"[^\w\s']", " ", text).split()


def align(ref: list[str], hyp: list[str]) -> list[tuple[str, str | None, str | None]]:
    """Minimum-edit alignment as (op, ref_word, hyp_word); op in ok/sub/del/ins."""
    n, m = len(ref), len(hyp)
    cost = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        cost[i][0] = i
    for j in range(m + 1):
        cost[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            same = ref[i - 1] == hyp[j - 1]
            cost[i][j] = min(cost[i - 1][j - 1] + (0 if same else 1), cost[i - 1][j] + 1, cost[i][j - 1] + 1)
    ops, i, j = [], n, m
    while i or j:
        if i and j and cost[i][j] == cost[i - 1][j - 1] + (0 if ref[i - 1] == hyp[j - 1] else 1):
            ops.append(("ok" if ref[i - 1] == hyp[j - 1] else "sub", ref[i - 1], hyp[j - 1]))
            i, j = i - 1, j - 1
        elif i and cost[i][j] == cost[i - 1][j] + 1:
            ops.append(("del", ref[i - 1], None))
            i -= 1
        else:
            ops.append(("ins", None, hyp[j - 1]))
            j -= 1
    return ops[::-1]


def wer(reference: str, hypothesis: str) -> dict:
    """Word error rate with substitution, deletion and insertion counts, plus name-token errors."""
    ref, hyp = words(reference), words(hypothesis)
    ops = align(ref, hyp)
    s = sum(o[0] == "sub" for o in ops)
    d = sum(o[0] == "del" for o in ops)
    n = sum(o[0] == "ins" for o in ops)
    name_errors = sum(o[0] in ("sub", "del") and o[1] == "name" for o in ops) + \
        sum(o[0] in ("sub", "ins") and o[2] == "name" and o[1] != "name" for o in ops)
    return {
        "wer": round((s + d + n) / len(ref), 4) if ref else 0.0,
        "reference_words": len(ref),
        "substitutions": s,
        "deletions": d,
        "insertions": n,
        "name_token_errors_in_alignment": name_errors,
    }


def heard_by_agent(transcript: str) -> str:
    return "\n".join(l.split(":", 1)[1] for l in transcript.splitlines() if l.startswith("BORROWER:"))


def main() -> int:
    results = []
    for call in sorted(CALLS.iterdir()):
        said, transcript = call / "borrower_said.txt", call / "transcript.txt"
        if not (said.exists() and transcript.exists()):
            continue
        result = {"call": call.name, "stt_model": "flux-general-en", "borrower_voice": "aura-2-helena-en",
                  "method": "redacted text, compounds normalised (agent/stt_accuracy.py docstring)",
                  **wer(said.read_text(encoding="utf-8"), heard_by_agent(transcript.read_text(encoding="utf-8")))}
        names = call / "stt_names.json"
        if names.exists():
            result["name_hearings_unredacted"] = json.loads(names.read_text(encoding="utf-8"))
        (call / "stt_accuracy.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        results.append(result)
        print(f"{call.name}: {result['reference_words']} words, WER {result['wer']:.1%} "
              f"({result['substitutions']}S/{result['deletions']}D/{result['insertions']}I), "
              f"name-token errors {result['name_token_errors_in_alignment']}")
    if not results:
        print("No call has both borrower_said.txt and transcript.txt yet; run a call first.")
        return 0
    total = sum(r["reference_words"] for r in results)
    errors = sum(r["substitutions"] + r["deletions"] + r["insertions"] for r in results)
    if total < MIN_WORDS:
        print(f"All calls: insufficient sample ({total} words in {len(results)} call(s); "
              f"a headline WER needs at least {MIN_WORDS}). Pooled rate so far {errors / total:.1%}, not for reporting.")
    else:
        print(f"All calls: WER {errors / total:.1%} over {total} words in {len(results)} calls")
    return 0


if __name__ == "__main__":
    sys.exit(main())
