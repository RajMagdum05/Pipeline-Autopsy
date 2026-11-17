# autopsy-sdk

`autopsy-sdk` is a thin semantic layer over the OpenTelemetry API. It adds the
Pipeline Autopsy trace-contract fields to ordinary spans and leaves provider and
exporter configuration to the host application.

```python
import autopsy_sdk as autopsy

autopsy.set_pipeline("toy-summarizer", "0.1.0")

with autopsy.run(items={"input-1": "source"}) as run:
    with autopsy.stage("fetch", inputs=["source-id"]) as stage:
        page_id = stage.record_artifact("page", {"title": "Hello", "body": "..."})
        stage.check("page.present", kind="schema", result="pass", action="continued",
                    target=page_id)
    run.set_outcome("success")
```

Install the core package with `pip install autopsy-sdk`. The core runtime
dependency is only `opentelemetry-api`; it never creates or replaces the host's
tracer provider. Install the `configure` extra for the optional S1.2 provider
setup, or the `upload` extra for the optional evidence uploader.

Use `autopsy_sdk.propagate.submit(executor, fn, *args, **kwargs)` when work is
submitted to a thread pool. Tests can use `autopsy_sdk.testing.InMemoryCapture`
and `assert_contract` without contacting a collector.

Error status descriptions are sanitized before they are attached to spans.
Document content, prompts, extracted values, and exception events are never
captured by the SDK.
