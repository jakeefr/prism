"""AdvisorPanel widget — full-screen CLAUDE.md recommendations panel."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Label, RichLog

from prism.advisor import AdvisorReport, Recommendation


ACTION_COLORS = {
    "ADD": "green",
    "TRIM": "red",
    "WARN": "yellow",
    "RESTRUCTURE": "cyan",
}

ACTION_ICONS = {
    "ADD": "✦ ADD",
    "TRIM": "✦ TRIM",
    "WARN": "✦ WARN",
    "RESTRUCTURE": "✦ RESTRUCTURE",
}


class AdvisorPanel(Widget):
    """Full-screen panel showing CLAUDE.md recommendations.

    Keyboard shortcut: 'A' to apply ADD recommendations.
    """

    class ApplyRequested(Message):
        """User pressed 'A' to apply recommendations."""

    DEFAULT_CSS = """
    AdvisorPanel {
        layout: vertical;
        padding: 1 2;
        background: #0d1117;
    }
    #advisor-log {
        height: 1fr;
        border: round #30363d;
        background: #161b22;
    }
    #advisor-controls {
        height: auto;
        padding: 1 0;
        layout: horizontal;
    }
    """

    def __init__(
        self,
        report: AdvisorReport | None = None,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._report = report

    def compose(self) -> ComposeResult:
        yield Label(
            " PRISM ADVISOR — CLAUDE.md Recommendations",
            classes="section-title",
        )
        yield RichLog(id="advisor-log", highlight=True, markup=True, wrap=True)
        yield Label(
            " [A] Apply ADD recommendations   [Q] Back",
            classes="dim",
        )

    def on_mount(self) -> None:
        if self._report:
            self.load_report(self._report)

    def load_report(self, report: AdvisorReport) -> None:
        """Populate the panel with a new AdvisorReport."""
        self._report = report
        try:
            log = self.query_one("#advisor-log", RichLog)
            log.clear()

            if not report.recommendations:
                log.write("[green]  ✓ No recommendations — your CLAUDE.md looks healthy![/green]")
                return

            for rec in report.recommendations:
                color = ACTION_COLORS.get(rec.action, "white")
                icon = ACTION_ICONS.get(rec.action, f"✦ {rec.action}")
                log.write(
                    f"[bold {color}]{icon}[/bold {color}]  "
                    f"([bold]{rec.impact} impact[/bold] — {rec.rationale})"
                )
                for line in rec.content.splitlines():
                    log.write(f"  [white]{line}[/white]")
                if rec.session_evidence:
                    log.write(f"  [dim]Sessions: {rec.session_evidence}[/dim]")
                log.write("")

        except Exception:
            pass

    def on_key(self, event) -> None:
        if event.key == "a":
            self.post_message(self.ApplyRequested())
