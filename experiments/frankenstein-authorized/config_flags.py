"""Fail-closed parsing for security-sensitive opt-in environment flags."""
import os

_TRUTHY = frozenset({"1", "true", "yes"})


def env_opt_in(name: str, default: str = "0") -> bool:
    """Enable only for explicit, stripped, case-insensitive truthy values."""
    return os.getenv(name, default).strip().lower() in _TRUTHY
