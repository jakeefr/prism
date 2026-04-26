"""Shared test fixtures for PRISM tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


def build_test_db(db_path: Path) -> None:
    """Create a minimal agentsview SQLite DB matching the real schema.

    Column names and types mirror github.com/wesm/agentsview internal/db/schema.sql.
    Only DEFAULT clauses relevant to test correctness are included.
    """
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            project TEXT NOT NULL,
            machine TEXT NOT NULL DEFAULT 'local',
            agent TEXT NOT NULL DEFAULT 'claude',
            first_message TEXT,
            display_name TEXT,
            started_at TEXT,
            ended_at TEXT,
            message_count INTEGER NOT NULL DEFAULT 0,
            user_message_count INTEGER NOT NULL DEFAULT 0,
            file_path TEXT,
            file_size INTEGER,
            file_mtime INTEGER,
            file_inode INTEGER,
            file_device INTEGER,
            file_hash TEXT,
            local_modified_at TEXT,
            parent_session_id TEXT,
            relationship_type TEXT NOT NULL DEFAULT '',
            total_output_tokens INTEGER NOT NULL DEFAULT 0,
            peak_context_tokens INTEGER NOT NULL DEFAULT 0,
            has_total_output_tokens INTEGER NOT NULL DEFAULT 0,
            has_peak_context_tokens INTEGER NOT NULL DEFAULT 0,
            is_automated INTEGER NOT NULL DEFAULT 0,
            tool_failure_signal_count INTEGER NOT NULL DEFAULT 0,
            tool_retry_count INTEGER NOT NULL DEFAULT 0,
            edit_churn_count INTEGER NOT NULL DEFAULT 0,
            consecutive_failure_max INTEGER NOT NULL DEFAULT 0,
            outcome TEXT NOT NULL DEFAULT 'unknown',
            outcome_confidence TEXT NOT NULL DEFAULT 'low',
            ended_with_role TEXT NOT NULL DEFAULT '',
            final_failure_streak INTEGER NOT NULL DEFAULT 0,
            signals_pending_since TEXT,
            compaction_count INTEGER NOT NULL DEFAULT 0,
            mid_task_compaction_count INTEGER NOT NULL DEFAULT 0,
            context_pressure_max REAL,
            health_score INTEGER,
            health_grade TEXT,
            has_tool_calls INTEGER NOT NULL DEFAULT 0,
            has_context_data INTEGER NOT NULL DEFAULT 0,
            data_version INTEGER NOT NULL DEFAULT 0,
            cwd TEXT NOT NULL DEFAULT '',
            git_branch TEXT NOT NULL DEFAULT '',
            source_session_id TEXT NOT NULL DEFAULT '',
            source_version TEXT NOT NULL DEFAULT '',
            parser_malformed_lines INTEGER NOT NULL DEFAULT 0,
            is_truncated INTEGER NOT NULL DEFAULT 0,
            deleted_at TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            thinking_text TEXT NOT NULL DEFAULT '',
            timestamp TEXT,
            has_thinking INTEGER NOT NULL DEFAULT 0,
            has_tool_use INTEGER NOT NULL DEFAULT 0,
            content_length INTEGER NOT NULL DEFAULT 0,
            is_system INTEGER NOT NULL DEFAULT 0,
            model TEXT NOT NULL DEFAULT '',
            token_usage TEXT NOT NULL DEFAULT '',
            context_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            has_context_tokens INTEGER NOT NULL DEFAULT 0,
            has_output_tokens INTEGER NOT NULL DEFAULT 0,
            claude_message_id TEXT NOT NULL DEFAULT '',
            claude_request_id TEXT NOT NULL DEFAULT '',
            source_type TEXT NOT NULL DEFAULT '',
            source_subtype TEXT NOT NULL DEFAULT '',
            source_uuid TEXT NOT NULL DEFAULT '',
            source_parent_uuid TEXT NOT NULL DEFAULT '',
            is_sidechain INTEGER NOT NULL DEFAULT 0,
            is_compact_boundary INTEGER NOT NULL DEFAULT 0,
            UNIQUE(session_id, ordinal)
        );
        CREATE TABLE tool_calls (
            id INTEGER PRIMARY KEY,
            message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
            session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            tool_name TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT '',
            tool_use_id TEXT,
            input_json TEXT,
            skill_name TEXT,
            result_content_length INTEGER,
            result_content TEXT,
            subagent_session_id TEXT
        );
    """)
    conn.close()
