# Changelog

All notable changes to this plugin are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions use [SemVer](https://semver.org/).

## [Unreleased]

### Changed

- **Residue is a symlink and nothing else.** `is_residue` now matches only symbolic links carrying
  the `.rollback-broken` suffix — the sole shape the pre-fix rollback leaves. A regular file with
  that name is never a candidate (it may hold unique user data), nor is a directory.
- **The data-loss gate requires a real skill.** A live canonical sibling now counts only when it is
  a directory containing a `SKILL.md` (or a symlink resolving into one); a directory without one no
  longer licenses removal of the residue beside it.
- **Cleanup is scoped to the active profile.** `skills_roots()` now returns only the active
  profile's writable skills dir, so shared/builtin, project, `skills.create_dir` and external roots
  — and other profiles — are never swept. The previous wider enumeration is preserved as the
  opt-in `all_skills_roots()` (with `active_skill_root()`).
- Test suite extended with explicit coverage: a regular file residue is never touched, a directory
  without a `SKILL.md` leaves the residue untouched, and non-active roots are never swept.

## [0.1.0] - 2026-11-15

### Added

- Native Hermes plugin that registers the `tool_execution` middleware and clears the
  `<name>.rollback-broken` symlink residue left by `skill_manage`'s batch rollback on pre-fix
  Hermes cores. Cleanup-only; uses the documented middleware seam and the public
  `skills_tool.skill_search_dirs()` API — no core rebind, no core patch.
- Capability guard classifying the running core as `fixed` / `unfixed` / `unknown`; the plugin is a
  no-op except on an `unfixed` core.
- Data-loss safety gate: a residue is removed only when a **live canonical skill sits beside it**.
  Residue that may be a skill's only surviving copy — a failed or interrupted restore — is
  preserved and logged. A `.rollback-broken` directory is never removed; `os.unlink` never follows
  a symlink, so a link's target is never touched.
- Test suite covering the scanner, the safety gate, the classifier, the real Hermes
  discovery/import/register path and the real `tool_execution` middleware chain.
- End-to-end acceptance test that drives the genuine **pre-fix rollback** on a symlinked skill —
  from a real pre-fix `skill_manager_batch.py` when available (`PREFIX_CORE`), otherwise from the
  faithful reconstruction in `tests/fixtures/prefix_core/` — then proves the residue is cleared and
  the skill and its target survive, and that the only-surviving-copy case is preserved.
- `build.sh` producing `tar.gz` + `zip` archives and `SHA256SUMS`; CI and release GitHub Actions
  workflows.

[Unreleased]: https://github.com/ErtzFiend/hermes-skill-rollback-guard/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ErtzFiend/hermes-skill-rollback-guard/releases/tag/v0.1.0
