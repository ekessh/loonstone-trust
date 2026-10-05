from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agent.redaction import Redactor
from agent.telemetry import RedactingSpanExporter


def test_spans_are_redacted_before_export():
    sink = InMemorySpanExporter()
    redactor = Redactor.from_offer_record()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(RedactingSpanExporter(sink, redactor)))
    tracer = provider.get_tracer("test")

    with tracer.start_as_current_span("agent_turn") as span:
        span.set_attribute("lk.pii.user_input", "Hi, this is Alex Carrow, account LT-5520-3371-08")
        span.set_attribute("gen_ai.output.messages", ["The charge is €4,210.55. Your rate is 3.65%."])
        span.set_attribute("lk.function_tool.arguments",
                           '{"date_of_birth": "12 March 1984", "address_first_line": "14 Harbour View"}')
        span.set_attribute("lk.response.ttfb", 0.41)
        span.add_event("user_message", {"content": "My balance is 285,400.00, Alex here"})

    (exported,) = sink.get_finished_spans()
    blob = repr(dict(exported.attributes)) + repr([dict(e.attributes) for e in exported.events])
    assert redactor.leaks(blob) == []
    for raw in ("4,210.55", "285,400.00", "LT-5520-3371-08", "1984", "Harbour"):
        assert raw not in blob
    assert "3.65%" in blob  # the quoted rate stays visible
    assert exported.attributes["lk.response.ttfb"] == 0.41  # timings untouched
