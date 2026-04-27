---
description: Analyze Claude Code session health using PRISM. Use when asked to check token usage, audit CLAUDE.md, understand why sessions are failing, or list projects.
---

# prism-analyze

Analyze Claude Code session health using PRISM.

## When to use
When the user asks to analyze their Claude Code sessions, check token usage,
audit their CLAUDE.md, understand why sessions are failing, list their
projects, or see what PRISM can see.

## Before running

First check if PRISM is installed:
```bash
prism --version
```

If the command is not found, install it first:
```bash
pip install prism-cc
```

Then verify it installed correctly:
```bash
prism --version
```

Once confirmed installed, proceed with the analysis.

## Usage

Run the analysis (reads JSONL from ~/.claude/projects/ by default):
```bash
prism analyze
```

If prism is not installed:
```bash
pip install prism-cc
prism analyze
```

For a specific project:
```bash
prism analyze --project <path>
```

For JSON output (useful for scripting):
```bash
prism analyze --json
```

For CLAUDE.md recommendations:
```bash
prism advise
```

List all projects PRISM can see:
```bash
prism projects
```

This prints each project name, session count, and last-active timestamp.
Use it when the user asks what projects PRISM has data for, or to confirm
that sessions are being recorded.

## Agentsview data source

If the user has [agentsview](https://github.com/wesm/agentsview) installed,
PRISM can read from its SQLite database instead of raw JSONL. This gives
real API token counts and agentsview's own health scores alongside PRISM's.

```bash
prism analyze --source agentsview
prism analyze --source agentsview --agentsview-db /path/to/sessions.db
prism analyze --source agentsview --json
```

DB path resolution when `--agentsview-db` is not specified:
`AGENTSVIEW_DATA_DIR` env → `AGENT_VIEWER_DATA_DIR` env → `~/.agentsview/sessions.db`

Use `--source agentsview` when the user mentions agentsview, asks for real
token counts, or wants richer session data. Use the default (no flag) when
they just want a quick analysis from raw session files.

## What PRISM shows
- Health scores (A-F) across 5 dimensions per project
- Token efficiency: CLAUDE.md re-read costs, compaction frequency
- Tool health: retry loops, edit-revert cycles, consecutive failures
- Context hygiene: compaction loss events, mid-task boundaries
- CLAUDE.md adherence: whether your rules are actually being followed
- Session continuity: resume success rate, truncated sessions

## Output
PRISM prints a health report table and top issues per project.
Run `prism` (no args) to open the interactive TUI dashboard.
Run `prism dashboard` to open the HTML dashboard in your browser.
