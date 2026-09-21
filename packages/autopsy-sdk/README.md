# Pipeline Autopsy Python SDK (`autopsy-sdk`)

Lightweight, fail-safe customer-side SDK for **Pipeline Autopsy** AI observability and automated root-cause analysis.

The SDK instruments your customer application using standard **OpenTelemetry** and exports telemetry via **OTLP/HTTP** directly to your Autopsy backend. All deep graph reconstruction, failure detection, RCA, Gemini diagnosis, and investigation agents remain strictly server-side.

---

## Installation

```bash
pip install autopsy-sdk
```

---

## Quickstart

### 1. Configuration & Initialization

Configure your API key, Autopsy backend endpoint, and project ID either via environment variables or programmatically:

#### Via Environment Variables:
```bash
export AUTOPSY_API_KEY="sk_live_customer_key_123"
export AUTOPSY_ENDPOINT="http://localhost:8000"
export AUTOPSY_PROJECT_ID="proj_ai_assistant"
export AUTOPSY_SERVICE_NAME="chat_service"
```

#### In Python:
```python
from autopsy_sdk import Autopsy

autopsy = Autopsy(
    api_key="sk_live_customer_key_123",
    endpoint="http://localhost:8000",
    project_id="proj_ai_assistant",
    service_name="chat_service",
)
```

---

### 2. Tracing Spans with Context Managers

Wrap critical pipeline stages using `with autopsy.span(...)`:

```python
with autopsy.span("query_vector_db", attributes={"top_k": 5, "index": "knowledge_v2"}) as span:
    results = vector_db.query(user_query)
    span.set_attribute("results.count", len(results))
    span.add_event("chunks_retrieved", {"count": len(results)})
```

If an exception occurs inside the `with autopsy.span` block, the SDK automatically:
1. Records the exception details and traceback as an OpenTelemetry exception event.
2. Marks the span status as `ERROR`.
3. Re-raises the exception so your application's error handling and control flow are preserved.

---

### 3. Tracing Functions with Decorators

```python
@autopsy.trace_fn("generate_llm_response")
def generate_response(prompt: str) -> str:
    return llm.predict(prompt)
```

---

### 4. Fail-Safe Guarantee

If your network is interrupted or the Autopsy backend is temporarily unavailable, the SDK catches export errors safely and emits a warning. **Your customer application will never crash** due to telemetry export failures.

---

### 5. Multi-Tenant Project Isolation

Every trace emitted includes your `project_id` and is securely authenticated via your `AUTOPSY_API_KEY`. Telemetry from different projects is strictly isolated and can never be queried or accessed across tenants.

---

### 6. Querying Investigation Reports

Once telemetry is received by Autopsy, query the complete investigation report via the Autopsy REST API:

```bash
curl -H "X-Autopsy-Api-Key: sk_live_customer_key_123" \
     -H "X-Autopsy-Project-Id: proj_ai_assistant" \
     http://localhost:8000/api/v1/executions/{execution_id}/report
```
