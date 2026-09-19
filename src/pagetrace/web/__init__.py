"""Packaged PageTrace evidence-first web application."""

from __future__ import annotations

from pathlib import Path


def default_web_root() -> Path:
    """Return the packaged, pre-built web application directory."""

    return Path(__file__).parent / "dist"


__all__ = ["default_web_root"]
