"""JSONL parser for Claude Code session files.

Reads raw records from session JSONL files. No analysis here — just parsing.
Returns typed dataclasses for downstream analysis.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

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


@dataclass
class UserRecord(Envelope):
    """A user-role message (includes tool results)."""
    content: list[ContentBlock] = field(default_factory=list)


@dataclass
class AssistantRecord(Envelope):
    """An assistant-role message (text + tool_use blocks)."""
    content: list[ContentBlock] = field(default_factory=list)


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
    """Parse a content array from a message into ContentBlock objects."""
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
            blocks.append(ContentBlock(
                type="tool_result",
                tool_use_id=item.get("tool_use_id"),
                tool_content=item.get("content"),
            ))

        else:
            # Unknown block type — store as generic
            blocks.append(ContentBlock(type=block_type))

    return blocks


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
        return UserRecord(
            **envelope_kwargs,
            content=_parse_content_blocks(content_raw),
        )

    elif record_type == "assistant":
        message = data.get("message", {})
        content_raw = message.get("content", []) if isinstance(message, dict) else []
        return AssistantRecord(
            **envelope_kwargs,
            content=_parse_content_blocks(content_raw),
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
    def last_active(self) -> str | None:
        """Timestamp of the most recently modified session file."""
        if not self.session_files:
            return None
        newest = max(self.session_files, key=lambda p: p.stat().st_mtime)
        return newest.stat().st_mtime.__class__.__name__  # return mtime float str


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


def iter_session_records(path: Path) -> Iterator[SessionRecord]:
    """Convenience iterator over records in a single session file."""
    result = parse_session_file(path)
    yield from result.records


def load_all_sessions(project: ProjectInfo) -> list[ParseResult]:
    """Load and parse all session files for a project."""
    return [parse_session_file(f) for f in project.session_files]
