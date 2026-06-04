"""JSONL parser for Claude Code session files.

Reads raw records from session JSONL files. No analysis here — just parsing.
Returns typed dataclasses for downstream analysis.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"


# ---------------------------------------------------------------------------
# Record dataclasses — mirror the JSONL envelope + typed subtypes
# ---------------------------------------------------------------------------

@dataclass
class Envelope:
    """Common fields present on every JSONL record."""
    uuid: str
    parent_uuid: str | None
    is_sidechain: bool
    session_id: str
    timestamp: str
    version: str
    cwd: str
    git_branch: str | None
    type: str  # "user" | "assistant" | "system"
    raw: dict[str, Any] = field(repr=False)


@dataclass
class ContentBlock:
    """A single block within a message's content array."""
    type: str  # "text" | "thinking" | "tool_use" | "tool_result"
    text: str | None = None
    thinking: str | None = None
    tool_use_id: str | None = None
    tool_id: str | None = None
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    tool_content: Any = None  # tool_result content
    is_error: bool | None = None  # tool_result error flag; None when absent


@dataclass
class UserRecord(Envelope):
    """A user-role message (includes tool results)."""
    content: list[ContentBlock] = field(default_factory=list)


@dataclass
class AssistantRecord(Envelope):
    """An assistant-role message (text + tool_use blocks)."""
    content: list[ContentBlock] = field(default_factory=list)
    actual_tokens: int | None = field(default=None, repr=False)


@dataclass
class SystemRecord(Envelope):
    """A system record (e.g. compact_boundary)."""
    subtype: str | None = None
    summary: str | None = None


# Convenience union type
SessionRecord = UserRecord | AssistantRecord | SystemRecord


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_content_blocks(content_raw: Any) -> list[ContentBlock]:
    """Parse a content array from a message into ContentBlock objects.

    Current Claude Code versions emit some messages (continuations, command
    caveats, plain prompts) with ``content`` as a bare string rather than a
    block array — treat those as a single text block.
    """
    if isinstance(content_raw, str):
        return [ContentBlock(type="text", text=content_raw)] if content_raw else []
    if not isinstance(content_raw, list):
        return []

    blocks: list[ContentBlock] = []
    for item in content_raw:
        if not isinstance(item, dict):
            continue
        block_type = item.get("type", "")

        if block_type == "text":
            blocks.append(ContentBlock(type="text", text=item.get("text", "")))

        elif block_type == "thinking":
            blocks.append(ContentBlock(type="thinking", thinking=item.get("thinking", "")))

        elif block_type == "tool_use":
            blocks.append(ContentBlock(
                type="tool_use",
                tool_id=item.get("id"),
                tool_name=item.get("name"),
                tool_input=item.get("input") if isinstance(item.get("input"), dict) else {},
            ))

        elif block_type == "tool_result":
            raw_is_error = item.get("is_error")
            blocks.append(ContentBlock(
                type="tool_result",
                tool_use_id=item.get("tool_use_id"),
                tool_content=item.get("content"),
                is_error=raw_is_error if isinstance(raw_is_error, bool) else None,
            ))

        else:
            # Unknown block type — store as generic
            blocks.append(ContentBlock(type=block_type))

    return blocks


def _extract_text_from_blocks(blocks: list[ContentBlock]) -> str:
    """Join text blocks into a single string for classification."""
    return " ".join(b.text for b in blocks if b.text)


def classify_system_message(text: str) -> str | None:
    """Classify user-record content as a system subtype, or None.

    Mirrors agentsview's ClassifyClaudeSystemMessage.
    """
    t = text.lstrip("﻿").strip()
    if t.startswith("This session is being continued"):
        return "continuation"
    if t.startswith("<local-command-caveat>"):
        return "resume"
    if t.startswith("[Request interrupted"):
        return "interrupted"
    if t.startswith("<task-notification>"):
        return "task_notification"
    if t.startswith("Stop hook feedback:"):
        return "stop_hook"
    return None


