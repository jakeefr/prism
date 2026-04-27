"""Tests for prism.agentsview — AgentsviewDataSource."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from prism.agentsview import AgentsviewDataSource
from prism.datasource import SessionDataSource
from prism.parser import (
    AssistantRecord,
    ContentBlock,
    ProjectInfo,
    SystemRecord,
    UserRecord,
    project_path_to_encoded_name,
)
from tests.conftest import build_test_db as _build_test_db


def _insert_session(
    conn: sqlite3.Connection,
    session_id: str,
    project: str,
    *,
    cwd: str = "/home/user/proj",
    git_branch: str = "main",
    source_version: str = "2.1.98",
    deleted_at: str | None = None,
) -> None:
    """Insert a session row with sensible defaults."""
    conn.execute(
        "INSERT INTO sessions (id, project, cwd, git_branch, source_version, deleted_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (session_id, project, cwd, git_branch, source_version, deleted_at),
    )


def _insert_message(
    conn: sqlite3.Connection,
    session_id: str,
    role: str,
    content: str = "",
    timestamp: str = "2026-04-20T10:00:00Z",
    source_uuid: str = "",
    **kwargs: object,
) -> int:
    """Insert a message row with sensible defaults. Returns the message id."""
    defaults = {
        "source_parent_uuid": "",
        "is_sidechain": 0,
        "is_compact_boundary": 0,
        "is_system": 0,
        "has_output_tokens": 0,
        "output_tokens": 0,
    }
    defaults.update(kwargs)
    ordinal = defaults.pop("ordinal", None)
    if ordinal is None:
        ordinal = conn.execute(
            "SELECT COALESCE(MAX(ordinal), 0) + 1 FROM messages WHERE session_id = ?",
            (session_id,),
        ).fetchone()[0]
    conn.execute(
        "INSERT INTO messages"
        " (session_id, ordinal, role, content, timestamp, source_uuid,"
        "  source_parent_uuid, is_sidechain, is_compact_boundary, is_system,"
        "  has_output_tokens, output_tokens)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            session_id, ordinal, role, content, timestamp,
            source_uuid,
            defaults["source_parent_uuid"], defaults["is_sidechain"],
            defaults["is_compact_boundary"], defaults["is_system"],
            defaults["has_output_tokens"], defaults["output_tokens"],
        ),
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


class TestAgentsviewDataSourceProtocol:
    def test_is_session_data_source(self, tmp_path: Path):
        db = tmp_path / "test.db"
        _build_test_db(db)
        assert isinstance(AgentsviewDataSource(db), SessionDataSource)


class TestDiscoverProjects:
    def test_empty_db_returns_empty(self, tmp_path: Path):
        db = tmp_path / "test.db"
        _build_test_db(db)
        ds = AgentsviewDataSource(db)
        assert ds.discover_projects() == []

    def test_one_project(self, tmp_path: Path):
        db = tmp_path / "test.db"
        _build_test_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, "s1", "/home/user/proj")
        conn.commit()
        conn.close()

        ds = AgentsviewDataSource(db)
        projects = ds.discover_projects()
        assert len(projects) == 1
        expected_encoded = project_path_to_encoded_name("/home/user/proj")
        assert projects[0].encoded_name == expected_encoded
        assert projects[0].session_files == []

    def test_soft_deleted_excluded(self, tmp_path: Path):
        db = tmp_path / "test.db"
        _build_test_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, "s1", "/home/user/proj",
                        deleted_at="2026-04-20T10:00:00Z")
        conn.commit()
        conn.close()

        ds = AgentsviewDataSource(db)
        assert ds.discover_projects() == []

    def test_multiple_sessions_same_project_deduped(self, tmp_path: Path):
        db = tmp_path / "test.db"
        _build_test_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, "s1", "/home/user/proj")
        _insert_session(conn, "s2", "/home/user/proj")
        conn.commit()
        conn.close()

        ds = AgentsviewDataSource(db)
        projects = ds.discover_projects()
        assert len(projects) == 1

    def test_multiple_distinct_projects(self, tmp_path: Path):
        db = tmp_path / "test.db"
        _build_test_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, "s1", "/home/user/alpha")
        _insert_session(conn, "s2", "/home/user/beta")
        conn.commit()
        conn.close()

        ds = AgentsviewDataSource(db)
        projects = ds.discover_projects()
        assert len(projects) == 2
        names = {p.encoded_name for p in projects}
        assert project_path_to_encoded_name("/home/user/alpha") in names
        assert project_path_to_encoded_name("/home/user/beta") in names

    def test_empty_project_excluded(self, tmp_path: Path):
        """Sessions with empty-string project are excluded."""
        db = tmp_path / "test.db"
        _build_test_db(db)
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO sessions (id, project) VALUES (?, ?)",
            ("s1", ""),
        )
        conn.commit()
        conn.close()

        ds = AgentsviewDataSource(db)
        assert ds.discover_projects() == []


class TestConnectionLifecycle:
    def test_close(self, tmp_path: Path):
        db = tmp_path / "test.db"
        _build_test_db(db)
        ds = AgentsviewDataSource(db)
        ds.discover_projects()
        ds.close()
        assert ds._conn is None

    def test_context_manager(self, tmp_path: Path):
        db = tmp_path / "test.db"
        _build_test_db(db)
        with AgentsviewDataSource(db) as ds:
            ds.discover_projects()
        assert ds._conn is None

    def test_safe_defaults(self, tmp_path: Path):
        db = tmp_path / "test.db"
        _build_test_db(db)
        ds = AgentsviewDataSource(db)
        proj = ds.discover_projects()
        assert ds.find_claude_md(
            ProjectInfo(encoded_name="x", project_dir=Path("."), session_files=[])
        ) is None


class TestLoadSessions:
    def _make_project(self, project_path: str = "/home/user/proj") -> ProjectInfo:
        encoded = project_path_to_encoded_name(project_path)
        return ProjectInfo(
            encoded_name=encoded,
            project_dir=Path(f"agentsview://{encoded}"),
            session_files=[],
        )

    def test_no_sessions_returns_empty(self, tmp_path: Path):
        db = tmp_path / "test.db"
        _build_test_db(db)
        ds = AgentsviewDataSource(db)
        assert ds.load_sessions(self._make_project()) == []

    def test_user_message_becomes_user_record(self, tmp_path: Path):
        db = tmp_path / "test.db"
        _build_test_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, "s1", "/home/user/proj")
        _insert_message(conn, "s1", "user", content="hello")
        conn.commit()
        conn.close()

        ds = AgentsviewDataSource(db)
        results = ds.load_sessions(self._make_project())
        assert len(results) == 1
        assert len(results[0].records) == 1
        rec = results[0].records[0]
        assert isinstance(rec, UserRecord)
        assert rec.content[0].text == "hello"

    def test_assistant_message_becomes_assistant_record(self, tmp_path: Path):
        db = tmp_path / "test.db"
        _build_test_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, "s1", "/home/user/proj")
        _insert_message(conn, "s1", "assistant", content="I'll help")
        conn.commit()
        conn.close()

        ds = AgentsviewDataSource(db)
        results = ds.load_sessions(self._make_project())
        rec = results[0].records[0]
        assert isinstance(rec, AssistantRecord)
        assert rec.content[0].text == "I'll help"

    def test_compact_boundary_becomes_system_record(self, tmp_path: Path):
        db = tmp_path / "test.db"
        _build_test_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, "s1", "/home/user/proj")
        _insert_message(conn, "s1", "user", is_compact_boundary=1)
        conn.commit()
        conn.close()

        ds = AgentsviewDataSource(db)
        results = ds.load_sessions(self._make_project())
        rec = results[0].records[0]
        assert isinstance(rec, SystemRecord)
        assert rec.subtype == "compact_boundary"

    def test_compact_boundary_type_is_system(self, tmp_path: Path):
        db = tmp_path / "test.db"
        _build_test_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, "s1", "/home/user/proj")
        _insert_message(conn, "s1", "user", is_compact_boundary=1)
        conn.commit()
        conn.close()

        ds = AgentsviewDataSource(db)
        results = ds.load_sessions(self._make_project())
        rec = results[0].records[0]
        assert isinstance(rec, SystemRecord)
        assert rec.type == "system"

    def test_is_system_continuation(self, tmp_path: Path):
        db = tmp_path / "test.db"
        _build_test_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, "s1", "/home/user/proj")
        _insert_message(
            conn, "s1", "user",
            content="This session is being continued from a previous conversation",
            is_system=1,
        )
        conn.commit()
        conn.close()

        ds = AgentsviewDataSource(db)
        results = ds.load_sessions(self._make_project())
        rec = results[0].records[0]
        assert isinstance(rec, SystemRecord)
        assert rec.subtype == "continuation"

    def test_multiple_sessions_ordered_by_latest(self, tmp_path: Path):
        db = tmp_path / "test.db"
        _build_test_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, "s_old", "/home/user/proj")
        _insert_session(conn, "s_new", "/home/user/proj")
        _insert_message(conn, "s_old", "user", content="old",
                        timestamp="2026-04-19T10:00:00Z")
        _insert_message(conn, "s_new", "user", content="new",
                        timestamp="2026-04-20T10:00:00Z")
        conn.commit()
        conn.close()

        ds = AgentsviewDataSource(db)
        results = ds.load_sessions(self._make_project())
        assert len(results) == 2
        assert results[0].records[0].session_id == "s_new"
        assert results[1].records[0].session_id == "s_old"

    def test_envelope_fields_populated(self, tmp_path: Path):
        db = tmp_path / "test.db"
        _build_test_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, "s1", "/home/user/proj",
                        cwd="/home/user/proj", git_branch="feat")
        _insert_message(
            conn, "s1", "user", content="hi",
            source_uuid="uuid-123", is_sidechain=1,
        )
        conn.commit()
        conn.close()

        ds = AgentsviewDataSource(db)
        rec = ds.load_sessions(self._make_project())[0].records[0]
        assert rec.uuid == "uuid-123"
        assert rec.cwd == "/home/user/proj"
        assert rec.is_sidechain is True
        assert rec.git_branch == "feat"
        assert rec.session_id == "s1"

    def test_messages_ordered_by_ordinal(self, tmp_path: Path):
        db = tmp_path / "test.db"
        _build_test_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, "s1", "/home/user/proj")
        _insert_message(conn, "s1", "user", content="second", ordinal=2,
                        timestamp="2026-04-20T10:00:00Z")
        _insert_message(conn, "s1", "assistant", content="first", ordinal=1,
                        timestamp="2026-04-20T10:00:01Z")
        conn.commit()
        conn.close()

        ds = AgentsviewDataSource(db)
        results = ds.load_sessions(self._make_project())
        assert results[0].records[0].content[0].text == "first"
        assert results[0].records[1].content[0].text == "second"


class TestActualTokens:
    """Phase 5a: real API token counts from agentsview."""

    def _make_project(self, project_path: str = "/home/user/proj") -> ProjectInfo:
        encoded = project_path_to_encoded_name(project_path)
        return ProjectInfo(
            encoded_name=encoded,
            project_dir=Path(f"agentsview://{encoded}"),
            session_files=[],
        )

    def test_assistant_gets_actual_tokens(self, tmp_path: Path):
        db = tmp_path / "test.db"
        _build_test_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, "s1", "/home/user/proj")
        _insert_message(conn, "s1", "assistant", content="hello",
                        has_output_tokens=1, output_tokens=150)
        conn.commit()
        conn.close()

        ds = AgentsviewDataSource(db)
        results = ds.load_sessions(self._make_project())
        rec = results[0].records[0]
        assert isinstance(rec, AssistantRecord)
        assert rec.actual_tokens == 150

    def test_assistant_without_tokens_gets_none(self, tmp_path: Path):
        db = tmp_path / "test.db"
        _build_test_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, "s1", "/home/user/proj")
        _insert_message(conn, "s1", "assistant", content="hello",
                        has_output_tokens=0, output_tokens=0)
        conn.commit()
        conn.close()

        ds = AgentsviewDataSource(db)
        results = ds.load_sessions(self._make_project())
        rec = results[0].records[0]
        assert isinstance(rec, AssistantRecord)
        assert rec.actual_tokens is None

    def test_user_record_has_no_actual_tokens(self, tmp_path: Path):
        db = tmp_path / "test.db"
        _build_test_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, "s1", "/home/user/proj")
        _insert_message(conn, "s1", "user", content="hello")
        conn.commit()
        conn.close()

        ds = AgentsviewDataSource(db)
        results = ds.load_sessions(self._make_project())
        rec = results[0].records[0]
        assert isinstance(rec, UserRecord)
        assert not hasattr(rec, "actual_tokens")

    def test_estimate_record_tokens_uses_actual(self):
        from prism.analyzer import estimate_record_tokens

        rec = AssistantRecord(
            uuid="u1", parent_uuid=None, is_sidechain=False,
            session_id="s1", timestamp="", version="", cwd="",
            git_branch=None, type="assistant", raw={},
            actual_tokens=250,
            content=[],
        )
        assert estimate_record_tokens(rec) == 250

    def test_estimate_record_tokens_applies_floor(self):
        from prism.analyzer import estimate_record_tokens

        rec = AssistantRecord(
            uuid="u1", parent_uuid=None, is_sidechain=False,
            session_id="s1", timestamp="", version="", cwd="",
            git_branch=None, type="assistant", raw={},
            actual_tokens=0,
            content=[],
        )
        assert estimate_record_tokens(rec) == 10

    def test_estimate_record_tokens_falls_back_to_heuristic(self):
        from prism.analyzer import estimate_record_tokens

        rec = AssistantRecord(
            uuid="u1", parent_uuid=None, is_sidechain=False,
            session_id="s1", timestamp="", version="", cwd="",
            git_branch=None, type="assistant", raw={},
            content=[ContentBlock(type="text", text="a" * 100)],
        )
        assert rec.actual_tokens is None
        assert estimate_record_tokens(rec) == 25  # 100 chars / 4


class TestResolveProjectPath:
    def test_hyphenated_project_path(self, tmp_path: Path):
        """Projects with hyphens in the name are resolved via DB lookup, not decode."""
        db = tmp_path / "test.db"
        _build_test_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, "s1", "/home/my-project")
        _insert_message(conn, "s1", "user", content="hi")
        conn.commit()
        conn.close()

        ds = AgentsviewDataSource(db)
        projects = ds.discover_projects()
        assert len(projects) == 1
        results = ds.load_sessions(projects[0])
        assert len(results) == 1

    def test_fallback_lookup_without_discover(self, tmp_path: Path):
        """load_sessions works even if discover_projects wasn't called first."""
        db = tmp_path / "test.db"
        _build_test_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, "s1", "/home/user/proj")
        _insert_message(conn, "s1", "user", content="hi")
        conn.commit()
        conn.close()

        ds = AgentsviewDataSource(db)
        proj = ProjectInfo(
            encoded_name=project_path_to_encoded_name("/home/user/proj"),
            project_dir=Path("agentsview://-home-user-proj"),
            session_files=[],
        )
        results = ds.load_sessions(proj)
        assert len(results) == 1

    def test_encoding_collision_last_wins(self, tmp_path: Path):
        """When two DB paths encode to the same name, the last one wins."""
        db = tmp_path / "test.db"
        _build_test_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, "s1", "/home/my-project")
        _insert_session(conn, "s2", "/home/my/project")
        _insert_message(conn, "s1", "user", content="a")
        _insert_message(conn, "s2", "user", content="b")
        conn.commit()
        conn.close()

        ds = AgentsviewDataSource(db)
        projects = ds.discover_projects()
        assert len(projects) == 2
        assert projects[0].encoded_name == projects[1].encoded_name

        # Both resolve to the last-cached path (/home/my/project = s2)
        results_first = ds.load_sessions(projects[0])
        results_last = ds.load_sessions(projects[-1])
        assert results_first == results_last
        assert len(results_last) == 1
        assert results_last[0].records[0].session_id == "s2"


