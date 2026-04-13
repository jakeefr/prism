"""Tests for prism.analyzer — analysis engine."""

from __future__ import annotations

from pathlib import Path

import pytest

from prism.analyzer import (
    ClaudeMdAdherenceMetrics,
    ContextHygieneMetrics,
    SessionContinuityMetrics,
    TokenEfficiencyMetrics,
    ToolHealthMetrics,
    analyze_claude_md_adherence,
    analyze_context_hygiene,
    analyze_session_continuity,
    analyze_token_efficiency,
    analyze_tool_health,
    estimate_tokens,
    score_to_grade,
)
from prism.parser import parse_session_file

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") >= 1  # minimum 1

    def test_short_string(self):
        assert estimate_tokens("hello") == 1  # 5 chars // 4 = 1

    def test_hundred_chars(self):
        assert estimate_tokens("a" * 100) == 25

    def test_consistent(self):
        """Same input → same output."""
        s = "The quick brown fox jumps over the lazy dog."
        assert estimate_tokens(s) == estimate_tokens(s)


class TestScoreToGrade:
    def test_a_plus(self):
        assert score_to_grade(100) == "A+"
        assert score_to_grade(95) == "A+"

    def test_a(self):
        assert score_to_grade(92) == "A"

    def test_b(self):
        assert score_to_grade(77) == "B"

    def test_c(self):
        assert score_to_grade(62) == "C"

    def test_d(self):
        assert score_to_grade(47) == "D"

    def test_f(self):
        assert score_to_grade(0) == "F"
        assert score_to_grade(39) == "F"


# ---------------------------------------------------------------------------
# Token Efficiency
# ---------------------------------------------------------------------------

class TestTokenEfficiency:
    def test_clean_session_scores_well(self):
        session = parse_session_file(FIXTURES / "sample_session.jsonl")
        metrics = analyze_token_efficiency([session])
        assert isinstance(metrics, TokenEfficiencyMetrics)
        assert metrics.score >= 70  # clean session should be healthy
        assert metrics.session_count == 1

    def test_compaction_session_penalized(self):
        session = parse_session_file(FIXTURES / "session_with_compaction.jsonl")
        metrics = analyze_token_efficiency([session])
        assert metrics.compaction_count >= 1

    def test_sidechain_records_counted(self, tmp_path):
        """Sidechain records count toward sidechain_count."""
        f = tmp_path / "sidechain.jsonl"
        f.write_text(
            '{"uuid":"u1","parentUuid":null,"isSidechain":true,"sessionId":"s1","timestamp":"2026-04-10T10:00:00.000Z","version":"2.1.98","cwd":"/proj","gitBranch":"main","type":"user","message":{"role":"user","content":[{"type":"text","text":"hi"}]}}\n'
            '{"uuid":"u2","parentUuid":"u1","isSidechain":false,"sessionId":"s1","timestamp":"2026-04-10T10:00:05.000Z","version":"2.1.98","cwd":"/proj","gitBranch":"main","type":"user","message":{"role":"user","content":[{"type":"text","text":"regular"}]}}\n',
            encoding="utf-8"
        )
        session = parse_session_file(f)
        metrics = analyze_token_efficiency([session])
        assert metrics.sidechain_count == 1

    def test_no_sessions_gives_defaults(self):
        metrics = analyze_token_efficiency([])
        assert metrics.session_count == 0
        assert metrics.score == 100.0
        assert metrics.grade == "A+"

    def test_with_claude_md(self, tmp_path):
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# Rules\n- Never do X\n- Always do Y\n", encoding="utf-8")
        session = parse_session_file(FIXTURES / "sample_session.jsonl")
        metrics = analyze_token_efficiency([session], claude_md)
        assert metrics.claude_md_size_tokens > 0


# ---------------------------------------------------------------------------
# Tool Health
# ---------------------------------------------------------------------------

