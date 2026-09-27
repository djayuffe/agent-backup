# Changelog

## 0.1.0

First stable release. The code is what `0.1.0rc3` shipped, with the release
plumbing for a non-pre-release tag made explicit; the release-candidate sections
below record how it got here and what each fixed.

What it does:

- Mirrors any JSONL-based coding agent's sessions to readable Markdown, exports
  them as portable ZIP archives, and takes verifiable 1:1 snapshots of a project
  and an agent home with a SHA-256 for every file copied.
- Ships profiles for **Claude Code** and **Codex**, validated against 21 Claude
  sessions (85,942 records) and 190 Codex rollouts (261,659 records) with no
  unhandled record shapes.
- Supports any other agent through a JSON profile and no code, and `audit` tells
  you when a profile stops matching what the agent writes.
- Refuses to lose data: it never overwrites an existing archive, never deletes a
  vanished session's chat unless asked, preserves symlinks as symlinks, keeps a
  read-only directory's contents, and reports what it could not read instead of
  failing the run.

Verified on every release: `ruff`, `mypy`, 43 tests at 91% coverage on Python
3.10–3.13 across Linux, macOS and Windows, a packaging check that the wheel
really carries `GPL-3.0-or-later`, and a profile check that drives a synthetic
third-party format end to end.

## 0.1.0rc3

Everything here was found by testing claims the README already made, or by
distrusting a green pipeline. Anyone on `0.1.0rc2` should move to this release:
it fixes a backup that could silently drop files.

### Fixed

- **A read-only directory lost its contents in a backup.** `copy_tree` applied a
  directory's permissions before copying what was inside it, so a source
  directory with a mode like `0o500` became unwritable and everything under it
  was skipped — recorded in `skipped`, but missing from the backup. Directory
  metadata is now applied after the contents, deepest first.
- **Every scanned SQLite database leaked its handle.** `with sqlite3.connect(...)`
  commits the transaction but does not close the connection; `collect_sqlite_schemas`
  now wraps it in `contextlib.closing`.
- **`audit` and the backup's record-shape profile miscounted any agent that does
  not name its discriminator `type`.** Every record was counted as `<missing>` —
  the generic engine failing precisely for the third-party agents it exists to
  serve. Profiles now declare `type_field`, defaulting to `type`.
- **CI could not fail on Windows.** The runner's default `pwsh` shell did not
  propagate a failing command's exit code: the coverage gate printed `FAIL` at
  89.95% and the step still reported success, so a red test run there would have
  kept the pipeline green. Every job now runs under `bash`, verified by pushing a
  deliberately failing test and confirming all six runners went red.
- **Coverage was measured only in the parent process**, so the CLI tests that run
  through `subprocess` did not count: the real figure was 91%, not 55%.

### Added

- `type_field` in a profile, for agents whose records name their kind with
  something other than `type`.
- Tests for the robustness the README promises: SQLite schema capture from a real
  database and a corrupt one, symlinks preserved rather than followed, FIFOs and
  unreadable directories reported instead of fatal, read-only directories keeping
  their contents, and the record-shape profile recording shapes but never message
  text.
- Warnings are errors in the test suite, which is how the SQLite handle leak
  surfaced.

### Changed

- The coverage floor (90%) is enforced where the whole suite runs; the POSIX-only
  tests skip on Windows and would otherwise drag the figure under it.
- GitHub Actions pinned to `checkout@v7`, `setup-python@v7`, `upload-artifact@v7`.

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
- Project metadata: richer description, classifiers, URLs and a `dev` extra.
- Dependabot for GitHub Actions updates.

### Changed

- `VERSION` now tracks the package version (`0.1.0rc2`) and is stamped into every
  export and backup as `tool_version`; the release job refuses to publish unless
  the tag, `pyproject.toml` and `VERSION` agree.
- Internal tidy-up to satisfy the linter: one `write_json` helper replaced six
  near-identical JSON writes, and shadowed loop variables were renamed.

### Fixed

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
