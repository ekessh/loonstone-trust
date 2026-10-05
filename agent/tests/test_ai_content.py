from agent.config import SYSTEM_ID
from agent.renewal_agent import TTS_MODEL, ai_content_label


def test_marks_agent_lines_including_multiline_turns():
    transcript = [
        "AGENT: Hello, am I speaking with Alex?",
        "BORROWER: Yes.",
        "AGENT: Thanks.\n\nI'm calling about your renewal.",
        "BORROWER: Sure.",
    ]
    label = ai_content_label("renewal-test", transcript, "v1.0")
    assert label["ai_generated_line_ranges"] == [[1, 1], [3, 5]]
    assert label["ai_generated"]["tts"] == TTS_MODEL
    assert label["ai_generated"]["agent_version"] == "v1.0"
    assert label["ai_generated"]["synthetic_voice"] is True
    assert label["system_id"] == SYSTEM_ID


def test_line_ranges_match_written_transcript():
    transcript = ["AGENT: one\ntwo", "BORROWER: three", "AGENT: four"]
    written = "\n".join(transcript).splitlines()
    for start, end in ai_content_label("r", transcript)["ai_generated_line_ranges"]:
        assert written[start - 1].startswith("AGENT:")
        assert all(not l.startswith("BORROWER:") for l in written[start - 1:end])


def test_provenance_label_is_not_an_art_50_2_mark():
    label = ai_content_label("r", ["AGENT: hi", "BORROWER: hello"])
    assert label["label"] == "loonstone-transcript-provenance/v1"
    assert label["is_art_50_2_output_mark"] is False


def test_simulated_borrower_is_marked_synthetic():
    assert ai_content_label("r", ["BORROWER: hi"], simulated=True)["borrower_lines"]["ai_generated"] is True
    assert ai_content_label("r", ["BORROWER: hi"], simulated=False)["borrower_lines"]["ai_generated"] is False
