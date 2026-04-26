"""Data source protocol and JSONL implementation for PRISM.

Defines the interface that all session backends must implement,
plus the default JSONL-backed implementation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from prism.parser import (
    CLAUDE_PROJECTS_DIR,
    ParseResult,
    ProjectInfo,
    discover_projects,
    load_all_sessions,
    parse_session_file,
)


@runtime_checkable
class SessionDataSource(Protocol):
    """Backend-agnostic interface for session data access."""

    def discover_projects(self) -> list[ProjectInfo]: ...

    def load_sessions(self, project: ProjectInfo) -> list[ParseResult]: ...

    def find_claude_md(self, project: ProjectInfo) -> Path | None: ...


class JSONLDataSource:
    """Default data source that reads raw JSONL session files."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = base_dir or CLAUDE_PROJECTS_DIR

    def discover_projects(self) -> list[ProjectInfo]:
        return discover_projects(self._base_dir)

    def load_sessions(self, project: ProjectInfo) -> list[ParseResult]:
        return load_all_sessions(project)

    def find_claude_md(self, project: ProjectInfo) -> Path | None:
        for session_file in project.session_files[:3]:
            result = parse_session_file(session_file)
            if result.records:
                cwd = Path(result.records[0].cwd)
                candidate = cwd / "CLAUDE.md"
                if candidate.exists():
                    return candidate
        return None
