"""Tests for prism.advisor — recommendation generator."""

from __future__ import annotations

from pathlib import Path

import pytest

from prism.advisor import (
    AdvisorReport,
    Recommendation,
    _recommend_attention_curve,
    apply_advice,
    format_advice_plain,
    generate_advice,
)
from prism.analyzer import analyze_project
from prism.parser import ProjectInfo, discover_projects, parse_session_file

FIXTURES = Path(__file__).parent / "fixtures"


def _make_project(tmp_path: Path, session_files: list[Path]) -> ProjectInfo:
    """Create a ProjectInfo from a list of session file paths."""
    proj_dir = tmp_path / "proj"
    proj_dir.mkdir(exist_ok=True)
    # Symlink or copy fixture files into proj_dir
    for sf in session_files:
        dest = proj_dir / sf.name
        dest.write_bytes(sf.read_bytes())
    return ProjectInfo(
        encoded_name="-home-user-proj",
        project_dir=proj_dir,
        session_files=[proj_dir / sf.name for sf in session_files],
    )


class TestGenerateAdvice:
    def test_clean_project_no_advice(self, tmp_path):
        """A healthy project should produce no or minimal advice."""
        project = _make_project(tmp_path, [FIXTURES / "sample_session.jsonl"])
        report = analyze_project(project)
        advice = generate_advice(report)
        assert isinstance(advice, AdvisorReport)
        # May or may not have recommendations — just shouldn't crash

    def test_retry_project_gets_advice(self, tmp_path):
        """Project with retry loops should get non-interactive flag recommendation."""
        project = _make_project(tmp_path, [FIXTURES / "session_with_retries.jsonl"])
        report = analyze_project(project)
        advice = generate_advice(report)
        assert isinstance(advice, AdvisorReport)
        # Should have at least one ADD recommendation for interactive flags
        add_recs = [r for r in advice.recommendations if r.action == "ADD"]
        # The retry fixture has interactive commands and retry loops
        assert len(add_recs) >= 1

    def test_migration_violation_gets_rule(self, tmp_path):
        """Project with migration file edits should get migration rule recommendation."""
        project = _make_project(tmp_path, [FIXTURES / "session_with_retries.jsonl"])
        report = analyze_project(project)
        advice = generate_advice(report)
        migration_recs = [
            r for r in advice.recommendations
            if "migration" in r.content.lower()
        ]
        assert len(migration_recs) >= 1

    def test_long_claude_md_gets_trim(self, tmp_path):
        """Project with long CLAUDE.md should get TRIM recommendation."""
        md = tmp_path / "CLAUDE.md"
        md.write_text("\n".join(f"Line {i}: some rule here" for i in range(100)), encoding="utf-8")
        project = _make_project(tmp_path, [FIXTURES / "sample_session.jsonl"])
        report = analyze_project(project, claude_md_path=md)
        advice = generate_advice(report, claude_md_path=md)
        trim_recs = [r for r in advice.recommendations if r.action == "TRIM"]
        assert len(trim_recs) >= 1

    def test_rule_violation_gets_warn(self, tmp_path):
        """Violated CLAUDE.md rules generate WARN recommendations."""
        md = tmp_path / "CLAUDE.md"
        md.write_text("Never edit existing migration files\n", encoding="utf-8")
        project = _make_project(tmp_path, [FIXTURES / "session_with_retries.jsonl"])
        report = analyze_project(project, claude_md_path=md)
        advice = generate_advice(report, claude_md_path=md)
        warn_recs = [r for r in advice.recommendations if r.action in ("WARN", "ADD")]
        assert len(warn_recs) >= 1

    def test_recommendations_sorted_by_impact(self, tmp_path):
        """High impact recommendations come before low impact."""
        project = _make_project(tmp_path, [FIXTURES / "session_with_retries.jsonl"])
        report = analyze_project(project)
        advice = generate_advice(report)
        if len(advice.recommendations) >= 2:
            impact_order = {"High": 0, "Medium": 1, "Low": 2}
            impacts = [impact_order.get(r.impact, 3) for r in advice.recommendations]
            assert impacts == sorted(impacts), "Recommendations not sorted by impact"

    def test_has_actionable_flag(self, tmp_path):
        """has_actionable is True when there are recommendations."""
        project = _make_project(tmp_path, [FIXTURES / "session_with_retries.jsonl"])
        report = analyze_project(project)
        advice = generate_advice(report)
        if advice.recommendations:
            assert advice.has_actionable is True
        else:
            assert advice.has_actionable is False


