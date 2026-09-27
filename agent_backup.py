#!/usr/bin/env python3
# agent-backup — mirror and back up local coding-agent session state.
# Copyright (C) 2026 Ulf Bertilsson
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. This program is distributed WITHOUT ANY WARRANTY; see the LICENSE
# file, or <https://www.gnu.org/licenses/>, for the full terms.

"""Mirror and back up local coding-agent session state.

One engine serves any agent that records its sessions as JSONL. The shape of
those records lives in a *profile*, and profiles can be loaded from JSON, so
supporting a new agent needs no code:

    python3 agent_backup.py profiles
    python3 agent_backup.py list   --agent claude
    python3 agent_backup.py sync   --agent codex --output codex-chats
    python3 agent_backup.py export --agent auto
    python3 agent_backup.py backup --agent claude --output ~/Backups
    python3 agent_backup.py audit  --agent claude --json

Profiles are discovered in ``$AGENT_BACKUP_PROFILES``, ``./agent-profiles`` and
``~/.config/agent-backup/profiles``, or named directly with --profile-file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "0.1.0rc2"

#: A trailing UUID is how most agents name a session file.
UUID_SUFFIX = r"([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})$"


# --------------------------------------------------------------------------- #
# Profiles
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Profile:
    """Declarative description of one agent's on-disk session format."""

    name: str
    label: str = ""
    home_env: str = ""
    home_default: str = ""
    session_globs: tuple[str, ...] = ()
    #: Regex whose first group is the session id inside the file name. The file
    #: name outranks any id in the records: a resumed session commonly carries
    #: the id of the session it continues.
    id_pattern: str = UUID_SUFFIX
    #: Dotted record paths consulted when the file name has no id.
    id_fields: tuple[str, ...] = ()
    #: Ordered title sources; earlier entries win.
    title_rules: tuple[dict[str, Any], ...] = ()
    #: How to recognise a message record and where its role/content live.
    message_rules: tuple[dict[str, Any], ...] = ()
    #: Dotted paths whose truthiness excludes a record (sub-agent traffic, ...).
    skip_when: tuple[str, ...] = ()
    #: Content-block renderers, keyed by block type.
    blocks: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Render "[type]" for block types the profile does not know, instead of
    #: dropping them, so a format change shows up in the output.
    mark_unknown_blocks: bool = True
    #: (header label or "" to collect silently, dotted path).
    meta_fields: tuple[tuple[str, str], ...] = ()
    timestamp_fields: tuple[str, ...] = ("timestamp",)
    #: Record key holding the nested body, used by `audit` when profiling keys.
    body_field: str = ""
    #: Single files copied into the export under `extras_dir`.
    extras: tuple[str, ...] = ()
    extras_dir: str = ""
    #: Directories copied into the export at their own top level.
    attachment_dirs: tuple[str, ...] = ()
    event_profile_name: str = "transcript-event-profile.json"

    def title(self) -> str:
        return self.label or self.name.title()

    def home(self) -> Path:
        if self.home_env and os.environ.get(self.home_env):
            return Path(os.environ[self.home_env])
        return Path(self.home_default).expanduser()

    def inventory_name(self) -> str:
        return f"{self.name}-file-inventory.json"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Profile:
        known = set(cls.__dataclass_fields__)
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown profile keys: {', '.join(sorted(unknown))}")
        if not data.get("name"):
            raise ValueError("a profile needs a name")
        values: dict[str, Any] = dict(data)
        for key in ("session_globs", "id_fields", "skip_when", "extras", "attachment_dirs", "timestamp_fields"):
            if key in values:
                values[key] = tuple(values[key])
        for key in ("title_rules", "message_rules"):
            if key in values:
                values[key] = tuple(dict(rule) for rule in values[key])
        if "meta_fields" in values:
            values["meta_fields"] = tuple((str(a), str(b)) for a, b in values["meta_fields"])
        return cls(**values)


TEXT = {"kind": "text", "key": "text"}

