"""AgentsviewDataSource — reads session data from the agentsview SQLite DB."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from prism.parser import (
    ParseResult,
    ProjectInfo,
    project_path_to_encoded_name,
)


class AgentsviewDataSource:
    """Data source backed by an agentsview SQLite database."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def discover_projects(self) -> list[ProjectInfo]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT DISTINCT project FROM sessions"
            " WHERE deleted_at IS NULL"
            " ORDER BY project"
        ).fetchall()
        projects: list[ProjectInfo] = []
        for row in rows:
            project_path = row["project"]
            encoded = project_path_to_encoded_name(project_path)
            projects.append(ProjectInfo(
                encoded_name=encoded,
                project_dir=Path(f"agentsview://{encoded}"),
                session_files=[],
            ))
        return projects

    def load_sessions(self, project: ProjectInfo) -> list[ParseResult]:
        raise NotImplementedError("Phase 3b")

    def find_claude_md(self, project: ProjectInfo) -> Path | None:
        raise NotImplementedError("Phase 3d")