class TestFormatAdvice:
    def test_format_plain_no_recommendations(self, tmp_path):
        advice = AdvisorReport(project_name="test", recommendations=[], has_actionable=False)
        output = format_advice_plain(advice)
        assert "No recommendations" in output
        assert "PRISM ADVISOR" in output

    def test_format_plain_with_recommendation(self):
        rec = Recommendation(
            action="ADD",
            impact="High",
            rationale="14 retry loops across 6 sessions",
            content="Always use non-interactive flags: --yes, -y",
        )
        advice = AdvisorReport(
            project_name="test",
            recommendations=[rec],
            has_actionable=True,
        )
        output = format_advice_plain(advice)
        assert "ADD" in output
        assert "High" in output
        assert "non-interactive" in output

    def test_format_plain_action_types(self):
        recs = [
            Recommendation(action="ADD", impact="High", rationale="r1", content="c1"),
            Recommendation(action="TRIM", impact="Medium", rationale="r2", content="c2"),
            Recommendation(action="WARN", impact="Low", rationale="r3", content="c3"),
            Recommendation(action="RESTRUCTURE", impact="Medium", rationale="r4", content="c4"),
        ]
        advice = AdvisorReport(project_name="test", recommendations=recs, has_actionable=True)
        output = format_advice_plain(advice)
        for action in ("ADD", "TRIM", "WARN", "RESTRUCTURE"):
            assert action in output


class TestApplyAdvice:
    def test_apply_adds_rules_section(self, tmp_path):
        md = tmp_path / "CLAUDE.md"
        md.write_text("# Project\n\nSome content.\n", encoding="utf-8")
        rec = Recommendation(
            action="ADD",
            impact="High",
            rationale="test",
            content="Always use non-interactive flags: --yes",
        )
        advice = AdvisorReport(
            project_name="test",
            recommendations=[rec],
            has_actionable=True,
        )
        result = apply_advice(advice, md, confirm=False)
        assert result is True
        content = md.read_text(encoding="utf-8")
        assert "Always use non-interactive flags" in content

    def test_apply_to_existing_rules_section(self, tmp_path):
        md = tmp_path / "CLAUDE.md"
        md.write_text("# Project\n\n## Rules\n- Existing rule\n", encoding="utf-8")
        rec = Recommendation(
            action="ADD",
            impact="High",
            rationale="test",
            content="Never edit migration files",
        )
        advice = AdvisorReport(
            project_name="test",
            recommendations=[rec],
            has_actionable=True,
        )
        result = apply_advice(advice, md, confirm=False)
        assert result is True
        content = md.read_text(encoding="utf-8")
        assert "Never edit migration files" in content
        assert "Existing rule" in content  # original content preserved

    def test_apply_no_add_recommendations_returns_false(self, tmp_path):
        md = tmp_path / "CLAUDE.md"
        md.write_text("# Project\n", encoding="utf-8")
        rec = Recommendation(
            action="WARN",
            impact="High",
            rationale="test",
            content="Some warning",
        )
        advice = AdvisorReport(
            project_name="test",
            recommendations=[rec],
            has_actionable=True,
        )
        result = apply_advice(advice, md, confirm=False)
        assert result is False

    def test_apply_no_duplicate_rules(self, tmp_path):
        rule = "Always use non-interactive flags: --yes"
        md = tmp_path / "CLAUDE.md"
        md.write_text(f"## Rules\n- {rule}\n", encoding="utf-8")
        rec = Recommendation(
            action="ADD",
            impact="High",
            rationale="test",
            content=rule,
        )
        advice = AdvisorReport(
            project_name="test",
            recommendations=[rec],
            has_actionable=True,
        )
        result = apply_advice(advice, md, confirm=False)
        assert result is False  # rule already present, nothing to add

