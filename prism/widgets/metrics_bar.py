"""MetricsBar widget — token usage sparklines and progress bars."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label


def _bar(value: float, max_value: float, width: int = 20, warn_threshold: float = 0.7) -> str:
    """Render a block progress bar with color-coded fill."""
    if max_value <= 0:
        ratio = 0.0
    else:
        ratio = min(1.0, value / max_value)
    filled = round(ratio * width)
    empty = width - filled
    return "█" * filled + "░" * empty


def _bar_class(ratio: float) -> str:
    """Return CSS class based on fill ratio."""
    if ratio >= 0.9:
        return "live-metric-danger"
    elif ratio >= 0.7:
        return "live-metric-warn"
    else:
        return "live-metric-value"


class CompactionRiskBar(Widget):
    """A progress bar that turns red as context fills."""

    token_count: reactive[int] = reactive(0)
    max_tokens: reactive[int] = reactive(200_000)

    DEFAULT_CSS = """
    CompactionRiskBar {
        height: 3;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        token_count: int = 0,
        max_tokens: int = 200_000,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.token_count = token_count
        self.max_tokens = max_tokens

    def compose(self) -> ComposeResult:
        yield Label("Compaction Risk", classes="live-metric-label")
        yield Label(self._render_bar(), classes=self._bar_css_class(), id="risk-bar")
        yield Label(self._pct_text(), classes=self._bar_css_class(), id="risk-pct")

    def _ratio(self) -> float:
        return min(1.0, self.token_count / max(1, self.max_tokens))

    def _render_bar(self) -> str:
        ratio = self._ratio()
        filled = round(ratio * 20)
        return "█" * filled + "░" * (20 - filled)

    def _bar_css_class(self) -> str:
        ratio = self._ratio()
        if ratio >= 0.85:
            return "compaction-risk-high"
        elif ratio >= 0.6:
            return "compaction-risk-medium"
        return "compaction-risk-low"

    def _pct_text(self) -> str:
        pct = self._ratio() * 100
        return f"{pct:.0f}% of context used"

    def _refresh_labels(self) -> None:
        try:
            bar = self.query_one("#risk-bar", Label)
            bar.update(self._render_bar())
            bar.remove_class("compaction-risk-low", "compaction-risk-medium", "compaction-risk-high")
            bar.add_class(self._bar_css_class())

            pct = self.query_one("#risk-pct", Label)
            pct.update(self._pct_text())
            pct.remove_class("compaction-risk-low", "compaction-risk-medium", "compaction-risk-high")
            pct.add_class(self._bar_css_class())
        except Exception:
            pass

    def watch_token_count(self, _: int) -> None:
        self._refresh_labels()

    def watch_max_tokens(self, _: int) -> None:
        self._refresh_labels()


class MetricsBar(Widget):
    """Displays key metrics as a horizontal bar with sparklines.

    Shows: token count, tool calls, compaction risk.
    """

    DEFAULT_CSS = """
    MetricsBar {
        height: auto;
        padding: 0 1;
        border: round #30363d;
        background: #161b22;
        layout: horizontal;
    }
    .metric-block {
        width: 1fr;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        total_tokens: int = 0,
        tool_call_count: int = 0,
        compaction_count: int = 0,
        session_count: int = 0,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._total_tokens = total_tokens
        self._tool_call_count = tool_call_count
        self._compaction_count = compaction_count
        self._session_count = session_count

    def compose(self) -> ComposeResult:
        tokens_k = self._total_tokens / 1000
        yield Label(
            f"Tokens: [bold]{tokens_k:.1f}k[/bold]",
            classes="metric-block accent",
            markup=True,
        )
        yield Label(
            f"Tool calls: [bold]{self._tool_call_count}[/bold]",
            classes="metric-block",
            markup=True,
        )
        yield Label(
            f"Compactions: [bold]{self._compaction_count}[/bold]",
            classes="metric-block warning" if self._compaction_count > 0 else "metric-block",
            markup=True,
        )
        yield Label(
            f"Sessions: [bold]{self._session_count}[/bold]",
            classes="metric-block dim",
            markup=True,
        )
