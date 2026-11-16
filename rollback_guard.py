"""Clean skill-rollback residue on pre-fix Hermes cores — cleanup only, never a core patch.

Background
----------
Hermes core applies a ``skill_manage`` batch atomically: it snapshots every touched skill and,
if any operation fails, rolls the whole batch back. Rolling one skill back renames the broken
skill directory aside as ``<name>.rollback-broken`` and then deletes that aside path.

On a core that predates the symlink-safe removal helper, that deletion is
``shutil.rmtree(aside, ignore_errors=True)``. ``shutil.rmtree`` refuses a symbolic link and
``ignore_errors=True`` swallows the refusal, so **every rollback of a symlinked skill leaves the
``<name>.rollback-broken`` link behind** (a stale one is merely replaced by a fresh one). A real
directory is removed normally, so only symlinked skills leave residue.

Why this plugin does not patch core
-----------------------------------
The Hermes plugin contract forbids a plugin from customizing Hermes "by replacing or wrapping
core functions, modules, private tables or other internal implementation details", and the
plugin catalogue refuses such a plugin at admission. So this plugin never rebinds
``tools.skill_manager_batch`` or ``shutil``. It uses the supported ``tool_execution`` middleware
seam to clean the residue a rollback leaves, right after each ``skill_manage`` call, and only
while the running core still exhibits the bug.

Guard
-----
Activation is a live capability probe, not a version string:

* ``fixed``   — the core module defines the symlink-safe helper: no-op.
* ``unfixed`` — the module is present, exposes the rollback entry point and lacks the helper:
  residue is possible, so the guard runs.
* ``unknown`` — the module is absent, unimportable, or an unrecognized shape: fail safe, no-op.

Nothing is ever deleted except a path whose name ends in ``.rollback-broken`` that is a **symbolic
link** — the only shape the bug produces. A regular file or a directory with that name (neither of
which the bug produces) is never touched: a regular file may hold unique user data, and removing a
directory would mean a recursive delete a plugin should not perform.

Scope
-----
The default cleanup scans only the **active profile's writable skills dir** — the single tree
``skill_manage`` installs into and therefore the only one the rollback bug can leave residue in.
Shared/builtin, project, ``skills.create_dir`` and external roots, and every other profile, are
deliberately **out of scope**: a plugin must never sweep a skill tree it does not own. Callers that
genuinely need the wider tree (isolated tests, explicit backfills) use :func:`all_skills_roots`.

Safety
------
Removing a residue link must never lose the only surviving copy of a skill. The pre-fix rollback
renames the broken skill aside (``<name>.rollback-broken``) and then fails to delete the link; a
*successful* rollback has already recreated the skill under its canonical name **beside** the
residue, so the residue is a pure duplicate and unlinking it loses nothing. So the guard removes a
residue entry only when a **live canonical sibling** exists next to it — the base name with every
``.rollback-broken`` suffix stripped, present as a skill directory (or a symlink that resolves into
one) that actually contains a ``SKILL.md``. When that sibling is absent, or is present but is not a
real skill (no ``SKILL.md``), the residue may be the *only* remaining reference to a skill whose
restore did not complete (``_restore_snapshot`` re-raises before ``aside.rename(pre_dir)``, or a
hand-interrupted rollback), so the guard leaves it in place. ``os.unlink`` never follows a symlink,
so a link's target directory is never touched regardless.
"""

from __future__ import annotations

import importlib
import logging
import os
import stat
import sys
import threading
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

#: Core module whose rollback cleanup this plugin works around.
CORE_MODULE_NAME = "tools.skill_manager_batch"
#: Attribute the fixed core exposes but the pre-fix core does not. Absence => pre-fix.
FIX_SENTINEL = "_discard_tree"
#: Rollback entry point a pre-fix core exposes; its presence confirms the shape we understand.
ROLLBACK_SENTINEL = "_restore_snapshot"
#: Suffix core gives the aside path while it rolls a skill back.
RESIDUE_SUFFIX = ".rollback-broken"
#: The one tool whose failure can leave this residue.
ROLLBACK_TOOL_NAME = "skill_manage"
#: Skills live at ``<root>/<name>`` or ``<root>/<category>/<name>``; scan no deeper than that.
MAX_SKILL_DEPTH = 2
#: Supported middleware kind that wraps tool execution (a documented extension seam).
TOOL_EXECUTION_MIDDLEWARE = "tool_execution"

STATE_FIXED = "fixed"
STATE_UNFIXED = "unfixed"
STATE_UNKNOWN = "unknown"

_REGISTER_LOCK = threading.Lock()
_REGISTER_MARKER = "_hermes_skill_rollback_guard_registered"