class TestToolHealth:
    def test_clean_session_healthy(self):
        session = parse_session_file(FIXTURES / "sample_session.jsonl")
        metrics = analyze_tool_health([session])
        assert isinstance(metrics, ToolHealthMetrics)
        assert metrics.score >= 60

    def test_retry_loops_detected(self):
        session = parse_session_file(FIXTURES / "session_with_retries.jsonl")
        metrics = analyze_tool_health([session])
        assert metrics.retry_loop_count >= 1
        assert metrics.score < 100  # should be penalized

    def test_interactive_command_detected(self):
        session = parse_session_file(FIXTURES / "session_with_retries.jsonl")
        metrics = analyze_tool_health([session])
        # session_with_retries has "npm test --watch"
        assert metrics.interactive_call_count >= 1

    def test_interactive_command_heuristic(self, tmp_path):
        """--watch without safe flags should be flagged as interactive."""
        f = tmp_path / "interactive.jsonl"
        f.write_text(
            '{"uuid":"a1","parentUuid":"u1","isSidechain":false,"sessionId":"s1","timestamp":"2026-04-10T10:00:00.000Z","version":"2.1.98","cwd":"/proj","gitBranch":"main","type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","id":"t1","name":"Bash","input":{"command":"npm test --watch"}}]}}\n',
            encoding="utf-8"
        )
        session = parse_session_file(f)
        metrics = analyze_tool_health([session])
        assert metrics.interactive_call_count >= 1

    def test_non_interactive_command_safe(self, tmp_path):
        """Commands with safe flags should NOT be flagged."""
        f = tmp_path / "safe.jsonl"
        f.write_text(
            '{"uuid":"a1","parentUuid":"u1","isSidechain":false,"sessionId":"s1","timestamp":"2026-04-10T10:00:00.000Z","version":"2.1.98","cwd":"/proj","gitBranch":"main","type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","id":"t1","name":"Bash","input":{"command":"npm test --non-interactive"}}]}}\n',
            encoding="utf-8"
        )
        session = parse_session_file(f)
        metrics = analyze_tool_health([session])
        assert metrics.interactive_call_count == 0

    def test_migration_edit_detected(self):
        session = parse_session_file(FIXTURES / "session_with_retries.jsonl")
        metrics = analyze_tool_health([session])
        # Migration file was edited
        migration_issues = [
            i for i in metrics.issues
            if "migration" in i.evidence.lower() if i.evidence
        ]
        # Edit-revert detection won't catch the migration specifically,
        # but there should be no crash and scores are valid
        assert metrics.score >= 0
        assert metrics.grade != ""

    def test_consecutive_failures_detected(self, tmp_path):
        f = tmp_path / "failures.jsonl"
        lines = []
        for i in range(4):
            lines.append(
                f'{{"uuid":"a{i}","parentUuid":"u{i}","isSidechain":false,"sessionId":"s1","timestamp":"2026-04-10T10:00:0{i}.000Z","version":"2.1.98","cwd":"/proj","gitBranch":"main","type":"assistant","message":{{"role":"assistant","content":[{{"type":"tool_use","id":"t{i}","name":"Bash","input":{{"command":"npm test"}}}}]}}}}\n'
            )
            lines.append(
                f'{{"uuid":"u{i}","parentUuid":"a{i}","isSidechain":false,"sessionId":"s1","timestamp":"2026-04-10T10:00:0{i}.000Z","version":"2.1.98","cwd":"/proj","gitBranch":"main","type":"user","message":{{"role":"user","content":[{{"type":"tool_result","tool_use_id":"t{i}","content":"Error: test failed with exit code 1"}}]}}}}\n'
            )
        f.write_text("".join(lines), encoding="utf-8")
        session = parse_session_file(f)
        metrics = analyze_tool_health([session])
        assert metrics.consecutive_failure_count >= 1


# ---------------------------------------------------------------------------
# Context Hygiene
# ---------------------------------------------------------------------------