CLAUDE = Profile(
    name="claude",
    label="Claude",
    home_env="CLAUDE_CONFIG_DIR",
    home_default="~/.claude",
    session_globs=("projects/*/*.jsonl", "sessions/**/*.jsonl"),
    id_fields=(),  # the file name is the only id we trust
    title_rules=(
        {"match": {"type": "custom-title"}, "field": "customTitle"},
        {"match": {"type": "ai-title"}, "field": "aiTitle"},
    ),
    message_rules=(
        {"match": {"type": ["user", "assistant"]}, "role": "message.role",
         "role_default": "type", "content": "message.content"},
    ),
    skip_when=("isSidechain",),
    blocks={
        "text": TEXT,
        "thinking": {"kind": "wrapped", "key": "thinking", "tag": "thinking"},
        "tool_use": {"kind": "label", "label": "tool_use", "key": "name"},
        "tool_result": {"kind": "nested", "label": "tool_result", "key": "content"},
        "tool_reference": {"kind": "label", "label": "tool_reference", "key": "name"},
        "image": {"kind": "marker", "label": "image"},
    },
    meta_fields=(("Project", "cwd"), ("", "gitBranch"), ("", "version")),
    body_field="message",
    extras=("settings.json", "CLAUDE.md", "keybindings.json"),
    extras_dir="claude",
    attachment_dirs=("plans", "tasks"),
)

CODEX = Profile(
    name="codex",
    label="Codex",
    home_env="CODEX_HOME",
    home_default="~/.codex",
    session_globs=("sessions/**/*.jsonl", "archived_sessions/*.jsonl"),
    id_fields=("payload.id",),
    title_rules=(
        {"match": {"type": "session_meta"}, "field": "payload.thread_name"},
        {"match": {"type": "session_meta"}, "field": "payload.title"},
    ),
    message_rules=(
        {"match": {"type": "response_item", "payload.type": "message"},
         "role": "payload.role", "content": "payload.content"},
    ),
    blocks={
        "input_text": TEXT,
        "output_text": TEXT,
        "text": TEXT,
        "input_image": {"kind": "marker", "label": "image"},
        "output_image": {"kind": "marker", "label": "image"},
        "image": {"kind": "marker", "label": "image"},
    },
    body_field="payload",
    extras=("session_index.jsonl", "config.toml"),
    extras_dir="codex",
    attachment_dirs=("attachments",),
    event_profile_name="rollout-event-profile.json",
)

BUILTIN: dict[str, Profile] = {CLAUDE.name: CLAUDE, CODEX.name: CODEX}


def profile_search_paths() -> list[Path]:
    paths = [Path("agent-profiles"), Path.home() / ".config" / "agent-backup" / "profiles"]
    extra = os.environ.get("AGENT_BACKUP_PROFILES")
    if extra:
        paths = [Path(p) for p in extra.split(os.pathsep) if p] + paths
    return paths


def load_profile_file(path: Path) -> list[Profile]:
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("profiles", [data]) if isinstance(data, dict) else data
    return [Profile.from_dict(entry) for entry in entries]


def registry(extra_files: Iterable[Path] = ()) -> dict[str, Profile]:
    """Built-in profiles, overlaid with any discovered or named JSON profiles."""
    found = dict(BUILTIN)
    for directory in reversed(profile_search_paths()):
        if directory.is_dir():
            for path in sorted(directory.glob("*.json")):
                for profile in load_profile_file(path):
                    found[profile.name] = profile
    for path in extra_files:
        for profile in load_profile_file(path):
            found[profile.name] = profile
    return found


# --------------------------------------------------------------------------- #
# Reading sessions
# --------------------------------------------------------------------------- #

def write_json(path: Path, data: Any, sort_keys: bool = True) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=sort_keys) + "\n", encoding="utf-8")


def dig(record: Any, path: str) -> Any:
    value = record
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def matches(record: dict[str, Any], condition: dict[str, Any]) -> bool:
    for path, expected in condition.items():
        value = dig(record, path)
        if isinstance(expected, list):
            if value not in expected:
                return False
        elif value != expected:
            return False
    return True


def sessions(profile: Profile, source: Path) -> Iterator[Path]:
    # Resolve duplicates defensively (for example, if a source layout adds a
    # second index pointing at the same session file).
    seen: set[Path] = set()
    globbed: list[Path] = []
    for pattern in profile.session_globs:
        globbed.extend(source.glob(pattern))
    for path in sorted(globbed):
        resolved = path.resolve()
        if resolved not in seen and path.is_file():
            seen.add(resolved)
            yield path


