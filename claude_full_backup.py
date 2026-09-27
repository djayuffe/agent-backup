#!/usr/bin/env python3
# agent-backup — mirror and back up local coding-agent session state.
# Copyright (C) 2026 Ulf Bertilsson
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. This program is distributed WITHOUT ANY WARRANTY; see the LICENSE
# file, or <https://www.gnu.org/licenses/>, for the full terms.

"""Create a local 1:1 backup of a project and its Claude state.

A thin front end for the generic engine in agent_backup.py, pinned to the
Claude profile.

Example:
    python3 claude_full_backup.py --output /Volumes/Backup/claude-backups
"""
from __future__ import annotations

import argparse
from pathlib import Path

import agent_backup
from agent_backup import CLAUDE as PROFILE, VERSION, copy_tree, walk

collect_sqlite_schemas = agent_backup.collect_sqlite_schemas


def extract_claude_data(home: Path, destination: Path) -> tuple[int, int]:
    return agent_backup.extract_sessions(PROFILE, home, destination)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--claude-home", dest="home", type=Path, default=PROFILE.home())
    parser.add_argument("--output", type=Path, default=Path.home() / "Claude Backups")
    parser.add_argument("--version", action="version", version=f"claude-full-backup {VERSION}")
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    home = args.home.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if output in (project, home) or output.is_relative_to(project) or output.is_relative_to(home):
        parser.error("--output must not be the project or Claude home directory")

    metadata = agent_backup.backup(PROFILE, project, home, output)
    print(f"Created 1:1 backup: {metadata['path']}")
    print(f"Files copied: {metadata['file_count']}")
    if metadata["skipped"]:
        print(f"Entries skipped: {len(metadata['skipped'])} (see backup-metadata.json)")
    print(f"Chats extracted: {metadata['chat_count']}")
    print(f"Claude files inventoried: {metadata['inventory_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
