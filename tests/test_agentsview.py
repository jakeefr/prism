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


class TestDecodeProjectPath:
    def test_unix_path(self):
        assert AgentsviewDataSource._decode_project_path("-home-user-proj") == "/home/user/proj"

    def test_windows_path(self):
        assert AgentsviewDataSource._decode_project_path("D--prism") == "D:\\prism"

    def test_windows_deep_path(self):
        result = AgentsviewDataSource._decode_project_path("D--jarvis-space")
        assert result == "D:\\jarvis\\space"


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
