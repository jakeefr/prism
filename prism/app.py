"""PRISM Textual TUI application — main interactive dashboard."""

from __future__ import annotations

import time
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import (
    Footer,
    Header,
    Label,
    ListView,
    RichLog,
)

from prism.advisor import generate_advice
from prism.analyzer import (
    ProjectHealthReport,
    analyze_project,
)
from prism.parser import (
    CLAUDE_PROJECTS_DIR,
    ProjectInfo,
    discover_projects,
    parse_session_file,
)
from prism.widgets.advisor_panel import AdvisorPanel
from prism.widgets.health_card import HealthCard
from prism.widgets.live_watcher import LiveWatcher
from prism.widgets.session_list import ProjectEntry, SessionList
from prism.widgets.timeline import Timeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_ago(mtime: float) -> str:
    """Human-readable 'X ago' string from a unix timestamp."""
    delta = time.time() - mtime
    if delta < 60:
        return "just now"
    elif delta < 3600:
        return f"{int(delta // 60)}m ago"
    elif delta < 86400:
        return f"{int(delta // 3600)}h ago"
    elif delta < 7 * 86400:
        return f"{int(delta // 86400)}d ago"
    else:
        return f"{int(delta // (7 * 86400))}w ago"


def _project_to_entry(project: ProjectInfo, report: ProjectHealthReport) -> ProjectEntry:
    mtime = project.last_active or 0.0
    last_active_str = _format_ago(mtime) if mtime else "never"
    return ProjectEntry(
        encoded_name=project.encoded_name,
        display_name=project.display_name,
        session_count=report.session_count,
        last_active_str=last_active_str,
        overall_grade=report.overall_grade,
        overall_score=report.overall_score,
    )


# ---------------------------------------------------------------------------
# Timeline / Replay Screen
# ---------------------------------------------------------------------------