def core_fix_state() -> str:
    """Classify the running core's rollback cleanup: ``fixed``, ``unfixed`` or ``unknown``.

    Cheap and side-effect free: it prefers the already-imported module and only imports the core
    module as a fallback (the module is always imported by the time a ``skill_manage`` call runs).
    """
    module = sys.modules.get(CORE_MODULE_NAME)
    if module is None:
        try:
            module = importlib.import_module(CORE_MODULE_NAME)
        except Exception:  # not importable / renamed: we cannot reason about it
            return STATE_UNKNOWN
    if hasattr(module, FIX_SENTINEL):
        return STATE_FIXED
    if hasattr(module, ROLLBACK_SENTINEL):
        return STATE_UNFIXED
    return STATE_UNKNOWN


def active_skill_root() -> Optional[Path]:
    """The active profile's live, writable skills dir — the one tree ``skill_manage`` installs into.

    ``None`` when the public ``skill_search_dirs()`` API is unavailable or fails.
    """
    try:
        from tools.skills_tool import skill_search_dirs
    except Exception:
        logger.debug("skills_tool unavailable; no active skill root")
        return None
    try:
        _roots, active = skill_search_dirs()
    except Exception as exc:
        logger.debug("skill_search_dirs() failed: %s", exc)
        return None
    return Path(active) if active is not None else None


def skills_roots() -> list[Path]:
    """The skill directories the middleware cleans by default.

    Exactly the active profile's writable skills root (see :func:`active_skill_root`). The rollback
    bug only ever leaves residue in the tree ``skill_manage`` writes to, so shared/builtin, project,
    ``skills.create_dir`` and external roots — and every other profile — are deliberately excluded:
    a plugin must not sweep a skill tree it does not own. Empty when that root is unavailable.
    """
    active = active_skill_root()
    return [active] if active is not None else []


def all_skills_roots() -> list[Path]:
    """Every skill root the public ``skill_search_dirs()`` API reports, de-duplicated.

    The live profile skills dir first, then the configured roots (project / create-dir / external).
    NOT used by the default cleanup — scanning these would reach shared/external/builtin dirs and
    other profiles. Provided for isolated tests and callers that explicitly opt into the wider tree.
    """
    try:
        from tools.skills_tool import skill_search_dirs
    except Exception:
        logger.debug("skills_tool unavailable; no skill roots to scan")
        return []
    try:
        roots, active = skill_search_dirs()
    except Exception as exc:
        logger.debug("skill_search_dirs() failed: %s", exc)
        return []
    ordered: list[Path] = []
    for candidate in (active, *(directory for _tier, directory in roots)):
        if candidate is None:
            continue
        path = Path(candidate)
        if path not in ordered:
            ordered.append(path)
    return ordered


def is_residue(entry: Path) -> bool:
    """True when *entry* has the residue name and is the shape the bug leaves (a symlink).

    Identification only — it does not say the entry is safe to remove. Use
    :func:`is_safe_residue` for the removal decision.

    The bug's rollback cleanup only ever fails to remove a **symlink** — ``shutil.rmtree`` refuses
    a symbolic link. So a regular file with the suffix is deliberately NOT residue (it could be
    unique user data), and neither is a directory with the suffix (removing it would be a recursive
    delete a plugin should not perform).
    """
    if not entry.name.endswith(RESIDUE_SUFFIX):
        return False
    try:
        mode = entry.lstat().st_mode
    except OSError:
        return False
    return stat.S_ISLNK(mode)


def _strip_residue_suffixes(name: str) -> str:
    """``x.rollback-broken.rollback-broken`` -> ``x`` (repeated rollbacks can chain a suffix)."""
    base = name
    while base.endswith(RESIDUE_SUFFIX):
        base = base[: -len(RESIDUE_SUFFIX)]
    return base


def _has_live_canonical_sibling(entry: Path) -> bool:
    """True when a live skill of the residue's canonical name sits beside it.

    This is the data-loss gate. A successful rollback recreates the skill under its canonical
    name next to the residue, so the residue is redundant; a failed or interrupted rollback can
    leave the residue as the *only* surviving reference, in which case this returns False and the
    guard keeps its hands off. The sibling must be a real skill directory — a directory containing
    a ``SKILL.md`` (or a symlink resolving into one). A directory without a ``SKILL.md``, or a
    broken sibling link (the restore did not land), does not qualify, so we also stay out.
    """
    base = _strip_residue_suffixes(entry.name)
    if base == entry.name or not base:  # no residue suffix, or an empty base name
        return False
    sibling = entry.with_name(base)
    if sibling == entry:
        return False
    try:
        # is_dir()/is_file() follow symlinks: a live skill dir or a link into one both qualify, a
        # broken link does not. A skill dir is only a live canonical skill if it carries SKILL.md.
        if not sibling.is_dir():
            return False
        return (sibling / "SKILL.md").is_file()
    except OSError:
        return False


def is_safe_residue(entry: Path) -> bool:
    """True for residue this guard may remove: the bug's shape AND a live canonical sibling.

    The sibling requirement is what guarantees cleanup can never delete the only surviving copy
    of a skill — see the module's *Safety* note.
    """
    return is_residue(entry) and _has_live_canonical_sibling(entry)


