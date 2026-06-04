"""Tests for prism.cli — CLI commands and datasource wiring."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from prism.cli import _resolve_agentsview_db, app
from tests.conftest import build_test_db

runner = CliRunner()


# ---------------------------------------------------------------------------
# _resolve_agentsview_db priority chain
# ---------------------------------------------------------------------------


class TestResolveAgentsviewDb:
    def test_explicit_path_wins(self, tmp_path: Path) -> None:
        p = tmp_path / "my.db"
        assert _resolve_agentsview_db(p) == p

    def test_agentsview_data_dir_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENTSVIEW_DATA_DIR", str(tmp_path))
        monkeypatch.delenv("AGENT_VIEWER_DATA_DIR", raising=False)
        assert _resolve_agentsview_db() == tmp_path / "sessions.db"

    def test_agent_viewer_data_dir_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("AGENTSVIEW_DATA_DIR", raising=False)
        monkeypatch.setenv("AGENT_VIEWER_DATA_DIR", str(tmp_path))
        assert _resolve_agentsview_db() == tmp_path / "sessions.db"

    def test_agentsview_takes_precedence_over_agent_viewer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        newer = tmp_path / "newer"
        older = tmp_path / "older"
        newer.mkdir()
        older.mkdir()
        monkeypatch.setenv("AGENTSVIEW_DATA_DIR", str(newer))
        monkeypatch.setenv("AGENT_VIEWER_DATA_DIR", str(older))
        assert _resolve_agentsview_db() == newer / "sessions.db"

    def test_default_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AGENTSVIEW_DATA_DIR", raising=False)
        monkeypatch.delenv("AGENT_VIEWER_DATA_DIR", raising=False)
        result = _resolve_agentsview_db()
        assert result == Path.home() / ".agentsview" / "sessions.db"

    def test_explicit_overrides_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENTSVIEW_DATA_DIR", str(tmp_path / "env"))
        explicit = tmp_path / "explicit.db"
        assert _resolve_agentsview_db(explicit) == explicit


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _populate_db(db_path: Path) -> None:
    """Insert a minimal project with one session and a user+assistant exchange."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO sessions (id, project, cwd, git_branch, source_version)"
        " VALUES (?, ?, ?, ?, ?)",
        ("sess-1", "/home/user/proj", "/home/user/proj", "main", "2.1.98"),
    )
    conn.execute(
        "INSERT INTO messages (session_id, ordinal, role, content, timestamp,"
        " source_uuid, source_parent_uuid, is_sidechain, is_compact_boundary, is_system)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("sess-1", 1, "user", "hello", "2026-04-20T10:00:00Z",
         "u1", "", 0, 0, 0),
    )
    conn.execute(
        "INSERT INTO messages (session_id, ordinal, role, content, timestamp,"
        " source_uuid, source_parent_uuid, is_sidechain, is_compact_boundary, is_system)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("sess-1", 2, "assistant", "hi there", "2026-04-20T10:00:01Z",
         "u2", "u1", 0, 0, 0),
    )
    conn.commit()
    conn.close()


def _make_test_db(tmp_path: Path) -> Path:
    """Build and populate a test DB, return its path."""
    db_path = tmp_path / "sessions.db"
    build_test_db(db_path)
    _populate_db(db_path)
    return db_path


# ---------------------------------------------------------------------------
# CLI: --source agentsview
# ---------------------------------------------------------------------------


