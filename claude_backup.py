#!/usr/bin/env python3
# agent-backup — mirror and back up local coding-agent session state.
# Copyright (C) 2026 Ulf Bertilsson
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. This program is distributed WITHOUT ANY WARRANTY; see the LICENSE
# file, or <https://www.gnu.org/licenses/>, for the full terms.

"""Mirror local Claude sessions to Markdown files.

A thin front end for the generic engine in agent_backup.py, pinned to the
Claude profile. Use agent_backup.py directly for other agents.

Usage: python claude_backup.py sync [--source PATH] [--output PATH]
       python claude_backup.py list [--source PATH]
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import agent_backup
from agent_backup import CLAUDE as PROFILE, VERSION

DEFAULT_OUTPUT = Path("claude-chats")


def default_source() -> Path:
    return PROFILE.home()


def sessions(source: Path):
    return agent_backup.sessions(PROFILE, source)


def session_id(path: Path, meta: dict[str, Any]) -> str:
    return agent_backup.session_id(PROFILE, path, meta)


def text_content(value: Any) -> str:
    return agent_backup.text_content(PROFILE, value)


def read_session(path: Path) -> tuple[dict[str, Any], list[tuple[str, str, str]]]:
    return agent_backup.read_session(PROFILE, path)


def render(path: Path, meta: dict[str, Any], messages: list[tuple[str, str, str]]) -> str:
    return agent_backup.render(PROFILE, path, meta, messages)


safe_name = agent_backup.safe_name


def main() -> int:
    parser = argparse.ArgumentParser(description="Mirror local Claude chats to Markdown files")
    parser.add_argument("command", choices=["sync", "list", "export"], nargs="?", default="sync")
    parser.add_argument("--source", type=Path, default=default_source(), help="Claude home directory")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Mirror directory")
    parser.add_argument("--zip", type=Path, help="ZIP path for export (default: claude-chats.zip)")
    parser.add_argument("--no-raw", action="store_true", help="Do not include original session files")
    parser.add_argument("--no-attachments", action="store_true", help="Do not include Claude attachments")
    parser.add_argument("--prune", action="store_true", help="Delete mirrored chats whose session is gone from the source")
    parser.add_argument("--version", action="version", version=f"claude-backup {VERSION}")
    args = parser.parse_args()

    if args.command == "list":
        for path in sessions(args.source):
            meta, messages = read_session(path)
            print(f"{session_id(path, meta)}\t{meta.get('thread_name', 'untitled')}\t{len(messages)} messages\t{meta.get('timestamp', '')}")
        return 0
    if args.command == "export":
        archive = args.zip or args.output.with_suffix(".zip")
        found = agent_backup.export(PROFILE, args.source, args.output, archive,
                                   not args.no_raw, not args.no_attachments, args.prune)
        print(f"Exported {len(found)} chats to {archive}")
        return 0
    found, _ = agent_backup.mirror(PROFILE, args.source, args.output, args.prune)
    print(f"Mirrored {len(found)} chats to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
