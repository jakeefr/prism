# PRISM — Build Specification
> Hand this entire document to Claude Code and say: "Build this project exactly as specified."

---

## What We're Building

PRISM is a Python CLI tool that reads Claude Code's session JSONL files from `~/.claude/projects/` and does three things no existing tool does:

1. **Diagnoses** why your sessions are failing (token drain, retry loops, compaction losses, CLAUDE.md drift)
2. **Scores** each project on a health dashboard (5 dimensions, letter grade A–F)
3. **Advises** — outputs a concrete diff of what to add, change, or remove from your CLAUDE.md

Users install it once. They keep using Claude Code exactly as normal. They run `prism` or `prism analyze` to get insights.

---

## Tech Stack

- **Language:** Python 3.11+
- **TUI Framework:** Textual (v0.80+) — full interactive dashboard
- **Output/formatting:** Rich (v14+) — for non-interactive CLI output
- **CLI:** Typer
- **Testing:** pytest
- **Packaging:** pyproject.toml with uv compatibility
- **License:** MIT

Install commands to support:
```bash
pip install prism-cc
pipx install prism-cc
```

---

## Project Structure

```
prism/
├── prism/
│   ├── __init__.py
│   ├── cli.py                  # Typer entry point, all commands
│   ├── parser.py               # JSONL parser for all session record types
│   ├── analyzer.py             # Core analysis engine, all metrics
│   ├── advisor.py              # CLAUDE.md diff/recommendation generator
│   ├── app.py                  # Textual TUI application (main dashboard)
│   ├── widgets/
│   │   ├── __init__.py
│   │   ├── health_card.py      # Project health score widget
│   │   ├── session_list.py     # Scrollable session browser
│   │   ├── timeline.py         # Session replay/scrub timeline
│   │   ├── advisor_panel.py    # CLAUDE.md recommendations panel
│   │   ├── metrics_bar.py      # Token usage sparklines/bars
│   │   └── live_watcher.py     # Real-time session file watcher
│   └── styles/
│       └── prism.tcss          # Textual CSS stylesheet
├── tests/
│   ├── fixtures/
│   │   ├── sample_session.jsonl        # Realistic sample with tool calls
│   │   ├── session_with_compaction.jsonl
│   │   └── session_with_retries.jsonl
│   ├── test_parser.py
│   ├── test_analyzer.py
│   └── test_advisor.py
├── README.md
├── pyproject.toml
├── CLAUDE.md
└── LICENSE
```

---

## JSONL Format Reference

Claude Code writes session files to `~/.claude/projects/<encoded-path>/<session-id>.jsonl`.

Each line is a JSON record. Common envelope fields on every record:

```json
{
  "uuid": "string",
  "parentUuid": "string | null",
  "isSidechain": false,
  "sessionId": "string",
  "timestamp": "2026-01-15T14:23:11.000Z",
  "version": "2.1.98",
  "cwd": "/home/user/myproject",
  "gitBranch": "main",
  "type": "user | assistant | system"
}
```

### Record Types

**User message:**
```json
{
  "type": "user",
  "message": {
    "role": "user",
    "content": [{ "type": "text", "text": "..." }]
  }
}
```

**Assistant message:**
```json
{
  "type": "assistant",
  "message": {
    "role": "assistant",
    "content": [
      { "type": "thinking", "thinking": "" },
      { "type": "text", "text": "..." },
      {
        "type": "tool_use",
        "id": "toolu_xxx",
        "name": "Bash",
        "input": { "command": "npm test" }
      }
    ]
  }
}
```

**Tool result (user record following tool_use):**
```json
{
  "type": "user",
  "message": {
    "role": "user",
    "content": [{
      "type": "tool_result",
      "tool_use_id": "toolu_xxx",
      "content": "..."
    }]
  }
}
```

**System / compaction boundary:**
```json
{
  "type": "system",
  "subtype": "compact_boundary",
  "summary": "..."
}
```

