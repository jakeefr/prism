"""Tests for prism.agentsview — AgentsviewDataSource."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from prism.agentsview import AgentsviewDataSource
from prism.datasource import SessionDataSource
from prism.parser import (
    AssistantRecord,
    ProjectInfo,
    SystemRecord,
    UserRecord,
    project_path_to_encoded_name,
)


def _build_test_db(db_path: Path) -> None:
    """Create a minimal agentsview SQLite DB with the tables needed by the adapter."""
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY,
            project TEXT,
            model TEXT,
            created_at TEXT,
            deleted_at TEXT
        );
        CREATE TABLE messages (
            message_id TEXT PRIMARY KEY,
            session_id TEXT,
            role TEXT,
            content TEXT,
            timestamp TEXT,
            uuid TEXT,
            parent_uuid TEXT,
            is_sidechain INTEGER DEFAULT 0,
            cwd TEXT,
            version TEXT,
            git_branch TEXT,
            is_compact_boundary INTEGER DEFAULT 0,
            is_system INTEGER DEFAULT 0
        );
        CREATE TABLE tool_calls (
            tool_call_id TEXT PRIMARY KEY,
            message_id TEXT,
            tool_name TEXT,
            input_json TEXT,
            output_text TEXT,
            is_error INTEGER DEFAULT 0
        );
    """)
    conn.close()


