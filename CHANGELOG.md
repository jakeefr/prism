# Changelog

## 0.4.0 — 2026-06-03

Your scores may shift relative to 0.3.x. That is because measurements got
more accurate, not because grading got more lenient: real token counts, a
corrected CLAUDE.md cost model, real-turn counting, gated resume detection,
is_error-based error detection, and subagent-aware metrics. All output
fields keep their names, types, and structure. Only the computed values
change.

### Changed (metric accuracy)

- **Real token counts on the JSONL backend.** Assistant records now use
  `message.usage.output_tokens` (present on current Claude Code sessions)
  instead of the chars/4 estimate, matching the agentsview backend. Falls
  back to the estimate when usage is absent. Shifts Token Efficiency.
- **CLAUDE.md cost modeled as injection, not re-reads.** CLAUDE.md is loaded
  once per session (plus once per compaction), not once per tool call. The
  old model overstated waste by orders of magnitude on tool-heavy sessions.
  Trivial stub sessions (under 2k tokens of activity) are excluded from both
  the per-session issue and the waste score. Raises Token Efficiency.
- **Turns are real user prompts.** Turn counting previously included every
  tool-result record, making tool-heavy sessions look 5-10x longer; the
  100-turn warning now fires on actual user prompts. Raises Context Hygiene
  on tool-heavy projects.
- **Context-loss phrases only checked on resumed sessions.** Fresh sessions
  opening with "let me start by..." are no longer counted as context loss.
  Raises Session Continuity.
- **Tool failures use the `is_error` flag when present.** Prose matching
  ("error", "failed") misfired on text like "0 errors"; the flag is now
  authoritative when a tool result carries one, with prose matching kept as
  fallback for older files and the agentsview backend. Shifts Tool Health.
- **Subagent transcripts attached to parent sessions.** Transcripts under
  `<session-uuid>/subagents/` (current Claude Code layout) now merge into
  their parent session, so subagent token usage and sidechain metrics count
  again. Session counts are unchanged; agent files are not sessions. Each
  transcript is analyzed independently for order-sensitive detections
  (retry loops, failure streaks), so nothing chains across the seam between
  transcripts. A truncated subagent transcript marks the session truncated.
  Compactions are counted from the main transcript only.

### Fixed

- **`analyze --json` emitted corrupt JSON.** Output was printed through the
  rich console, which wraps lines at terminal width (80 on non-TTY),
  injecting raw newlines inside JSON string literals whenever an issue
  description exceeded about 80 chars, and interprets `[bracket]` text in
  descriptions as markup, silently stripping it. Either corruption breaks
  `JSON.parse` in downstream consumers. Now printed plain. A contract
  regression test locks in valid round-trippable output and the fields
  consumers parse.
- **Bare-string message content was dropped by the parser.** Recent Claude
  Code versions emit some messages (continuations, command caveats, plain
  prompts) with `message.content` as a string instead of a block array. The
  parser produced no content blocks for these, so continuation/resume/
  interrupted classification never fired on the JSONL backend. A bare string
  now parses as a single text block.

## 0.3.1 — 2026-06-03

### Fixed

- **`click` declared as a direct dependency.** `cli.py` imports `click`
  directly but relied on typer pulling it in. Typer 0.26 dropped its click
  dependency, so a fresh `pip install prism-cc` failed at startup with
  `ModuleNotFoundError`. (#8c0c007)

## 0.3.0 — 2026-04-26

Agentsview integration: PRISM can now read sessions from the
[agentsview](https://github.com/wesm/agentsview) SQLite database as an
alternative to raw JSONL parsing.

### Added

- **`--source agentsview` flag** on `analyze`, `advise`, and `dashboard`
  commands. Reads session data from the agentsview SQLite DB instead of
  parsing JSONL files directly.
- **`--agentsview-db` flag** to specify an explicit database path. Falls
  back to `AGENTSVIEW_DATA_DIR`, `AGENT_VIEWER_DATA_DIR`, then
  `~/.agentsview/sessions.db`.
- **`SessionDataSource` protocol** (`prism/datasource.py`) — backend-agnostic
  interface that both `JSONLDataSource` and `AgentsviewDataSource` implement.
- **`AgentsviewDataSource`** (`prism/agentsview.py`) — full adapter covering
  project discovery, session loading, record reconstruction, tool call
  enrichment, and CLAUDE.md discovery.
- **Real API token counts** — assistant records from agentsview carry the
  actual `output_tokens` count from the Claude API. `estimate_record_tokens`
  uses real counts when available, falling back to the chars/4 heuristic for
  JSONL-sourced records.
- **Health score cross-reference** — when using `--source agentsview`, the
  analyze output shows agentsview's own health_score, health_grade, and
  outcome alongside PRISM's grades (both Rich table and JSON output).

### Architecture

Built in 5 phases with full schema verification against upstream
`schema.sql`. Each phase preserved the existing test baseline and passed
roborev review before proceeding.

- Phase 1: SessionDataSource protocol
- Phase 2: JSONLDataSource refactor + analyzer datasource parameter
- Phase 3: AgentsviewDataSource adapter (connection, session loading,
  tool call enrichment, CLAUDE.md discovery)
- Phase 4: CLI `--source` flag + DB path discovery
- Phase 5: Real token counts + health score cross-reference

### Notes

- The `--source jsonl` path (default) is completely unchanged.
- `context_tokens` from agentsview is intentionally not used for per-record
  token estimation — it represents the full input window size per API call,
  not a per-message delta.
- Filtering passthrough (`--outcome`, `--min-score`, etc.) deferred to a
  future release.

## 0.2.1

Initial public release with JSONL parsing, five-dimension health scoring,
CLAUDE.md advisor, interactive TUI, and HTML dashboard.
