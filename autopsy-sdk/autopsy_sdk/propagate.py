"""Context propagation helpers for concurrent work."""
from contextvars import copy_context


def submit(executor, fn, *args, **kwargs):
    """Submit a callable while carrying the current contextvars into its thread."""
    context = copy_context()
    return executor.submit(context.run, fn, *args, **kwargs)