class TestAnalyzeAgentsview:
    def test_analyze_agentsview_source(self, tmp_path: Path) -> None:
        db_path = _make_test_db(tmp_path)
        result = runner.invoke(
            app, ["analyze", "--source", "agentsview", "--agentsview-db", str(db_path)]
        )
        assert result.exit_code == 0
        assert "PRISM Health Report" in result.output

    def test_analyze_agentsview_json(self, tmp_path: Path) -> None:
        db_path = _make_test_db(tmp_path)
        result = runner.invoke(
            app,
            ["analyze", "--source", "agentsview", "--agentsview-db", str(db_path), "--json"],
        )
        assert result.exit_code == 0
        assert '"overall_grade"' in result.output

    def test_analyze_agentsview_json_with_health(self, tmp_path: Path) -> None:
        db_path = _make_test_db(tmp_path)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE sessions SET health_score = 85, health_grade = 'B',"
            " outcome = 'success' WHERE id = 'sess-1'"
        )
        conn.commit()
        conn.close()
        result = runner.invoke(
            app,
            ["analyze", "--source", "agentsview", "--agentsview-db", str(db_path), "--json"],
        )
        assert result.exit_code == 0
        assert '"agentsview_health"' in result.output
        assert '"mean_score"' in result.output

    def test_analyze_agentsview_json_no_health_key_when_absent(self, tmp_path: Path) -> None:
        db_path = _make_test_db(tmp_path)
        result = runner.invoke(
            app,
            ["analyze", "--source", "agentsview", "--agentsview-db", str(db_path), "--json"],
        )
        assert result.exit_code == 0
        assert '"agentsview_health"' not in result.output

    def test_analyze_agentsview_db_not_found(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            ["analyze", "--source", "agentsview", "--agentsview-db", str(tmp_path / "nope.db")],
        )
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_analyze_agentsview_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_test_db(tmp_path)
        monkeypatch.setenv("AGENTSVIEW_DATA_DIR", str(tmp_path))
        result = runner.invoke(app, ["analyze", "--source", "agentsview"])
        assert result.exit_code == 0


class TestAdviseAgentsview:
    def test_advise_agentsview_source(self, tmp_path: Path) -> None:
        db_path = _make_test_db(tmp_path)
        result = runner.invoke(
            app, ["advise", "--source", "agentsview", "--agentsview-db", str(db_path)]
        )
        assert result.exit_code == 0


class TestDashboardAgentsview:
    def test_dashboard_agentsview_source(self, tmp_path: Path) -> None:
        db_path = _make_test_db(tmp_path)
        result = runner.invoke(
            app,
            ["dashboard", "--source", "agentsview", "--agentsview-db", str(db_path), "--no-open"],
        )
        assert result.exit_code == 0
        assert "Dashboard generated" in result.output


# ---------------------------------------------------------------------------
# CLI: validation errors
# ---------------------------------------------------------------------------


class TestSourceValidation:
    def test_invalid_source_rejected(self) -> None:
        result = runner.invoke(app, ["analyze", "--source", "badvalue"])
        assert result.exit_code != 0

    def test_project_with_agentsview_rejected(self, tmp_path: Path) -> None:
        db_path = _make_test_db(tmp_path)
        result = runner.invoke(
            app,
            ["analyze", "--source", "agentsview", "--agentsview-db", str(db_path),
             "--project", "/some/path"],
        )
        assert result.exit_code != 0
        assert "--project cannot be used" in result.output

    def test_base_dir_with_agentsview_rejected(self, tmp_path: Path) -> None:
        db_path = _make_test_db(tmp_path)
        result = runner.invoke(
            app,
            ["analyze", "--source", "agentsview", "--agentsview-db", str(db_path),
             "--base-dir", str(tmp_path)],
        )
        assert result.exit_code != 0
        assert "--base-dir cannot be used" in result.output

    def test_advise_project_with_agentsview_rejected(self, tmp_path: Path) -> None:
        db_path = _make_test_db(tmp_path)
        result = runner.invoke(
            app,
            ["advise", "--source", "agentsview", "--agentsview-db", str(db_path),
             "--project", "/some/path"],
        )
        assert result.exit_code != 0
        assert "--project cannot be used" in result.output

    def test_advise_base_dir_with_agentsview_rejected(self, tmp_path: Path) -> None:
        db_path = _make_test_db(tmp_path)
        result = runner.invoke(
            app,
            ["advise", "--source", "agentsview", "--agentsview-db", str(db_path),
             "--base-dir", str(tmp_path)],
        )
        assert result.exit_code != 0
        assert "--base-dir cannot be used" in result.output

    def test_dashboard_base_dir_with_agentsview_rejected(self, tmp_path: Path) -> None:
        db_path = _make_test_db(tmp_path)
        result = runner.invoke(
            app,
            ["dashboard", "--source", "agentsview", "--agentsview-db", str(db_path),
             "--base-dir", str(tmp_path), "--no-open"],
        )
        assert result.exit_code != 0
        assert "--base-dir cannot be used" in result.output


# ---------------------------------------------------------------------------
# CLI: default --source jsonl unchanged
# ---------------------------------------------------------------------------