class TestToolCallEnrichment:
    def _make_project(self, project_path: str = "/home/user/proj") -> ProjectInfo:
        encoded = project_path_to_encoded_name(project_path)
        return ProjectInfo(
            encoded_name=encoded,
            project_dir=Path(f"agentsview://{encoded}"),
            session_files=[],
        )

    def test_tool_use_on_assistant(self, tmp_path: Path):
        db = tmp_path / "test.db"
        _build_test_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, "s1", "/home/user/proj")
        msg_id = _insert_message(conn, "s1", "assistant", content="Let me read that")
        conn.execute(
            "INSERT INTO tool_calls (message_id, session_id, tool_name, tool_use_id, input_json)"
            " VALUES (?, ?, ?, ?, ?)",
            (msg_id, "s1", "Read", "tc1", '{"file_path": "/tmp/foo.py"}'),
        )
        conn.commit()
        conn.close()

        ds = AgentsviewDataSource(db)
        results = ds.load_sessions(self._make_project())
        rec = results[0].records[0]
        assert isinstance(rec, AssistantRecord)
        tool_blocks = [b for b in rec.content if b.type == "tool_use"]
        assert len(tool_blocks) == 1
        assert tool_blocks[0].tool_name == "Read"
        assert tool_blocks[0].tool_input == {"file_path": "/tmp/foo.py"}

    def test_tool_result_on_next_user(self, tmp_path: Path):
        db = tmp_path / "test.db"
        _build_test_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, "s1", "/home/user/proj")
        msg_id = _insert_message(conn, "s1", "assistant", content="Reading",
                                 timestamp="2026-04-20T10:00:00Z", ordinal=1)
        _insert_message(conn, "s1", "user", content="ok",
                        timestamp="2026-04-20T10:01:00Z", ordinal=2)
        conn.execute(
            "INSERT INTO tool_calls"
            " (message_id, session_id, tool_name, tool_use_id, input_json, result_content)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (msg_id, "s1", "Read", "tc1", '{"file_path": "/tmp/foo.py"}', "file contents here"),
        )
        conn.commit()
        conn.close()

        ds = AgentsviewDataSource(db)
        results = ds.load_sessions(self._make_project())
        user_rec = results[0].records[1]
        assert isinstance(user_rec, UserRecord)
        result_blocks = [b for b in user_rec.content if b.type == "tool_result"]
        assert len(result_blocks) == 1
        assert result_blocks[0].tool_content == "file contents here"
        assert result_blocks[0].tool_use_id == "tc1"

    def test_malformed_input_json(self, tmp_path: Path):
        db = tmp_path / "test.db"
        _build_test_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, "s1", "/home/user/proj")
        msg_id = _insert_message(conn, "s1", "assistant", content="")
        conn.execute(
            "INSERT INTO tool_calls (message_id, session_id, tool_name, tool_use_id, input_json)"
            " VALUES (?, ?, ?, ?, ?)",
            (msg_id, "s1", "Bash", "tc1", "not valid json"),
        )
        conn.commit()
        conn.close()

        ds = AgentsviewDataSource(db)
        results = ds.load_sessions(self._make_project())
        rec = results[0].records[0]
        tool_blocks = [b for b in rec.content if b.type == "tool_use"]
        assert tool_blocks[0].tool_input == {}

    def test_multiple_tool_calls_per_message(self, tmp_path: Path):
        db = tmp_path / "test.db"
        _build_test_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, "s1", "/home/user/proj")
        msg_id = _insert_message(conn, "s1", "assistant", content="")
        conn.execute(
            "INSERT INTO tool_calls (message_id, session_id, tool_name, tool_use_id, input_json)"
            " VALUES (?, ?, ?, ?, ?)",
            (msg_id, "s1", "Read", "tc1", '{"file_path": "a.py"}'),
        )
        conn.execute(
            "INSERT INTO tool_calls (message_id, session_id, tool_name, tool_use_id, input_json)"
            " VALUES (?, ?, ?, ?, ?)",
            (msg_id, "s1", "Read", "tc2", '{"file_path": "b.py"}'),
        )
        conn.commit()
        conn.close()

        ds = AgentsviewDataSource(db)
        results = ds.load_sessions(self._make_project())
        rec = results[0].records[0]
        tool_blocks = [b for b in rec.content if b.type == "tool_use"]
        assert len(tool_blocks) == 2

    def test_tool_calls_keyed_by_message_id(self, tmp_path: Path):
        """Tool calls are keyed by messages.id (integer), not source_uuid.

        Also covers assistant-only session: tool_result blocks are dropped
        when there is no UserRecord to receive them.
        """
        db = tmp_path / "test.db"
        _build_test_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, "s1", "/home/user/proj")
        msg_id = _insert_message(conn, "s1", "assistant", content="",
                                 source_uuid="uuid-different")
        conn.execute(
            "INSERT INTO tool_calls"
            " (message_id, session_id, tool_name, tool_use_id, input_json, result_content)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (msg_id, "s1", "Bash", "tc1", '{"command": "ls"}', "some output"),
        )
        conn.commit()
        conn.close()

        ds = AgentsviewDataSource(db)
        results = ds.load_sessions(self._make_project())
        rec = results[0].records[0]
        assert isinstance(rec, AssistantRecord)
        tool_blocks = [b for b in rec.content if b.type == "tool_use"]
        assert len(tool_blocks) == 1
        assert tool_blocks[0].tool_name == "Bash"
        # No UserRecord exists → tool_result is intentionally dropped
        result_blocks = [b for b in rec.content if b.type == "tool_result"]
        assert result_blocks == []

    def test_trailing_tool_results_flushed(self, tmp_path: Path):
        """Tool results from the last assistant message are flushed to the last user record."""
        db = tmp_path / "test.db"
        _build_test_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, "s1", "/home/user/proj")
        _insert_message(conn, "s1", "user", content="do something",
                        timestamp="2026-04-20T10:00:00Z", ordinal=1)
        msg_id = _insert_message(conn, "s1", "assistant", content="running",
                                 timestamp="2026-04-20T10:01:00Z", ordinal=2)
        conn.execute(
            "INSERT INTO tool_calls"
            " (message_id, session_id, tool_name, tool_use_id, input_json, result_content)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (msg_id, "s1", "Bash", "tc1", '{"command": "ls"}', "file1.py\nfile2.py"),
        )
        conn.commit()
        conn.close()

        ds = AgentsviewDataSource(db)
        results = ds.load_sessions(self._make_project())
        # The only user record should get the flushed tool results
        user_rec = results[0].records[0]
        assert isinstance(user_rec, UserRecord)
        result_blocks = [b for b in user_rec.content if b.type == "tool_result"]
        assert len(result_blocks) == 1
        assert result_blocks[0].tool_content == "file1.py\nfile2.py"


