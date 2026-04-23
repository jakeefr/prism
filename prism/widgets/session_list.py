"""SessionList widget — scrollable project/session browser."""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView


@dataclass
class ProjectEntry:
    """Data for a single row in the project list."""
    encoded_name: str
    display_name: str
    session_count: int
    last_active_str: str
    overall_grade: str
    overall_score: float


def _grade_bar(score: float, width: int = 10) -> str:
    """Return a simple block bar representing a 0–100 score."""
    filled = max(0, min(width, round(score / 100 * width)))
    return "█" * filled + "░" * (width - filled)


def _grade_to_class(grade: str) -> str:
    if not grade or grade == "N/A":
        return "project-grade-f"
    letter = grade[0].upper()
    return {
        "A": "project-grade-a",
        "B": "project-grade-b",
        "C": "project-grade-c",
        "D": "project-grade-d",
        "F": "project-grade-f",
    }.get(letter, "project-grade-f")


class ProjectListItem(ListItem):
    """A single row in the project list."""

    def __init__(self, entry: ProjectEntry, **kwargs) -> None:
        super().__init__(**kwargs)
        self.entry = entry

    def compose(self) -> ComposeResult:
        grade_class = _grade_to_class(self.entry.overall_grade)
        bar = _grade_bar(self.entry.overall_score)
        active_dot = "●" if self.entry.session_count > 0 else "○"

        yield Label(
            f" {active_dot} {self.entry.display_name:<30}  "
            f"last: {self.entry.last_active_str:<12}  "
            f"{bar}  ",
            classes="project-name",
        )
        yield Label(
            f"{self.entry.overall_grade:>3}",
            classes=grade_class,
        )


class SessionList(Widget):
    """Scrollable list of projects with health scores.

    Emits a ProjectSelected message when the user selects a project.
    """

    class ProjectSelected(Message):
        """Emitted when a project row is selected."""
        def __init__(self, entry: ProjectEntry) -> None:
            super().__init__()
            self.entry = entry

    entries: reactive[list[ProjectEntry]] = reactive(list, recompose=True)

    DEFAULT_CSS = """
    SessionList {
        height: 1fr;
        border: round #30363d;
        background: #161b22;
    }
    """

    def __init__(
        self,
        entries: list[ProjectEntry] | None = None,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.entries = entries or []

    def compose(self) -> ComposeResult:
        items = [ProjectListItem(e) for e in self.entries]
        yield ListView(*items, id="project-listview")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        event.stop()
        if isinstance(event.item, ProjectListItem):
            self.post_message(self.ProjectSelected(event.item.entry))

    def update_entries(self, entries: list[ProjectEntry]) -> None:
        """Replace the list content with new entries."""
        self.entries = entries