class TestDefaultJsonlBehavior:
    def test_analyze_default_no_sessions(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["analyze", "--base-dir", str(tmp_path)])
        assert result.exit_code != 0
        assert "No Claude Code sessions found" in result.output

    def test_analyze_default_with_sessions(self, tmp_path: Path) -> None:
        proj_dir = tmp_path / "test-project"
        proj_dir.mkdir()
        session = proj_dir / "session1.jsonl"
        session.write_text(
            '{"uuid":"u1","parentUuid":null,"isSidechain":false,'
            '"sessionId":"s1","timestamp":"2026-04-20T10:00:00Z",'
            '"version":"2.1","cwd":"/tmp","type":"user",'
            '"message":{"content":[{"type":"text","text":"hi"}]}}\n'
            '{"uuid":"u2","parentUuid":"u1","isSidechain":false,'
            '"sessionId":"s1","timestamp":"2026-04-20T10:00:01Z",'
            '"version":"2.1","cwd":"/tmp","type":"assistant",'
            '"message":{"content":[{"type":"text","text":"hello"}]}}\n',
            encoding="utf-8",
        )
        result = runner.invoke(app, ["analyze", "--base-dir", str(tmp_path)])
        assert result.exit_code == 0
        assert "PRISM Health Report" in result.output


# ---------------------------------------------------------------------------
# CLI: --json output contract (consumed by cloudcli-plugin-prism)
# ---------------------------------------------------------------------------


def _envelope(uuid: str, parent: str | None, rtype: str, message: dict) -> str:
    """Build one JSONL line with the common envelope fields."""
    return json.dumps({
        "uuid": uuid,
        "parentUuid": parent,
        "isSidechain": False,
        "sessionId": "contract-sess",
        "timestamp": "2026-06-01T10:00:00Z",
        "version": "2.1.150",
        "cwd": "/tmp/proj",
        "gitBranch": "main",
        "type": rtype,
        "message": message,
    })


def _write_contract_fixture(tmp_path: Path) -> Path:
    """Project whose analysis yields an issue description >80 chars containing
    rich-markup-style bracket text — the exact inputs that corrupted --json output.
    """
    proj_dir = tmp_path / "contract-project"
    proj_dir.mkdir()
    # An Edit to a migration file triggers a high-severity tool_health issue whose
    # description embeds the file path verbatim.
    long_markup_path = (
        "/srv/app/db/migrations/0001_[bold]initial_schema[/bold]_with_a_very_"
        "long_descriptive_name_that_forces_line_wrapping_in_narrow_consoles.py"
    )
    lines = [
        _envelope("u1", None, "user",
                  {"role": "user", "content": [{"type": "text", "text": "fix the schema"}]}),
        _envelope("a1", "u1", "assistant",
                  {"role": "assistant", "content": [{
                      "type": "tool_use",
                      "id": "toolu_001",
                      "name": "Edit",
                      "input": {"file_path": long_markup_path},
                  }]}),
        _envelope("u2", "a1", "user",
                  {"role": "user", "content": [{
                      "type": "tool_result",
                      "tool_use_id": "toolu_001",
                      "content": "ok",
                  }]}),
    ]
    (proj_dir / "session1.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return proj_dir


class TestJsonOutputContract:
    """analyze --json must emit valid, unmangled JSON with the fields the
    cloudcli-plugin-prism consumer parses."""

    def test_json_round_trips_with_long_and_markup_descriptions(self, tmp_path: Path) -> None:
        _write_contract_fixture(tmp_path)
        result = runner.invoke(app, ["analyze", "--base-dir", str(tmp_path), "--json"])
        assert result.exit_code == 0

        # Must parse: rich line-wrapping previously injected raw newlines into
        # string literals, breaking json.loads / JSON.parse downstream.
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 1
        entry = data[0]

        # Every field the plugin reads must be present.
        for key in ("project", "display_name", "session_count",
                    "overall_grade", "overall_score", "dimensions", "top_issues"):
            assert key in entry, f"missing contract field: {key}"
        assert entry["dimensions"], "dimensions must not be empty"
        for name, dim in entry["dimensions"].items():
            assert "grade" in dim, f"dimensions.{name} missing grade"
            assert "score" in dim, f"dimensions.{name} missing score"
        assert entry["top_issues"], "expected at least one issue from fixture"
        for issue in entry["top_issues"]:
            for key in ("severity", "category", "description"):
                assert key in issue, f"top_issues entry missing {key}"

        # Markup-style brackets must survive verbatim — rich markup previously
        # stripped them from descriptions.
        descriptions = [i["description"] for i in entry["top_issues"]]
        assert any("[bold]" in d for d in descriptions), (
            "bracket text was stripped from issue descriptions"
        )
