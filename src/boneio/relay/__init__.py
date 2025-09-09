"""Relay module."""

from boneio.relay.mcp import MCPRelay
from boneio.relay.pca import PWMPCA
from boneio.relay.pcf import PCFRelay

__all__ = ["MCPRelay", "PWMPCA", "PCFRelay"]
