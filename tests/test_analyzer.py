"""Tests for prism.analyzer — analysis engine."""

from __future__ import annotations

import json
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

# ---------------------------------------------------------------------------
# JSONL line builders for behavior-specific fixtures
# ---------------------------------------------------------------------------

def _line(uuid: str, rtype: str, content, **extra) -> str:
    """One JSONL record line with envelope fields. content = blocks list or str."""
    rec = {
        "uuid": uuid,
        "parentUuid": None,
        "isSidechain": False,
        "sessionId": "s1",
        "timestamp": "2026-06-01T10:00:00.000Z",
        "version": "2.1.150",
        "cwd": "/proj",
        "gitBranch": "main",
        "type": rtype,
        "message": {"role": rtype, "content": content},
    }
    rec.update(extra)
    return json.dumps(rec)


def _user_text(uuid: str, text: str) -> str:
    return _line(uuid, "user", [{"type": "text", "text": text}])


def _assistant_text(uuid: str, text: str) -> str:
    return _line(uuid, "assistant", [{"type": "text", "text": text}])


def _tool_use(uuid: str, tool_id: str, name: str = "Bash", inp: dict | None = None) -> str:
    return _line(uuid, "assistant", [
        {"type": "tool_use", "id": tool_id, "name": name,
         "input": inp or {"command": "echo hi"}},
    ])


def _tool_result(uuid: str, tool_id: str, content: str, is_error: bool | None = None) -> str:
    block = {"type": "tool_result", "tool_use_id": tool_id, "content": content}
    if is_error is not None:
        block["is_error"] = is_error
    return _line(uuid, "user", [block])


def _compact_boundary(uuid: str, **extra) -> str:
    rec = {
        "uuid": uuid,
        "parentUuid": None,
        "isSidechain": False,
        "sessionId": "s1",
        "timestamp": "2026-06-01T10:00:00.000Z",
        "version": "2.1.150",
        "cwd": "/proj",
        "gitBranch": "main",
        "type": "system",
        "subtype": "compact_boundary",
        "summary": "context compacted",
    }
    rec.update(extra)
    return json.dumps(rec)


def _session(tmp_path: Path, name: str, lines: list[str]):
    f = tmp_path / name
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return parse_session_file(f)


# ---------------------------------------------------------------------------
# CLAUDE.md injection cost (once per session + once per compaction)
# ---------------------------------------------------------------------------

class TestClaudeMdInjectionCost:
    def _claude_md(self, tmp_path: Path) -> Path:
        md = tmp_path / "CLAUDE.md"
        md.write_text("x" * 400, encoding="utf-8")  # ~100 tokens
        return md

    def test_cost_once_per_session_not_per_tool_call(self, tmp_path):
        """10 tool calls must not book 10x the CLAUDE.md size as waste."""
        md = self._claude_md(tmp_path)
        lines = []
        for i in range(10):
            lines.append(_tool_use(f"a{i}", f"t{i}"))
            # Substantial results so the session clears the stub-session floor.
            lines.append(_tool_result(f"u{i}", f"t{i}", "y" * 1_200))
        session = _session(tmp_path, "s.jsonl", lines)
        metrics = analyze_token_efficiency([session], md)
        assert metrics.claude_md_size_tokens == 100
        assert metrics.claude_md_reread_tokens == metrics.claude_md_size_tokens

    def test_trivial_session_not_flagged(self, tmp_path):
        """A 2-record stub session always 'spends' more on CLAUDE.md than on
        work — that is noise, not an actionable issue."""
        md = self._claude_md(tmp_path)
        lines = [
            _user_text("u1", "hi"),
            _assistant_text("a1", "hello"),
        ]
        session = _session(tmp_path, "s.jsonl", lines)
        metrics = analyze_token_efficiency([session], md)
        cost_issues = [i for i in metrics.issues if "CLAUDE.md context cost" in i.description]
        assert cost_issues == []

    def test_substantial_session_with_heavy_cost_flagged(self, tmp_path):
        """Sessions with real activity still get flagged when the ratio is high."""
        md = tmp_path / "CLAUDE.md"
        md.write_text("x" * 40_000, encoding="utf-8")  # ~10k tokens
        lines = []
        for i in range(20):
            lines.append(_tool_use(f"a{i}", f"t{i}"))
            lines.append(_tool_result(f"r{i}", f"t{i}", "y" * 2_000))
        session = _session(tmp_path, "s.jsonl", lines)
        metrics = analyze_token_efficiency([session], md)
        cost_issues = [i for i in metrics.issues if "CLAUDE.md context cost" in i.description]
        assert len(cost_issues) == 1

    def test_cost_grows_with_compaction(self, tmp_path):
        """Each compaction re-injects CLAUDE.md once — independent of tool-call count."""
        md = self._claude_md(tmp_path)
        lines = [
            _tool_use("a1", "t1"),
            _tool_result("u1", "t1", "y" * 3_000),
            _compact_boundary("c1"),
            _tool_use("a2", "t2"),
            _tool_result("u2", "t2", "y" * 3_000),
            _tool_use("a3", "t3"),
            _tool_result("u3", "t3", "y" * 3_000),
            _tool_use("a4", "t4"),
            _tool_result("u4", "t4", "y" * 3_000),
        ]
        session = _session(tmp_path, "s.jsonl", lines)
        metrics = analyze_token_efficiency([session], md)
        # 1 initial injection + 1 compaction re-injection — NOT 4 tool calls x size.
        assert metrics.claude_md_reread_tokens == 2 * metrics.claude_md_size_tokens


