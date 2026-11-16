"""hermes-skill-rollback-guard — clean skill-rollback residue on pre-fix Hermes cores.

Native Hermes plugin. Registers a ``tool_execution`` middleware that clears the
``<name>.rollback-broken`` symlink residue a ``skill_manage`` batch rollback leaves on cores whose
rollback cleanup is symlink-blind. It cleans up only; it never patches core. See
``rollback_guard.py`` for the mechanism and ``README.md`` for the contract and limitations.
"""

from __future__ import annotations

from .rollback_guard import (
    CORE_MODULE_NAME,
    FIX_SENTINEL,
    RESIDUE_SUFFIX,
    ROLLBACK_SENTINEL,
    ROLLBACK_TOOL_NAME,
    STATE_FIXED,
    STATE_UNFIXED,
    STATE_UNKNOWN,
    TOOL_EXECUTION_MIDDLEWARE,
    clean_residue,
    core_fix_state,
    find_residue,
    find_unsafe_residue,
    guard_once,
    guard_tool_execution,
    is_residue,
    is_safe_residue,
    register,
    skills_roots,
)

__version__ = "0.1.0"

__all__ = [
    "register",
    "guard_tool_execution",
    "guard_once",
    "core_fix_state",
    "clean_residue",
    "find_residue",
    "find_unsafe_residue",
    "is_residue",
    "is_safe_residue",
    "skills_roots",
    "CORE_MODULE_NAME",
    "FIX_SENTINEL",
    "ROLLBACK_SENTINEL",
    "RESIDUE_SUFFIX",
    "ROLLBACK_TOOL_NAME",
    "TOOL_EXECUTION_MIDDLEWARE",
    "STATE_FIXED",
    "STATE_UNFIXED",
    "STATE_UNKNOWN",
    "__version__",
]
