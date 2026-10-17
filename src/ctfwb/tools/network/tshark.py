"""Tshark command helper."""

from ctfwb.tools.external import ExternalToolHelper

TSHARK = ExternalToolHelper(name="tshark", executable="tshark")

__all__ = ["TSHARK"]