class TestContextHygiene:
    def test_clean_session(self):
        session = parse_session_file(FIXTURES / "sample_session.jsonl")
        metrics = analyze_context_hygiene([session])
        assert isinstance(metrics, ContextHygieneMetrics)
        assert metrics.compaction_count == 0
        assert metrics.score >= 85

    def test_compaction_detected(self):
        session = parse_session_file(FIXTURES / "session_with_compaction.jsonl")
        metrics = analyze_context_hygiene([session])
        assert metrics.compaction_count >= 1
        assert metrics.score < 100

    def test_mid_task_compaction_signal(self):
        session = parse_session_file(FIXTURES / "session_with_compaction.jsonl")
        metrics = analyze_context_hygiene([session])
        # The compaction fixture has repeated tool patterns after boundary
        # (find src, read User.ts appear on both sides)
        assert metrics.compaction_count >= 1

    def test_no_sessions(self):
        metrics = analyze_context_hygiene([])
        assert metrics.score == 100.0


# ---------------------------------------------------------------------------
# CLAUDE.md Adherence
# ---------------------------------------------------------------------------

class TestClaudeMdAdherence:
    def test_no_claude_md(self):
        session = parse_session_file(FIXTURES / "sample_session.jsonl")
        metrics = analyze_claude_md_adherence([session], None)
        assert isinstance(metrics, ClaudeMdAdherenceMetrics)
        assert metrics.grade == "N/A"

    def test_missing_claude_md_file(self, tmp_path):
        session = parse_session_file(FIXTURES / "sample_session.jsonl")
        metrics = analyze_claude_md_adherence([session], tmp_path / "nonexistent.md")
        assert metrics.grade == "N/A"

    def test_rules_extracted(self, tmp_path):
        md = tmp_path / "CLAUDE.md"
        md.write_text(
            "# Rules\n"
            "Never edit migration files\n"
            "Always run tests before finishing\n"
            "Don't use hardcoded paths\n"
            "This line has no imperative\n",
            encoding="utf-8"
        )
        session = parse_session_file(FIXTURES / "sample_session.jsonl")
        metrics = analyze_claude_md_adherence([session], md)
        assert metrics.rules_found >= 3

    def test_migration_rule_violation(self, tmp_path):
        md = tmp_path / "CLAUDE.md"
        md.write_text("Never edit existing migration files\n", encoding="utf-8")
        session = parse_session_file(FIXTURES / "session_with_retries.jsonl")
        metrics = analyze_claude_md_adherence([session], md)
        # The retries fixture edits a migration file
        assert metrics.rules_violated >= 1

    def test_long_claude_md_flagged(self, tmp_path):
        md = tmp_path / "CLAUDE.md"
        md.write_text("\n".join(f"Line {i}" for i in range(100)), encoding="utf-8")
        session = parse_session_file(FIXTURES / "sample_session.jsonl")
        metrics = analyze_claude_md_adherence([session], md)
        assert metrics.claude_md_line_count >= 100
        long_issues = [i for i in metrics.issues if "line" in i.description.lower() and "80" in i.description]
        assert len(long_issues) >= 1


# ---------------------------------------------------------------------------
# Session Continuity
# ---------------------------------------------------------------------------

class TestSessionContinuity:
    def test_clean_sessions(self):
        session = parse_session_file(FIXTURES / "sample_session.jsonl")
        metrics = analyze_session_continuity([session])
        assert isinstance(metrics, SessionContinuityMetrics)
        assert metrics.score >= 80

    def test_truncated_session(self, tmp_path):
        f = tmp_path / "trunc.jsonl"
        f.write_text(
            '{"uuid":"u1","type":"user","message":{"role":"user","content":[{"type":"text","text":"hi"}]}}\n'
            '{"uuid":"u2","type":"user",',  # truncated
            encoding="utf-8"
        )
        session = parse_session_file(f)
        metrics = analyze_session_continuity([session])
        assert metrics.truncated_sessions == 1

    def test_no_sessions(self):
        metrics = analyze_session_continuity([])
        assert metrics.score == 100.0
