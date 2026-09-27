# Changelog

## 0.1.0rc2

### Added

- GNU General Public License v3.0 or later: full license text, a per-file notice
  on every module, `License-Expression: GPL-3.0-or-later` in the built
  distributions, and the license bundled in the wheel.
- Ulf Bertilsson recorded as author, maintainer and copyright holder.
- A complete CI pipeline: `ruff` lint, `mypy` type check, the suite with coverage
  on Python 3.10-3.13 (Linux) plus 3.12 on macOS and Windows, a packaging job
  that asserts the license metadata reaches the wheel, profile validation, and a
  release job that builds and publishes on a `v*` tag.
- `--force` for `export`, which otherwise refuses to replace an existing archive.
- `type_field` in a profile, for agents whose records name their kind with
  something other than `type`.
- Tests for the robustness the README promises: SQLite schema capture including a
  corrupt database, symlinks preserved rather than followed, FIFOs and unreadable
  directories reported instead of fatal, read-only directories keeping their
  contents, and the record-shape profile recording shapes but never contents.
- Project metadata: richer description, classifiers, URLs and a `dev` extra.
- Dependabot for GitHub Actions updates.

### Changed

- `VERSION` now tracks the package version (`0.1.0rc2`) and is stamped into every
  export and backup as `tool_version`; the release job refuses to publish unless
  the tag, `pyproject.toml` and `VERSION` agree.
- Internal tidy-up to satisfy the linter: one `write_json` helper replaced six
  near-identical JSON writes, and shadowed loop variables were renamed.

### Fixed

- **A read-only directory lost its contents in a backup.** `copy_tree` applied a
  directory's permissions before copying what was inside it, so a mode like
  `0o500` made the copy unwritable and everything under it was skipped. Directory
  metadata is now applied after the contents, deepest first.
- **The record-shape profile and `audit` miscounted any agent that does not call
  its discriminator `type`.** Every record came out as `<missing>`. Profiles now
  declare `type_field`, defaulting to `type`.
- **Coverage was measured only in-process**, so the CLI tests that run through
  `subprocess` did not count: the real figure was 91%, not 55%. `tests/conftest.py`
  now instruments the children, and CI enforces a 90% floor.
- **An export could silently replace an older archive.** An archive may hold the
  only remaining copy of sessions the agent has since deleted, so `export` now
  refuses to overwrite one, suggests a timestamped name, and takes `--force` when
  replacing is what you want.
- A CLI test built a bare environment, which left Windows runners without
  `SYSTEMROOT`.

## rc01 (0.1.0rc1)

First release. A single generic engine (`agent_backup.py`) with profile-driven
support for any JSONL-based coding agent, built-in profiles for Claude Code and
Codex, and four pinned front ends that keep the original per-agent CLIs.

### Added

- `agent_backup.py`: `profiles`, `list`, `sync`, `export`, `backup`, `audit`.
- Profiles as data, loadable from JSON via `./agent-profiles`,
  `~/.config/agent-backup/profiles`, `$AGENT_BACKUP_PROFILES` or `--profile-file`;
  a new agent needs no code.
- `--agent auto` detects the single agent with sessions on disk.
- `audit`: verifies a profile against real files and exits non-zero on a problem.
- `--prune` for deleting mirrored chats whose session left the source.
- 38 tests, including a synthetic third-party format driven end to end.
- GitHub Actions CI: the suite on Python 3.10-3.13 (Linux) and 3.12 (macOS), a
  packaging job that installs the project and checks the built distributions, and
  a job that validates every bundled profile.
- Licensed under the GNU General Public License v3.0 or later.

### Fixed

Each of these was found by auditing the tools against real state:

- **Sessions silently overwriting each other.** A resumed or forked session
  records the id of the session it continues. Three Codex chats were lost on every
  sync; five files reported an id that did not match their own name. The session id
  now comes from the file name, with the recorded id as a fallback only.
- **Content silently dropped.** Claude `image` (295) and `tool_reference` (93)
  blocks and Codex `input_image` blocks were discarded. All are rendered now, and
  unknown block types render as `[type]` instead of vanishing.
- **User-set titles ignored.** 13 of 21 Claude sessions had a `custom-title` that
  lost to the generated `ai-title`.
- **Stale mirror files.** A retitled session left its old Markdown file behind,
  and the manifest, keyed by session id, hid the duplicate.
- **Backups aborting on one bad path.** An unreadable directory, dangling symlink,
  socket or device node crashed the whole run; such entries are now skipped and
  listed in `backup-metadata.json`.
- **Colliding output names.** Two sources claiming one id now both survive,
  disambiguated by a path hash.