**Known issues to handle gracefully:**
- Concurrent write corruption: truncated lines, malformed JSON — skip and continue
- Thinking text stripped since v2.1.72: `thinking` field is `""`, signature present — don't error
- Token usage not in JSONL as top-level field — derive from content length estimates

---

## CLI Commands

### `prism` (default — opens TUI)
```
prism
```
Opens the full Textual interactive dashboard. Default view: project list with health scores.

### `prism analyze [--project PATH] [--json]`
```
prism analyze
prism analyze --project ~/myproject
prism analyze --json > report.json
```
Non-interactive. Prints a Rich-formatted health report for all projects (or one project). Shows scores, top issues, key metrics. Exits when done.

### `prism advise [--project PATH] [--apply]`
```
prism advise
prism advise --project ~/myproject
prism advise --apply   # writes changes directly to CLAUDE.md with confirmation prompt
```
Prints concrete CLAUDE.md recommendations as a colored diff. With `--apply`, asks for confirmation then writes them.

### `prism replay <session-id-or-path>`
```
prism replay abc123
prism replay ~/.claude/projects/xyz/abc123.jsonl
```
Opens a Textual timeline view of a single session. Scrub through turns, see tool calls, token costs per turn, compaction boundaries highlighted.

### `prism watch`
```
prism watch
```
Live mode. Watches `~/.claude/projects/` for active session file changes. Shows a real-time dashboard of the current session: current token count, tool calls this session, estimated cost, compaction risk warning.

### `prism projects`
```
prism projects
```
Lists all Claude Code projects found with session counts and last-used dates. Quick summary table.

---

## Analysis Engine — What to Measure

### 1. Token Efficiency Score (A–F)

Metrics:
- **CLAUDE.md re-read cost**: Each tool call reads CLAUDE.md. Count how many tool calls per session × estimated CLAUDE.md token size. Flag if >15% of session tokens are CLAUDE.md re-reads.
- **Cache hit estimation**: Look at consecutive tool calls with identical `cwd` — cache misses show as elevated input sizes. Track patterns.
- **Compaction frequency**: How many `compact_boundary` records per session. More than 1 per session is a warning sign.
- **Sidechain fragmentation**: Count `isSidechain: true` records. High sidechain ratio means wasted context branches.

### 2. Tool Call Health Score (A–F)

Metrics:
- **Retry loops**: Detect consecutive `tool_use` records for the same tool with the same or similar input. 3+ in a row = retry loop.
- **Edit-revert cycles**: Detect `Write` or `Edit` tool call followed within 3 turns by another `Write`/`Edit` to the same file = revert.
- **Consecutive failures**: Tool results containing `error`, `Error`, `failed`, `FAILED`, `exit code 1` — count consecutive failures. More than 3 = problem pattern.
- **Bash interactive calls**: Detect `Bash` tool calls with commands that would hang waiting for input (commands without `-y`, `--yes`, `-n`, `--non-interactive` flags on known interactive tools like `apt`, `npm init`, `git commit` without `-m`).

### 3. Context Hygiene Score (A–F)

Metrics:
- **Compaction loss events**: Each `compact_boundary` = potential context loss. Check if similar tool calls repeat after boundary (signs of re-doing work).
- **Session length vs. task completion**: Very long sessions (>100 turns) with no clear completion signal = context drift.
- **Mid-task compaction**: If `compact_boundary` appears in the middle of a multi-step task sequence = bad. Track by checking if tool calls after boundary repeat patterns from before.

### 4. CLAUDE.md Adherence Score (A–F)

This is the most novel metric — nothing else does this.

Strategy:
- Parse the project's CLAUDE.md and extract rule-like statements (lines starting with "Never", "Always", "Don't", "Use", "Avoid", "Run", "NEVER", "ALWAYS", imperative sentences)
- For each rule, check session tool calls and assistant text for violations:
  - "Never use `any` in TypeScript" → scan Edit/Write tool content for `: any`
  - "Run tests non-interactively" → scan Bash calls for interactive test commands
  - "Never edit migration files" → scan Write/Edit calls for files matching `migration*` or `*/migrations/*`
  - "Always run `make test` before finishing" → check if last N turns of session include a Bash call with `make test`