class TestAttentionCurve:
    def test_short_file_no_recommendation(self, tmp_path):
        """File with <20 lines should never generate a recommendation."""
        md = tmp_path / "CLAUDE.md"
        md.write_text("\n".join(["NEVER do X", "ALWAYS do Y"] * 5), encoding="utf-8")
        # 10 lines — below the 20-line threshold
        project = _make_project(tmp_path, [FIXTURES / "sample_session.jsonl"])
        report = analyze_project(project, claude_md_path=md)
        recs = _recommend_attention_curve(report, md)
        assert recs == []

    def test_critical_rule_in_danger_zone_generates_recommendation(self, tmp_path):
        """Critical rule in middle 55% of file should trigger a RESTRUCTURE rec."""
        md = tmp_path / "CLAUDE.md"
        # 40 lines total. danger_start=8, danger_end=30.
        # Put a NEVER rule at line 20 (index 19) — firmly in the danger zone.
        lines = [f"# line {i}" for i in range(40)]
        lines[19] = "NEVER edit migration files directly"
        md.write_text("\n".join(lines), encoding="utf-8")
        project = _make_project(tmp_path, [FIXTURES / "sample_session.jsonl"])
        report = analyze_project(project, claude_md_path=md)
        recs = _recommend_attention_curve(report, md)
        assert len(recs) == 1
        assert recs[0].action == "RESTRUCTURE"
        assert "NEVER" in recs[0].content or "migration" in recs[0].content.lower()
        assert "attention" in recs[0].rationale.lower() or "dead zone" in recs[0].rationale.lower()

    def test_critical_rules_at_top_no_recommendation(self, tmp_path):
        """Critical rules in the first 20% of the file should not be flagged."""
        md = tmp_path / "CLAUDE.md"
        # 40 lines total. danger_start=8.
        # Put NEVER at line 2 (index 1) — safely in the top 20%.
        lines = [f"# line {i}" for i in range(40)]
        lines[1] = "NEVER edit migration files directly"
        md.write_text("\n".join(lines), encoding="utf-8")
        project = _make_project(tmp_path, [FIXTURES / "sample_session.jsonl"])
        report = analyze_project(project, claude_md_path=md)
        recs = _recommend_attention_curve(report, md)
        assert recs == []

    def test_attention_curve_integrated_into_generate_advice(self, tmp_path):
        """generate_advice should include attention curve recs when applicable."""
        md = tmp_path / "CLAUDE.md"
        lines = [f"# line {i}" for i in range(40)]
        lines[19] = "NEVER edit migration files directly"
        md.write_text("\n".join(lines), encoding="utf-8")
        project = _make_project(tmp_path, [FIXTURES / "sample_session.jsonl"])
        report = analyze_project(project, claude_md_path=md)
        advice = generate_advice(report, claude_md_path=md)
        restructure_recs = [r for r in advice.recommendations if r.action == "RESTRUCTURE"]
        # At least one RESTRUCTURE from attention curve
        assert any("attention" in r.rationale.lower() or "dead zone" in r.rationale.lower()
                   for r in restructure_recs)


class TestApplyAdviceExtra:
    def test_apply_creates_content_from_scratch(self, tmp_path):
        md = tmp_path / "CLAUDE.md"
        # No existing file
        rec = Recommendation(
            action="ADD",
            impact="High",
            rationale="test",
            content="Never edit migration files",
        )
        advice = AdvisorReport(
            project_name="test",
            recommendations=[rec],
            has_actionable=True,
        )
        result = apply_advice(advice, md, confirm=False)
        assert result is True
        content = md.read_text(encoding="utf-8")
        assert "Never edit migration files" in content
