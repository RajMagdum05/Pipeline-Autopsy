"""Compatibility import path for the backend application package."""

from pathlib import Path

__path__ = [str(Path(__file__).resolve().parent.parent / "backend" / "app")]