class ReplayScreen(Screen):
    """Full-screen session timeline / replay view."""

    BINDINGS = [
        Binding("q,escape", "dismiss", "Back"),
        Binding("up,k", "cursor_up", "Up"),
        Binding("down,j", "cursor_down", "Down"),
    ]

    def __init__(self, session_path: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._session_path = session_path

    def compose(self) -> ComposeResult:
        result = parse_session_file(self._session_path)
        session_id = result.records[0].session_id if result.records else "unknown"
        turn_count = len(result.records)
        ts = ""
        if result.records:
            ts = result.records[0].timestamp[:10]

        yield Header()
        with Container(id="timeline-screen"):
            yield Label(
                f" ← Back  │  Session: {session_id[:8]}  │  {ts}  │  {turn_count} records",
                classes="section-title",
            )
            yield Timeline(result.records, id="main-timeline")
        yield Footer()

    def action_dismiss(self) -> None:
        self.app.pop_screen()

    def action_cursor_up(self) -> None:
        try:
            self.query_one("#main-timeline Timeline ListView").action_cursor_up()
        except Exception:
            pass

    def action_cursor_down(self) -> None:
        try:
            self.query_one("#main-timeline Timeline ListView").action_cursor_down()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Live Watch Screen
# ---------------------------------------------------------------------------

class LiveScreen(Screen):
    """Full-screen live session watcher."""

    BINDINGS = [
        Binding("q,escape", "dismiss", "Back"),
    ]

    def __init__(self, base_dir: Path | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._base_dir = base_dir

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="live-screen"):
            yield Label(" PRISM — Live Watch", classes="section-title")
            yield LiveWatcher(base_dir=self._base_dir, id="live-watcher")
        yield Footer()

    def action_dismiss(self) -> None:
        self.app.pop_screen()


# ---------------------------------------------------------------------------
# Advisor Screen
# ---------------------------------------------------------------------------

class AdvisorScreen(Screen):
    """Full-screen advisor recommendations view."""

    BINDINGS = [
        Binding("q,escape", "dismiss", "Back"),
        Binding("a", "apply", "Apply"),
    ]

    def __init__(self, report: ProjectHealthReport, claude_md_path: Path | None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._report = report
        self._claude_md_path = claude_md_path

    def compose(self) -> ComposeResult:
        advisor_report = generate_advice(self._report, self._claude_md_path)
        yield Header()
        yield AdvisorPanel(advisor_report, id="advisor-main")
        yield Footer()

    def action_dismiss(self) -> None:
        self.app.pop_screen()

    def action_apply(self) -> None:
        # In TUI mode, just notify — actual apply runs via CLI
        try:
            panel = self.query_one("#advisor-main", AdvisorPanel)
            panel.post_message(AdvisorPanel.ApplyRequested())
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main Dashboard Screen
# ---------------------------------------------------------------------------

class DashboardScreen(Screen):
    """Main interactive dashboard showing all projects and health scores."""

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "replay", "Replay"),
        Binding("a", "advise", "Advise"),
        Binding("w", "watch", "Watch"),
        Binding("up,k", "cursor_up", "Up"),
        Binding("down,j", "cursor_down", "Down"),
        Binding("enter", "select", "Select"),
    ]

    selected_project_idx: reactive[int] = reactive(0)

    def __init__(self, projects: list[ProjectInfo], reports: list[ProjectHealthReport], **kwargs) -> None:
        super().__init__(**kwargs)
        self._projects = projects
        self._reports = reports
        self._selected_idx = 0

    def compose(self) -> ComposeResult:
        yield Header()

        with Horizontal(id="top-panel"):
            # Left: project list
            with Vertical(id="project-panel"):
                yield Label(" YOUR PROJECTS", classes="section-title")
                entries = [
                    _project_to_entry(p, r)
                    for p, r in zip(self._projects, self._reports)
                ]
                yield SessionList(entries, id="main-session-list")

            # Right: selected project details
            with Vertical(id="detail-panel"):
                yield Label(" SELECTED PROJECT", classes="section-title", id="selected-label")
                with Horizontal(id="score-cards"):
                    yield HealthCard("Token Eff.", "?", "", id="card-token")
                    yield HealthCard("Tool Health", "?", "", id="card-tool")
                    yield HealthCard("Ctx Hygiene", "?", "", id="card-ctx")
                    yield HealthCard("MD Adherence", "?", "", id="card-md")
                    yield HealthCard("Continuity", "?", "", id="card-cont")

                with Container(id="issues-panel"):
                    yield Label(" TOP ISSUES", classes="section-title")
                    yield RichLog(
                        id="issues-log",
                        highlight=True,
                        markup=True,
                        wrap=True,
                    )

                yield Label(
                    " [A] Advise   [R] Replay last session   [W] Watch live   [Q] Quit",
                    classes="dim",
                )

        yield Footer()

    def on_mount(self) -> None:
        if self._reports:
            self._update_detail(0)

    def _update_detail(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._reports):
            return
        self._selected_idx = idx
        report = self._reports[idx]
        project = self._projects[idx]

        try:
            self.query_one("#selected-label", Label).update(
                f" SELECTED: {project.display_name}"
            )

            self.query_one("#card-token", HealthCard).update(
                "Token Eff.",
                report.token_efficiency.grade,
                f"{report.session_count} sessions",
            )
            self.query_one("#card-tool", HealthCard).update(
                "Tool Health",
                report.tool_health.grade,
                f"{report.tool_health.retry_loop_count} loops",
            )
            self.query_one("#card-ctx", HealthCard).update(
                "Ctx Hygiene",
                report.context_hygiene.grade,
                f"{report.context_hygiene.compaction_count} compact.",
            )
            md_grade = report.claude_md_adherence.grade
            self.query_one("#card-md", HealthCard).update(
                "MD Adherence",
                md_grade,
                f"{report.claude_md_adherence.rules_violated} violated",
            )
            self.query_one("#card-cont", HealthCard).update(
                "Continuity",
                report.session_continuity.grade,
                f"{report.session_continuity.truncated_sessions} truncated",
            )

            log = self.query_one("#issues-log", RichLog)
            log.clear()
            if report.top_issues:
                severity_colors = {"high": "red", "medium": "yellow", "low": "dim"}
                for issue in report.top_issues[:6]:
                    color = severity_colors.get(issue.severity, "white")
                    log.write(
                        f"[{color}]  ! {issue.description[:80]}[/{color}]"
                    )
            else:
                log.write("[green]  ✓ No issues detected — looks healthy![/green]")

        except Exception:
            pass

    def on_session_list_project_selected(self, event: SessionList.ProjectSelected) -> None:
        event.stop()
        # Find the selected project index by encoded_name
        for i, p in enumerate(self._projects):
            if p.encoded_name == event.entry.encoded_name:
                self._update_detail(i)
                break

    def action_replay(self) -> None:
        if self._selected_idx < len(self._projects):
            project = self._projects[self._selected_idx]
            if project.session_files:
                self.app.push_screen(ReplayScreen(project.session_files[0]))

    def action_advise(self) -> None:
        if self._selected_idx < len(self._reports):
            report = self._reports[self._selected_idx]
            project = self._projects[self._selected_idx]
            claude_md = None
            if report.token_efficiency.session_count > 0:
                # Try to find CLAUDE.md from session cwd
                sessions = parse_session_file(project.session_files[0]) if project.session_files else None
                if sessions and sessions.records:
                    cwd = Path(sessions.records[0].cwd)
                    candidate = cwd / "CLAUDE.md"
                    if candidate.exists():
                        claude_md = candidate
            self.app.push_screen(AdvisorScreen(report, claude_md))

    def action_watch(self) -> None:
        self.app.push_screen(LiveScreen(base_dir=self.app._base_dir))

    def action_quit(self) -> None:
        self.app.exit()

    def action_cursor_up(self) -> None:
        new_idx = max(0, self._selected_idx - 1)
        if new_idx != self._selected_idx:
            self._update_detail(new_idx)

    def action_cursor_down(self) -> None:
        new_idx = min(len(self._projects) - 1, self._selected_idx + 1)
        if new_idx != self._selected_idx:
            self._update_detail(new_idx)

    def action_select(self) -> None:
        self._update_detail(self._selected_idx)


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------

