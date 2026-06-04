"""Tests for prism.parser — JSONL parsing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prism.parser import (
    AssistantRecord,
    ContentBlock,
    ParseResult,
    ProjectInfo,
    SystemRecord,
    UserRecord,
    discover_projects,
    load_all_sessions,
    parse_record,
    parse_session_file,
    project_path_to_encoded_name,
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

    def test_classify_continuation_as_system_record(self):
        """User record with continuation text is promoted to SystemRecord."""
        data = {
            "uuid": "u-cont",
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
                "content": [{"type": "text", "text": "This session is being continued from a previous conversation."}]
            }
        }
        record = parse_record(data)
        assert isinstance(record, SystemRecord)
        assert record.type == "user"
        assert record.subtype == "continuation"
        assert record.summary.startswith("This session is being continued")

    def test_classify_interrupted_as_system_record(self):
        """User record with interrupted text is promoted to SystemRecord."""
        data = {
            "uuid": "u-int",
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
                "content": [{"type": "text", "text": "[Request interrupted by user]"}]
            }
        }
        record = parse_record(data)
        assert isinstance(record, SystemRecord)
        assert record.type == "user"
        assert record.subtype == "interrupted"

    def test_regular_user_message_unchanged(self):
        """Normal user text must NOT be promoted to SystemRecord."""
        data = {
            "uuid": "u-norm",
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
                "content": [{"type": "text", "text": "Please fix the login bug"}]
            }
        }
        record = parse_record(data)
        assert isinstance(record, UserRecord)
        assert record.content[0].text == "Please fix the login bug"

    def test_bom_prefix_handled(self):
        """BOM prefix before continuation text must still classify correctly."""
        data = {
            "uuid": "u-bom",
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
                "content": [{"type": "text", "text": "﻿This session is being continued from a previous conversation."}]
            }
        }
        record = parse_record(data)
        assert isinstance(record, SystemRecord)
        assert record.subtype == "continuation"

    def test_classify_resume_as_system_record(self):
        """User record with resume caveat is promoted to SystemRecord."""
        data = {
            "uuid": "u-resume",
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
                "content": [{"type": "text", "text": "<local-command-caveat>Session resumed.</local-command-caveat>"}]
            }
        }
        record = parse_record(data)
        assert isinstance(record, SystemRecord)
        assert record.subtype == "resume"

    def test_classify_task_notification_as_system_record(self):
        """User record with task notification is promoted to SystemRecord."""
        data = {
            "uuid": "u-task",
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
                "content": [{"type": "text", "text": "<task-notification>Background task completed.</task-notification>"}]
            }
        }
        record = parse_record(data)
        assert isinstance(record, SystemRecord)
        assert record.subtype == "task_notification"

    def test_classify_stop_hook_as_system_record(self):
        """User record with stop hook feedback is promoted to SystemRecord."""
        data = {
            "uuid": "u-stop",
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
                "content": [{"type": "text", "text": "Stop hook feedback: lint failed with 3 errors"}]
            }
        }
        record = parse_record(data)
        assert isinstance(record, SystemRecord)
        assert record.subtype == "stop_hook"

    def test_user_string_content_becomes_text_block(self):
        """message.content as a bare string (current CC format) parses as one text block."""
        data = {
            "uuid": "u-str",
            "parentUuid": None,
            "isSidechain": False,
            "sessionId": "sess1",
            "timestamp": "2026-06-01T10:00:00.000Z",
            "version": "2.1.150",
            "cwd": "/home/user/proj",
            "gitBranch": "main",
            "type": "user",
            "message": {"role": "user", "content": "fix the login bug please"}
        }
        record = parse_record(data)
        assert isinstance(record, UserRecord)
        assert len(record.content) == 1
        assert record.content[0].type == "text"
        assert record.content[0].text == "fix the login bug please"

    def test_assistant_string_content_becomes_text_block(self):
        """Assistant string content parses as one text block."""
        data = {
            "uuid": "a-str",
            "parentUuid": "u-str",
            "isSidechain": False,
            "sessionId": "sess1",
            "timestamp": "2026-06-01T10:00:01.000Z",
            "version": "2.1.150",
            "cwd": "/home/user/proj",
            "gitBranch": "main",
            "type": "assistant",
            "message": {"role": "assistant", "content": "On it."}
        }
        record = parse_record(data)
        assert isinstance(record, AssistantRecord)
        assert len(record.content) == 1
        assert record.content[0].type == "text"
        assert record.content[0].text == "On it."

    def test_classify_continuation_from_string_content(self):
        """Continuation messages arrive as string content on current CC versions
        and must still be classified as SystemRecord subtype=continuation."""
        data = {
            "uuid": "u-cont",
            "parentUuid": None,
            "isSidechain": False,
            "sessionId": "sess1",
            "timestamp": "2026-06-01T10:00:00.000Z",
            "version": "2.1.150",
            "cwd": "/home/user/proj",
            "gitBranch": "main",
            "type": "user",
            "message": {
                "role": "user",
                "content": "This session is being continued from a previous conversation that ran out of context."
            }
        }
        record = parse_record(data)
        assert isinstance(record, SystemRecord)
        assert record.subtype == "continuation"

    def test_classify_resume_from_string_content(self):
        """Caveat messages arrive as string content and must classify as resume."""
        data = {
            "uuid": "u-resume-str",
            "parentUuid": None,
            "isSidechain": False,
            "sessionId": "sess1",
            "timestamp": "2026-06-01T10:00:00.000Z",
            "version": "2.1.150",
            "cwd": "/home/user/proj",
            "gitBranch": "main",
            "type": "user",
            "message": {
                "role": "user",
                "content": "<local-command-caveat>Caveat: The messages below were generated by the user while running local commands.</local-command-caveat>"
            }
        }
        record = parse_record(data)
        assert isinstance(record, SystemRecord)
        assert record.subtype == "resume"

    def test_empty_string_content_yields_no_blocks(self):
        """Empty string content must not create an empty text block."""
        data = {
            "uuid": "u-empty",
            "parentUuid": None,
            "isSidechain": False,
            "sessionId": "sess1",
            "timestamp": "2026-06-01T10:00:00.000Z",
            "version": "2.1.150",
            "cwd": "/home/user/proj",
            "gitBranch": "main",
            "type": "user",
            "message": {"role": "user", "content": ""}
        }
        record = parse_record(data)
        assert isinstance(record, UserRecord)
        assert record.content == []


class TestActualTokens:
    """parse_record must capture message.usage.output_tokens on assistant records."""

    def _assistant(self, usage) -> dict:
        message = {
            "role": "assistant",
            "content": [{"type": "text", "text": "done"}],
        }
        if usage is not None:
            message["usage"] = usage
        return {
            "uuid": "a-usage",
            "parentUuid": "u1",
            "isSidechain": False,
            "sessionId": "sess1",
            "timestamp": "2026-06-01T10:00:00.000Z",
            "version": "2.1.150",
            "cwd": "/home/user/proj",
            "gitBranch": "main",
            "type": "assistant",
            "message": message,
        }

    def test_output_tokens_captured(self):
        record = parse_record(self._assistant({"input_tokens": 12, "output_tokens": 321}))
        assert isinstance(record, AssistantRecord)
        assert record.actual_tokens == 321

    def test_missing_usage_gives_none(self):
        record = parse_record(self._assistant(None))
        assert isinstance(record, AssistantRecord)
        assert record.actual_tokens is None

    def test_malformed_usage_gives_none(self):
        record = parse_record(self._assistant("not-a-dict"))
        assert record.actual_tokens is None
        record = parse_record(self._assistant({"output_tokens": "many"}))
        assert record.actual_tokens is None


class TestToolResultIsError:
    """parse_record must capture the is_error flag on tool_result blocks."""

    def _user_with_result(self, extra: dict) -> dict:
        block = {"type": "tool_result", "tool_use_id": "t1", "content": "output text"}
        block.update(extra)
        return {
            "uuid": "u-res",
            "parentUuid": "a1",
            "isSidechain": False,
            "sessionId": "sess1",
            "timestamp": "2026-06-01T10:00:00.000Z",
            "version": "2.1.150",
            "cwd": "/home/user/proj",
            "gitBranch": "main",
            "type": "user",
            "message": {"role": "user", "content": [block]},
        }

    def test_is_error_true_captured(self):
        record = parse_record(self._user_with_result({"is_error": True}))
        assert record.content[0].is_error is True

    def test_is_error_false_captured(self):
        record = parse_record(self._user_with_result({"is_error": False}))
        assert record.content[0].is_error is False

    def test_is_error_absent_gives_none(self):
        record = parse_record(self._user_with_result({}))
        assert record.content[0].is_error is None


# ---------------------------------------------------------------------------
# Subagent transcript attachment
# ---------------------------------------------------------------------------

def _jsonl_line(uuid: str, rtype: str, sidechain: bool, text: str) -> str:
    return json.dumps({
        "uuid": uuid,
        "parentUuid": None,
        "isSidechain": sidechain,
        "sessionId": "parent-sess",
        "timestamp": "2026-06-01T10:00:00.000Z",
        "version": "2.1.150",
        "cwd": "/home/user/proj",
        "gitBranch": "main",
        "type": rtype,
        "message": {"role": rtype, "content": [{"type": "text", "text": text}]},
    })


class TestSubagentAttachment:
    """Subagent transcripts at <project>/<session-uuid>/subagents/agent-*.jsonl
    must attach to the parent session — never count as separate sessions."""

    def _build_project(self, tmp_path: Path) -> Path:
        proj = tmp_path / "D--myproj"
        proj.mkdir()
        main = proj / "abc-123.jsonl"
        main.write_text(
            _jsonl_line("u1", "user", False, "do the thing") + "\n"
            + _jsonl_line("a1", "assistant", False, "doing it") + "\n",
            encoding="utf-8",
        )
        agents = proj / "abc-123" / "subagents"
        agents.mkdir(parents=True)
        (agents / "agent-xyz.jsonl").write_text(
            _jsonl_line("s1", "user", True, "subagent prompt") + "\n"
            + _jsonl_line("s2", "assistant", True, "subagent reply") + "\n",
            encoding="utf-8",
        )
        return proj

    def test_session_count_unchanged_by_subagent_files(self, tmp_path):
        self._build_project(tmp_path)
        projects = discover_projects(tmp_path)
        assert len(projects) == 1
        # Only the top-level session file — agent files are not sessions.
        assert len(projects[0].session_files) == 1
        sessions = load_all_sessions(projects[0])
        assert len(sessions) == 1

    def test_subagent_records_attached_to_parent_session(self, tmp_path):
        self._build_project(tmp_path)
        projects = discover_projects(tmp_path)
        sessions = load_all_sessions(projects[0])
        records = sessions[0].records
        sidechain = [r for r in records if r.is_sidechain]
        assert len(sidechain) == 2, "subagent records must merge into parent session"
        assert len(records) == 4

    def test_project_without_subagents_unaffected(self, tmp_path):
        proj = tmp_path / "D--plain"
        proj.mkdir()
        (proj / "sess.jsonl").write_text(
            _jsonl_line("u1", "user", False, "hello") + "\n", encoding="utf-8"
        )
        projects = discover_projects(tmp_path)
        sessions = load_all_sessions(projects[0])
        assert len(sessions) == 1
        assert len(sessions[0].records) == 1

    def test_truncated_subagent_marks_session_truncated(self, tmp_path):
        """A subagent transcript cut mid-write is data loss for the session."""
        proj = self._build_project(tmp_path)
        agents = proj / "abc-123" / "subagents"
        (agents / "agent-cut.jsonl").write_text(
            _jsonl_line("s9", "user", True, "started") + "\n"
            + '{"uuid":"s10","type":"assist',  # truncated mid-record
            encoding="utf-8",
        )
        projects = discover_projects(tmp_path)
        sessions = load_all_sessions(projects[0])
        assert sessions[0].truncated is True


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

    def test_last_active_returns_float(self, tmp_path):
        proj = tmp_path / "-home-user-proj"
        proj.mkdir()
        (proj / "session.jsonl").write_text(
            '{"uuid":"u1","type":"user","message":{"role":"user","content":[]}}\n',
            encoding="utf-8"
        )
        projects = discover_projects(tmp_path)
        assert isinstance(projects[0].last_active, float)

    def test_last_active_none_when_no_sessions(self, tmp_path):
        proj = tmp_path / "-home-user-empty"
        proj.mkdir()
        projects = discover_projects(tmp_path)
        assert projects[0].last_active is None


# ---------------------------------------------------------------------------
# project_path_to_encoded_name tests
# ---------------------------------------------------------------------------

class TestProjectPathToEncodedName:
    """Verify encoding round-trips for Windows paths, Unix paths, and display names."""

    def test_unix_absolute_path(self):
        assert project_path_to_encoded_name("/home/user/myproject") == "-home-user-myproject"

    def test_unix_nested_path(self):
        assert project_path_to_encoded_name("/home/alice/work/proj") == "-home-alice-work-proj"

    def test_windows_backslash_path(self):
        # Native Windows path with backslash separators
        assert project_path_to_encoded_name("D:\\jarvis\\space") == "D--jarvis-space"

    def test_windows_forward_slash_path(self):
        # Windows path written with forward slashes
        assert project_path_to_encoded_name("D:/jarvis/space") == "D--jarvis-space"

    def test_windows_display_name(self):
        # Display name as shown in the projects table (D:\ → D-- after decode)
        assert project_path_to_encoded_name("D//jarvis/space") == "D--jarvis-space"

    def test_already_encoded_name_unchanged(self):
        # An already-encoded name has no path chars — passes through as-is
        assert project_path_to_encoded_name("D--jarvis-space") == "D--jarvis-space"

    def test_display_name_roundtrip(self):
        """display_name -> encode -> same encoded dir name."""
        encoded = "D--jarvis-space"
        info = ProjectInfo(encoded_name=encoded, project_dir=Path("."), session_files=[])
        # display_name replaces "-" with "/" giving "D//jarvis/space"
        display = info.display_name
        # re-encoding the display should yield the original encoded name
        assert project_path_to_encoded_name(display) == encoded
