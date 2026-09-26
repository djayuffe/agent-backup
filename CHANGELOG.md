# Changelog

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
