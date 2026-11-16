"""Shared helpers for the rollback-guard tests."""

from __future__ import annotations

import contextlib
import importlib.util
import shutil
import sys
import types
from pathlib import Path

import rollback_guard as g

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_MODULE_NAME = "tools.skill_manager_batch"

#: Where a real pre-fix ``skill_manager_batch.py`` may be found for the acceptance test. Never a
#: shipped dependency: the repo carries no Hermes core source. Set ``PREFIX_CORE`` to point at one.
PREFIX_CORE_ENV = "PREFIX_CORE"
#: Shipped faithful reconstruction of the pre-fix rollback, used when no real pre-fix core exists.
PREFIX_CORE_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "prefix_core" / "skill_manager_batch.py"

#: Files that make up the installable plugin (everything the loader needs).
PLUGIN_FILES = ("plugin.yaml", "__init__.py", "rollback_guard.py")

#: The plugin's directory/manifest name.
PLUGIN_NAME = "hermes-skill-rollback-guard"


def stage_plugin(home: Path, name: str) -> Path:
    """Copy the plugin into ``<home>/plugins/<name>`` the way an install would."""
    dest = Path(home) / "plugins" / name
    dest.mkdir(parents=True, exist_ok=True)
    for rel in PLUGIN_FILES:
        shutil.copy2(REPO_ROOT / rel, dest / rel)
    return dest


@contextlib.contextmanager
def _fake_core(*, fixed: bool):
    """Install a stand-in ``tools.skill_manager_batch`` in ``sys.modules`` for the duration."""
    module = types.ModuleType(CORE_MODULE_NAME)
    module._restore_snapshot = lambda *args, **kwargs: None
    if fixed:
        module._discard_tree = lambda path: None
    had = CORE_MODULE_NAME in sys.modules
    previous = sys.modules.get(CORE_MODULE_NAME)
    sys.modules[CORE_MODULE_NAME] = module
    try:
        yield module
    finally:
        if had:
            sys.modules[CORE_MODULE_NAME] = previous
        else:
            sys.modules.pop(CORE_MODULE_NAME, None)


def unfix_core():
    """Context manager: simulate a pre-fix core (no symlink-safe helper)."""
    return _fake_core(fixed=False)


def fix_core():
    """Context manager: simulate an already-fixed core (symlink-safe helper present)."""
    return _fake_core(fixed=True)


@contextlib.contextmanager
def absent_core():
    """Context manager: remove the core module so the guard cannot classify it."""
    had = CORE_MODULE_NAME in sys.modules
    previous = sys.modules.get(CORE_MODULE_NAME)
    sys.modules.pop(CORE_MODULE_NAME, None)
    try:
        yield
    finally:
        if had:
            sys.modules[CORE_MODULE_NAME] = previous


def find_prefix_core() -> Path | None:
    """Locate a pre-fix ``skill_manager_batch.py``: ``PREFIX_CORE`` if set, else the shipped fixture.

    The fixture is a faithful reconstruction (see ``tests/fixtures/prefix_core``), so the acceptance
    test exercises the pre-fix code path on every machine.
    """
    import os

    env = os.environ.get(PREFIX_CORE_ENV, "")
    if env and Path(env).is_file():
        return Path(env)
    return PREFIX_CORE_FIXTURE if PREFIX_CORE_FIXTURE.is_file() else None


@contextlib.contextmanager
def real_prefix_core(path: Path):
    """Install the *real* pre-fix core module as ``tools.skill_manager_batch`` for the duration.

    The actual Hermes ``tools`` package is imported first and only its one submodule is overridden,
    so ``from tools.registry import tool_error`` and every other core import keep resolving to the
    installed package (a synthetic ``tools`` shim would break them).
    """
    tools = sys.modules.get("tools")
    if tools is None:
        import tools  # the real package on sys.path
    from importlib.machinery import SourceFileLoader

    name = CORE_MODULE_NAME
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    had = name in sys.modules
    previous = sys.modules.get(name)
    previous_attr = getattr(tools, "skill_manager_batch", None)
    sys.modules[name] = module
    setattr(tools, "skill_manager_batch", module)
    try:
        loader.exec_module(module)  # module-global imports only: stdlib, no core dispatch
        yield module
    finally:
        if had:
            sys.modules[name] = previous
        else:
            sys.modules.pop(name, None)
        if previous_attr is not None:
            setattr(tools, "skill_manager_batch", previous_attr)
        elif hasattr(tools, "skill_manager_batch"):
            delattr(tools, "skill_manager_batch")


def plant_residue(link: Path, target: Path) -> Path:
    """Create a ``.rollback-broken`` symlink at *link* pointing at *target* (need not exist)."""
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target, target_is_directory=True)
    return link


def link_skill(root: Path, name: str, target: Path) -> Path:
    """Create the live canonical skill entry ``root/name`` as a symlink to *target*.

    The production profile installs each skill as a symlink into its canonical source directory;
    the guard treats such an entry as the live skill beside a residue link.
    """
    root.mkdir(parents=True, exist_ok=True)
    link = root / name
    link.symlink_to(target, target_is_directory=True)
    return link


def plant_safe_residue(root: Path, name: str, target: Path, *, link_dir: Path) -> Path:
    """Plant residue *and* the live canonical skill beside it, the shape the guard may remove.

    ``root/name`` becomes a live skill — a symlink into *link_dir* (created with a ``SKILL.md``
    if missing, since a skill dir is only "live" when it carries one) — and
    ``root/<name>.rollback-broken`` the leftover link, exactly as a *successful* rollback leaves
    them.
    """
    root.mkdir(parents=True, exist_ok=True)
    if not link_dir.exists():
        link_dir.mkdir(parents=True, exist_ok=True)
    skill_md = link_dir / "SKILL.md"
    if not skill_md.exists():
        skill_md.write_text(f"# {name}\n")
    link_skill(root, name, link_dir)
    return plant_residue(root / f"{name}{g.RESIDUE_SUFFIX}", target)