class PrismApp(App):
    """PRISM — Session intelligence for Claude Code."""

    CSS_PATH = Path(__file__).parent / "styles" / "prism.tcss"

    TITLE = "◈ PRISM"
    SUB_TITLE = "Session intelligence for Claude Code"

    BINDINGS = [
        Binding("ctrl+c,q", "quit", "Quit", priority=True),
    ]

    def __init__(
        self,
        base_dir: Path | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._base_dir = base_dir or CLAUDE_PROJECTS_DIR

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label(
            "  ◈ PRISM — loading...",
            classes="accent",
            id="loading-label",
        )
        yield Footer()

    def on_mount(self) -> None:
        # Load projects in a worker thread to avoid blocking the TUI
        self.run_worker(self._load_and_show, exclusive=True, thread=True)

    def _load_and_show(self) -> None:
        """Worker: discover projects, run analysis, switch to dashboard."""
        projects = discover_projects(self._base_dir)

        if not projects:
            self.call_from_thread(self._show_no_projects)
            return

        # Analyze each project (cap at 20 projects to keep startup fast)
        reports: list[ProjectHealthReport] = []
        for project in projects[:20]:
            try:
                report = analyze_project(project)
                reports.append(report)
            except Exception:
                # If analysis fails for a project, create a minimal stub report
                from prism.analyzer import (
                    TokenEfficiencyMetrics,
                    ToolHealthMetrics,
                    ContextHygieneMetrics,
                    ClaudeMdAdherenceMetrics,
                    SessionContinuityMetrics,
                )
                reports.append(ProjectHealthReport(
                    project=project,
                    session_count=len(project.session_files),
                    token_efficiency=TokenEfficiencyMetrics(grade="?"),
                    tool_health=ToolHealthMetrics(grade="?"),
                    context_hygiene=ContextHygieneMetrics(grade="?"),
                    claude_md_adherence=ClaudeMdAdherenceMetrics(grade="?"),
                    session_continuity=SessionContinuityMetrics(grade="?"),
                    overall_score=50.0,
                    overall_grade="?",
                    top_issues=[],
                ))

        # Keep only projects with matching reports
        projects = projects[:len(reports)]
        self.call_from_thread(self._show_dashboard, projects, reports)

    def _show_no_projects(self) -> None:
        try:
            label = self.query_one("#loading-label", Label)
            label.update(
                "\n\n  No Claude Code sessions found.\n\n"
                "  Have you used Claude Code yet?\n"
                f"  Looking in: {self._base_dir}\n"
            )
        except Exception:
            pass

    def _show_dashboard(
        self,
        projects: list[ProjectInfo],
        reports: list[ProjectHealthReport],
    ) -> None:
        self.push_screen(DashboardScreen(projects, reports))


def run_tui(base_dir: Path | None = None) -> None:
    """Entry point to launch the PRISM TUI."""
    app = PrismApp(base_dir=base_dir)
    app.run()