def session_id(profile: Profile, path: Path, meta: dict[str, Any]) -> str:
    if profile.id_pattern:
        match = re.search(profile.id_pattern, path.stem)
        if match:
            return match.group(1)
    recorded = (meta.get(field.split(".")[-1]) for field in profile.id_fields)
    for value in (meta.get("id"), *recorded):
        if value:
            return str(value)
    return path.stem


def text_content(profile: Profile, value: Any, depth: int = 0) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and depth < 8:
        parts: list[str] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            kind = item.get("type")
            spec = profile.blocks.get(str(kind))
            if spec is None:
                if profile.mark_unknown_blocks and kind:
                    parts.append(f"[{kind}]")
                continue
            style = spec.get("kind", "text")
            if style == "text":
                parts.append(str(item.get(spec.get("key", "text"), "")))
            elif style == "wrapped":
                body = str(item.get(spec.get("key", "text"), "")).strip()
                tag = spec.get("tag", "detail")
                if body:
                    parts.append(f"<{tag}>\n{body}\n</{tag}>")
            elif style == "label":
                name = item.get(spec.get("key", "name"), "unknown")
                parts.append(f"[{spec.get('label', kind)}: {name}]")
            elif style == "marker":
                parts.append(f"[{spec.get('label', kind)}]")
            elif style == "nested":
                nested = text_content(profile, item.get(spec.get("key", "content")), depth + 1)
                parts.append(f"[{spec.get('label', kind)}]\n{nested}")
        return "\n".join(p for p in parts if p)
    if isinstance(value, dict) and isinstance(value.get("text"), str):
        return value["text"]
    return ""