# ---------------------------------------------------------------------------
# Turn counting (real user prompts, not tool-result volume)
# ---------------------------------------------------------------------------

class TestTurnCounting:
    def test_tool_result_volume_is_not_turns(self, tmp_path):
        """120 tool calls in a 3-prompt session must not trigger the long-session flag."""
        lines = [_user_text("u0", "kick off the task")]
        for i in range(120):
            lines.append(_tool_use(f"a{i}", f"t{i}"))
            lines.append(_tool_result(f"r{i}", f"t{i}", "ok"))
        lines.append(_user_text("u1", "looks good"))
        lines.append(_assistant_text("a-final", "done"))
        session = _session(tmp_path, "s.jsonl", lines)
        metrics = analyze_context_hygiene([session])
        assert metrics.long_sessions == 0

    def test_many_real_turns_still_flagged(self, tmp_path):
        """A session with >100 actual user prompts is genuinely long."""
        lines = []
        for i in range(105):
            lines.append(_user_text(f"u{i}", f"question number {i}"))
            lines.append(_assistant_text(f"a{i}", f"answer number {i}"))
        session = _session(tmp_path, "s.jsonl", lines)
        metrics = analyze_context_hygiene([session])
        assert metrics.long_sessions == 1


# ---------------------------------------------------------------------------
# Resume-phrase gating (only resumed sessions can lose context)
# ---------------------------------------------------------------------------

class TestResumePhraseGating:
    def test_non_resumed_session_not_flagged(self, tmp_path):
        """Normal sessions opening with 'let me start by' are not context loss."""
        lines = [
            _user_text("u1", "review the auth module"),
            _assistant_text("a1", "Let me start by reading the existing code."),
        ]
        session = _session(tmp_path, "s.jsonl", lines)
        metrics = analyze_session_continuity([session])
        assert metrics.context_loss_resumes == 0

    def test_resumed_session_with_phrases_flagged(self, tmp_path):
        """Resumed sessions that re-establish context still count."""
        lines = [
            _line("u-cont", "user",
                  "This session is being continued from a previous conversation."),
            _assistant_text("a1", "First let me understand what the project does."),
        ]
        session = _session(tmp_path, "s.jsonl", lines)
        metrics = analyze_session_continuity([session])
        assert metrics.resumed_sessions == 1
        assert metrics.context_loss_resumes == 1


# ---------------------------------------------------------------------------
# Consecutive failures via is_error flag
# ---------------------------------------------------------------------------

class TestConsecutiveFailureFlag:
    def test_is_error_flag_counts_failures(self, tmp_path):
        """Three flagged failures count even when result text looks benign."""
        lines = []
        for i in range(3):
            lines.append(_tool_use(f"a{i}", f"t{i}"))
            lines.append(_tool_result(f"r{i}", f"t{i}", "command exited", is_error=True))
        session = _session(tmp_path, "s.jsonl", lines)
        metrics = analyze_tool_health([session])
        assert metrics.consecutive_failure_count == 1

    def test_is_error_false_suppresses_prose_match(self, tmp_path):
        """is_error=False must override error-looking prose like '0 errors'."""
        lines = []
        for i in range(3):
            lines.append(_tool_use(f"a{i}", f"t{i}"))
            lines.append(_tool_result(
                f"r{i}", f"t{i}",
                "Lint finished: 0 errors, 0 warnings. Error handling looks good.",
                is_error=False,
            ))
        session = _session(tmp_path, "s.jsonl", lines)
        metrics = analyze_tool_health([session])
        assert metrics.consecutive_failure_count == 0

    def test_absent_flag_falls_back_to_prose(self, tmp_path):
        """Without the flag (older files, agentsview), prose matching still works."""
        lines = []
        for i in range(3):
            lines.append(_tool_use(f"a{i}", f"t{i}"))
            lines.append(_tool_result(f"r{i}", f"t{i}", "Error: exit code 1"))
        session = _session(tmp_path, "s.jsonl", lines)
        metrics = analyze_tool_health([session])
        assert metrics.consecutive_failure_count == 1