class TestFindClaudeMd:
    def test_found_in_project_path(self, tmp_path: Path):
        db = tmp_path / "test.db"
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "CLAUDE.md").write_text("# Rules\n", encoding="utf-8")

        _build_test_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, "s1", str(workspace))
        conn.commit()
        conn.close()

        ds = AgentsviewDataSource(db)
        projects = ds.discover_projects()
        assert len(projects) == 1
        result = ds.find_claude_md(projects[0])
        assert result == workspace / "CLAUDE.md"

    def test_found_via_cwd_fallback(self, tmp_path: Path):
        db = tmp_path / "test.db"
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "CLAUDE.md").write_text("# Rules\n", encoding="utf-8")

        # Project path intentionally doesn't exist — forces cwd fallback
        assert not (tmp_path / "nonexistent").exists()
        _build_test_db(db)
        conn = sqlite3.connect(db)
        # cwd lives on sessions in the real schema
        _insert_session(conn, "s1", str(tmp_path / "nonexistent"),
                        cwd=str(workspace))
        conn.commit()
        conn.close()

        ds = AgentsviewDataSource(db)
        projects = ds.discover_projects()
        result = ds.find_claude_md(projects[0])
        assert result == workspace / "CLAUDE.md"

    def test_returns_none_when_missing(self, tmp_path: Path):
        db = tmp_path / "test.db"
        _build_test_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, "s1", str(tmp_path / "nonexistent"),
                        cwd=str(tmp_path / "also-nonexistent"))
        conn.commit()
        conn.close()

        ds = AgentsviewDataSource(db)
        projects = ds.discover_projects()
        result = ds.find_claude_md(projects[0])
        assert result is None

    def test_returns_none_for_unknown_project(self, tmp_path: Path):
        db = tmp_path / "test.db"
        _build_test_db(db)
        ds = AgentsviewDataSource(db)
        proj = ProjectInfo(
            encoded_name="nonexistent", project_dir=Path("."), session_files=[],
        )
        assert ds.find_claude_md(proj) is None


class TestAnalyzeProjectIntegration:
    def test_analyze_with_agentsview_datasource(self, tmp_path: Path):
        from prism.analyzer import ProjectHealthReport, analyze_project

        db = tmp_path / "test.db"
        _build_test_db(db)
        conn = sqlite3.connect(db)
        _insert_session(conn, "s1", "/home/user/proj")
        _insert_message(conn, "s1", "user", content="hello world", ordinal=1)
        _insert_message(conn, "s1", "assistant", content="I can help",
                        timestamp="2026-04-20T10:01:00Z", ordinal=2)
        _insert_message(conn, "s1", "user", content="thanks",
                        timestamp="2026-04-20T10:02:00Z", ordinal=3)
        conn.commit()
        conn.close()

        ds = AgentsviewDataSource(db)
        proj = ProjectInfo(
            encoded_name=project_path_to_encoded_name("/home/user/proj"),
            project_dir=Path("agentsview://-home-user-proj"),
            session_files=[],
        )
        report = analyze_project(proj, datasource=ds)
        assert isinstance(report, ProjectHealthReport)
        assert report.session_count == 1
