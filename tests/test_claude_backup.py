# agent-backup — mirror and back up local coding-agent session state.
# Copyright (C) 2026 Ulf Bertilsson
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. This program is distributed WITHOUT ANY WARRANTY; see the LICENSE
# file, or <https://www.gnu.org/licenses/>, for the full terms.

import json
import subprocess
import sys
import zipfile
from pathlib import Path

from claude_backup import read_session, render, safe_name, session_id, sessions, text_content

ROOT = Path(__file__).resolve().parents[1]


def write_transcript(home: Path, project: str, sid: str, rows: list[dict]) -> Path:
    directory = home / "projects" / project
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{sid}.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return path


def message(role: str, content, **extra) -> dict:
    return {"type": role, "message": {"role": role, "content": content}, "timestamp": "2026-01-01T00:00:00Z", **extra}


def test_reads_message_content(tmp_path: Path):
    source = write_transcript(tmp_path, "proj", "abc", [
        {"type": "ai-title", "aiTitle": "Demo", "sessionId": "abc"},
        message("user", "Hello", cwd="/work"),
        message("assistant", [{"type": "text", "text": "Hi"}]),
    ])
    meta, messages = read_session(source)
    assert meta["id"] == "abc"
    assert meta["cwd"] == "/work"
    assert [m[2] for m in messages] == ["Hello", "Hi"]
    output = render(source, meta, messages)
    assert "# Demo" in output and "- Project: /work" in output


def test_custom_title_outranks_ai_title(tmp_path: Path):
    source = write_transcript(tmp_path, "proj", "abc", [
        {"type": "custom-title", "customTitle": "Mine", "sessionId": "abc"},
        {"type": "ai-title", "aiTitle": "Generated", "sessionId": "abc"},
    ])
    meta, _ = read_session(source)
    assert meta["thread_name"] == "Mine"


def test_session_id_ignores_forked_session_stamps(tmp_path: Path):
    source = write_transcript(tmp_path, "proj", "abc", [message("user", "Hi", sessionId="older-id")])
    meta, _ = read_session(source)
    assert session_id(source, meta) == "abc"


def test_content_block_kinds(tmp_path: Path):
    source = write_transcript(tmp_path, "proj", "abc", [
        message("assistant", [
            {"type": "thinking", "thinking": "pondering", "signature": "x"},
            {"type": "thinking", "thinking": "", "signature": "x"},
            {"type": "text", "text": "answer"},
            {"type": "tool_use", "name": "Read", "input": {}},
        ]),
        message("user", [{"type": "tool_result", "content": [
            {"type": "text", "text": "file body"},
            {"type": "image", "source": {}},
            {"type": "tool_reference", "name": "Edit"},
        ]}]),
    ])
    _, messages = read_session(source)
    assert "<thinking>\npondering\n</thinking>" in messages[0][2]
    assert "[tool_use: Read]" in messages[0][2]
    assert messages[1][2] == "[tool_result]\nfile body\n[image]\n[tool_reference: Edit]"


def test_skips_sidechain_and_contentless_records(tmp_path: Path):
    source = write_transcript(tmp_path, "proj", "abc", [
        message("assistant", [{"type": "text", "text": "sub"}], isSidechain=True),
        message("assistant", [{"type": "thinking", "thinking": "", "signature": "x"}]),
        {"type": "queue-operation", "operation": "enqueue", "content": "ignored"},
        message("assistant", [{"type": "text", "text": "kept"}]),
    ])
    _, messages = read_session(source)
    assert [m[2] for m in messages] == ["kept"]


def test_handles_malformed_lines_and_object_text(tmp_path: Path):
    source = write_transcript(tmp_path, "proj", "abc", [message("assistant", {"text": "Hello"})])
    source.write_text("not json\n[1, 2]\n" + source.read_text(encoding="utf-8"), encoding="utf-8")
    _, messages = read_session(source)
    assert messages[0][2] == "Hello"
    assert text_content({"text": "Nested"}) == "Nested"


def test_safe_name_sanitises_and_truncates():
    assert safe_name("a/b:c") == "a_b_c"
    assert safe_name("") == "untitled"
    assert len(safe_name("x" * 200)) == 100


def test_sessions_discovers_projects_and_deduplicates(tmp_path: Path):
    write_transcript(tmp_path, "one", "abc", [])
    write_transcript(tmp_path, "two", "def", [])
    (tmp_path / "projects" / "two" / "ignored.txt").write_text("x", encoding="utf-8")
    assert sorted(p.stem for p in sessions(tmp_path)) == ["abc", "def"]


def run(home: Path, output: Path, *args: str) -> str:
    result = subprocess.run(
        [sys.executable, str(ROOT / "claude_backup.py"), *args, "--source", str(home), "--output", str(output)],
        capture_output=True, text=True, cwd=ROOT, check=True,
    )
    return result.stdout


def test_sync_replaces_retitled_file_and_prunes(tmp_path: Path):
    home, output = tmp_path / "home", tmp_path / "out"
    write_transcript(home, "proj", "abc", [{"type": "ai-title", "aiTitle": "First", "sessionId": "abc"}, message("user", "Hi")])
    run(home, output, "sync")
    assert (output / "First--abc.md").exists()

    write_transcript(home, "proj", "abc", [{"type": "custom-title", "customTitle": "Second", "sessionId": "abc"}, message("user", "Hi")])
    run(home, output, "sync")
    assert (output / "Second--abc.md").exists()
    assert not (output / "First--abc.md").exists()
    manifest = json.loads((output / ".manifest.json").read_text(encoding="utf-8"))
    assert list(manifest) == ["Second--abc.md"]

    (home / "projects" / "proj" / "abc.jsonl").unlink()
    run(home, output, "sync")
    assert (output / "Second--abc.md").exists()  # kept without --prune
    run(home, output, "sync", "--prune")
    assert not (output / "Second--abc.md").exists()


def test_export_bundles_chats_raw_and_extras(tmp_path: Path):
    home, output = tmp_path / "home", tmp_path / "out"
    write_transcript(home, "proj", "abc", [message("user", "Hi")])
    (home / "settings.json").write_text("{}", encoding="utf-8")
    (home / "plans").mkdir()
    (home / "plans" / "plan.md").write_text("plan", encoding="utf-8")
    run(home, output, "export")

    with zipfile.ZipFile(output.with_suffix(".zip")) as zf:
        names = set(zf.namelist())
        metadata = json.loads(zf.read("chats/export-metadata.json"))
    assert "raw/projects/proj/abc.jsonl" in names
    assert "claude/settings.json" in names
    assert "plans/plan.md" in names
    assert metadata["chat_count"] == 1 and metadata["format"] == "claude-chat-export-v1"


def test_list_reports_titles_and_counts(tmp_path: Path):
    home = tmp_path / "home"
    write_transcript(home, "proj", "abc", [{"type": "ai-title", "aiTitle": "Demo", "sessionId": "abc"}, message("user", "Hi")])
    stdout = run(home, tmp_path / "out", "list")
    assert "abc\tDemo\t1 messages" in stdout