def _extract_output_tokens(message: Any) -> int | None:
    """Pull message.usage.output_tokens when present and well-formed.

    Returns None otherwise so callers fall back to the chars/4 estimate.
    """
    if not isinstance(message, dict):
        return None
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None
    tokens = usage.get("output_tokens")
    if isinstance(tokens, bool) or not isinstance(tokens, int):
        return None
    return tokens


def _parse_envelope(data: dict[str, Any]) -> dict[str, Any]:
    """Extract common envelope fields from a raw record dict."""
    return {
        "uuid": data.get("uuid", ""),
        "parent_uuid": data.get("parentUuid"),
        "is_sidechain": bool(data.get("isSidechain", False)),
        "session_id": data.get("sessionId", ""),
        "timestamp": data.get("timestamp", ""),
        "version": data.get("version", ""),
        "cwd": data.get("cwd", ""),
        "git_branch": data.get("gitBranch"),
        "type": data.get("type", ""),
        "raw": data,
    }


def parse_record(data: dict[str, Any]) -> SessionRecord | None:
    """Parse a single JSON dict into a typed SessionRecord.

    Returns None for unrecognized or structurally invalid records.
    """
    envelope_kwargs = _parse_envelope(data)
    record_type = envelope_kwargs["type"]

    if record_type == "user":
        message = data.get("message", {})
        content_raw = message.get("content", []) if isinstance(message, dict) else []
        blocks = _parse_content_blocks(content_raw)
        text = _extract_text_from_blocks(blocks)
        subtype = classify_system_message(text)
        if subtype:
            return SystemRecord(
                **envelope_kwargs,
                subtype=subtype,
                summary=text[:200],
            )
        return UserRecord(**envelope_kwargs, content=blocks)

    elif record_type == "assistant":
        message = data.get("message", {})
        content_raw = message.get("content", []) if isinstance(message, dict) else []
        return AssistantRecord(
            **envelope_kwargs,
            content=_parse_content_blocks(content_raw),
            actual_tokens=_extract_output_tokens(message),
        )

    elif record_type == "system":
        return SystemRecord(
            **envelope_kwargs,
            subtype=data.get("subtype"),
            summary=data.get("summary"),
        )

    else:
        logger.debug("Unrecognized record type: %r", record_type)
        return None


# ---------------------------------------------------------------------------
# File-level parsing
# ---------------------------------------------------------------------------

@dataclass
class ParseResult:
    """Result of parsing a single JSONL session file."""
    path: Path
    records: list[SessionRecord]
    skipped_lines: int = 0
    truncated: bool = False  # last line was not valid JSON
    # When subagent transcripts are merged in, the per-transcript record
    # groups (main first). None when the session is a single transcript.
    transcripts: list[list[SessionRecord]] | None = field(default=None, repr=False)

    def transcript_groups(self) -> list[list[SessionRecord]]:
        """Record groups to analyze independently for order-sensitive checks."""
        if self.transcripts:
            return self.transcripts
        return [self.records] if self.records else []


def parse_session_file(path: Path) -> ParseResult:
    """Parse a single .jsonl session file into a ParseResult.

    Malformed or truncated lines are skipped; their count is recorded.
    Never raises — always returns a ParseResult (possibly empty).
    """
    records: list[SessionRecord] = []
    skipped = 0
    last_line_valid = True

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError) as exc:
        logger.warning("Cannot read %s: %s", path, exc)
        return ParseResult(path=path, records=[], skipped_lines=0, truncated=False)

    lines = text.splitlines()
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            if not isinstance(data, dict):
                skipped += 1
                last_line_valid = (i < len(lines) - 1)
                continue
            record = parse_record(data)
            if record is not None:
                records.append(record)
            last_line_valid = True
        except json.JSONDecodeError:
            skipped += 1
            last_line_valid = (i < len(lines) - 1)
            logger.debug("Skipping malformed line %d in %s", i + 1, path)

    truncated = not last_line_valid if lines else False

    return ParseResult(
        path=path,
        records=records,
        skipped_lines=skipped,
        truncated=truncated,
    )


