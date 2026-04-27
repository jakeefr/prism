"""AgentsviewDataSource — reads session data from the agentsview SQLite DB.

Schema reference: github.com/wesm/agentsview internal/db/schema.sql
Local test fixture: tests/conftest.py build_test_db()
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from pathlib import Path

from prism.parser import (
    AssistantRecord,
    ContentBlock,
    ParseResult,
    ProjectInfo,
    SessionRecord,
    SystemRecord,
    UserRecord,
    classify_system_message,
    project_path_to_encoded_name,
)


def _envelope_kwargs(row: sqlite3.Row, session_cwd: str, session_version: str,
                     session_git_branch: str) -> dict:
    """Extract Envelope constructor kwargs from a messages row.

    cwd, version, and git_branch live on the sessions table in the real schema,
    so they must be passed in from the caller.
    """
    return {
        "uuid": row["source_uuid"] or "",
        "parent_uuid": row["source_parent_uuid"] or None,
        "is_sidechain": bool(row["is_sidechain"]),
        "session_id": row["session_id"],
        "timestamp": row["timestamp"] or "",
        "version": session_version,
        "cwd": session_cwd,
        "git_branch": session_git_branch or None,
        "type": row["role"] or "",
        "raw": {},
    }


def _row_to_record(row: sqlite3.Row, session_cwd: str, session_version: str,
                   session_git_branch: str) -> SessionRecord | None:
    """Convert a messages table row to a typed SessionRecord."""
    kwargs = _envelope_kwargs(row, session_cwd, session_version, session_git_branch)
    content_text = row["content"] or ""

    if row["is_compact_boundary"]:
        kwargs["type"] = "system"
        return SystemRecord(**kwargs, subtype="compact_boundary", summary=content_text[:200])

    if row["is_system"]:
        kwargs["type"] = "system"
        subtype = classify_system_message(content_text)
        return SystemRecord(**kwargs, subtype=subtype, summary=content_text[:200])

    role = row["role"]
    blocks = [ContentBlock(type="text", text=content_text)] if content_text else []

    if role == "assistant":
        if row["has_output_tokens"]:
            kwargs["actual_tokens"] = row["output_tokens"]
        return AssistantRecord(**kwargs, content=blocks)
    if role == "user":
        return UserRecord(**kwargs, content=blocks)
    if role == "system":
        return SystemRecord(**kwargs, subtype=None, summary=content_text[:200])

    return None


def _enrich_with_tool_calls(
    records: list[SessionRecord],
    record_msg_ids: list[int],
    conn: sqlite3.Connection,
) -> None:
    """Inject tool_use and tool_result ContentBlocks from the tool_calls table.

    record_msg_ids must be parallel to records (same length, same order).
    IDs are integers matching messages.id in the real schema.
    """
    if not record_msg_ids:
        return
    unique_ids = list(set(record_msg_ids))
    placeholders = ",".join("?" * len(unique_ids))
    tc_rows = conn.execute(
        f"SELECT * FROM tool_calls WHERE message_id IN ({placeholders})"
        " ORDER BY id",
        unique_ids,
    ).fetchall()
    if not tc_rows:
        return

    tc_by_msg: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for row in tc_rows:
        tc_by_msg[row["message_id"]].append(row)

    pending_results: list[ContentBlock] = []
    for rec, mid in zip(records, record_msg_ids):
        if isinstance(rec, UserRecord) and pending_results:
            rec.content.extend(pending_results)
            pending_results = []
        if isinstance(rec, AssistantRecord) and mid in tc_by_msg:
            for tc in tc_by_msg[mid]:
                tool_input = _parse_input_json(tc["input_json"])
                rec.content.append(ContentBlock(
                    type="tool_use",
                    tool_id=tc["tool_use_id"],
                    tool_name=tc["tool_name"],
                    tool_input=tool_input,
                ))
                if tc["result_content"] is not None:
                    pending_results.append(ContentBlock(
                        type="tool_result",
                        tool_use_id=tc["tool_use_id"],
                        tool_content=tc["result_content"],
                    ))
    # Flush trailing tool results to the last UserRecord.
    # Dropped if no UserRecord exists (assistant-only session).
    if pending_results:
        for rec in reversed(records):
            if isinstance(rec, UserRecord):
                rec.content.extend(pending_results)
                break


def _parse_input_json(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        result = json.loads(raw)
        return result if isinstance(result, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


class AgentsviewDataSource:
    """Data source backed by an agentsview SQLite database."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._project_paths: dict[str, str] = {}  # encoded_name → original DB path

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> AgentsviewDataSource:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def discover_projects(self) -> list[ProjectInfo]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT DISTINCT project FROM sessions"
            " WHERE deleted_at IS NULL AND project IS NOT NULL AND project != ''"
            " ORDER BY project"
        ).fetchall()
        projects: list[ProjectInfo] = []
        for row in rows:
            project_path = row["project"]
            encoded = project_path_to_encoded_name(project_path)
            self._project_paths[encoded] = project_path
            # Synthetic non-filesystem path — agentsview projects have no local directory
            projects.append(ProjectInfo(
                encoded_name=encoded,
                project_dir=Path(f"agentsview://{encoded}"),
                session_files=[],
            ))
        return projects

    def _resolve_project_path(self, encoded_name: str) -> str:
        """Get the original DB project path from encoded_name."""
        if encoded_name in self._project_paths:
            return self._project_paths[encoded_name]
        # Fallback: query DB directly for the original path
        conn = self._connect()
        rows = conn.execute(
            "SELECT DISTINCT project FROM sessions"
            " WHERE project IS NOT NULL AND deleted_at IS NULL"
        ).fetchall()
        for row in rows:
            if project_path_to_encoded_name(row["project"]) == encoded_name:
                self._project_paths[encoded_name] = row["project"]
                return row["project"]
        return ""

    def load_sessions(self, project: ProjectInfo) -> list[ParseResult]:
        project_path = self._resolve_project_path(project.encoded_name)
        if not project_path:
            return []
        conn = self._connect()
        session_rows = conn.execute(
            "SELECT id, cwd, git_branch, source_version FROM sessions"
            " WHERE project = ? AND deleted_at IS NULL",
            (project_path,),
        ).fetchall()
        if not session_rows:
            return []

        session_info: dict[str, sqlite3.Row] = {r["id"]: r for r in session_rows}
        session_ids = list(session_info.keys())
        placeholders = ",".join("?" * len(session_ids))
        msg_rows = conn.execute(
            f"SELECT * FROM messages WHERE session_id IN ({placeholders})"
            " ORDER BY session_id, ordinal",
            session_ids,
        ).fetchall()

        grouped: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in msg_rows:
            grouped[row["session_id"]].append(row)

        # Order sessions by latest message timestamp (most recent first)
        def _latest_ts(sid: str) -> str:
            msgs = grouped.get(sid, [])
            return msgs[-1]["timestamp"] if msgs else ""

        results: list[ParseResult] = []
        for sid in sorted(session_ids, key=_latest_ts, reverse=True):
            sinfo = session_info[sid]
            s_cwd = sinfo["cwd"] or ""
            s_version = sinfo["source_version"] or ""
            s_branch = sinfo["git_branch"]
            pairs = [
                (row["id"], _row_to_record(row, s_cwd, s_version, s_branch))
                for row in grouped.get(sid, [])
            ]
            msg_ids = [mid for mid, rec in pairs if rec is not None]
            records = [rec for _, rec in pairs if rec is not None]
            _enrich_with_tool_calls(records, msg_ids, conn)
            results.append(ParseResult(
                path=Path(f"agentsview://{sid}.jsonl"),
                records=records,
            ))
        return results

    def find_claude_md(self, project: ProjectInfo) -> Path | None:
        project_path = self._resolve_project_path(project.encoded_name)
        if not project_path:
            return None
        # Try the project path itself first
        candidate = Path(project_path) / "CLAUDE.md"
        if candidate.exists():
            return candidate
        # cwd lives on sessions, not messages — get the most recent session's cwd
        conn = self._connect()
        row = conn.execute(
            "SELECT cwd FROM sessions"
            " WHERE project = ? AND deleted_at IS NULL"
            " AND cwd IS NOT NULL AND cwd != ''"
            " ORDER BY created_at DESC LIMIT 1",
            (project_path,),
        ).fetchone()
        if row:
            candidate = Path(row["cwd"]) / "CLAUDE.md"
            if candidate.exists():
                return candidate
        return None
