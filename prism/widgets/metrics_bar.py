"""MetricsBar widget — token usage sparklines and progress bars."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label


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
