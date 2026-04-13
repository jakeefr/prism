"""HealthCard widget — displays a single health dimension score."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label


def _grade_css_class(grade: str) -> str:
    """Return the CSS class for a letter grade."""
    if not grade or grade == "N/A":
        return "dim"
    letter = grade[0].upper()
    return {
        "A": "health-a",
        "B": "health-b",
        "C": "health-c",
        "D": "health-d",
        "F": "health-f",
    }.get(letter, "dim")


class HealthCard(Widget):
    """A compact card showing a health dimension grade + brief detail.

    Usage:
        HealthCard("Token Efficiency", "B+", "23 sessions")
    """

    DEFAULT_CSS = """
    HealthCard {
        border: round #30363d;
        padding: 1 2;
        background: #161b22;
        min-width: 18;
        min-height: 6;
    }
    """

    title: reactive[str] = reactive("Dimension")
    grade: reactive[str] = reactive("?")
    detail: reactive[str] = reactive("")

    def __init__(
        self,
        title: str,
        grade: str = "?",
        detail: str = "",
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.title = title
        self.grade = grade
        self.detail = detail

    def compose(self) -> ComposeResult:
        grade_class = _grade_css_class(self.grade)
        yield Label(self.title, classes="health-card-title")
        yield Label(self.grade, classes=f"health-card-grade {grade_class}")
        yield Label(self.detail, classes="health-card-detail dim")

    def update(self, title: str, grade: str, detail: str) -> None:
        """Update the card's content."""
        self.title = title
        self.grade = grade
        self.detail = detail
        self.refresh()

    def on_mount(self) -> None:
        self.refresh()

    def watch_grade(self, new_grade: str) -> None:
        """Re-render when grade changes."""
        try:
            grade_label = self.query_one(".health-card-grade", Label)
            grade_class = _grade_css_class(new_grade)
            grade_label.update(new_grade)
            # Reset and re-apply classes
            grade_label.remove_class(
                "health-a", "health-b", "health-c", "health-d", "health-f", "dim"
            )
            grade_label.add_class(grade_class)
        except Exception:
            pass

    def watch_detail(self, new_detail: str) -> None:
        try:
            detail_label = self.query_one(".health-card-detail", Label)
            detail_label.update(new_detail)
        except Exception:
            pass

    def watch_title(self, new_title: str) -> None:
        try:
            title_label = self.query_one(".health-card-title", Label)
            title_label.update(new_title)
        except Exception:
            pass