# ---------------------------------------------------------------------------
# Incremental tail reading
# ---------------------------------------------------------------------------

class SessionTail:
    """Incremental reader for a growing session JSONL file.

    Tracks a byte offset and parses only newly appended lines per ``poll()``,
    so repeated polling of a large live session does not re-read and re-parse
    the whole file each time. ``records`` always equals what a full
    ``parse_session_file(path).records`` of the file's current complete lines
    would produce.

    Only complete lines (ending in a newline) are consumed; a partial trailing
    line — a record mid-write — stays unread until its newline arrives. A full
    re-parse would skip that partial line as malformed and pick it up complete
    on the next pass, so holding it back yields the same records.

    Truncation, rotation, and in-place replacement reset all state and
    re-read from the start. Detected two ways: the file shrank below the
    last read offset, or the file's leading bytes no longer match the
    fingerprint captured on first read (appends never change them; a
    rewrite that keeps the same leading bytes is undetectable, but session
    files start with a unique record uuid). Rotation to a *different* path
    is the caller's concern: create a new SessionTail for the new file.
    """

    _FINGERPRINT_LEN = 64

    def __init__(self, path: Path) -> None:
        self.path = path
        self.records: list[SessionRecord] = []
        self.skipped_lines = 0
        self._offset = 0  # byte offset of the next unread data
        self._fingerprint = b""  # leading bytes captured on first read

    def _reset(self) -> None:
        self.records = []
        self.skipped_lines = 0
        self._offset = 0
        self._fingerprint = b""

    def poll(self) -> list[SessionRecord]:
        """Read newly appended complete lines; return the new records.

        Never raises — an unreadable or missing file returns no new records
        and keeps existing state.
        """
        try:
            size = self.path.stat().st_size
        except OSError:
            return []

        try:
            with self.path.open("rb") as fh:
                if self._fingerprint:
                    head = fh.read(len(self._fingerprint))
                    if head != self._fingerprint:
                        # Replaced in place (size may have grown) — start over.
                        self._reset()
                if size < self._offset:
                    # Truncated/rotated — start over.
                    self._reset()
                if size == self._offset:
                    return []
                fh.seek(self._offset)
                chunk = fh.read(size - self._offset)
        except OSError:
            return []

        # Consume only up to the last newline; hold back a partial trailing
        # line. A newline byte never occurs inside a UTF-8 multibyte
        # sequence, so this boundary is always a safe decode point.
        end = chunk.rfind(b"\n")
        if end == -1:
            return []
        consumed = chunk[: end + 1]
        if self._offset == 0:
            self._fingerprint = consumed[: self._FINGERPRINT_LEN]
        self._offset += end + 1

        new_records: list[SessionRecord] = []
        for line in consumed.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                self.skipped_lines += 1
                logger.debug("Skipping malformed tail line in %s", self.path)
                continue
            if not isinstance(data, dict):
                self.skipped_lines += 1
                continue
            record = parse_record(data)
            if record is not None:
                new_records.append(record)

        self.records.extend(new_records)
        return new_records


# ---------------------------------------------------------------------------
# Project-level discovery
# ---------------------------------------------------------------------------

@dataclass
class ProjectInfo:
    """Metadata about a discovered Claude Code project."""
    encoded_name: str
    project_dir: Path
    session_files: list[Path]

    @property
    def display_name(self) -> str:
        """Decode the project directory name to a human-readable path."""
        # Claude Code encodes forward-slashes as hyphens in directory names,
        # and the directory name is the encoded absolute path of the project.
        # Best effort: replace hyphens that look like path separators.
        name = self.encoded_name
        # Try to reconstruct: leading hyphen = leading slash
        if name.startswith("-"):
            name = "/" + name[1:]
        name = name.replace("-", "/")
        return name

    @property
    def last_active(self) -> float | None:
        """Mtime of the most recently modified session file."""
        if not self.session_files:
            return None
        newest = max(self.session_files, key=lambda p: p.stat().st_mtime)
        return newest.stat().st_mtime


