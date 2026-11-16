"""End-to-end acceptance for the pre-fix rollback bug.

Drives the *actual* pre-fix ``_restore_snapshot`` (a real pre-fix ``skill_manager_batch.py``,
located via ``PREFIX_CORE`` or a known local backup) so a symlinked skill's rollback leaves its
``.rollback-broken`` residue, then loads the plugin through the real Hermes loader and runs a
``skill_manage`` call through the real ``tool_execution`` middleware chain — proving the guard
clears the residue in the real chain while preserving the restored skill and its target.

The repo ships no Hermes core source; when no pre-fix module is available the real-module test
skips and the faithful, self-contained reproduction below still runs.
"""

from __future__ import annotations

import os
import shutil

import pytest

pytest.importorskip("hermes_cli")

import rollback_guard as g  # noqa: E402
from hermes_cli import middleware as mw  # noqa: E402
from hermes_cli import plugins as plugins_mod  # noqa: E402
from _support import (  # noqa: E402
    PLUGIN_NAME,
    find_prefix_core,
    link_skill,
    real_prefix_core,
    stage_plugin,
    unfix_core,
)


@pytest.fixture(autouse=True)
def _clean_managers():
    plugins_mod._reset_plugin_managers_for_tests()
    yield
    plugins_mod._reset_plugin_managers_for_tests()


def _load_real_plugin(hermes_home, monkeypatch):
    """Stage + load the plugin through the real discovery/import/register path."""
    (hermes_home / "plugins").mkdir(parents=True, exist_ok=True)
    stage_plugin(hermes_home, PLUGIN_NAME)
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    manager = plugins_mod.PluginManager()
    manifests = manager._scan_directory(hermes_home / "plugins", source="user")
    assert [m.name for m in manifests] == [PLUGIN_NAME]
    manager._load_plugin(manifests[0])
    callbacks = [
        cb for cb in manager._middleware.get(mw.TOOL_EXECUTION_MIDDLEWARE, [])
        if getattr(cb, "__name__", "") == "guard_tool_execution"
    ]
    assert callbacks, "the real loader did not register the middleware"
    monkeypatch.setattr(plugins_mod, "_plugin_manager", manager)
    return manager


def _run_skill_manage():
    """One skill_manage call through the real middleware chain; returns (result, call_count)."""
    calls = []

    def next_call(*_a, **_k):
        calls.append(1)
        return "skill_manage-result"

    result = mw.run_tool_execution_middleware("skill_manage", {"operations": []}, next_call)
    return result, len(calls)


def _symlinked_skill(home):
    """A canonical source dir + a symlinked live skill + a snapshot to restore from."""
    canonical = home / "canonical" / "demo"
    canonical.mkdir(parents=True)
    (canonical / "SKILL.md").write_text("# demo skill")
    skills = home / "skills"
    pre_dir = link_skill(skills, "demo", canonical)
    snap = home / "snapshot"
    snap.mkdir()
    (snap / "SKILL.md").write_text("# demo skill")
    return skills, canonical, pre_dir, snap


def test_real_prefix_rollback_then_guard_clears_through_real_chain(tmp_path, monkeypatch):
    prefix = find_prefix_core()
    if prefix is None:
        pytest.skip("no real pre-fix core module available (set PREFIX_CORE)")

    home = tmp_path / "hermes_home"
    home.mkdir()
    skills, canonical, pre_dir, snap = _symlinked_skill(home)

    with real_prefix_core(prefix) as core:
        # It is the genuine pre-fix shape: rollback entry point, no symlink-safe helper.
        assert hasattr(core, g.ROLLBACK_SENTINEL)
        assert not hasattr(core, g.FIX_SENTINEL)
        assert g.core_fix_state() == g.STATE_UNFIXED

        # --- drive the actual pre-fix restore of a symlinked skill -------------------------
        core._restore_snapshot(pre_dir, snap, pre_dir, dir_pre_existed=True)

        residue = skills / "demo.rollback-broken"
        assert residue.is_symlink(), "the real pre-fix core did not leave its residue"
        assert pre_dir.is_dir() and not pre_dir.is_symlink(), "the skill was not restored"

        # --- clear it through the real Hermes chain ----------------------------------------
        _load_real_plugin(home, monkeypatch)
        result, count = _run_skill_manage()

    assert result == "skill_manage-result"
    assert count == 1
    assert not os.path.lexists(residue)                            # residue gone
    assert not pre_dir.is_symlink() and (pre_dir / "SKILL.md").read_text() == "# demo skill"
    assert (canonical / "SKILL.md").read_text() == "# demo skill"  # target untouched


def test_real_chain_preserves_the_only_surviving_copy(tmp_path, monkeypatch):
    """A residue that may be a skill's only surviving copy is never removed by the real chain."""
    home = tmp_path / "hermes_home"
    home.mkdir()
    canonical = home / "canonical"
    canonical.mkdir()
    (canonical / "SKILL.md").write_text("# the only copy of the content")
    skills = home / "skills"
    skills.mkdir()
    orphan = skills / "demo.rollback-broken"
    orphan.symlink_to(canonical, target_is_directory=True)  # no live 'demo' sibling at all

    with unfix_core():
        _load_real_plugin(home, monkeypatch)
        result, count = _run_skill_manage()

    assert result == "skill_manage-result"
    assert count == 1
    assert os.path.lexists(orphan)                                   # preserved
    assert (canonical / "SKILL.md").read_text() == "# the only copy of the content"


def test_faithful_prefix_reproduction_leaves_residue_then_guard_clears(tmp_path, monkeypatch):
    """Self-contained proof (no pre-fix module needed) of the exact pre-fix failure and the fix."""
    home = tmp_path / "hermes_home"
    home.mkdir()
    skills, canonical, pre_dir, snap = _symlinked_skill(home)

    aside = skills / "demo.rollback-broken"

    # The verbatim pre-fix rollback, on a symlinked skill:
    pre_dir.rename(aside)                       # post_dir.rename(aside)
    shutil.rmtree(aside, ignore_errors=True)    # pre-fix cleanup: silently no-ops on a symlink
    shutil.copytree(snap, pre_dir)              # restore the snapshot to the canonical name

    assert aside.is_symlink()                   # residue, the documented bug

    with unfix_core():
        _load_real_plugin(home, monkeypatch)
        result, count = _run_skill_manage()

    assert result == "skill_manage-result"
    assert count == 1
    assert not os.path.lexists(aside)
    assert (pre_dir / "SKILL.md").read_text() == "# demo skill"
    assert (canonical / "SKILL.md").read_text() == "# demo skill"
