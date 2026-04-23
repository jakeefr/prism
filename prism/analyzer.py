"""Core analysis engine for PRISM.

Takes parsed session records and computes health metrics.
No I/O here — all analysis is pure computation on ParseResult objects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from prism.parser import (
    AssistantRecord,
    ContentBlock,
    ParseResult,
    ProjectInfo,
    SessionRecord,
    SystemRecord,
    UserRecord,
    load_all_sessions,
    parse_session_file,
)


# ---------------------------------------------------------------------------
# Token estimation helper (chars ÷ 4 heuristic, consistent across all calls)
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """Estimate token count from a string using chars/4 heuristic."""
    return max(1, len(text) // 4)


def estimate_record_tokens(record: SessionRecord) -> int:
    """Estimate the total token cost of a session record."""
    total = 0
    if isinstance(record, (UserRecord, AssistantRecord)):
        for block in record.content:
            if block.text:
                total += estimate_tokens(block.text)
            if block.thinking:
                total += estimate_tokens(block.thinking)
            if block.tool_input:
                total += estimate_tokens(str(block.tool_input))
            if block.tool_content:
                total += estimate_tokens(str(block.tool_content))
    elif isinstance(record, SystemRecord):
        if record.summary:
            total += estimate_tokens(record.summary)
    return max(total, 10)  # minimum 10 tokens per record


# ---------------------------------------------------------------------------
# Letter grade assignment
# ---------------------------------------------------------------------------

_GRADE_THRESHOLDS = [
    (95, "A+"), (90, "A"), (85, "A-"),
    (80, "B+"), (75, "B"), (70, "B-"),
    (65, "C+"), (60, "C"), (55, "C-"),
    (50, "D+"), (45, "D"), (40, "D-"),
]


def score_to_grade(score: float) -> str:
    """Convert a 0-100 float score to a letter grade with +/- modifiers."""
    for threshold, grade in _GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return "F"


# ---------------------------------------------------------------------------
# Issue dataclass
# ---------------------------------------------------------------------------

@dataclass
class Issue:
    """A detected problem in a session or project."""
    severity: str  # "high" | "medium" | "low"
    category: str  # which score dimension
    description: str
    session_id: str = ""
    evidence: str = ""
    count: int = 1


# ---------------------------------------------------------------------------
# 1. Token Efficiency Score
# ---------------------------------------------------------------------------

@dataclass
class TokenEfficiencyMetrics:
    session_count: int = 0
    total_tokens: int = 0
    compaction_count: int = 0
    sidechain_count: int = 0
    total_records: int = 0
    claude_md_reread_tokens: int = 0
    claude_md_size_tokens: int = 0
    issues: list[Issue] = field(default_factory=list)
    score: float = 100.0
    grade: str = "A"


def analyze_token_efficiency(
    sessions: list[ParseResult],
    claude_md_path: Path | None = None,
) -> TokenEfficiencyMetrics:
    m = TokenEfficiencyMetrics()
    m.session_count = len(sessions)

    # Estimate CLAUDE.md token cost
    if claude_md_path and claude_md_path.exists():
        try:
            text = claude_md_path.read_text(encoding="utf-8", errors="replace")
            m.claude_md_size_tokens = estimate_tokens(text)
        except OSError:
            pass

    for session in sessions:
        session_tokens = 0
        tool_call_count = 0

        for record in session.records:
            rt = estimate_record_tokens(record)
            session_tokens += rt
            m.total_records += 1

            if record.is_sidechain:
                m.sidechain_count += 1

            if isinstance(record, SystemRecord) and record.subtype == "compact_boundary":
                m.compaction_count += 1

            if isinstance(record, AssistantRecord):
                for block in record.content:
                    if block.type == "tool_use":
                        tool_call_count += 1

        m.total_tokens += session_tokens

        # CLAUDE.md re-read cost estimation
        if m.claude_md_size_tokens > 0 and tool_call_count > 0:
            reread_cost = tool_call_count * m.claude_md_size_tokens
            m.claude_md_reread_tokens += reread_cost
            if session_tokens > 0 and reread_cost / session_tokens > 0.15:
                m.issues.append(Issue(
                    severity="high",
                    category="token_efficiency",
                    description=f"CLAUDE.md re-reads consume >{int(reread_cost/session_tokens*100)}% of session tokens",
                    session_id=session.records[0].session_id if session.records else "",
                    count=tool_call_count,
                ))

        # Compaction warning (more than 1 per session)
        session_compactions = sum(
            1 for r in session.records
            if isinstance(r, SystemRecord) and r.subtype == "compact_boundary"
        )
        if session_compactions > 1:
            m.issues.append(Issue(
                severity="medium",
                category="token_efficiency",
                description=f"Session has {session_compactions} compaction boundaries (>1 is a warning)",
                session_id=session.records[0].session_id if session.records else "",
                count=session_compactions,
            ))

    # Score calculation
    score = 100.0

    # Penalize high compaction rate
    if m.session_count > 0:
        compaction_rate = m.compaction_count / m.session_count
        if compaction_rate > 2:
            score -= 30
        elif compaction_rate > 1:
            score -= 15
        elif compaction_rate > 0.5:
            score -= 8

    # Penalize high sidechain ratio
    if m.total_records > 0:
        sidechain_ratio = m.sidechain_count / m.total_records
        if sidechain_ratio > 0.3:
            score -= 20
        elif sidechain_ratio > 0.1:
            score -= 10

    # Penalize CLAUDE.md token waste
    if m.total_tokens > 0 and m.claude_md_reread_tokens > 0:
        waste_ratio = m.claude_md_reread_tokens / m.total_tokens
        if waste_ratio > 0.3:
            score -= 25
        elif waste_ratio > 0.15:
            score -= 12

    score = max(0.0, min(100.0, score))
    m.score = score
    m.grade = score_to_grade(score)
    return m


# ---------------------------------------------------------------------------
# 2. Tool Call Health Score
# ---------------------------------------------------------------------------

INTERACTIVE_PATTERNS = [
    re.compile(r'\bnpm\s+init\b(?!\s+[-][-\w])'),
    re.compile(r'\bapt\b(?!\s+[-][-\w])(?!\s+-y\b)(?!\s+install\b.*-y)'),
    re.compile(r'\bgit\s+commit\b(?!\s+-m\b)'),
    re.compile(r'--watch\b'),
    re.compile(r'\byarn\s+add\b(?!\s+-[-\w])'),
]

INTERACTIVE_SAFE_FLAGS = {"--yes", "-y", "--non-interactive", "--no-input", "-n", "--assume-yes"}

ERROR_PATTERNS = re.compile(
    r'\b(error|Error|ERROR|failed|FAILED|exception|Exception|exit code [1-9])\b'
)


def _command_is_interactive(command: str) -> bool:
    """Heuristic: detect if a Bash command might hang waiting for input."""
    cmd_lower = command.lower()
    for pattern in INTERACTIVE_PATTERNS:
        if pattern.search(command):
            # Check if any safe flag is present
            if not any(flag in cmd_lower for flag in INTERACTIVE_SAFE_FLAGS):
                return True
    return False


@dataclass
class ToolHealthMetrics:
    retry_loop_count: int = 0
    edit_revert_count: int = 0
    consecutive_failure_count: int = 0
    interactive_call_count: int = 0
    migration_edit_count: int = 0
    total_tool_calls: int = 0
    issues: list[Issue] = field(default_factory=list)
    score: float = 100.0
    grade: str = "A"


def analyze_tool_health(sessions: list[ParseResult]) -> ToolHealthMetrics:
    m = ToolHealthMetrics()

    for session in sessions:
        session_id = session.records[0].session_id if session.records else ""
        tool_calls: list[ContentBlock] = []
        tool_results: list[ContentBlock] = []

        # Collect all tool_use and tool_result blocks in order
        for record in session.records:
            if isinstance(record, AssistantRecord):
                for block in record.content:
                    if block.type == "tool_use":
                        tool_calls.append(block)
                        m.total_tool_calls += 1
            elif isinstance(record, UserRecord):
                for block in record.content:
                    if block.type == "tool_result":
                        tool_results.append(block)

        # Detect retry loops (3+ consecutive calls to same tool with same/similar input)
        for i in range(len(tool_calls) - 2):
            t1, t2, t3 = tool_calls[i], tool_calls[i + 1], tool_calls[i + 2]
            if (t1.tool_name == t2.tool_name == t3.tool_name and
                    t1.tool_input == t2.tool_input):
                m.retry_loop_count += 1
                m.issues.append(Issue(
                    severity="high",
                    category="tool_health",
                    description=f"Retry loop detected: {t1.tool_name} called 3+ times with same input",
                    session_id=session_id,
                    evidence=str(t1.tool_input)[:120] if t1.tool_input else "",
                    count=3,
                ))
                break  # count once per session block

        # Detect migration file edits
        for block in tool_calls:
            if block.tool_name in ("Write", "Edit") and block.tool_input:
                fp = block.tool_input.get("file_path", "")
                if "migration" in fp.lower() or "/migrations/" in fp.lower():
                    m.migration_edit_count += 1
                    m.issues.append(Issue(
                        severity="high",
                        category="tool_health",
                        description=f"Migration file edited: {fp}",
                        session_id=session_id,
                        evidence=fp,
                    ))

        # Detect interactive commands
        for block in tool_calls:
            if block.tool_name == "Bash" and block.tool_input:
                cmd = block.tool_input.get("command", "")
                if _command_is_interactive(cmd):
                    m.interactive_call_count += 1
                    m.issues.append(Issue(
                        severity="medium",
                        category="tool_health",
                        description=f"Potentially interactive Bash command: {cmd[:80]}",
                        session_id=session_id,
                        evidence=cmd[:120],
                    ))

        # Detect edit-revert cycles (Write/Edit to same file within 3 turns)
        edit_history: list[tuple[str, int]] = []  # (file_path, index)
        for idx, block in enumerate(tool_calls):
            if block.tool_name in ("Write", "Edit") and block.tool_input:
                fp = block.tool_input.get("file_path", "")
                # Check if this file was edited recently (within 3 positions)
                for prev_fp, prev_idx in edit_history[-6:]:
                    if prev_fp == fp and (idx - prev_idx) <= 3 and idx != prev_idx:
                        m.edit_revert_count += 1
                        m.issues.append(Issue(
                            severity="medium",
                            category="tool_health",
                            description=f"Edit-revert cycle detected on {fp}",
                            session_id=session_id,
                            evidence=fp,
                        ))
                        break
                edit_history.append((fp, idx))

        # Detect consecutive tool failures
        consecutive_errors = 0
        max_consecutive = 0
        for result_block in tool_results:
            content_str = str(result_block.tool_content or "")
            if ERROR_PATTERNS.search(content_str):
                consecutive_errors += 1
                max_consecutive = max(max_consecutive, consecutive_errors)
            else:
                consecutive_errors = 0

        if max_consecutive >= 3:
            m.consecutive_failure_count += 1
            m.issues.append(Issue(
                severity="high",
                category="tool_health",
                description=f"Consecutive tool failures: {max_consecutive} errors in a row",
                session_id=session_id,
                count=max_consecutive,
            ))

    # Score calculation
    score = 100.0
    score -= min(40, m.retry_loop_count * 15)
    score -= min(20, m.interactive_call_count * 8)
    score -= min(15, m.edit_revert_count * 8)
    score -= min(20, m.consecutive_failure_count * 10)

    score = max(0.0, min(100.0, score))
    m.score = score
    m.grade = score_to_grade(score)
    return m


# ---------------------------------------------------------------------------
# 3. Context Hygiene Score
# ---------------------------------------------------------------------------

@dataclass
class ContextHygieneMetrics:
    compaction_count: int = 0
    long_sessions: int = 0  # >100 turns
    mid_task_compactions: int = 0
    total_sessions: int = 0
    issues: list[Issue] = field(default_factory=list)
    score: float = 100.0
    grade: str = "A"


def _count_turns(records: list[SessionRecord]) -> int:
    """Count user+assistant turn pairs."""
    return sum(1 for r in records if isinstance(r, (UserRecord, AssistantRecord)))


def _has_repeated_tool_pattern_after_boundary(records: list[SessionRecord]) -> bool:
    """Detect if tool calls after a compaction boundary repeat pre-boundary patterns."""
    boundary_idx = None
    for i, r in enumerate(records):
        if isinstance(r, SystemRecord) and r.subtype == "compact_boundary":
            boundary_idx = i
            break

    if boundary_idx is None:
        return False

    def get_tool_names(recs: list[SessionRecord]) -> list[str]:
        names = []
        for r in recs:
            if isinstance(r, AssistantRecord):
                for b in r.content:
                    if b.type == "tool_use" and b.tool_name:
                        names.append(b.tool_name)
        return names

    before = get_tool_names(records[:boundary_idx])
    after = get_tool_names(records[boundary_idx + 1:])

    if not before or not after:
        return False

    # Check if first few post-boundary tools match pre-boundary tools
    overlap = set(after[:5]) & set(before[:10])
    return len(overlap) >= 2


def analyze_context_hygiene(sessions: list[ParseResult]) -> ContextHygieneMetrics:
    m = ContextHygieneMetrics()
    m.total_sessions = len(sessions)

    for session in sessions:
        session_id = session.records[0].session_id if session.records else ""
        turn_count = _count_turns(session.records)

        # Count compactions
        compactions = [
            r for r in session.records
            if isinstance(r, SystemRecord) and r.subtype == "compact_boundary"
        ]
        m.compaction_count += len(compactions)

        if compactions:
            m.issues.append(Issue(
                severity="medium" if len(compactions) == 1 else "high",
                category="context_hygiene",
                description=f"Session has {len(compactions)} compaction event(s)",
                session_id=session_id,
                count=len(compactions),
            ))

            # Check for mid-task compaction (tool patterns repeat after boundary)
            if _has_repeated_tool_pattern_after_boundary(session.records):
                m.mid_task_compactions += 1
                m.issues.append(Issue(
                    severity="high",
                    category="context_hygiene",
                    description="Mid-task compaction: tool patterns repeat after boundary (context loss signal)",
                    session_id=session_id,
                ))

        # Long session check
        if turn_count > 100:
            m.long_sessions += 1
            m.issues.append(Issue(
                severity="medium",
                category="context_hygiene",
                description=f"Session has {turn_count} turns — possible context drift",
                session_id=session_id,
                count=turn_count,
            ))

    # Score
    score = 100.0
    if m.total_sessions > 0:
        compaction_rate = m.compaction_count / m.total_sessions
        score -= min(35, compaction_rate * 20)
    score -= min(20, m.mid_task_compactions * 15)
    score -= min(15, m.long_sessions * 10)

    score = max(0.0, min(100.0, score))
    m.score = score
    m.grade = score_to_grade(score)
    return m


# ---------------------------------------------------------------------------
# 4. CLAUDE.md Adherence Score
# ---------------------------------------------------------------------------

RULE_PREFIXES = re.compile(
    r'^(Never|Always|Don\'t|Use|Avoid|Run|NEVER|ALWAYS|DO NOT|Prefer|Must|Ensure)\b',
    re.IGNORECASE
)


@dataclass
class AdherenceRule:
    text: str
    line_number: int
    violations: int = 0
    checks: int = 0


@dataclass
class ClaudeMdAdherenceMetrics:
    rules_found: int = 0
    rules_violated: int = 0
    rules_followed: int = 0
    rules_unchecked: int = 0
    claude_md_line_count: int = 0
    violations: list[Issue] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    score: float = 100.0
    grade: str = "A"


def _extract_rules(claude_md_path: Path) -> list[AdherenceRule]:
    """Extract rule-like lines from CLAUDE.md."""
    rules = []
    try:
        lines = claude_md_path.read_text(encoding="utf-8", errors="replace").splitlines()
        for i, line in enumerate(lines, 1):
            stripped = line.strip().lstrip("- *#").strip()
            if RULE_PREFIXES.match(stripped):
                rules.append(AdherenceRule(text=stripped, line_number=i))
    except OSError:
        pass
    return rules


def _check_rule_violation(rule: AdherenceRule, sessions: list[ParseResult]) -> int:
    """Return number of sessions where this rule appears to be violated."""
    text_lower = rule.text.lower()
    violations = 0

    # Build violation check predicates based on rule content
    check_fns: list[Any] = []

    if "migration" in text_lower and ("never" in text_lower or "don't" in text_lower):
        # "Never edit migration files"
        def check_migration(block: ContentBlock) -> bool:
            if block.type == "tool_use" and block.tool_name in ("Write", "Edit"):
                fp = (block.tool_input or {}).get("file_path", "")
                return "migration" in fp.lower() or "/migrations/" in fp.lower()
            return False
        check_fns.append(check_migration)

    if "non-interactive" in text_lower or "interactive" in text_lower:
        def check_interactive(block: ContentBlock) -> bool:
            if block.type == "tool_use" and block.tool_name == "Bash":
                cmd = (block.tool_input or {}).get("command", "")
                return _command_is_interactive(cmd)
            return False
        check_fns.append(check_interactive)

    if "any" in text_lower and "typescript" in text_lower:
        def check_ts_any(block: ContentBlock) -> bool:
            if block.type == "tool_use" and block.tool_name in ("Write", "Edit"):
                content = str((block.tool_input or {}).get("new_string", "")) + \
                          str((block.tool_input or {}).get("content", ""))
                return ": any" in content or ":any" in content
            return False
        check_fns.append(check_ts_any)

    if not check_fns:
        return 0  # Can't check this rule automatically

    for session in sessions:
        session_violated = False
        for record in session.records:
            if isinstance(record, AssistantRecord):
                for block in record.content:
                    for fn in check_fns:
                        if fn(block):
                            session_violated = True
                            break
                if session_violated:
                    break
        if session_violated:
            violations += 1

    return violations


def analyze_claude_md_adherence(
    sessions: list[ParseResult],
    claude_md_path: Path | None,
) -> ClaudeMdAdherenceMetrics:
    m = ClaudeMdAdherenceMetrics()

    if claude_md_path is None or not claude_md_path.exists():
        m.grade = "N/A"
        return m

    try:
        lines = claude_md_path.read_text(encoding="utf-8", errors="replace").splitlines()
        m.claude_md_line_count = len(lines)
    except OSError:
        m.grade = "N/A"
        return m

    # "Mr. Tinkleberry test"
    if m.claude_md_line_count > 80:
        m.issues.append(Issue(
            severity="high",
            category="claude_md_adherence",
            description=f"CLAUDE.md is {m.claude_md_line_count} lines — adherence degrades past line 80",
        ))

    rules = _extract_rules(claude_md_path)
    m.rules_found = len(rules)

    for rule in rules:
        violations = _check_rule_violation(rule, sessions)
        rule.violations = violations
        if violations > 0:
            m.rules_violated += 1
            m.violations.append(Issue(
                severity="high",
                category="claude_md_adherence",
                description=f"Rule violated in {violations} session(s): '{rule.text}'",
                count=violations,
            ))
        else:
            m.rules_followed += 1

    m.rules_unchecked = m.rules_found - m.rules_violated - m.rules_followed

    # Score
    score = 100.0
    if m.rules_found > 0:
        violation_ratio = m.rules_violated / m.rules_found
        score -= violation_ratio * 60
    if m.claude_md_line_count > 80:
        score -= 15
    if m.claude_md_line_count > 120:
        score -= 10

    score = max(0.0, min(100.0, score))
    m.score = score
    m.grade = score_to_grade(score)
    return m


# ---------------------------------------------------------------------------
# 5. Session Continuity Score
# ---------------------------------------------------------------------------

RESUME_CONTEXT_LOSS_PHRASES = re.compile(
    r'\b(what is|what are|can you describe|first let me understand|'
    r'could you tell me|what does|what\'s the|let me start by)\b',
    re.IGNORECASE
)


@dataclass
class SessionContinuityMetrics:
    total_sessions: int = 0
    truncated_sessions: int = 0
    resumed_sessions: int = 0
    context_loss_resumes: int = 0
    issues: list[Issue] = field(default_factory=list)
    score: float = 100.0
    grade: str = "A"


def analyze_session_continuity(sessions: list[ParseResult]) -> SessionContinuityMetrics:
    m = SessionContinuityMetrics()
    m.total_sessions = len(sessions)

    for session in sessions:
        session_id = session.records[0].session_id if session.records else ""

        if session.truncated:
            m.truncated_sessions += 1
            m.issues.append(Issue(
                severity="medium",
                category="session_continuity",
                description="Session file truncated — write was interrupted",
                session_id=session_id,
            ))

        # Check for resume signals in system records
        is_resumed = any(
            isinstance(r, SystemRecord) and r.subtype in ("continuation", "resume")
            for r in session.records
        )
        if is_resumed:
            m.resumed_sessions += 1

        # Check first few assistant turns for context re-establishment phrases
        first_assistant_turns = [
            r for r in session.records[:10]
            if isinstance(r, AssistantRecord)
        ][:3]
        for turn in first_assistant_turns:
            for block in turn.content:
                if block.text and RESUME_CONTEXT_LOSS_PHRASES.search(block.text):
                    m.context_loss_resumes += 1
                    m.issues.append(Issue(
                        severity="medium",
                        category="session_continuity",
                        description="Context re-establishment phrases detected at session start",
                        session_id=session_id,
                        evidence=block.text[:100],
                    ))
                    break
            else:
                continue
            break

    # Score
    score = 100.0
    if m.total_sessions > 0:
        truncation_rate = m.truncated_sessions / m.total_sessions
        score -= min(20, truncation_rate * 40)
        context_loss_rate = m.context_loss_resumes / m.total_sessions
        score -= min(30, context_loss_rate * 40)

    score = max(0.0, min(100.0, score))
    m.score = score
    m.grade = score_to_grade(score)
    return m


# ---------------------------------------------------------------------------
# Overall Project Health
# ---------------------------------------------------------------------------

@dataclass
class ProjectHealthReport:
    project: ProjectInfo
    session_count: int
    token_efficiency: TokenEfficiencyMetrics
    tool_health: ToolHealthMetrics
    context_hygiene: ContextHygieneMetrics
    claude_md_adherence: ClaudeMdAdherenceMetrics
    session_continuity: SessionContinuityMetrics
    overall_score: float
    overall_grade: str
    top_issues: list[Issue]


def analyze_project(
    project: ProjectInfo,
    claude_md_path: Path | None = None,
    max_sessions: int = 50,
) -> ProjectHealthReport:
    """Run all five analysis dimensions on a project.

    Args:
        project: The project to analyze.
        claude_md_path: Optional override for CLAUDE.md location.
            If None, attempts to find CLAUDE.md from the project's cwd.
        max_sessions: Maximum number of sessions to load (most recent first).
    """
    sessions = load_all_sessions(project)[:max_sessions]

    # Try to find CLAUDE.md if not provided
    if claude_md_path is None and sessions:
        for session in sessions:
            if session.records:
                cwd = Path(session.records[0].cwd)
                candidate = cwd / "CLAUDE.md"
                if candidate.exists():
                    claude_md_path = candidate
                    break

    token_efficiency = analyze_token_efficiency(sessions, claude_md_path)
    tool_health = analyze_tool_health(sessions)
    context_hygiene = analyze_context_hygiene(sessions)
    claude_md_adherence = analyze_claude_md_adherence(sessions, claude_md_path)
    session_continuity = analyze_session_continuity(sessions)

    # Overall score: weighted average
    scores = [
        token_efficiency.score * 0.20,
        tool_health.score * 0.25,
        context_hygiene.score * 0.20,
        (claude_md_adherence.score if claude_md_adherence.grade != "N/A" else 70.0) * 0.20,
        session_continuity.score * 0.15,
    ]
    overall_score = sum(scores)
    overall_grade = score_to_grade(overall_score)

    # Collect and prioritize top issues
    all_issues: list[Issue] = (
        token_efficiency.issues
        + tool_health.issues
        + context_hygiene.issues
        + claude_md_adherence.violations
        + claude_md_adherence.issues
        + session_continuity.issues
    )
    severity_order = {"high": 0, "medium": 1, "low": 2}
    all_issues.sort(key=lambda i: severity_order.get(i.severity, 3))

    return ProjectHealthReport(
        project=project,
        session_count=len(sessions),
        token_efficiency=token_efficiency,
        tool_health=tool_health,
        context_hygiene=context_hygiene,
        claude_md_adherence=claude_md_adherence,
        session_continuity=session_continuity,
        overall_score=overall_score,
        overall_grade=overall_grade,
        top_issues=all_issues[:10],
    )
