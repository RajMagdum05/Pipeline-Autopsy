"""
Automatic and programmatic instrumentation helpers for customer AI applications.
"""
from typing import Any, Callable, Dict, Optional
from autopsy_sdk.client import Autopsy


def instrument_function(
    autopsy_client: Autopsy,
    name: Optional[str] = None,
    attributes: Optional[Dict[str, Any]] = None,
) -> Callable:
    """
    Wraps a callable in an Autopsy span context.
    """
    return autopsy_client.trace_fn(name=name, attributes=attributes)
