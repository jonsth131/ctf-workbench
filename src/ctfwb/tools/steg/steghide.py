"""Steghide command helper."""

from ctfwb.tools.external import ExternalToolHelper

STEGHIDE = ExternalToolHelper(name="steghide", executable="steghide")

__all__ = ["STEGHIDE"]