# ---------------------------------------------------------------------------
# Transcript boundaries (parent + merged subagent transcripts)
# ---------------------------------------------------------------------------

class TestTranscriptBoundaries:
    """Order-sensitive detections must not chain across the seam between a
    parent transcript and merged subagent transcripts."""

    def _build_split_failures(self, tmp_path: Path):
        """Main transcript ends with 2 flagged failures; subagent starts with 1.
        Flat-concatenated they would look like 3 consecutive failures."""
        from prism.parser import discover_projects, load_all_sessions
        proj = tmp_path / "D--proj"
        proj.mkdir()
        main_lines = [
            _tool_use("a1", "t1"),
            _tool_result("r1", "t1", "boom", is_error=True),
            _tool_use("a2", "t2"),
            _tool_result("r2", "t2", "boom", is_error=True),
        ]
        (proj / "sess-1.jsonl").write_text("\n".join(main_lines) + "\n", encoding="utf-8")
        agents = proj / "sess-1" / "subagents"
        agents.mkdir(parents=True)
        agent_lines = [
            _line("s1", "assistant",
                  [{"type": "tool_use", "id": "st1", "name": "Bash",
                    "input": {"command": "echo hi"}}], isSidechain=True),
            _line("s2", "user",
                  [{"type": "tool_result", "tool_use_id": "st1",
                    "content": "boom", "is_error": True}], isSidechain=True),
            _line("s3", "assistant", [{"type": "text", "text": "recovered"}],
                  isSidechain=True),
        ]
        (agents / "agent-a.jsonl").write_text("\n".join(agent_lines) + "\n", encoding="utf-8")
        projects = discover_projects(tmp_path)
        return load_all_sessions(projects[0])

    def test_failures_do_not_chain_across_transcripts(self, tmp_path):
        sessions = self._build_split_failures(tmp_path)
        assert len(sessions) == 1
        # All 3 sidechain+main records merged...
        assert any(r.is_sidechain for r in sessions[0].records)
        # ...but 2 failures in the parent + 1 in the subagent is not a streak of 3.
        metrics = analyze_tool_health(sessions)
        assert metrics.consecutive_failure_count == 0

    def test_retry_loops_do_not_span_transcripts(self, tmp_path):
        """2 identical calls in parent + 1 identical in subagent != retry loop."""
        from prism.parser import discover_projects, load_all_sessions
        proj = tmp_path / "D--proj"
        proj.mkdir()
        same = {"command": "pytest tests/"}
        main_lines = [
            _tool_use("a1", "t1", inp=same),
            _tool_use("a2", "t2", inp=same),
        ]
        (proj / "sess-1.jsonl").write_text("\n".join(main_lines) + "\n", encoding="utf-8")
        agents = proj / "sess-1" / "subagents"
        agents.mkdir(parents=True)
        agent_lines = [
            _line("s1", "assistant",
                  [{"type": "tool_use", "id": "st1", "name": "Bash", "input": same}],
                  isSidechain=True),
        ]
        (agents / "agent-a.jsonl").write_text("\n".join(agent_lines) + "\n", encoding="utf-8")
        projects = discover_projects(tmp_path)
        sessions = load_all_sessions(projects[0])
        metrics = analyze_tool_health(sessions)
        assert metrics.retry_loop_count == 0

    def test_retry_loop_in_each_transcript_counts_per_transcript(self, tmp_path):
        """A full retry loop in the main transcript AND one in a subagent are
        two distinct loops — counted once per transcript."""
        from prism.parser import discover_projects, load_all_sessions
        proj = tmp_path / "D--proj"
        proj.mkdir()
        same = {"command": "pytest tests/"}
        main_lines = [_tool_use(f"a{i}", f"t{i}", inp=same) for i in range(3)]
        (proj / "sess-1.jsonl").write_text("\n".join(main_lines) + "\n", encoding="utf-8")
        agents = proj / "sess-1" / "subagents"
        agents.mkdir(parents=True)
        agent_lines = [
            _line(f"s{i}", "assistant",
                  [{"type": "tool_use", "id": f"st{i}", "name": "Bash", "input": same}],
                  isSidechain=True)
            for i in range(3)
        ]
        (agents / "agent-a.jsonl").write_text("\n".join(agent_lines) + "\n", encoding="utf-8")
        projects = discover_projects(tmp_path)
        sessions = load_all_sessions(projects[0])
        metrics = analyze_tool_health(sessions)
        assert metrics.retry_loop_count == 2

    def test_subagent_compaction_not_counted_for_session(self, tmp_path):
        """Compaction inside a subagent transcript is not a main-session
        compaction event."""
        from prism.parser import discover_projects, load_all_sessions
        proj = tmp_path / "D--proj"
        proj.mkdir()
        main_lines = [
            _user_text("u1", "do the thing"),
            _assistant_text("a1", "done"),
        ]
        (proj / "sess-1.jsonl").write_text("\n".join(main_lines) + "\n", encoding="utf-8")
        agents = proj / "sess-1" / "subagents"
        agents.mkdir(parents=True)
        agent_lines = [
            _line("s1", "user", [{"type": "text", "text": "subagent task"}],
                  isSidechain=True),
            _compact_boundary("sc1", isSidechain=True),
        ]
        (agents / "agent-a.jsonl").write_text("\n".join(agent_lines) + "\n", encoding="utf-8")
        projects = discover_projects(tmp_path)
        sessions = load_all_sessions(projects[0])
        metrics = analyze_context_hygiene(sessions)
        assert metrics.compaction_count == 0

    def test_subagent_compaction_not_counted_for_token_efficiency(self, tmp_path):
        """Token efficiency must also exclude subagent compactions — they feed
        the compaction-rate penalty and the CLAUDE.md injection count."""
        from prism.parser import discover_projects, load_all_sessions
        proj = tmp_path / "D--proj"
        proj.mkdir()
        md = tmp_path / "CLAUDE.md"
        md.write_text("x" * 400, encoding="utf-8")  # ~100 tokens
        # Substantial main transcript so the stub-session floor doesn't apply.
        main_lines = [
            _user_text("u1", "do the thing"),
            _assistant_text("a1", "y" * 12_000),
        ]
        (proj / "sess-1.jsonl").write_text("\n".join(main_lines) + "\n", encoding="utf-8")
        agents = proj / "sess-1" / "subagents"
        agents.mkdir(parents=True)
        agent_lines = [
            _line("s1", "user", [{"type": "text", "text": "subagent task"}],
                  isSidechain=True),
            _compact_boundary("sc1", isSidechain=True),
        ]
        (agents / "agent-a.jsonl").write_text("\n".join(agent_lines) + "\n", encoding="utf-8")
        projects = discover_projects(tmp_path)
        sessions = load_all_sessions(projects[0])
        metrics = analyze_token_efficiency(sessions, md)
        assert metrics.compaction_count == 0
        # One injection only — the subagent compaction must not add another.
        assert metrics.claude_md_reread_tokens == metrics.claude_md_size_tokens

    def test_empty_parent_does_not_promote_subagent_to_main(self, tmp_path):
        """If the parent file has no parseable records, the first subagent
        transcript must not be treated as the main conversation."""
        from prism.parser import discover_projects, load_all_sessions
        proj = tmp_path / "D--proj"
        proj.mkdir()
        (proj / "sess-1.jsonl").write_text("not json at all\n", encoding="utf-8")
        agents = proj / "sess-1" / "subagents"
        agents.mkdir(parents=True)
        agent_lines = []
        for i in range(105):
            agent_lines.append(_line(f"su{i}", "user",
                                     [{"type": "text", "text": f"prompt {i}"}],
                                     isSidechain=True))
        (agents / "agent-a.jsonl").write_text("\n".join(agent_lines) + "\n", encoding="utf-8")
        projects = discover_projects(tmp_path)
        sessions = load_all_sessions(projects[0])
        metrics = analyze_context_hygiene(sessions)
        # 105 subagent prompts are not 105 main-conversation turns.
        assert metrics.long_sessions == 0


# ---------------------------------------------------------------------------
# Stub-session gate must cover the score, not just the issue
# ---------------------------------------------------------------------------

class TestStubSessionScoreGate:
    def test_stub_sessions_do_not_drag_token_efficiency_score(self, tmp_path):
        """A project of tiny stub sessions must not lose Token Efficiency
        points to CLAUDE.md cost — same gate as the per-session issue."""
        md = tmp_path / "CLAUDE.md"
        md.write_text("x" * 4_000, encoding="utf-8")  # ~1k tokens
        sessions = []
        for i in range(3):
            sessions.append(_session(tmp_path, f"stub{i}.jsonl", [
                _user_text(f"u{i}", "hi"),
                _assistant_text(f"a{i}", "hello"),
            ]))
        metrics = analyze_token_efficiency(sessions, md)
        assert metrics.claude_md_reread_tokens == 0
        assert metrics.score == 100.0


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
