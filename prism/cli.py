"""PRISM CLI — Typer entry point.

Thin layer that calls analyzer / advisor / app. No business logic here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from prism import __version__
from prism.analyzer import analyze_project, score_to_grade
from prism.parser import (
    CLAUDE_PROJECTS_DIR,
    ProjectInfo,
    discover_projects,
    parse_session_file,
    project_path_to_encoded_name,
)

# Force UTF-8 output on Windows so Unicode symbols render correctly
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

app = typer.Typer(
    name="prism",
    help="Session intelligence for Claude Code — diagnose, score, and fix your sessions.",
    add_completion=False,
    invoke_without_command=True,
    no_args_is_help=False,
)

console = Console()
err_console = Console(stderr=True)


# ---------------------------------------------------------------------------
# Default command: open TUI
# ---------------------------------------------------------------------------

@app.callback()
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-V", help="Show version and exit."),
) -> None:
    """PRISM — session intelligence for Claude Code.

    Run without a subcommand to open the interactive TUI dashboard.
    """
    if version:
        console.print(f"prism v{__version__}")
        raise typer.Exit()

    if ctx.invoked_subcommand is None:
        # Open TUI
        from prism.app import run_tui
        run_tui()


# ---------------------------------------------------------------------------
# prism analyze
# ---------------------------------------------------------------------------

@app.command("analyze")
def analyze_cmd(
    project: Optional[Path] = typer.Option(
        None,
        "--project",
        "-p",
        help="Path to a specific project directory to analyze.",
        exists=False,
    ),
    output_json: bool = typer.Option(
        False,
        "--json",
        help="Output results as JSON.",
    ),
    base_dir: Optional[Path] = typer.Option(
        None,
        "--base-dir",
        help="Override ~/.claude/projects/ directory.",
        hidden=True,
    ),
) -> None:
    """Print a health report for all projects (or one project)."""
    projects = _resolve_projects(project, base_dir)
    if not projects:
        _no_projects_error(base_dir)
        raise typer.Exit(1)

    reports = []
    for proj in projects:
        try:
            report = analyze_project(proj)
            reports.append((proj, report))
        except Exception as exc:
            err_console.print(f"[yellow]Warning: Could not analyze {proj.encoded_name}: {exc}[/yellow]")

    if output_json:
        _print_json(reports)
    else:
        _print_rich_report(reports)


def _print_rich_report(reports: list) -> None:
    """Print a Rich-formatted health report table."""
    table = Table(
        title="◈ PRISM Health Report",
        show_header=True,
        header_style="bold cyan",
        border_style="#30363d",
    )
    table.add_column("Project", style="#e6edf3", no_wrap=True, max_width=35)
    table.add_column("Sessions", justify="right", style="#8b949e")
    table.add_column("Token Eff.", justify="center")
    table.add_column("Tool Health", justify="center")
    table.add_column("Ctx Hygiene", justify="center")
    table.add_column("MD Adherence", justify="center")
    table.add_column("Continuity", justify="center")
    table.add_column("Overall", justify="center", style="bold")

    def grade_color(grade: str) -> str:
        if not grade or grade in ("?", "N/A"):
            return "#8b949e"
        letter = grade[0]
        return {
            "A": "#3fb950",
            "B": "#58a6ff",
            "C": "#d29922",
            "D": "#f85149",
            "F": "#ff7b72",
        }.get(letter, "#8b949e")

    for proj, report in reports:
        def gc(g: str) -> Text:
            return Text(g, style=grade_color(g))

        table.add_row(
            proj.display_name[-35:],
            str(report.session_count),
            gc(report.token_efficiency.grade),
            gc(report.tool_health.grade),
            gc(report.context_hygiene.grade),
            gc(report.claude_md_adherence.grade),
            gc(report.session_continuity.grade),
            gc(report.overall_grade),
        )

    console.print()
    console.print(table)

    # Print top issues for each project
    for proj, report in reports:
        if report.top_issues:
            console.print(f"\n[bold cyan]{proj.display_name}[/bold cyan] — top issues:")
            for issue in report.top_issues[:5]:
                color = {"high": "red", "medium": "yellow", "low": "dim"}.get(issue.severity, "white")
                console.print(f"  [{color}]! {issue.description[:100]}[/{color}]")

    console.print()


def _print_json(reports: list) -> None:
    """Output analysis results as JSON."""
    output = []
    for proj, report in reports:
        output.append({
            "project": proj.encoded_name,
            "display_name": proj.display_name,
            "session_count": report.session_count,
            "overall_grade": report.overall_grade,
            "overall_score": round(report.overall_score, 1),
            "dimensions": {
                "token_efficiency": {
                    "grade": report.token_efficiency.grade,
                    "score": round(report.token_efficiency.score, 1),
                    "compaction_count": report.token_efficiency.compaction_count,
                },
                "tool_health": {
                    "grade": report.tool_health.grade,
                    "score": round(report.tool_health.score, 1),
                    "retry_loop_count": report.tool_health.retry_loop_count,
                    "interactive_call_count": report.tool_health.interactive_call_count,
                },
                "context_hygiene": {
                    "grade": report.context_hygiene.grade,
                    "score": round(report.context_hygiene.score, 1),
                    "compaction_count": report.context_hygiene.compaction_count,
                },
                "claude_md_adherence": {
                    "grade": report.claude_md_adherence.grade,
                    "score": round(report.claude_md_adherence.score, 1),
                    "rules_violated": report.claude_md_adherence.rules_violated,
                },
                "session_continuity": {
                    "grade": report.session_continuity.grade,
                    "score": round(report.session_continuity.score, 1),
                    "truncated_sessions": report.session_continuity.truncated_sessions,
                },
            },
            "top_issues": [
                {
                    "severity": i.severity,
                    "category": i.category,
                    "description": i.description,
                }
                for i in report.top_issues[:5]
            ],
        })
    console.print(json.dumps(output, indent=2))


# ---------------------------------------------------------------------------
# prism advise
# ---------------------------------------------------------------------------

@app.command("advise")
def advise_cmd(
    project: Optional[Path] = typer.Option(
        None,
        "--project",
        "-p",
        help="Path to a specific project directory.",
        exists=False,
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Apply ADD recommendations to CLAUDE.md (with confirmation).",
    ),
    base_dir: Optional[Path] = typer.Option(
        None,
        "--base-dir",
        help="Override ~/.claude/projects/ directory.",
        hidden=True,
    ),
) -> None:
    """Print concrete CLAUDE.md recommendations as a colored diff."""
    from prism.advisor import apply_advice, format_advice_rich, generate_advice

    projects = _resolve_projects(project, base_dir)
    if not projects:
        _no_projects_error(base_dir)
        raise typer.Exit(1)

    # Use the first (most recent) project if no --project given
    proj = projects[0]
    try:
        report = analyze_project(proj)
    except Exception as exc:
        err_console.print(f"[red]Error analyzing project: {exc}[/red]")
        raise typer.Exit(1)

    # Find CLAUDE.md
    claude_md_path = _find_claude_md(proj)

    advisor_report = generate_advice(report, claude_md_path)
    console.print(format_advice_rich(advisor_report), markup=True)

    if apply and claude_md_path:
        result = apply_advice(advisor_report, claude_md_path, confirm=True)
        if result:
            console.print(f"\n[green]✓ Applied recommendations to {claude_md_path}[/green]")
        else:
            console.print("\n[dim]No changes applied.[/dim]")
    elif apply and not claude_md_path:
        err_console.print("[yellow]Warning: CLAUDE.md not found — cannot apply.[/yellow]")


# ---------------------------------------------------------------------------
# prism replay
# ---------------------------------------------------------------------------

@app.command("replay")
def replay_cmd(
    session: str = typer.Argument(
        ...,
        help="Session ID or path to a .jsonl file.",
    ),
) -> None:
    """Open an interactive timeline view of a single session."""
    from prism.app import PrismApp, ReplayScreen
    from textual.app import App

    session_path = _resolve_session_path(session)
    if session_path is None:
        err_console.print(f"[red]Session not found: {session}[/red]")
        raise typer.Exit(1)

    class ReplayApp(App):
        CSS_PATH = Path(__file__).parent / "styles" / "prism.tcss"
        TITLE = f"◈ PRISM — Replay: {session_path.stem}"

        def on_mount(self) -> None:
            self.push_screen(ReplayScreen(session_path))

    ReplayApp().run()


# ---------------------------------------------------------------------------
# prism watch
# ---------------------------------------------------------------------------

@app.command("watch")
def watch_cmd(
    base_dir: Optional[Path] = typer.Option(
        None,
        "--base-dir",
        help="Override ~/.claude/projects/ directory.",
        hidden=True,
    ),
) -> None:
    """Live mode — watch active session in real time."""
    from prism.app import LiveScreen, PrismApp
    from textual.app import App

    watch_base = base_dir or CLAUDE_PROJECTS_DIR

    class WatchApp(App):
        CSS_PATH = Path(__file__).parent / "styles" / "prism.tcss"
        TITLE = "◈ PRISM — Live Watch"
        BINDINGS = [("q", "quit", "Quit")]

        def on_mount(self) -> None:
            self.push_screen(LiveScreen(base_dir=watch_base))

        def action_quit(self) -> None:
            self.exit()

    WatchApp().run()


# ---------------------------------------------------------------------------
# prism projects
# ---------------------------------------------------------------------------

@app.command("projects")
def projects_cmd(
    base_dir: Optional[Path] = typer.Option(
        None,
        "--base-dir",
        help="Override ~/.claude/projects/ directory.",
        hidden=True,
    ),
) -> None:
    """List all Claude Code projects with session counts and last-used dates."""
    import time

    projects = discover_projects(base_dir or CLAUDE_PROJECTS_DIR)
    if not projects:
        _no_projects_error(base_dir)
        raise typer.Exit(1)

    table = Table(
        title="◈ PRISM — Claude Code Projects",
        show_header=True,
        header_style="bold cyan",
        border_style="#30363d",
    )
    table.add_column("Project", style="#e6edf3", max_width=50)
    table.add_column("Sessions", justify="right", style="#8b949e")
    table.add_column("Last Active", justify="right", style="#8b949e")

    now = time.time()
    for proj in projects:
        mtime = proj.session_files[0].stat().st_mtime if proj.session_files else 0
        from prism.app import _format_ago
        last = _format_ago(mtime) if mtime else "never"
        table.add_row(
            proj.display_name[-50:],
            str(len(proj.session_files)),
            last,
        )

    console.print()
    console.print(table)
    console.print(
        f"\n[dim]{len(projects)} project(s) found in "
        f"{base_dir or CLAUDE_PROJECTS_DIR}[/dim]\n"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_projects(
    project_path: Path | None,
    base_dir: Path | None,
) -> list[ProjectInfo]:
    """Return a list of ProjectInfo objects based on CLI options.

    The ``--project`` flag accepts any of:

    * The actual path to a Claude Code project directory (inside
      ``~/.claude/projects/``), e.g. ``~/.claude/projects/D--jarvis-space``.
    * The real absolute path of the user's workspace on any OS, e.g.
      ``D:\\jarvis\\space`` or ``/home/user/proj``.  The path is encoded
      to the Claude Code convention and looked up under *effective_base*.
    * The display name shown in the projects table, e.g. ``D//jarvis/space``
      or ``/home/user/proj``.  Forward-slash normalisation by ``pathlib``
      means this is equivalent to passing the real path on most systems.
    """
    effective_base = base_dir or CLAUDE_PROJECTS_DIR

    if project_path is not None:
        # Strategy 1: the argument is already a Claude Code project directory
        # that contains JSONL session files — use it directly.
        if project_path.is_dir():
            sessions = sorted(
                project_path.glob("*.jsonl"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if sessions:
                return [ProjectInfo(
                    encoded_name=project_path.name,
                    project_dir=project_path,
                    session_files=sessions,
                )]

        # Strategy 2: interpret the argument as a real path or display name
        # and look up the corresponding encoded directory inside effective_base.
        encoded = project_path_to_encoded_name(str(project_path))
        candidate = effective_base / encoded
        if candidate.is_dir():
            sessions = sorted(
                candidate.glob("*.jsonl"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            return [ProjectInfo(
                encoded_name=encoded,
                project_dir=candidate,
                session_files=sessions,
            )]

        err_console.print(f"[red]Project not found: {project_path}[/red]")
        err_console.print(
            f"[dim]Tried encoded name '{encoded}' in {effective_base}[/dim]"
        )
        return []

    return discover_projects(effective_base)


def _resolve_session_path(session: str) -> Path | None:
    """Resolve a session ID or file path to a Path object."""
    # Direct file path
    p = Path(session)
    if p.exists() and p.suffix == ".jsonl":
        return p

    # Session ID — search all project dirs
    base = CLAUDE_PROJECTS_DIR
    if base.exists():
        for proj_dir in base.iterdir():
            if proj_dir.is_dir():
                candidate = proj_dir / f"{session}.jsonl"
                if candidate.exists():
                    return candidate
                # Also try partial match
                for jf in proj_dir.glob("*.jsonl"):
                    if jf.stem.startswith(session):
                        return jf
    return None


def _find_claude_md(project: ProjectInfo) -> Path | None:
    """Try to find CLAUDE.md for a project by checking session cwds."""
    for session_file in project.session_files[:3]:
        result = parse_session_file(session_file)
        if result.records:
            cwd = Path(result.records[0].cwd)
            candidate = cwd / "CLAUDE.md"
            if candidate.exists():
                return candidate
    return None


def _no_projects_error(base_dir: Path | None) -> None:
    location = base_dir or CLAUDE_PROJECTS_DIR
    err_console.print(
        f"\n[yellow]No Claude Code sessions found.[/yellow]\n"
        f"Have you used Claude Code yet?\n"
        f"Looking in: [dim]{location}[/dim]\n"
    )
