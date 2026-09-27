# agent-backup — mirror and back up local coding-agent session state.
# Copyright (C) 2026 Ulf Bertilsson
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. This program is distributed WITHOUT ANY WARRANTY; see the LICENSE
# file, or <https://www.gnu.org/licenses/>, for the full terms.

import json
import os
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import agent_backup
from agent_backup import (
    CLAUDE,
    CODEX,
    Profile,
    audit,
    dig,
    matches,
    mirror,
    read_session,
    registry,
    render,
    session_id,
    text_content,
)

ROOT = Path(__file__).resolve().parents[1]

EXAMPLE = {
    "name": "example",
    "home_env": "EXAMPLE_AGENT_HOME",
    "home_default": "~/.example-agent",
    "session_globs": ["threads/*.jsonl"],
    "id_fields": ["thread_id"],
    "type_field": "kind",
    "title_rules": [{"match": {"kind": "meta"}, "field": "subject"}],
    "message_rules": [{"match": {"kind": "turn"}, "role": "speaker", "content": "body"}],
    "skip_when": ["hidden"],
    "blocks": {
        "say": {"kind": "text", "key": "text"},
        "call": {"kind": "label", "label": "tool", "key": "tool"},
        "result": {"kind": "nested", "label": "result", "key": "parts"},
        "picture": {"kind": "marker", "label": "image"},
    },
    "meta_fields": [["Workspace", "workspace"]],
    "timestamp_fields": ["at"],
}


def write_thread(home: Path, name: str, rows: list[dict]) -> Path:
    directory = home / "threads"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return path


def test_dig_and_matches():
    record = {"a": {"b": "c"}, "t": "x"}
    assert dig(record, "a.b") == "c"
    assert dig(record, "a.b.c") is None and dig(record, "nope") is None
    assert matches(record, {"a.b": "c", "t": ["x", "y"]})
    assert not matches(record, {"t": "z"})


def test_profile_roundtrip_and_validation():
    profile = Profile.from_dict(EXAMPLE)
    assert Profile.from_dict(profile.to_dict()) == profile
    with pytest.raises(ValueError):
        Profile.from_dict({"name": "x", "bogus": 1})
    with pytest.raises(ValueError):
        Profile.from_dict({"label": "no name"})


def test_custom_profile_reads_a_foreign_format(tmp_path: Path):
    profile = Profile.from_dict(EXAMPLE)
    path = write_thread(tmp_path, "t1", [
        {"kind": "meta", "subject": "Hello there", "thread_id": "T-1", "workspace": "/w", "at": "2026-01-01T00:00:00Z"},
        {"kind": "turn", "speaker": "human", "at": "2026-01-01T00:00:01Z",
         "body": [{"type": "say", "text": "hi"}, {"type": "picture"}]},
        {"kind": "turn", "speaker": "robot", "hidden": True, "body": [{"type": "say", "text": "secret"}]},
        {"kind": "turn", "speaker": "robot", "at": "2026-01-01T00:00:02Z", "body": [
            {"type": "call", "tool": "grep"},
            {"type": "result", "parts": [{"type": "say", "text": "found"}]},
        ]},
    ])
    meta, messages = read_session(profile, path)
    assert meta["thread_name"] == "Hello there"
    assert session_id(profile, path, meta) == "T-1"  # no UUID in the name, so the record wins
    assert [m[0] for m in messages] == ["human", "robot"]
    assert messages[0][2] == "hi\n[image]"
    assert messages[1][2] == "[tool: grep]\n[result]\nfound"
    output = render(profile, path, meta, messages)
    assert "# Hello there" in output and "- Workspace: /w" in output
    assert "## Human — 2026-01-01T00:00:01Z" in output


def test_unknown_block_types_are_marked_not_dropped(tmp_path: Path):
    profile = Profile.from_dict(EXAMPLE)
    path = write_thread(tmp_path, "t1", [{"kind": "turn", "speaker": "robot", "body": [{"type": "brand_new"}]}])
    _, messages = read_session(profile, path)
    assert messages[0][2] == "[brand_new]"
    quiet = Profile.from_dict({**EXAMPLE, "mark_unknown_blocks": False})
    assert text_content(quiet, [{"type": "brand_new"}]) == ""


def test_records_tolerates_damage(tmp_path: Path):
    path = tmp_path / "t.jsonl"
    path.write_text('not json\n[1,2]\n{"kind":"turn"}\n\n', encoding="utf-8")
    assert list(agent_backup.records(path)) == [{"kind": "turn"}]
    assert list(agent_backup.records(tmp_path / "missing.jsonl")) == []


