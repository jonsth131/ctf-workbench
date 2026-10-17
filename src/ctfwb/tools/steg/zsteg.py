"""Zsteg command helper."""

from ctfwb.tools.external import ExternalToolHelper

ZSTEG = ExternalToolHelper(name="zsteg", executable="zsteg")

__all__ = ["ZSTEG"]
