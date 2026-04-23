"""LiveWatcher widget — real-time session file watcher."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, RichLog

from prism.parser import (
    CLAUDE_PROJECTS_DIR,
    AssistantRecord,
    SystemRecord,
    parse_session_file,
)
from prism.analyzer import estimate_record_tokens


class LiveWatcher(Widget):
    """Split panel: left = real-time event stream, right = live metrics.

    Polls the most recently modified JSONL file in ~/.claude/projects/.
    Updates on a 2-second interval.
    """

    class SessionUpdated(Message):
        """Emitted when live session data refreshes."""
        def __init__(
            self,
            token_count: int,
            tool_calls: int,
            compaction_risk: float,
        ) -> None:
            super().__init__()
            self.token_count = token_count
            self.tool_calls = tool_calls
            self.compaction_risk = compaction_risk

    DEFAULT_CSS = """
    LiveWatcher {
        layout: horizontal;
        height: 1fr;
    }
    #live-events-panel {
        width: 2fr;
        border: round #30363d;
        background: #161b22;
        padding: 0 1;
    }
    #live-metrics-panel {
        width: 1fr;
        border: round #30363d;
        background: #161b22;
        padding: 1 2;
        layout: vertical;
    }
    """

    token_count: reactive[int] = reactive(0)
    tool_call_count: reactive[int] = reactive(0)
    compaction_risk: reactive[float] = reactive(0.0)

    def __init__(
        self,
        base_dir: Path | None = None,
        max_context_tokens: int = 200_000,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._base_dir = base_dir or CLAUDE_PROJECTS_DIR
        self._max_context = max_context_tokens
        self._watch_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._current_file: Path | None = None

    def compose(self) -> ComposeResult:
        yield RichLog(
            id="live-events-panel",
            highlight=True,
            markup=True,
            wrap=True,
        )
        yield self._build_metrics_panel()

    def _build_metrics_panel(self) -> Widget:
        from textual.containers import Vertical
        from prism.widgets.metrics_bar import CompactionRiskBar

        class MetricsPanel(Widget):
            DEFAULT_CSS = """
            MetricsPanel {
                layout: vertical;
                height: 1fr;
                padding: 1 2;
            }
            """
            def compose(self) -> ComposeResult:
                yield Label(" LIVE METRICS", classes="section-title")
                yield Label("─" * 28, classes="dim")
                yield Label("Tokens:", classes="live-metric-label")
                yield Label("0", id="live-tokens", classes="live-metric-value")
                yield Label("Tool calls:", classes="live-metric-label")
                yield Label("0", id="live-tools", classes="live-metric-value")
                yield Label("Compactions:", classes="live-metric-label")
                yield Label("0", id="live-compactions", classes="live-metric-value")
                yield Label("")
                yield Label("Context usage:", classes="live-metric-label")
                yield Label("░" * 20, id="live-bar", classes="compaction-risk-low")
                yield Label("0%", id="live-pct", classes="compaction-risk-low")

        return MetricsPanel(id="live-metrics-panel")

    def on_mount(self) -> None:
        self._start_watching()
        # Update metrics every 2 seconds via set_interval
        self.set_interval(2.0, self._poll_and_update)

    def on_unmount(self) -> None:
        self._stop_event.set()

    def _find_active_session(self) -> Path | None:
        """Find the most recently modified JSONL file."""
        if not self._base_dir.exists():
            return None
        newest: Path | None = None
        newest_mtime = 0.0
        try:
            for proj_dir in self._base_dir.iterdir():
                if not proj_dir.is_dir():
                    continue
                for jf in proj_dir.glob("*.jsonl"):
                    try:
                        mtime = jf.stat().st_mtime
                        if mtime > newest_mtime:
                            newest_mtime = mtime
                            newest = jf
                    except OSError:
                        pass
        except OSError:
            pass
        return newest

    def _poll_and_update(self) -> None:
        """Poll active session and update the display."""
        active = self._find_active_session()
        if active is None:
            self._emit_no_session()
            return

        result = parse_session_file(active)
        if not result.records:
            return

        total_tokens = sum(estimate_record_tokens(r) for r in result.records)
        tool_calls = sum(
            1 for r in result.records
            if isinstance(r, AssistantRecord)
            for b in r.content
            if b.type == "tool_use"
        )
        compactions = sum(
            1 for r in result.records
            if isinstance(r, SystemRecord) and r.subtype == "compact_boundary"
        )
        risk = min(1.0, total_tokens / self._max_context)

        self._update_metrics_display(total_tokens, tool_calls, compactions, risk)
        self._update_event_log(active, result.records[-10:] if result.records else [])
        self.post_message(self.SessionUpdated(total_tokens, tool_calls, risk))

    def _emit_no_session(self) -> None:
        try:
            log = self.query_one("#live-events-panel", RichLog)
            log.write("[dim]No active session found. Watching...[/dim]")
        except Exception:
            pass

    def _update_metrics_display(
        self,
        tokens: int,
        tools: int,
        compactions: int,
        risk: float,
    ) -> None:
        try:
            self.query_one("#live-tokens", Label).update(f"{tokens / 1000:.1f}k")
            self.query_one("#live-tools", Label).update(str(tools))
            self.query_one("#live-compactions", Label).update(str(compactions))

            filled = round(risk * 20)
            bar = "█" * filled + "░" * (20 - filled)
            pct = f"{risk * 100:.0f}%"

            bar_label = self.query_one("#live-bar", Label)
            pct_label = self.query_one("#live-pct", Label)
            bar_label.update(bar)
            pct_label.update(pct)

            css_class = (
                "compaction-risk-high" if risk >= 0.85
                else "compaction-risk-medium" if risk >= 0.6
                else "compaction-risk-low"
            )
            for lbl in (bar_label, pct_label):
                lbl.remove_class(
                    "compaction-risk-low", "compaction-risk-medium", "compaction-risk-high"
                )
                lbl.add_class(css_class)

        except Exception:
            pass

    def _update_event_log(self, path: Path, records: list) -> None:
        try:
            log = self.query_one("#live-events-panel", RichLog)
            log.clear()
            log.write(f"[dim]Active: {path.name}[/dim]")
            log.write("")
            for record in records:
                if hasattr(record, "content"):
                    for block in getattr(record, "content", []):
                        if block.type == "tool_use":
                            log.write(
                                f"[yellow]  → {block.tool_name}[/yellow]: "
                                f"{str(block.tool_input or '')[:60]}"
                            )
                        elif block.type == "text" and block.text:
                            log.write(f"[white]  {block.text[:80]}[/white]")
                elif hasattr(record, "subtype") and record.subtype == "compact_boundary":
                    log.write("[red]  ─── COMPACTION BOUNDARY ───[/red]")
        except Exception:
            pass

    def _start_watching(self) -> None:
        """Log a startup message."""
        try:
            log = self.query_one("#live-events-panel", RichLog)
            log.write("[cyan]  PRISM Live Watch — monitoring ~/.claude/projects/[/cyan]")
            log.write("[dim]  Polling every 2 seconds...[/dim]")
            log.write("")
        except Exception:
            pass
