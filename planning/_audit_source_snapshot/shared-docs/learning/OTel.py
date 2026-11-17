from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor,
    ConsoleSpanExporter,
)

# 1. Create the trace engine
tracer_provider = TracerProvider()

# 2. Say where finished spans should go
# For now, print them in the terminal
tracer_provider.add_span_processor(
    SimpleSpanProcessor(ConsoleSpanExporter())
)

# 3. Make this the global tracer provider
trace.set_tracer_provider(tracer_provider)

# 4. Create a tracer for your application
tracer = trace.get_tracer("pipeline.autopsy.lesson1")

# 5. Create one trace with one span
with tracer.start_as_current_span("insurance_claim_execution") as span:
    span.set_attribute("claim_id", "CLAIM-001")
    span.set_attribute("execution_id", "EXEC-001")

    print("Insurance claim execution started")