def project_path_to_encoded_name(path_str: str) -> str:
    """Convert a path string to a Claude Code encoded project directory name.

    Claude Code stores project sessions under ``~/.claude/projects/`` using
    directory names that are the absolute project path with every path
    separator and colon replaced by a hyphen.  This function performs that
    same normalisation so callers can look up a project by its real path
    *or* by the display name shown in the projects table.

    Examples::

        "D:\\\\jarvis\\\\space"  ->  "D--jarvis-space"   # native Windows path
        "D:/jarvis/space"       ->  "D--jarvis-space"   # forward-slash Windows
        "D//jarvis/space"       ->  "D--jarvis-space"   # display name from table
        "/home/user/proj"       ->  "-home-user-proj"   # Unix path

    Args:
        path_str: A real absolute path (any OS) or a display name from the
                  projects table.

    Returns:
        The encoded directory name used by Claude Code.
    """
    return path_str.replace("\\", "-").replace("/", "-").replace(":", "-")


def discover_projects(base_dir: Path | None = None) -> list[ProjectInfo]:
    """Discover all Claude Code projects under base_dir (default: ~/.claude/projects).

    Returns a list of ProjectInfo objects sorted by most-recently-modified first.
    Never raises — missing directory returns empty list.
    """
    if base_dir is None:
        base_dir = CLAUDE_PROJECTS_DIR

    if not base_dir.exists():
        logger.info("Claude projects directory not found: %s", base_dir)
        return []

    projects: list[ProjectInfo] = []

    try:
        for project_dir in base_dir.iterdir():
            if not project_dir.is_dir():
                continue
            session_files = sorted(
                project_dir.glob("*.jsonl"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            projects.append(ProjectInfo(
                encoded_name=project_dir.name,
                project_dir=project_dir,
                session_files=session_files,
            ))
    except (OSError, PermissionError) as exc:
        logger.warning("Error reading projects directory %s: %s", base_dir, exc)

    # Sort by most recently modified session
    def _last_mtime(p: ProjectInfo) -> float:
        if p.session_files:
            return p.session_files[0].stat().st_mtime
        return 0.0

    return sorted(projects, key=_last_mtime, reverse=True)


def load_all_sessions(project: ProjectInfo) -> list[ParseResult]:
    """Load and parse all session files for a project.

    Subagent transcripts (stored at ``<session-uuid>/subagents/agent-*.jsonl``
    next to each session file) are merged into their parent session's records.
    They are never returned as separate sessions.
    """
    results: list[ParseResult] = []
    for session_file in project.session_files:
        result = parse_session_file(session_file)
        subagents_dir = session_file.parent / session_file.stem / "subagents"
        if subagents_dir.is_dir():
            main_records = result.records
            agent_groups: list[list[SessionRecord]] = []
            for agent_file in sorted(subagents_dir.glob("*.jsonl")):
                agent_result = parse_session_file(agent_file)
                if agent_result.records:
                    agent_groups.append(agent_result.records)
                result.skipped_lines += agent_result.skipped_lines
                result.truncated = result.truncated or agent_result.truncated
            if agent_groups:
                merged = list(main_records)
                for group in agent_groups:
                    merged.extend(group)
                result.records = merged
                # Keep per-transcript groups so order-sensitive detections
                # (retry loops, failure streaks) don't chain across the seam.
                # The main transcript keeps slot 0 even when empty so callers
                # never mistake a subagent transcript for the main one.
                result.transcripts = [main_records] + agent_groups
        results.append(result)
    return results
