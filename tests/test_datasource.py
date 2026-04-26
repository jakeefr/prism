"""Tests for prism.datasource — SessionDataSource protocol and JSONLDataSource."""

from __future__ import annotations

import json
from pathlib import Path

from prism.analyzer import ProjectHealthReport, analyze_project
from prism.datasource import JSONLDataSource, SessionDataSource
from prism.parser import ParseResult, ProjectInfo

FIXTURES = Path(__file__).parent / "fixtures"


class _MockDataSource:
    """Minimal implementation that satisfies the protocol."""

    def discover_projects(self) -> list[ProjectInfo]:
        return []

    def load_sessions(self, project: ProjectInfo) -> list[ParseResult]:
        return []

    def find_claude_md(self, project: ProjectInfo) -> Path | None:
        return None


class TestSessionDataSourceProtocol:
    def test_mock_is_instance(self):
        assert isinstance(_MockDataSource(), SessionDataSource)

    def test_discover_projects_returns_list(self):
        ds = _MockDataSource()
        assert ds.discover_projects() == []

    def test_load_sessions_returns_list(self, tmp_path):
        ds = _MockDataSource()
        proj = ProjectInfo(
            encoded_name="test",
            project_dir=tmp_path,
            session_files=[],
        )
        assert ds.load_sessions(proj) == []

    def test_find_claude_md_returns_none(self, tmp_path):
        ds = _MockDataSource()
        proj = ProjectInfo(
            encoded_name="test",
            project_dir=tmp_path,
            session_files=[],
        )
        assert ds.find_claude_md(proj) is None


def _make_session_file(directory: Path, cwd: str) -> Path:
    """Write a minimal valid JSONL session file pointing at the given cwd."""
    record = {
        "uuid": "u1",
        "parentUuid": None,
        "isSidechain": False,
        "sessionId": "s1",
        "timestamp": "2026-04-10T10:00:00.000Z",
        "version": "2.1.98",
        "cwd": cwd,
        "gitBranch": "main",
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]},
    }
    path = directory / "session.jsonl"
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    return path


class TestJSONLDataSource:
    def test_is_session_data_source(self):
        assert isinstance(JSONLDataSource(), SessionDataSource)

    def test_discover_projects_empty_dir(self, tmp_path):
        ds = JSONLDataSource(base_dir=tmp_path)
        assert ds.discover_projects() == []

    def test_discover_projects_finds_project(self, tmp_path):
        proj_dir = tmp_path / "-home-user-proj"
        proj_dir.mkdir()
        _make_session_file(proj_dir, "/home/user/proj")
        ds = JSONLDataSource(base_dir=tmp_path)
        projects = ds.discover_projects()
        assert len(projects) == 1
        assert projects[0].encoded_name == "-home-user-proj"

    def test_load_sessions_returns_parse_results(self):
        proj = ProjectInfo(
            encoded_name="test",
            project_dir=FIXTURES,
            session_files=[FIXTURES / "sample_session.jsonl"],
        )
        ds = JSONLDataSource()
        results = ds.load_sessions(proj)
        assert len(results) == 1
        assert isinstance(results[0], ParseResult)
        assert len(results[0].records) > 0

    def test_find_claude_md_returns_path(self, tmp_path):
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "CLAUDE.md").write_text("# Rules\n", encoding="utf-8")
        session_file = _make_session_file(proj_dir, str(workspace))
        proj = ProjectInfo(
            encoded_name="test",
            project_dir=proj_dir,
            session_files=[session_file],
        )
        ds = JSONLDataSource()
        result = ds.find_claude_md(proj)
        assert result == workspace / "CLAUDE.md"

    def test_find_claude_md_returns_none_when_missing(self, tmp_path):
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()
        session_file = _make_session_file(proj_dir, str(tmp_path / "nonexistent"))
        proj = ProjectInfo(
            encoded_name="test",
            project_dir=proj_dir,
            session_files=[session_file],
        )
        ds = JSONLDataSource()
        assert ds.find_claude_md(proj) is None

    def test_analyze_project_with_datasource(self):
        proj = ProjectInfo(
            encoded_name="test",
            project_dir=FIXTURES,
            session_files=[FIXTURES / "sample_session.jsonl"],
        )
        ds = JSONLDataSource()
        report = analyze_project(proj, datasource=ds)
        assert isinstance(report, ProjectHealthReport)
        assert report.session_count >= 1