def _scan(directory: Path, depth: int, found: list[Path]) -> None:
    """Append every residue-shaped path under *directory* to *found*, never descending a symlink."""
    try:
        with os.scandir(directory) as scan:
            entries = list(scan)
    except OSError:
        return
    for entry in entries:
        path = Path(entry.path)
        if entry.name.endswith(RESIDUE_SUFFIX):
            if is_residue(path):
                found.append(path)
            continue  # never descend into a residue-named entry
        if depth < MAX_SKILL_DEPTH:
            try:
                if entry.is_dir(follow_symlinks=False):
                    _scan(path, depth + 1, found)
            except OSError:
                continue


def _candidate_residue(dirs: Optional[Iterable[Path]] = None) -> list[Path]:
    """Every residue-shaped path under *dirs* (default: :func:`skills_roots`), safe or not."""
    roots = list(dirs) if dirs is not None else skills_roots()
    found: list[Path] = []
    for root in roots:
        _scan(Path(root), 1, found)
    return found


def find_residue(dirs: Optional[Iterable[Path]] = None) -> list[Path]:
    """Every rollback-residue path under *dirs* that is safe to remove.

    Only entries with a live canonical sibling are returned; residue that might be the last
    surviving copy of a skill is withheld (see :func:`find_unsafe_residue`).
    """
    return [p for p in _candidate_residue(dirs) if _has_live_canonical_sibling(p)]


def find_unsafe_residue(dirs: Optional[Iterable[Path]] = None) -> list[Path]:
    """Residue-shaped paths deliberately left in place because removing them could lose data.

    Reported for observability: these entries look like residue but no live canonical skill sits
    beside them, so they may be the only surviving reference and are never unlinked.
    """
    return [p for p in _candidate_residue(dirs) if not _has_live_canonical_sibling(p)]


def clean_residue(
    dirs: Optional[Iterable[Path]] = None, *, dry_run: bool = False
) -> tuple[list[Path], list[tuple[Path, OSError]]]:
    """Remove rollback residue under *dirs*; return ``(removed, failed)``.

    Only residue with a live canonical sibling is removed (see :func:`find_residue`); a residue
    that may be a skill's only surviving copy is preserved. ``os.unlink`` removes the link or file
    itself and never follows it, so a symlink's target is untouched. Idempotent: a second pass over
    the same tree finds nothing.
    """
    removed: list[Path] = []
    failed: list[tuple[Path, OSError]] = []
    for path in find_residue(dirs):
        if dry_run:
            removed.append(path)
            continue
        try:
            os.unlink(path)
            removed.append(path)
        except OSError as exc:
            failed.append((path, exc))
    return removed, failed


def guard_once() -> list[Path]:
    """One guarded cleanup pass; returns the residue paths removed. Never raises.

    A no-op unless the live core reports ``unfixed`` — so on a fixed core, or one we do not
    recognize, nothing is scanned or deleted.
    """
    try:
        if core_fix_state() != STATE_UNFIXED:
            return []
        removed, failed = clean_residue()
        for path, exc in failed:
            logger.debug("could not remove rollback residue %s: %s", path, exc)
        try:
            preserved = find_unsafe_residue()
        except Exception:  # observability only; never fail the pass for it
            preserved = []
        if preserved:
            logger.info(
                "kept %d rollback residue path(s) that may be a skill's only surviving copy: %s",
                len(preserved), ", ".join(str(p) for p in preserved),
            )
        if removed:
            logger.info(
                "removed %d skill-rollback residue path(s): %s",
                len(removed), ", ".join(str(p) for p in removed),
            )
        return removed
    except Exception as exc:  # a cleanup helper must never break the tool call it follows
        logger.debug("skill-rollback guard pass failed: %s", exc)
        return []


def guard_tool_execution(tool_name: str = "", args=None, next_call=None, **_context):
    """``tool_execution`` middleware: run the tool, then clear rollback residue it left.

    Calls ``next_call`` exactly once (the middleware contract) and returns its result unchanged,
    so the tool behaves identically whether or not this plugin is installed.
    """
    if next_call is None:  # not the execution-chain contract we expect; do nothing
        return None
    result = next_call()
    if str(tool_name) == ROLLBACK_TOOL_NAME:
        try:
            guard_once()
        except Exception as exc:  # a cleanup must never break the tool call it follows
            logger.debug("skill-rollback guard raised (ignored): %s", exc)
    return result


def register(ctx) -> None:
    """Plugin entry point: register the ``tool_execution`` middleware (idempotent per context)."""
    with _REGISTER_LOCK:
        if getattr(ctx, _REGISTER_MARKER, False):
            logger.debug("register() called twice for the same context; ignoring")
            return
        ctx.register_middleware(TOOL_EXECUTION_MIDDLEWARE, guard_tool_execution)
        try:
            setattr(ctx, _REGISTER_MARKER, True)
        except Exception:  # a context that disallows attribute writes: registration is idempotent anyway
            logger.debug("could not mark context as registered; duplicate registration is harmless")
