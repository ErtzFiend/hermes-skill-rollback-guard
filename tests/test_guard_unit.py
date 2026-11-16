"""Unit tests for the residue scanner, the safety gate and the remover."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import rollback_guard as g
from _support import link_skill, plant_residue, plant_safe_residue, unfix_core


def test_is_residue_matches_only_symlinks_with_the_suffix(tmp_path):
    link = plant_residue(tmp_path / "a.rollback-broken", tmp_path / "gone")
    real_file = tmp_path / "b.rollback-broken"
    real_file.write_text("x")                 # a regular file is never the bug's shape
    real_dir = tmp_path / "c.rollback-broken"
    real_dir.mkdir()
    live_skill = tmp_path / "demo"
    live_skill.mkdir()

    assert g.is_residue(link) is True
    assert g.is_residue(real_file) is False   # could be unique user data: never touched
    assert g.is_residue(real_dir) is False    # never a directory: no recursive delete
    assert g.is_residue(live_skill) is False
    assert g.is_residue(tmp_path / "other.txt") is False


def test_safe_residue_requires_a_live_canonical_sibling(tmp_path):
    root = tmp_path / "skills"
    root.mkdir()
    target = tmp_path / "real_skill"
    target.mkdir()

    orphan = plant_residue(root / "lonely.rollback-broken", target)
    assert g.is_residue(orphan) is True          # it is residue-shaped ...
    assert g.is_safe_residue(orphan) is False    # ... but may be the only surviving copy

    safe = plant_safe_residue(root, "demo", target, link_dir=target)
    assert g.is_safe_residue(safe) is True


def test_chained_residue_resolves_to_the_true_canonical_name(tmp_path):
    root = tmp_path / "skills"
    target = tmp_path / "real_skill"
    target.mkdir()
    (target / "SKILL.md").write_text("# demo\n")  # a live skill carries SKILL.md
    link_skill(root, "demo", target)              # the live skill
    chained = plant_residue(root / "demo.rollback-broken.rollback-broken", target)

    assert g.is_safe_residue(chained) is True     # base 'demo' strips to the live sibling


def test_broken_live_sibling_is_not_treated_as_safe(tmp_path):
    root = tmp_path / "skills"
    root.mkdir()
    (root / "demo").symlink_to(tmp_path / "vanished", target_is_directory=True)
    residue = plant_residue(root / "demo.rollback-broken", tmp_path / "gone")

    assert g.is_safe_residue(residue) is False    # the sibling does not resolve


def test_find_residue_scans_two_levels_only(tmp_path):
    root = tmp_path / "skills"
    (root / "cat").mkdir(parents=True)
    (root / "deep").mkdir()
    live = tmp_path / "live"
    live.mkdir()

    a = plant_safe_residue(root, "a", tmp_path / "gone", link_dir=live)          # depth 1
    b = plant_safe_residue(root / "cat", "b", tmp_path / "gone", link_dir=live)  # depth 2
    # depth 3 -> ignored, even with a sibling
    (root / "deep" / "sub").mkdir()
    link_skill(root / "deep" / "sub", "c", live)
    plant_residue(root / "deep" / "sub" / "c.rollback-broken", tmp_path / "gone")

    assert set(g.find_residue([root])) == {a, b}


def test_find_residue_withholds_unsafe_residue(tmp_path):
    root = tmp_path / "skills"
    root.mkdir()
    live = tmp_path / "live"
    live.mkdir()
    safe = plant_safe_residue(root, "kept-skill", tmp_path / "gone", link_dir=live)
    unsafe = plant_residue(root / "lonely.rollback-broken", tmp_path / "gone")

    assert g.find_residue([root]) == [safe]
    assert g.find_unsafe_residue([root]) == [unsafe]


def test_find_residue_does_not_follow_symlinked_directories(tmp_path):
    root = tmp_path / "skills"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.rollback-broken").write_text("residue")
    (root / "cat").symlink_to(outside, target_is_directory=True)

    assert g.find_residue([root]) == []
    assert g.find_unsafe_residue([root]) == []


def test_clean_residue_removes_link_but_not_its_target(tmp_path):
    target = tmp_path / "real_skill"
    target.mkdir()
    (target / "SKILL.md").write_text("# demo")
    root = tmp_path / "skills"
    root.mkdir()
    link = plant_safe_residue(root, "demo", target, link_dir=target)

    removed, failed = g.clean_residue([root])

    assert removed == [link]
    assert failed == []
    assert not os.path.lexists(link)          # the link entry itself is gone
    assert target.is_dir()                    # its target is untouched
    assert (target / "SKILL.md").read_text() == "# demo"


def test_clean_residue_preserves_the_only_surviving_copy(tmp_path):
    """A residue with no live canonical sibling — a failed/interrupted restore — is never removed."""
    target = tmp_path / "real_skill"
    target.mkdir()
    (target / "SKILL.md").write_text("# only copy of the content")
    root = tmp_path / "skills"
    root.mkdir()
    orphan = plant_residue(root / "demo.rollback-broken", target)

    removed, failed = g.clean_residue([root])

    assert removed == []
    assert failed == []
    assert os.path.lexists(orphan)                       # kept
    assert (target / "SKILL.md").read_text() == "# only copy of the content"


def test_clean_residue_is_idempotent(tmp_path):
    root = tmp_path / "skills"
    root.mkdir()
    live = tmp_path / "live"
    plant_safe_residue(root, "a", tmp_path / "gone", link_dir=live)

    first, _ = g.clean_residue([root])
    second, _ = g.clean_residue([root])

    assert len(first) == 1
    assert second == []


def test_clean_residue_dry_run_changes_nothing(tmp_path):
    root = tmp_path / "skills"
    root.mkdir()
    live = tmp_path / "live"
    link = plant_safe_residue(root, "a", tmp_path / "gone", link_dir=live)

    removed, failed = g.clean_residue([root], dry_run=True)

    assert removed == [link]
    assert failed == []
    assert os.path.lexists(link)


def test_clean_residue_reports_unlink_failure(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    root.mkdir()
    live = tmp_path / "live"
    link = plant_safe_residue(root, "a", tmp_path / "gone", link_dir=live)

    def boom(path):
        raise PermissionError("denied")

    monkeypatch.setattr(g.os, "unlink", boom)

    removed, failed = g.clean_residue([root])

    assert removed == []
    assert len(failed) == 1
    assert failed[0][0] == link
    assert isinstance(failed[0][1], PermissionError)


def test_prefix_rollback_leaves_symlink_residue_and_guard_clears_it(tmp_path):
    """Reproduce the exact pre-fix failure and prove the guard's cleanup removes it.

    Faithful to the pre-fix ``_restore_snapshot``: the broken (symlinked) skill is renamed aside,
    then ``shutil.rmtree(aside, ignore_errors=True)`` silently no-ops on the link, then the snapshot
    is copied back to the canonical name — leaving ``demo`` live and ``demo.rollback-broken`` behind.
    """
    target = tmp_path / "real_skill"
    target.mkdir()
    (target / "SKILL.md").write_text("# x")
    root = tmp_path / "skills"
    root.mkdir()
    skill = root / "demo"
    skill.symlink_to(target, target_is_directory=True)

    snap = tmp_path / "snapshot"
    snap.mkdir()
    (snap / "SKILL.md").write_text("# x")

    aside = root / "demo.rollback-broken"
    skill.rename(aside)                        # core: post_dir.rename(aside)
    shutil.rmtree(aside, ignore_errors=True)   # pre-fix cleanup: silently no-ops on a symlink
    shutil.copytree(snap, skill)               # core: restore the snapshot to the canonical name

    assert aside.is_symlink()                  # -> residue, the documented bug
    assert skill.is_dir() and not skill.is_symlink()  # the skill was restored

    removed, failed = g.clean_residue([root])

    assert removed == [aside]
    assert failed == []
    assert not os.path.lexists(aside)
    assert target.exists() and (target / "SKILL.md").exists()
    assert (skill / "SKILL.md").read_text() == "# x"


def test_real_directory_residue_is_left_alone(tmp_path):
    """A ``.rollback-broken`` directory (a partial state the bug never produces) is not removed."""
    root = tmp_path / "skills"
    root.mkdir()
    residue_dir = root / "demo.rollback-broken"
    residue_dir.mkdir()
    (residue_dir / "partial").write_text("x")

    removed, failed = g.clean_residue([root])

    assert removed == []
    assert failed == []
    assert residue_dir.is_dir() and (residue_dir / "partial").exists()


def test_restore_failure_path_leaves_no_residue(tmp_path):
    """When the restore re-raises, core renames the aside dir back: nothing for the guard to do."""
    root = tmp_path / "skills"
    root.mkdir()
    skill = root / "demo"
    skill.mkdir()
    aside = root / "demo.rollback-broken"

    skill.rename(aside)      # moved aside
    aside.rename(skill)      # copytree failed -> half-applied state put back

    assert not os.path.lexists(aside)
    assert g.find_residue([root]) == []
    assert g.find_unsafe_residue([root]) == []


def test_guard_tool_execution_runs_tool_once_and_returns_result():
    calls = []

    def next_call(*args, **kwargs):
        calls.append(1)
        return "TOOL-RESULT"

    from _support import fix_core

    with fix_core():
        result = g.guard_tool_execution(tool_name="read_file", args={}, next_call=next_call)

    assert result == "TOOL-RESULT"
    assert calls == [1]


def test_guard_tool_execution_without_next_call_is_inert():
    assert g.guard_tool_execution(tool_name="skill_manage", args={}, next_call=None) is None


def test_guard_tool_execution_survives_a_raising_cleanup(monkeypatch):
    def boom():
        raise RuntimeError("cleanup exploded")

    monkeypatch.setattr(g, "guard_once", boom)

    def next_call(*args, **kwargs):
        return "TOOL-RESULT"

    # The tool result must still be delivered unchanged.
    assert g.guard_tool_execution(tool_name="skill_manage", args={}, next_call=next_call) == "TOOL-RESULT"


class _FakeSkillsTool:
    """Module stand-in for ``tools.skills_tool`` exposing only ``skill_search_dirs``."""

    def __init__(self, roots, active):
        self._roots = roots
        self._active = active

    def skill_search_dirs(self):
        return self._roots, self._active


def test_skills_roots_is_the_active_profile_root_only(monkeypatch):
    """Default cleanup scopes to the active profile writable root — never shared/project/external."""
    active = Path("/tmp/active-profile-skills")
    shared = Path("/tmp/shared-skills")           # builtin/external/shared: not ours to sweep
    project = Path("/tmp/project-skills")
    monkeypatch.setitem(sys.modules, "tools.skills_tool",
                        _FakeSkillsTool([(1, project), (3, shared)], active))

    assert g.active_skill_root() == active
    assert g.skills_roots() == [active]                       # scoped, not the wider tree
    assert g.all_skills_roots() == [active, project, shared]  # wider tree still available


def test_guard_once_leaves_non_active_roots_untouched(tmp_path, monkeypatch):
    """A residue in a shared/other-profile root is never swept by the default cleanup."""
    active = tmp_path / "profile" / "skills"
    shared = tmp_path / "shared-skills"
    live = tmp_path / "live"
    active_residue = plant_safe_residue(active, "mine", tmp_path / "gone-a", link_dir=live / "mine")
    shared_residue = plant_safe_residue(shared, "theirs", tmp_path / "gone-b", link_dir=live / "theirs")
    monkeypatch.setitem(sys.modules, "tools.skills_tool",
                        _FakeSkillsTool([(3, shared)], active))

    with unfix_core():
        removed = g.guard_once()

    assert removed == [active_residue]        # ours: cleaned
    assert not os.path.lexists(active_residue)
    assert os.path.lexists(shared_residue)    # not ours: never touched


def test_regular_file_residue_is_never_touched(tmp_path):
    """The bug only ever leaves a symlink; a regular file is unique data and stays intact."""
    root = tmp_path / "skills"
    (root / "demo").mkdir(parents=True)
    (root / "demo" / "SKILL.md").write_text("# live demo\n")   # a genuine live sibling
    precious = root / "demo.rollback-broken"
    precious.write_text("unique user data, not a symlink\n")

    assert not g.is_residue(precious)
    assert g.find_residue([root]) == []
    removed, failed = g.clean_residue([root])
    assert removed == [] and failed == []
    assert precious.read_text() == "unique user data, not a symlink\n"


def test_directory_without_skill_md_sibling_is_preserved(tmp_path):
    """A live-looking sibling that is not a real skill (no SKILL.md) never licenses removal."""
    root = tmp_path / "skills"
    (root / "demo").mkdir(parents=True)          # sibling dir, but no SKILL.md
    (root / "demo" / "notes.txt").write_text("not a skill\n")
    residue = plant_residue(root / "demo.rollback-broken", tmp_path / "gone")

    assert not g.is_safe_residue(residue)
    assert g.find_residue([root]) == []
    removed, _failed = g.clean_residue([root])
    assert removed == []
    assert os.path.lexists(residue)
