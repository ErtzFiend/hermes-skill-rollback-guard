"""Acceptance tests: the plugin loads through the real Hermes loader and, on a pre-fix core,
clears the rollback residue a real ``skill_manage`` call leaves — without editing core files."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("hermes_cli")

from hermes_cli import middleware as mw  # noqa: E402
from hermes_cli import plugins as plugins_mod  # noqa: E402
from hermes_cli.plugin_dev import _doctor_runtime  # noqa: E402

from _support import REPO_ROOT, fix_core, plant_residue, stage_plugin, unfix_core  # noqa: E402

PLUGIN_NAME = "hermes-skill-rollback-guard"


def _guard_callbacks(manager):
    return [
        cb for cb in manager._middleware.get(mw.TOOL_EXECUTION_MIDDLEWARE, [])
        if getattr(cb, "__name__", "") == "guard_tool_execution"
    ]


@pytest.fixture(autouse=True)
def _clean_managers():
    plugins_mod._reset_plugin_managers_for_tests()
    yield
    plugins_mod._reset_plugin_managers_for_tests()


def test_doctor_loads_plugin_through_the_real_loader():
    with _doctor_runtime(REPO_ROOT) as result:
        assert result.manifest.name == PLUGIN_NAME
        assert result.manifest.version == "0.1.0"
        assert result.manifest.kind == "standalone"
        assert _guard_callbacks(result.manager)  # real discovery + import + register(ctx)


def _install_into_home(hermes_home):
    stage_plugin(hermes_home, PLUGIN_NAME)
    skills = hermes_home / "skills"
    skills.mkdir(parents=True, exist_ok=True)
    target = hermes_home / "real_skill"
    target.mkdir()
    (target / "SKILL.md").write_text("# demo")
    (skills / "demo").symlink_to(target, target_is_directory=True)
    residue = plant_residue(skills / "demo.rollback-broken", hermes_home / "vanished")
    return skills, target, residue


def _load_manager(hermes_home, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    manager = plugins_mod.PluginManager()
    manifests = manager._scan_directory(hermes_home / "plugins", source="user")
    assert [m.name for m in manifests] == [PLUGIN_NAME]
    manager._load_plugin(manifests[0])
    assert _guard_callbacks(manager), "the middleware was not registered"
    return manager


def test_prefix_core_residue_is_cleared_through_the_real_chain(tmp_path, monkeypatch):
    hermes_home = tmp_path / "hermes_home"
    skills, target, residue = _install_into_home(hermes_home)
    manager = _load_manager(hermes_home, monkeypatch)

    called = []

    def next_call(*args, **kwargs):
        called.append(1)
        return "skill_manage-result"

    with unfix_core():
        monkeypatch.setattr(plugins_mod, "_plugin_manager", manager)
        result = mw.run_tool_execution_middleware("skill_manage", {"operations": []}, next_call)

    assert result == "skill_manage-result"   # result passes through unchanged
    assert called == [1]                     # the tool ran exactly once
    assert not os.path.lexists(residue)      # residue cleared
    assert (skills / "demo").is_symlink()    # the live skill is untouched
    assert (target / "SKILL.md").read_text() == "# demo"


def test_upstream_fixed_core_is_a_noop_through_the_real_chain(tmp_path, monkeypatch):
    hermes_home = tmp_path / "hermes_home"
    skills, _target, residue = _install_into_home(hermes_home)
    manager = _load_manager(hermes_home, monkeypatch)

    with fix_core():
        monkeypatch.setattr(plugins_mod, "_plugin_manager", manager)
        result = mw.run_tool_execution_middleware("skill_manage", {}, lambda *a, **k: "ok")

    assert result == "ok"
    assert os.path.lexists(residue)          # on a fixed core nothing is deleted


def test_other_tools_are_never_scanned(tmp_path, monkeypatch):
    hermes_home = tmp_path / "hermes_home"
    _skills, _target, residue = _install_into_home(hermes_home)
    manager = _load_manager(hermes_home, monkeypatch)

    with unfix_core():
        monkeypatch.setattr(plugins_mod, "_plugin_manager", manager)
        mw.run_tool_execution_middleware("write_file", {"path": "x"}, lambda *a, **k: "ok")

    assert os.path.lexists(residue)  # only a skill_manage call triggers the cleanup


def test_load_twice_is_safe(tmp_path, monkeypatch):
    hermes_home = tmp_path / "hermes_home"
    _skills, _target, residue = _install_into_home(hermes_home)
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    manager = plugins_mod.PluginManager()
    manifest = manager._scan_directory(hermes_home / "plugins", source="user")[0]

    manager._load_plugin(manifest)
    manager._load_plugin(manifest)           # a second load must not raise

    with unfix_core():
        monkeypatch.setattr(plugins_mod, "_plugin_manager", manager)
        result = mw.run_tool_execution_middleware("skill_manage", {}, lambda *a, **k: "ok")

    assert result == "ok"
    assert not os.path.lexists(residue)      # cleanup still correct (and idempotent)