- Track: rules followed vs. rules violated vs. rules that appear to be ignored entirely (no evidence either way)
- The "Mr. Tinkleberry test": warn if CLAUDE.md is over 80 lines — adherence degrades

### 5. Session Continuity Score (A–F)

Metrics:
- **Resume success rate**: Count sessions that start with a `--resume` or `--continue` signal (look for system records indicating continuation) vs. those that appear to start fresh despite being in the same project.
- **Context loss on resume**: After a resume, do the first 3 assistant turns repeat information/questions that were already established? (Pattern match for "what is", "can you describe", "first let me understand" type phrases in early assistant turns of resumed sessions)
- **Session file completeness**: Check for truncated JSONL (last line not valid JSON = write interrupted)

---

## The Advisor — CLAUDE.md Diff Output

After analysis, the advisor generates specific recommendations. Format:

```
╭─────────────────────────────────────────────────────────────╮
│  PRISM ADVISOR — recommendations for .claude/CLAUDE.md      │
╰─────────────────────────────────────────────────────────────╯

  ✦ ADD  (High impact — fixes 14 retry loops across 6 sessions)
    "Always use non-interactive flags: --yes, -y, --non-interactive"

  ✦ ADD  (High impact — 3 edit-revert cycles on migration files)  
    "NEVER edit existing migration files — always create new ones"

  ✦ TRIM  (208k tokens wasted — Claude ignores these anyway)
    Remove lines 45–67: personality/tone instructions
    Claude Code's system prompt handles this; these lines cost tokens silently

  ✦ WARN  (Adherence degrading)
    Your CLAUDE.md is 94 lines — rules after line ~80 show 60% adherence drop
    Consider moving rarely-needed rules to .claude/rules/ subdirectory files

  ✦ RESTRUCTURE  (Token efficiency)
    Move these 3 rules to src/CLAUDE.md (only loaded when touching src/):
    - "Use functional components only in React"
    - "Import from @/components, never relative paths"  
    - "Run bun run typecheck after any TypeScript changes"
```

Rules for generating advice:
- Only recommend things with session evidence — never generic advice
- Always cite which sessions/sessions count triggered the recommendation
- Always explain the token or quality cost of NOT doing it
- `--apply` mode writes a new CLAUDE.md with adds inserted at the top of relevant sections, trims marked with comments, warns before destructive changes

---

## Textual TUI Layout

### Main Dashboard (default view)

```
┌─────────────────────────────────────────────────────────────────┐
│  ◈ PRISM  │  Projects  │  Sessions  │  Advisor  │  Live         │
├───────────┴─────────────────────────────────────────────────────┤
│                                                                   │
│  YOUR PROJECTS                          HEALTH SCORES            │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ ● myproject          last: 2h ago    ████████░░  B+  │   │
│  │ ● api-server         last: 1d ago    ██████░░░░  C+  │   │
│  │ ○ old-experiment     last: 2w ago    ████░░░░░░  D   │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                   │
│  SELECTED: myproject                                              │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐               │
│  │ Token Eff.  │ │ Tool Health │ │ Ctx Hygiene │               │
│  │     B+      │ │     A-      │ │     C       │               │
│  │ 23 sessions │ │ 2 loops     │ │ 4 compact.  │               │
│  └─────────────┘ └─────────────┘ └─────────────┘               │
│  ┌─────────────┐ ┌─────────────┐                                │
│  │ MD Adherence│ │ Continuity  │                                │
│  │     D+      │ │     B       │                                │
│  │ 6 violated  │ │ 87% resume  │                                │
│  └─────────────┘ └─────────────┘                                │
│                                                                   │
│  TOP ISSUES:                                                      │
│  ! 14 retry loops — likely missing non-interactive flags         │
│  ! CLAUDE.md 94 lines — adherence degrading past line 80         │
│  ! 3 migration file edits detected (rule violation)              │
│                                                                   │
│  [A] Advise   [R] Replay last session   [W] Watch live           │
└─────────────────────────────────────────────────────────────────┘
```

