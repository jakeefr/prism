"""CLAUDE.md recommendation generator for PRISM.

Takes ProjectHealthReport objects and produces actionable recommendations.
No I/O here except optionally writing the updated CLAUDE.md when --apply is used.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from prism.analyzer import (
    Issue,
    ProjectHealthReport,
)


# ---------------------------------------------------------------------------
# Recommendation types
# ---------------------------------------------------------------------------

@dataclass
class Recommendation:
    """A single actionable CLAUDE.md recommendation."""
    action: str          # "ADD" | "TRIM" | "WARN" | "RESTRUCTURE"
    impact: str          # "High" | "Medium" | "Low"
    rationale: str       # Evidence-backed reason
    content: str         # The text to add/remove/restructure
    line_range: tuple[int, int] | None = None  # For TRIM actions
    session_evidence: str = ""  # Which sessions triggered this


@dataclass
class AdvisorReport:
    """Full set of recommendations for a project."""
    project_name: str
    recommendations: list[Recommendation] = field(default_factory=list)
    has_actionable: bool = False


# ---------------------------------------------------------------------------
# Recommendation generators
# ---------------------------------------------------------------------------

def _recommend_non_interactive_flag(report: ProjectHealthReport) -> Recommendation | None:
    """Recommend adding non-interactive flags if retry loops detected."""
    interactive_issues = [
        i for i in report.tool_health.issues
        if "interactive" in i.description.lower()
    ]
    retry_issues = [
        i for i in report.tool_health.issues
        if "retry" in i.description.lower()
    ]

    if not interactive_issues and not retry_issues:
        return None

    count = len(interactive_issues) + len(retry_issues)
    sessions = {i.session_id for i in interactive_issues + retry_issues if i.session_id}

    return Recommendation(
        action="ADD",
        impact="High" if count >= 3 else "Medium",
        rationale=(
            f"Fixes {report.tool_health.retry_loop_count} retry loop(s) and "
            f"{report.tool_health.interactive_call_count} interactive command(s) "
            f"across {len(sessions)} session(s)"
        ),
        content=(
            "Always use non-interactive flags when available: "
            "--yes, -y, --non-interactive, --no-input. "
            "Never use commands with --watch, --interactive, or prompts that wait for input."
        ),
        session_evidence=", ".join(sorted(sessions)[:3]),
    )


def _recommend_migration_rule(report: ProjectHealthReport) -> Recommendation | None:
    """Recommend a migration file protection rule if violations found."""
    migration_violations = [
        i for i in report.tool_health.issues + report.claude_md_adherence.violations
        if "migration" in i.description.lower() or
        (i.evidence and "migration" in i.evidence.lower())
    ]

    if not migration_violations:
        return None

    count = len(migration_violations)
    sessions = {i.session_id for i in migration_violations if i.session_id}

    return Recommendation(
        action="ADD",
        impact="High",
        rationale=f"{count} migration file edit(s) detected across {len(sessions)} session(s)",
        content=(
            "NEVER edit existing migration files — always create new ones. "
            "Migration files in db/migrations/ or */migrations/ are immutable once applied."
        ),
        session_evidence=", ".join(sorted(sessions)[:3]),
    )


def _recommend_trim_long_claude_md(report: ProjectHealthReport, claude_md_path: Path | None) -> Recommendation | None:
    """Recommend trimming an oversized CLAUDE.md."""
    line_count = report.claude_md_adherence.claude_md_line_count
    if line_count <= 80:
        return None
    if claude_md_path is None or not claude_md_path.exists():
        return None

    # Estimate wasted tokens
    try:
        text = claude_md_path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        # Find lines 80+ that look like personality/tone instructions
        tone_lines = []
        for i, line in enumerate(lines[79:], 80):
            stripped = line.strip()
            if any(kw in stripped.lower() for kw in
                   ["tone", "style", "personality", "be", "sound", "format", "voice"]):
                tone_lines.append(i + 1)
    except OSError:
        tone_lines = []

    if tone_lines:
        line_range = (min(tone_lines), max(tone_lines))
        content = f"Remove lines {line_range[0]}–{line_range[1]}: personality/tone instructions"
        rationale = (
            f"Your CLAUDE.md is {line_count} lines — adherence drops ~60% past line 80. "
            f"Lines {line_range[0]}–{line_range[1]} appear to be tone/personality instructions "
            f"that Claude Code's system prompt already handles."
        )
    else:
        line_range = (81, line_count)
        content = f"Trim CLAUDE.md from {line_count} lines to under 80"
        rationale = (
            f"Your CLAUDE.md is {line_count} lines — adherence drops significantly past line 80. "
            f"Consider moving rarely-used rules to per-directory CLAUDE.md files."
        )

    return Recommendation(
        action="TRIM",
        impact="Medium",
        rationale=rationale,
        content=content,
        line_range=line_range,
    )


def _recommend_rule_violations(report: ProjectHealthReport) -> list[Recommendation]:
    """Generate recommendations for each detected rule violation."""
    recs = []
    seen = set()
    for violation in report.claude_md_adherence.violations[:5]:  # cap at 5
        key = violation.description[:50]
        if key in seen:
            continue
        seen.add(key)
        recs.append(Recommendation(
            action="WARN",
            impact="High",
            rationale=violation.description,
            content=f"Rule appears violated — review sessions and reinforce: {violation.description}",
            session_evidence="",
        ))
    return recs


def _recommend_restructure(report: ProjectHealthReport, claude_md_path: Path | None) -> Recommendation | None:
    """Recommend restructuring if project-specific rules could be moved to subdirectory CLAUDE.md."""
    if claude_md_path is None or not claude_md_path.exists():
        return None
    if report.claude_md_adherence.claude_md_line_count <= 60:
        return None

    try:
        lines = claude_md_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None

    # Find rules that mention specific subdirectories or file patterns
    subdir_rules: list[str] = []
    subdir_pattern = re.compile(r'\b(src/|tests/|lib/|components/|pages/|api/)\b')
    for line in lines:
        stripped = line.strip().lstrip("- *").strip()
        if subdir_pattern.search(stripped) and len(stripped) > 10:
            subdir_rules.append(f"  - \"{stripped}\"")

    if len(subdir_rules) < 2:
        return None

    rule_list = "\n".join(subdir_rules[:3])
    return Recommendation(
        action="RESTRUCTURE",
        impact="Medium",
        rationale=(
            f"Found {len(subdir_rules)} rules that reference specific subdirectories. "
            f"Moving these to subdirectory CLAUDE.md files reduces root-level token cost "
            f"and improves context relevance."
        ),
        content=(
            f"Consider moving these rules to their respective subdirectory CLAUDE.md files:\n"
            f"{rule_list}"
        ),
    )


def _recommend_attention_curve(
    report: ProjectHealthReport,
    claude_md_path: Path | None,
) -> list[Recommendation]:
    """Score CLAUDE.md rules by their position in the U-shaped attention curve.

    Rules in the middle 55% of the file get the least model attention.
    Flag critical rules (Never/NEVER/CRITICAL/DO NOT/ALWAYS/MUST NOT) that are
    in the danger zone and recommend moving them to the top or bottom.
    """
    if claude_md_path is None or not claude_md_path.exists():
        return []

    try:
        lines = claude_md_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []

    total = len(lines)
    if total < 20:  # Too short to matter
        return []

    danger_start = int(total * 0.20)
    danger_end = int(total * 0.75)

    critical_patterns = ["NEVER", "CRITICAL", "DO NOT", "ALWAYS", "MUST NOT"]
    buried_rules: list[tuple[int, str]] = []

    for i, line in enumerate(lines):
        if danger_start <= i <= danger_end:
            if any(p in line.upper() for p in critical_patterns):
                buried_rules.append((i + 1, line.strip()))

    if not buried_rules:
        return []

    rule_list = "\n".join(
        f"  Line {lineno}: {text[:80]}"
        for lineno, text in buried_rules[:5]
    )

    return [Recommendation(
        action="RESTRUCTURE",
        impact="Medium",
        rationale=(
            f"Found {len(buried_rules)} critical rule(s) in the attention dead zone "
            f"(lines {danger_start}–{danger_end} of {total}). "
            "LLMs follow a U-shaped attention curve — middle content gets least focus. "
            "Move NEVER/CRITICAL rules to the first 20% or last 25% of your CLAUDE.md."
        ),
        content=f"Move these rules to the top or bottom of your CLAUDE.md:\n{rule_list}",
    )]


def _recommend_continuity(report: ProjectHealthReport) -> Recommendation | None:
    """Recommend session continuity improvements."""
    if report.session_continuity.truncated_sessions == 0:
        return None
    if report.session_continuity.truncated_sessions / max(report.session_count, 1) < 0.1:
        return None

    return Recommendation(
        action="WARN",
        impact="Low",
        rationale=(
            f"{report.session_continuity.truncated_sessions} session file(s) appear truncated — "
            f"Claude Code was likely killed mid-write."
        ),
        content=(
            "Truncated sessions indicate abrupt process termination. "
            "Avoid force-killing Claude Code; use Ctrl+C for graceful exit."
        ),
    )


# ---------------------------------------------------------------------------
# Main advisor entry point
# ---------------------------------------------------------------------------

def generate_advice(
    report: ProjectHealthReport,
    claude_md_path: Path | None = None,
) -> AdvisorReport:
    """Generate a full AdvisorReport from a ProjectHealthReport.

    All recommendations are evidence-backed — no generic advice.
    """
    advisor_report = AdvisorReport(project_name=report.project.encoded_name)
    recs: list[Recommendation] = []

    # Non-interactive flags
    rec = _recommend_non_interactive_flag(report)
    if rec:
        recs.append(rec)

    # Migration rule
    rec = _recommend_migration_rule(report)
    if rec:
        recs.append(rec)

    # Trim oversized CLAUDE.md
    rec = _recommend_trim_long_claude_md(report, claude_md_path)
    if rec:
        recs.append(rec)

    # Rule violations
    recs.extend(_recommend_rule_violations(report))

    # Restructure to subdirectories
    rec = _recommend_restructure(report, claude_md_path)
    if rec:
        recs.append(rec)

    # Attention curve — critical rules buried in middle of CLAUDE.md
    recs.extend(_recommend_attention_curve(report, claude_md_path))

    # Continuity
    rec = _recommend_continuity(report)
    if rec:
        recs.append(rec)

    # Sort by impact
    impact_order = {"High": 0, "Medium": 1, "Low": 2}
    recs.sort(key=lambda r: impact_order.get(r.impact, 3))

    advisor_report.recommendations = recs
    advisor_report.has_actionable = len(recs) > 0
    return advisor_report


# ---------------------------------------------------------------------------
# Rich-formatted output renderer
# ---------------------------------------------------------------------------

def format_advice_rich(advisor_report: AdvisorReport) -> str:
    """Render an AdvisorReport as a Rich-formatted string."""
    lines = []
    lines.append(
        f"\n[bold cyan]╭{'─' * 61}╮[/bold cyan]\n"
        f"[bold cyan]│  PRISM ADVISOR — recommendations for CLAUDE.md"
        f"{'':14}│[/bold cyan]\n"
        f"[bold cyan]╰{'─' * 61}╯[/bold cyan]\n"
    )

    if not advisor_report.recommendations:
        lines.append(
            "[green]  ✓ No recommendations — your CLAUDE.md looks healthy![/green]\n"
        )
        return "".join(lines)

    action_colors = {
        "ADD": "green",
        "TRIM": "red",
        "WARN": "yellow",
        "RESTRUCTURE": "cyan",
    }

    for rec in advisor_report.recommendations:
        color = action_colors.get(rec.action, "white")
        lines.append(
            f"[{color}]  ✦ {rec.action}[/{color}]  "
            f"([bold]{rec.impact} impact[/bold] — {rec.rationale})\n"
        )
        for content_line in rec.content.splitlines():
            lines.append(f"    {content_line}\n")
        if rec.session_evidence:
            lines.append(f"    [dim]Sessions: {rec.session_evidence}[/dim]\n")
        lines.append("\n")

    return "".join(lines)


# ---------------------------------------------------------------------------
# --apply mode: write changes to CLAUDE.md
# ---------------------------------------------------------------------------

def apply_advice(
    advisor_report: AdvisorReport,
    claude_md_path: Path,
    confirm: bool = True,
) -> bool:
    """Apply ADD recommendations to CLAUDE.md.

    Args:
        advisor_report: The advisor report with recommendations.
        claude_md_path: Path to the CLAUDE.md to modify.
        confirm: If True, print changes and ask for user confirmation.

    Returns:
        True if changes were written, False if skipped.
    """
    add_recs = [r for r in advisor_report.recommendations if r.action == "ADD"]
    if not add_recs:
        return False

    try:
        existing = claude_md_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        existing = ""

    new_rules = []
    for rec in add_recs:
        rule_text = f"- {rec.content}"
        if rule_text not in existing:
            new_rules.append(rule_text)

    if not new_rules:
        return False

    if confirm:
        print("\nThe following rules will be added to CLAUDE.md:\n")
        for rule in new_rules:
            print(f"  + {rule}")
        response = input("\nApply? [y/N] ").strip().lower()
        if response != "y":
            return False

    # Find or create ## Rules section
    if "## Rules" in existing:
        new_content = existing.replace(
            "## Rules\n",
            "## Rules\n" + "\n".join(new_rules) + "\n",
            1,
        )
    else:
        new_content = existing.rstrip() + "\n\n## Rules\n" + "\n".join(new_rules) + "\n"

    claude_md_path.write_text(new_content, encoding="utf-8")
    return True
