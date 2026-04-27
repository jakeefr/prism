# PRISM

Post-session diagnostic CLI for Claude Code. Parses session data, scores it
across five health dimensions, and surfaces actionable fixes via a CLI report,
interactive TUI, or HTML dashboard.

## Health Dimensions

1. **Token Efficiency** — compaction rate, token waste, CLAUDE.md bloat
2. **Tool Health** — retry loops, interactive commands, migration edits, consecutive failures
3. **Context Hygiene** — compaction frequency, mid-task compaction, context pressure
4. **CLAUDE.md Adherence** — rule extraction, violation detection, attention curve
5. **Session Continuity** — truncation, context loss across continuations

## Architecture

```
JSONL files ─┐
             ├─ SessionDataSource ─→ analyzer ─→ advisor ─→ CLI / TUI / dashboard
agentsview DB┘
```

The `SessionDataSource` protocol (`datasource.py`) abstracts over two backends:
- `JSONLDataSource` — reads raw `.jsonl` session files from `~/.claude/projects/`
- `AgentsviewDataSource` — reads from the agentsview SQLite DB

The parser produces typed records (`UserRecord`, `AssistantRecord`, `SystemRecord`).
The analyzer computes metrics from those records. The advisor generates CLAUDE.md
recommendations from the metrics. The CLI, TUI, and dashboard are thin presentation
layers.

## Key Files

| File | Purpose |
|------|---------|
| `prism/parser.py` | JSONL parsing, record dataclasses. No analysis. |
| `prism/analyzer.py` | All metrics computation. No I/O (except CLAUDE.md read). |
| `prism/advisor.py` | Recommendation generation from analyzer output. |
| `prism/datasource.py` | `SessionDataSource` protocol + `JSONLDataSource`. |
| `prism/agentsview.py` | `AgentsviewDataSource` — SQLite adapter for agentsview. |
| `prism/cli.py` | Typer CLI. Thin layer calling analyzer/advisor/app. |
| `prism/app.py` | Textual TUI. Imports widgets from `prism/widgets/`. |
| `prism/dashboard.py` | Single-file HTML dashboard generator. |

## Data Sources

**JSONL (default):**
```
prism analyze                          # reads ~/.claude/projects/
prism analyze --base-dir /other/path   # override base directory
prism analyze --project /path/to/proj  # single project
```

**Agentsview:**
```
prism analyze --source agentsview                      # auto-discover DB
prism analyze --source agentsview --agentsview-db X.db  # explicit path
```

DB path resolution: `--agentsview-db` flag > `AGENTSVIEW_DATA_DIR` env >
`AGENT_VIEWER_DATA_DIR` env > `~/.agentsview/sessions.db`.

When using `--source agentsview`, `--project` and `--base-dir` are rejected.
The agentsview adapter also surfaces health_score/health_grade/outcome from
the agentsview DB alongside PRISM's own grades.

## Commands

- `prism analyze` — health report (table or `--json`)
- `prism advise` — CLAUDE.md recommendations (`--apply` to write)
- `prism dashboard` — generate HTML dashboard (`--serve` for localhost)
- `prism replay <session>` — interactive timeline of a single session
- `prism watch` — live-watch active sessions
- `prism projects` — list projects with session counts

## Development

```
pip install -e ".[dev]"   # or: uv sync --dev
pytest                    # 181 tests
python -m prism           # run locally
```

## Rules

- Never mix parsing and analysis — parser returns raw records, analyzer computes metrics
- Never hardcode `~/.claude` path — use `Path.home() / ".claude"` and make it configurable
- Always handle malformed JSONL gracefully — skip bad lines, never crash
- Use `Path` objects throughout, never string concatenation for paths
- Textual widgets must not import from cli.py — no circular deps
- Run `pytest` before marking any task done
- New code must have corresponding tests before committing
