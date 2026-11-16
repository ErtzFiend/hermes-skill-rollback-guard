"""Tests for the capability guard: fixed / unfixed / unknown classification and its effects."""

from __future__ import annotations

import os

import pytest

import rollback_guard as g
from _support import absent_core, fix_core, plant_residue, plant_safe_residue, unfix_core


def test_state_fixed_when_helper_present():
    with fix_core():
        assert g.core_fix_state() == g.STATE_FIXED


def test_state_unfixed_when_rollback_present_without_helper():
    with unfix_core():
        assert g.core_fix_state() == g.STATE_UNFIXED


def test_state_unknown_when_module_unimportable(monkeypatch):
    def boom(name, *args, **kwargs):
        raise ImportError(name)

    monkeypatch.setattr(g.importlib, "import_module", boom)
    with absent_core():
        assert g.core_fix_state() == g.STATE_UNKNOWN


def test_guard_once_is_a_noop_on_a_fixed_core(tmp_path):
    root = tmp_path / "skills"
    root.mkdir()
    link = plant_residue(root / "a.rollback-broken", tmp_path / "gone")

    with fix_core():
        assert g.guard_once() == []

    assert os.path.lexists(link)  # untouched: the fix means there is nothing to clean


def test_guard_once_is_a_noop_on_an_unrecognized_core(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    root.mkdir()
    link = plant_residue(root / "a.rollback-broken", tmp_path / "gone")
    monkeypatch.setattr(g, "skills_roots", lambda: [root])

    with absent_core():
        monkeypatch.setattr(g.importlib, "import_module", lambda *a, **k: (_ for _ in ()).throw(ImportError()))
        assert g.guard_once() == []

    assert os.path.lexists(link)


def test_guard_once_cleans_on_an_unfixed_core(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    root.mkdir()
    live = tmp_path / "live"
    link = plant_safe_residue(root, "a", tmp_path / "gone", link_dir=live)
    monkeypatch.setattr(g, "skills_roots", lambda: [root])

    with unfix_core():
        removed = g.guard_once()

    assert removed == [link]
    assert not os.path.lexists(link)


def test_guard_once_preserves_the_only_surviving_copy_on_an_unfixed_core(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    root.mkdir()
    target = tmp_path / "real_skill"
    target.mkdir()
    (target / "SKILL.md").write_text("# only copy")
    orphan = plant_residue(root / "demo.rollback-broken", target)
    monkeypatch.setattr(g, "skills_roots", lambda: [root])

    with unfix_core():
        removed = g.guard_once()

    assert removed == []
    assert os.path.lexists(orphan)
    assert (target / "SKILL.md").read_text() == "# only copy"


def test_installed_core_is_classified_and_matches_its_helper():
    """Against the environment's real core: state is known, and 'fixed' iff the helper exists."""
    import sys

    state = g.core_fix_state()
    assert state in {g.STATE_FIXED, g.STATE_UNFIXED, g.STATE_UNKNOWN}
    module = sys.modules.get(g.CORE_MODULE_NAME)
    if module is not None:
        assert state == (g.STATE_FIXED if hasattr(module, g.FIX_SENTINEL) else g.STATE_UNFIXED)


def test_register_is_idempotent_per_context():
    class Ctx:
        def __init__(self):
            self.registered = []

        def register_middleware(self, kind, callback):
            self.registered.append((kind, callback))

    ctx = Ctx()
    g.register(ctx)
    g.register(ctx)
    g.register(ctx)

    assert len(ctx.registered) == 1
    assert ctx.registered[0][0] == g.TOOL_EXECUTION_MIDDLEWARE
    assert ctx.registered[0][1] is g.guard_tool_execution
