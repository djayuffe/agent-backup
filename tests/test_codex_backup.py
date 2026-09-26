import json
import subprocess
import sys
import zipfile
from pathlib import Path

from codex_backup import read_session, render, safe_name, session_id, sessions, text_content

ROOT = Path(__file__).resolve().parents[1]


def write_rollout(home: Path, day: str, stamp: str, sid: str, rows: list[dict]) -> Path:
    directory = home / "sessions" / day
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"rollout-{stamp}-{sid}.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return path


def message(role: str, text: str, kind: str = "input_text") -> dict:
    return {"type": "response_item", "timestamp": "2026-01-01T00:00:00Z",
            "payload": {"type": "message", "role": role, "content": [{"type": kind, "text": text}]}}


def test_reads_message_content(tmp_path: Path):
    source = tmp_path / "rollout.jsonl"
    rows = [
        {"type": "session_meta", "payload": {"id": "abc", "thread_name": "Demo"}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Hello"}]}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Hi"}]}},
    ]
    source.write_text("\n".join(json.dumps(row) for row in rows))
    meta, messages = read_session(source)
    assert meta["id"] == "abc"
    assert [message[2] for message in messages] == ["Hello", "Hi"]
    assert "# Demo" in render(source, meta, messages)


def test_handles_object_text_and_malformed_payload(tmp_path: Path):
    source = tmp_path / "rollout.jsonl"
    rows = [
        {"type": "response_item", "payload": None},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": {"text": "Hello"}}},
    ]
    source.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    _, messages = read_session(source)
    assert messages[0][2] == "Hello"
    assert text_content({"text": "Nested"}) == "Nested"


def test_image_blocks_are_marked():
    assert text_content([{"type": "input_text", "text": "look"}, {"type": "input_image", "image_url": "..."}]) == "look\n[image]"


def test_session_id_prefers_file_name_over_resumed_meta(tmp_path: Path):
    uuid = "019d69a2-7624-7232-b7c8-49c8a57249c0"
    other = "019d6ef5-f2d5-7d10-a715-486d1c1a3d18"
    source = write_rollout(tmp_path, "2026/04/08", "2026-04-08T23-18-25", other,
                           [{"type": "session_meta", "payload": {"id": uuid, "thread_name": "Resumed"}}])
    meta, _ = read_session(source)
    # A resumed rollout carries the id it continues; the file name wins.
    assert session_id(source, meta) == other


def test_session_id_falls_back_to_meta_without_uuid_name(tmp_path: Path):
    source = tmp_path / "rollout.jsonl"
    source.write_text(json.dumps({"type": "session_meta", "payload": {"id": "abc"}}), encoding="utf-8")
    meta, _ = read_session(source)
    assert session_id(source, meta) == "abc"


def test_sessions_discovers_active_and_archived(tmp_path: Path):
    write_rollout(tmp_path, "2026/01/01", "2026-01-01T00-00-00", "019d69a2-7624-7232-b7c8-49c8a57249c0", [])
    archived = tmp_path / "archived_sessions"
    archived.mkdir()
    (archived / "old.jsonl").write_text("", encoding="utf-8")
    assert len(list(sessions(tmp_path))) == 2


def test_safe_name_sanitises_and_truncates():
    assert safe_name("a/b:c") == "a_b_c"
    assert safe_name("") == "untitled"
    assert len(safe_name("x" * 200)) == 100


def run(home: Path, output: Path, *args: str) -> str:
    result = subprocess.run(
        [sys.executable, str(ROOT / "codex_backup.py"), *args, "--source", str(home), "--output", str(output)],
        capture_output=True, text=True, cwd=ROOT, check=True,
    )
    return result.stdout


def test_sync_keeps_both_rollouts_of_one_resumed_session(tmp_path: Path):
    home, output = tmp_path / "home", tmp_path / "out"
    first = "019d69a2-7624-7232-b7c8-49c8a57249c0"
    second = "019d6ef5-f2d5-7d10-a715-486d1c1a3d18"
    meta = {"type": "session_meta", "payload": {"id": first, "thread_name": "Shared"}}
    write_rollout(home, "2026/04/07", "2026-04-07T22-29-08", first, [meta, message("user", "one")])
    write_rollout(home, "2026/04/08", "2026-04-08T23-18-25", second, [meta, message("user", "two")])
    run(home, output, "sync")
    assert (output / f"Shared--{first}.md").exists()
    assert (output / f"Shared--{second}.md").exists()


def test_sync_replaces_retitled_file_and_prunes(tmp_path: Path):
    home, output = tmp_path / "home", tmp_path / "out"
    sid = "019d69a2-7624-7232-b7c8-49c8a57249c0"
    rollout = write_rollout(home, "2026/04/07", "2026-04-07T22-29-08", sid,
                            [{"type": "session_meta", "payload": {"id": sid, "thread_name": "First"}}, message("user", "hi")])
    run(home, output, "sync")
    assert (output / f"First--{sid}.md").exists()

    write_rollout(home, "2026/04/07", "2026-04-07T22-29-08", sid,
                  [{"type": "session_meta", "payload": {"id": sid, "thread_name": "Second"}}, message("user", "hi")])
    run(home, output, "sync")
    assert (output / f"Second--{sid}.md").exists()
    assert not (output / f"First--{sid}.md").exists()

    rollout.unlink()
    run(home, output, "sync")
    assert (output / f"Second--{sid}.md").exists()  # kept without --prune
    run(home, output, "sync", "--prune")
    assert not (output / f"Second--{sid}.md").exists()


def test_export_bundles_chats_raw_and_extras(tmp_path: Path):
    home, output = tmp_path / "home", tmp_path / "out"
    sid = "019d69a2-7624-7232-b7c8-49c8a57249c0"
    write_rollout(home, "2026/04/07", "2026-04-07T22-29-08", sid, [message("user", "hi")])
    (home / "config.toml").write_text("", encoding="utf-8")
    (home / "attachments").mkdir()
    (home / "attachments" / "a.png").write_text("x", encoding="utf-8")
    run(home, output, "export")

    with zipfile.ZipFile(output.with_suffix(".zip")) as zf:
        names = set(zf.namelist())
        metadata = json.loads(zf.read("chats/export-metadata.json"))
    assert f"raw/sessions/2026/04/07/rollout-2026-04-07T22-29-08-{sid}.jsonl" in names
    assert "codex/config.toml" in names
    assert "attachments/a.png" in names
    assert metadata["chat_count"] == 1 and metadata["format"] == "codex-chat-export-v1"
