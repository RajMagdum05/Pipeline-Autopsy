"""Compatibility shim for the former OTLP adapter location."""

from autopsy.ingest.otlp import (
    OTLPAdapter,
    _parse_attributes,
    _parse_hex_id,
    _parse_otlp_value,
    _parse_span_kind,
    _parse_status_code,
    _parse_timestamp,
)

__all__ = ["OTLPAdapter"]