def _insert_message(
    conn: sqlite3.Connection,
    message_id: str,
    session_id: str,
    role: str,
    content: str = "",
    timestamp: str = "2026-04-20T10:00:00Z",
    uuid: str = "",
    cwd: str = "/home/user/proj",
    **kwargs: object,
) -> None:
    """Insert a message row with sensible defaults."""
    defaults = {
        "parent_uuid": None,
        "is_sidechain": 0,
        "version": "2.1.98",
        "git_branch": "main",
        "is_compact_boundary": 0,
        "is_system": 0,
    }
    defaults.update(kwargs)
    conn.execute(
        "INSERT INTO messages"
        " (message_id, session_id, role, content, timestamp, uuid, cwd,"
        "  parent_uuid, is_sidechain, version, git_branch,"
        "  is_compact_boundary, is_system)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            message_id, session_id, role, content, timestamp,
            uuid or message_id, cwd,
            defaults["parent_uuid"], defaults["is_sidechain"],
            defaults["version"], defaults["git_branch"],
            defaults["is_compact_boundary"], defaults["is_system"],
        ),
    )


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
        conn.execute(
            "INSERT INTO sessions (session_id, project) VALUES (?, ?)",
            ("s1", "/home/user/proj"),
        )
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
        conn.execute(
            "INSERT INTO sessions (session_id, project, deleted_at) VALUES (?, ?, ?)",
            ("s1", "/home/user/proj", "2026-04-20T10:00:00Z"),
        )
        conn.commit()
        conn.close()

        ds = AgentsviewDataSource(db)
        assert ds.discover_projects() == []

    def test_multiple_sessions_same_project_deduped(self, tmp_path: Path):
        db = tmp_path / "test.db"
        _build_test_db(db)
        conn = sqlite3.connect(db)
        conn.executemany(
            "INSERT INTO sessions (session_id, project) VALUES (?, ?)",
            [("s1", "/home/user/proj"), ("s2", "/home/user/proj")],
        )
        conn.commit()
        conn.close()

        ds = AgentsviewDataSource(db)
        projects = ds.discover_projects()
        assert len(projects) == 1

    def test_multiple_distinct_projects(self, tmp_path: Path):
        db = tmp_path / "test.db"
        _build_test_db(db)
        conn = sqlite3.connect(db)
        conn.executemany(
            "INSERT INTO sessions (session_id, project) VALUES (?, ?)",
            [("s1", "/home/user/alpha"), ("s2", "/home/user/beta")],
        )
        conn.commit()
        conn.close()

        ds = AgentsviewDataSource(db)
        projects = ds.discover_projects()
        assert len(projects) == 2
        names = {p.encoded_name for p in projects}
        assert project_path_to_encoded_name("/home/user/alpha") in names
        assert project_path_to_encoded_name("/home/user/beta") in names

    def test_null_project_excluded(self, tmp_path: Path):
        db = tmp_path / "test.db"
        _build_test_db(db)
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO sessions (session_id, project) VALUES (?, ?)",
            ("s1", None),
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
        conn.execute(
            "INSERT INTO sessions (session_id, project) VALUES (?, ?)",
            ("s1", "/home/user/proj"),
        )
        _insert_message(conn, "m1", "s1", "user", content="hello")
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
        conn.execute(
            "INSERT INTO sessions (session_id, project) VALUES (?, ?)",
            ("s1", "/home/user/proj"),
        )
        _insert_message(conn, "m1", "s1", "assistant", content="I'll help")
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
        conn.execute(
            "INSERT INTO sessions (session_id, project) VALUES (?, ?)",
            ("s1", "/home/user/proj"),
        )
        _insert_message(conn, "m1", "s1", "user", is_compact_boundary=1)
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
        conn.execute(
            "INSERT INTO sessions (session_id, project) VALUES (?, ?)",
            ("s1", "/home/user/proj"),
        )
        _insert_message(conn, "m1", "s1", "user", is_compact_boundary=1)
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
        conn.execute(
            "INSERT INTO sessions (session_id, project) VALUES (?, ?)",
            ("s1", "/home/user/proj"),
        )
        _insert_message(
            conn, "m1", "s1", "user",
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
        conn.execute(
            "INSERT INTO sessions (session_id, project) VALUES (?, ?)",
            ("s_old", "/home/user/proj"),
        )
        conn.execute(
            "INSERT INTO sessions (session_id, project) VALUES (?, ?)",
            ("s_new", "/home/user/proj"),
        )
        _insert_message(conn, "m1", "s_old", "user", content="old",
                         timestamp="2026-04-19T10:00:00Z")
        _insert_message(conn, "m2", "s_new", "user", content="new",
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
        conn.execute(
            "INSERT INTO sessions (session_id, project) VALUES (?, ?)",
            ("s1", "/home/user/proj"),
        )
        _insert_message(
            conn, "m1", "s1", "user", content="hi",
            uuid="uuid-123", cwd="/home/user/proj",
            is_sidechain=1, git_branch="feat",
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


class TestResolveProjectPath:
    def test_hyphenated_project_path(self, tmp_path: Path):
        """Projects with hyphens in the name are resolved via DB lookup, not decode."""
        db = tmp_path / "test.db"
        _build_test_db(db)
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO sessions (session_id, project) VALUES (?, ?)",
            ("s1", "/home/my-project"),
        )
        _insert_message(conn, "m1", "s1", "user", content="hi")
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
        conn.execute(
            "INSERT INTO sessions (session_id, project) VALUES (?, ?)",
            ("s1", "/home/user/proj"),
        )
        _insert_message(conn, "m1", "s1", "user", content="hi")
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
        """When two DB paths encode to the same name, the last one wins.

        Known limitation: project_path_to_encoded_name is non-injective.
        Both projects get the same encoded_name. The internal cache stores
        only the last-seen path, so load_sessions for either ProjectInfo
        returns sessions from the last-discovered project. The first
        project's sessions are unreachable via encoded_name lookup.
        """
        db = tmp_path / "test.db"
        _build_test_db(db)
        conn = sqlite3.connect(db)
        # /home/my-project and /home/my/project both encode to -home-my-project
        conn.execute(
            "INSERT INTO sessions (session_id, project) VALUES (?, ?)",
            ("s1", "/home/my-project"),
        )
        conn.execute(
            "INSERT INTO sessions (session_id, project) VALUES (?, ?)",
            ("s2", "/home/my/project"),
        )
        _insert_message(conn, "m1", "s1", "user", content="a")
        _insert_message(conn, "m2", "s2", "user", content="b")
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
        conn.execute(
            "INSERT INTO sessions (session_id, project) VALUES (?, ?)",
            ("s1", "/home/user/proj"),
        )
        _insert_message(conn, "m1", "s1", "assistant", content="Let me read that",
                         uuid="m1")
        conn.execute(
            "INSERT INTO tool_calls (tool_call_id, message_id, tool_name, input_json)"
            " VALUES (?, ?, ?, ?)",
            ("tc1", "m1", "Read", '{"file_path": "/tmp/foo.py"}'),
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
        conn.execute(
            "INSERT INTO sessions (session_id, project) VALUES (?, ?)",
            ("s1", "/home/user/proj"),
        )
        _insert_message(conn, "m1", "s1", "assistant", content="Reading",
                         uuid="m1", timestamp="2026-04-20T10:00:00Z")
        _insert_message(conn, "m2", "s1", "user", content="ok",
                         uuid="m2", timestamp="2026-04-20T10:01:00Z")
        conn.execute(
            "INSERT INTO tool_calls"
            " (tool_call_id, message_id, tool_name, input_json, output_text)"
            " VALUES (?, ?, ?, ?, ?)",
            ("tc1", "m1", "Read", '{"file_path": "/tmp/foo.py"}', "file contents here"),
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
        conn.execute(
            "INSERT INTO sessions (session_id, project) VALUES (?, ?)",
            ("s1", "/home/user/proj"),
        )
        _insert_message(conn, "m1", "s1", "assistant", content="",
                         uuid="m1")
        conn.execute(
            "INSERT INTO tool_calls (tool_call_id, message_id, tool_name, input_json)"
            " VALUES (?, ?, ?, ?)",
            ("tc1", "m1", "Bash", "not valid json"),
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
        conn.execute(
            "INSERT INTO sessions (session_id, project) VALUES (?, ?)",
            ("s1", "/home/user/proj"),
        )
        _insert_message(conn, "m1", "s1", "assistant", content="",
                         uuid="m1")
        conn.execute(
            "INSERT INTO tool_calls (tool_call_id, message_id, tool_name, input_json)"
            " VALUES (?, ?, ?, ?)",
            ("tc1", "m1", "Read", '{"file_path": "a.py"}'),
        )
        conn.execute(
            "INSERT INTO tool_calls (tool_call_id, message_id, tool_name, input_json)"
            " VALUES (?, ?, ?, ?)",
            ("tc2", "m1", "Read", '{"file_path": "b.py"}'),
        )
        conn.commit()
        conn.close()

        ds = AgentsviewDataSource(db)
        results = ds.load_sessions(self._make_project())
        rec = results[0].records[0]
        tool_blocks = [b for b in rec.content if b.type == "tool_use"]
        assert len(tool_blocks) == 2


class TestAnalyzeProjectIntegration:
    def test_analyze_with_agentsview_datasource(self, tmp_path: Path):
        from prism.analyzer import ProjectHealthReport, analyze_project

        db = tmp_path / "test.db"
        _build_test_db(db)
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO sessions (session_id, project) VALUES (?, ?)",
            ("s1", "/home/user/proj"),
        )
        _insert_message(conn, "m1", "s1", "user", content="hello world")
        _insert_message(conn, "m2", "s1", "assistant", content="I can help",
                         timestamp="2026-04-20T10:01:00Z")
        _insert_message(conn, "m3", "s1", "user", content="thanks",
                         timestamp="2026-04-20T10:02:00Z")
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