def test_registry_discovers_json_profiles(tmp_path: Path):
    (tmp_path / "extra.json").write_text(json.dumps(EXAMPLE), encoding="utf-8")
    known = registry([tmp_path / "extra.json"])
    assert {"claude", "codex", "example"} <= set(known)
    assert known["example"].session_globs == ("threads/*.jsonl",)


def test_bundled_profiles_files_are_valid():
    for path in sorted((ROOT / "agent-profiles").glob("*.json")):
        for profile in agent_backup.load_profile_file(path):
            assert profile.name and profile.message_rules


def test_home_honours_environment(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("EXAMPLE_AGENT_HOME", str(tmp_path))
    assert Profile.from_dict(EXAMPLE).home() == tmp_path
    monkeypatch.delenv("EXAMPLE_AGENT_HOME")
    assert Profile.from_dict(EXAMPLE).home() == Path("~/.example-agent").expanduser()


def test_audit_reports_a_clean_profile_and_a_broken_one(tmp_path: Path):
    profile = Profile.from_dict(EXAMPLE)
    write_thread(tmp_path, "t1", [
        {"kind": "meta", "subject": "One", "thread_id": "T-1"},
        {"kind": "turn", "speaker": "human", "body": [{"type": "say", "text": "hi"}]},
    ])
    report = audit(profile, tmp_path)
    assert report["ok"] and report["files"] == 1 and report["message_records"] == 1
    assert report["unhandled_blocks"] == {} and report["block_types"] == {"say": 1}

    write_thread(tmp_path, "t2", [
        {"kind": "meta", "subject": "One", "thread_id": "T-1"},
        {"kind": "turn", "speaker": "human", "body": [{"type": "mystery"}]},
    ])
    (tmp_path / "threads" / "t3.jsonl").write_text("{oops\n", encoding="utf-8")
    broken = audit(profile, tmp_path)
    assert not broken["ok"]
    assert broken["unhandled_blocks"] == {"mystery": 1}
    assert list(broken["duplicate_ids"]) == ["T-1"] and list(broken["name_collisions"]) == ["One--T-1.md"]
    assert broken["invalid_json"] == 1


def test_mirror_keeps_colliding_ids_apart(tmp_path: Path):
    profile = Profile.from_dict(EXAMPLE)
    home, output = tmp_path / "home", tmp_path / "out"
    for name in ("t1", "t2"):
        write_thread(home, name, [
            {"kind": "meta", "subject": "Same", "thread_id": "T-1"},
            {"kind": "turn", "speaker": "human", "body": [{"type": "say", "text": name}]},
        ])
    _, manifest = mirror(profile, home, output)
    assert len(manifest) == 2
    assert (output / "Same--T-1.md").exists()
    assert len(list(output.glob("Same--T-1--*.md"))) == 1


def run(*args: str) -> str:
    result = subprocess.run([sys.executable, str(ROOT / "agent_backup.py"), *args],
                            capture_output=True, text=True, cwd=ROOT, check=True)
    return result.stdout


def test_cli_profiles_lists_builtins_and_custom():
    stdout = run("profiles")
    assert "claude\tbuilt-in" in stdout and "codex\tbuilt-in" in stdout
    assert "example\tcustom" in stdout  # from agent-profiles/


def test_cli_auto_detects_a_single_agent(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    write_thread(home, "t1", [{"kind": "meta", "subject": "Auto", "thread_id": "T-1"},
                              {"kind": "turn", "speaker": "human", "body": [{"type": "say", "text": "hi"}]}])
    # Copy the real environment: a bare dict leaves Windows runners without
    # SYSTEMROOT, and the interpreter then fails to start at all.
    env = {**os.environ, "EXAMPLE_AGENT_HOME": str(home),
           "CLAUDE_CONFIG_DIR": str(tmp_path / "none"), "CODEX_HOME": str(tmp_path / "none")}
    result = subprocess.run([sys.executable, str(ROOT / "agent_backup.py"), "list", "--json"],
                            capture_output=True, text=True, cwd=ROOT, env=env, check=True)
    assert json.loads(result.stdout)[0]["title"] == "Auto"


def test_cli_unknown_agent_and_ambiguous_auto_fail(tmp_path: Path):
    bad = subprocess.run([sys.executable, str(ROOT / "agent_backup.py"), "list", "--agent", "nope"],
                         capture_output=True, text=True, cwd=ROOT)
    assert bad.returncode == 2 and "unknown agent" in bad.stderr


def test_cli_audit_exit_code_and_json(tmp_path: Path):
    home = tmp_path / "home"
    write_thread(home, "t1", [{"kind": "turn", "speaker": "human", "body": [{"type": "mystery"}]}])
    result = subprocess.run([sys.executable, str(ROOT / "agent_backup.py"), "audit", "--agent", "example",
                             "--source", str(home), "--json"], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 1
    assert json.loads(result.stdout)["unhandled_blocks"] == {"mystery": 1}


def test_cli_export_and_backup_for_a_custom_profile(tmp_path: Path):
    home, output = tmp_path / "home", tmp_path / "out"
    write_thread(home, "t1", [{"kind": "meta", "subject": "Ship", "thread_id": "T-1"},
                              {"kind": "turn", "speaker": "human", "body": [{"type": "say", "text": "hi"}]}])
    (home / "config.yaml").write_text("k: v", encoding="utf-8")
    (home / "files").mkdir()
    (home / "files" / "a.bin").write_text("x", encoding="utf-8")
    run("export", "--agent", "example", "--source", str(home), "--output", str(output))
    with zipfile.ZipFile(output.with_suffix(".zip")) as zf:
        names = set(zf.namelist())
        metadata = json.loads(zf.read("chats/export-metadata.json"))
    assert {"chats/Ship--T-1.md", "raw/threads/t1.jsonl", "example/config.yaml", "files/a.bin"} <= names
    assert metadata["agent"] == "example" and metadata["tool_version"] == agent_backup.VERSION

    project = tmp_path / "proj"
    project.mkdir()
    (project / "code.py").write_text("print()", encoding="utf-8")
    stdout = run("backup", "--agent", "example", "--source", str(home),
                 "--project", str(project), "--output", str(tmp_path / "backups"))
    assert "Created 1:1 backup" in stdout
    created = next((tmp_path / "backups").iterdir())
    metadata = json.loads((created / "backup-metadata.json").read_text(encoding="utf-8"))
    assert metadata["agent"] == "example" and metadata["chat_count"] == 1
    assert (created / "extracted" / "chats" / "Ship--T-1.md").exists()
    assert (created / "extracted" / "example-file-inventory.json").exists()
    assert (created / "project" / "code.py").exists()
    assert metadata["sha256"]["project/code.py"]


def test_export_refuses_to_replace_an_existing_archive(tmp_path: Path):
    home, output = tmp_path / "home", tmp_path / "out"
    write_thread(home, "t1", [{"kind": "meta", "subject": "Keep", "thread_id": "T-1"},
                              {"kind": "turn", "speaker": "human", "body": [{"type": "say", "text": "hi"}]}])
    archive = tmp_path / "chats.zip"
    run("export", "--agent", "example", "--source", str(home), "--output", str(output), "--zip", str(archive))
    first = archive.read_bytes()

    refused = subprocess.run([sys.executable, str(ROOT / "agent_backup.py"), "export", "--agent", "example",
                              "--source", str(home), "--output", str(output), "--zip", str(archive)],
                             capture_output=True, text=True, cwd=ROOT)
    assert refused.returncode == 2
    assert "already exists" in refused.stderr and "--force" in refused.stderr
    assert archive.read_bytes() == first  # untouched

    run("export", "--agent", "example", "--source", str(home), "--output", str(output),
        "--zip", str(archive), "--force")
    assert archive.exists()

    with pytest.raises(FileExistsError):
        agent_backup.export(Profile.from_dict(EXAMPLE), home, output, archive)


def test_backup_refuses_output_inside_source(tmp_path: Path):
    home = tmp_path / "home"
    write_thread(home, "t1", [])
    bad = subprocess.run([sys.executable, str(ROOT / "agent_backup.py"), "backup", "--agent", "example",
                          "--source", str(home), "--output", str(home / "inside")],
                         capture_output=True, text=True, cwd=ROOT)
    assert bad.returncode == 2 and "must not be" in bad.stderr


def test_backup_records_sqlite_schemas_and_reports_broken_ones(tmp_path: Path):
    profile = Profile.from_dict(EXAMPLE)
    home, project = tmp_path / "home", tmp_path / "proj"
    write_thread(home, "t1", [{"kind": "turn", "speaker": "human", "body": [{"type": "say", "text": "hi"}]}])
    project.mkdir()
    connection = sqlite3.connect(home / "state.sqlite")
    connection.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT NOT NULL)")
    connection.commit()
    connection.close()
    (home / "broken.db").write_bytes(b"this is not a database")

    metadata = agent_backup.backup(profile, project, home, tmp_path / "out")
    schemas = json.loads((Path(metadata["path"]) / "extracted" / "sqlite-schema.json").read_text(encoding="utf-8"))
    columns = schemas["state.sqlite"]["tables"]["notes"]["columns"]
    assert [c["name"] for c in columns] == ["id", "body"]
    assert "CREATE TABLE notes" in schemas["state.sqlite"]["tables"]["notes"]["sql"]
    assert "error" in schemas["broken.db"]  # recorded, not fatal


@pytest.mark.skipif(os.name != "posix", reason="symlinks, FIFOs and chmod 000 are POSIX behaviour")
def test_backup_preserves_symlinks_and_reports_what_it_cannot_copy(tmp_path: Path):
    profile = Profile.from_dict(EXAMPLE)
    home, project = tmp_path / "home", tmp_path / "proj"
    write_thread(home, "t1", [{"kind": "turn", "speaker": "human", "body": [{"type": "say", "text": "hi"}]}])
    project.mkdir()
    (project / "real.txt").write_text("data", encoding="utf-8")
    (project / "link.txt").symlink_to("real.txt")
    (project / "dangling.txt").symlink_to("nowhere")
    os.mkfifo(project / "pipe")
    locked = project / "locked"
    locked.mkdir()
    (locked / "secret").write_text("x", encoding="utf-8")
    locked.chmod(0o000)
    readonly = project / "readonly"
    readonly.mkdir()
    (readonly / "kept.txt").write_text("keep me", encoding="utf-8")
    readonly.chmod(0o500)
    try:
        metadata = agent_backup.backup(profile, project, home, tmp_path / "out")
    finally:
        locked.chmod(0o700)
        readonly.chmod(0o700)
        for copied in (tmp_path / "out").rglob("*"):
            if copied.is_dir() and not copied.is_symlink():
                copied.chmod(0o700)

    copied = Path(metadata["path"]) / "project"
    assert (copied / "real.txt").read_text(encoding="utf-8") == "data"
    assert (copied / "link.txt").is_symlink() and os.readlink(copied / "link.txt") == "real.txt"
    assert (copied / "dangling.txt").is_symlink()  # preserved, not followed
    assert metadata["sha256"]["project/real.txt"]
    assert "project/link.txt" not in metadata["sha256"]  # a symlink has no content of its own
    skipped = "\n".join(metadata["skipped"])
    assert "pipe: not a regular file" in skipped
    assert "locked" in skipped and "Permission denied" in skipped
    # A read-only directory keeps its contents: its mode is applied afterwards.
    assert (copied / "readonly" / "kept.txt").read_text(encoding="utf-8") == "keep me"
    assert metadata["sha256"]["project/readonly/kept.txt"]
    assert metadata["chat_count"] == 1  # the backup still finished


@pytest.mark.skipif(os.name != "posix", reason="chmod 000 does not block reads on Windows")
def test_walk_reports_directories_it_cannot_read(tmp_path: Path):
    (tmp_path / "open").mkdir()
    (tmp_path / "open" / "file").write_text("x", encoding="utf-8")
    shut = tmp_path / "shut"
    shut.mkdir()
    shut.chmod(0o000)
    skipped: list[str] = []
    try:
        seen = {p.name for p in agent_backup.walk(tmp_path, skipped)}
    finally:
        shut.chmod(0o700)
    assert {"open", "file", "shut"} <= seen
    assert any("shut" in entry and "Permission denied" in entry for entry in skipped)


def test_backup_event_profile_counts_records_without_copying_content(tmp_path: Path):
    profile = Profile.from_dict({**EXAMPLE, "body_field": "body"})
    home, project = tmp_path / "home", tmp_path / "proj"
    project.mkdir()
    write_thread(home, "t1", [
        {"kind": "meta", "subject": "Quiet", "thread_id": "T-1"},
        {"kind": "turn", "speaker": "human", "body": {"type": "say", "text": "a secret"}},
        {"kind": "turn", "speaker": "robot", "body": {"type": "say", "text": "another"}},
    ])
    (home / "threads" / "damaged.jsonl").write_text("{not json\n", encoding="utf-8")

    metadata = agent_backup.backup(profile, project, home, tmp_path / "out")
    extracted = Path(metadata["path"]) / "extracted"
    report = json.loads((extracted / profile.event_profile_name).read_text(encoding="utf-8"))
    assert report["files"] == 2 and report["invalid_json"] == 1
    assert report["record_types"] == {"meta": 1, "turn": 2}
    assert report["body_keys"]["turn"] == {"type": 2, "text": 2}
    assert "secret" not in json.dumps(report)  # shapes only, never contents


def test_builtin_profiles_cover_their_own_documented_blocks():
    for profile in (CLAUDE, CODEX):
        assert profile.session_globs and profile.message_rules and profile.blocks
        assert profile.home_env and profile.home_default
