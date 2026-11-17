---
id: pb_upstream_timeout
title: Investigate an unavailable or timed out upstream provider
match:
  error_type: TimeoutError
  classification: SERVICE_EXECUTION_FAILURE
---
1. Check provider health, request latency, and timeout settings for the failing operation.
2. Confirm retries use bounded backoff and do not repeat non-idempotent work.
3. Compare the operation's input and output artifacts to identify whether the failure is provider-side or local.