def records(path: Path) -> Iterator[dict[str, Any]]:
    """Yield the object records of a JSONL file, tolerating damage."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            yield item


def read_session(profile: Profile, path: Path) -> tuple[dict[str, Any], list[tuple[str, str, str]]]:
    meta: dict[str, Any] = {}
    messages: list[tuple[str, str, str]] = []
    best_title = len(profile.title_rules)
    for item in records(path):
        for rank, rule in enumerate(profile.title_rules):
            if rank <= best_title and matches(item, rule.get("match", {})):
                value = dig(item, rule["field"])
                if value:
                    meta["thread_name"], best_title = value, rank
        for _, dotted in profile.meta_fields:
            value = dig(item, dotted)
            if value:
                meta.setdefault(dotted.split(".")[-1], value)
        for dotted in profile.id_fields:
            value = dig(item, dotted)
            if value:
                meta.setdefault(dotted.split(".")[-1], value)
                meta.setdefault("id", value)
        for dotted in profile.timestamp_fields:
            stamp = dig(item, dotted)
            if stamp:
                meta.setdefault("timestamp", stamp)
                meta["updated_at"] = stamp
                break
        if any(dig(item, dotted) for dotted in profile.skip_when):
            continue
        for rule in profile.message_rules:
            if not matches(item, rule.get("match", {})):
                continue
            body = text_content(profile, dig(item, rule["content"]))
            if body:
                role = dig(item, rule.get("role", "role")) or dig(item, rule.get("role_default", "")) or "unknown"
                stamp = next((dig(item, d) for d in profile.timestamp_fields if dig(item, d)), "")
                messages.append((str(role), str(stamp or ""), body))
            break
    meta["id"] = session_id(profile, path, meta)
    return meta, messages


def safe_name(value: str) -> str:
    value = "".join(c if c.isalnum() or c in " ._-" else "_" for c in value).strip()
    return (value or "untitled")[:100]


def render(profile: Profile, path: Path, meta: dict[str, Any], messages: list[tuple[str, str, str]]) -> str:
    title = meta.get("thread_name") or meta.get("title") or meta.get("id") or path.stem
    lines = [f"# {title}", "", f"- Session: `{meta.get('id', path.stem)}`"]
    for label, dotted in profile.meta_fields:
        value = meta.get(dotted.split(".")[-1])
        if label and value:
            lines.append(f"- {label}: {value}")
    lines += [f"- Updated: {meta.get('updated_at', meta.get('timestamp', ''))}", ""]
    for role, timestamp, body in messages:
        lines += [f"## {role.title()}" + (f" — {timestamp}" if timestamp else ""), "", body.rstrip(), ""]
    return "\n".join(lines)


def chat_name(profile: Profile, path: Path, meta: dict[str, Any]) -> str:
    sid = session_id(profile, path, meta)
    return f"{safe_name(str(meta.get('thread_name') or sid))}--{sid}.md"


# --------------------------------------------------------------------------- #
# Mirroring and exporting
# --------------------------------------------------------------------------- #

def mirror(profile: Profile, source: Path, output: Path, prune: bool = False) -> tuple[list[Path], dict[str, str]]:
    found = list(sessions(profile, source))
    output.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, str] = {}
    written: set[Path] = set()
    for path in found:
        meta, messages = read_session(profile, path)
        destination = output / chat_name(profile, path, meta)
        if destination in written:
            # Two sources claiming one id: keep both rather than overwrite.
            suffix = hashlib.sha256(str(path).encode()).hexdigest()[:10]
            destination = destination.with_name(f"{destination.stem}--{suffix}.md")
        written.add(destination)
        content = render(profile, path, meta, messages)
        digest = hashlib.sha256(content.encode()).hexdigest()
        manifest[destination.name] = digest
        if not destination.exists() or hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
            destination.write_text(content, encoding="utf-8")
    live = {f"--{session_id(profile, path, {})}.md" for path in found}
    for stale in output.glob("*--*.md"):
        if stale in written:
            continue
        # A retitled session leaves its old file behind; drop it. Files for
        # sessions no longer in the source are only removed with --prune.
        if prune or "--" + stale.name.split("--")[-1] in live:
            stale.unlink()
    write_json(output / ".manifest.json", manifest)
    return found, manifest


def export(profile: Profile, source: Path, output: Path, archive: Path,
           raw: bool = True, attachments: bool = True, prune: bool = False,
           force: bool = False) -> list[Path]:
    # An export is an archive of state that may no longer exist anywhere else,
    # so replacing one is never implicit.
    if archive.exists() and not force:
        raise FileExistsError(f"{archive} already exists; pass force to replace it, or choose another path")
    found, _ = mirror(profile, source, output, prune)
    metadata = {
        "format": f"{profile.name}-chat-export-v1",
        "tool": "agent-backup",
        "tool_version": VERSION,
        "agent": profile.name,
        "source": str(source),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "chat_count": len(found),
        "raw_sessions": raw,
        "attachments": attachments,
    }
    write_json(output / "export-metadata.json", metadata, sort_keys=False)
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in output.rglob("*"):
            if file.is_file():
                zf.write(file, Path("chats") / file.relative_to(output))
        if raw:
            for file in found:
                # Preserve enough source structure to avoid collisions between
                # session files that share a name in different directories.
                try:
                    relative = file.relative_to(source)
                except ValueError:
                    relative = Path(file.name)
                zf.write(file, Path("raw") / relative)
        for extra in profile.extras:
            path = source / extra
            if path.is_file():
                zf.write(path, Path(profile.extras_dir or profile.name) / path.name)
        if attachments:
            for attachment_dir in profile.attachment_dirs:
                directory = source / attachment_dir
                if directory.is_dir():
                    for file in directory.rglob("*"):
                        if file.is_file():
                            zf.write(file, Path(attachment_dir) / file.relative_to(directory))
    return found


# --------------------------------------------------------------------------- #
# Full 1:1 backup
# --------------------------------------------------------------------------- #

def walk(source: Path, skipped: list[str] | None = None) -> Iterator[Path]:
    """Yield every entry under source, reporting directories we cannot read."""
    stack = [source]
    while stack:
        directory = stack.pop()
        try:
            entries = sorted(directory.iterdir())
        except OSError as exc:
            if skipped is not None:
                skipped.append(f"{directory}: {exc.strerror or exc}")
            continue
        for item in entries:
            yield item
            if item.is_dir() and not item.is_symlink():
                stack.append(item)


def copy_tree(source: Path, destination: Path, manifest: dict[str, str], skipped: list[str], prefix: str) -> None:
    if not source.exists():
        return
    for item in walk(source, skipped):
        relative = item.relative_to(source)
        target = destination / relative
        try:
            if item.is_dir() and not item.is_symlink():
                target.mkdir(parents=True, exist_ok=True)
                shutil.copystat(item, target, follow_symlinks=False)
            elif item.is_symlink():
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() or target.is_symlink():
                    target.unlink()
                target.symlink_to(os.readlink(item))
            elif item.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
                manifest[f"{prefix}/{relative}"] = hashlib.sha256(item.read_bytes()).hexdigest()
            else:
                # Sockets, FIFOs and device nodes are not part of a backup.
                skipped.append(f"{prefix}/{relative}: not a regular file")
        except OSError as exc:
            skipped.append(f"{prefix}/{relative}: {exc.strerror or exc}")


def extract_sessions(profile: Profile, home: Path, destination: Path) -> tuple[int, int]:
    """Write readable chats and a file inventory alongside the raw backup."""
    chats = destination / "chats"
    chats.mkdir(parents=True, exist_ok=True)
    count = 0
    for path in sessions(profile, home):
        meta, messages = read_session(profile, path)
        target = chats / chat_name(profile, path, meta)
        if target.exists():
            suffix = hashlib.sha256(str(path).encode()).hexdigest()[:10]
            target = target.with_name(f"{target.stem}--{suffix}.md")
        target.write_text(render(profile, path, meta, messages), encoding="utf-8")
        count += 1

    inventory = []
    for item in sorted(walk(home)):
        if item.is_file() or item.is_symlink():
            try:
                stat = item.lstat()
            except OSError:
                continue
            inventory.append({
                "path": str(item.relative_to(home)),
                "bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                "symlink": item.is_symlink(),
            })
    write_json(destination / profile.inventory_name(), inventory, sort_keys=False)
    return count, len(inventory)


def profile_events(profile: Profile, home: Path, destination: Path) -> None:
    """Profile observed JSONL record shapes without copying message contents."""
    report: dict[str, Any] = {"files": 0, "lines": 0, "invalid_json": 0, "record_types": {}, "body_keys": {}}
    for path in sessions(profile, home):
        report["files"] += 1
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            report["lines"] += 1
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                report["invalid_json"] += 1
                continue
            kind = item.get("type", "<missing>") if isinstance(item, dict) else "<non-object>"
            report["record_types"][kind] = report["record_types"].get(kind, 0) + 1
            body = dig(item, profile.body_field) if profile.body_field and isinstance(item, dict) else None
            if isinstance(body, dict):
                keys = report["body_keys"].setdefault(kind, {})
                for key in body:
                    keys[key] = keys.get(key, 0) + 1
    write_json(destination / profile.event_profile_name, report)


def collect_sqlite_schemas(home: Path, destination: Path) -> None:
    schemas: dict[str, Any] = {}
    for db in sorted(item for item in walk(home) if item.suffix in {".sqlite", ".db"}):
        if not db.is_file():
            continue
        try:
            with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as connection:
                tables = {}
                listing = "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                fields = ("cid", "name", "type", "notnull", "default", "pk")
                for (name,) in connection.execute(listing):
                    columns = [dict(zip(fields, row, strict=False))
                               for row in connection.execute(f'PRAGMA table_info("{name}")')]
                    sql = connection.execute("SELECT sql FROM sqlite_master WHERE name = ?", (name,)).fetchone()[0]
                    tables[name] = {"columns": columns, "sql": sql}
                schemas[str(db.relative_to(home))] = {"tables": tables}
        except sqlite3.Error as exc:
            schemas[str(db.relative_to(home))] = {"error": str(exc)}
    write_json(destination / "sqlite-schema.json", schemas)


def backup(profile: Profile, project: Path, home: Path, output: Path) -> dict[str, Any]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = output / f"{profile.name}-backup-{stamp}"
    destination.mkdir(parents=True, exist_ok=False)
    manifest: dict[str, str] = {}
    skipped: list[str] = []
    copy_tree(project, destination / "project", manifest, skipped, "project")
    copy_tree(home, destination / f"{profile.name}-home", manifest, skipped, f"{profile.name}-home")
    extracted = destination / "extracted"
    chat_count, inventory_count = extract_sessions(profile, home, extracted)
    profile_events(profile, home, extracted)
    collect_sqlite_schemas(home, extracted)
    metadata = {
        "format": f"{profile.name}-full-backup-v1",
        "tool": "agent-backup",
        "tool_version": VERSION,
        "agent": profile.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project": str(project),
        "home": str(home),
        f"{profile.name}_home": str(home),
        "file_count": len(manifest),
        "chat_count": chat_count,
        "inventory_count": inventory_count,
        f"{profile.name}_inventory_count": inventory_count,
        "artifacts": [
            "extracted/chats/",
            f"extracted/{profile.inventory_name()}",
            f"extracted/{profile.event_profile_name}",
            "extracted/sqlite-schema.json",
        ],
        "skipped": skipped,
        "sha256": manifest,
    }
    write_json(destination / "backup-metadata.json", metadata)
    metadata["path"] = str(destination)
    return metadata


# --------------------------------------------------------------------------- #
# Auditing
# --------------------------------------------------------------------------- #

def audit(profile: Profile, home: Path) -> dict[str, Any]:
    """Check a profile against real files: coverage, ids, collisions, damage."""
    report: dict[str, Any] = {
        "agent": profile.name, "source": str(home), "files": 0, "lines": 0,
        "invalid_json": 0, "non_object_lines": 0, "record_types": {},
        "block_types": {}, "unhandled_blocks": {}, "message_records": 0,
        "rendered_messages": 0, "duplicate_ids": {}, "name_collisions": {},
        "id_from_records_differs": [],
    }
    ids: dict[str, list[str]] = {}
    names: dict[str, list[str]] = {}
    for path in sessions(profile, home):
        report["files"] += 1
        meta, messages = read_session(profile, path)
        report["rendered_messages"] += len(messages)
        sid = session_id(profile, path, meta)
        ids.setdefault(sid, []).append(str(path))
        names.setdefault(chat_name(profile, path, meta), []).append(str(path))
        for dotted in profile.id_fields:
            recorded = meta.get(dotted.split(".")[-1])
            if recorded and str(recorded) != sid:
                report["id_from_records_differs"].append({"file": path.name, "recorded": str(recorded), "used": sid})
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            report.setdefault("unreadable", []).append(f"{path}: {exc.strerror or exc}")
            continue
        for line in text.splitlines():
            if not line.strip():
                continue
            report["lines"] += 1
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                report["invalid_json"] += 1
                continue
            if not isinstance(item, dict):
                report["non_object_lines"] += 1
                continue
            kind = str(item.get("type", "<missing>"))
            report["record_types"][kind] = report["record_types"].get(kind, 0) + 1
            for rule in profile.message_rules:
                if not matches(item, rule.get("match", {})):
                    continue
                report["message_records"] += 1
                _count_blocks(profile, dig(item, rule["content"]), report)
                break
    report["duplicate_ids"] = {k: v for k, v in ids.items() if len(v) > 1}
    report["name_collisions"] = {k: v for k, v in names.items() if len(v) > 1}
    report["ok"] = not (report["invalid_json"] or report["unhandled_blocks"]
                        or report["duplicate_ids"] or report["name_collisions"]
                        or report.get("unreadable"))
    return report


def _count_blocks(profile: Profile, value: Any, report: dict[str, Any], depth: int = 0) -> None:
    if not isinstance(value, list) or depth > 8:
        return
    for item in value:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type"))
        report["block_types"][kind] = report["block_types"].get(kind, 0) + 1
        spec = profile.blocks.get(kind)
        if spec is None:
            report["unhandled_blocks"][kind] = report["unhandled_blocks"].get(kind, 0) + 1
        elif spec.get("kind") == "nested":
            _count_blocks(profile, item.get(spec.get("key", "content")), report, depth + 1)


# --------------------------------------------------------------------------- #
# Command line
# --------------------------------------------------------------------------- #

def detect(known: dict[str, Profile]) -> list[Profile]:
    return [p for p in known.values() if p.home().is_dir() and next(sessions(p, p.home()), None)]


def resolve_profile(parser: argparse.ArgumentParser, name: str, files: Iterable[Path]) -> Profile:
    known = registry(files)
    if name != "auto":
        if name not in known:
            parser.error(f"unknown agent '{name}'; known: {', '.join(sorted(known))}")
        return known[name]
    candidates = detect(known)
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        parser.error(f"no agent state found; name one with --agent (known: {', '.join(sorted(known))})")
    parser.error("several agents found: " + ", ".join(p.name for p in candidates) + "; pick one with --agent")
    raise SystemExit(2)  # unreachable: parser.error exits


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mirror and back up local coding-agent session state")
    parser.add_argument("command", choices=["list", "sync", "export", "backup", "audit", "profiles"],
                        nargs="?", default="sync")
    parser.add_argument("--agent", default="auto", help="Profile name, or 'auto' to detect (default: auto)")
    parser.add_argument("--profile-file", type=Path, action="append", default=[],
                        metavar="PATH", help="Load extra profiles from a JSON file (repeatable)")
    parser.add_argument("--source", "--home", type=Path, dest="source", help="Agent home directory")
    parser.add_argument("--output", type=Path, help="Mirror directory, or backup destination")
    parser.add_argument("--zip", type=Path, help="ZIP path for export")
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="Project tree to back up")
    parser.add_argument("--no-raw", action="store_true", help="Do not include original session files")
    parser.add_argument("--no-attachments", action="store_true", help="Do not include attachment directories")
    parser.add_argument("--prune", action="store_true", help="Delete mirrored chats whose session is gone")
    parser.add_argument("--force", action="store_true", help="Let export replace an archive that already exists")
    parser.add_argument("--json", action="store_true", help="Machine-readable output where available")
    parser.add_argument("--version", action="version", version=f"agent-backup {VERSION}")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "profiles":
        known = registry(args.profile_file)
        available = {p.name for p in detect(known)}
        for name, profile in sorted(known.items()):
            home = profile.home()
            state = "found" if name in available else ("empty" if home.is_dir() else "absent")
            builtin = "built-in" if name in BUILTIN else "custom"
            print(f"{name}\t{builtin}\t{home}\t{state}")
        if args.json:
            print(json.dumps({name: p.to_dict() for name, p in sorted(known.items())}, indent=2, sort_keys=True))
        return 0

    profile = resolve_profile(parser, args.agent, args.profile_file)
    source = (args.source or profile.home()).expanduser()

    if args.command == "audit":
        report = audit(profile, source)
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(f"agent: {profile.name}   source: {report['source']}")
            print(f"files: {report['files']}   records: {report['lines']}   invalid json: {report['invalid_json']}")
            print(f"messages: {report['message_records']}   rendered: {report['rendered_messages']}")
            unhandled = json.dumps(report["unhandled_blocks"]) if report["unhandled_blocks"] else "none"
            print("unhandled block types: " + unhandled)
            print("duplicate ids: " + (", ".join(report["duplicate_ids"]) or "none"))
            print("name collisions: " + (", ".join(report["name_collisions"]) or "none"))
            if report["id_from_records_differs"]:
                print(f"sessions whose records name another id: {len(report['id_from_records_differs'])}")
            print("verdict: " + ("ok" if report["ok"] else "problems found"))
        return 0 if report["ok"] else 1

    if args.command == "backup":
        project = args.project.expanduser().resolve()
        home = source.resolve()
        output = (args.output or Path.home() / f"{profile.title()} Backups").expanduser().resolve()
        if output in (project, home) or output.is_relative_to(project) or output.is_relative_to(home):
            parser.error(f"--output must not be the project or the {profile.title()} home directory")
        metadata = backup(profile, project, home, output)
        print(f"Created 1:1 backup: {metadata['path']}")
        print(f"Files copied: {metadata['file_count']}")
        if metadata["skipped"]:
            print(f"Entries skipped: {len(metadata['skipped'])} (see backup-metadata.json)")
        print(f"Chats extracted: {metadata['chat_count']}")
        print(f"{profile.title()} files inventoried: {metadata['inventory_count']}")
        return 0

    output = args.output or Path(f"{profile.name}-chats")
    if args.command == "list":
        rows = []
        for path in sessions(profile, source):
            meta, messages = read_session(profile, path)
            rows.append({"id": session_id(profile, path, meta), "title": meta.get("thread_name", "untitled"),
                         "messages": len(messages), "timestamp": meta.get("timestamp", ""), "file": str(path)})
        if args.json:
            print(json.dumps(rows, indent=2))
        else:
            for row in rows:
                print(f"{row['id']}\t{row['title']}\t{row['messages']} messages\t{row['timestamp']}")
        return 0

    if args.command == "export":
        archive = args.zip or output.with_suffix(".zip")
        try:
            found = export(profile, source, output, archive, not args.no_raw,
                           not args.no_attachments, args.prune, args.force)
        except FileExistsError:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            suggestion = archive.with_name(f"{archive.stem}-{stamp}{archive.suffix}")
            parser.error(f"{archive} already exists. An export can hold sessions that are gone "
                         f"from disk, so it is never replaced silently. Write a new archive with "
                         f"--zip {suggestion}, or pass --force to replace this one.")
        print(f"Exported {len(found)} chats to {archive}")
        return 0

    found, _ = mirror(profile, source, output, args.prune)
    print(f"Mirrored {len(found)} chats to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
