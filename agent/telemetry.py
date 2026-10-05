"""Tracing to the local Langfuse, with personal data redacted before export.

LiveKit Agents emits OpenTelemetry spans for every session, user turn, agent
turn, LLM call and TTS call, with per-step timings. This module sends them to
Langfuse's OTLP endpoint through RedactingSpanExporter, which rewrites every
span's attributes and events with agent.redaction before they leave the
process. Nothing unredacted reaches Langfuse.

LiveKit's own PII filter drops conversation content entirely; we keep content
(the trace must show each turn) and mask only the personal data, so the
LiveKit filter is set to allow_pii=True and this exporter does the redaction.

Controls: GDPR Art. 5(1)(c) and Art. 32; ISO/IEC 42001 A.7.4, A.6.2.8 event logs;
NIST AI RMF MEASURE 2.10 privacy risk. Traces are hosted locally, never by a third party.
"""

from __future__ import annotations

import base64
import os
from collections.abc import Sequence

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Event, ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult

from .redaction import Redactor


class RedactingSpanExporter(SpanExporter):
    def __init__(self, inner: SpanExporter, redactor: Redactor):
        self._inner = inner
        self._redactor = redactor

    def _redact(self, span: ReadableSpan) -> ReadableSpan:
        r = self._redactor
        events = tuple(
            Event(name=e.name, attributes=r.attributes(e.attributes), timestamp=e.timestamp)
            for e in span.events
        )
        return ReadableSpan(
            name=r.text(span.name),
            context=span.context,
            parent=span.parent,
            resource=span.resource,
            attributes=r.attributes(span.attributes),
            events=events,
            links=span.links,
            kind=span.kind,
            status=span.status,
            start_time=span.start_time,
            end_time=span.end_time,
            instrumentation_scope=span.instrumentation_scope,
        )

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        return self._inner.export([self._redact(s) for s in spans])

    def shutdown(self) -> None:
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._inner.force_flush(timeout_millis)


def langfuse_exporter() -> OTLPSpanExporter:
    host = os.environ.get("LANGFUSE_HOST", "http://localhost:3000").rstrip("/")
    auth = base64.b64encode(
        f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}".encode()
    ).decode()
    return OTLPSpanExporter(
        endpoint=f"{host}/api/public/otel/v1/traces",
        headers={"Authorization": f"Basic {auth}"},
    )


def setup(service: str, metadata: dict[str, str]) -> TracerProvider:
    """Install a redacting Langfuse tracer for this job. Call once per job process."""
    from livekit.agents.telemetry import set_tracer_provider

    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    provider.add_span_processor(
        BatchSpanProcessor(RedactingSpanExporter(langfuse_exporter(), Redactor.from_offer_record()))
    )
    # metadata lands on every span: Langfuse groups a call's traces by session id
    set_tracer_provider(provider, metadata=metadata, allow_pii=True)
    return provider
