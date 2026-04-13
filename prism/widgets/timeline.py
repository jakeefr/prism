"""Timeline widget — session replay scrubber."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from pathlib import Path

from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView, RichLog

from prism.analyzer import estimate_record_tokens
from prism.parser import AssistantRecord, SessionRecord, SystemRecord, UserRecord


@dataclass
class TurnEntry:
    """A single turn row in the timeline."""
    index: int
    label: str          # "T01", "T02", etc.
    record_type: str    # "user" | "assistant" | "tool:Bash" | "system" | etc.
    token_estimate: int
    is_warning: bool
    warning_text: str
    css_class: str
    record: SessionRecord


def _classify_record(record: SessionRecord, idx: int) -> TurnEntry:
    """Turn a parsed record into a TurnEntry for the timeline."""
    tokens = estimate_record_tokens(record)
    label = f"T{idx + 1:02d}"
    is_warning = False
    warning_text = ""
    css_class = ""
    record_type = record.type

    if isinstance(record, SystemRecord):
        record_type = f"system:{record.subtype or 'msg'}"
        css_class = "timeline-system"

    elif isinstance(record, AssistantRecord):
        # Check for tool_use blocks
        tool_blocks = [b for b in record.content if b.type == "tool_use"]
        if tool_blocks:
            tool_name = tool_blocks[0].tool_name or "tool"
            record_type = f"tool:{tool_name}"
            css_class = "timeline-tool-use"
            # Check for interactive commands
            for block in tool_blocks:
                if block.tool_name == "Bash" and block.tool_input:
                    cmd = block.tool_input.get("command", "")
                    if "--watch" in cmd or ("npm init" in cmd and "--yes" not in cmd):
                        is_warning = True
                        warning_text = f"Interactive command: {cmd[:60]}"
                        css_class = "timeline-warning"
        else:
            css_class = "timeline-assistant"

    elif isinstance(record, UserRecord):
        # Check if it's a tool result
        result_blocks = [b for b in record.content if b.type == "tool_result"]
        if result_blocks:
            record_type = "tool:result"
            css_class = "timeline-tool-result"
            # Check for errors in result
            content_str = str(result_blocks[0].tool_content or "")
            if any(kw in content_str.lower() for kw in ("error", "failed", "exit code 1")):
                is_warning = True
                warning_text = f"Error in result: {content_str[:60]}"
                css_class = "timeline-warning"
        else:
            css_class = "timeline-user"

    return TurnEntry(
        index=idx,
        label=label,
        record_type=record_type,
        token_estimate=tokens,
        is_warning=is_warning,
        warning_text=warning_text,
        css_class=css_class,
        record=record,
    )


class TurnListItem(ListItem):
    """A single row in the timeline list."""

    def __init__(self, entry: TurnEntry, cumulative_tokens: int, **kwargs) -> None:
        super().__init__(**kwargs)
        self.entry = entry
        self.cumulative_tokens = cumulative_tokens

    def compose(self) -> ComposeResult:
        warn = " ⚠" if self.entry.is_warning else "  "
        tokens_k = self.entry.token_estimate / 1000
        css = self.entry.css_class
        if isinstance(self.entry.record, SystemRecord):
            yield Label(
                f"  ── {self.entry.record_type} ──",
                classes="timeline-system",
            )
        else:
            yield Label(
                f" {warn}{self.entry.label}  {self.entry.record_type:<20}  {tokens_k:.1f}k",
                classes=css,
            )


class Timeline(Widget):
    """Session replay timeline widget.

    Left panel: scrollable list of turns.
    Right panel: detail view of selected turn.
    """

    class TurnSelected(Message):
        def __init__(self, entry: TurnEntry) -> None:
            super().__init__()
            self.entry = entry

    selected_index: reactive[int] = reactive(0)

    DEFAULT_CSS = """
    Timeline {
        layout: horizontal;
        height: 1fr;
    }
    #tl-list {
        width: 1fr;
        border: round #30363d;
        background: #161b22;
    }
    #tl-detail {
        width: 1fr;
        border: round #30363d;
        background: #161b22;
        padding: 1 2;
    }
    """

    def __init__(
        self,
        records: list[SessionRecord] | None = None,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._records = records or []
        self._entries: list[TurnEntry] = []
        self._cumulative: list[int] = []

    def on_mount(self) -> None:
        self._build_entries()
        self._render_list()

    def _build_entries(self) -> None:
        self._entries = [_classify_record(r, i) for i, r in enumerate(self._records)]
        cumulative = 0
        self._cumulative = []
        for e in self._entries:
            cumulative += e.token_estimate
            self._cumulative.append(cumulative)

    def _render_list(self) -> None:
        try:
            lv = self.query_one("#tl-list", ListView)
            items = [
                TurnListItem(e, self._cumulative[i] if i < len(self._cumulative) else 0)
                for i, e in enumerate(self._entries)
            ]
            lv.clear()
            for item in items:
                lv.append(item)
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        yield ListView(id="tl-list")
        yield RichLog(id="tl-detail", highlight=True, markup=True)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        event.stop()
        if isinstance(event.item, TurnListItem):
            entry = event.item.entry
            self.selected_index = entry.index
            self._show_detail(entry, event.item.cumulative_tokens)
            self.post_message(self.TurnSelected(entry))

    def _show_detail(self, entry: TurnEntry, cumulative: int) -> None:
        try:
            log = self.query_one("#tl-detail", RichLog)
            log.clear()
            log.write(f"[bold cyan]Turn {entry.index + 1} — {entry.record_type}[/bold cyan]")
            log.write("")

            record = entry.record
            if isinstance(record, AssistantRecord):
                for block in record.content:
                    if block.type == "text" and block.text:
                        log.write(f"[white]{block.text[:300]}[/white]")
                    elif block.type == "tool_use":
                        log.write(f"[yellow]Tool: {block.tool_name}[/yellow]")
                        if block.tool_input:
                            for k, v in block.tool_input.items():
                                log.write(f"  [dim]{k}:[/dim] {str(v)[:120]}")

            elif isinstance(record, UserRecord):
                for block in record.content:
                    if block.type == "text" and block.text:
                        log.write(f"[cyan]{block.text[:300]}[/cyan]")
                    elif block.type == "tool_result":
                        content_str = str(block.tool_content or "")[:300]
                        log.write(f"[white]{content_str}[/white]")

            elif isinstance(record, SystemRecord):
                if record.summary:
                    log.write(f"[dim]{record.summary[:300]}[/dim]")

            log.write("")
            if entry.is_warning:
                log.write(f"[bold red]⚠ {entry.warning_text}[/bold red]")

            log.write(f"[dim]Tokens this turn: {entry.token_estimate:,}[/dim]")
            log.write(f"[dim]Cumulative: {cumulative / 1000:.1f}k[/dim]")

        except Exception:
            pass

    def load_records(self, records: list[SessionRecord]) -> None:
        """Load new records and re-render."""
        self._records = records
        self._build_entries()
        self._render_list()
