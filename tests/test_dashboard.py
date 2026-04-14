"""Tests for prism.dashboard — HTML dashboard generator."""

from __future__ import annotations

from pathlib import Path

import pytest

from prism.analyzer import analyze_project
from prism.dashboard import (
    _build_project_data,
    _safe_json,
    generate_dashboard,
    get_dashboard_path,
)
from prism.parser import ProjectInfo

FIXTURES = Path(__file__).parent / "fixtures"


def _make_project(tmp_path: Path, session_files: list[Path]) -> ProjectInfo:
    proj_dir = tmp_path / "proj"
    proj_dir.mkdir(exist_ok=True)
    for sf in session_files:
        dest = proj_dir / sf.name
        dest.write_bytes(sf.read_bytes())
    return ProjectInfo(
        encoded_name="-home-user-proj",
        project_dir=proj_dir,
        session_files=[proj_dir / sf.name for sf in session_files],
    )


class TestSafeJson:
    def test_escapes_angle_brackets(self):
        result = _safe_json({"key": "<script>alert(1)</script>"})
        assert "<script>" not in result
        assert r"\u003c" in result
        assert r"\u003e" in result

    def test_escapes_ampersand(self):
        result = _safe_json({"key": "a&b"})
        assert "&b" not in result
        assert r"\u0026" in result

    def test_valid_json(self):
        import json
        data = {"a": 1, "b": [1, 2, 3], "c": None}
        result = _safe_json(data)
        parsed = json.loads(result)
        assert parsed == data

    def test_nested_structure(self):
        import json
        data = {"projects": [{"name": "test", "score": 95.5, "issues": []}]}
        result = _safe_json(data)
        parsed = json.loads(result)
        assert parsed == data


class TestBuildProjectData:
    def test_returns_expected_keys(self, tmp_path):
        project = _make_project(tmp_path, [FIXTURES / "sample_session.jsonl"])
        report = analyze_project(project)
        data = _build_project_data(report)
        for key in ("name", "display_name", "overall_grade", "overall_score",
                    "dimensions", "top_issues", "advisor_recommendations",
                    "session_count"):
            assert key in data, f"Missing key: {key}"

    def test_dimensions_have_expected_keys(self, tmp_path):
        project = _make_project(tmp_path, [FIXTURES / "sample_session.jsonl"])
        report = analyze_project(project)
        data = _build_project_data(report)
        for dim in ("token_efficiency", "tool_health", "context_hygiene",
                    "md_adherence", "continuity"):
            assert dim in data["dimensions"], f"Missing dimension: {dim}"
            d = data["dimensions"][dim]
            assert "grade" in d
            assert "score" in d
            assert "issues" in d

    def test_session_count_matches(self, tmp_path):
        project = _make_project(tmp_path, [FIXTURES / "sample_session.jsonl"])
        report = analyze_project(project)
        data = _build_project_data(report)
        assert data["session_count"] == report.session_count

    def test_advisor_recs_are_list(self, tmp_path):
        project = _make_project(tmp_path, [FIXTURES / "session_with_retries.jsonl"])
        report = analyze_project(project)
        data = _build_project_data(report)
        assert isinstance(data["advisor_recommendations"], list)
        for rec in data["advisor_recommendations"]:
            assert "action" in rec
            assert "impact" in rec
            assert "content" in rec
            assert "rationale" in rec


class TestGenerateDashboard:
    def test_creates_html_file(self, tmp_path):
        project = _make_project(tmp_path, [FIXTURES / "sample_session.jsonl"])
        report = analyze_project(project)
        output = tmp_path / "dashboard.html"
        result = generate_dashboard([report], output)
        assert result == output
        assert output.exists()

    def test_html_is_self_contained(self, tmp_path):
        project = _make_project(tmp_path, [FIXTURES / "sample_session.jsonl"])
        report = analyze_project(project)
        output = tmp_path / "dashboard.html"
        generate_dashboard([report], output)
        content = output.read_text(encoding="utf-8")
        # Must have HTML structure
        assert "<!DOCTYPE html>" in content
        assert "<html" in content
        assert "</html>" in content
        # No external resources
        assert "cdn." not in content
        assert "https://" not in content
        # Data embedded
        assert "prism-data" in content

    def test_html_contains_version(self, tmp_path):
        from prism import __version__
        project = _make_project(tmp_path, [FIXTURES / "sample_session.jsonl"])
        report = analyze_project(project)
        output = tmp_path / "dashboard.html"
        generate_dashboard([report], output)
        content = output.read_text(encoding="utf-8")
        assert __version__ in content

    def test_multiple_projects(self, tmp_path):
        import json
        (tmp_path / "p1").mkdir()
        (tmp_path / "p2").mkdir()
        p1 = _make_project(tmp_path / "p1", [FIXTURES / "sample_session.jsonl"])
        p2 = _make_project(tmp_path / "p2", [FIXTURES / "session_with_retries.jsonl"])
        r1 = analyze_project(p1)
        r2 = analyze_project(p2)
        output = tmp_path / "dashboard.html"
        generate_dashboard([r1, r2], output)
        content = output.read_text(encoding="utf-8")
        assert output.exists()
        # JSON blob should have 2 projects
        start = content.find('type="application/json"')
        assert start != -1

    def test_empty_projects_list(self, tmp_path):
        output = tmp_path / "dashboard.html"
        result = generate_dashboard([], output)
        assert result == output
        assert output.exists()
        content = output.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content

    def test_xss_safe_project_name(self, tmp_path):
        """Project names with special chars are safely embedded."""
        project = _make_project(tmp_path, [FIXTURES / "sample_session.jsonl"])
        # Monkey-patch encoded_name with XSS payload
        project = ProjectInfo(
            encoded_name='<script>alert(1)</script>',
            project_dir=project.project_dir,
            session_files=project.session_files,
        )
        report = analyze_project(project)
        output = tmp_path / "dashboard.html"
        generate_dashboard([report], output)
        content = output.read_text(encoding="utf-8")
        # Raw <script> tag from the project name must not appear outside the data blob
        # The JSON blob itself uses unicode escapes
        assert "<script>alert(1)</script>" not in content


class TestGetDashboardPath:
    def test_returns_path_in_claude_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        path = get_dashboard_path()
        assert path.name == "dashboard.html"
        assert path.parent.exists()
        assert "prism" in str(path)