### Session Timeline View (replay mode)

```
┌─────────────────────────────────────────────────────────────────┐
│  ← Back  │  Session: abc123  │  2026-04-10 14:23  │  87 turns   │
├──────────┴──────────────────────────────────────────────────────┤
│  TIMELINE                              TURN DETAIL               │
│  ┌─────────────────────────────┐  ┌──────────────────────────┐  │
│  │ ▶ T01  user        0.2k    │  │ Turn 23 — Bash           │  │
│  │   T02  assistant   1.4k    │  │ npm test --watch         │  │
│  │   T03  tool:Bash   0.1k    │  │                          │  │
│  │   T04  tool:result 0.8k    │  │ ⚠ INTERACTIVE FLAG       │  │
│  │ ▶ T05  assistant   2.1k    │  │ --watch will hang.       │  │
│  │ ░ T23  tool:Bash ⚠ 0.1k   │  │ This likely caused the   │  │
│  │ ░ T24  tool:result 0.4k    │  │ retry loop at T24-T26    │  │
│  │ ░ T25  tool:Bash ⚠ 0.1k   │  │                          │  │
│  │   ── compact_boundary ──   │  │ Tokens this turn: 0.1k   │  │
│  │   T51  assistant   3.2k    │  │ Cumulative: 34.2k        │  │
│  └─────────────────────────────┘  └──────────────────────────┘  │
│                                                                   │
│  ▲/▼ navigate   SPACE select   A annotate   Q quit               │
└─────────────────────────────────────────────────────────────────┘
```

### Advisor View

Full-screen diff panel with color-coded recommendations. Green = add, Red = remove, Yellow = warning. Keyboard shortcut `A` to apply.

### Live Watch View

Split panel: left = real-time session event stream, right = live metrics (token count climbing, tool call tally, compaction risk meter as a colored progress bar going red as context fills).

---

## Textual CSS (prism.tcss)

Use a dark, professional color scheme. Inspired by terminal tools like lazygit and btop.

```css
/* prism.tcss */
Screen {
    background: #0d1117;
    color: #e6edf3;
}

.health-card {
    border: round #30363d;
    padding: 1 2;
    background: #161b22;
}

.health-a { color: #3fb950; }
.health-b { color: #58a6ff; }
.health-c { color: #d29922; }
.health-d { color: #f85149; }
.health-f { color: #ff7b72; }

.advisor-add { color: #3fb950; }
.advisor-trim { color: #f85149; }
.advisor-warn { color: #d29922; }

.compact-boundary { color: #8b949e; background: #21262d; }
.retry-loop { color: #f85149; }
.interactive-flag { color: #d29922; }

Header { background: #161b22; color: #58a6ff; }
Footer { background: #161b22; color: #8b949e; }
```

Colors are GitHub Dark theme palette — familiar to developers, professional, readable.

---

## Error Handling

- Malformed/truncated JSONL lines: skip silently, log count of skipped lines at end
- Missing `~/.claude/projects/`: print friendly message "No Claude Code sessions found. Have you used Claude Code yet?"
- Permission errors on session files: skip that session, note in output
- Empty projects (no sessions): include in list with "No sessions yet"
- CLAUDE.md not found: skip adherence analysis for that project, note in output

---

## Test Fixtures

Create realistic sample JSONL fixtures covering:

`sample_session.jsonl`:
- 20 turns, mix of user/assistant/tool_use/tool_result
- 2 Bash calls, 1 Edit call, 1 Read call
- Normal successful session

`session_with_compaction.jsonl`:
- 60 turns
- 1 compact_boundary in the middle
- Tool calls after boundary that echo patterns from before (context loss signal)

`session_with_retries.jsonl`:
- 30 turns
- 3 consecutive Bash retry loops (same command, 3x)
- 1 interactive command (npm test --watch)
- 1 migration file edit

---

