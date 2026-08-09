"""Canonical ZEL Alpha Engine family registry.

This package defines research contracts only. It has no paper/live/order authority.
"""

from .registry import ALPHA_FAMILIES, AlphaFamilySpec, get_alpha_family

__all__ = ["ALPHA_FAMILIES", "AlphaFamilySpec", "get_alpha_family"]
