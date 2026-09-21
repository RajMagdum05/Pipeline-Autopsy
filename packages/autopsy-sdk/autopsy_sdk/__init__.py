"""
Pipeline Autopsy Python SDK.

Lightweight OpenTelemetry-powered instrumentation SDK for customer AI pipelines.
"""
from autopsy_sdk.config import AutopsyConfig
from autopsy_sdk.client import Autopsy, AutopsySpan
from autopsy_sdk.instrumentation import instrument_function

__all__ = [
    "Autopsy",
    "AutopsySpan",
    "AutopsyConfig",
    "instrument_function",
]

__version__ = "0.1.0"
