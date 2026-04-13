"""Tests for prism.parser — JSONL parsing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prism.parser import (
    AssistantRecord,
    ContentBlock,
    ParseResult,
    SystemRecord,
    UserRecord,
    discover_projects,
    parse_record,
    parse_session_file,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# parse_record unit tests
# ---------------------------------------------------------------------------

class TestParseRecord:
    def test_user_text_message(self):
        data = {
            "uuid": "u1",
            "parentUuid": None,
            "isSidechain": False,
            "sessionId": "sess1",
            "timestamp": "2026-04-10T10:00:00.000Z",
            "version": "2.1.98",
            "cwd": "/home/user/proj",
            "gitBranch": "main",
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "Hello, world"}]
            }
        }
        record = parse_record(data)
        assert isinstance(record, UserRecord)
        assert record.uuid == "u1"
        assert record.parent_uuid is None
        assert record.is_sidechain is False
        assert record.session_id == "sess1"
        assert record.type == "user"
        assert len(record.content) == 1
        assert record.content[0].type == "text"
        assert record.content[0].text == "Hello, world"

    def test_assistant_with_tool_use(self):
        data = {
            "uuid": "a1",
            "parentUuid": "u1",
            "isSidechain": False,
            "sessionId": "sess1",
            "timestamp": "2026-04-10T10:00:05.000Z",
            "version": "2.1.98",
            "cwd": "/home/user/proj",
            "gitBranch": "main",
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Let me run that."},
                    {
                        "type": "tool_use",
                        "id": "toolu_001",
                        "name": "Bash",
                        "input": {"command": "ls -la"}
                    }
                ]
            }
        }
        record = parse_record(data)
        assert isinstance(record, AssistantRecord)
        assert record.parent_uuid == "u1"
        assert len(record.content) == 2
        text_block = record.content[0]
        assert text_block.type == "text"
        assert text_block.text == "Let me run that."
        tool_block = record.content[1]
        assert tool_block.type == "tool_use"
        assert tool_block.tool_name == "Bash"
        assert tool_block.tool_id == "toolu_001"
        assert tool_block.tool_input == {"command": "ls -la"}

    def test_tool_result_in_user_record(self):
        data = {
            "uuid": "u2",
            "parentUuid": "a1",
            "isSidechain": False,
            "sessionId": "sess1",
            "timestamp": "2026-04-10T10:00:06.000Z",
            "version": "2.1.98",
            "cwd": "/home/user/proj",
            "gitBranch": "main",
            "type": "user",
            "message": {
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": "toolu_001",
                    "content": "total 32\n-rw-r--r-- 1 user user 4096 README.md"
                }]
            }
        }
        record = parse_record(data)
        assert isinstance(record, UserRecord)
        assert len(record.content) == 1
        result_block = record.content[0]
        assert result_block.type == "tool_result"
        assert result_block.tool_use_id == "toolu_001"
        assert "README.md" in result_block.tool_content

    def test_system_compact_boundary(self):
        data = {
            "uuid": "s1",
            "parentUuid": "u1",
            "isSidechain": False,
            "sessionId": "sess1",
            "timestamp": "2026-04-10T10:05:00.000Z",
            "version": "2.1.98",
            "cwd": "/home/user/proj",
            "gitBranch": "main",
            "type": "system",
            "subtype": "compact_boundary",
            "summary": "We implemented feature X."
        }
        record = parse_record(data)
        assert isinstance(record, SystemRecord)
        assert record.type == "system"
        assert record.subtype == "compact_boundary"
        assert record.summary == "We implemented feature X."

    def test_unknown_type_returns_none(self):
        data = {
            "uuid": "x1",
            "parentUuid": None,
            "isSidechain": False,
            "sessionId": "sess1",
            "timestamp": "2026-04-10T10:00:00.000Z",
            "version": "2.1.98",
            "cwd": "/home/user/proj",
            "gitBranch": "main",
            "type": "unknown_future_type",
        }
        record = parse_record(data)
        assert record is None

    def test_thinking_block_with_empty_thinking(self):
        """Thinking stripped since v2.1.72 — empty thinking field must not error."""
        data = {
            "uuid": "a2",
            "parentUuid": "u1",
            "isSidechain": False,
            "sessionId": "sess1",
            "timestamp": "2026-04-10T10:00:05.000Z",
            "version": "2.1.98",
            "cwd": "/home/user/proj",
            "gitBranch": None,
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": ""},
                    {"type": "text", "text": "My response."}
                ]
            }
        }
        record = parse_record(data)
        assert isinstance(record, AssistantRecord)
        assert record.content[0].type == "thinking"
        assert record.content[0].thinking == ""
        assert record.content[1].text == "My response."

    def test_sidechain_flag(self):
        data = {
            "uuid": "s2",
            "parentUuid": "u1",
            "isSidechain": True,
            "sessionId": "sess1",
            "timestamp": "2026-04-10T10:00:00.000Z",
            "version": "2.1.98",
            "cwd": "/home/user/proj",
            "gitBranch": "main",
            "type": "user",
            "message": {"role": "user", "content": []}
        }
        record = parse_record(data)
        assert isinstance(record, UserRecord)
        assert record.is_sidechain is True

    def test_missing_optional_fields_dont_crash(self):
        """Records with missing optional envelope fields should still parse."""
        data = {
            "uuid": "min1",
            "type": "user",
            "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]}
        }
        record = parse_record(data)
        assert isinstance(record, UserRecord)
        assert record.uuid == "min1"
        assert record.session_id == ""
        assert record.is_sidechain is False


# ---------------------------------------------------------------------------
# parse_session_file tests
# ---------------------------------------------------------------------------

class TestParseSessionFile:
    def test_parse_sample_session(self):
        path = FIXTURES / "sample_session.jsonl"
        result = parse_session_file(path)
        assert isinstance(result, ParseResult)
        assert result.skipped_lines == 0
        assert result.truncated is False
        assert len(result.records) == 20

    def test_sample_has_correct_record_types(self):
        path = FIXTURES / "sample_session.jsonl"
        result = parse_session_file(path)
        types = [r.type for r in result.records]
        assert "user" in types
        assert "assistant" in types

    def test_parse_compaction_session(self):
        path = FIXTURES / "session_with_compaction.jsonl"
        result = parse_session_file(path)
        # Should have a compact_boundary system record
        system_records = [r for r in result.records if isinstance(r, SystemRecord)]
        assert len(system_records) >= 1
        compact = [r for r in system_records if r.subtype == "compact_boundary"]
        assert len(compact) == 1
        assert "JWT" in compact[0].summary or "implemented" in compact[0].summary.lower()

    def test_parse_retry_session(self):
        path = FIXTURES / "session_with_retries.jsonl"
        result = parse_session_file(path)
        assert len(result.records) > 0
        # Check that migration file edit exists
        edit_calls = [
            b
            for r in result.records
            if isinstance(r, AssistantRecord)
            for b in r.content
            if b.type == "tool_use" and b.tool_name in ("Edit", "Write")
            and b.tool_input
            and "migration" in (b.tool_input.get("file_path", "") or "").lower()
        ]
        assert len(edit_calls) >= 1

    def test_malformed_lines_skipped(self, tmp_path):
        """Malformed JSON lines are skipped, not errors."""
        f = tmp_path / "bad.jsonl"
        f.write_text(
            '{"uuid":"u1","type":"user","message":{"role":"user","content":[{"type":"text","text":"ok"}]}}\n'
            'THIS IS NOT JSON\n'
            '{"uuid":"u2","type":"user","message":{"role":"user","content":[{"type":"text","text":"also ok"}]}}\n',
            encoding="utf-8"
        )
        result = parse_session_file(f)
        assert result.skipped_lines == 1
        assert len(result.records) == 2

    def test_truncated_file_detected(self, tmp_path):
        """A file where the last line is not valid JSON is marked truncated."""
        f = tmp_path / "trunc.jsonl"
        f.write_text(
            '{"uuid":"u1","type":"user","message":{"role":"user","content":[]}}\n'
            '{"uuid":"u2","type":"user",',  # truncated
            encoding="utf-8"
        )
        result = parse_session_file(f)
        assert result.truncated is True

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.jsonl"
        f.write_text("", encoding="utf-8")
        result = parse_session_file(f)
        assert result.records == []
        assert result.skipped_lines == 0

    def test_nonexistent_file(self, tmp_path):
        f = tmp_path / "nonexistent.jsonl"
        result = parse_session_file(f)
        assert result.records == []

    def test_blank_lines_ignored(self, tmp_path):
        f = tmp_path / "blanks.jsonl"
        f.write_text(
            '\n'
            '{"uuid":"u1","type":"user","message":{"role":"user","content":[]}}\n'
            '\n',
            encoding="utf-8"
        )
        result = parse_session_file(f)
        assert len(result.records) == 1
        assert result.skipped_lines == 0


# ---------------------------------------------------------------------------
# discover_projects tests
# ---------------------------------------------------------------------------

class TestDiscoverProjects:
    def test_missing_directory_returns_empty(self, tmp_path):
        missing = tmp_path / "no_such_dir"
        result = discover_projects(missing)
        assert result == []

    def test_discovers_project_dirs(self, tmp_path):
        proj_a = tmp_path / "-home-user-proj_a"
        proj_a.mkdir()
        (proj_a / "session1.jsonl").write_text(
            '{"uuid":"u1","type":"user","message":{"role":"user","content":[]}}\n',
            encoding="utf-8"
        )
        proj_b = tmp_path / "-home-user-proj_b"
        proj_b.mkdir()
        (proj_b / "session2.jsonl").write_text(
            '{"uuid":"u2","type":"user","message":{"role":"user","content":[]}}\n',
            encoding="utf-8"
        )
        projects = discover_projects(tmp_path)
        assert len(projects) == 2
        names = {p.encoded_name for p in projects}
        assert "-home-user-proj_a" in names
        assert "-home-user-proj_b" in names

    def test_empty_project_dir_included(self, tmp_path):
        proj = tmp_path / "-home-user-empty"
        proj.mkdir()
        projects = discover_projects(tmp_path)
        assert len(projects) == 1
        assert projects[0].session_files == []

    def test_non_jsonl_files_ignored(self, tmp_path):
        proj = tmp_path / "-home-user-proj"
        proj.mkdir()
        (proj / "notes.txt").write_text("not a session", encoding="utf-8")
        (proj / "session.jsonl").write_text(
            '{"uuid":"u1","type":"user","message":{"role":"user","content":[]}}\n',
            encoding="utf-8"
        )
        projects = discover_projects(tmp_path)
        assert len(projects[0].session_files) == 1
        assert projects[0].session_files[0].suffix == ".jsonl"