## pyproject.toml

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "prism-cc"
version = "0.1.0"
description = "Session intelligence for Claude Code — find why your sessions fail and fix them"
readme = "README.md"
license = { text = "MIT" }
requires-python = ">=3.11"
keywords = ["claude", "claude-code", "ai", "developer-tools", "tui"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Environment :: Console",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Topic :: Software Development :: Libraries :: Python Modules",
]
dependencies = [
    "textual>=0.80.0",
    "rich>=14.0.0",
    "typer>=0.12.0",
    "watchdog>=4.0.0",
]

[project.scripts]
prism = "prism.cli:app"

[project.urls]
Homepage = "https://github.com/YOUR_USERNAME/prism"
Repository = "https://github.com/YOUR_USERNAME/prism"
Issues = "https://github.com/YOUR_USERNAME/prism/issues"

[dependency-groups]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-textual-snapshot>=0.4.0",
]

[tool.hatch.build.targets.wheel]
packages = ["prism"]
```

---

## README.md Structure

Write a README with this exact section order (content TBD after build):

1. Title + one-liner: `PRISM — session intelligence for Claude Code`
2. Badges: PyPI version, license MIT, Python 3.11+, stars
3. **Demo GIF placeholder** — `<!-- demo gif goes here -->`
4. One-command install: `pip install prism-cc` and `pipx install prism-cc`
5. What it does (3 bullet points, no more)
6. Quick start (3 commands, each with expected output shown)
7. Features table (5 rows, one per health dimension)
8. How it works (short paragraph + diagram of the flow)
9. Contributing
10. License

---

## CLAUDE.md for This Project

```markdown
# PRISM

Python CLI tool. Session intelligence for Claude Code.

## Commands
- Run tests: `pytest`
- Install dev: `pip install -e ".[dev]"` or `uv sync --dev`
- Run locally: `python -m prism` or `prism` after install

## Structure
- `prism/parser.py` — all JSONL parsing logic, no analysis here
- `prism/analyzer.py` — all metrics calculation, no I/O here  
- `prism/advisor.py` — recommendation generation, reads analyzer output
- `prism/app.py` — Textual TUI, imports widgets from prism/widgets/
- `prism/cli.py` — Typer CLI, thin layer that calls analyzer/advisor/app

## Rules
- Never mix parsing and analysis — parser returns raw records, analyzer computes metrics
- Never hardcode `~/.claude` path — use `Path.home() / ".claude"` and make it configurable
- Always handle malformed JSONL gracefully — skip bad lines, never crash
- Use `Path` objects throughout, never string concatenation for paths
- Textual widgets must not import from cli.py — no circular deps
- Run `pytest` before marking any task done
```

---

## Build Order for Claude Code

Tell Claude Code to build in this order to avoid circular dependency issues:

1. `pyproject.toml` + `CLAUDE.md`
2. `prism/__init__.py` (version only)
3. `prism/parser.py` + tests/fixtures + `tests/test_parser.py`
4. `prism/analyzer.py` + `tests/test_analyzer.py`
5. `prism/advisor.py` + `tests/test_advisor.py`
6. `prism/styles/prism.tcss`
7. `prism/widgets/*.py` (all widgets)
8. `prism/app.py` (Textual app, imports widgets)
9. `prism/cli.py` (Typer, thin layer)
10. `README.md`
11. Run full `pytest` suite — fix any failures
12. Manual smoke test: `prism analyze` against real `~/.claude/projects/` if available

---

## First Message to Send Claude Code

Paste this verbatim as your first message:

```
Read PRISM_BUILD_SPEC.md in full before writing any code. 

Build the PRISM project exactly as specified. Start with pyproject.toml and CLAUDE.md, then follow the build order at the bottom of the spec. 

After each major step, run pytest to verify nothing is broken before moving on.

The session JSONL format is documented in the spec — use the exact field names specified. Handle malformed lines gracefully.

The Textual TUI is the centerpiece — it needs to look professional and polished. Use the GitHub Dark color palette from the spec's CSS section.
```
