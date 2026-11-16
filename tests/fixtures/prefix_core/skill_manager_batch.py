"""Faithful reconstruction of the PRE-FIX ``tools.skill_manager_batch`` rollback path.

This is a **test fixture**, not Hermes source. It reproduces exactly the behaviour under test —
rename the broken skill aside as ``<name>.rollback-broken``, then ``shutil.rmtree(aside,
ignore_errors=True)``, which refuses a symbolic link and swallows the refusal — so the acceptance
test can drive the genuine pre-fix rollback on any machine, including CI, without shipping any
Hermes core file. The fix replaces the two ``shutil.rmtree(aside, ...)`` calls with a symlink-safe
helper; this module deliberately does not define that helper, so it classifies as ``unfixed``.

Only the rollback branch that leaves the residue is required by the tests; the ``snap is None``
branches are kept for fidelity to the original shape.
"""

from __future__ import annotations

import shutil
from contextlib import suppress
from pathlib import Path


def _restore_snapshot(pre_dir: Path, snap: Path | None, post_dir: Path | None,
                      dir_pre_existed: bool = False, written=()) -> None:
    post_exists = post_dir is not None and post_dir.is_dir()
    if snap is None:
        if not post_exists:
            return
        if not dir_pre_existed:
            shutil.rmtree(post_dir)
            return
        for rel in ("SKILL.md", *written):
            target = post_dir / rel
            with suppress(OSError):
                target.unlink()
            for parent in target.parents:
                if parent == post_dir or not parent.is_relative_to(post_dir):
                    break
                with suppress(OSError):
                    parent.rmdir()
        with suppress(OSError):
            post_dir.rmdir()
        return
    if not post_exists:
        shutil.copytree(snap, pre_dir)
        return
    # Move the broken state aside and delete it only after the snapshot is back.
    aside = post_dir.with_name(post_dir.name + ".rollback-broken")
    shutil.rmtree(aside, ignore_errors=True)   # pre-fix: silently no-ops on a symlink
    post_dir.rename(aside)
    try:
        shutil.copytree(snap, pre_dir)
    except Exception:
        shutil.rmtree(pre_dir, ignore_errors=True)
        aside.rename(pre_dir)
        raise
    shutil.rmtree(aside, ignore_errors=True)   # pre-fix: leaves a symlink residue behind
