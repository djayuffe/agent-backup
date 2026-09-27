# agent-backup

[![CI](https://github.com/djayuffe/agent-backup/actions/workflows/ci.yml/badge.svg)](https://github.com/djayuffe/agent-backup/actions/workflows/ci.yml)
[![License: GPL v3](https://img.shields.io/badge/license-GPLv3-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

**Keep your own copy of what your coding agents said.**

Coding agents write every session to disk as JSONL, then quietly rotate, retitle
and delete it. `agent-backup` turns that state into something you own: readable
Markdown you can grep, portable ZIP archives you can move off the machine, and
verifiable 1:1 snapshots with a SHA-256 for every file. Claude Code and Codex
work out of the box; any other JSONL-based agent needs a small JSON profile and
no code at all.

- **One engine, many agents.** The record layout lives in a *profile*, not in code.
- **No dependencies.** Standard library only, Python 3.10+.
- **Nothing lost, nothing silently dropped.** Unknown fields surface instead of vanishing;
  damaged files are skipped and reported, never fatal.
- **Self-checking.** `agent-backup audit` verifies a profile still matches reality and
  exits non-zero when it does not.

```console
$ agent-backup profiles
claude	built-in	/Users/you/.claude	found
codex	built-in	/Users/you/.codex	found

$ agent-backup sync --agent claude --output claude-chats
Mirrored 21 chats to claude-chats

$ agent-backup audit --agent codex
agent: codex   source: /Users/you/.codex
files: 190   records: 261659   invalid json: 0
messages: 17688   rendered: 17688
unhandled block types: none
duplicate ids: none
name collisions: none
verdict: ok
```

---

## Contents

- [Install](#install)
- [Quickstart](#quickstart)
- [Commands](#commands)
- [Options](#options)
- [Output layouts](#output-layouts)
- [Supported agents](#supported-agents)
- [Writing a profile](#writing-a-profile)
- [Auditing](#auditing)
- [Design guarantees](#design-guarantees)
- [Pinned front ends](#pinned-front-ends)
- [Library use](#library-use)
- [Tests](#tests)
- [Continuous integration](#continuous-integration)
- [Limitations](#limitations)
- [Versioning](#versioning)
- [License](#license)

---

## Install

No installation is required — the scripts run straight from a checkout:

```bash
git clone <this repo> agent-backup
cd agent-backup
python3 agent_backup.py profiles
```

To get the console scripts on your `PATH`:

```bash
pip install -e .
agent-backup profiles
```

That registers `agent-backup` plus the four pinned front ends (`claude-backup`,
`claude-full-backup`, `codex-backup`, `codex-full-backup`).

## Quickstart

```bash
# What do I have on this machine?
python3 agent_backup.py profiles

# Readable Markdown, one file per session, safe to re-run
python3 agent_backup.py sync --agent claude --output claude-chats

# A portable archive: Markdown + original JSONL + config + attachments
python3 agent_backup.py export --agent codex --zip codex-chats.zip

# A 1:1 backup of a project and the agent's whole home directory
python3 agent_backup.py backup --agent claude --project ~/code/myapp --output /Volumes/Backup

# Does the profile still match what the agent is writing?
python3 agent_backup.py audit --agent claude
```

With exactly one agent present on the machine, `--agent` can be left out
entirely (it defaults to `auto`).

## Commands

| Command | What it does |
| --- | --- |
| `profiles` | Lists every known profile with its home directory and whether state was found there (`found`, `empty`, `absent`). `--json` dumps the complete profile specs. |
| `list` | One line per session: id, title, message count, first timestamp. `--json` emits records including the source path. |
| `sync` | Writes one Markdown file per session into `--output`. Idempotent: a chat is rewritten only when its rendered content changed. |
| `export` | Runs `sync`, then builds a ZIP containing the Markdown mirror, the original session files, the agent's config files and its attachment directories. |
| `backup` | Copies a project tree **and** the agent home verbatim into a timestamped directory, then adds an `extracted/` digest: rendered chats, a file inventory, a record-shape profile and any SQLite schemas. |
| `audit` | Reads every session and reports coverage and integrity: record types, content-block types, unhandled block types, duplicate ids, output-name collisions, damaged lines, sessions whose records name a different id. Exits `1` on a problem, `0` when clean. |

Default command is `sync`.

## Options

| Option | Applies to | Meaning |
| --- | --- | --- |
| `--agent NAME` | all | Profile to use, or `auto` (default) to detect the single agent with sessions on disk. Refuses to guess when several qualify. |
| `--profile-file PATH` | all | Load extra profiles from a JSON file. Repeatable. |
| `--source PATH` / `--home PATH` | all | Override the agent home directory. |
| `--output PATH` | `sync`, `export`, `backup` | Mirror directory, or backup destination. Defaults to `<agent>-chats`, and `~/<Agent> Backups` for `backup`. |
| `--zip PATH` | `export` | Archive path. Defaults to the mirror directory with a `.zip` suffix. |
| `--project PATH` | `backup` | Project tree to copy. Defaults to the current directory. |
| `--no-raw` | `export` | Omit the original session files. |
| `--no-attachments` | `export` | Omit the profile's attachment directories. |
| `--prune` | `sync`, `export` | Also delete mirrored chats whose session has disappeared from the source. |
| `--force` | `export` | Replace an archive that already exists. Without it, `export` refuses and suggests a timestamped name. |
| `--json` | `profiles`, `list`, `audit` | Machine-readable output. |
| `--version` | all | Print the tool version. |

## Output layouts

### `sync` — the mirror directory

```
claude-chats/
├── .manifest.json                                  # output filename → SHA-256 of contents
├── Fix Logic hang caused by stale AUv3 wrapper--5321a9a2-….md
└── Export tracker music to C64 SID assembly--962254ac-….md
```

Each file is `<title>--<session-id>.md`, where the title is sanitised and capped
at 100 characters. A rendered chat looks like:

```markdown
# Fix Logic hang caused by stale AUv3 wrapper

- Session: `5321a9a2-c555-4fe2-8432-9d8029c3a38d`
- Project: /Users/you/code/myapp
- Updated: 2026-06-29T06:30:04.141Z

## User — 2026-06-29T05:58:11.002Z

Logic hangs when I load the plugin…

## Assistant — 2026-06-29T05:58:19.418Z

<thinking>
The wrapper is probably stale…
</thinking>
[tool_use: Read]
Here is what I found…
```

### `export` — the ZIP

```
codex-chats.zip
├── chats/           # the Markdown mirror, plus .manifest.json and export-metadata.json
├── raw/             # original JSONL, in the agent's own directory layout
├── codex/           # the profile's config files (config.toml, session_index.jsonl, …)
└── attachments/     # the profile's attachment directories
```

`export-metadata.json` records the format tag, tool version, agent, source path,
creation time, chat count and which optional groups were included.

### `backup` — the 1:1 directory

```
claude-backup-20260926T205208Z/
├── backup-metadata.json      # format, versions, counts, `skipped`, per-file SHA-256 of everything copied
├── project/                  # verbatim copy of --project
├── claude-home/              # verbatim copy of the agent home (symlinks preserved as symlinks)
└── extracted/
    ├── chats/                        # rendered Markdown
    ├── claude-file-inventory.json    # every file: path, size, mtime, symlink flag
    ├── transcript-event-profile.json # record types and body keys, no message contents
    └── sqlite-schema.json            # tables and columns of any .sqlite/.db found
```

## Supported agents

| Profile | Home | Sessions | Notes |
| --- | --- | --- | --- |
| `claude` | `$CLAUDE_CONFIG_DIR` or `~/.claude` | `projects/*/*.jsonl`, `sessions/**/*.jsonl` | Title from `custom-title`, else `ai-title`. Renders `text`, `thinking`, `tool_use`, `tool_result`, `tool_reference`, `image`. Skips `isSidechain` (sub-agent) records. Header carries the session's `cwd`. Exports `settings.json`, `CLAUDE.md`, `keybindings.json`, `plans/`, `tasks/`. |
| `codex` | `$CODEX_HOME` or `~/.codex` | `sessions/**/*.jsonl`, `archived_sessions/*.jsonl` | Title from `session_meta.thread_name`. Messages are `response_item` records of type `message`; renders `input_text`, `output_text`, `text` and image blocks. Exports `config.toml`, `session_index.jsonl`, `attachments/`. |

Both were validated against real state: 21 Claude sessions (85,942 records) and
190 Codex rollouts (261,659 records), with zero unhandled block types and zero
id collisions.

## Writing a profile

A profile is JSON. Put it in `./agent-profiles`, `~/.config/agent-backup/profiles`
or a directory named in `$AGENT_BACKUP_PROFILES`, or point at it with
`--profile-file`. Profiles found later override earlier ones of the same name, so
you can shadow a built-in.

```json
{
  "name": "example",
  "label": "Example Agent",
  "home_env": "EXAMPLE_AGENT_HOME",
  "home_default": "~/.example-agent",
  "session_globs": ["threads/*.jsonl"],
  "id_fields": ["thread_id"],
  "type_field": "kind",
  "title_rules": [{ "match": { "kind": "meta" }, "field": "subject" }],
  "message_rules": [
    { "match": { "kind": "turn" }, "role": "speaker", "content": "body" }
  ],
  "skip_when": ["hidden"],
  "blocks": {
    "say": { "kind": "text", "key": "text" },
    "call": { "kind": "label", "label": "tool", "key": "tool" },
    "result": { "kind": "nested", "label": "result", "key": "parts" },
    "picture": { "kind": "marker", "label": "image" }
  },
  "meta_fields": [["Workspace", "workspace"]],
  "timestamp_fields": ["at"],
  "body_field": "body",
  "extras": ["config.yaml"],
  "extras_dir": "example",
  "attachment_dirs": ["files"]
}
```

The full version of that file ships as
[`agent-profiles/example-agent.json`](agent-profiles/example-agent.json) and is
exercised end to end by the test suite.

### Profile keys

| Key | Type | Meaning |
| --- | --- | --- |
| `name` | string, required | Profile id used by `--agent`. |
| `label` | string | Human name in messages and default paths. Defaults to a title-cased `name`. |
| `home_env`, `home_default` | string | Environment variable and fallback path for the agent home. |
| `session_globs` | list | Glob patterns under the home that match session files. |
| `id_pattern` | regex | Group 1 is the session id **in the file name**. Defaults to a trailing UUID. Set to `""` to always use `id_fields`. |
| `id_fields` | list | Dotted record paths consulted only when the file name yields no id. |
| `title_rules` | list | Ordered `{"match": {...}, "field": "dotted.path"}`. The earliest matching rule wins, so put user-set titles first. |
| `message_rules` | list | `{"match": {...}, "role": "dotted.path", "content": "dotted.path", "role_default": "dotted.path"}`. First matching rule is used. |
| `skip_when` | list | Dotted paths whose truthiness excludes a record. |
| `type_field` | string | Record key naming the record's kind, used by `audit` and the backup's record-shape profile. Default `type`. |
| `blocks` | object | Content-block renderers, keyed by block type. See below. |
| `mark_unknown_blocks` | bool | Render `[type]` for unknown block types instead of dropping them. Default `true`. |
| `meta_fields` | list | `[label, dotted.path]` pairs. A non-empty label adds a header line; an empty label collects the value without rendering it. |
| `timestamp_fields` | list | Dotted paths checked in order for a record's time. Default `["timestamp"]`. |
| `body_field` | string | Nested key whose sub-keys `backup` profiles (e.g. `message`, `payload`). |
| `extras` | list | Single files under the home, copied into `extras_dir` in an export. |
| `extras_dir` | string | Directory name for `extras` inside the ZIP. Defaults to `name`. |
| `attachment_dirs` | list | Directories under the home, copied at their own top level in an export. |
| `event_profile_name` | string | File name for the record-shape profile in a backup. |

### Block renderers

| `kind` | Output | Extra keys |
| --- | --- | --- |
| `text` | The block's text verbatim | `key` (default `text`) |
| `wrapped` | Text wrapped in `<tag>…</tag>`, dropped when empty | `key`, `tag` |
| `label` | `[label: value]` | `label`, `key` |
| `marker` | `[label]` | `label` |
| `nested` | `[label]` followed by the recursively rendered sub-blocks | `label`, `key` |

### Matching

Every `match` is a mapping of dotted path to an expected value, or to a list of
acceptable values. This covers flat records:

```json
{ "match": { "type": ["user", "assistant"] } }
```

and nested ones:

```json
{ "match": { "type": "response_item", "payload.type": "message" } }
```

## Auditing

`audit` is how you find out that an agent changed its format before your mirror
quietly loses content. It reports:

- file, record and line counts, plus unparsable lines and non-object lines
- every record type and every content-block type seen
- **unhandled block types** — types the profile has no renderer for
- **duplicate session ids** and **output name collisions**, with the files involved
- sessions whose records name an id different from the one used
- unreadable files

It exits `1` if any of those indicate a problem, which makes it usable in a cron
job or CI step:

```bash
python3 agent_backup.py audit --agent claude --json > audit.json || echo "profile needs attention"
```

## Design guarantees

These are deliberate, and each one came from a bug found against real data:

- **The file name is the session id.** A resumed or forked session records the id
  of the session it *continues*. Trusting that id made several files claim one
  output name and silently overwrite each other — three Codex chats were lost per
  sync before this was fixed.
- **Two sources claiming one id both survive**, the second disambiguated by a
  short hash of its path.
- **Unknown content blocks are marked, not dropped.** Image blocks used to vanish
  entirely; now anything the profile does not recognise renders as `[type]`.
- **`sync` is idempotent and conservative.** Files are rewritten only when their
  content changed. A retitled session's old file is removed; a session that has
  left the source is kept unless you pass `--prune`, so pointing the tool at the
  wrong `--source` can never delete history.
- **Damage is never fatal.** Unparsable lines, non-object lines, unreadable files,
  unreadable directories, dangling symlinks, sockets and device nodes are skipped
  and recorded in `backup-metadata.json`'s `skipped` list.
- **Backups are verifiable.** Every copied file's SHA-256 is recorded, symlinks
  are preserved as symlinks rather than followed, and a backup destination inside
  the project or the agent home is refused.
- **An existing export is never replaced silently.** An archive can be the last
  remaining copy of sessions the agent has since deleted, so `export` refuses to
  overwrite one and suggests a timestamped name; `--force` is explicit.
- **Nothing is written to the agent's own directory.** The tool only reads there.

## Pinned front ends

Four wrappers keep the original per-agent CLIs, for habit and for scripts that
already call them:

| Script | Equivalent |
| --- | --- |
| `claude_backup.py {list,sync,export}` | `agent_backup.py … --agent claude` |
| `codex_backup.py {list,sync,export}` | `agent_backup.py … --agent codex` |
| `claude_full_backup.py` | `agent_backup.py backup --agent claude` |
| `codex_full_backup.py` | `agent_backup.py backup --agent codex` |

They accept their historical flags (`--source`, `--output`, `--zip`, `--no-raw`,
`--no-attachments`, `--prune`, `--version`; the full mirrors take `--project` and
`--claude-home` / `--codex-home`) and produce byte-identical output to the
generic path.

## Library use

```python
from pathlib import Path
import agent_backup
from agent_backup import CLAUDE, Profile

for path in agent_backup.sessions(CLAUDE, CLAUDE.home()):
    meta, messages = agent_backup.read_session(CLAUDE, path)
    print(agent_backup.session_id(CLAUDE, path, meta), meta.get("thread_name"), len(messages))
    print(agent_backup.render(CLAUDE, path, meta, messages))

mine = Profile.from_dict({"name": "mine", "session_globs": ["*.jsonl"],
                          "message_rules": [{"match": {"kind": "turn"}, "content": "body"}]})
report = agent_backup.audit(mine, Path("./transcripts"))
assert report["ok"], report["unhandled_blocks"]
```

Useful entry points: `sessions`, `read_session`, `render`, `session_id`,
`text_content`, `records`, `mirror`, `export`, `backup`, `audit`, `registry`,
`detect`, `Profile`, `dig`, `matches`.

## Tests

```bash
python3 -m pytest            # 43 tests, no dependencies beyond pytest
pip install -e ".[dev]"      # pytest, coverage, ruff, mypy, build, twine
ruff check .                 # lint, as CI runs it
mypy                         # type check, as CI runs it
python3 -m pytest --cov      # coverage, 91%; the CLI subprocesses are
                             # instrumented too, and CI enforces a 90% floor
```

The suite covers the engine (dotted-path lookup, profile round-trip and
validation, block renderers, damage tolerance, collision handling, audit on both
clean and broken data), the CLI (auto-detection, unknown agent, audit exit codes,
export and backup layouts, destination refusal, archive-clobber refusal) and both
built-in profiles through their pinned front ends. A synthetic third-party format
is driven end to end, so the no-code path is a tested path.

The guarantees above are tested, not just asserted in prose: SQLite schemas are
captured from a real database and a corrupt one, symlinks are checked to survive
as symlinks, FIFOs and unreadable directories are checked to be reported rather
than fatal, a read-only directory is checked to keep its contents, and the
record-shape profile is checked to contain shapes but no message text.

## Continuous integration

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on every push to
`main`, every pull request, every `v*` tag and on demand:

| Job | What it proves |
| --- | --- |
| `lint` | `ruff check` passes with `E,F,I,UP,B,SIM,C4,RET` at a 120-column limit. |
| `types` | `mypy` is clean across all five modules. |
| `test` | The 43 tests pass with coverage (floor: 90%) on Python 3.10–3.13 (Linux) and 3.12 (macOS, Windows), and every CLI entry point starts. |
| `package` | `pip install .` works, all five console scripts are installed, `python -m build` plus `twine check --strict` accept the distributions, and the wheel is asserted to carry `License-Expression: GPL-3.0-or-later` and the license text. |
| `profiles` | Every profile in `agent-profiles/` parses, and the example profile is driven end to end through `audit` — so the no-code path is covered outside the unit tests too. |
| `release` | On a `v*` tag only, and only after every other job passes: checks that the tag, `pyproject.toml` and `VERSION` agree, builds the distributions and a standalone bundle with `SHA256SUMS`, and publishes the GitHub release with notes from the changelog. |

## Limitations

- Only JSONL session formats are supported. An agent storing sessions in SQLite
  or a binary format needs an engine change, not a profile.
- `export` and `backup` copy whole directories; there is no incremental mode, and
  a backup of a large agent home is as big as that home.
- A session being written while the tool reads it yields the content up to the
  last complete line; re-run to pick up the rest.
- `audit` proves the profile handles what is *currently* on disk. It cannot
  predict a format change that has not happened yet.

## Versioning

`VERSION` in `agent_backup.py` is stamped into every export and backup as
`tool_version`. Export and backup format tags are per agent and versioned
separately (`claude-chat-export-v1`, `codex-full-backup-v1`, …) so an archive
always states how to read it.

Current release: **`0.1.0rc2`**. A release is cut by tagging `v<version>`; CI
refuses to publish unless the tag, `pyproject.toml` and `VERSION` agree.

## License

Copyright (C) 2026 Ulf Bertilsson.

GNU General Public License v3.0 or later — see [LICENSE](LICENSE).

This program is free software: you may redistribute and modify it under the
terms of the GPL as published by the Free Software Foundation, either version 3
or (at your option) any later version. It is distributed in the hope that it will
be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
